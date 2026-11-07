"""Verify a MarketFlow article against issuer-scoped OpenDART evidence."""

import calendar
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from html.parser import HTMLParser
from io import BytesIO
import json
import logging
import os
from pathlib import Path
import re
import time
import unicodedata
from zipfile import BadZipFile, ZipFile
from zlib import error as ZlibError

from dotenv import dotenv_values
import requests


_KST = timezone(timedelta(hours=9))
_API = 'https://opendart.fss.or.kr/api/'
_VIEWER = 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo='
_WINDOW = timedelta(days=3)
_DOCUMENT_LIMIT = 4 * 1024 * 1024
_METRICS = ('매출액', '영업이익', '법인세비용차감전계속사업이익', '당기순이익',
            '지배기업소유주지분순이익', '연결당기순이익')
_TERMS = {
    'earnings': ('실적', '분기보고서', '반기보고서', '사업보고서'),
    'contract': ('단일판매', '공급계약'),
    'capacity': ('시설투자', '유형자산'),
    'capital_policy': ('자기주식', '배당', '증자', '전환사채',
                       '특정증권등소유상황', '주식등의대량보유상황'),
    'risk': ('소송', '횡령', '배임', '회생', '영업정지'),
    'regulatory': ('투자판단관련', '주요경영사항'),
    'industry': (),
}
_CLAIM = re.compile(
    r'(?<![\w])(매출액?|영업이익|당기순이익|순이익)\s*(?:은|는|이|가|[:：])?\s*'
    r'([+-]?(?:\d[\d,]*(?:\.\d+)?\s*[조억만]\s*){1,3})(?:원)?'
)
_AMOUNT = re.compile(r'(\d[\d,]*(?:\.\d+)?)\s*([조억만])')
_SCALE = {'조': 10**12, '억': 10**8, '만': 10**4}
_UNIT = {'조원': 10**12, '억원': 10**8, '백만원': 10**6, '천원': 10**3, '원': 1}
_GLOBAL_STATUS = {'010', '011', '012', '020', '800', '901'}


class _SourceError(ValueError):
    pass


class _BudgetSpent(Exception):
    pass


def _name(value):
    cleaned = re.sub(r'\s+', '', unicodedata.normalize('NFKC', value)).casefold()
    return re.sub(r'^(?:주식회사|\(주\))|(?:주식회사|\(주\))$', '', cleaned)


def _day(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{8}', value):
        raise ValueError('invalid_filing_date')
    return date(int(value[:4]), int(value[4:6]), int(value[6:]))


def _credentials(root):
    key = (os.getenv('DART_API_KEY') or '').strip()
    if key:
        return key
    # python-dotenv can warn about malformed lines. Disable warnings so a
    # malformed configuration never writes credentials to a worker log.
    logger = logging.getLogger('dotenv.main')
    quiet = logger.disabled
    try:
        logger.disabled = True
        return (dotenv_values(root / '.env', interpolate=False).get('DART_API_KEY') or '').strip()
    finally:
        logger.disabled = quiet


def _http_get(url, params, *, limit, deadline):
    remaining = max(0.1, deadline - time.monotonic())
    timeout = (min(2.5, remaining), min(4, remaining))
    with requests.Session() as session:
        session.trust_env = False
        with session.get(url, params=params, stream=True, timeout=timeout, allow_redirects=False) as response:
            if response.status_code != 200:
                raise _SourceError('http_error')
            body = bytearray()
            for chunk in response.iter_content(chunk_size=64 * 1024):
                body.extend(chunk)
                if len(body) > limit or time.monotonic() > deadline:
                    raise _SourceError('response_limit')
    return bytes(body)


class _DocumentText(HTMLParser):
    def __init__(self):
        super().__init__()
        self._ignore = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ('style', 'script'):
            self._ignore += 1

    def handle_endtag(self, tag):
        if tag in ('style', 'script'):
            self._ignore = max(0, self._ignore - 1)

    def handle_data(self, data):
        if self._ignore == 0 and data.strip():
            self.parts.append(data.strip())


def _document_text(body, receipt):
    with ZipFile(BytesIO(body)) as archive:
        files = [info for info in archive.infolist() if not info.is_dir()]
        exact = [info for info in files if info.filename in {receipt + '.xml', receipt + '.html'}]
        selected = exact or files
        if (len(selected) != 1 or not selected[0].filename.lower().endswith(('.xml', '.html'))
                or not 0 < selected[0].file_size <= _DOCUMENT_LIMIT):
            raise ValueError('unsupported_document_archive')
        raw = archive.read(selected[0])
    try:
        decoded = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        decoded = raw.decode('cp949')
    if re.search(r'<!\s*(?:DOCTYPE|ENTITY)\b', decoded, re.IGNORECASE):
        raise ValueError('unsafe_document')
    if not re.search(r'</(?:document|html)>\s*$', decoded, re.IGNORECASE):
        raise ValueError('incomplete_document')
    parser = _DocumentText()
    parser.feed(decoded)
    parser.close()
    return parser.parts


def _period_matches(header, year, quarter):
    # Restrict evidence to the current period in the filing header. A prior
    # quarter on the same document is not the claimed current period.
    current = re.search(r'당기실적\s*(20\d{2})[-.](\d{2})[-.](\d{2})\s*[~～]\s*(20\d{2})[-.](\d{2})[-.](\d{2})', header)
    if current:
        first_year, first_month, first_day, last_year, last_month, last_day = map(int, current.groups())
        end_month = quarter * 3
        return (
            (first_year, first_month, first_day) == (year, end_month - 2, 1)
            and (last_year, last_month, last_day) == (year, end_month, calendar.monthrange(year, end_month)[1])
        )
    tokens = re.findall(r'(20\d{2})\s*[.년]\s*([1-4])\s*(?:Q|분기)', header)
    return bool(tokens and tuple(map(int, tokens[0])) == (year, quarter))


def _amount_in_filing(lines, metric, cumulative, multiplier):
    anchors = [i for i, line in enumerate(lines) if re.sub(r'\s+', '', line) == metric]
    if len(anchors) != 1:
        return None
    rows = []
    for line in lines[anchors[0] + 1:]:
        if re.sub(r'\s+', '', line) in _METRICS or re.match(r'\d+\.\s*정보', line):
            break
        rows.append(line)
    label = '누계실적' if cumulative else '당해실적'
    found = [i for i, row in enumerate(rows) if row.replace(' ', '') == label and i + 1 < len(rows)]
    if len(found) != 1:
        return None
    value = rows[found[0] + 1].replace(',', '')
    if not re.fullmatch(r'[+-]?\d+(?:\.\d+)?', value):
        return None
    return Decimal(value) * multiplier


def _basis_conflicts(title, report):
    consolidated = '연결재무제표' in ''.join(report.split())
    return bool(re.search(r'별도|개별', title)) if consolidated else '연결' in title


def _check_amounts(article, filing, lines):
    title = article['title']
    periods = set(re.findall(r'([1-4])\s*분기', title))
    years = set(re.findall(r'(20\d{2})\s*년', title))
    if (len(periods) != 1 or len(years) > 1 or len(article.get('entities') or ()) != 1
            or article['event'].get('certainty') in {'forecast', 'opinion'}
            or re.search(r'(?:지난해|작년|전년도?)\s*[1-4]\s*분기', title)):
        return []
    year = int(next(iter(years), str(datetime.fromisoformat(article['published_at']).astimezone(_KST).year)))
    quarter = int(next(iter(periods)))
    if _basis_conflicts(title, filing['report_nm']):
        return []
    first_metric = next((i for i, line in enumerate(lines) if re.sub(r'\s+', '', line) in _METRICS), len(lines))
    header = '\n'.join(lines[:first_metric])
    units = set(re.findall(r'단위\s*[:：]\s*(조원|억원|백만원|천원|원)', header))
    if len(units) != 1 or not _period_matches(header, year, quarter):
        return []
    multiplier = _UNIT[next(iter(units))]
    claims = []
    previous = 0
    for match in _CLAIM.finditer(title):
        amount = match.group(2).strip()
        context = title[previous:match.start()]
        previous = match.end()
        # Headline deltas and foreign currencies are not absolute KRW amounts.
        if re.match(r'\s*(?:달러|유로|엔|위안|불|증가|감소|개선|축소|늘어|줄어)', title[match.end():]):
            continue
        parts = _AMOUNT.findall(amount)
        if not parts or any(_SCALE[a[1]] <= _SCALE[b[1]] for a, b in zip(parts, parts[1:])):
            continue
        try:
            value = sum(Decimal(number.replace(',', '')) * _SCALE[scale] for number, scale in parts)
        except InvalidOperation:
            continue
        if amount.startswith('-'):
            value = -value
        last_number, scale = parts[-1]
        precision = len(last_number.partition('.')[2])
        tolerance = Decimal(_SCALE[scale]) / (2 * 10**precision)
        metric = {'매출': '매출액', '순이익': '당기순이익'}.get(match.group(1), match.group(1))
        cumulative = bool(re.search(r'누적|누계', context))
        official = _amount_in_filing(lines, metric, cumulative, multiplier)
        claims.append({
            'metric': metric, 'article_amount_krw': format(value, 'f'),
            'official_amount_krw': format(official, 'f') if official is not None else None,
            'verified': official is not None and abs(official - value) <= tolerance,
            'period': f'{year}Q{quarter}', 'basis': '누계' if cumulative else '당기',
        })
    return claims


class DisclosureVerifier:
    """Bounded OpenDART reads shared by one scheduled verification run."""

    def __init__(self, project_root, *, max_requests=8, max_seconds=35, transport=None):
        self.root = Path(project_root)
        self._remaining = max_requests
        self._deadline = time.monotonic() + max_seconds
        self._transport = transport or _http_get
        self._key = _credentials(self.root)
        self._catalogues = {}
        self._documents = {}
        self._blocked = None
        try:
            self._registry = json.loads((self.root / 'data/dart_corp_codes.json').read_bytes())
            if not isinstance(self._registry, dict):
                self._registry = None
        except (OSError, ValueError):
            self._registry = None

    def _get(self, endpoint, limit, **params):
        if self._blocked:
            raise _SourceError(self._blocked)
        if not self._key:
            raise _SourceError('dart_key_missing')
        if self._remaining <= 0 or time.monotonic() >= self._deadline:
            raise _BudgetSpent()
        self._remaining -= 1
        try:
            return self._transport(
                _API + endpoint, {'crtfc_key': self._key, **params},
                limit=limit, deadline=self._deadline,
            )
        except (requests.exceptions.RequestException, OSError):
            self._blocked = 'request_failed'
            raise _SourceError(self._blocked) from None

    def _catalogue(self, corp_code, start, end):
        key = (corp_code, start, end)
        if key not in self._catalogues:
            raw = self._get('list.json', 1024 * 1024, corp_code=corp_code,
                            bgn_de=start.strftime('%Y%m%d'), end_de=end.strftime('%Y%m%d'),
                            last_reprt_at='Y', page_no=1, page_count=100)
            body = json.loads(raw)
            if not isinstance(body, dict):
                raise _SourceError('invalid_catalogue')
            status = body.get('status')
            if status in _GLOBAL_STATUS:
                self._blocked = 'dart_status_' + status
            if status == '013':
                rows = []
            elif status != '000':
                raise _SourceError(self._blocked or 'invalid_catalogue')
            else:
                rows = body.get('list')
                if (not isinstance(rows, list) or not rows or len(rows) > 100
                        or any(not isinstance(row, dict) for row in rows)):
                    raise _SourceError('invalid_catalogue')
                if str(body.get('total_page')) != '1':
                    raise _SourceError('catalogue_page_limit')
            self._catalogues[key] = rows, sha256(raw).hexdigest()
        return self._catalogues[key]

    def _document(self, receipt, issuer):
        if receipt not in self._documents:
            body = self._get('document.xml', _DOCUMENT_LIMIT, rcept_no=receipt)
            self._documents[receipt] = _document_text(body, receipt), sha256(body).hexdigest()
        lines, digest = self._documents[receipt]
        if _name(issuer) not in _name(' '.join(lines)[:1000]):
            raise ValueError('document_issuer_mismatch')
        return lines, digest

    def verify(self, article, entity, now):
        result = {'status': 'no_matching_filing', 'checks': [],
                  'source': 'OpenDART', 'checked_at': now.isoformat()}
        try:
            symbol = entity['symbol']
            issuer = entity['name']
            title = article['title']
            published = datetime.fromisoformat(article['published_at'])
            kind = article['event']['type']
            if (not isinstance(symbol, str) or not re.fullmatch(r'[0-9A-Z]{6}', symbol) or symbol == '000000'
                    or not isinstance(title, str) or not isinstance(issuer, str) or not _name(issuer)
                    or published.tzinfo is None or now.tzinfo is None or published > now
                    or not any(row.get('symbol') == symbol and row.get('name') == issuer
                               for row in article['entities'] if isinstance(row, dict))):
                raise ValueError('invalid_candidate')
            if self._registry is None:
                raise _SourceError('issuer_registry_unavailable')
            corp = self._registry.get(symbol)
            if not isinstance(corp, str) or not re.fullmatch(r'[0-9]{8}', corp):
                raise _SourceError('issuer_mapping_unavailable')
            day = published.astimezone(_KST).date()
            start, end = day - _WINDOW, min(day + _WINDOW, now.astimezone(_KST).date())
            rows, digest = self._catalogue(corp, start, end)
            result.update(query_start=start.isoformat(), query_end=end.isoformat(), catalogue_sha256=digest)
            checks = self._match(article, symbol, issuer, corp, day, start, end, kind, rows)
            result['checks'] = checks
            for status in ('pending', 'verified_numeric_claims', 'document_unavailable',
                           'related_filing_found', 'issuer_name_conflict'):
                if any(check['status'] == status for check in checks):
                    result['status'] = status
                    break
        except _BudgetSpent:
            result['status'] = 'pending'
        except _SourceError as exc:
            result.update(status='source_unavailable', error_code=str(exc))
        except (KeyError, TypeError, ValueError):
            result.update(status='source_unavailable', error_code='invalid_candidate_or_source')
        return result

    def _match(self, article, symbol, issuer, corp, day, start, end, kind, rows):
        terms = set(_TERMS.get(kind, ()))
        title = article['title']
        if _CLAIM.search(title):
            terms.update(_TERMS['earnings'])
        matches = []
        for row in rows:
            report = row.get('report_nm')
            receipt = row.get('rcept_no')
            if not isinstance(report, str):
                continue
            compact_report = ''.join(report.split())
            if '자회사' in compact_report or not any(term in compact_report for term in terms):
                continue
            filing_date = _day(row.get('rcept_dt'))
            if not isinstance(receipt, str) or not re.fullmatch(r'[0-9]{14}', receipt):
                raise _SourceError('invalid_filing_receipt')
            if not (start <= filing_date <= end and (filing_date <= day or '정정' in report)):
                continue
            matches.append((filing_date, '정정' in report, receipt, row))
        checks = []
        document_attempted = False
        for filing_date, _, receipt, row in sorted(matches, key=lambda match: match[:3], reverse=True)[:5]:
            name = row.get('corp_name')
            check = {
                'status': 'related_filing_found', 'url': _VIEWER + receipt,
                'filing': {'report_nm': row['report_nm'].strip(), 'rcept_no': receipt, 'rcept_dt': row['rcept_dt'],
                           'corp_name': name if isinstance(name, str) else None},
                'claims': [],
                'filing_date_relation': ('same_day_time_unknown' if filing_date == day
                                         else 'later_correction' if filing_date > day else 'prior_day'),
            }
            if (row.get('corp_code') != corp or row.get('stock_code') != symbol
                    or not isinstance(name, str) or _name(name) != _name(issuer)):
                check['status'] = 'issuer_name_conflict'
                checks.append(check)
                continue
            # OpenDART can return both original and corrected filings even with
            # last_reprt_at=Y. Never corroborate a headline from a superseded table.
            if (not document_attempted and '영업(잠정)실적' in ''.join(row['report_nm'].split())
                    and _CLAIM.search(title) and not _basis_conflicts(title, row['report_nm'])):
                document_attempted = True
                try:
                    lines, digest = self._document(receipt, name)
                    claims = _check_amounts(article, row, lines)
                    check.update(claims=claims, document_sha256=digest)
                    if claims and all(claim['verified'] for claim in claims):
                        check['status'] = 'verified_numeric_claims'
                except _BudgetSpent:
                    check['status'] = 'pending'
                except (BadZipFile, OSError, ValueError, RuntimeError, ZlibError):
                    check['status'] = 'document_unavailable'
            checks.append(check)
        return checks

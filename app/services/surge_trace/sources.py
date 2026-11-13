"""Bounded source adapters. No price producer, article crawling or LLM calls."""
import csv
from datetime import timedelta
from email.utils import parsedate_to_datetime
import json
import math
from pathlib import Path
import re
import sqlite3
import time
import xml.etree.ElementTree as ET

import requests

from .common import clock, digest, normalized_name, safe_url, sports_title, stamp, title_matches

SOURCE_NAMES = ('omni', 'businesspost', 'google_news', 'dart')
MAX_BODY = 2_000_000


class SourceUnavailable(ValueError):
    """Internal diagnostic codes only; never copy provider exception messages."""


class EvidenceBatch(list):
    """Keep usable saved evidence while preserving an upstream health failure."""
    def __init__(self, rows, error_code=None, limitations=()):
        super().__init__(rows)
        self.error_code = error_code
        self.limitations = list(limitations)


def load_market(project_root, now):
    path = Path(project_root) / 'data' / 'screener_leading_latest.json'
    try:
        raw = path.read_bytes()
        body = json.loads(raw)
        observed = stamp(body['timestamp'], legacy_kst=True)
    except (OSError, ValueError, KeyError, TypeError):
        return {'status': 'unavailable', 'rows': [], 'as_of': None, 'hash': None}
    result = {'status': 'fresh', 'rows': [], 'as_of': observed.isoformat(), 'hash': digest(raw.decode('utf-8'))}
    quality = body.get('data_quality') or {}
    if body.get('quote_mode') != 'real':
        result['status'] = 'paper' if body.get('quote_mode') == 'paper' else 'unverified_quote_mode'
    elif body.get('error') or quality.get('critical_complete') is not True or quality.get('safe_to_replace_latest') is not True:
        result['status'] = 'incomplete'
    elif body.get('market_status') not in {'open', 'closed', 'pre_market'}:
        result['status'] = 'unavailable'
    elif observed > now:
        result['status'] = 'future'
    elif now - observed > timedelta(hours=72):
        result['status'] = 'stale'
    elif observed.date() != now.date() or body.get('market_status') in {'closed', 'pre_market'}:
        result['status'] = 'historical'
    elif not (9, 0) <= (observed.hour, observed.minute) <= (15, 30):
        result['status'] = 'unavailable'
    elif now - observed > timedelta(minutes=5):
        result['status'] = 'stale'
    if result['status'] not in {'fresh', 'historical'}:
        return result
    result['limitations'] = ['source_universe_partial'] if quality.get('universe_complete') is False else []
    try:
        with (Path(project_root) / 'data/ticker_to_yahoo_map.csv').open(encoding='utf-8-sig', newline='') as handle:
            listing = list(csv.DictReader(handle))
        identities = {}
        for item in listing:
            symbol = str(item.get('ticker') or '').strip()
            identities.setdefault(symbol, set()).add((normalized_name(item.get('name')), item.get('market')))
    except (OSError, ValueError, TypeError):
        result['status'] = 'identity_unavailable'
        return result
    candidates = body.get('candidate_pool') if isinstance(body.get('candidate_pool'), list) else body.get('results', [])
    if not isinstance(candidates, list):
        result['status'] = 'incomplete'
        return result
    accepted = {}
    for row in candidates:
        if not isinstance(row, dict):
            continue
        symbol, name, market = row.get('code'), row.get('name'), row.get('market')
        if (not isinstance(symbol, str) or not re.fullmatch(r'[0-9A-Z]{6}', symbol) or symbol == '000000'
                or not isinstance(name, str) or not name.strip() or market not in {'KOSPI', 'KOSDAQ'}
                or identities.get(symbol) != {(normalized_name(name), market)}):
            continue
        numbers = [row.get(key) for key in ('price', 'change_pct', 'trading_value')]
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in numbers):
            continue
        price, change, value = numbers
        if price <= 0 or change < 5 or value < 2_000_000_000:
            continue
        accepted[symbol] = {'symbol': symbol, 'name': name, 'market': market, 'price': price,
                            'change_pct': change, 'trading_value': value}
    result['rows'] = sorted(accepted.values(), key=lambda row: (-row['change_pct'], -row['trading_value'], row['symbol']))[:20]
    return result


def _http_get(url, params, *, deadline):
    deadline = min(deadline, time.monotonic() + 8)
    if deadline <= time.monotonic():
        raise SourceUnavailable('deadline')
    remaining = max(.1, deadline - time.monotonic())
    with requests.Session() as session:
        session.trust_env = False
        with session.get(url, params=params, timeout=(min(2, remaining), min(4, remaining)),
                         stream=True, allow_redirects=False) as response:
            if response.status_code != 200:
                raise SourceUnavailable('http_error')
            body = bytearray()
            for chunk in response.iter_content(65536):
                body.extend(chunk)
                if len(body) > MAX_BODY or time.monotonic() >= deadline:
                    raise SourceUnavailable('response_limit')
    return bytes(body)


class EvidenceSources:
    def __init__(self, project_root, *, now=None):
        self.project_root = Path(project_root)
        self.data = self.project_root / 'data'
        self._dart = None
        self._clock_override = now

    def collect(self, source, observation, now, deadline):
        if time.monotonic() >= deadline:
            raise SourceUnavailable('deadline')
        return getattr(self, source)(observation, now, deadline)

    def omni(self, observation, now, deadline):
        path = self.data / 'omni/omni.db'
        if not path.is_file():
            raise SourceUnavailable('source_missing')
        # Existing ledger.connect() creates directories/tables and changes WAL.
        # mode=ro prevents accidental writes and database creation.
        con = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=1)
        try:
            con.row_factory = sqlite3.Row
            con.execute('PRAGMA query_only=ON')
            con.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            rows = con.execute('SELECT title,link,source,published_ts,collected_at,symbols FROM news_events '
                               'WHERE symbols LIKE ? ORDER BY collected_at DESC LIMIT 100',
                               (f'%"{observation["symbol"]}"%',)).fetchall()
        finally:
            con.close()
        result = []
        for row in rows:
            try:
                symbols = json.loads(row['symbols'] or '[]')
            except (TypeError, ValueError):
                continue
            if observation['symbol'] not in symbols or not title_matches(row['title'], observation['name']):
                continue
            result.append({'kind': 'news', 'title': row['title'], 'url': row['link'], 'source': 'omni',
                           'publisher': row['source'] or None, 'published_at': row['published_ts'],
                           'published_precision': 'timestamp' if row['published_ts'] else 'unknown',
                           'first_received_at': row['collected_at'], 'verification': 'issuer_symbol_and_title_match'})
        return EvidenceBatch(result, limitations=['omni_archive_freshness_unknown'])

    def businesspost(self, observation, now, deadline):
        from app.services.kongming_article_candidates import read_view
        root = self.data / 'kongming_article_candidates'
        if not (root / 'snapshot.json').is_file():
            raise SourceUnavailable('source_missing')
        view = read_view(root, now=now)
        result = []
        for row in view['items']:
            exact = any(entity.get('symbol') == observation['symbol'] and
                        normalized_name(entity.get('name')) == normalized_name(observation['name'])
                        for entity in row.get('entities', []) if isinstance(entity, dict))
            if exact and title_matches(row['title'], observation['name']):
                result.append({'kind': 'news', 'title': row['title'], 'url': row['url'],
                               'source': 'businesspost', 'publisher': '비즈니스포스트',
                               'published_at': row['published_at'], 'published_precision': 'timestamp',
                               'first_received_at': row['first_seen_at'], 'verification': 'issuer_symbol_and_title_match'})
        status = view['operation']['state']
        return EvidenceBatch(result, f'upstream_{status}' if status in {'partial', 'error', 'waiting'} else None)

    def google_news(self, observation, now, deadline):
        raw = _http_get('https://news.google.com/rss/search',
                        {'q': f'"{observation["name"]}" when:7d', 'hl': 'ko', 'gl': 'KR', 'ceid': 'KR:ko'},
                        deadline=deadline)
        received = clock(self._clock_override)
        if not raw or len(raw) > MAX_BODY or re.search(br'<!\s*(DOCTYPE|ENTITY)', raw, re.I):
            raise SourceUnavailable('invalid_feed')
        feed = ET.fromstring(raw)
        channel = feed.find('channel')
        if feed.tag != 'rss' or channel is None:
            raise SourceUnavailable('invalid_feed')
        result = []
        for entry in channel.findall('item')[:100]:
            title = ' '.join((entry.findtext('title') or '').split())[:500]
            publisher = (entry.findtext('source') or '').strip()[:200] or None
            if publisher and title.endswith(' - ' + publisher):
                title = title[:-len(publisher) - 3]
            if not title_matches(title, observation['name']) or sports_title(title, publisher):
                continue
            if (len(normalized_name(observation['name'])) <= 2
                    and not re.search(rf'(?<![0-9A-Z]){re.escape(observation["symbol"])}(?![0-9A-Z])', title)
                    and not re.search(rf'(?:주식회사|\(주\))\s*{re.escape(observation["name"])}', title)):
                # Short issuer names can also be ordinary words (e.g. 동양).
                # An aggregate title alone cannot establish which entity it means.
                continue
            try:
                published = stamp(parsedate_to_datetime(entry.findtext('pubDate') or ''))
            except (TypeError, ValueError, OverflowError):
                continue
            url = safe_url(entry.findtext('link'))
            if not url or published > received or received - published > timedelta(days=7):
                continue
            result.append({'kind': 'news', 'title': title, 'url': url, 'source': 'google_news',
                           'publisher': publisher, 'published_at': published.isoformat(),
                           'published_precision': 'timestamp', 'first_received_at': received.isoformat(),
                           'verification': 'issuer_title_match'})
        return sorted(result, key=lambda row: row['published_at'], reverse=True)[:10]

    def dart(self, observation, now, deadline):
        from app.services.kongming_disclosure import DisclosureVerifier, RegistryError, _BudgetSpent, _SourceError
        if self._dart is None:
            self._dart = DisclosureVerifier(self.project_root, max_requests=5,
                                           max_seconds=max(.1, min(35, deadline - time.monotonic())))
        verifier = self._dart
        end = now.date()
        start = end - timedelta(days=7)
        try:
            mapping = verifier.resolve_issuer(observation['symbol'], observation['name'], now, deadline=deadline)
            corp = mapping['corp_code']
            rows, _ = verifier._catalogue(corp, start, end)
        except _BudgetSpent:
            raise SourceUnavailable('request_budget_exhausted') from None
        except (RegistryError, _SourceError) as exc:
            # Both exceptions expose controlled diagnostic codes, never URLs.
            raise SourceUnavailable(str(exc)) from None
        result = []
        for row in rows:
            if (row.get('corp_code') != corp or row.get('stock_code') != observation['symbol']
                    or normalized_name(row.get('corp_name')) != normalized_name(observation['name'])):
                continue
            receipt, day = row.get('rcept_no'), row.get('rcept_dt')
            if (not isinstance(receipt, str) or not re.fullmatch(r'\d{14}', receipt)
                    or not isinstance(day, str) or not re.fullmatch(r'\d{8}', day)):
                continue
            published = f'{day[:4]}-{day[4:6]}-{day[6:]}'
            if not start.isoformat() <= published <= end.isoformat():
                continue
            result.append({'kind': 'disclosure', 'title': str(row.get('report_nm') or '')[:500],
                           'url': f'https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt}',
                           'source': 'dart', 'publisher': 'OpenDART', 'published_at': published,
                           'published_precision': 'date', 'first_received_at': clock(self._clock_override).isoformat(),
                           'verification': 'issuer_registry_match', 'issuer_mapping': mapping})
        return result[:30]

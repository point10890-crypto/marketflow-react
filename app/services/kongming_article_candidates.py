"""MarketFlow's standalone BusinessPost RSS article candidate collector."""

import csv
import hashlib
import io
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import holidays
import requests
from filelock import FileLock

from app.utils.atomic_json import write_json_atomic
from app.utils.paths import DATA_DIR


ROOT = Path(DATA_DIR) / 'kongming_article_candidates'
KST = timezone(timedelta(hours=9))
FEEDS = (
    'https://www.businesspost.co.kr/rss/Article.xml',
    'https://www.businesspost.co.kr/rss/Article_8.xml',
)
MAX_BODY = 2_000_000
MAX_CANDIDATES = 700
SNAPSHOT = 'snapshot.json'
ARTICLE_FIELDS = ('id', 'title', 'url', 'entities', 'published_at', 'first_seen_at', 'provenance', 'event')
SYMBOL = re.compile(r'[0-9A-Z]{6}')
ARTICLE_ID = re.compile(r'[1-9][0-9]{0,9}')
PARTICLES = '은|는|이|가|을|를|의|에|에서|에게|와|과|도|만|로|으로|부터|까지'
GROUPS = {
    'contract': ('수주', '계약', '공급'),
    'earnings': ('실적', '영업이익', '순이익', '매출'),
    'capital_policy': ('자사주', '소각', '배당', '행동주의', '증자'),
    'capacity': ('증설', '공장', '설비투자'),
    'regulatory': ('허가', '승인', '규제', '제재'),
    'risk': ('취소', '소송', '횡령', '적자', '하향', '유출'),
    'industry': ('반도체', '인공지능', '데이터센터', '로봇', '전력망'),
}
CERTAINTIES = {'opinion', 'forecast', 'reported_unverified'}


def _timestamp(value):
    stamp = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(stamp, datetime) or stamp.tzinfo is None:
        raise ValueError('An aware timestamp is required')
    return stamp.astimezone(KST)


def _now(value=None):
    return _timestamp(value) if value is not None else datetime.now(KST)


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in {'script', 'style'}:
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def _plain(value, limit):
    parser = _PlainText()
    parser.feed(value or '')
    parser.close()
    return ' '.join(' '.join(parser.parts).split())[:limit]


def _canonical(url):
    parsed = urlsplit(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    identifiers = query.get('num', [])
    if (parsed.scheme != 'https'
            or parsed.netloc not in {'www.businesspost.co.kr', 'm.businesspost.co.kr'}
            or parsed.path != '/BP' or query.get('command') != ['article_view']
            or len(identifiers) != 1 or not ARTICLE_ID.fullmatch(identifiers[0])):
        raise ValueError('Unexpected BusinessPost article URL')
    identifier = identifiers[0]
    return identifier, f'https://www.businesspost.co.kr/BP?command=article_view&num={identifier}'


def _event(title, summary):
    text = f'{title} {summary}'
    kind = next((kind for kind, terms in GROUPS.items() if any(term in text for term in terms)), None)
    if any(term in title for term in ('백브리핑', '기자의눈', '리포트', '칼럼', 'VIEW')):
        certainty = 'opinion'
    elif any(term in text for term in ('전망', '검토', '유력', '기대', '예상', '가능성')):
        certainty = 'forecast'
    else:
        certainty = 'reported_unverified'
    return {'type': kind, 'certainty': certainty}


def _issuer_index(rows):
    names = {}
    for row in rows:
        name, symbol = row['name'], row['symbol']
        if len(name) >= 2 and SYMBOL.fullmatch(symbol):
            names.setdefault(name, set()).add(symbol)
    return [
        (name, re.compile(rf'(?<!\w){re.escape(name)}(?=$|\W|(?:{PARTICLES})(?=$|\W))'),
         {'symbol': next(iter(symbols)), 'name': name})
        for name, symbols in names.items() if len(symbols) == 1
    ]


def _verified_listing(root, now):
    """Reuse the full listing that MarketFlow sealed with its AlphaLab run."""
    inputs = root / 'alpha_lab' / 'inputs'
    pointer = json.loads((inputs / 'current.json').read_text(encoding='utf-8'))
    snapshot_id = pointer['snapshot_id']
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}-[0-9a-f]{20}', snapshot_id):
        raise ValueError('Invalid AlphaLab listing directory')
    as_of = date.fromisoformat(pointer['as_of'])
    if not 0 <= (now.date() - as_of).days <= 7 or not snapshot_id.startswith(f'{as_of}-'):
        raise ValueError('AlphaLab listing date unavailable')
    snapshot = inputs / 'snapshots' / snapshot_id
    report_path = snapshot / 'universe' / 'report.json'
    report_bytes = report_path.read_bytes()
    if hashlib.sha256(report_bytes).hexdigest() != pointer['hashes']['universe_report']:
        raise ValueError('AlphaLab listing report hash mismatch')
    listing = snapshot / 'scope' / 'sources' / f'listing_{as_of}.csv'
    raw = listing.read_bytes()
    if hashlib.sha256(raw).hexdigest() != json.loads(report_bytes)['input_evidence']['listing']['sha256']:
        raise ValueError('AlphaLab listing hash mismatch')
    rows = [
        {'symbol': row['Code'].strip(), 'name': row['Name'].strip()}
        for row in csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
        if row['Market'].strip() in {'KOSPI', 'KOSDAQ', 'KOSDAQ GLOBAL'}
    ]
    if len(rows) < 1000:
        raise ValueError('Incomplete AlphaLab listing')
    return rows, as_of.isoformat()


def _load_issuers(root, now):
    try:
        return _verified_listing(root, now)
    except (OSError, ValueError, KeyError, TypeError):
        # Older installs can still use the MarketFlow ticker directory. It has
        # no verified listing date, so the API leaves that date unknown.
        with (root / 'ticker_to_yahoo_map.csv').open(encoding='utf-8-sig', newline='') as handle:
            rows = [
                {'symbol': row['ticker'].strip(), 'name': row['name'].strip()}
                for row in csv.DictReader(handle)
                if row['market'].strip() in {'KOSPI', 'KOSDAQ'}
            ]
        if not rows:
            raise ValueError('MarketFlow ticker directory is empty')
        return rows, None


def _parse_feed(raw, now, issuers):
    if not raw or len(raw) > MAX_BODY:
        raise ValueError('Unexpected RSS size')
    xml = raw.decode('utf-8-sig')
    if '<!DOCTYPE' in xml.upper() or '<!ENTITY' in xml.upper():
        raise ValueError('Unsafe RSS XML')
    root = ET.fromstring(xml)
    channel = root.find('channel')
    if root.tag != 'rss' or channel is None:
        raise ValueError('RSS channel missing')
    entries = channel.findall('item')
    if not entries or len(entries) > 2000:
        raise ValueError('Unexpected RSS entry count')
    candidates = {}
    published_times = []
    for entry in entries:
        identifier, url = _canonical(entry.findtext('link') or '')
        published = _timestamp(parsedate_to_datetime(entry.findtext('pubDate') or ''))
        title = _plain(entry.findtext('title'), 500)
        if not title or published > now:
            raise ValueError('Invalid RSS article')
        published_times.append(published)
        entities = sorted(
            (entity for name, pattern, entity in issuers if name in title and pattern.search(title)),
            key=lambda entity: entity['symbol'],
        )
        excerpt = _plain(entry.findtext('description'), 1200)
        event = _event(title, excerpt)
        candidates[identifier] = {
            'id': identifier, 'title': title, 'url': url, 'entities': entities,
            'published_at': published.isoformat(), 'first_seen_at': now.isoformat(),
            'provenance': 'marketflow_rss', 'event': event,
            # Private bounded evidence for AI review; not part of ARTICLE_FIELDS.
            'rss_excerpt': excerpt, 'rss_excerpt_fetched_at': now.isoformat(),
        }
    return candidates, max(published_times)


def _fetch(feed, now):
    if feed not in FEEDS:
        raise ValueError('Unexpected RSS source')
    url = f'{feed}?_bm_rss_bucket={int(now.timestamp()) // 300}'
    deadline = time.monotonic() + 20
    with requests.Session() as session:
        session.trust_env = False
        with session.get(url, headers={'User-Agent': 'MarketFlow RSS reader/1.0'}, timeout=(5, 12),
                         stream=True, allow_redirects=False) as response:
            if response.status_code != 200:
                raise ValueError('RSS source did not return a body')
            age = response.headers.get('Age', '')
            if age.isdecimal() and int(age) > 300:
                raise ValueError('RSS cache age exceeds five minutes')
            raw = bytearray()
            for chunk in response.iter_content(65536):
                raw.extend(chunk)
                if len(raw) > MAX_BODY or time.monotonic() > deadline:
                    raise ValueError('RSS download exceeded its bound')
            return bytes(raw)


def _read(data_dir):
    try:
        with (data_dir / SNAPSHOT).open(encoding='utf-8') as handle:
            return json.load(handle)
    except FileNotFoundError:
        return {'items': [], 'feeds': {}}


def _retain(items):
    return sorted(items, key=lambda row: (row['published_at'], int(row['id'])), reverse=True)[:MAX_CANDIDATES]


def _interval(now):
    regular = (
        now.weekday() < 5 and now.date() not in holidays.KR(years=[now.year])
        and now.strftime('%m-%d') not in {'05-01', '12-31'}
        and (9, 0) <= (now.hour, now.minute) < (15, 30)
    )
    return timedelta(minutes=5 if regular else 30)


def _due(receipt, now):
    if not receipt:
        return now
    interval = timedelta(minutes=30) if receipt['state'] == 'error' else _interval(now)
    return _timestamp(receipt['last_poll_at']) + interval


def _view(state, now):
    items = [
        {**{key: row[key] for key in ARTICLE_FIELDS},
         'freshness': 'recent' if now - _timestamp(row['published_at']) <= timedelta(hours=72)
         else 'older_context'}
        for row in state['items'] if not row.get('withdrawn')
    ]
    receipts = state['feeds']
    polled = [receipt['last_poll_at'] for receipt in receipts.values()]
    received = [r['last_body_received_at'] for r in receipts.values() if r.get('last_body_received_at')]
    published = [r['latest_published_at'] for r in receipts.values() if r.get('latest_published_at')]
    next_poll = min(_due(receipts.get(feed), now) for feed in FEEDS) if polled else None
    errors = sum(receipt['state'] == 'error' for receipt in receipts.values())
    interrupted = any(receipt['state'] == 'polling'
                      and now - _timestamp(receipt['last_poll_at']) > timedelta(minutes=2)
                      for receipt in receipts.values())
    if errors == len(FEEDS):
        status = 'error'
    elif errors or interrupted or (next_poll and now > next_poll + timedelta(minutes=2)):
        status = 'partial'
    else:
        status = 'ready' if received else 'waiting'
    return {
        'items': items, 'candidate_article_count': len(items),
        'recent_candidate_article_count': sum(row['freshness'] == 'recent' for row in items),
        'computed_at': state.get('computed_at'), 'issuer_source_as_of': state.get('issuer_source_as_of'),
        'operation': {
            'state': status, 'last_poll_at': max(polled, default=None),
            'next_poll_at': next_poll.isoformat() if next_poll else None,
            'last_body_received_at': max(received, default=None),
            'latest_published_at': max(published, default=None),
            'source_count': len(received),
        },
    }


def read_view(data_dir=ROOT, *, now=None):
    """Read the atomic snapshot without any upstream or worker calls."""
    return _view(_read(Path(data_dir)), _now(now))


def run_once(data_dir=ROOT, now=None):
    """Fetch due feeds once and commit completed feed stages independently."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    current = _now(now)
    with FileLock(str(data_dir / 'worker.lock'), timeout=0):
        state = _read(data_dir)
        feeds = state['feeds']
        due = [feed for feed in FEEDS if current >= _due(feeds.get(feed), current)]
        if not due:
            return None
        try:
            rows, as_of = _load_issuers(data_dir.parent, current)
            issuers = _issuer_index(rows)
            if not issuers:
                raise ValueError('No unambiguous issuers')
        except (OSError, ValueError, KeyError, TypeError):
            for feed in due:
                feeds[feed] = {**feeds.get(feed, {}), 'state': 'error', 'last_poll_at': current.isoformat()}
            write_json_atomic(data_dir / SNAPSHOT, state)
            return _view(state, current)
        items = {row['id']: row for row in state['items']}
        seen_this_run = set()
        for feed in due:
            receipt = {**feeds.get(feed, {}), 'last_poll_at': current.isoformat(), 'state': 'polling'}
            feeds[feed] = receipt
            # Reserve the poll before touching the provider. A killed task can
            # recover the other due feed without replaying this request window.
            write_json_atomic(data_dir / SNAPSHOT, state)
            try:
                raw = _fetch(feed, current)
                received = _now(now)
                candidates, latest = _parse_feed(raw, received, issuers)
                if receipt.get('latest_published_at') and latest < _timestamp(receipt['latest_published_at']):
                    raise ValueError('RSS publication watermark regressed')
                for identifier, row in candidates.items():
                    if identifier in seen_this_run:
                        continue
                    previous = items.get(identifier)
                    if previous and row['published_at'] < previous['published_at']:
                        continue
                    if (previous and previous.get('source_feed') == FEEDS[0] and feed != FEEDS[0]
                            and row['published_at'] == previous['published_at']):
                        continue
                    if not row['entities'] or row['event']['type'] is None:
                        # A directory change alone is not evidence of a publisher correction.
                        if previous and (previous['title'] != row['title'] or row['event']['type'] is None):
                            items[identifier] = {**previous, 'withdrawn': True,
                                                 'published_at': row['published_at'], 'source_feed': feed}
                        continue
                    if previous:
                        row['first_seen_at'] = previous['first_seen_at']
                        row['provenance'] = previous['provenance']
                        if (row['title'] == previous['title']
                                and row['rss_excerpt'] == previous.get('rss_excerpt')
                                and previous.get('rss_excerpt_fetched_at')):
                            # Repeated polls are not new evidence or a reason to
                            # pay for another interpretation of identical text.
                            row['rss_excerpt_fetched_at'] = previous['rss_excerpt_fetched_at']
                    row['source_feed'] = feed
                    items[identifier] = row
                seen_this_run.update(candidates)
                receipt.update(state='ready', last_body_received_at=received.isoformat(),
                               latest_published_at=latest.isoformat(), sha256=hashlib.sha256(raw).hexdigest())
                state.update(items=_retain(items.values()), computed_at=received.isoformat(),
                             issuer_source_as_of=as_of)
            except (requests.RequestException, OSError, ET.ParseError, ValueError, TypeError, OverflowError):
                receipt['state'] = 'error'
            write_json_atomic(data_dir / SNAPSHOT, state)
        return _view(state, _now(now))


def import_archive(data_dir, rows, *, now=None):
    """One-time migration of displayed publisher metadata from the original app."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    current = _now(now)
    if not isinstance(rows, list) or not 0 < len(rows) <= MAX_CANDIDATES:
        raise ValueError('Invalid archive size')
    with FileLock(str(data_dir / 'worker.lock'), timeout=5):
        state = _read(data_dir)
        if state.get('archive_imported_at'):
            raise ValueError('The archive has already been imported')
        items = {row['id']: row for row in state['items']}
        for row in rows:
            identifier, url = _canonical(row['url'])
            title = _plain(row['title'], 500)
            published, received = (_timestamp(row[key]) for key in ('published_at', 'first_seen_at'))
            event = {key: row['event'][key] for key in ('type', 'certainty')}
            entities = [
                {'symbol': entity['symbol'], 'name': entity['name'].strip()[:100]}
                for entity in row['entities'] if SYMBOL.fullmatch(entity['symbol']) and entity['name'].strip()
            ]
            if (not title or not entities or max(published, received) > current
                    or event['type'] not in GROUPS or event['certainty'] not in CERTAINTIES):
                raise ValueError('Invalid archive article')
            items.setdefault(identifier, {
                'id': identifier, 'title': title, 'url': url, 'entities': entities, 'event': event,
                'published_at': published.isoformat(), 'first_seen_at': received.isoformat(),
                'provenance': 'kongming_archive',
            })
        state.update(items=_retain(items.values()), archive_imported_at=current.isoformat())
        write_json_atomic(data_dir / SNAPSHOT, state)
        return _view(state, current)

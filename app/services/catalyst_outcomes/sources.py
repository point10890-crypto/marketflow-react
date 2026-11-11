"""Read all retained event ledgers without crawling, provider calls, or writes.

Verification describes the current saved state. ``verification_at`` must never
be mistaken for evidence available at ``anchor_at``. Imported archive clocks
do not establish an observed first receipt, even when the archive supplies one.
"""
from __future__ import annotations

from collections import Counter
import csv
import json
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.services import kongming_article_candidates as articles
from app.services.surge_trace.common import (
    clock, digest, normalized_name, safe_url, sports_title, stamp, title_matches,
)

SOURCE_NAMES = ('verification', 'businesspost', 'omni', 'surge_trace')
# Safety bounds are far above the current retained ledgers and are reported if
# reached. There is deliberately no display-limit/recent-days archive filter.
MAX_DATABASE_ROWS = 1_000_000
DATABASE_SECONDS = 60
_WITHDRAWN = {'withdrawn', 'retracted', 'deleted', 'invalidated'}
_VERIFICATION_RANK = {
    'verified_numeric_claims': 8, 'verified': 7, 'matched_filing': 6,
    'issuer_registry_match': 5, 'issuer_symbol_and_title_match': 4,
    'issuer_title_match': 3, 'reported_unverified': 2, 'pending': 1,
}


def _bump(diag, code):
    diag['invalid'][code] += 1


def _listing(project_root, diag):
    values = {}
    path = Path(project_root) / 'data/ticker_to_yahoo_map.csv'
    try:
        with path.open(encoding='utf-8-sig', newline='') as handle:
            reader = csv.DictReader(handle)
            if not {'ticker', 'name', 'market'} <= set(reader.fieldnames or ()):
                raise ValueError()
            for row in reader:
                symbol, name, market = (str(row.get(key) or '').strip() for key in ('ticker', 'name', 'market'))
                if re.fullmatch(r'[0-9A-Z]{6}', symbol) and symbol != '000000' and name and market in {'KOSPI', 'KOSDAQ'}:
                    values.setdefault(symbol, set()).add((name, market))
        identities = {symbol: next(iter(rows)) for symbol, rows in values.items() if len(rows) == 1}
        diag['listing'] = {'status': 'ready' if identities else 'unavailable', 'symbols': len(identities)}
        return identities
    except (OSError, UnicodeError, ValueError, csv.Error):
        diag['listing'] = {'status': 'unavailable', 'symbols': 0, 'error': 'listing_unavailable'}
        return {}


def _json(path, status, field, expected):
    try:
        value = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(value, dict) or not isinstance(value.get(field), expected):
            raise ValueError()
        status['status'] = 'ready'
        operation = value.get('operation') or {}
        # Some snapshots call this field receipt. Retain producer health beside
        # usable saved rows instead of treating stale cache as an empty success.
        receipt = value.get('receipt') or {}
        feeds = value.get('feeds') if isinstance(value.get('feeds'), dict) else {}
        if any(isinstance(item, dict) and item.get('state') in {'error', 'partial', 'waiting'}
               for item in (operation, receipt, *feeds.values())):
            status.update(status='partial', error='upstream_partial')
        return value[field]
    except (OSError, UnicodeError, ValueError, TypeError):
        status.update(status='unavailable', error='source_missing_or_invalid')
        return [] if expected is list else {}


def _database(path, query, status):
    if not path.is_file():
        status.update(status='unavailable', error='source_missing')
        return
    connection = None
    deadline = time.monotonic() + DATABASE_SECONDS
    count = 0
    try:
        connection = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=1)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA query_only=ON')
        connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        for row in connection.execute(query):
            if count >= MAX_DATABASE_ROWS or time.monotonic() >= deadline:
                status.update(status='partial', truncated=True, error='archive_read_bound')
                break
            count += 1
            yield dict(row)
        else:
            status['status'] = 'ready'
    except sqlite3.Error:
        status.update(status='partial' if count else 'unavailable',
                      error='archive_read_failed', truncated=bool(count))
    finally:
        status['read_rows'] = count
        if connection is not None:
            connection.close()


def _canonical(value):
    result = safe_url(value)
    if result is None:
        return None
    parsed = urlsplit(result)
    # Mobile and desktop links identify the same publisher article.
    if parsed.hostname in {'www.businesspost.co.kr', 'm.businesspost.co.kr'} and parsed.path == '/BP':
        query = dict(parse_qsl(parsed.query))
        if query.get('command') == 'article_view' and re.fullmatch(r'[1-9][0-9]{0,9}', query.get('num', '')):
            return urlunsplit(('https', 'www.businesspost.co.kr', '/BP',
                               urlencode({'command': 'article_view', 'num': query['num']}), ''))
    return result


def _timestamp(value, field, diag):
    if value in (None, ''):
        return None
    try:
        return stamp(value)
    except (TypeError, ValueError, OverflowError):
        _bump(diag, field)
        return None


def _withdrawn(row):
    primary = row.get('primary') if isinstance(row.get('primary'), dict) else {}
    return (row.get('withdrawn') is True or row.get('is_withdrawn') is True
            or any(isinstance(value, str) and value in _WITHDRAWN
                   for value in (row.get('status'), row.get('verification'), primary.get('status'))))


def _normalize(row, source, listing, now, diag):
    if not isinstance(row, dict):
        _bump(diag, 'row_shape')
        return None
    if _withdrawn(row):
        _bump(diag, 'withdrawn')
        return None
    symbol = row.get('symbol')
    if isinstance(symbol, str) and not re.fullmatch(r'[0-9]{6}', symbol):
        _bump(diag, 'unsupported_symbol')
        return None
    listed = listing.get(symbol) if isinstance(symbol, str) else None
    name = row.get('name')
    if (not listed or not isinstance(name, str) or normalized_name(name) != normalized_name(listed[0])
            or row.get('market') is not None and row['market'] != listed[1]):
        _bump(diag, 'identity')
        return None
    title = row.get('title')
    if not isinstance(title, str) or not title.strip() or len(title) > 2000:
        _bump(diag, 'title')
        return None
    title = ' '.join(title.split())
    if not title_matches(title, listed[0]):
        _bump(diag, 'identity')
        return None
    publisher = row.get('publisher')
    if publisher is not None and not isinstance(publisher, str):
        _bump(diag, 'row_shape')
        return None
    if sports_title(title, publisher):
        _bump(diag, 'sports')
        return None
    original_url = row.get('url')
    url = _canonical(original_url) if original_url else None
    if original_url and url is None:
        _bump(diag, 'unsafe_url')
        return None
    event = row.get('event')
    kind = event.get('type') if isinstance(event, dict) else None
    if not kind:
        kind = articles._event(title, str(row.get('summary') or ''))['type']
    if not isinstance(kind, str) or kind not in articles.GROUPS:
        _bump(diag, 'non_material')
        return None
    published = _timestamp(row.get('published_at'), 'published_at', diag)
    received = _timestamp(row.get('first_seen_at'), 'first_seen_at', diag)
    if any(value and value > now for value in (published, received)):
        _bump(diag, 'future_timestamp')
        return None
    if published and received and published > received:
        _bump(diag, 'timestamp_order')
        return None
    provenance = str(row.get('provenance') or '').lower()
    imported = any(term in provenance for term in ('archive', 'import', 'backfill'))
    basis = 'received' if received and not imported else 'retrospective'
    anchor = received if basis == 'received' else published or received
    if anchor is None:
        _bump(diag, 'anchor_missing')
        return None
    verification = row.get('verification') or 'issuer_symbol_and_title_match'
    if not isinstance(verification, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,99}', verification):
        verification = 'unverified'
    verified_at = _timestamp(row.get('verification_at'), 'verification_at', diag)
    if verified_at and verified_at > now:
        _bump(diag, 'future_verification')
        verification, verified_at = 'unverified', None
    return dict(id='', symbol=symbol, name=listed[0], title=title, url=url, source=source,
                event_type=kind, published_at=published.isoformat() if published else None,
                first_seen_at=received.isoformat() if received else None, anchor_at=anchor.isoformat(),
                analysis_basis=basis, verification=verification,
                verification_at=verified_at.isoformat() if verified_at else None)


def event_keys(row):
    """Public immutable alias keys for reconciliation with a retained ledger.

    A fresh import can reveal an earlier receipt with another canonical URL.
    Therefore callers must preserve their existing ledger ID when any alias
    matches, rather than treating the newly calculated source ID as a new case.
    """
    # Financial punctuation is part of the claim: +100 != -100, 1.0 != 10.
    # Normalize whitespace/case only; stripping punctuation merges opposites.
    title = normalized_name(row['title'])
    # Repeated annual headlines are different events. Syndication of the same
    # dated headline merges even when each publisher uses a different URL.
    day = (row['published_at'] or row['anchor_at'])[:10]
    keys = [(row['symbol'], 'title', title, day)]
    url = _canonical(row.get('url'))
    if url:
        keys.append((row['symbol'], 'url', url))
    return keys


def is_withdrawn(event, diagnostics):
    """Match serializable tombstones against current fields and saved aliases.

    Persist the union of ``withdrawn_keys`` across runs. Upstream retention may
    remove a tombstone later, which must not silently reactivate its old case.
    Withdrawal changes eligibility, never a previously sealed outcome record.
    """
    raw = diagnostics.get('withdrawn_keys', []) if isinstance(diagnostics, dict) else []
    keys = {tuple(key) for key in raw if isinstance(key, (list, tuple))
            and len(key) == 3 and all(isinstance(value, str) for value in key)}
    if not isinstance(event, dict) or not keys:
        return False
    candidates = [(event.get('symbol'), 'url', _canonical(event.get('url'))),
                  (event.get('symbol'), 'title', normalized_name(event.get('title')))]
    for alias in event.get('_aliases', []) if isinstance(event.get('_aliases'), list) else []:
        if isinstance(alias, (list, tuple)) and len(alias) in {3, 4}:
            # Event title aliases additionally include the publication date.
            candidates.append(tuple(alias[:3]))
    return any(all(isinstance(value, str) for value in key) and key in keys for key in candidates)


def _merge(rows):
    first = min(rows, key=lambda item: item['anchor_at'])
    result = dict(first)
    received = [row for row in rows if row['analysis_basis'] == 'received']
    if received:
        receipt = min(row['first_seen_at'] for row in received)
        result.update(first_seen_at=receipt, anchor_at=receipt, analysis_basis='received')
    publications = [row['published_at'] for row in rows if row['published_at']]
    if publications:
        result['published_at'] = min(publications)
    verified = max(rows, key=lambda item: (_VERIFICATION_RANK.get(item['verification'], 0), item['verification_at'] or ''))
    result.update(verification=verified['verification'], verification_at=verified['verification_at'])
    if not result['url']:
        result['url'] = next((row['url'] for row in rows if row['url']), None)
    return result


def _deduplicate(rows, diagnostics):
    groups, aliases = {}, {}
    for index, row in enumerate(rows):
        keys = event_keys(row)
        matches = {aliases[key] for key in keys if key in aliases}
        owner = min(matches) if matches else index
        group = groups.setdefault(owner, [])
        for other in matches - {owner}:
            group.extend(groups.pop(other))
            for key, value in list(aliases.items()):
                if value == other:
                    aliases[key] = owner
        group.append(row)
        for key in keys:
            aliases[key] = owner
    output = []
    for group in groups.values():
        row = _merge(group)
        title_key = normalized_name(row['title'])
        identity = row['url'] or f'{title_key}|{row["anchor_at"][:10]}'
        row['id'] = digest(f'{row["symbol"]}|{identity}')
        diagnostics['identity_aliases'][row['id']] = [list(key) for key in sorted({
            key for original in group for key in event_keys(original)})]
        output.append(row)
    return sorted(output, key=lambda item: (item['anchor_at'], item['symbol'], item['id']))


def load_events(project_root, now):
    """Union retained verification, publisher, Omni, and surge evidence history."""
    now, project_root = clock(now), Path(project_root)
    diag = dict(status='ready', sources={key: {'status': 'unavailable', 'read_rows': 0, 'accepted': 0,
                                             'truncated': False} for key in SOURCE_NAMES},
                source_counts={key: 0 for key in SOURCE_NAMES}, invalid=Counter(), deduplicated=0,
                truncated=False, withdrawn_keys=[], identity_aliases={},
                limitations=['current_verification_is_not_historical',
                             'retained_sources_are_not_complete_market_history',
                             'numeric_six_digit_kr_equities_only'])
    listing = _listing(project_root, diag)
    if not listing:
        diag.update(status='unavailable', invalid=dict(diag['invalid']))
        return [], diag
    accepted = []
    withdrawn_urls, withdrawn_titles = set(), set()

    def add(row, source):
        if isinstance(row, dict) and _withdrawn(row):
            symbol, name, title = row.get('symbol'), row.get('name'), row.get('title')
            listed = listing.get(symbol) if isinstance(symbol, str) else None
            if (listed and isinstance(name, str) and normalized_name(name) == normalized_name(listed[0])
                    and isinstance(title, str) and title_matches(title, listed[0])):
                # Publisher tombstones must also suppress older, now-inactive
                # verification tasks. Otherwise reading all history resurrects
                # a claim the publisher explicitly withdrew.
                url = _canonical(row.get('url'))
                if url:
                    withdrawn_urls.add((symbol, url))
                    withdrawn_titles.add((symbol, normalized_name(title)))
        normalized = _normalize(row, source, listing, now, diag)
        if normalized:
            accepted.append(normalized)
            diag['sources'][source]['accepted'] += 1

    source = 'verification'
    status = diag['sources'][source]
    for entry in _database(project_root / 'data/kongming_article_candidates/verification.sqlite3',
                           'SELECT payload FROM tasks', status):
        diag['source_counts'][source] += 1
        try:
            row = json.loads(entry['payload'])
            if not isinstance(row, dict):
                raise ValueError()
        except (ValueError, TypeError):
            _bump(diag, 'verification_payload')
            continue
        primary = row.get('primary') if isinstance(row.get('primary'), dict) else {}
        add({**row, 'title': row.get('article_title'), 'url': row.get('article_url'),
             'published_at': row.get('article_published_at'), 'provenance': row.get('first_seen_source'),
             'verification': primary.get('status') or 'unverified',
             'verification_at': primary.get('checked_at') or row.get('checked_at')}, source)

    source = 'businesspost'
    status = diag['sources'][source]
    rows = _json(project_root / 'data/kongming_article_candidates/snapshot.json', status, 'items', list)
    status['read_rows'] = len(rows)
    for row in rows:
        diag['source_counts'][source] += 1
        if not isinstance(row, dict) or not isinstance(row.get('entities'), list):
            _bump(diag, 'row_shape')
            continue
        for entity in row['entities']:
            if isinstance(entity, dict):
                add({**row, 'symbol': entity.get('symbol'), 'name': entity.get('name'),
                     'market': entity.get('market')}, source)

    source = 'omni'
    status = diag['sources'][source]
    for row in _database(project_root / 'data/omni/omni.db',
                          'SELECT title,summary,link,source,published_ts,collected_at,symbols FROM news_events', status):
        diag['source_counts'][source] += 1
        try:
            symbols = json.loads(row.get('symbols') or '[]')
            if not isinstance(symbols, list):
                raise ValueError()
        except (ValueError, TypeError):
            _bump(diag, 'omni_symbols')
            continue
        for symbol in dict.fromkeys(item for item in symbols if isinstance(item, str)):
            add({**row, 'symbol': symbol, 'name': listing.get(symbol, ('', ''))[0],
                 'url': row.get('link'), 'publisher': row.get('source'),
                 'published_at': row.get('published_ts'), 'first_seen_at': row.get('collected_at')}, source)

    source = 'surge_trace'
    status = diag['sources'][source]
    observations = _json(project_root / 'data/surge_trace/snapshot.json', status, 'observations', dict)
    for observation in observations.values():
        if not isinstance(observation, dict):
            _bump(diag, 'row_shape')
            continue
        for key in ('evidence', '_evidence_history'):
            rows = observation.get(key, [])
            if not isinstance(rows, list):
                _bump(diag, 'row_shape')
                continue
            for row in rows:
                diag['source_counts'][source] += 1
                if not isinstance(row, dict):
                    _bump(diag, 'row_shape')
                    continue
                add({**row, 'symbol': observation.get('symbol'), 'name': observation.get('name'),
                     'market': observation.get('market'), 'first_seen_at': row.get('first_received_at'),
                     'verification_at': row.get('verification_at')}, source)
    status['read_rows'] = diag['source_counts'][source]
    diag['withdrawn_keys'] = sorted(
        [[symbol, 'url', url] for symbol, url in withdrawn_urls]
        + [[symbol, 'title', title] for symbol, title in withdrawn_titles])
    retained = [row for row in accepted if not is_withdrawn(row, diag)]
    diag['withdrawn_history_excluded'] = len(accepted) - len(retained)
    result = _deduplicate(retained, diag)
    diag.update(deduplicated=len(retained) - len(result), events=len(result), invalid=dict(diag['invalid']),
                truncated=any(value['truncated'] for value in diag['sources'].values()))
    if any(value['status'] != 'ready' for value in diag['sources'].values()):
        diag['status'] = 'partial' if result or any(value['status'] == 'ready' for value in diag['sources'].values()) else 'unavailable'
    return result, diag

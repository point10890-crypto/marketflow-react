"""Bounded read-only join of existing MarketFlow Omni news, never a fetch.

An issuer mention is reported evidence, not official verification or a ranking
bonus. Unknown producer poll freshness remains explicit even for recent rows.
"""
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
import time

from app.services import evidence_review as evidence
from app.services.surge_trace.common import safe_url, sports_title, title_matches


def read_news(path, targets, now, warnings):
    path = Path(path)
    if not path.is_file():
        warnings.append('omni_news_source_unavailable')
        return []
    rows = []
    deadline = time.monotonic() + .5
    try:
        con = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=.2)
        try:
            con.row_factory = sqlite3.Row
            con.execute('PRAGMA query_only=ON')
            con.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            for target in targets[:6]:
                saved = con.execute('SELECT title,link,source,published_ts,collected_at,symbols '
                    'FROM news_events WHERE symbols LIKE ? ORDER BY collected_at DESC LIMIT 100',
                    (f'%"{target["symbol"]}"%',)).fetchall()
                valid = []
                for row in saved:
                    try:
                        symbols = json.loads(row['symbols'])
                        title = row['title']
                        if (not isinstance(symbols, list) or target['symbol'] not in symbols
                                or not isinstance(title, str) or not 1 <= len(title) <= 1200
                                or not isinstance(row['published_ts'], str) or not isinstance(row['collected_at'], str)
                                or not title.isprintable() or not title_matches(title, target['name'])
                                or sports_title(title, row['source'])):
                            continue
                        published, received = evidence._clock(row['published_ts']), evidence._clock(row['collected_at'])
                        url = safe_url(row['link'])
                        if not url or not published <= received <= now or now-published > timedelta(hours=72):
                            continue
                        valid.append((published, received, title, url))
                    except (ValueError, TypeError, KeyError, OverflowError):
                        continue
                seen_titles, seen_urls = set(), set()
                for published, received, title, url in sorted(valid, key=lambda r: (r[0], r[3]), reverse=True):
                    normalized = ' '.join(title.split()).casefold()
                    if normalized in seen_titles or url in seen_urls:
                        continue
                    seen_titles.add(normalized); seen_urls.add(url)
                    identifier = 'omni-' + evidence._hash(dict(url=url, title=title, published=evidence._stamp(published)))[:24]
                    source = evidence._source(f'article:{identifier}', title, title=title,
                        source='MarketFlow_Omni_saved_news', published=evidence._stamp(published),
                        fetched=evidence._stamp(received), url=url, status='reported_unverified')
                    source['url'] = url  # Already validated; legacy helper allows only BusinessPost/DART.
                    rows.append(dict(article_id=identifier, targets=[dict(target)], sources=[source],
                        source_origin_at=evidence._stamp(published), event_type=evidence.articles._event(title, '')['type']))
                    if len(seen_urls) >= 2:
                        break
        finally:
            con.close()
    except (OSError, sqlite3.Error):
        warnings.append('omni_news_source_unavailable')
        return []
    warnings.append('omni_archive_freshness_unknown')
    # A syndicated/shared article has one stable identity with exact issuers.
    unique = {}
    for row in rows:
        existing = unique.get(row['article_id'])
        if existing is None:
            unique[row['article_id']] = row
        elif row['targets'][0] not in existing['targets']:
            existing['targets'].extend(row['targets'])
    return list(unique.values())

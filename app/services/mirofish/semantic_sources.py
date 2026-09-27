"""Attach current local news ledger evidence without backdating historical snapshots."""
from datetime import datetime, timezone, timedelta
from app.services.mirofish import semantic_decisions as s


def enrich_snapshot(snapshot_id, *, root=None, now=None, reader=None):
    if reader is None:
        from app.services.mirofish.retrieval import _news_for
        reader = _news_for
    snapshot = s.read_snapshot(snapshot_id, root=root)
    observed = now or datetime.now(timezone.utc).isoformat()
    at = s._instant(observed)
    if at < s._instant(snapshot['decision_at']):
        raise ValueError('observation_before_snapshot')
    added, errors = 0, 0
    for candidate in snapshot['candidates']:
        packets = []
        try:
            rows = reader(candidate['symbol'], 3)
        except Exception:
            rows, errors = [], errors+1
        for row in rows[:3]:
            title, link = row.get('title'), row.get('link')
            if not isinstance(title, str) or not title.strip() or not isinstance(link, str) or not link.startswith(('https://', 'http://')):
                continue
            try:
                ts = row['published_ts']
                published = datetime.fromtimestamp(float(ts), timezone.utc) if isinstance(ts, (int, float)) else s._instant(ts)
            except (ValueError, TypeError, KeyError, OverflowError, OSError):
                continue
            if not at-timedelta(days=7) <= published <= at:
                continue
            packets.append({'source': 'omni_news_ledger', 'evidence_id': link,
                'fetched_at': observed, 'published_at': published.isoformat(),
                'content': {'text': title, 'title': title, 'available_at': observed}})
        added += len(packets)
        # Prefer bounded raw headlines over precomputed AI summaries. Never fetch URLs here.
        candidate['source_packets'] = packets + candidate['source_packets']
    result = s.record_snapshot(snapshot['candidates'], workflow_id='enriched:'+snapshot_id,
                               decision_at=observed, root=root)
    return {**result, 'added_headlines': added, 'source_errors': errors,
            'evidence_scope': 'headlines_only', 'baseline_decision_at': snapshot['decision_at']}

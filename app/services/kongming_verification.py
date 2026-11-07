"""Persist independent filing and price evidence for each article and issuer."""

from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from filelock import FileLock

from app.services import kongming_article_candidates as candidates


ROOT = candidates.ROOT
DATABASE = 'verification.sqlite3'
SOURCE = 'marketflow'
WORKER_INTERVAL = 60
DISPLAY_LIMIT = 250
HISTORY_LIMIT = 100
DART_RETRY = timedelta(minutes=15)
PRICE_RETRY = timedelta(minutes=15)
_STAGES = ('primary', 'price')
_PRIMARY_FAILURES = {'source_unavailable', 'document_unavailable'}
_PRICE_FAILURES = {'source_unavailable', 'calendar_unavailable'}


def _clock(now=None):
    if now is None:
        return datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ValueError('Verification requires an aware clock')
    return now.astimezone(timezone.utc)


def _timestamp(value):
    return _clock(datetime.fromisoformat(value))


def _stamp(value):
    return value.isoformat(timespec='microseconds')


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def _open(data_dir, *, read_only=False):
    path = Path(data_dir) / DATABASE
    if read_only:
        return sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=1)
    return sqlite3.connect(path, timeout=3)


def _initialize(db):
    db.execute('PRAGMA journal_mode=WAL')
    db.executescript('''
        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            article_id TEXT NOT NULL,
            published_at TEXT NOT NULL,
            active INTEGER NOT NULL,
            primary_due TEXT,
            price_due TEXT,
            payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS verification_active ON tasks(active, published_at DESC);
        CREATE INDEX IF NOT EXISTS verification_article ON tasks(article_id, active);
        CREATE TABLE IF NOT EXISTS history (
            sequence INTEGER PRIMARY KEY,
            article_id TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS verification_history_article ON history(article_id, sequence DESC);
        CREATE TABLE IF NOT EXISTS meta (
            name TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    ''')


def _meta(db, name):
    row = db.execute('SELECT value FROM meta WHERE name = ?', (name,)).fetchone()
    return row[0] if row else None


def _set_meta(db, name, value):
    db.execute('INSERT INTO meta VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET value = excluded.value',
               (name, value))


def _initial(article, entity):
    identity = {
        'article_id': article['id'], 'article_title': article['title'], 'article_url': article['url'],
        'article_published_at': article['published_at'], 'first_seen_at': article['first_seen_at'],
        'first_seen_source': article.get('provenance'),
        'symbol': entity['symbol'], 'name': entity['name'],
    }
    context = {'event': article.get('event'), 'issuers': sorted(
        (item['symbol'], item['name']) for item in article['entities']
    )}
    return {**identity, 'task_id': _hash([identity, context]), 'primary': {'status': 'pending'},
            'price': {'status': 'pending'}}


def _discover(db, articles, now):
    rows = [_initial(article, entity) for article in articles for entity in article['entities']]
    revision = _hash(sorted(row['task_id'] for row in rows))
    if _meta(db, 'input_revision') == revision:
        return
    with db:
        db.execute('UPDATE tasks SET active = 0')
        db.executemany('''
            INSERT INTO tasks VALUES (?, ?, ?, 1, '', '', ?)
            ON CONFLICT(task_id) DO UPDATE SET active = 1
        ''', [(row['task_id'], row['article_id'], _stamp(_timestamp(row['article_published_at'])), _json(row))
              for row in rows])
        _set_meta(db, 'input_revision', revision)
        _set_meta(db, 'last_change_at', _stamp(now))


def _due_tasks(db, stage, now, limit):
    if stage not in _STAGES:
        raise ValueError('Invalid verification stage')
    return db.execute(f'''
        SELECT task_id, payload FROM tasks
        WHERE active = 1 AND {stage}_due <= ?
        ORDER BY (published_at < ?), {stage}_due, published_at DESC, task_id
        LIMIT ?
    ''', (_stamp(now), _stamp(now - timedelta(hours=72)), limit)).fetchall()


def _retry_at(stage, result, article, now):
    status = result['status']
    if stage == 'primary':
        if status == 'pending':
            return now + timedelta(minutes=1)
        if status in _PRIMARY_FAILURES:
            return now + DART_RETRY
        if now - _timestamp(article['published_at']) <= timedelta(days=3):
            return now + timedelta(hours=6)
        return None
    if status == 'verified' and result.get('window_complete', True):
        return None
    if status in {'invalid_identity', 'historical_window_expired'}:
        return None
    if status == 'awaiting_session' and result.get('session'):
        next_open = datetime.fromisoformat(result['session'] + 'T09:05:00+09:00')
        if next_open > now:
            return next_open.astimezone(timezone.utc)
    if status == 'awaiting_session' and not result.get('session'):
        return now + timedelta(minutes=30)
    if status == 'awaiting_post_receipt_data' and result.get('window_complete'):
        window_end = _timestamp(result['window_end_at'])
        return now + timedelta(hours=6) if now - window_end <= timedelta(days=3) else None
    if status in {'awaiting_session', 'awaiting_post_receipt_data', 'verified'}:
        return now + timedelta(minutes=5)
    return now + PRICE_RETRY


def _stable_evidence(result):
    return {key: value for key, value in result.items()
            if key not in {'checked_at', 'fetched_at', 'calendar_captured_at'}}


def _latest_receipt(result):
    return next((check['filing']['rcept_no'] for check in result.get('checks', [])
                 if check.get('filing', {}).get('rcept_no')), None)


def _save_stage(db, stage, task, result, next_at, now):
    previous = task[stage]
    failures = _PRIMARY_FAILURES if stage == 'primary' else _PRICE_FAILURES
    if stage == 'primary':
        incoming_receipt = _latest_receipt(result)
        same_filing = not incoming_receipt or incoming_receipt == _latest_receipt(previous)
        retain = previous.get('checks') and same_filing and result['status'] in failures | {'pending'}
    else:
        retain = previous['status'] == 'verified' and result['status'] in failures | {'awaiting_post_receipt_data'}
    if retain:
        result = {**previous, 'refresh_status': result['status']}
    changed = _stable_evidence(previous) != _stable_evidence(result)
    task[stage] = result
    task['checked_at'] = _stamp(now)
    with db:
        db.execute(f'UPDATE tasks SET payload = ?, {stage}_due = ? WHERE task_id = ?',
                   (_json(task), _stamp(next_at) if next_at else None, task['task_id']))
        if changed:
            event = {
                'id': _hash([task['task_id'], stage, _stamp(now), _stable_evidence(result)]),
                'article_id': task['article_id'], 'article_title': task['article_title'],
                'symbol': task['symbol'], 'name': task['name'], 'checked_at': task['checked_at'],
                'primary': {'status': task['primary']['status']},
                'price': {'status': task['price']['status']},
            }
            db.execute('INSERT INTO history(article_id, payload) VALUES (?, ?)', (task['article_id'], _json(event)))
            _set_meta(db, 'last_change_at', _stamp(now))


def _run_stage(db, articles, stage, provider, now, stop, limit):
    count = 0
    for _, encoded in _due_tasks(db, stage, now, limit):
        if time.monotonic() >= stop:
            break
        task = json.loads(encoded)
        article = articles[task['article_id']]
        entity = {'symbol': task['symbol'], 'name': task['name']}
        try:
            result = (provider.verify(article, entity, now) if stage == 'primary'
                      else provider.verify(article, entity['symbol'], now))
            if not isinstance(result, dict) or not isinstance(result.get('status'), str):
                raise ValueError('Invalid verification result')
        except Exception:
            # Provider exception details can contain request credentials.
            result = {'status': 'source_unavailable', 'reason': 'provider_error'}
        if result['status'] in {'pending', 'deferred'}:
            if stage == 'primary' and result.get('checks'):
                _save_stage(db, stage, task, result, _retry_at(stage, result, article, now), now)
            break
        next_at = _retry_at(stage, result, article, now)
        _save_stage(db, stage, task, result, next_at, now)
        count += 1
    return count


def run_once(data_dir=ROOT, *, now=None, deadline=None, disclosure=None, price=None):
    """Advance bounded batches from the current MarketFlow candidate archive."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    current = _clock(now)
    stop = deadline if deadline is not None else time.monotonic() + 60
    with FileLock(str(data_dir / 'verification.lock'), timeout=0), closing(_open(data_dir)) as db:
        _initialize(db)
        articles = {row['id']: row for row in candidates.read_view(data_dir, now=current)['items']}
        _discover(db, articles.values(), current)
        disclosure_checked = price_checked = 0
        if articles and time.monotonic() < stop - 15:
            if disclosure is None:
                from app.services.kongming_disclosure import DisclosureVerifier
                disclosure = DisclosureVerifier(data_dir.parent.parent, max_requests=7, max_seconds=23)
            # Keep a separate time slice for KIS even when DART is slow.
            disclosure_stop = min(time.monotonic() + 23, stop - 17)
            disclosure_checked = _run_stage(db, articles, 'primary', disclosure, current, disclosure_stop, 12)
        if articles and time.monotonic() < stop - 8:
            if price is None:
                from app.services.kongming_price_evidence import KongmingPriceProvider
                price = KongmingPriceProvider(max_requests=5, calendar_path=data_dir / 'price_calendar.json',
                                              time_budget_seconds=min(30, stop - time.monotonic() - 5))
            price_checked = _run_stage(db, articles, 'price', price, current, stop - 6, 16)
        with db:
            _set_meta(db, 'last_run_at', _stamp(_clock(now)))
        return {'disclosure_checked': disclosure_checked, 'price_checked': price_checked}


def _empty():
    return {
        'source': SOURCE, 'items': [], 'history_count': 0, 'computed_at': None,
        'operation': {'state': 'waiting', 'task_count': 0, 'pending_count': 0,
                      'disclosure_checked': 0, 'price_checked': 0, 'source_error_count': 0},
        'live': {'last_run_at': None, 'last_change_at': None, 'age_seconds': None,
                 'stalled': None, 'worker_interval_seconds': WORKER_INTERVAL},
    }


def read_dashboard(data_dir=ROOT, *, article_id=None, now=None):
    """Read only completed database transactions. The web request never verifies."""
    current = _clock(now)
    if not (Path(data_dir) / DATABASE).is_file():
        return _empty()
    with closing(_open(data_dir, read_only=True)) as db:
        db.execute('BEGIN')
        where = 'active = 1' + (' AND article_id = ?' if article_id else '')
        params = (article_id,) if article_id else ()
        total, pending, disclosures, prices, failures = db.execute(f'''
            SELECT COUNT(*),
                   SUM(json_extract(payload, '$.primary.status') = 'pending'
                       OR json_extract(payload, '$.price.status') = 'pending'),
                   SUM(json_extract(payload, '$.primary.status') NOT IN ('pending', 'source_unavailable')),
                   SUM(json_extract(payload, '$.price.status') = 'verified'),
                   SUM(json_extract(payload, '$.primary.status') IN ('source_unavailable', 'document_unavailable')
                       OR json_extract(payload, '$.price.status') IN ('source_unavailable', 'calendar_unavailable')
                       OR json_extract(payload, '$.primary.refresh_status') IS NOT NULL
                       OR json_extract(payload, '$.price.refresh_status') IS NOT NULL)
            FROM tasks WHERE {where}
        ''', params).fetchone()
        items = [json.loads(row[0]) for row in db.execute(f'''
            SELECT payload FROM tasks WHERE {where}
            ORDER BY published_at DESC, article_id DESC, task_id LIMIT ?
        ''', (*params, DISPLAY_LIMIT))]
        where_history = ' WHERE article_id = ?' if article_id else ''
        history_count = db.execute('SELECT COUNT(*) FROM history' + where_history, params).fetchone()[0]
        last_run, last_change = _meta(db, 'last_run_at'), _meta(db, 'last_change_at')
    age = round((current - _timestamp(last_run)).total_seconds()) if last_run else None
    stalled = age is not None and (age < 0 or age > 3 * WORKER_INTERVAL)
    state = 'waiting'
    if total:
        state = 'partial' if failures or stalled else 'working' if pending else 'ready'
    return {
        'source': SOURCE, 'items': items, 'computed_at': last_change, 'history_count': history_count,
        'operation': {'state': state, 'task_count': total, 'pending_count': pending or 0,
                      'disclosure_checked': disclosures or 0, 'price_checked': prices or 0,
                      'source_error_count': failures or 0},
        'live': {'last_run_at': last_run, 'last_change_at': last_change, 'age_seconds': age,
                 'stalled': stalled if last_run else None, 'worker_interval_seconds': WORKER_INTERVAL},
    }


def read_history(data_dir=ROOT, *, article_id=None):
    if not (Path(data_dir) / DATABASE).is_file():
        return {'source': SOURCE, 'items': []}
    with closing(_open(data_dir, read_only=True)) as db:
        where = ' WHERE article_id = ?' if article_id else ''
        params = (article_id,) if article_id else ()
        rows = db.execute('SELECT payload FROM history' + where + ' ORDER BY sequence DESC LIMIT ?',
                          (*params, HISTORY_LIMIT)).fetchall()
    return {'source': SOURCE, 'items': [json.loads(row[0]) for row in rows]}

"""Offline publisher and frozen prospective observation for analogue research.

GET never scans. A cross-process lock owns publication and first-day decisions.
Research scenario weights never become brokerage orders or approved exposure.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
from datetime import date
from pathlib import Path

from filelock import FileLock, Timeout

from app.services.mirofish import chart_analogue as chart
from app.utils.atomic_json import write_json_atomic


ROOT = Path(os.environ.get('MIROFISH_CHART_KELLY_ROOT', chart.INDEX_ROOT / 'kelly'))
POLICY_ID = 'chart-analogue-kelly-v1'
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_AUDIT_BYTES = 24 * 1024 * 1024
MAX_DECISIONS = 730
MAX_SCAN_SECONDS = 2700


def _engine():
    from app.services.mirofish import chart_analogue_kelly
    return chart_analogue_kelly


def _iso(value=None):
    return chart._cutoff(value).isoformat().replace('+00:00', 'Z')


def _now():
    return _iso()


def _day(value):
    return chart._cutoff(value).astimezone(chart.KST).date().isoformat()


def _read(path):
    path = Path(path)
    if not path.exists():
        return None
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError('oversized_research_artifact')
    with path.open(encoding='utf-8-sig') as handle:
        return json.load(handle, parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite_json')))


def _encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')


def _write(path, value):
    path = Path(path)
    limit = MAX_AUDIT_BYTES if path.parent.name == 'runs' else MAX_JSON_BYTES
    if len(_encoded(value)) > limit:
        raise ValueError('oversized_research_artifact')
    write_json_atomic(os.fspath(path), value)


def _hash(value):
    return hashlib.sha256(_encoded(value)).hexdigest()


def _stamp(source):
    return tuple(source.get(key) for key in ('source_id', 'price_basis', 'built_at', 'captured_at', 'rows', 'symbols', 'latest_session'))


def _assert_research(report):
    if (not isinstance(report, dict) or report.get('schema_version') != 1
            or report.get('policy_id') != POLICY_ID or report.get('mode') != 'research'
            or report.get('status') not in {'ready', 'blocked'}):
        raise ValueError('invalid_research_protocol')
    approval = report.get('approval') or {}
    candidates = report.get('candidates')
    if (approval.get('status') != 'held' or approval.get('approved_exposure') != 0
            or not isinstance(candidates, list) or len(candidates) > 3
            or any((row.get('kelly') or {}).get('approved_weight', 'missing') is not None for row in candidates)):
        raise ValueError('research_cannot_authorize_trades')
    _encoded(report)


def _lock(root):
    return FileLock(str(root / 'scan.lock'), thread_local=False)


def _active(root):
    if not (root / 'scan.lock').exists():
        return False
    try:
        with _lock(root).acquire(timeout=0):
            return False
    except Timeout:
        return True


def _freshness(report, root, index_root=None):
    if not report:
        return 'missing'
    _assert_research(report)
    if report['status'] == 'blocked':
        return 'stale'
    metadata, error = chart._load(full=False, index_root=index_root)
    source = metadata.get('source', {}) if metadata else {}
    universe = _read(root / 'universe.json')
    now = chart._cutoff(_now())
    scope_age = ((now.astimezone(chart.KST).date() - date.fromisoformat(universe['as_of'])).days
                 if isinstance(universe, dict) and isinstance(universe.get('as_of'), str) else -1)
    source_age = chart._freshness(source, now) if not error else -1
    valid = (not error and universe is not None and isinstance(source_age, (int, float)) and not isinstance(source_age, bool)
             and math.isfinite(source_age)
             and 0 <= scope_age <= chart.STALE_DAYS and 0 <= source_age <= chart.STALE_DAYS
             and report.get('universe_fingerprint') == _hash(universe)
             and _stamp(report.get('source') or {}) == _stamp(source)
             and chart._cutoff(source['captured_at']) <= chart._cutoff(report['as_of']) <= now)
    return 'current' if valid and report['status'] == 'ready' else 'stale'


def read_status(*, root=None, index_root=None):
    """Read bounded results and small source metadata; never collect or scan."""
    root = Path(root) if root is not None else ROOT
    default = {'state': 'none', 'processed': 0, 'total': 0, 'started_at': None, 'error': None}
    job = _read(root / 'job.json') or default
    report = _read(root / 'report.json')
    if _active(root):
        job = {**job, 'state': 'running', 'error': None}
    elif job.get('state') == 'running':
        job = _read(root / 'job.json') or job
        report = _read(root / 'report.json')
        if job.get('state') == 'running':
            job = {**job, 'state': 'error', 'error': 'scan_interrupted'}
    if job.get('state') not in {'none', 'running', 'done', 'error'}:
        raise ValueError('invalid_research_job')
    return {**job, 'freshness': _freshness(report, root, index_root), 'report': report}


def _freeze(root, report):
    journal = _read(root / 'decisions.json') or {'schema_version': 1, 'policy_id': POLICY_ID, 'items': []}
    items = journal.get('items')
    if not isinstance(items, list) or journal.get('policy_id') != POLICY_ID:
        raise ValueError('invalid_decision_journal')
    decision_at = _now()
    if chart._cutoff(report['as_of']) > chart._cutoff(decision_at):
        raise ValueError('future_decision_cutoff')
    day = _day(decision_at)
    if (_day(report['as_of']) != day or report['status'] != 'ready' or not report['candidates']
            or any(item['day'] == day for item in items)):
        return journal
    if len(items) >= MAX_DECISIONS:
        raise ValueError('decision_archive_required')
    targets = []
    for row in report['candidates']:
        price = row.get('current_close')
        if (not re.fullmatch(r'\d{6}', row.get('symbol', '')) or isinstance(price, bool)
                or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0
                or row.get('reference_session', '') > day):
            raise ValueError('invalid_frozen_target')
        targets.append({key: row[key] for key in ('symbol', 'target', 'reference_session', 'current_close')})
    journal['items'].append({'day': day, 'decision_at': decision_at, 'run_id': report['run_id'],
                             'source': {key: report['source'][key] for key in ('source_id', 'price_basis')},
                             'universe_fingerprint': report['universe_fingerprint'], 'targets': targets})
    _write(root / 'decisions.json', journal)
    return journal


def _observe(root, journal, cutoff, index_root=None):
    items = journal.get('items', [])
    if len(items) > MAX_DECISIONS:
        raise ValueError('decision_archive_required')
    rows, nets, pending, blocked = [], [], 0, 0
    loaded = chart._load(full=True, index_root=index_root) if items else None
    for item in items:
        if chart._cutoff(item['decision_at']) > chart._cutoff(cutoff):
            continue
        for target in item['targets']:
            observed = chart.observed_outcomes(
                target['symbol'], decision_at=item['decision_at'], reference_session=target['reference_session'],
                frozen_reference_close=target['current_close'], as_of=cutoff, horizons=(20,),
                expected_source_id=item['source']['source_id'], expected_price_basis=item['source']['price_basis'],
                index_root=index_root, _loaded_index=loaded,
            )
            horizon = next((row for row in observed.get('trade_horizons', []) if row.get('sessions') == 20), {})
            gross = horizon.get('gross_return_pct')
            net = None
            if horizon.get('status') == 'matured' and isinstance(gross, (int, float)) and not isinstance(gross, bool) and math.isfinite(gross):
                net = float(gross) - .33
                nets.append(net)
            elif horizon.get('status') == 'pending':
                pending += 1
            else:
                blocked += 1
            rows.append({'day': item['day'], 'symbol': target['symbol'], 'target': target['target'],
                         'decision_at': item['decision_at'], 'horizon': horizon, 'net_return_pct': net})
    summary = {'as_of': cutoff, 'decision_days': sum(chart._cutoff(item['decision_at']) <= chart._cutoff(cutoff) for item in items),
               'matured_trades': len(nets), 'pending_trades': pending, 'blocked_trades': blocked,
               'net_win_rate_pct': sum(value > 0 for value in nets) / len(nets) * 100 if nets else None,
               'expectancy_pct': sum(nets) / len(nets) if nets else None, 'independent': False}
    _write(root / 'observations.json', {'schema_version': 1, 'policy_id': POLICY_ID, 'as_of': cutoff, 'summary': summary, 'items': rows})
    return summary


def _reuse(report, root, index_root, universe_hash, as_of):
    if not report or report.get('universe_fingerprint') != universe_hash:
        return False
    if _freshness(report, root, index_root) != 'current':
        return False
    return report['as_of'] == _iso(as_of) if as_of is not None else _day(report['as_of']) == _day(_now())


def _execute(root, lock, universe, *, index_root=None, as_of=None):
    job = {'state': 'running', 'processed': 0, 'total': 0, 'started_at': _now(), 'error': None}
    try:
        cutoff = _iso(as_of) if as_of is not None else _now()
        if chart._cutoff(cutoff) > chart._cutoff(_now()):
            raise ValueError('future_decision_cutoff')
        _write(root / 'job.json', job)
        def progress(processed, total):
            job.update(processed=processed, total=total)
            _write(root / 'job.json', job)
        report = _engine().scan(universe, as_of=cutoff, index_root=index_root, progress=progress)
        _assert_research(report)
        if report['as_of'] != cutoff:
            raise ValueError('scan_cutoff_mismatch')
        audit = report.pop('_audit', {})
        report['universe_fingerprint'] = _hash(universe)
        report['run_id'] = _day(cutoff) + '-' + _hash({'source': _stamp(report.get('source') or {}), 'universe': report['universe_fingerprint'], 'cutoff': cutoff})[:16]
        journal = _freeze(root, report)
        report['forward'] = _observe(root, journal, _now(), index_root)
        _write(root / 'runs' / (report['run_id'] + '.json'), {'report': report, 'audit': audit})
        _write(root / 'report.json', report)
        counts = report['universe']
        job.update(state='done', processed=counts['processed'], total=counts['quality_passed'])
        _write(root / 'job.json', job)
        return report
    except Exception:
        job.update(state='error', error='scan_failed')
        _write(root / 'job.json', job)
        raise
    finally:
        lock.release()


def _universe(root, universe_path=None):
    path = Path(universe_path) if universe_path is not None else Path(os.environ.get('MIROFISH_CHART_KELLY_UNIVERSE', root / 'universe.json'))
    universe = _read(path)
    if not isinstance(universe, dict):
        raise ValueError('prepared_universe_required')
    return universe


def run_scan(*, root=None, index_root=None, universe_path=None, as_of=None):
    """Operator entry; same completed source/scope/cutoff is reused."""
    if as_of is not None and chart._cutoff(as_of) > chart._cutoff(_now()):
        raise ValueError('future_decision_cutoff')
    root = Path(root) if root is not None else ROOT
    root.mkdir(parents=True, exist_ok=True)
    lock = _lock(root)
    lock.acquire(timeout=MAX_SCAN_SECONDS + 30)
    try:
        universe = _universe(root, universe_path)
        fingerprint = _hash(universe)
        _write(root / 'universe.json', universe)
        previous = _read(root / 'report.json')
        if _reuse(previous, root, index_root, fingerprint, as_of):
            lock.release()
            return previous
    except Exception:
        lock.release()
        raise
    return _execute(root, lock, universe, index_root=index_root, as_of=as_of)


def start_scan(*, root=None, index_root=None):
    """Nonblocking fixed scan with durable state and one shared worker."""
    root = Path(root) if root is not None else ROOT
    state = read_status(root=root, index_root=index_root)
    if state['state'] == 'running' or (state['state'] == 'done' and state['freshness'] == 'current' and _day(state['report']['as_of']) == _day(_now())):
        return state
    root.mkdir(parents=True, exist_ok=True)
    lock = _lock(root)
    try:
        lock.acquire(timeout=0)
    except Timeout:
        return read_status(root=root, index_root=index_root)
    try:
        universe = _universe(root)
        previous = _read(root / 'report.json')
        if _reuse(previous, root, index_root, _hash(universe), None):
            lock.release()
            return read_status(root=root, index_root=index_root)
        _write(root / 'universe.json', universe)
        _write(root / 'job.json', {'state': 'running', 'processed': 0, 'total': len(universe.get('quality', {}).get('passed', [])), 'started_at': _now(), 'error': None})
    except Exception:
        lock.release()
        raise
    def work():
        try:
            _execute(root, lock, universe, index_root=index_root)
        except Exception:
            pass  # Safe durable job error, retryable on next request.
    try:
        threading.Thread(target=work, name='ChartAnalogueKelly', daemon=True).start()
    except Exception:
        lock.release()
        _write(root / 'job.json', {'state': 'error', 'processed': 0, 'total': 0, 'started_at': _now(), 'error': 'scan_failed'})
        raise
    return read_status(root=root, index_root=index_root)

"""Deterministic whole-index TOP3 with saved evidence and single-flight jobs.

This is a separate research shortlist. It does not alter existing AI Brain
rankings or place orders. GET reads small artifacts; only CLI/POST scans.
"""
from __future__ import annotations

import json
import math
import os
import statistics
import threading
import time
import uuid
from collections import Counter
from pathlib import Path

from filelock import FileLock, Timeout

from app.services.mirofish import chart_analogue as engine
from app.utils.atomic_json import write_json_atomic

ROOT = Path(os.environ.get('MIROFISH_CHART_TOP3_ROOT', engine.INDEX_ROOT / 'top3'))
RULE_VERSION = 'chart-top3-risk20-v1'
CRITERIA = {'horizon_sessions': 20, 'min_samples': 20, 'min_up_frequency_pct': 60,
            'min_p10_return_pct': -12, 'min_median_similarity': .8,
            'min_distinct_symbols': 5, 'cost_bps': 33, 'downside_weight': .5}
MAX_SCAN_SECONDS = 2700
WARNINGS = [
    'research_shortlist_forward_efficacy_unvalidated',
    'up_frequency_is_not_calibrated_probability',
    'indexed_universe_is_not_entire_exchange',
    'price_only_no_volume_flow_disclosure_or_liquidity_filter',
    'historical_samples_may_share_market_regimes',
    'p10_is_horizon_return_not_maximum_drawdown',
    'score_deducts_assumed_33_roundtrip_bps_not_actual_execution_cost',
]


def _iso(value=None):
    return engine._cutoff(value).isoformat().replace('+00:00', 'Z')


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _vintage(source):
    return tuple(source.get(key) for key in ('source_id', 'price_basis', 'built_at', 'captured_at', 'rows', 'symbols', 'latest_session'))


def _candidate(prediction, source, cutoff):
    """Return an eligible row or one primary rejection reason per symbol."""
    if prediction.get('status') != 'ready':
        return None, str(prediction.get('status') or 'invalid_prediction')
    src = prediction.get('source') or {}
    if src.get('query_collection_status') == 'cache_preserved':
        return None, 'cached_target'
    if src.get('latest_session') != source.get('latest_session'):
        return None, 'old_target_session'
    try:
        if (engine._cutoff(src['query_captured_at']) > cutoff
                or engine._cutoff(src['captured_at']) > cutoff
                or engine._cutoff(prediction['as_of']) != cutoff):
            return None, 'future_capture'
    except (ValueError, KeyError, TypeError):
        return None, 'invalid_capture'
    samples = prediction.get('sample_count')
    if not _finite(samples) or samples < CRITERIA['min_samples']:
        return None, 'too_few_samples'
    neighbors = prediction.get('neighbors') or []
    distinct = len({row.get('symbol') for row in neighbors})
    if distinct < CRITERIA['min_distinct_symbols']:
        return None, 'insufficient_diversity'
    if len(neighbors) != samples or any(not _finite(row.get('similarity')) or not 0 <= row['similarity'] <= 1 for row in neighbors):
        return None, 'invalid_neighbors'
    for row in neighbors:
        try:
            if (engine._cutoff(row['captured_at']) > cutoff
                    or row['outcome_end_date'] > cutoff.astimezone(engine.KST).date().isoformat()):
                return None, 'future_capture'
        except (ValueError, KeyError, TypeError):
            return None, 'invalid_capture'
    similarity = statistics.median(row['similarity'] for row in neighbors)
    if similarity < CRITERIA['min_median_similarity']:
        return None, 'weak_similarity'
    horizons = prediction.get('horizons') or []
    horizon = next((row for row in horizons if row.get('sessions') == 20), {})
    fields = ('median_return_pct', 'p10_return_pct', 'p90_return_pct', 'up_frequency_pct')
    if any(not _finite(horizon.get(key)) for key in fields):
        return None, 'invalid_statistics'
    median, low, high, up = (horizon[key] for key in fields)
    if not low <= median <= high or not 0 <= up <= 100:
        return None, 'invalid_statistics'
    if up < CRITERIA['min_up_frequency_pct']:
        return None, 'low_up_frequency'
    if low < CRITERIA['min_p10_return_pct']:
        return None, 'tail_risk'
    score = round(median - CRITERIA['cost_bps'] / 100 - CRITERIA['downside_weight'] * max(0, -low), 6)
    if score <= 0:
        return None, 'nonpositive_score'
    history = prediction.get('history') or []
    if not history or not _finite(history[-1].get('close')) or history[-1]['close'] <= 0:
        return None, 'invalid_price'
    return {'symbol': prediction['symbol'], 'target': prediction['target'], 'market': 'KR',
            'score': round(score, 6), 'sample_count': int(samples), 'distinct_symbols': distinct,
            'median_similarity': round(similarity, 6), 'latest_session': src['latest_session'],
            'query_captured_at': src['query_captured_at'], 'close': history[-1]['close'],
            'horizon': {'sessions': 20, **{key: horizon[key] for key in fields}},
            'reasons': ['positive_risk_adjusted_score', 'up_frequency_at_least_60',
                        'p10_at_least_minus_12', '20_diverse_historical_samples']}, None


def scan(*, as_of=None, index_root=None, progress=None):
    """Inspect every indexed symbol using the same captured arrays and cutoff."""
    cutoff = engine._cutoff(as_of)
    started = time.monotonic()
    loaded = engine._load(full=True, index_root=index_root)
    data, error = loaded
    source = dict(data['metadata']['source']) if data else {}
    report = {'schema_version': 1, 'rule_version': RULE_VERSION, 'mode': 'research',
              'status': error or 'insufficient_candidates', 'as_of': _iso(cutoff),
              'generated_at': _iso(), 'source': source,
              'criteria': dict(CRITERIA), 'candidates': [], 'warnings': list(WARNINGS),
              'universe': {'indexed': len(data['symbols']) if data else 0,
                           'processed': 0, 'eligible': 0, 'rejected': {}}}
    if error:
        return report
    if (source.get('price_basis') != 'provider_adjusted'
            or not source.get('latest_session')
            or source['latest_session'] > cutoff.astimezone(engine.KST).date().isoformat()):
        report['status'] = 'invalid_index'
        return report
    if engine._freshness(source, cutoff) > engine.STALE_DAYS:
        report['status'] = 'stale_data'
        return report
    eligible, best, rejected = [], [], Counter()
    ranking_key = lambda row: (-row['score'], -row['horizon']['up_frequency_pct'], row['symbol'])
    if progress:
        progress(0, report['universe']['indexed'])
    for symbol in data['symbols']:
        if time.monotonic() - started > MAX_SCAN_SECONDS:
            report.update(status='failed', warnings=[*WARNINGS, 'scan_time_budget_exceeded'])
            return report  # A partially scanned market must not masquerade as TOP3.
        prediction = engine.predict(str(symbol), as_of=report['as_of'], horizons=(20,), k=20,
                                    _loaded_index=loaded)
        row, reason = _candidate(prediction, source, cutoff)
        if reason:
            rejected[reason] += 1
        else:
            eligible.append(row)
            best.append((row, prediction))
            best.sort(key=lambda pair: ranking_key(pair[0]))
            del best[3:]
        report['universe'].update(processed=report['universe']['processed'] + 1,
                                  eligible=len(eligible), rejected=dict(rejected))
        if progress and (report['universe']['processed'] % 25 == 0
                         or report['universe']['processed'] == report['universe']['indexed']):
            progress(report['universe']['processed'], report['universe']['indexed'])
    eligible.sort(key=ranking_key)
    report['candidates'] = [dict(row, rank=i + 1) for i, row in enumerate(eligible[:3])]
    report['status'] = 'ready' if len(eligible) >= 3 else 'insufficient_candidates'
    report['generated_at'] = _iso()
    report['elapsed_seconds'] = round(time.monotonic() - started, 3)
    # Full ranking/rejection counts and exact selected historical evidence are
    # saved by the publisher separately, keeping public polling responses small.
    report['_audit'] = {'eligible': eligible, 'selected_forecasts': [prediction for _, prediction in best]}
    return report


def _read(path):
    if not path.exists():
        return None
    if path.stat().st_size > 256 * 1024:
        raise ValueError('oversized_scan_report')
    with path.open(encoding='utf-8') as handle:
        return json.load(handle, parse_constant=lambda value: (_ for _ in ()).throw(ValueError('invalid_json')))


def _write(path, value):
    json.dumps(value, allow_nan=False)
    write_json_atomic(os.fspath(path), value)


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


def _freshness(report, index_root=None):
    if report:
        metadata, error = engine._load(full=False, index_root=index_root)
        current = metadata['source'] if metadata else {}
        return ('current' if not error and report.get('rule_version') == RULE_VERSION
                and _vintage(report.get('source') or {}) == _vintage(current)
                and engine._freshness(current, engine._cutoff()) <= engine.STALE_DAYS
                and report.get('status') in {'ready', 'insufficient_candidates'} else 'outdated')
    return 'missing'


def read_status(*, root=None, index_root=None):
    """Small saved artifacts plus metadata-only source comparison; no scan."""
    root = Path(root) if root is not None else ROOT
    job = _read(root / 'job.json') or {'state': 'none', 'processed': 0, 'total': 0,
                                     'started_at': None, 'error': None}
    report = _read(root / 'report.json')
    freshness = _freshness(report, index_root)
    if _active(root):
        job = {**job, 'state': 'running', 'error': None}
    elif job['state'] == 'running':
        # The worker may have finished between the initial read and lock check.
        job = _read(root / 'job.json') or job
        report = _read(root / 'report.json')
        freshness = _freshness(report, index_root)
        if job['state'] == 'running':
            job = {**job, 'state': 'error', 'error': 'scan_interrupted'}
    return {**job, 'freshness': freshness, 'report': report}


def _execute(root, lock, *, index_root=None, as_of=None):
    job = {'state': 'running', 'processed': 0, 'total': 0, 'started_at': _iso(), 'error': None}
    try:
        _write(root / 'job.json', job)
        def progress(processed, total):
            job.update(processed=processed, total=total)
            _write(root / 'job.json', job)
        report = scan(as_of=as_of, index_root=index_root, progress=progress)
        audit = report.pop('_audit', {})
        run_id = report['as_of'][:10] + '-' + uuid.uuid4().hex[:12]
        report['run_id'] = run_id
        _write(root / 'runs' / (run_id + '.json'), {'report': report, 'audit': audit})
        if report['status'] in {'ready', 'insufficient_candidates'}:
            _write(root / 'report.json', report)
            job.update(state='done', processed=report['universe']['processed'],
                       total=report['universe']['indexed'])
        else:
            job.update(state='error', error=report['status'],
                       processed=report['universe']['processed'], total=report['universe']['indexed'])
        _write(root / 'job.json', job)
        return report
    except Exception:
        # Never expose provider messages, filesystem paths or credentials.
        job.update(state='error', error='scan_failed')
        _write(root / 'job.json', job)
        raise
    finally:
        lock.release()


def run_scan(*, root=None, index_root=None, as_of=None):
    """Nightly entry waits for API work, then reuses or scans the latest index.

    If the price builder publishes a new vintage while an API scan is running,
    that older result cannot satisfy the nightly run. Recheck after acquiring
    the lock and compute the newly published corpus when necessary.
    """
    root = Path(root) if root is not None else ROOT
    root.mkdir(parents=True, exist_ok=True)
    lock = _lock(root)
    lock.acquire(timeout=MAX_SCAN_SECONDS + 30)
    try:
        completed = _read(root / 'job.json') or {}
        report = _read(root / 'report.json')
        if (as_of is None and completed.get('state') == 'done'
                and _freshness(report, index_root) == 'current'):
            lock.release()
            return report
    except Exception:
        lock.release()
        raise
    return _execute(root, lock, index_root=index_root, as_of=as_of)


def start_scan(*, root=None, index_root=None):
    """Return immediately while one shared worker evaluates the corpus."""
    root = Path(root) if root is not None else ROOT
    state = read_status(root=root, index_root=index_root)
    if state['state'] == 'running' or (state['state'] == 'done' and state['freshness'] == 'current'):
        return state
    root.mkdir(parents=True, exist_ok=True)
    lock = _lock(root)
    try:
        lock.acquire(timeout=0)
    except Timeout:
        return read_status(root=root, index_root=index_root)
    # A preceding scan may finish after the optimistic read but before we own
    # the lock. Reuse that result rather than doing the same corpus twice.
    try:
        completed = _read(root / 'job.json') or {}
        if (completed.get('state') == 'done'
                and _freshness(_read(root / 'report.json'), index_root) == 'current'):
            lock.release()
            return read_status(root=root, index_root=index_root)
    except Exception:
        lock.release()
        raise
    def work():
        try:
            _execute(root, lock, index_root=index_root)
        except Exception:
            pass  # Durable job.json carries the safe error and allows retry.
    try:
        threading.Thread(target=work, name='ChartAnalogueTop3', daemon=True).start()
    except Exception:
        lock.release()
        raise
    return read_status(root=root, index_root=index_root)

"""Immutable prospective chart challenger cohorts and offline paired evaluation.

Recording reads the scanner's original forecast artifact, never predicts. Public
reads consume one cached JSON report. Only the offline evaluator reads outcomes.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from filelock import FileLock

from app.services.mirofish import chart_analogue
from app.utils.atomic_json import write_json_atomic


ROOT = Path(os.environ.get('MIROFISH_CHART_ANALOGUE_EVALUATION_ROOT',
                          Path(chart_analogue.INDEX_ROOT) / 'evaluation'))
KST = timezone(timedelta(hours=9))
HORIZONS = (5, 20, 40)
PROTOCOL = 'chart_median20_v1'
COST_BPS = 23
SLIPPAGE_BPS = 10
WARNINGS = [
    'shadow_only_no_ranking_changes',
    'only_first_valid_cohort_per_kst_day',
    'baseline_is_actual_workflow_top3_equal_weight',
    'market_etf_benchmark_unavailable',
    'net_returns_deduct_33_roundtrip_bps',
    'aggregate_returns_are_means_of_paired_daily_baskets',
    'not_calibrated_accuracy',
]


def _utc(value=None):
    if value is None:
        return datetime.now(timezone.utc)
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('explicit_timezone_required')
    return parsed.astimezone(timezone.utc)


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _strict_json(value):
    """No NaN/Infinity may enter immutable snapshots or the public report."""
    if isinstance(value, dict):
        return {str(k): _strict_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_strict_json(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _write(path, value):
    json.dumps(value, allow_nan=False)
    write_json_atomic(os.fspath(path), value)


def _reject_constant(value):
    raise ValueError('nonfinite_json')


def _read(path, default=None):
    try:
        with Path(path).open(encoding='utf-8-sig') as handle:
            return json.load(handle, parse_constant=_reject_constant)
    except FileNotFoundError:
        return default


def _snapshots(root):
    records = [_read(path) for path in sorted((root / 'snapshots').glob('*.json'))]
    if any(not isinstance(row, dict) or not row.get('snapshot_id') for row in records):
        raise ValueError('invalid_snapshot_store')
    return sorted(records, key=lambda row: (row['recorded_at'], row['snapshot_id']))


def _identity(item):
    candidate = item.get('candidate') if isinstance(item.get('candidate'), dict) else {}
    symbol = str(item.get('symbol') or candidate.get('symbol') or '')
    if not re.fullmatch(r'[0-9]{6}', symbol) or not _finite(item.get('final_score')):
        raise ValueError('invalid_candidate_identity_or_score')
    return {'symbol': symbol,
            'target': str(item.get('target') or candidate.get('display_name') or candidate.get('name') or symbol),
            'final_score': item['final_score']}


def _freeze_forecast(prediction, decision, artifact_cutoff):
    if not isinstance(prediction, dict) or prediction.get('status') != 'ready' or prediction.get('mode') != 'shadow':
        raise ValueError('forecast_not_ready')
    if not prediction.get('as_of'):
        raise ValueError('forecast_cutoff_invalid')
    cutoff = _utc(prediction['as_of'])
    if cutoff != artifact_cutoff or cutoff > decision:
        raise ValueError('forecast_cutoff_invalid')
    source = prediction.get('source') or {}
    if not isinstance(source, dict) or not source.get('source_id') or source.get('price_basis') not in {'unadjusted', 'provider_adjusted'}:
        raise ValueError('forecast_source_invalid')
    if not source.get('captured_at') or _utc(source['captured_at']) > cutoff:
        raise ValueError('forecast_capture_invalid')
    if source.get('query_captured_at') and _utc(source['query_captured_at']) > cutoff:
        raise ValueError('forecast_capture_invalid')
    if not prediction.get('model_version') or not _finite(prediction.get('sample_count')) or prediction['sample_count'] <= 0:
        raise ValueError('forecast_model_or_samples_invalid')
    history = prediction.get('history') or []
    reference = history[-1] if history and isinstance(history[-1], dict) else {}
    reference_session = str(reference.get('date') or '')
    if (not _finite(reference.get('close')) or reference['close'] <= 0
            or date.fromisoformat(reference_session) > decision.astimezone(KST).date()
            or source.get('latest_session') != reference_session):
        raise ValueError('forecast_reference_invalid')
    horizons = prediction.get('horizons')
    if not isinstance(horizons, list) or len(horizons) != 3:
        raise ValueError('forecast_horizons_invalid')
    by_session = {row.get('sessions'): row for row in horizons if isinstance(row, dict)}
    if set(by_session) != set(HORIZONS):
        raise ValueError('forecast_horizons_invalid')
    for row in horizons:
        fields = ('median_return_pct', 'p10_return_pct', 'p90_return_pct', 'up_frequency_pct')
        if any(not _finite(row.get(key)) for key in fields):
            raise ValueError('forecast_horizons_invalid')
        if (not row['p10_return_pct'] <= row['median_return_pct'] <= row['p90_return_pct']
                or not 0 <= row['up_frequency_pct'] <= 100
                or any(isinstance(value, float) and not math.isfinite(value) for value in row.values())):
            raise ValueError('forecast_horizons_invalid')
    return _strict_json({
        'symbol': prediction['symbol'], 'as_of': cutoff.isoformat(),
        'model_version': prediction['model_version'], 'sample_count': prediction['sample_count'],
        'source': source, 'reference_session': reference_session, 'reference_close': reference['close'],
        'horizons': [by_session[h] for h in HORIZONS],
    })


def record_workflow(workflow, eligible=None, forecasts=None, now=None, root=None):
    """Freeze a workflow once, during the same KST decision day, without outcomes."""
    from app.services.mirofish import alpha_scanner
    from app.services.mirofish import workflow as workflow_service

    destination = Path(root) if root is not None else Path(ROOT)
    workflow_id = str(workflow.get('id') or '')
    if not workflow_id:
        raise ValueError('workflow_id_required')
    snapshot_id = hashlib.sha256(workflow_id.encode()).hexdigest()[:32]
    destination.mkdir(parents=True, exist_ok=True)
    snapshot_path = destination / 'snapshots' / f'{snapshot_id}.json'
    with FileLock(os.fspath(destination / '.publication.lock'), timeout=30):
        existing = _read(snapshot_path)
        if existing is not None:
            # Also repairs a report publication interrupted after snapshot commit.
            _refresh_report(destination)
            return existing
        recorded = _utc(now)
        snapshot = {'schema_version': 1, 'snapshot_id': snapshot_id, 'protocol': PROTOCOL,
                    'workflow_id': workflow_id, 'scanner_run_id': workflow.get('scanner_run_id'),
                    'decision_at': workflow.get('completed_at'), 'recorded_at': recorded.isoformat(),
                    'decision_day': None, 'status': 'blocked', 'reason': None,
                    'aggregate_eligible': False, 'baseline': [], 'challenger': [], 'forecasts': {}}
        try:
            if workflow.get('status') != 'completed' or not workflow.get('completed_at'):
                raise ValueError('workflow_not_completed')
            decision = _utc(workflow['completed_at'])
            snapshot['decision_at'] = decision.isoformat()
            snapshot['decision_day'] = decision.astimezone(KST).date().isoformat()
            if decision > recorded:
                raise ValueError('decision_after_recorded_at')
            if decision.astimezone(KST).date() != recorded.astimezone(KST).date():
                raise ValueError('historical_freeze_not_allowed')
            actual_top3 = workflow.get('top3') or []
            snapshot['baseline'] = [_identity(row) for row in actual_top3]
            if len(actual_top3) != 3 or len({row['symbol'] for row in snapshot['baseline']}) != 3:
                raise ValueError('partial_baseline')
            ranked = eligible if eligible is not None else (workflow.get('analysis_runs') or [])
            qualified = workflow_service._select_top3(
                ranked, top_n=len(ranked), require_buy=workflow_service._require_buy(workflow))
            identities = [_identity(row) for row in qualified]
            symbols = {row['symbol'] for row in identities}
            if len(symbols) != len(identities) or not {row['symbol'] for row in snapshot['baseline']} <= symbols:
                raise ValueError('baseline_not_eligible')
            artifact = forecasts
            if artifact is None:
                artifact = alpha_scanner.read_scanner_run_artifact(workflow.get('scanner_run_id'), 'chart_analogue.json')
            if not isinstance(artifact, dict) or artifact.get('run_id') != workflow.get('scanner_run_id'):
                raise ValueError('original_scanner_forecasts_unavailable')
            if not artifact.get('as_of') or not artifact.get('generated_at'):
                raise ValueError('forecast_cutoff_invalid')
            artifact_cutoff = _utc(artifact['as_of'])
            if artifact_cutoff > decision or _utc(artifact.get('generated_at')) > decision:
                raise ValueError('forecast_cutoff_invalid')
            indexed = {}
            for row in artifact.get('items') or []:
                if isinstance(row, dict) and row.get('symbol') in symbols:
                    if row['symbol'] in indexed:
                        raise ValueError('duplicate_forecast_identity')
                    indexed[row['symbol']] = row
            for identity in identities:
                symbol = identity['symbol']
                if symbol not in indexed:
                    raise ValueError('incomplete_forecast_coverage')
                snapshot['forecasts'][symbol] = _freeze_forecast(indexed[symbol], decision, artifact_cutoff)
            challenger = sorted(identities, key=lambda row: (
                -snapshot['forecasts'][row['symbol']]['horizons'][1]['median_return_pct'],
                -row['final_score'], row['symbol']))[:3]
            if len(challenger) != 3:
                raise ValueError('partial_challenger')
            snapshot['challenger'] = challenger
            already_selected = any(row.get('aggregate_eligible') and row.get('decision_day') == snapshot['decision_day']
                                   for row in _snapshots(destination))
            snapshot.update(status='frozen', reason='intraday_excluded' if already_selected else None,
                            aggregate_eligible=not already_selected)
        except (ValueError, TypeError, KeyError) as exc:
            snapshot['reason'] = str(exc) if isinstance(exc, ValueError) else 'invalid_workflow_or_forecast_contract'
        snapshot = _strict_json(snapshot)
        _write(snapshot_path, snapshot)
        _refresh_report(destination)
        return snapshot


def _empty_horizon(sessions, status='pending', observed_sessions=0):
    return {'sessions': sessions, 'status': status, 'observed_sessions': observed_sessions,
            'baseline_net_return_pct': None, 'challenger_net_return_pct': None, 'excess_return_pct': None}


def _vintage(source):
    """Check stable corpus metadata, excluding symbol-specific capture fields."""
    keys = ('source_id', 'price_basis', 'built_at', 'rows', 'symbols')
    if not isinstance(source, dict) or any(source.get(key) is None for key in keys):
        return None
    canonical = json.dumps({key: source[key] for key in keys}, sort_keys=True, allow_nan=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _paired_horizons(snapshot, outcomes, as_of):
    symbols = {row['symbol'] for row in snapshot['baseline'] + snapshot['challenger']}
    result = []
    for sessions in HORIZONS:
        legs = {}
        for symbol in symbols:
            payload = outcomes.get(symbol) or {}
            payload = payload if isinstance(payload, dict) else {}
            rows = payload.get('trade_horizons') or []
            rows = rows if isinstance(rows, list) else []
            matches = [row for row in rows if isinstance(row, dict) and row.get('sessions') == sessions]
            leg = matches[0] if len(matches) == 1 else {'status': 'blocked', 'observed_sessions': 0}
            if leg.get('status') not in ('pending', 'blocked', 'matured'):
                leg = {'status': 'blocked', 'observed_sessions': 0}
            if leg.get('status') == 'matured':
                try:
                    if (not _finite(leg.get('gross_return_pct')) or not _finite(leg.get('entry_close'))
                            or not _finite(leg.get('exit_close')) or leg['entry_close'] <= 0 or leg['exit_close'] <= 0
                            or date.fromisoformat(leg['entry_date']) <= _utc(snapshot['decision_at']).astimezone(KST).date()
                            or date.fromisoformat(leg['exit_date']) <= date.fromisoformat(leg['entry_date'])
                            or not leg.get('captured_at') or _utc(leg['captured_at']) > as_of):
                        raise ValueError('invalid_matured_outcome')
                except (ValueError, KeyError, TypeError):
                    leg = {**leg, 'status': 'blocked'}
            legs[symbol] = leg
        observed = min((max(0, int(row.get('observed_sessions') or 0))
                        if _finite(row.get('observed_sessions')) else 0 for row in legs.values()), default=0)
        state = ('blocked' if any(row['status'] == 'blocked' for row in legs.values()) else
                 'pending' if any(row['status'] == 'pending' for row in legs.values()) else 'matured')
        horizon = _empty_horizon(sessions, state, observed)
        if state == 'matured':
            baseline = sum(legs[row['symbol']]['gross_return_pct'] / 3 for row in snapshot['baseline'])
            challenger = sum(legs[row['symbol']]['gross_return_pct'] / 3 for row in snapshot['challenger'])
            net_cost = (COST_BPS + SLIPPAGE_BPS) / 100
            horizon.update(baseline_net_return_pct=round(baseline - net_cost, 8),
                           challenger_net_return_pct=round(challenger - net_cost, 8),
                           excess_return_pct=round(challenger - baseline, 8))
        result.append(horizon)
    return result


def _base_report():
    return {'schema_version': 1, 'status': 'collecting', 'evaluated_at': None, 'protocol': PROTOCOL,
            'ranking_effect': 'none', 'cost_bps': COST_BPS, 'slippage_bps': SLIPPAGE_BPS,
            'counts': {'recorded': 0, 'eligible_days': 0, 'pending': 0, 'blocked': 0, 'intraday_excluded': 0},
            'horizons': [{'sessions': h, 'paired_days': 0, 'pending_days': 0, 'blocked_days': 0,
                          'baseline_net_return_pct': None, 'challenger_net_return_pct': None,
                          'excess_return_pct': None} for h in HORIZONS], 'recent': [], 'warnings': list(WARNINGS)}


def _build_report(snapshots, evaluations):
    report = _base_report()
    report['evaluated_at'] = evaluations.get('evaluated_at')
    evaluated = evaluations.get('items') or {}
    all_rows = []
    paired = {h: [] for h in HORIZONS}
    for snapshot in snapshots:
        report['counts']['recorded'] += 1
        try:
            decision_at = _utc(snapshot['decision_at']).isoformat() if snapshot.get('decision_at') else None
        except (ValueError, TypeError):
            decision_at = None
        row = {'workflow_id': snapshot['workflow_id'], 'decision_at': decision_at,
               'status': 'blocked', 'reason': snapshot.get('reason'),
               'baseline': [{key: item[key] for key in ('symbol', 'target')} for item in snapshot['baseline']],
               'challenger': [{key: item[key] for key in ('symbol', 'target')} for item in snapshot['challenger']],
               'horizons': []}
        if snapshot['status'] == 'blocked':
            report['counts']['blocked'] += 1
        elif not snapshot['aggregate_eligible']:
            report['counts']['intraday_excluded'] += 1
        else:
            report['counts']['eligible_days'] += 1
            row['horizons'] = (evaluated.get(snapshot['snapshot_id']) or {}).get('horizons') or [_empty_horizon(h) for h in HORIZONS]
            states = {h['status'] for h in row['horizons']}
            row['status'] = 'blocked' if 'blocked' in states else 'pending' if 'pending' in states else 'matured'
            row['reason'] = 'outcome_leg_blocked' if row['status'] == 'blocked' else None
            report['counts']['pending'] += int('pending' in states)
            report['counts']['blocked'] += int('blocked' in states)
            for horizon in row['horizons']:
                summary = next(h for h in report['horizons'] if h['sessions'] == horizon['sessions'])
                if horizon['status'] == 'matured':
                    summary['paired_days'] += 1
                    paired[horizon['sessions']].append(horizon)
                elif horizon['status'] == 'pending':
                    summary['pending_days'] += 1
                else:
                    summary['blocked_days'] += 1
        if decision_at is not None:
            all_rows.append(row)
    for horizon in report['horizons']:
        days = paired[horizon['sessions']]
        if days:
            for field in ('baseline_net_return_pct', 'challenger_net_return_pct', 'excess_return_pct'):
                horizon[field] = round(sum(day[field] / len(days) for day in days), 8)
            report['status'] = 'ready'
    report['recent'] = list(reversed(all_rows))[:10]
    return report


def _refresh_report(destination):
    # Called under the publication lock; consumes JSON only, never price data.
    evaluations = _read(destination / 'evaluations.json', {})
    report = _build_report(_snapshots(destination), evaluations)
    _write(destination / 'report.json', report)
    return report


def evaluate(root=None, as_of=None, index_root=None):
    """Offline evaluator. Keep the originally selected baskets, including failures."""
    from app.services.mirofish import chart_analogue

    destination = Path(root) if root is not None else Path(ROOT)
    destination.mkdir(parents=True, exist_ok=True)
    cutoff = _utc(as_of)
    with FileLock(os.fspath(destination / '.publication.lock'), timeout=30):
        snapshots = [row for row in _snapshots(destination) if _utc(row['recorded_at']) <= cutoff]
        evaluations = {'evaluated_at': cutoff.isoformat(), 'items': {}}
        loaded_index = chart_analogue._load(full=True, index_root=index_root) if any(
            row['aggregate_eligible'] for row in snapshots) else (None, None)
        index_data = loaded_index[0]
        expected_vintage = _vintage(index_data['metadata']['source']) if isinstance(index_data, dict) else None
        for snapshot in snapshots:
            if not snapshot['aggregate_eligible']:
                continue
            outcomes = {}
            symbols = list(dict.fromkeys(row['symbol'] for row in snapshot['baseline'] + snapshot['challenger']))
            for symbol in symbols:
                forecast = snapshot['forecasts'][symbol]
                try:
                    outcomes[symbol] = chart_analogue.observed_outcomes(
                        symbol, decision_at=snapshot['decision_at'],
                        reference_session=forecast['reference_session'], frozen_reference_close=forecast['reference_close'],
                        as_of=cutoff.isoformat(), expected_source_id=forecast['source']['source_id'],
                        expected_price_basis=forecast['source']['price_basis'], index_root=index_root,
                        _loaded_index=loaded_index)
                    if expected_vintage and (not isinstance(outcomes[symbol], dict)
                                             or _vintage(outcomes[symbol].get('source')) != expected_vintage):
                        outcomes[symbol] = {'status': 'blocked', 'reason': 'evaluation_vintage_mismatch',
                                            'trade_horizons': []}
                except Exception as exc:
                    outcomes[symbol] = {'status': 'blocked', 'reason': f'observed_outcomes_failed:{type(exc).__name__}',
                                        'trade_horizons': []}
            evaluations['items'][snapshot['snapshot_id']] = {
                'horizons': _paired_horizons(snapshot, outcomes, cutoff), 'outcomes': _strict_json(outcomes)}
        report = _build_report(snapshots, evaluations)
        _write(destination / 'evaluations.json', evaluations)
        _write(destination / 'report.json', report)
        return report


def read_report(root=None):
    """Cheap public read; no snapshot scan, prediction, outcome or vendor calls."""
    destination = Path(root) if root is not None else Path(ROOT)
    try:
        report = _read(destination / 'report.json')
        if report is None:
            return _base_report()
        if not isinstance(report, dict) or report.get('schema_version') != 1 or report.get('protocol') != PROTOCOL:
            raise ValueError('invalid_cached_report')
        json.dumps(report, allow_nan=False)
        return report
    except (OSError, ValueError, TypeError):
        report = _base_report()
        report.update(status='unavailable', warnings=[*WARNINGS, 'cached_report_unavailable'])
        return report

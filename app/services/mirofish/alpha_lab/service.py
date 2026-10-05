"""Fixed-policy AlphaLab orchestration; GET is a saved, cheap status read."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path, PureWindowsPath
from statistics import fmean
import threading

from filelock import FileLock, Timeout

from .analyst_context import build_analyst_context, build_entry_guard
from .data import file_hash, load_inputs
from .research import ResearchConfig, run_research
from . import store

ROOT = Path(os.environ.get('MARKETFLOW_ALPHA_LAB_ROOT', Path(__file__).resolve().parents[4] / 'data' / 'alpha_lab'))
REFERENCES = [
    dict(name='Qlib: factor and model research', url='https://github.com/microsoft/qlib'),
    dict(name='FreqAI: causal rolling evaluation', url='https://www.freqtrade.io/en/stable/freqai-running/'),
    dict(name='Freqtrade: lookahead analysis', url='https://www.freqtrade.io/en/stable/lookahead-analysis/'),
    dict(name='Thorp: Kelly criterion', url='https://www.edwardothorp.com/wp-content/uploads/2016/11/TheKellyCriterionAndTheStockMarket.pdf'),
]


def resolve_inputs(root):
    base = (Path(root) / 'inputs').resolve()
    path = base / 'current.json'
    if not path.is_file() or path.stat().st_size > 32768:
        raise ValueError('input_pointer_unavailable')
    pointer = json.loads(path.read_text(encoding='utf-8-sig'))
    if pointer.get('schema_version') != 1:
        raise ValueError('input_pointer_invalid')
    paths = []
    for key in ('prices', 'price_manifest', 'universe_report'):
        value = pointer.get(key)
        if (not isinstance(value, str) or Path(value).is_absolute() or PureWindowsPath(value).drive
                or '..' in PureWindowsPath(value).parts):
            raise ValueError('input_pointer_escape')
        target = (base / value).resolve()
        if not target.is_relative_to(base) or not target.is_file():
            raise ValueError('input_pointer_unavailable')
        if pointer.get('hashes') and pointer['hashes'].get(key) != file_hash(target):
            raise ValueError('input_pointer_hash_mismatch')
        paths.append(target)
    return tuple(paths)


def _performance(phase):
    values = phase.get('closed_net_returns') or []
    metrics = phase.get('metrics') or {}
    return dict(net_total_return=metrics.get('net_total_return'), max_drawdown=metrics.get('max_drawdown'),
                trades=len(values), win_rate=sum(value > 0 for value in values)/len(values) if values else None)


def normalize_report(core, inputs, *, now=None):
    now = store.timestamp(now)
    periods = core['protocol'].get('periods') or {}
    if not periods or not periods['train']['end'] < periods['validation']['end'] < periods['test']['start']:
        raise ValueError('insufficient_chronological_history')
    champion = core.get('champion')
    selected = next((row for row in core['strategies'] if champion and row['strategy_id'] == champion['strategy_id']), None)
    def economic_reasons(strategy):
        result = []
        if strategy['test']['metrics']['net_total_return'] <= 0:
            result.append('heldout_test_net_loss')
        if strategy['stress']['test']['metrics']['net_total_return'] <= 0:
            result.append('heldout_cost_stress_net_loss')
        if len(strategy['test'].get('closed_net_returns') or []) < 30:
            result.append('heldout_insufficient_completed_outcomes')
        return result
    economic_holds = economic_reasons(selected) if selected else ['no_validation_qualified_champion']
    warnings = list(dict.fromkeys([*inputs['warnings'], 'recent_fixed_split_not_full_multiyear_walkforward',
                'correlated_outcomes_not_independent_trials', 'hypothetical_costs_and_liquidity_not_guaranteed',
                'diagnostic_backtest_10pct_not_approved_allocation', 'allocation_caps_allow_subsequent_price_drift']))
    candidates = []
    for raw in core['candidates']:
        risk = raw['risk']; reasons = list(dict.fromkeys([*raw.get('reasons', []), *risk.get('held_reasons', []), *economic_holds]))
        plan = raw.get('plan')
        eligible = bool(champion and not economic_holds and risk.get('qualified') and raw.get('setup_active') and inputs['status'] == 'ready'
                        and inputs['provenance']['analysis_ready'])
        if not raw.get('setup_active'):
            reasons.append('entry_setup_inactive')
        if not inputs['provenance']['analysis_ready']:
            reasons.append('source_verification_required')
        candidates.append(dict(symbol=raw['symbol'], name=raw['name'], strategy_id=raw.get('strategy_id', raw.get('strategy')),
            score=raw['score'], last_close=raw['last_close'], quote_session=raw.get('as_of'), plan={key: plan[key] for key in
                ('entry_price', 'stop_price', 'target_price', 'loss_fraction')} if plan and plan['entry_price'] > 0 else None,
            risk=dict(weight=risk['weight'] if eligible else 0., status='research' if eligible else 'held',
                      reasons=reasons, p=risk.get('p'), kelly_raw=risk.get('raw_fraction'),
                      research_weight=risk.get('weight', 0.), planned_account_risk=risk.get('planned_account_risk', 0.)),
            reasons=reasons, setup_active=raw.get('setup_active', False)))
    strategies = []
    for raw in core['strategies']:
        values = raw['validation'].get('closed_net_returns') or []
        strategies.append(dict(strategy_id=raw['strategy_id'], name=raw['name'],
            validation=dict(trades=len(values), win_rate=sum(value > 0 for value in values)/len(values) if values else None,
                            mean_net_return=fmean(values) if values else None),
            test=_performance(raw['test']), stress=_performance(raw['stress']['test']),
            qualified=raw['calibration']['qualified'] and not economic_reasons(raw),
            reasons=[*raw['calibration'].get('held_reasons', []), *economic_reasons(raw)],
            validation_performance=_performance(raw['validation']),
            calibrated_test=_performance(raw['calibrated_test']) if raw.get('calibrated_test') else None,
            limit_drift=raw['test'].get('observed_limit_drift', {})))
    reasons = list(dict.fromkeys([*inputs['reasons'], *core['diagnostics'].get('held_reasons', []), *economic_holds]))
    report = dict(schema_version=1, mode='research', as_of=inputs['latest_session']+'T00:00:00Z', decision_at=now,
        universe=inputs['universe'], provenance=inputs['provenance'], latest_session=inputs['latest_session'],
        champion=dict(strategy_id=champion['strategy_id'] if champion else None, selection_basis='validation_only',
                      status='research' if champion and not economic_holds else 'held', reasons=reasons),
        strategies=strategies, candidates=candidates, warnings=warnings,
        agents=[dict(id='data', name='데이터 감시', status=inputs['status'], detail='시총 상위 100종목의 현재 재무 품질과 가격 출처 검사'),
                dict(id='factors', name='요인 검출', status='complete', detail='모멘텀·유동성 돌파·평균회귀·학습 순위 비교'),
                dict(id='learner', name='학습 모델', status='complete', detail='학습 기간 정규화와 성숙한 순수익 라벨 사용'),
                dict(id='critic', name='검증 심사', status='complete', detail='검증 기간 전용 선택·별도 테스트·비용 2배 스트레스'),
                dict(id='risk', name='켈리 리스크', status='held', detail='순수익 켈리·단일 종목 20% 상한·계좌 계획 손실 1% 이내'),
                dict(id='monitor', name='전향 성과 감시', status='collecting', detail='오늘 고정한 관찰 종목을 이후 실제 일봉으로 추적')],
        forward=dict(decisions=0, matured=0, win_rate=None, mean_net_return=None),
        protocol=dict(train_end=periods['train']['end'], validation_end=periods['validation']['end'],
                      test_start=periods['test']['start'], horizon_sessions=core['protocol']['configuration']['policy']['horizon'],
                      source_references=REFERENCES, evaluation='recent_frozen_chronological_split',
                      execution='next_union_session_open_IOC_stop_first', cost_stress_multiplier=2.,
                      score_interpretation='ranking_score_not_probability'),
        approval=dict(status='held', approved_exposure=0., live_orders=False),
        input_fingerprint=inputs['input_fingerprint'], diagnostics=inputs.get('diagnostics', {}))
    json.dumps(report, allow_nan=False)
    return report


def _lock(root):
    Path(root).mkdir(parents=True, exist_ok=True)
    return FileLock(str(Path(root)/'scan.lock'), thread_local=False)


def discover_opportunities(*args, **kwargs):
    from .discovery import discover_opportunities as discover
    return discover(*args, **kwargs)


def build_opportunity_board(*args, **kwargs):
    from .decision_engine import build_opportunity_board as build
    return build(*args, **kwargs)


def _held_opportunity_board(report):
    fingerprint = report['input_fingerprint']
    audit = report['opportunity_scan']['audit_hash']
    identity = store._hash(dict(policy='profit-opportunity-v1', input_fingerprint=fingerprint,
                               source_audit_hash=audit, stage='unavailable'))
    return dict(schema_version=1, policy_version='profit-opportunity-v1', decision_id=identity,
        input_fingerprint=fingerprint, source_audit_hash=audit, generated_at=report['decision_at'],
        latest_session=report['latest_session'], entry_session=None, valid_until=None, status='held',
        research_only=True, live_orders=False, coverage=dict(inspected=0, eligible=0, selected=0),
        candidates=[], alternatives=[], reasons=['opportunity_engine_unavailable'],
        stages=[dict(id='data', status='unavailable', detail='분석 자료를 갱신한 후 다시 확인해 주세요.', count=0)])


def _add_decision_engine(root, report, inputs, discovery):
    from . import opportunity_store
    try:
        board = build_opportunity_board(discovery, inputs['prices_by_symbol'], report, now=report['decision_at'])
        report['opportunity_board'] = opportunity_store.register_board(root, board)
        view = opportunity_store.attach_saved(dict(state='held', report=report), root, now=report['decision_at'])
        report['opportunity_board'] = view['report']['opportunity_board']
    except Exception as exc:
        logging.getLogger(__name__).warning('Opportunity engine held (%s)', type(exc).__name__)
        report['opportunity_board'] = _held_opportunity_board(report)


def _add_opportunities(root, report, inputs):
    from copy import deepcopy
    from .proposals import present_status
    discovery = discover_opportunities(inputs['prices_by_symbol'], names=inputs['names'],
                                      as_of=inputs['latest_session'], candidate_limit=100)
    all_discovery = deepcopy(discovery)
    # The original BUY3 artifact and both old journals keep their exact identity.
    discovery['candidates'] = discovery['candidates'][:3]
    digest = store._hash(discovery)
    path = Path(root)/'opportunities'/'runs'/f"{inputs['latest_session']}-{inputs['input_fingerprint'][:12]}-{digest}.json"
    if not path.exists():
        store._write(path, discovery)
    elif store._hash(store._read(path)) != digest:
        raise ValueError('opportunity_integrity')
    public = deepcopy(discovery)
    report['buy_candidates'] = public.pop('candidates')
    # Bind descriptive factors to the exact canonical snapshot. The existing
    # discovery hash, selection and net-Kelly calculations remain unchanged.
    context_prices = {symbol: inputs['prices_by_symbol'].get(symbol, []) for symbol in inputs['names']}
    contexts = build_analyst_context(context_prices, as_of=inputs['latest_session'],
                                    input_fingerprint=inputs['input_fingerprint'])
    context_audit = dict(schema_version=1, policy_version='quality-analyst-context-v1',
                         latest_session=inputs['latest_session'], input_fingerprint=inputs['input_fingerprint'],
                         opportunity_audit_hash=digest, universe=deepcopy(inputs['universe']),
                         provenance=deepcopy(inputs['provenance']), contexts=contexts)
    context_hash = store._hash(context_audit)
    context_path = Path(root)/'opportunities'/'context-runs'/f"{inputs['latest_session']}-{inputs['input_fingerprint'][:12]}-{context_hash}.json"
    if not context_path.exists():
        store._write(context_path, context_audit)
    elif store._hash(store._read(context_path)) != context_hash:
        raise ValueError('analyst_context_integrity')
    for row in report['buy_candidates']:
        if row['symbol'] in contexts:
            row['analyst_context'] = deepcopy(contexts[row['symbol']])
        row['entry_guard'] = build_entry_guard(row['symbol'], row['quote_session'], row['last_close'],
                                              inputs['input_fingerprint'])
    ready_contexts = sum(row['status'] == 'ready' for row in contexts.values())
    report['agents'].append(dict(id='price_context', name='가격 요인 대조',
        status='complete' if ready_contexts else 'unavailable',
        detail=f"현재 재무 품질 코호트 {len(contexts)}종목 중 {ready_contexts}종목의 고정 4개 가격 요인 참고 비교 · 매수 선정·비중에 미반영"))
    public['analyst_context_audit_hash'] = context_hash
    public.pop('audit', None)
    public['audit_hash'] = digest
    public['status'] = inputs['status']
    report['opportunity_scan'] = public
    view = present_status(dict(state='held', report=report), now=report['decision_at'])['report']
    forward_report = dict(report, candidates=[row for row in view['buy_candidates']
                                             if row.get('proposal', {}).get('action') == 'buy'])
    public['forward'] = store.observe_and_freeze(Path(root)/'opportunities', forward_report,
                                                inputs['prices_by_symbol'], now=report['decision_at'])
    _add_decision_engine(root, report, inputs, all_discovery)

def _execute(root):
    try:
        inputs = load_inputs(*resolve_inputs(root))
        attempt_path = Path(root)/'inputs'/'last_attempt.json'
        if attempt_path.is_file() and attempt_path.stat().st_size < 32768:
            attempt = json.loads(attempt_path.read_text(encoding='utf-8-sig'))
            if attempt.get('status') == 'failed':
                inputs['status'] = 'held'
                inputs['reasons'].append('input_refresh_failed_previous_snapshot_retained')
                inputs['warnings'].append('input_refresh_failed_previous_snapshot_retained')
        core = run_research(inputs['prices_by_symbol'], names=inputs['names'],
                            config=ResearchConfig(as_of=inputs['latest_session']))
        report = normalize_report(core, inputs)
        _add_opportunities(root, report, inputs)
        report['forward'] = store.observe_and_freeze(root, report, inputs['prices_by_symbol'])
        # Full replay evidence is private local data; the member API publishes a compact, path-free view.
        report['experiment_hash'] = store._hash(core)
        audit_path = Path(root)/'runs'/f"{report['latest_session']}-{inputs['input_fingerprint'][:12]}-{report['experiment_hash']}.json"
        if not audit_path.exists():
            store._write(audit_path, core)
        elif store._hash(store._read(audit_path)) != report['experiment_hash']:
            raise ValueError('experiment_integrity')
        published = store.publish(root, report, held=inputs['status'] != 'ready' or report['champion']['status'] == 'held'
                                  or not inputs['provenance']['analysis_ready'])
        from .monitor import register_report
        register_report(root, report, now=report['decision_at'])
        return published
    except Exception as exc:
        logging.getLogger(__name__).warning('AlphaLab scan failed (%s)', type(exc).__name__)
        return store.set_failure(root)


def read_status(*, now=None):
    # Saved projections only: no quote/source acquisition, fitting or writes.
    from .monitor import attach_operations
    from . import opportunity_store
    from .decision_engine import project_opportunity_board
    status = attach_operations(store.read_status(ROOT, now=now), ROOT, now=now)
    status = opportunity_store.attach_saved(status, ROOT, now=now)
    board = (status.get('report') or {}).get('opportunity_board')
    try:
        snapshot = opportunity_store.read_quote_snapshot(ROOT, board)
    except (OSError, ValueError, KeyError, TypeError):
        snapshot = None
        if isinstance(board, dict):
            board.update(status='held', reasons=list(dict.fromkeys(
                [*board.get('reasons', []), 'opportunity_store_unavailable'])))
    return project_opportunity_board(status, now=now, quote_snapshot=snapshot)


def scan_once(root=None):
    root = Path(root) if root is not None else ROOT
    try:
        with _lock(root).acquire(timeout=0):
            store.set_running(root)
            return _execute(root)
    except Timeout:
        return store.read_status(root)


def start_scan():
    from .decision_engine import project_opportunity_board
    root = ROOT; lock = _lock(root)
    try:
        lock.acquire(timeout=0)
    except Timeout:
        return project_opportunity_board(store.read_status(root))
    try:
        status = store.set_running(root)
        def run():
            try:
                _execute(root)
            finally:
                lock.release()
        threading.Thread(target=run, name='alpha-lab-research', daemon=True).start()
        return project_opportunity_board(status)
    except Exception:
        lock.release()
        raise

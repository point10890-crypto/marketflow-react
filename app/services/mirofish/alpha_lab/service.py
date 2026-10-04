"""Fixed-policy AlphaLab orchestration; GET is a saved, cheap status read."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path, PureWindowsPath
from statistics import fmean
import threading

from filelock import FileLock, Timeout

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


def _add_opportunities(root, report, inputs):
    from copy import deepcopy
    from .proposals import present_status
    discovery = discover_opportunities(inputs['prices_by_symbol'], names=inputs['names'],
                                      as_of=inputs['latest_session'])
    digest = store._hash(discovery)
    path = Path(root)/'opportunities'/'runs'/f"{inputs['latest_session']}-{inputs['input_fingerprint'][:12]}-{digest}.json"
    if not path.exists():
        store._write(path, discovery)
    elif store._hash(store._read(path)) != digest:
        raise ValueError('opportunity_integrity')
    public = deepcopy(discovery)
    report['buy_candidates'] = public.pop('candidates')
    public.pop('audit', None)
    public['audit_hash'] = digest
    public['status'] = inputs['status']
    report['opportunity_scan'] = public
    view = present_status(dict(state='held', report=report), now=report['decision_at'])['report']
    forward_report = dict(report, candidates=[row for row in view['buy_candidates']
                                             if row.get('proposal', {}).get('action') == 'buy'])
    public['forward'] = store.observe_and_freeze(Path(root)/'opportunities', forward_report,
                                                inputs['prices_by_symbol'], now=report['decision_at'])

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
        return store.publish(root, report, held=inputs['status'] != 'ready' or report['champion']['status'] == 'held'
                             or not inputs['provenance']['analysis_ready'])
    except Exception as exc:
        logging.getLogger(__name__).warning('AlphaLab scan failed (%s)', type(exc).__name__)
        return store.set_failure(root)


def read_status():
    return store.read_status(ROOT)


def scan_once(root=None):
    root = Path(root) if root is not None else ROOT
    try:
        with _lock(root).acquire(timeout=0):
            store.set_running(root)
            return _execute(root)
    except Timeout:
        return store.read_status(root)


def start_scan():
    root = ROOT; lock = _lock(root)
    try:
        lock.acquire(timeout=0)
    except Timeout:
        return store.read_status(root)
    try:
        status = store.set_running(root)
        def run():
            try:
                _execute(root)
            finally:
                lock.release()
        threading.Thread(target=run, name='alpha-lab-research', daemon=True).start()
        return status
    except Exception:
        lock.release()
        raise

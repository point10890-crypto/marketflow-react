import threading
from concurrent.futures import Future
from datetime import datetime, timedelta, timezone

import pytest

from app.services.mirofish import multi_mcp_orchestrator as orchestrator


def _candidate(symbol='005380', name='현대차'):
    observed_at = datetime.now(timezone.utc).isoformat()
    return {
        'symbol': symbol,
        'name': name,
        'price': 100000,
        'change_pct': 3.0,
        'volume': 1000000,
        'source': 'KIS',
        'market': 'KOSPI',
        'observed_at': observed_at,
        'source_packets': [{
            'evidence_id': f'kis-{symbol}', 'source': 'KIS',
            'fetched_at': observed_at, 'freshness': 'live', 'confidence': 1.0,
            'content': {'price': 100000, 'change_pct': 3.0, 'volume': 1000000},
        }],
    }


def test_architecture_separates_evidence_mcp_from_decision_agents():
    manifest = orchestrator.architecture_manifest()
    domains = {row['id'] for row in manifest['mcp_domains']}
    assert {'market', 'technical', 'evidence', 'memory', 'debate', 'cio'} <= domains
    assert manifest['numeric_authority'] == 'deterministic_mcp_tools_only'
    assert manifest['hard_rules']['forced_top3'] is True
    assert manifest['hard_rules']['fallback_source'] == 'verified_fresh_kis_only'


def test_downtrend_candidate_reaches_agents_with_explicit_risk_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr(orchestrator, 'RUNS_ROOT', str(tmp_path))
    monkeypatch.setattr(orchestrator.crash_rebound_gate, 'read_latest_crash_rebound_gate', lambda: {})
    monkeypatch.setattr(orchestrator.fear_index, 'read_latest_fear_index', lambda: {})
    monkeypatch.setattr(
        orchestrator.mcp_resource_catalog,
        'build_mcp_resource_snapshot',
        lambda **kwargs: {'status': 'ready', 'resources': []},
    )
    monkeypatch.setattr(
        orchestrator,
        'get_price_trend_metrics',
        lambda *args, **kwargs: {
            'sample_days': 120,
            'trend_5d_pct': -17,
            'trend_20d_pct': -27,
            'over_ma20_pct': -18,
            'trend_score': 0,
            'drawdown_20d_pct': 29,
        },
    )
    monkeypatch.setattr(
        orchestrator.tradingagents,
        'run_deep_analysis',
        lambda *args, **kwargs: {
            'id': 'downtrend-review',
            'verdict': {'verdict': 'HOLD', 'confidence': 55},
        },
    )

    result = orchestrator.run_multi_mcp_analysis([_candidate()], use_llm=True)

    assert result['status'] == 'selective_portfolio'
    assert result['profit_gate_passed_count'] == 1
    assert [row['symbol'] for row in result['selected']] == ['005380']
    assert result['selected'][0]['selection_source'] == 'deterministic_kis_fallback'
    assert result['top3_shortfall'] == 2
    assert 'positive_5d' in result['evidence_packets'][0]['profit_gate']['risk_flags']


def test_mutual_agents_can_approve_only_verified_symbol(monkeypatch, tmp_path):
    monkeypatch.setattr(orchestrator, 'RUNS_ROOT', str(tmp_path))
    monkeypatch.setattr(orchestrator.crash_rebound_gate, 'read_latest_crash_rebound_gate', lambda: {})
    monkeypatch.setattr(orchestrator.fear_index, 'read_latest_fear_index', lambda: {})
    monkeypatch.setattr(
        orchestrator.mcp_resource_catalog,
        'build_mcp_resource_snapshot',
        lambda **kwargs: {'status': 'ready', 'resources': [{}]},
    )
    monkeypatch.setattr(
        orchestrator,
        'get_price_trend_metrics',
        lambda *args, **kwargs: {
            'sample_days': 120,
            'trend_5d_pct': 8,
            'trend_20d_pct': 20,
            'over_ma20_pct': 12,
            'trend_score': 12,
            'drawdown_20d_pct': 4,
        },
    )
    monkeypatch.setattr(
        orchestrator.tradingagents,
        'run_deep_analysis',
        lambda target, **kwargs: {
            'id': 'ta_test',
            'analyst_reports': [{'role': 'technical', 'score': 80}],
            'research_debate': {'bull_case': 'trend', 'bear_case': 'valuation'},
            'trader_risk': {'pm_decision': {'verdict': 'BUY'}},
            'verdict': {'verdict': 'BUY', 'confidence': 82, 'reasoning': 'consensus'},
        },
    )

    result = orchestrator.run_multi_mcp_analysis(
        [_candidate('123456', '검증종목')],
        use_llm=True,
    )

    assert result['status'] == 'selective_portfolio'
    assert [row['symbol'] for row in result['selected']] == ['123456']
    assert result['selected'][0]['approved'] is True
    assert result['selected'][0]['selection_source'] == 'ai_verified'
    assert result['selection_mode'] == 'ai_only'
    assert result['top3_shortfall'] == 2


def _stub_context(monkeypatch, tmp_path, *, trend=None, deep_run=None):
    monkeypatch.setattr(orchestrator, 'RUNS_ROOT', str(tmp_path))
    monkeypatch.setattr(
        orchestrator.crash_rebound_gate,
        'read_latest_crash_rebound_gate',
        lambda: {},
    )
    monkeypatch.setattr(
        orchestrator.fear_index,
        'read_latest_fear_index',
        lambda: {},
    )
    monkeypatch.setattr(
        orchestrator.mcp_resource_catalog,
        'build_mcp_resource_snapshot',
        lambda **kwargs: {'status': 'ready', 'resources': []},
    )
    monkeypatch.setattr(
        orchestrator,
        'get_price_trend_metrics',
        lambda *args, **kwargs: trend or {
            'sample_days': 120,
            'trend_5d_pct': 8,
            'trend_20d_pct': 20,
            'over_ma20_pct': 12,
            'trend_score': 12,
            'drawdown_20d_pct': 4,
        },
    )
    monkeypatch.setattr(
        orchestrator.tradingagents,
        'reserve_compact_batch',
        lambda run_id, packets: ([{
            'packet': packet,
            'request_ids': {op: f'{run_id}:{packet["symbol"]}:{op}' for op in ('bulk_text', 'compact_debate', 'decisive_text')},
            'reservation_ids': {op: f'permit-{packet["symbol"]}-{op}' for op in ('bulk_text', 'compact_debate', 'decisive_text')},
            'reservation_owner_tokens': {op: f'owner-{packet["symbol"]}-{op}' for op in ('bulk_text', 'compact_debate', 'decisive_text')},
        } for packet in packets[:3]], [
            {
                'symbol': packet['symbol'],
                'status': 'admitted' if index < 3 else 'deferred',
                'reason': None if index < 3 else 'hard_cap',
                'permits': {},
            }
            for index, packet in enumerate(packets)
        ]),
    )
    monkeypatch.setattr(
        orchestrator.tradingagents,
        'run_deep_analysis',
        lambda *args, **kwargs: deep_run or {
            'id': 'ta_contract',
            'verdict': {
                'verdict': 'BUY',
                'confidence': 80,
                'reasoning': 'verified',
            },
        },
    )


def test_unverified_source_and_nonpositive_price_cannot_reach_agents(
    monkeypatch,
    tmp_path,
):
    _stub_context(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(
        orchestrator.tradingagents,
        'run_deep_analysis',
        lambda *args, **kwargs: calls.append(args) or {},
    )
    unverified = _candidate('111111', 'Unverified')
    unverified['source'] = 'manual'
    missing_price = _candidate('222222', 'No price')
    missing_price['price'] = 0

    result = orchestrator.run_multi_mcp_analysis(
        [unverified, missing_price],
        use_llm=True,
    )

    assert result['status'] == 'cash_wait'
    assert result['profit_gate_passed_count'] == 0
    assert calls == []


def test_duplicate_symbol_cannot_fill_partial_or_top3_portfolio(
    monkeypatch,
    tmp_path,
):
    _stub_context(monkeypatch, tmp_path)

    result = orchestrator.run_multi_mcp_analysis(
        [
            _candidate('123456', 'Same stock'),
            _candidate('123456', 'Same stock alias'),
            _candidate('123456', 'Same stock duplicate'),
        ],
        use_llm=True,
    )

    assert result['candidate_count'] == 1
    assert result['status'] == 'selective_portfolio'
    assert [row['symbol'] for row in result['selected']] == ['123456']


def test_llm_cannot_approve_with_out_of_contract_confidence(
    monkeypatch,
    tmp_path,
):
    _stub_context(
        monkeypatch,
        tmp_path,
        deep_run={
            'id': 'ta_numeric_injection',
            'verdict': {
                'verdict': 'BUY',
                'confidence': 1000,
                'reasoning': 'attempted numeric override',
            },
        },
    )

    result = orchestrator.run_multi_mcp_analysis([_candidate()], use_llm=True)

    assert result['status'] == 'selective_portfolio'
    assert [row['symbol'] for row in result['selected']] == ['005380']
    assert result['selected'][0]['selection_source'] == 'deterministic_kis_fallback'
    assert result['agent_analyses'][0]['approved'] is False


def test_stale_market_observation_is_blocked_before_agents(
    monkeypatch,
    tmp_path,
):
    _stub_context(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(
        orchestrator.tradingagents,
        'run_deep_analysis',
        lambda *args, **kwargs: calls.append(args) or {},
    )
    stale = _candidate()
    stale['observed_at'] = (
        datetime.now(timezone.utc) - timedelta(hours=3)
    ).isoformat()

    result = orchestrator.run_multi_mcp_analysis([stale], use_llm=True)

    assert result['status'] == 'cash_wait'
    assert result['profit_gate_passed_count'] == 0
    assert calls == []


def test_evidence_packet_retains_stable_underlying_source_cutoff():
    candidate = orchestrator._normalize_candidate(_candidate())
    first = orchestrator._evidence_packet(candidate, use_llm=True)
    second = orchestrator._evidence_packet(candidate, use_llm=True)
    assert first['as_of'] == candidate['observed_at']
    assert first['fingerprint'] == second['fingerprint']


def test_candidate_source_cutoff_uses_instant_not_timestamp_text_order():
    raw = _candidate()
    raw.pop('source_cutoff', None)
    raw['source_packets'] = [
        {**raw['source_packets'][0], 'fetched_at': '2026-09-03T10:00:00+09:00'},
        {**raw['source_packets'][0], 'evidence_id': 'later',
         'fetched_at': '2026-09-03T03:00:00+00:00'},
    ]
    candidate = orchestrator._normalize_candidate(raw)
    assert candidate['source_cutoff'] == '2026-09-03T03:00:00+00:00'


def test_live_market_scan_uses_kis_candidate_pool(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        'app.services.kis_screener.run_screening',
        lambda force=True: {
            'timestamp': '2026-07-29T15:00:00+09:00',
            'market_status': 'open',
            'quote_mode': 'paper',
            'source_counts': {'fluctuation': 30},
            'candidate_pool': [_candidate('123456', '검증종목')],
        },
    )
    monkeypatch.setattr(
        orchestrator,
        'run_multi_mcp_analysis',
        lambda candidates, **kwargs: captured.setdefault(
            'result',
            {'id': 'multi_live', 'status': 'cash_wait', 'candidate_count': len(candidates)},
        ),
    )

    result = orchestrator.run_live_market_scan(use_llm=False)

    assert captured['result']['candidate_count'] == 1
    assert result['scanner']['market_status'] == 'open'
    assert result['scanner']['source_counts']['fluctuation'] == 30


def test_preflight_limits_work_before_futures_to_three_complete_candidates(monkeypatch, tmp_path):
    _stub_context(monkeypatch, tmp_path)
    calls = []

    def fake(target, **kwargs):
        calls.append((target, kwargs))
        return {'id': target, 'analysis_status': 'SUCCESS_PRIMARY',
                'verdict': {'verdict': 'HOLD', 'confidence': 50}}

    monkeypatch.setattr(orchestrator.tradingagents, 'run_deep_analysis', fake)
    candidates = [_candidate(f'{index:06d}', f'종목{index}') for index in range(10)]
    result = orchestrator.run_multi_mcp_analysis(candidates, max_candidates=5)
    assert len(calls) == 3
    assert result['budget_summary']['admitted'] == 3
    assert result['budget_summary']['deferred'] == 7
    assert all(call[1]['profile'] == 'compact' for call in calls)
    assert len({call[1]['routing_run_id'] for call in calls}) == 1
    assert all(call[1]['reservation_ids']['decisive_text'] for call in calls)


def test_three_verified_kis_candidates_always_emit_deterministic_top3_when_ai_holds(
    monkeypatch,
    tmp_path,
):
    _stub_context(
        monkeypatch,
        tmp_path,
        deep_run={
            'id': 'ta-hold',
            'analysis_status': 'SUCCESS_PRIMARY',
            'verdict': {'verdict': 'HOLD', 'confidence': 55, 'reasoning': 'wait'},
        },
    )
    candidates = [
        _candidate('300003', '셋'),
        _candidate('100001', '하나'),
        _candidate('200002', '둘'),
    ]

    result = orchestrator.run_multi_mcp_analysis(candidates, max_candidates=5)

    assert result['status'] == 'portfolio_ready'
    assert [row['symbol'] for row in result['selected']] == [
        '100001', '200002', '300003',
    ]
    assert all(
        row['selection_source'] == 'deterministic_kis_fallback'
        for row in result['selected']
    )
    assert result['selection_mode'] == 'deterministic_only'
    assert result['ai_selected_count'] == 0
    assert result['deterministic_fallback_count'] == 3
    assert result['top3_shortfall'] == 0
    assert result['data_shortage_reason'] is None
    assert result['input_mode'] == 'authenticated_debug'
    assert result['publishable_top3'] is False


def test_ai_approved_rows_are_ranked_first_then_kis_fallback_fills_top3(
    monkeypatch,
    tmp_path,
):
    _stub_context(monkeypatch, tmp_path)

    def fake(_target, **kwargs):
        symbol = kwargs['symbol']
        return {
            'id': f'ta-{symbol}',
            'analysis_status': 'SUCCESS_PRIMARY',
            'verdict': {
                'verdict': 'BUY' if symbol == '300003' else 'HOLD',
                'confidence': 90 if symbol == '300003' else 40,
                'reasoning': 'verified',
            },
        }

    monkeypatch.setattr(orchestrator.tradingagents, 'run_deep_analysis', fake)
    result = orchestrator.run_multi_mcp_analysis([
        _candidate('200002', '둘'),
        _candidate('300003', '셋'),
        _candidate('100001', '하나'),
    ])

    assert [row['symbol'] for row in result['selected']] == [
        '300003', '100001', '200002',
    ]
    assert [row['selection_source'] for row in result['selected']] == [
        'ai_verified',
        'deterministic_kis_fallback',
        'deterministic_kis_fallback',
    ]
    assert result['selection_mode'] == 'ai_plus_deterministic'
    assert result['ai_selected_count'] == 1
    assert result['deterministic_fallback_count'] == 2
    assert set(row['symbol'] for row in result['selected']) <= {
        '100001', '200002', '300003',
    }


def test_deterministic_fallback_prefers_complete_scanner_eligible_rows(
    monkeypatch,
    tmp_path,
):
    _stub_context(
        monkeypatch,
        tmp_path,
        deep_run={
            'id': 'ta-hold',
            'analysis_status': 'SUCCESS_PRIMARY',
            'verdict': {'verdict': 'HOLD', 'confidence': 40},
        },
    )
    incomplete = {
        **_candidate('900009', '불완전'),
        'score': {'total': 99},
        'score_complete': False,
        'eligible': False,
        'rejection_reason': 'missing_required_inputs',
    }
    complete = [
        {
            **_candidate(symbol, name),
            'score': {'total': score},
            'score_complete': True,
            'eligible': True,
        }
        for symbol, name, score in (
            ('100001', '하나', 70),
            ('200002', '둘', 60),
            ('300003', '셋', 50),
        )
    ]

    result = orchestrator.run_multi_mcp_analysis([incomplete, *complete])

    assert [row['symbol'] for row in result['selected']] == [
        '100001', '200002', '300003',
    ]
    assert all(row['data_quality_status'] == 'verified_complete' for row in result['selected'])


def test_hold_review_can_never_pass_critic():
    packet = {'symbol': '005930', 'name': '삼성전자', 'trend': {'trend_score': 15}}
    reviewed = orchestrator._critic_review(packet, {
        'id': 'ta_x', 'analysis_status': 'HOLD_REVIEW',
        'verdict': {'verdict': 'BUY', 'confidence': 99},
    })
    assert reviewed['approved'] is False


def test_multi_mcp_renews_all_queued_compact_permits(monkeypatch, tmp_path):
    _stub_context(monkeypatch, tmp_path)
    renewals = []
    abort_events = []
    renewal_started = threading.Event()

    def renew(permits, owners):
        renewals.append((dict(permits), dict(owners)))
        renewal_started.set()
        return True

    def analyze(target, **kwargs):
        abort_events.append(kwargs.get('permit_abort_event'))
        if not renewal_started.wait(timeout=2):
            raise TimeoutError('permit renewal did not start')
        return {
            'id': target,
            'analysis_status': 'SUCCESS_PRIMARY',
            'verdict': {'verdict': 'HOLD', 'confidence': 50},
        }

    monkeypatch.setattr(
        orchestrator.tradingagents,
        'compact_permit_heartbeat_seconds',
        lambda: 0.001,
    )
    monkeypatch.setattr(
        orchestrator.tradingagents,
        'renew_compact_permits',
        renew,
    )
    monkeypatch.setattr(orchestrator.tradingagents, 'run_deep_analysis', analyze)

    orchestrator.run_multi_mcp_analysis(
        [_candidate(f'{index:06d}', f'종목{index}') for index in range(1, 4)],
        max_parallel=1,
    )

    assert renewals
    assert any(len(permits) == 9 for permits, _owners in renewals)
    assert all(event is abort_events[0] for event in abort_events)
    assert isinstance(abort_events[0], threading.Event)


def test_executor_constructor_failure_releases_every_preflight_permit(
    monkeypatch,
    tmp_path,
):
    _stub_context(monkeypatch, tmp_path)
    released = []
    monkeypatch.setattr(
        orchestrator.tradingagents,
        'release_compact_permits',
        lambda permits, owners: released.extend((permits or {}).values()),
    )
    monkeypatch.setattr(
        orchestrator,
        'ThreadPoolExecutor',
        lambda **kwargs: (_ for _ in ()).throw(OSError('executor unavailable')),
    )

    with pytest.raises(OSError, match='executor unavailable'):
        orchestrator.run_multi_mcp_analysis([
            _candidate(f'{index:06d}', f'종목{index}')
            for index in range(1, 4)
        ])

    assert set(released) == {
        f'permit-{index:06d}-{operation}'
        for index in range(1, 4)
        for operation in ('bulk_text', 'compact_debate', 'decisive_text')
    }


def test_partial_future_submission_failure_releases_unsubmitted_permits(
    monkeypatch,
    tmp_path,
):
    _stub_context(monkeypatch, tmp_path)
    released = []
    monkeypatch.setattr(
        orchestrator.tradingagents,
        'release_compact_permits',
        lambda permits, owners: released.extend((permits or {}).values()),
    )

    class PartialExecutor:
        def __init__(self, **kwargs):
            self.submissions = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def shutdown(self, **kwargs):
            return None

        def submit(self, fn, *args, **kwargs):
            self.submissions += 1
            if self.submissions == 2:
                raise OSError('submit unavailable')
            future = Future()
            future.set_result({
                'id': 'first',
                'analysis_status': 'SUCCESS_PRIMARY',
                'verdict': {'verdict': 'HOLD', 'confidence': 50},
            })
            return future

    monkeypatch.setattr(orchestrator, 'ThreadPoolExecutor', PartialExecutor)

    with pytest.raises(OSError, match='submit unavailable'):
        orchestrator.run_multi_mcp_analysis([
            _candidate(f'{index:06d}', f'종목{index}')
            for index in range(1, 4)
        ])

    assert set(released) == {
        f'permit-{index:06d}-{operation}'
        for index in range(1, 4)
        for operation in ('bulk_text', 'compact_debate', 'decisive_text')
    }

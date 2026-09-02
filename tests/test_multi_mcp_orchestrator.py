from datetime import datetime, timedelta, timezone

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
    assert manifest['hard_rules']['forced_top3'] is False


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

    assert result['status'] == 'cash_wait'
    assert result['profit_gate_passed_count'] == 1
    assert result['selected'] == []
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
        } for packet in packets], []),
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

    assert result['status'] == 'cash_wait'
    assert result['selected'] == []
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


def test_preflight_limits_work_before_futures_to_five(monkeypatch, tmp_path):
    _stub_context(monkeypatch, tmp_path)
    calls = []

    def fake(target, **kwargs):
        calls.append((target, kwargs))
        return {'id': target, 'analysis_status': 'SUCCESS_PRIMARY',
                'verdict': {'verdict': 'HOLD', 'confidence': 50}}

    monkeypatch.setattr(orchestrator.tradingagents, 'run_deep_analysis', fake)
    candidates = [_candidate(f'{index:06d}', f'종목{index}') for index in range(10)]
    result = orchestrator.run_multi_mcp_analysis(candidates, max_candidates=5)
    assert len(calls) == 5
    assert result['budget_summary']['admitted'] == 5
    assert result['budget_summary']['deferred'] == 5
    assert all(call[1]['profile'] == 'compact' for call in calls)
    assert len({call[1]['routing_run_id'] for call in calls}) == 1
    assert all(call[1]['reservation_ids']['decisive_text'] for call in calls)


def test_hold_review_can_never_pass_critic():
    packet = {'symbol': '005930', 'name': '삼성전자', 'trend': {'trend_score': 15}}
    reviewed = orchestrator._critic_review(packet, {
        'id': 'ta_x', 'analysis_status': 'HOLD_REVIEW',
        'verdict': {'verdict': 'BUY', 'confidence': 99},
    })
    assert reviewed['approved'] is False

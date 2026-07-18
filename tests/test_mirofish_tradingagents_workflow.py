"""Task 6 — TradingAgents deep-verification layer intervention in TOP3 selection.

Covers `_apply_tradingagents_layer`: SELL exclusion, STRONG_BUY boost (+매수유력),
BUY confidence-weighted boost, HOLD penalty, kill-switch no-op, and engine-failure
fallback. Plus `_select_top3` excluded-item drop and the telegram badge line.
"""

from __future__ import annotations

from app.services.mirofish import workflow


def _ranked():
    return [
        {'candidate': {'symbol': f'00{i}', 'display_name': f'종목{i}'}, 'run_id': f'r{i}',
         'final_score': 90 - i * 10, 'verdict': {'action': 'BUY'}} for i in range(4)  # 90,80,70,60
    ]


def _fake_engine(verdict_map):
    def fake(target, **kw):
        v = verdict_map.get(target, ('HOLD', 50))
        return {'id': f'ta_{target}', 'method': 'rule',
                'verdict': {'verdict': v[0], 'confidence': v[1], 'strong_buy': v[0] == 'STRONG_BUY',
                            'bull_case': 'b', 'bear_case': 'r', 'risk_summary': 's', 'reasoning': 'x'}}
    return fake


def test_sell_excluded_and_replaced(monkeypatch):
    monkeypatch.delenv('MIROFISH_TRADINGAGENTS_DISABLED', raising=False)
    monkeypatch.setattr(workflow.ta_engine, 'run_deep_analysis',
                        _fake_engine({'종목0': ('SELL', 80), '종목1': ('BUY', 80),
                                      '종목2': ('STRONG_BUY', 85), '종목3': ('HOLD', 50)}))
    adjusted, summary = workflow._apply_tradingagents_layer(_ranked(), top_n=3, require_buy=True)
    top = adjusted[:3]
    symbols = [t['candidate']['symbol'] for t in top]
    assert '000' not in symbols                                   # SELL excluded
    # math: 001 BUY → 80 + 5*0.8 = 84.0 ; 002 STRONG_BUY → 70+8 = 78.0 ; 003 HOLD → 60-3 = 57.0
    assert top[0]['candidate']['symbol'] == '001' and top[0]['ta_adjusted_score'] == 84.0
    assert top[1]['candidate']['symbol'] == '002' and top[1]['tradingagents']['strong_buy'] is True
    assert top[2]['candidate']['symbol'] == '003'
    assert summary['excluded'] == ['000'] and summary['analyzed'] == 4


def test_kill_switch_no_change(monkeypatch):
    monkeypatch.setenv('MIROFISH_TRADINGAGENTS_DISABLED', 'true')
    ranked = _ranked()
    adjusted, summary = workflow._apply_tradingagents_layer(ranked, top_n=3, require_buy=True)
    assert adjusted == ranked and summary['status'] == 'disabled'


def test_engine_failure_falls_back(monkeypatch):
    monkeypatch.delenv('MIROFISH_TRADINGAGENTS_DISABLED', raising=False)

    def boom(target, **kw):
        raise RuntimeError('llm down')

    monkeypatch.setattr(workflow.ta_engine, 'run_deep_analysis', boom)
    adjusted, summary = workflow._apply_tradingagents_layer(_ranked(), top_n=3, require_buy=True)
    assert [r['final_score'] for r in adjusted[:3]] == [90, 80, 70]  # no adjustment
    assert summary['analyzed'] == 0


def test_mature_learning_policy_weights_verdict_and_caps_stale_confidence(monkeypatch):
    monkeypatch.delenv('MIROFISH_TRADINGAGENTS_DISABLED', raising=False)
    monkeypatch.setattr(workflow, '_load_ta_learning_policy', lambda: {
        'status': 'applied', 'applied': True, 'sample_count': 40, 'min_samples': 20,
        'lookahead_safe': True, 'confidence_cap': 75,
        'verdict_weights': {'BUY': 1.2},
    })
    ranked = _ranked()[:1]
    ranked[0]['candidate']['source_freshness'] = {'price': {'status': 'stale'}}
    target = ranked[0]['candidate']['display_name']
    monkeypatch.setattr(workflow.ta_engine, 'run_deep_analysis',
                        _fake_engine({target: ('BUY', 90)}))

    adjusted, summary = workflow._apply_tradingagents_layer(ranked, top_n=1, require_buy=True)

    # stale evidence caps confidence at 60: 90 + (5 * .60 * 1.2)
    assert adjusted[0]['ta_adjusted_score'] == 93.6
    assert adjusted[0]['tradingagents']['raw_confidence'] == 90
    assert adjusted[0]['tradingagents']['confidence'] == 60
    assert 'stale_source' in adjusted[0]['tradingagents']['confidence_cap_reasons']
    assert summary['learning_policy']['applied'] is True


def test_immature_learning_policy_is_observe_only(monkeypatch):
    monkeypatch.setattr(workflow, '_load_ta_learning_policy', lambda: {
        'status': 'observe_only', 'applied': False, 'sample_count': 3, 'min_samples': 20,
        'verdict_weights': {'BUY': 1.5}, 'confidence_cap': 40,
    })
    ranked = _ranked()[:1]
    target = ranked[0]['candidate']['display_name']
    monkeypatch.setattr(workflow.ta_engine, 'run_deep_analysis',
                        _fake_engine({target: ('BUY', 80)}))
    adjusted, _ = workflow._apply_tradingagents_layer(ranked, top_n=1, require_buy=True)
    assert adjusted[0]['ta_adjusted_score'] == 94.0
    assert adjusted[0]['tradingagents']['confidence'] == 80


def test_ranking_snapshot_records_score_movement_and_exclusion_reason():
    items = _ranked()[:2]
    items[1]['ta_adjusted_score'] = 95
    items[0]['ta_excluded'] = True
    items[0]['ta_exclusion_reason'] = 'TradingAgents SELL verdict'
    snapshot = workflow._ranking_snapshot([items[1], items[0]], before={'000': 1, '001': 2})
    assert snapshot[0]['symbol'] == '001'
    assert snapshot[0]['base_score'] == 80
    assert snapshot[0]['adjusted_score'] == 95
    assert snapshot[0]['rank_movement'] == 1
    assert snapshot[1]['excluded'] is True
    assert snapshot[1]['exclusion_reason'] == 'TradingAgents SELL verdict'


def test_learning_aggregate_converts_only_mature_verdicts_to_bounded_policy():
    policy = workflow._ta_policy_from_aggregate({
        'lookahead_safe_only': True,
        'evaluated_sample_count': 12,
        'minimum_samples_for_adjustment': 5,
        'verdict_accuracy': {
            'BUY': {'sample_count': 8, 'hit_rate_pct': 70},
            'SELL': {'sample_count': 2, 'hit_rate_pct': 100},
        },
        'lessons': [{'scope': 'verdict', 'key': 'BUY',
                     'suggested_confidence_cap_delta': -5}],
    })
    assert policy['verdict_weights'] == {'BUY': 1.1}
    assert policy['confidence_cap'] == 95
    assert policy['sample_count'] == 12


def test_select_top3_never_returns_ta_excluded_item():
    ranked = [
        {'candidate': {'symbol': '000'}, 'verdict': {'action': 'BUY'}, 'final_score': 95, 'ta_excluded': True},
        {'candidate': {'symbol': '001'}, 'verdict': {'action': 'BUY'}, 'final_score': 80},
        {'candidate': {'symbol': '002'}, 'verdict': {'action': 'BUY'}, 'final_score': 70},
    ]
    # require_buy True
    top = workflow._select_top3(ranked, top_n=3, require_buy=True)
    assert all(not item.get('ta_excluded') for item in top)
    assert [item['candidate']['symbol'] for item in top] == ['001', '002']
    # require_buy False — still must drop excluded
    top_all = workflow._select_top3(ranked, top_n=3, require_buy=False)
    assert all(not item.get('ta_excluded') for item in top_all)
    assert [item['candidate']['symbol'] for item in top_all] == ['001', '002']


def test_telegram_message_includes_tradingagents_line_and_badge():
    candidate = {
        'symbol': '000001',
        'display_name': 'Alpha One',
        'name': 'Alpha One',
        'market': 'KOSPI',
        'alpha_score': 80,
        'risk_score': 20,
        'analysis_profile': {},
        'price': {'date': '2026-05-07', 'current_price': 1000, 'currency': 'KRW'},
    }
    message = workflow.build_workflow_top3_telegram_message({
        'id': 'mcp_test123',
        'scanner_run_id': 'mfas_test',
        'scanner_freshness': {'status': 'fresh'},
        'event_count': 1,
        'completed_at': '2026-05-07T12:00:00+00:00',
        'analysis_runs': [{'symbol': '000001'}],
        'summary': {'top_count': 1},
        'top3': [{
            'candidate': candidate,
            'target': 'Alpha One',
            'symbol': '000001',
            'market': 'KOSPI',
            'final_score': 88.5,
            'verdict': {'action': 'BUY', 'confidence_pct': 75},
            'graph': {'links': 42},
            'brain': {'score': 63, 'regime': 'neutral'},
            'tradingagents': {'verdict': 'STRONG_BUY', 'confidence': 85, 'strong_buy': True},
        }],
    })

    assert 'TradingAgents: STRONG_BUY 85%' in message
    assert '매수유력' in message


def test_telegram_message_no_badge_for_non_strong_buy():
    candidate = {
        'symbol': '000001',
        'display_name': 'Alpha One',
        'name': 'Alpha One',
        'market': 'KOSPI',
        'alpha_score': 80,
        'risk_score': 20,
        'analysis_profile': {},
        'price': {'date': '2026-05-07', 'current_price': 1000, 'currency': 'KRW'},
    }
    message = workflow.build_workflow_top3_telegram_message({
        'id': 'mcp_test123',
        'scanner_run_id': 'mfas_test',
        'scanner_freshness': {'status': 'fresh'},
        'event_count': 1,
        'completed_at': '2026-05-07T12:00:00+00:00',
        'analysis_runs': [{'symbol': '000001'}],
        'summary': {'top_count': 1},
        'top3': [{
            'candidate': candidate,
            'target': 'Alpha One',
            'symbol': '000001',
            'market': 'KOSPI',
            'final_score': 88.5,
            'verdict': {'action': 'BUY', 'confidence_pct': 75},
            'graph': {'links': 42},
            'brain': {'score': 63, 'regime': 'neutral'},
            'tradingagents': {'verdict': 'BUY', 'confidence': 72, 'strong_buy': False},
        }],
    })

    assert 'TradingAgents: BUY 72%' in message
    assert '매수유력' not in message


def test_build_share_payload_surfaces_tradingagents():
    """공유 payload 의 top_item 이 tradingagents 판정을 노출해야 대시보드 배지가 가능."""
    payload = workflow.build_share_payload({
        'id': 'mcp_share1',
        'completed_at': '2026-07-17T12:00:00+00:00',
        'top3': [{
            'candidate': {'symbol': '005930', 'display_name': '삼성전자'},
            'target': '삼성전자', 'symbol': '005930', 'market': 'KOSPI',
            'final_score': 92.0,
            'verdict': {'action': 'BUY', 'confidence_pct': 80},
            'tradingagents': {'verdict': 'STRONG_BUY', 'confidence': 85.0, 'strong_buy': True,
                              'bull_case': 'b', 'bear_case': 'r'},
        }],
    })
    ta = payload['top_items'][0]['tradingagents']
    assert ta == {'verdict': 'STRONG_BUY', 'confidence': 85.0, 'strong_buy': True}


def test_build_share_payload_tradingagents_absent_is_none():
    payload = workflow.build_share_payload({
        'id': 'mcp_share2',
        'completed_at': '2026-07-17T12:00:00+00:00',
        'top3': [{
            'candidate': {'symbol': '000660', 'display_name': 'SK하이닉스'},
            'target': 'SK하이닉스', 'symbol': '000660', 'market': 'KOSPI',
            'final_score': 70.0,
            'verdict': {'action': 'BUY', 'confidence_pct': 60},
        }],
    })
    assert payload['top_items'][0]['tradingagents'] is None

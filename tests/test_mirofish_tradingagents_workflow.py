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

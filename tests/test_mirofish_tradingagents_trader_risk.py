"""Unit tests for the trader + risk team + PM decision layer.

Pins the deterministic PM verdict bands (driven by debate['_analyst_mean']),
the fixed 3-role risk debate order, and the negative-keyword veto path.
"""

from app.services.mirofish.tradingagents import trader_risk

BUNDLE = {'target': '삼성전자', 'price': {'found': True, 'price': 70000, 'change_pct': 4.0},
          'technical': {'trend': 'up'}, 'rs': {'rs_rating': 90}, 'corpus': '수주', 'errors': {}}


def _debate(mean_hint):
    return {'manager': {'stance': 'bull' if mean_hint > 0 else 'bear',
                        'thesis': 't', 'confidence': 80},
            'bull_case': 'b', 'bear_case': 'r',
            '_analyst_mean': mean_hint}


def test_pm_strong_buy_thresholds():
    out = trader_risk.run_trader_and_risk('삼성전자', BUNDLE, _debate(40), use_llm=False)
    pm = out['pm_decision']
    assert pm['verdict'] == 'STRONG_BUY' and pm['strong_buy'] and pm['confidence'] >= 75
    assert len(out['risk_debate']) == 3
    assert out['method'] == 'rule'


def test_pm_sell_and_hold():
    assert trader_risk.run_trader_and_risk('t', BUNDLE, _debate(-30), use_llm=False)['pm_decision']['verdict'] == 'SELL'
    assert trader_risk.run_trader_and_risk('t', BUNDLE, _debate(5), use_llm=False)['pm_decision']['verdict'] == 'HOLD'


def test_pm_buy_band():
    out = trader_risk.run_trader_and_risk('t', BUNDLE, _debate(20), use_llm=False)
    pm = out['pm_decision']
    assert pm['verdict'] == 'BUY' and pm['strong_buy'] is False


def test_risk_debate_role_order():
    out = trader_risk.run_trader_and_risk('t', BUNDLE, _debate(40), use_llm=False)
    assert [r['role'] for r in out['risk_debate']] == ['risky', 'safe', 'neutral']
    for r in out['risk_debate']:
        assert r['vote'] in ('approve', 'reject', 'neutral')
        assert r['message']


def test_risk_votes_positive_mean():
    out = trader_risk.run_trader_and_risk('t', BUNDLE, _debate(40), use_llm=False)
    votes = {r['role']: r['vote'] for r in out['risk_debate']}
    # mean>0 → risky approves; clean corpus + mean>0 → safe neutral; neutral neutral
    assert votes['risky'] == 'approve'
    assert votes['safe'] == 'neutral'
    assert votes['neutral'] == 'neutral'


def test_risk_safe_vetoes_on_negative_keyword():
    bad = dict(BUNDLE, corpus='대규모 소송 제기 및 유상증자')
    out = trader_risk.run_trader_and_risk('t', bad, _debate(40), use_llm=False)
    votes = {r['role']: r['vote'] for r in out['risk_debate']}
    assert votes['safe'] == 'reject'


def test_trader_plan_shape():
    out = trader_risk.run_trader_and_risk('t', BUNDLE, _debate(40), use_llm=False)
    plan = out['trader_plan']
    assert set(plan) >= {'action_hint', 'entry_note', 'risk_note'}
    assert all(isinstance(plan[k], str) and plan[k] for k in ('action_hint', 'entry_note', 'risk_note'))


def test_strong_buy_confidence_floor():
    # manager confidence below 75 → STRONG_BUY still floors at 75
    debate = _debate(40)
    debate['manager']['confidence'] = 60
    out = trader_risk.run_trader_and_risk('t', BUNDLE, debate, use_llm=False)
    assert out['pm_decision']['confidence'] == 75

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


def _fake_by_system(mapping, default=None):
    """Build a generate_text stub that dispatches on the `system` kwarg."""
    def fake(prompt, **kwargs):
        system = kwargs.get('system') or ''
        for token, response in mapping.items():
            if token in system:
                return response
        return default
    return fake


def test_llm_pm_invalid_verdict_fails_closed_with_rule_diagnostic(monkeypatch):
    # Trader + risk succeed via LLM; PM returns an out-of-set verdict → the PM
    # piece must not publish the rule STRONG_BUY after decisive validation fails.
    fake = _fake_by_system({
        '트레이더': '{"action_hint": "매수", "entry_note": "분할 진입", "risk_note": "손절"}',
        '포트폴리오 매니저': '{"verdict": "MODERATE_BUY", "confidence": 80, "reasoning": "x"}',
        '리스크 애널리스트': '{"message": "리스크 판단", "vote": "approve"}',
    })
    monkeypatch.setattr(
        trader_risk.llm_client, 'generate_text_with_metadata',
        lambda *args, **kwargs: (fake(*args, **kwargs), {
            'provider': 'openai', 'model': 'test', 'success': True,
            'fallback_used': False, 'attempts': [], 'latency_ms': 1,
        }),
    )
    out = trader_risk.run_trader_and_risk('삼성전자', BUNDLE, _debate(40), use_llm=True)
    assert out['pm_decision']['verdict'] == 'HOLD_REVIEW'
    assert out['pm_decision']['strong_buy'] is False
    assert out['analysis_status'] == 'HOLD_REVIEW'
    assert out['rule_candidate_verdict']['verdict'] == 'STRONG_BUY'
    assert out['method'] == 'mixed'  # trader+risk LLM ok, PM fell back
    assert out['trader_plan']['llm']['provider'] == 'openai'
    assert all(entry['llm']['provider'] == 'openai' for entry in out['risk_debate'])
    assert out['pm_decision']['llm']['success'] is True
    # trader plan came from the LLM stub
    assert out['trader_plan']['action_hint'] == '매수'


def test_pm_requests_decisive_operation_cap_and_identity(monkeypatch):
    calls = []

    def fake(prompt, **kwargs):
        calls.append(kwargs)
        system = kwargs.get('system') or ''
        if '포트폴리오 매니저' in system:
            return ('{"symbol":"005930","name":"삼성전자","market":"KOSPI",'
                    '"analyst_mean":40,"verdict":"BUY","confidence":80,"reasoning":"ok"}',
                    {'success': True, 'analysis_status': 'SUCCESS_PRIMARY', 'provider': 'deepseek'})
        if '트레이더' in system:
            return ('{"action_hint":"매수","entry_note":"분할","risk_note":"손절"}', {'success': True})
        return ('{"message":"검토","vote":"approve"}', {'success': True})

    monkeypatch.setattr(trader_risk.llm_client, 'generate_text_with_metadata', fake)
    bundle = {**BUNDLE, 'symbol': '005930', 'market': 'KOSPI', 'display_name': '삼성전자'}
    out = trader_risk.run_trader_and_risk(
        '삼성전자', bundle, _debate(40), use_llm=True, run_id='wf_1',
    )

    pm_call = next(call for call in calls if call.get('operation') == 'decisive_text')
    assert pm_call['max_tokens'] == 1200
    assert pm_call['run_id'] == 'wf_1'
    assert pm_call['symbol'] == '005930' and pm_call['market'] == 'KOSPI'
    assert out['analysis_status'] == 'SUCCESS_PRIMARY'


def test_strong_buy_confidence_floor():
    # manager confidence below 75 → STRONG_BUY still floors at 75
    debate = _debate(40)
    debate['manager']['confidence'] = 60
    out = trader_risk.run_trader_and_risk('t', BUNDLE, debate, use_llm=False)
    assert out['pm_decision']['confidence'] == 75


def test_regime_boost_lifts_rule_verdict_band():
    from app.services.mirofish.tradingagents import trader_risk
    out = trader_risk.run_trader_and_risk('삼성전자', {}, _debate(12),
                                          use_llm=False, regime_adjustment=5.0)
    assert out['pm_decision']['verdict'] == 'BUY'


def test_regime_penalty_lowers_rule_verdict_band():
    from app.services.mirofish.tradingagents import trader_risk
    out = trader_risk.run_trader_and_risk('삼성전자', {}, _debate(-12),
                                          use_llm=False, regime_adjustment=-5.0)
    assert out['pm_decision']['verdict'] == 'SELL'


def test_no_adjustment_matches_baseline():
    from app.services.mirofish.tradingagents import trader_risk
    out = trader_risk.run_trader_and_risk('삼성전자', {}, _debate(12), use_llm=False)
    assert out['pm_decision']['verdict'] == 'HOLD'

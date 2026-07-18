"""Unit tests for the deep-analysis engine (orchestration + persistence).

Runs the full rule pipeline end-to-end with a patched data source, verifies the
LOCKED run schema, persistence + retrieval, path-traversal rejection in get_run,
and the kill-switch status flag.
"""

import app.services.mirofish.tradingagents.engine as engine


def _patch_sources(monkeypatch, tmp_path):
    monkeypatch.setattr(engine, 'RUNS_ROOT', str(tmp_path))
    monkeypatch.setattr(engine.data_hub, 'gather_bundle', lambda t: {
        'target': t, 'symbol': '005930', 'market': 'KOSPI', 'display_name': t,
        'price': {'found': True, 'price': 70000, 'change_pct': 4.0, 'date': '2026-07-17'},
        'corpus': '수주 계약 신고가', 'technical': {'trend': 'up', 'ma_aligned': True},
        'rs': {'rs_rating': 90}, 'fundamentals': {}, 'errors': {}})


def test_run_deep_analysis_rule_end_to_end(monkeypatch, tmp_path):
    monkeypatch.delenv('MIROFISH_TRADINGAGENTS_DISABLED', raising=False)
    _patch_sources(monkeypatch, tmp_path)
    run = engine.run_deep_analysis('삼성전자', use_llm=False)
    assert run['verdict']['verdict'] in ('STRONG_BUY', 'BUY', 'HOLD', 'SELL')
    assert run['method'] == 'rule' and run['id'].startswith('ta_')
    assert len(run['analyst_reports']) == 4
    assert engine.get_run(run['id'])['id'] == run['id']
    assert engine.list_runs(limit=5)[0]['id'] == run['id']
    st = engine.get_status()
    assert st['enabled'] is True and st['last_run_id'] == run['id']


def test_verdict_flat_merge_fields(monkeypatch, tmp_path):
    monkeypatch.delenv('MIROFISH_TRADINGAGENTS_DISABLED', raising=False)
    _patch_sources(monkeypatch, tmp_path)
    run = engine.run_deep_analysis('삼성전자', use_llm=False)
    v = run['verdict']
    assert {'verdict', 'confidence', 'strong_buy', 'reasoning',
            'bull_case', 'bear_case', 'risk_summary'} <= set(v)
    assert isinstance(v['risk_summary'], str) and v['risk_summary']
    # risk_summary references all three risk personas
    for role in ('risky', 'safe', 'neutral'):
        assert role in v['risk_summary']


def test_bundle_meta_shape(monkeypatch, tmp_path):
    monkeypatch.delenv('MIROFISH_TRADINGAGENTS_DISABLED', raising=False)
    _patch_sources(monkeypatch, tmp_path)
    run = engine.run_deep_analysis('삼성전자', use_llm=False)
    meta = run['bundle_meta']
    assert meta['has_price'] and meta['has_technical'] and meta['has_rs']
    assert meta['has_fundamentals'] is False
    assert meta['corpus_chars'] == len('수주 계약 신고가')
    assert isinstance(meta['errors'], dict)


def test_symbol_override_preserved(monkeypatch, tmp_path):
    monkeypatch.delenv('MIROFISH_TRADINGAGENTS_DISABLED', raising=False)
    monkeypatch.setattr(engine, 'RUNS_ROOT', str(tmp_path))
    monkeypatch.setattr(engine.data_hub, 'gather_bundle', lambda t: {
        'target': t, 'symbol': None, 'market': None, 'display_name': t,
        'price': {}, 'corpus': '', 'technical': {}, 'rs': {}, 'fundamentals': {}, 'errors': {}})
    run = engine.run_deep_analysis('미지종목', symbol='123456', use_llm=False)
    assert run['symbol'] == '123456'


def test_get_run_rejects_path_traversal(monkeypatch, tmp_path):
    _patch_sources(monkeypatch, tmp_path)
    assert engine.get_run('../etc') is None
    assert engine.get_run('ta_bad/../../x') is None
    assert engine.get_run('nonexistent_ta_20260717_000000_abcdef') is None


def test_rounds_env_clamp(monkeypatch, tmp_path):
    monkeypatch.delenv('MIROFISH_TRADINGAGENTS_DISABLED', raising=False)
    _patch_sources(monkeypatch, tmp_path)
    monkeypatch.setenv('MIROFISH_TA_DEBATE_ROUNDS', '99')
    run = engine.run_deep_analysis('삼성전자', use_llm=False)
    assert len(run['research_debate']['rounds']) == 4


def test_explicit_rounds_arg_overrides_env(monkeypatch, tmp_path):
    monkeypatch.delenv('MIROFISH_TRADINGAGENTS_DISABLED', raising=False)
    _patch_sources(monkeypatch, tmp_path)
    monkeypatch.setenv('MIROFISH_TA_DEBATE_ROUNDS', '4')
    run = engine.run_deep_analysis('삼성전자', rounds=1, use_llm=False)
    assert len(run['research_debate']['rounds']) == 1


def test_run_ids_unique_back_to_back(monkeypatch, tmp_path):
    monkeypatch.delenv('MIROFISH_TRADINGAGENTS_DISABLED', raising=False)
    _patch_sources(monkeypatch, tmp_path)
    r1 = engine.run_deep_analysis('삼성전자', use_llm=False)
    r2 = engine.run_deep_analysis('삼성전자', use_llm=False)
    assert r1['id'] != r2['id']
    # both survive on disk (neither overwrote the other) and round-trip via get_run
    assert engine._count_runs() == 2
    assert engine.get_run(r1['id'])['id'] == r1['id']
    assert engine.get_run(r2['id'])['id'] == r2['id']


def test_run_id_matches_regex(monkeypatch, tmp_path):
    monkeypatch.delenv('MIROFISH_TRADINGAGENTS_DISABLED', raising=False)
    _patch_sources(monkeypatch, tmp_path)
    run = engine.run_deep_analysis('삼성전자', use_llm=False)
    assert engine._RUN_ID_RE.match(run['id'])


def test_engine_aggregates_mixed_method(monkeypatch, tmp_path):
    """Analysts succeed via LLM; debate + trader_risk LLM all fail → rule.

    Aggregated run method must be 'mixed' ({'llm','rule'}). Patches the shared
    llm_client module so all three sub-layers see the same fake.
    """
    monkeypatch.delenv('MIROFISH_TRADINGAGENTS_DISABLED', raising=False)
    _patch_sources(monkeypatch, tmp_path)

    def fake_generate(prompt, **kwargs):
        system = kwargs.get('system') or ''
        # Fail every debate/trader/risk/PM piece; only analyst roles get JSON.
        if any(tok in system for tok in ('리서처', '리서치 매니저', '트레이더',
                                         '리스크 애널리스트', '포트폴리오 매니저')):
            return None
        return ('{"title": "t", "summary": "요약", "stance": "bullish", '
                '"score": 30, "evidence": ["e"]}')

    monkeypatch.setattr(
        'app.services.mirofish.llm_client.generate_text_with_metadata',
        lambda *args, **kwargs: (fake_generate(*args, **kwargs), {
            'provider': 'deepseek', 'model': 'test', 'success': True,
            'fallback_used': False, 'attempts': [], 'latency_ms': 1,
        }),
    )
    run = engine.run_deep_analysis('삼성전자', use_llm=True)
    assert all(r['method'] == 'llm' for r in run['analyst_reports'])
    assert run['research_debate']['method'] == 'rule'
    assert run['trader_risk']['method'] == 'rule'
    assert run['method'] == 'mixed'


def test_kill_switch_status(monkeypatch, tmp_path):
    _patch_sources(monkeypatch, tmp_path)
    monkeypatch.setenv('MIROFISH_TRADINGAGENTS_DISABLED', 'true')
    assert engine.get_status()['enabled'] is False


def test_provider_usage_summarizes_calls_fallbacks_and_providers():
    usage = engine._provider_usage([
        {'provider': 'deepseek', 'success': True, 'fallback_used': False,
         'attempts': [{'provider': 'deepseek', 'success': True}]},
        {'provider': 'openai', 'success': True, 'fallback_used': True,
         'attempts': [{'provider': 'deepseek', 'success': False},
                      {'provider': 'openai', 'success': True}]},
        {'provider': 'none', 'success': False, 'fallback_used': True,
         'attempts': [{'provider': 'deepseek', 'success': False},
                      {'provider': 'openai', 'success': False}]},
    ])
    assert usage == {
        'calls': 3, 'successes': 2, 'failures': 1, 'fallbacks': 2,
        'providers': {
            'deepseek': {'attempts': 3, 'successes': 1, 'failures': 2, 'selected': 1},
            'openai': {'attempts': 2, 'successes': 1, 'failures': 1, 'selected': 1},
        },
        'attempts': 5,
    }


def test_status_config_exposes_tuning(monkeypatch, tmp_path):
    _patch_sources(monkeypatch, tmp_path)
    monkeypatch.delenv('MIROFISH_TRADINGAGENTS_DISABLED', raising=False)
    cfg = engine.get_status()['config']
    assert set(cfg) == {'max_candidates', 'debate_rounds', 'boost_strong', 'boost_buy', 'penalty_hold'}
    assert cfg['max_candidates'] == 5 and cfg['boost_strong'] == 8.0

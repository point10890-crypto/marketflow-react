"""Unit tests for the deep-analysis engine (orchestration + persistence).

Runs the full rule pipeline end-to-end with a patched data source, verifies the
LOCKED run schema, persistence + retrieval, path-traversal rejection in get_run,
and the kill-switch status flag.
"""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import app.services.mirofish.tradingagents.engine as engine
from app.services.mirofish.tradingagents.run_cache import RunCache, execute_cached


def _patch_sources(monkeypatch, tmp_path):
    monkeypatch.setattr(engine, 'RUNS_ROOT', str(tmp_path))
    monkeypatch.setattr(engine.data_hub, 'gather_bundle', lambda t, **_: {
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
    monkeypatch.setattr(engine.data_hub, 'gather_bundle', lambda t, **_: {
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
    assert set(cfg) == {
        'max_candidates', 'debate_rounds', 'boost_strong', 'boost_buy',
        'penalty_hold', 'sell_exclude_min_confidence',
        'penalty_uncertain_sell',
    }
    assert cfg['max_candidates'] == 5 and cfg['boost_strong'] == 8.0
    assert cfg['sell_exclude_min_confidence'] == 65.0
    assert cfg['penalty_uncertain_sell'] == 5.0


def test_run_deep_analysis_threads_brain_and_regime(monkeypatch, tmp_path):
    from app.services.mirofish.tradingagents import engine
    monkeypatch.setattr(engine, 'RUNS_ROOT', str(tmp_path))
    brain = {'regime': 'constructive_bullish', 'alignment_score': 0.8}
    run = engine.run_deep_analysis('삼성전자', symbol='005930', use_llm=False, brain=brain)
    assert run['verdict']['regime'] == 'constructive_bullish'
    assert run['verdict']['regime_adjustment']['direction'] == 'bull'
    assert run['regime_context']['adjustment'] == 5.0


def test_run_deep_analysis_without_brain_is_neutral(monkeypatch, tmp_path):
    from app.services.mirofish.tradingagents import engine
    monkeypatch.setattr(engine, 'RUNS_ROOT', str(tmp_path))
    run = engine.run_deep_analysis('삼성전자', symbol='005930', use_llm=False)
    assert run['verdict']['regime'] == 'unknown'
    assert run['regime_context']['adjustment'] == 0.0


def test_compact_profile_makes_exactly_three_calls_with_fixed_caps(monkeypatch, tmp_path):
    _patch_sources(monkeypatch, tmp_path)
    calls = []

    def fake(prompt, **kwargs):
        calls.append(kwargs)
        operation = str(kwargs.get('operation'))
        if operation.endswith('bulk_text'):
            return '{"digest":"근거 요약","evidence_ids":["ev1"]}', {'success': True, 'analysis_status': 'SUCCESS_PRIMARY'}
        if operation.endswith('compact_debate'):
            return ('{"bull_case":"강세","bear_case":"약세",'
                    '"bull_evidence_ids":["ev1"],"bear_evidence_ids":["ev1"]}',
                    {'success': True, 'analysis_status': 'SUCCESS_PRIMARY'})
        return ('{"symbol":"005930","name":"삼성전자","market":"KOSPI",'
                '"analyst_mean":31.25,"verdict":"BUY","confidence":80,"reasoning":"결정"}',
                {'success': True, 'analysis_status': 'SUCCESS_PRIMARY', 'provider': 'deepseek'})

    monkeypatch.setattr(engine.llm_client, 'generate_text_with_metadata', fake)
    packet = {
        'symbol': '005930', 'name': '삼성전자', 'market': 'KOSPI',
        'as_of': '2026-07-17T06:30:00+00:00', 'fingerprint': 'f' * 64,
        'evidence_ids': ['ev1'], 'schema_version': '1', 'prompt_version': '1',
    }
    run = engine.run_deep_analysis(
        '삼성전자', symbol='005930', use_llm=True, profile='compact',
        evidence_packet=packet, run_id='ta_20260717_063000_000000_abcdef',
    )

    assert len(calls) == 3
    assert [call['max_tokens'] for call in calls] == [768, 768, 1200]
    assert [str(call['operation']) for call in calls] == ['bulk_text', 'compact_debate', 'decisive_text']
    assert len(run['analyst_reports']) == 4
    assert all(report['method'] == 'rule' for report in run['analyst_reports'])
    assert run['profile'] == 'compact' and run['id'] == 'ta_20260717_063000_000000_abcdef'


def test_default_profile_remains_full(monkeypatch, tmp_path):
    _patch_sources(monkeypatch, tmp_path)
    run = engine.run_deep_analysis('삼성전자', use_llm=False)
    assert run['profile'] == 'full'


def test_compact_cache_reuses_completed_artifact_and_force_bypasses(monkeypatch, tmp_path):
    _patch_sources(monkeypatch, tmp_path)
    packet = {
        'symbol': '005930', 'name': '삼성전자', 'market': 'KOSPI',
        'as_of': '2026-07-17T06:30:00+00:00', 'fingerprint': 'a' * 64,
        'evidence_ids': [], 'schema_version': '1', 'prompt_version': '1',
        'profile': 'compact', 'models': {'deepseek': 'pro'},
    }
    calls = []

    def fake(prompt, **kwargs):
        calls.append(kwargs['operation'])
        if kwargs['operation'] == 'bulk_text':
            return '{"digest":"d","evidence_ids":[]}', {'success': True, 'analysis_status': 'SUCCESS_PRIMARY'}
        if kwargs['operation'] == 'compact_debate':
            return '{"bull_case":"b","bear_case":"r","bull_evidence_ids":[],"bear_evidence_ids":[]}', {'success': True, 'analysis_status': 'SUCCESS_PRIMARY'}
        return '{"symbol":"005930","name":"삼성전자","market":"KOSPI","analyst_mean":31.25,"verdict":"BUY","confidence":80,"reasoning":"ok"}', {'success': True, 'analysis_status': 'SUCCESS_PRIMARY'}

    monkeypatch.setattr(engine.llm_client, 'generate_text_with_metadata', fake)
    first = engine.run_deep_analysis('삼성전자', profile='compact', evidence_packet=packet)
    second = engine.run_deep_analysis('삼성전자', profile='compact', evidence_packet=packet)
    third = engine.run_deep_analysis('삼성전자', profile='compact', evidence_packet=packet, force=True)
    assert second['id'] == first['id'] and second['cache_hit'] is True
    assert third['id'] != first['id']
    assert len(calls) == 6


def test_run_cache_concurrent_identical_requests_execute_once(tmp_path):
    db_path = str(tmp_path / 'cache.sqlite3')
    artifact = tmp_path / 'ta_shared.json'
    started = threading.Event()
    release = threading.Event()
    counter_lock = threading.Lock()
    producer_calls = 0

    def producer():
        nonlocal producer_calls
        with counter_lock:
            producer_calls += 1
        started.set()
        assert release.wait(timeout=2)
        result = {'id': 'ta_shared', 'analysis_status': 'SUCCESS_PRIMARY'}
        artifact.write_text(json.dumps(result), encoding='utf-8')
        return result

    def invoke(owner_id):
        cache = RunCache(db_path, wait_seconds=2)
        return execute_cached(cache, 'same-key', owner_id, producer, lambda _: str(artifact))

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(invoke, 'owner-a')
        assert started.wait(timeout=2)
        second = executor.submit(invoke, 'owner-b')
        time.sleep(0.1)
        release.set()
        results = [first.result(timeout=3), second.result(timeout=3)]

    assert producer_calls == 1
    assert {result['id'] for result in results} == {'ta_shared'}
    assert sum(bool(result.get('cache_hit')) for result in results) == 1


def test_run_cache_recovers_expired_process_lease(tmp_path):
    db_path = str(tmp_path / 'cache.sqlite3')
    first = RunCache(db_path)
    assert first.claim('same-key', 'dead-owner').owner is True
    with first._connect() as connection:
        connection.execute(
            'UPDATE run_cache SET lease_until=0 WHERE cache_key=?', ('same-key',),
        )

    recovered = RunCache(db_path).claim('same-key', 'replacement-owner')
    assert recovered.owner is True
    assert recovered.status == 'recovered'


def test_hold_review_result_is_never_cached(tmp_path):
    cache = RunCache(str(tmp_path / 'cache.sqlite3'))
    producer_calls = 0

    def producer():
        nonlocal producer_calls
        producer_calls += 1
        return {'id': f'ta_review_{producer_calls}', 'analysis_status': 'HOLD_REVIEW'}

    first = execute_cached(cache, 'same-key', 'owner-a', producer, lambda _: str(tmp_path / 'missing.json'))
    second = execute_cached(cache, 'same-key', 'owner-b', producer, lambda _: str(tmp_path / 'missing.json'))

    assert first['id'] != second['id']
    assert producer_calls == 2

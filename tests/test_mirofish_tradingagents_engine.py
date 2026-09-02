"""Unit tests for the deep-analysis engine (orchestration + persistence).

Runs the full rule pipeline end-to-end with a patched data source, verifies the
LOCKED run schema, persistence + retrieval, path-traversal rejection in get_run,
and the kill-switch status flag.
"""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

import app.services.mirofish.tradingagents.engine as engine
from app.services.ai_routing.budget import BudgetReservation
from app.services.ai_routing.contracts import RoutingRequest
from app.services.ai_routing.router import estimate_reservation_input_tokens
from app.services.mirofish.tradingagents.run_cache import (
    CacheWaitTimeout, LeaseLostError, RunCache, execute_cached,
)


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
        'models': engine.routing_model_ids(),
        'execution_inputs': {'use_llm': True, 'brain': None},
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
        'evidence_ids': ['ev1'], 'sources': [{'evidence_id': 'ev1', 'content': {'text': '근거'}}],
        'schema_version': '1', 'prompt_version': '1',
        'profile': 'compact', 'models': engine.routing_model_ids(),
        'execution_inputs': {'use_llm': True, 'brain': None},
    }
    calls = []

    def fake(prompt, **kwargs):
        calls.append(kwargs['operation'])
        if kwargs['operation'] == 'bulk_text':
            return '{"digest":"d","evidence_ids":["ev1"]}', {'success': True, 'analysis_status': 'SUCCESS_PRIMARY'}
        if kwargs['operation'] == 'compact_debate':
            return '{"bull_case":"b","bear_case":"r","bull_evidence_ids":["ev1"],"bear_evidence_ids":["ev1"]}', {'success': True, 'analysis_status': 'SUCCESS_PRIMARY'}
        return '{"symbol":"005930","name":"삼성전자","market":"KOSPI","analyst_mean":31.25,"verdict":"BUY","confidence":80,"reasoning":"ok"}', {'success': True, 'analysis_status': 'SUCCESS_PRIMARY'}

    monkeypatch.setattr(engine.llm_client, 'generate_text_with_metadata', fake)
    released = []
    monkeypatch.setattr(engine, 'release_openai_reservations', lambda permits: released.extend(permits))
    first = engine.run_deep_analysis('삼성전자', symbol='005930', profile='compact', evidence_packet=packet)
    second = engine.run_deep_analysis(
        '삼성전자', symbol='005930', profile='compact', evidence_packet=packet,
        reservation_ids={'bulk_text': 'unused-cache-hit'},
        reservation_owner_tokens={'bulk_text': 'owner-cache-hit'}, permits_preflighted=True,
    )
    third = engine.run_deep_analysis('삼성전자', symbol='005930', profile='compact', evidence_packet=packet, force=True)
    assert second['id'] == first['id'] and second['cache_hit'] is True
    assert third['id'] != first['id']
    assert len(calls) == 6
    assert released == [('unused-cache-hit', 'owner-cache-hit')]


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


def test_compact_replay_never_gathers_live_bundle(monkeypatch, tmp_path):
    monkeypatch.setattr(engine, 'RUNS_ROOT', str(tmp_path))
    monkeypatch.setattr(engine.data_hub, 'gather_bundle', lambda *_a, **_k: (_ for _ in ()).throw(AssertionError('live gather')))
    packet = {
        'symbol': '005930', 'name': '삼성전자', 'market': 'KOSPI',
        'as_of': '2026-07-17T06:30:00+00:00', 'fingerprint': 'b' * 64,
        'evidence_ids': ['ev1'], 'sources': [{'evidence_id': 'ev1', 'content': {'text': '수주'}}],
        'numeric_inputs': {'current_price': 70000, 'change_pct': 2.5, 'volume': 1000},
        'deterministic_scores': {'relative_strength': 90, 'trend': 20},
        'risk_gates': {'profit_gate': True}, 'schema_version': '1', 'prompt_version': '1',
        'profile': 'compact', 'models': {'decisive_text.deepseek': 'pro'},
        'execution_inputs': {'use_llm': False, 'brain': None},
    }
    run = engine.run_deep_analysis('삼성전자', symbol='005930', use_llm=False,
                                   profile='compact', evidence_packet=packet, force=True)
    assert run['symbol'] == '005930' and run['market'] == 'KOSPI'
    assert run['bundle_meta']['has_price'] is True


def test_compact_replay_rejects_identity_mismatch_before_any_call(monkeypatch, tmp_path):
    monkeypatch.setattr(engine, 'RUNS_ROOT', str(tmp_path))
    monkeypatch.setattr(engine.llm_client, 'generate_text_with_metadata', pytest.fail)
    packet = {
        'symbol': '000660', 'name': 'SK하이닉스', 'market': 'KOSPI',
        'as_of': '2026-07-17T06:30:00+00:00', 'fingerprint': 'c' * 64,
        'evidence_ids': ['ev1'], 'sources': [{'evidence_id': 'ev1'}],
        'numeric_inputs': {}, 'deterministic_scores': {}, 'risk_gates': {},
        'schema_version': '1', 'prompt_version': '1', 'profile': 'compact', 'models': {},
    }
    with pytest.raises(ValueError, match='identity'):
        engine.run_deep_analysis('삼성전자', symbol='005930', profile='compact',
                                 evidence_packet=packet, force=True)


def test_compact_rejects_execution_mode_or_brain_outside_packet(monkeypatch, tmp_path):
    monkeypatch.setattr(engine, 'RUNS_ROOT', str(tmp_path))
    monkeypatch.setattr(engine.llm_client, 'generate_text_with_metadata', pytest.fail)
    packet = {
        'symbol': '005930', 'name': '삼성전자', 'market': 'KOSPI',
        'as_of': '2026-07-17T06:30:00+00:00', 'fingerprint': '8' * 64,
        'evidence_ids': ['ev1'], 'sources': [{'evidence_id': 'ev1', 'content': {'text': '근거'}}],
        'numeric_inputs': {'current_price': 70000}, 'deterministic_scores': {},
        'risk_gates': {}, 'schema_version': '1', 'prompt_version': '1',
        'profile': 'compact', 'models': {},
        'execution_inputs': {'use_llm': False, 'brain': {'alignment_score': 60}},
    }
    with pytest.raises(ValueError, match='execution'):
        engine.run_deep_analysis(
            '삼성전자', symbol='005930', profile='compact', evidence_packet=packet,
            use_llm=True, force=True,
        )
    with pytest.raises(ValueError, match='brain'):
        engine.run_deep_analysis(
            '삼성전자', symbol='005930', profile='compact', evidence_packet=packet,
            use_llm=False, brain={'alignment_score': 61}, force=True,
        )


def test_live_cache_owner_renews_lease_across_long_chain(tmp_path):
    db_path = str(tmp_path / 'cache.sqlite3')
    artifact = tmp_path / 'long.json'
    calls = 0
    lock = threading.Lock()
    started = threading.Event()
    def producer():
        nonlocal calls
        with lock:
            calls += 1
        started.set()
        time.sleep(1.3)
        value = {'id': 'ta_long', 'analysis_status': 'SUCCESS_PRIMARY'}
        artifact.write_text(json.dumps(value), encoding='utf-8')
        return value
    def invoke(owner):
        return execute_cached(
            RunCache(db_path, lease_seconds=1, wait_seconds=3), 'long-key', owner,
            producer, lambda _: str(artifact),
        )
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(invoke, 'owner-a')
        assert started.wait(1)
        time.sleep(1.1)
        second = pool.submit(invoke, 'owner-b')
        results = [first.result(4), second.result(4)]
    assert calls == 1
    assert {item['id'] for item in results} == {'ta_long'}


def test_cache_waiter_never_returns_materializable_in_progress(tmp_path):
    cache = RunCache(str(tmp_path / 'cache.sqlite3'), lease_seconds=10, wait_seconds=0.1)
    assert cache.claim('busy', 'owner-a').owner
    with pytest.raises(CacheWaitTimeout):
        execute_cached(cache, 'busy', 'owner-b', pytest.fail, lambda _: 'unused')


def test_stale_owner_publish_is_rejected_by_fence(tmp_path):
    cache = RunCache(str(tmp_path / 'cache.sqlite3'))
    old = cache.claim('key', 'owner-a')
    with cache._connect() as connection:
        connection.execute('UPDATE run_cache SET lease_until=0 WHERE cache_key=?', ('key',))
    recovered = cache.claim('key', 'owner-b')
    artifact = tmp_path / 'artifact.json'
    artifact.write_text('{}', encoding='utf-8')
    assert recovered.fence > old.fence
    with pytest.raises(LeaseLostError):
        cache.publish('key', 'owner-a', old.fence, 'ta_old', str(artifact))


def test_admission_rejects_missing_symbol_with_deterministic_id(tmp_path):
    from app.services.mirofish.tradingagents.run_cache import AdmissionManager
    manager = AdmissionManager(str(tmp_path / 'admission.sqlite3'))
    _admitted, first = manager.admit('wf-1', [{'name': 'missing'}], limit=5)
    _admitted, second = manager.admit('wf-1', [{'name': 'missing'}], limit=5)
    assert first['rejected'] == 1 and first['deferred'] == 0
    assert first['records'][0]['reason'] == 'missing_symbol'
    assert first['records'][0]['admission_id'] == second['records'][0]['admission_id']


def test_invalid_compact_citations_are_degraded_and_not_cached(monkeypatch, tmp_path):
    monkeypatch.setattr(engine, 'RUNS_ROOT', str(tmp_path))
    packet = {
        'symbol': '005930', 'name': '삼성전자', 'market': 'KOSPI',
        'as_of': '2026-07-17T06:30:00+00:00', 'fingerprint': 'd' * 64,
        'evidence_ids': ['ev1'], 'sources': [{'evidence_id': 'ev1', 'content': {'text': '근거'}}],
        'numeric_inputs': {'current_price': 70000}, 'deterministic_scores': {},
        'risk_gates': {}, 'schema_version': '1', 'prompt_version': '1',
        'profile': 'compact', 'models': engine.routing_model_ids(),
        'execution_inputs': {'use_llm': True, 'brain': None},
    }
    calls = []
    def fake(_prompt, **kwargs):
        calls.append(kwargs['operation'])
        if kwargs['operation'] == 'bulk_text':
            return '{"digest":"d","evidence_ids":[]}', {'success': True, 'analysis_status': 'SUCCESS_PRIMARY'}
        if kwargs['operation'] == 'compact_debate':
            return '{"bull_case":"b","bear_case":"r","bull_evidence_ids":[],"bear_evidence_ids":[]}', {'success': True, 'analysis_status': 'SUCCESS_PRIMARY'}
        return ('{"symbol":"005930","name":"삼성전자","market":"KOSPI",'
                '"analyst_mean":0,"verdict":"HOLD","confidence":50,"reasoning":"ok"}',
                {'success': True, 'analysis_status': 'SUCCESS_PRIMARY'})
    monkeypatch.setattr(engine.llm_client, 'generate_text_with_metadata', fake)
    first = engine.run_deep_analysis('삼성전자', symbol='005930', profile='compact', evidence_packet=packet)
    second = engine.run_deep_analysis('삼성전자', symbol='005930', profile='compact', evidence_packet=packet)
    assert first['analysis_status'] == second['analysis_status'] == 'DEGRADED'
    assert len(calls) == 6


def test_compact_evidence_calls_forward_citation_validators(monkeypatch, tmp_path):
    monkeypatch.setattr(engine, 'RUNS_ROOT', str(tmp_path))
    packet = {
        'symbol': '005930', 'name': '삼성전자', 'market': 'KOSPI',
        'as_of': '2026-07-17T06:30:00+00:00', 'fingerprint': '7' * 64,
        'evidence_ids': ['ev1'], 'sources': [{'evidence_id': 'ev1', 'content': {'text': '근거'}}],
        'numeric_inputs': {'current_price': 70000}, 'deterministic_scores': {},
        'risk_gates': {}, 'schema_version': '1', 'prompt_version': '1',
        'profile': 'compact', 'models': engine.routing_model_ids(),
        'execution_inputs': {'use_llm': True, 'brain': None},
    }
    validators = {}
    def fake(_prompt, **kwargs):
        validators[kwargs['operation']] = kwargs.get('domain_validator')
        if kwargs['operation'] == 'bulk_text':
            return '{"digest":"d","evidence_ids":["ev1"]}', {'success': True, 'analysis_status': 'SUCCESS_PRIMARY'}
        if kwargs['operation'] == 'compact_debate':
            return '{"bull_case":"b","bear_case":"r","bull_evidence_ids":["ev1"],"bear_evidence_ids":["ev1"]}', {'success': True, 'analysis_status': 'SUCCESS_PRIMARY'}
        return ('{"symbol":"005930","name":"삼성전자","market":"KOSPI",'
                '"analyst_mean":0,"verdict":"HOLD","confidence":50,"reasoning":"ok"}',
                {'success': True, 'analysis_status': 'SUCCESS_PRIMARY'})
    monkeypatch.setattr(engine.llm_client, 'generate_text_with_metadata', fake)
    engine.run_deep_analysis(
        '삼성전자', symbol='005930', profile='compact', evidence_packet=packet, force=True,
    )
    assert validators['bulk_text']({'digest': 'd', 'evidence_ids': []}) is not None
    assert validators['bulk_text']({'digest': 'd', 'evidence_ids': ['foreign']}) is not None
    assert validators['bulk_text']({'digest': 'd', 'evidence_ids': ['ev1']}) is None
    assert validators['compact_debate']({
        'bull_case': 'b', 'bear_case': 'r', 'bull_evidence_ids': [], 'bear_evidence_ids': ['ev1'],
    }) is not None


def test_compact_abort_after_active_stage_skips_remaining_llm_stages(monkeypatch, tmp_path):
    monkeypatch.setattr(engine, 'RUNS_ROOT', str(tmp_path))
    packet = {
        'symbol': '005930', 'name': '삼성전자', 'market': 'KOSPI',
        'as_of': '2026-07-17T06:30:00+00:00', 'fingerprint': 'a' * 64,
        'evidence_ids': ['ev1'],
        'sources': [{'evidence_id': 'ev1', 'content': {'text': '근거'}}],
        'numeric_inputs': {'current_price': 70000}, 'deterministic_scores': {},
        'risk_gates': {}, 'schema_version': '1', 'prompt_version': '1',
        'profile': 'compact', 'models': engine.routing_model_ids(),
        'execution_inputs': {'use_llm': True, 'brain': None},
    }
    abort = threading.Event()
    calls = []

    def fake(_prompt, **kwargs):
        calls.append(kwargs['operation'])
        if kwargs['operation'] != 'bulk_text':
            pytest.fail('abort fence must block every later provider stage')
        assert kwargs['permit_abort_event'] is abort
        abort.set()
        return (
            '{"digest":"d","evidence_ids":["ev1"]}',
            {'success': True, 'analysis_status': 'SUCCESS_PRIMARY'},
        )

    monkeypatch.setattr(engine.llm_client, 'generate_text_with_metadata', fake)
    monkeypatch.setattr(engine, 'release_compact_permits', lambda *_args: None)

    with pytest.raises(RuntimeError, match='permit_lease_renewal_failed'):
        engine.run_deep_analysis(
            '삼성전자', symbol='005930', profile='compact', evidence_packet=packet,
            force=True, routing_run_id='wf-abort', permits_preflighted=True,
            request_ids={
                'bulk_text': 'req-bulk', 'compact_debate': 'req-debate',
                'decisive_text': 'req-decisive',
            },
            reservation_ids={
                'bulk_text': 'permit-bulk', 'compact_debate': 'permit-debate',
                'decisive_text': 'permit-decisive',
            },
            reservation_owner_tokens={
                'bulk_text': 'owner-bulk', 'compact_debate': 'owner-debate',
                'decisive_text': 'owner-decisive',
            },
            permit_abort_event=abort,
        )

    assert calls == ['bulk_text']


def test_preflight_denied_low_priority_stages_are_not_re_reserved(monkeypatch, tmp_path):
    monkeypatch.setattr(engine, 'RUNS_ROOT', str(tmp_path))
    packet = {
        'symbol': '005930', 'name': '삼성전자', 'market': 'KOSPI',
        'as_of': '2026-07-17T06:30:00+00:00', 'fingerprint': 'e' * 64,
        'evidence_ids': ['ev1'], 'sources': [{'evidence_id': 'ev1', 'content': {'text': '근거'}}],
        'numeric_inputs': {'current_price': 70000}, 'deterministic_scores': {},
        'risk_gates': {}, 'schema_version': '1', 'prompt_version': '1',
        'profile': 'compact', 'models': engine.routing_model_ids(),
        'execution_inputs': {'use_llm': True, 'brain': None},
    }
    calls = []
    def fake(_prompt, **kwargs):
        calls.append((kwargs['operation'], kwargs.get('reservation_id')))
        return ('{"symbol":"005930","name":"삼성전자","market":"KOSPI",'
                '"analyst_mean":0,"verdict":"HOLD","confidence":50,"reasoning":"ok"}',
                {'success': True, 'analysis_status': 'SUCCESS_PRIMARY'})
    monkeypatch.setattr(engine.llm_client, 'generate_text_with_metadata', fake)
    monkeypatch.setattr(engine, 'release_openai_reservations', lambda _ids: None)

    result = engine.run_deep_analysis(
        '삼성전자', symbol='005930', profile='compact', evidence_packet=packet,
        force=True, permits_preflighted=True,
        reservation_ids={'decisive_text': 'permit-decisive'},
    )

    assert calls == [('decisive_text', 'permit-decisive')]
    assert result['analysis_status'] == 'DEGRADED'


def test_compact_preflight_bounds_every_actual_runtime_prompt(monkeypatch, tmp_path):
    monkeypatch.setattr(engine, 'RUNS_ROOT', str(tmp_path))
    packet = {
        'symbol': '005930', 'name': '삼성전자', 'market': 'KOSPI',
        'as_of': '2026-07-17T06:30:00+00:00', 'fingerprint': '6' * 64,
        'evidence_ids': ['ev1'], 'sources': [{'evidence_id': 'ev1', 'content': {'text': '근거' * 2000}}],
        'numeric_inputs': {'current_price': 70000}, 'deterministic_scores': {},
        'risk_gates': {}, 'schema_version': '1', 'prompt_version': '1',
        'profile': 'compact', 'models': engine.routing_model_ids(),
        'execution_inputs': {'use_llm': True, 'brain': None},
    }
    reserved = {}
    sequence = iter(range(3))
    def reserve(request, **kwargs):
        reserved[request.operation.value] = request
        index = next(sequence)
        return BudgetReservation(True, f'permit-{index}', acquired_by_caller=True,
                                 owner_token=kwargs['owner_token'])
    monkeypatch.setattr(engine, 'reserve_openai_fallback', reserve)
    prepared, _records = engine.reserve_compact_batch('wf-bound', [packet])
    actual = {}
    def fake(prompt, **kwargs):
        operation = kwargs['operation']
        actual[operation] = RoutingRequest(
            operation=operation, prompt=prompt, system=kwargs.get('system'), json_mode=True,
            max_output_tokens=kwargs['max_tokens'], run_id='wf-bound', request_id=f'actual-{operation}',
        )
        if operation == 'bulk_text':
            return '{"digest":"d","evidence_ids":["ev1"]}', {'success': True, 'analysis_status': 'SUCCESS_PRIMARY'}
        if operation == 'compact_debate':
            return '{"bull_case":"b","bear_case":"r","bull_evidence_ids":["ev1"],"bear_evidence_ids":["ev1"]}', {'success': True, 'analysis_status': 'SUCCESS_PRIMARY'}
        return ('{"symbol":"005930","name":"삼성전자","market":"KOSPI",'
                '"analyst_mean":0,"verdict":"HOLD","confidence":50,"reasoning":"ok"}',
                {'success': True, 'analysis_status': 'SUCCESS_PRIMARY'})
    monkeypatch.setattr(engine.llm_client, 'generate_text_with_metadata', fake)
    monkeypatch.setattr(engine, 'release_compact_permits', lambda *_: None)
    item = prepared[0]
    engine.run_deep_analysis(
        '삼성전자', symbol='005930', profile='compact', evidence_packet=packet,
        force=True, routing_run_id='wf-bound', request_ids=item['request_ids'],
        reservation_ids=item['reservation_ids'],
        reservation_owner_tokens=item['reservation_owner_tokens'], permits_preflighted=True,
    )
    assert set(actual) == {'bulk_text', 'compact_debate', 'decisive_text'}
    for operation, request in actual.items():
        assert estimate_reservation_input_tokens(request) <= estimate_reservation_input_tokens(reserved[operation])


def test_missing_preflight_decisive_permit_dominates_degraded_stages(monkeypatch, tmp_path):
    monkeypatch.setattr(engine, 'RUNS_ROOT', str(tmp_path))
    monkeypatch.setattr(engine.llm_client, 'generate_text_with_metadata', pytest.fail)
    packet = {
        'symbol': '005930', 'name': '삼성전자', 'market': 'KOSPI',
        'as_of': '2026-07-17T06:30:00+00:00', 'fingerprint': '9' * 64,
        'evidence_ids': ['ev1'], 'sources': [{'evidence_id': 'ev1', 'content': {'text': '근거'}}],
        'numeric_inputs': {'current_price': 70000}, 'deterministic_scores': {},
        'risk_gates': {}, 'schema_version': '1', 'prompt_version': '1',
        'profile': 'compact', 'models': engine.routing_model_ids(),
        'execution_inputs': {'use_llm': True, 'brain': None},
    }

    result = engine.run_deep_analysis(
        '삼성전자', symbol='005930', profile='compact', evidence_packet=packet,
        force=True, permits_preflighted=True, reservation_ids={},
    )

    assert result['analysis_status'] == 'HOLD_REVIEW'
    assert result['verdict']['verdict'] == 'HOLD_REVIEW'


def test_partial_preflight_exception_releases_every_acquired_permit(monkeypatch):
    packet = {
        'symbol': '005930', 'market': 'KOSPI', 'fingerprint': 'f' * 64,
    }
    calls = 0
    def reserve(_request, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError('budget store unavailable')
        return BudgetReservation(
            True, f'permit-{calls}', acquired_by_caller=True,
            owner_token=kwargs['owner_token'],
        )
    released = []
    monkeypatch.setattr(engine, 'reserve_openai_fallback', reserve)
    monkeypatch.setattr(
        engine, 'release_openai_reservations', lambda permits: released.extend(permits),
    )

    with pytest.raises(OSError, match='budget store unavailable'):
        engine.reserve_compact_batch('workflow-crash', [packet])

    assert {permit for permit, _owner in released} == {'permit-1', 'permit-2'}
    assert all(owner for _permit, owner in released)

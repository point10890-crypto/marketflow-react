"""Phase 1 C1 — LLM 응답 캐시 / 실측 비용 가드 / picks 사전계산 / 부팅 설정 검증.

리뷰(docs/app_review_prioritization_2026_09_02.md §3.4-6/7, §3.5 ④⑤⑥⑦) 회귀 테스트.
네트워크·운영 데이터 파일을 건드리지 않는다 (conftest 가 캐시 DB/원장 경로를 tmp 로 돌린다).
"""
from __future__ import annotations

import json
import os
import time

import pytest
from flask import Flask

from app.services.mirofish import (
    auto_runner,
    deepseek_client,
    llm_client,
    llm_cost_ledger,
    llm_response_cache,
)


# ─────────────────────────── C1-a: llm_client response cache ───────────────────────────

def _single_provider(monkeypatch, calls, *, provider='openai', model='gpt-4o', text='{"ok": true}',
                     prompt_tokens=1_000_000, completion_tokens=0):
    monkeypatch.setenv('MIROFISH_LLM_PROVIDER_ORDER', provider)
    monkeypatch.setenv('MIROFISH_LLM_DISABLED', ','.join(p for p in llm_client.SUPPORTED_PROVIDERS if p != provider))
    monkeypatch.delenv('MIROFISH_LLM_CACHE_DISABLED', raising=False)
    monkeypatch.setenv('OPENAI_MODEL', model)
    monkeypatch.delenv('OPENAI_FALLBACK_MODEL', raising=False)

    def fake(*_args, **_kwargs):
        calls.append(provider)
        llm_client._record_usage(provider, prompt_tokens, completion_tokens)
        return text

    monkeypatch.setattr(llm_client, f'_generate_{provider}', fake)


def test_llm_cache_hit_skips_provider_and_costs_nothing(monkeypatch):
    calls: list[str] = []
    _single_provider(monkeypatch, calls)

    text1, meta1 = llm_client.generate_text_with_metadata('prompt A', cache_ttl=60, cache_scope='t1')
    with llm_client.collect_generation_metadata() as collected:
        text2, meta2 = llm_client.generate_text_with_metadata('prompt A', cache_ttl=60, cache_scope='t1')

    assert calls == ['openai']
    assert text1 == text2 == '{"ok": true}'
    assert meta1['cache_hit'] is False and meta1['est_cost_usd'] == pytest.approx(2.5)
    assert meta2['cache_hit'] is True
    assert meta2['est_cost_usd'] == 0.0
    assert meta2['provider'] == 'openai' and meta2['model'] == 'gpt-4o'
    assert meta2['usage']['prompt_tokens'] == 1_000_000
    # 적중도 collector 에 게시된다 (원장이 cache_hits 를 셀 수 있게)
    assert len(collected) == 1 and collected[0]['cache_hit'] is True
    assert llm_client.get_last_generation_metadata()['cache_hit'] is True


def test_llm_cache_is_opt_in_and_scoped(monkeypatch):
    calls: list[str] = []
    _single_provider(monkeypatch, calls)

    llm_client.generate_text('prompt B')
    llm_client.generate_text('prompt B')
    assert calls == ['openai', 'openai'], 'cache_ttl=None must not cache'

    llm_client.generate_text('prompt C', cache_ttl=60, cache_scope='scope-1')
    llm_client.generate_text('prompt C', cache_ttl=60, cache_scope='scope-2')
    assert len(calls) == 4, 'different cache_scope must be a miss'

    llm_client.generate_text('prompt C', cache_ttl=60, cache_scope='scope-1', temperature=0.9)
    assert len(calls) == 5, 'temperature is part of the key'

    monkeypatch.setenv('MIROFISH_LLM_CACHE_DISABLED', '1')
    llm_client.generate_text('prompt C', cache_ttl=60, cache_scope='scope-1')
    assert len(calls) == 6, 'kill-switch must bypass the cache'


def test_llm_cache_never_stores_failures(monkeypatch):
    monkeypatch.setenv('MIROFISH_LLM_PROVIDER_ORDER', 'openai')
    monkeypatch.setenv('MIROFISH_LLM_DISABLED', 'deepseek,gemini')
    monkeypatch.delenv('MIROFISH_LLM_CACHE_DISABLED', raising=False)
    monkeypatch.setattr(llm_client, '_generate_openai', lambda *a, **k: None)

    text, meta = llm_client.generate_text_with_metadata('prompt D', cache_ttl=60)
    assert text is None and meta['success'] is False
    assert llm_response_cache.stats()['entries'] == 0


def test_llm_cache_expiry_and_purge(monkeypatch):
    key = llm_response_cache.make_key('unit', 'expiry')
    assert llm_response_cache.put(key, provider='deepseek', model='m', text='cached', usage=None, ttl=1)
    assert llm_response_cache.get(key)['text'] == 'cached'

    real_time = time.time
    monkeypatch.setattr(llm_response_cache.time, 'time', lambda: real_time() + 5)
    assert llm_response_cache.get(key) is None
    assert llm_client.purge_expired() == 1
    assert llm_response_cache.stats()['entries'] == 0
    assert llm_response_cache.put(key, provider='deepseek', model='m', text='x', usage=None, ttl=0) is False


# ─────────────────────────── C1-a: adoption sites ───────────────────────────

class _FakeResponse:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def _candidate(symbol='000001'):
    return {
        'rank': 1, 'symbol': symbol, 'display_name': 'Alpha One', 'market': 'KOSPI',
        'alpha_score': 82, 'risk_score': 20, 'ranking_score': 73, 'action': 'BUY_CANDIDATE',
        'strategy_tags': ['momentum'],
        'price': {'date': '2026-05-04', 'current_price': 1000, 'change_rate': 5.2, 'volume': 1, 'trading_value': 1},
    }


def test_deepseek_rerank_reuses_cached_overlay_for_same_candidate_set(monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'sk-test')
    monkeypatch.delenv('MIROFISH_LLM_CACHE_DISABLED', raising=False)
    requests_made: list[str] = []

    def fake_request(method, url, **kwargs):
        requests_made.append(url)
        return _FakeResponse({
            'model': 'deepseek-v4-pro',
            'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({
                'portfolio_note_ko': 'ok',
                'items': [{'symbol': '000001', 'deepseek_conviction': 80, 'ranking_adjustment': 3,
                           'risk_flags': [], 'positive_evidence': [], 'rationale_ko': 'r'}],
            })}}],
            'usage': {'total_tokens': 10},
        })

    monkeypatch.setattr(deepseek_client.requests, 'request', fake_request)

    first = deepseek_client.rerank_scanner_candidates([_candidate()], run_context={'generated_at': 't1'}, limit=1)
    second = deepseek_client.rerank_scanner_candidates([_candidate()], run_context={'generated_at': 't2'}, limit=1)
    assert len(requests_made) == 1
    assert first['cache_hit'] is False and second['cache_hit'] is True
    assert second['overlay'] == first['overlay'] and second['model'] == 'deepseek-v4-pro'

    deepseek_client.rerank_scanner_candidates([_candidate('000002')], limit=1)
    assert len(requests_made) == 2, 'different candidate set must miss'

    deepseek_client.rerank_scanner_candidates([_candidate()], limit=1, cache_ttl=None)
    assert len(requests_made) == 3, 'cache_ttl=None bypasses the cache'


def test_leading_enricher_news_reason_is_cached_across_calls(monkeypatch):
    import llm_fallback
    from app.services import leading_enricher

    monkeypatch.delenv('MIROFISH_LLM_CACHE_DISABLED', raising=False)
    calls: list[str] = []

    def fake_json(prompt, **_kwargs):
        calls.append(prompt)
        return {'ai_score': 2, 'ai_reason': '수주 공시', 'themes': ['조선']}, 'deepseek'

    monkeypatch.setattr(llm_fallback, 'generate_json_fallback', fake_json)

    first = leading_enricher._analyze_news_llm('한화오션', '042660', 4.2)
    second = leading_enricher._analyze_news_llm('한화오션', '042660', 4.4)   # 같은 정수 버킷(4%)
    assert calls and len(calls) == 1
    assert first == second == {'ai_score': 2, 'ai_reason': '수주 공시', 'themes': ['조선']}

    leading_enricher._analyze_news_llm('한화오션', '042660', 9.0)
    assert len(calls) == 2, 'a different move bucket is a new question'

    # 빈 사유(키 없음/429)는 저장되지 않아 다음 사이클에 재시도된다
    monkeypatch.setattr(llm_fallback, 'generate_json_fallback', lambda *a, **k: (None, 'none'))
    monkeypatch.setattr(leading_enricher, '_analyze_news_gemini',
                        lambda *a, **k: {'ai_score': 0, 'ai_reason': '', 'themes': []})
    leading_enricher._analyze_news_llm('신규', '000000', 1.0)
    assert leading_enricher._read_news_cache('000000', 1.0) is None


# ─────────────────────────── C1-b: measured cost ledger + guard ───────────────────────────

def _meta(model='gpt-4o', cost=0.5, cache_hit=False):
    return {
        'provider': 'openai', 'model': model, 'success': True, 'cache_hit': cache_hit,
        'est_cost_usd': cost,
        'attempts': [] if cache_hit else [{'provider': 'openai', 'model': model, 'success': True, 'est_cost_usd': cost}],
    }


def test_cost_ledger_records_measured_and_estimated_triggers():
    measured = llm_cost_ledger.record_trigger_cost([_meta(cost=0.5), _meta(model='deepseek-chat', cost=0.25)],
                                                   fallback_usd=0.07)
    assert measured['estimated'] is False and measured['usd'] == pytest.approx(0.75)
    assert measured['by_model']['gpt-4o']['calls'] == 1

    estimated = llm_cost_ledger.record_trigger_cost([], fallback_usd=0.07)
    assert estimated['estimated'] is True and estimated['usd'] == pytest.approx(0.07)

    cache_only = llm_cost_ledger.record_trigger_cost([_meta(cost=0.0, cache_hit=True)], fallback_usd=0.07)
    assert cache_only['estimated'] is False and cache_only['usd'] == 0.0

    summary = llm_cost_ledger.get_llm_cost_summary(days=7)
    assert summary['total_usd'] == pytest.approx(0.82)
    assert summary['total_triggers'] == 3 and summary['estimated_calls'] == 1
    assert summary['total_cache_hits'] == 1
    assert summary['by_model']['gpt-4o']['usd'] == pytest.approx(0.5)
    assert summary['avg_usd_per_trigger'] == pytest.approx(0.82 / 3, abs=1e-6)
    assert os.path.isfile(llm_cost_ledger.LEDGER_PATH)
    with open(llm_cost_ledger.LEDGER_PATH, encoding='utf-8') as fh:
        raw = json.load(fh)
    (day, entry), = raw.items()
    assert entry['triggers'] == 3 and 'by_model' in entry and 'estimated_calls' in entry


@pytest.fixture
def isolated_runner(tmp_path, monkeypatch):
    monkeypatch.setattr(auto_runner, 'STATE_DIR', str(tmp_path))
    monkeypatch.setattr(auto_runner, 'STATE_PATH', str(tmp_path / 'auto_runner_state.json'))
    monkeypatch.setattr(auto_runner, 'HISTORY_PATH', str(tmp_path / 'auto_runner_history.jsonl'))
    monkeypatch.setattr(auto_runner.alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setenv('MIROFISH_AUTO_RUNNER_COST_PER_TRIGGER', '0.07')
    return tmp_path


def test_record_success_accumulates_measured_cost_not_flat_estimate(isolated_runner):
    tuning = auto_runner._tunables()
    auto_runner._record_success({}, time.perf_counter(), tuning, top3_count=3, llm_calls=[_meta(cost=1.25)])
    today = auto_runner._read_state()['today']
    assert today['est_cost_usd'] == pytest.approx(1.25)
    assert today['measured_cost_usd'] == pytest.approx(1.25)
    assert today['llm_calls'] == 1 and 'estimated_cost_triggers' not in today

    # 실측이 없으면 고정 추정치로 폴백하고 그 사실을 표시한다
    auto_runner._record_success({}, time.perf_counter(), tuning, top3_count=3, llm_calls=[])
    today = auto_runner._read_state()['today']
    assert today['est_cost_usd'] == pytest.approx(1.32)
    assert today['estimated_cost_triggers'] == 1

    # llm_calls 없이 호출되는 경로(분석 전)는 비용을 더하지 않는다
    auto_runner._record_failure({}, time.perf_counter(), 'pre_analysis', tuning)
    assert auto_runner._read_state()['today']['est_cost_usd'] == pytest.approx(1.32)


def test_cost_gate_projects_next_trigger_from_measured_average(isolated_runner):
    tuning = auto_runner._tunables()
    assert auto_runner._projected_trigger_cost(tuning) == (pytest.approx(0.07), 'flat_estimate')

    llm_cost_ledger.record_trigger_cost([_meta(cost=2.0)], fallback_usd=0.07)
    projected, source = auto_runner._projected_trigger_cost(tuning)
    assert source == 'measured_7d_avg' and projected == pytest.approx(2.0)


def test_fire_workflow_measures_llm_cost_through_collector(isolated_runner, monkeypatch):
    monkeypatch.setenv('MIROFISH_AUTO_RUNNER_DRY_RUN', '0')
    calls: list[str] = []
    _single_provider(monkeypatch, calls)      # gpt-4o, 1M prompt tokens → $2.50 per call

    def fake_workflow(**_kwargs):
        llm_client.generate_text('analyse')
        llm_client.generate_text('analyse again')
        return {'status': 'blocked', 'blocked_reason': 'unit'}

    monkeypatch.setattr(auto_runner.workflow_svc, 'start_workflow_from_scanner_events', fake_workflow)

    tuning = auto_runner._tunables()
    cycle: dict = {}
    result = auto_runner._fire_workflow_transaction(tuning, {}, cycle, time.perf_counter())

    assert result['fired'] is True and result['success'] is False
    assert cycle['llm_cost']['calls'] == 2 and cycle['llm_cost']['estimated'] is False
    assert cycle['llm_cost']['usd'] == pytest.approx(5.0)
    today = auto_runner._read_state()['today']
    assert today['est_cost_usd'] == pytest.approx(5.0) and today['llm_calls'] == 2
    assert llm_cost_ledger.get_llm_cost_summary(days=1)['total_usd'] == pytest.approx(5.0)
    assert auto_runner.get_llm_cost_summary(days=1)['by_model']['gpt-4o']['calls'] == 2


def test_agent_status_route_exposes_llm_cost(monkeypatch):
    from app.routes import admin_mirofish
    from app.services.mirofish import alpha_brain_agent

    monkeypatch.setattr(alpha_brain_agent, 'get_agent_status', lambda: {'service': 'stub'})
    llm_cost_ledger.record_trigger_cost([_meta(cost=0.3)], fallback_usd=0.07)

    app = Flask(__name__)
    app.register_blueprint(admin_mirofish.admin_mirofish_bp, url_prefix='/api/admin/mirofish')
    with app.test_request_context('/api/admin/mirofish/agent/status'):
        body = admin_mirofish.agent_status.__wrapped__().get_json()

    assert body['service'] == 'stub'
    assert body['llm_cost']['days'] == 7
    assert body['llm_cost']['total_usd'] == pytest.approx(0.3)


# ─────────────────────────── C1-c: picks summary precompute ───────────────────────────

def _write_picks_fixture(root):
    history = root / 'history'
    history.mkdir()
    (history / 'picks_2026-01-02.json').write_text(json.dumps({
        'analysis_date': '2026-01-02',
        'picks': [
            {'ticker': 'AAPL', 'price_at_analysis': 100.0},
            {'ticker': 'MSFT', 'price_at_analysis': 200.0},
        ],
    }), encoding='utf-8')
    (history / 'picks_2026-01-05.json').write_text(json.dumps({
        'analysis_date': '2026-01-05',
        'picks': [
            {'ticker': 'AAPL', 'price_at_analysis': 110.0},
            {'ticker': 'ZZZZ', 'price_at_analysis': 5.0},     # 가격 데이터 없음 → 제외
        ],
    }), encoding='utf-8')
    data = root / 'data'
    data.mkdir()
    rows = ['Date,Ticker,Close']
    for date, aapl, msft, spy in [
        ('2026-01-02', 100, 200, 500),
        ('2026-01-05', 110, 190, 510),
        ('2026-01-09', 121, 180, 520),
    ]:
        rows += [f'{date},AAPL,{aapl}', f'{date},MSFT,{msft}', f'{date},SPY,{spy}']
    csv_path = data / 'us_daily_prices.csv'
    csv_path.write_text('\n'.join(rows) + '\n', encoding='utf-8')
    output = root / 'output'
    output.mkdir()
    return history, csv_path, output


def test_build_picks_summary_matches_route_formula(tmp_path):
    from app.services.us_picks_summary import build_picks_summary

    history, csv_path, _ = _write_picks_fixture(tmp_path)
    summary = build_picks_summary(str(history), str(csv_path))

    assert [row['date'] for row in summary['by_date']] == ['2026-01-05', '2026-01-02']
    jan2 = summary['by_date'][1]
    # AAPL 100→121 (+21%), MSFT 200→180 (-10%) → avg 5.5 ; SPY 500→520 (+4%) → alpha 1.5
    assert jan2 == {'date': '2026-01-02', 'avg_return': 5.5, 'spy_return': 4.0, 'alpha': 1.5,
                    'win_rate': 50.0, 'num_picks': 2}
    jan5 = summary['by_date'][0]
    # AAPL 110→121 (+10%) ; SPY 510→520 (+1.96%)
    assert jan5['num_picks'] == 1 and jan5['avg_return'] == 10.0 and jan5['spy_return'] == 1.96
    assert summary['overall']['total_recommendations'] == 3
    assert summary['overall']['num_dates'] == 2
    assert summary['overall']['avg_return_all'] == pytest.approx(7.75)
    assert summary['source']['picks_files'] == 2


def test_history_summary_route_serves_fresh_precomputed_file(tmp_path, monkeypatch):
    from app.routes import us_market
    from app.services import us_picks_summary

    history, csv_path, output = _write_picks_fixture(tmp_path)
    monkeypatch.setattr(us_market, '_HISTORY_DIR', str(history))
    monkeypatch.setattr(us_market, '_DATA_DIR', str(csv_path.parent))
    monkeypatch.setattr(us_market, '_OUTPUT_DIR', str(output))

    builds: list[str] = []
    real_build = us_picks_summary.build_picks_summary

    def counting_build(history_dir, latest_csv):
        builds.append(history_dir)
        return real_build(history_dir, latest_csv)

    monkeypatch.setattr(us_picks_summary, 'build_picks_summary', counting_build)

    app = Flask(__name__)
    app.register_blueprint(us_market.us_bp, url_prefix='/api/us')
    client = app.test_client()

    first = client.get('/api/us/history-summary')
    assert first.status_code == 200
    assert first.get_json()['overall']['num_dates'] == 2
    summary_path = output / us_picks_summary.SUMMARY_FILENAME
    assert summary_path.is_file() and len(builds) == 1

    second = client.get('/api/us/history-summary')
    assert second.status_code == 200 and second.get_json()['by_date'] == first.get_json()['by_date']
    assert len(builds) == 1, 'fresh picks_summary.json must be served without recomputing'

    # 새 picks 파일이 생기면(더 새로운 mtime) 자가 치유 재계산
    newer = history / 'picks_2026-01-09.json'
    newer.write_text(json.dumps({'picks': [{'ticker': 'MSFT', 'price_at_analysis': 180.0}]}), encoding='utf-8')
    future = time.time() + 30
    os.utime(newer, (future, future))
    third = client.get('/api/us/history-summary')
    assert third.status_code == 200
    assert len(builds) == 2 and third.get_json()['overall']['num_dates'] == 3

    monkeypatch.setattr(us_market, '_HISTORY_DIR', str(tmp_path / 'missing'))
    assert client.get('/api/us/history-summary').status_code == 404


# ─────────────────────────── C1-d: boot-time config validation ───────────────────────────

_CONFIG_KEYS = (
    'SECRET_KEY', 'DEEPSEEK_API_KEY', 'OPENAI_API_KEY', 'GEMINI_API_KEY', 'GOOGLE_API_KEY',
    'DART_API_KEY', 'KIS_APP_KEY', 'KIS_APP_SECRET', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID',
    'MIROFISH_USE_KIS', 'WORKER_SCREENER_ENABLED', 'MARKETFLOW_STRICT_CONFIG',
)


@pytest.fixture
def bare_env(monkeypatch):
    for key in _CONFIG_KEYS:
        monkeypatch.delenv(key, raising=False)
    for key in list(os.environ):
        if key.endswith('_TELEGRAM_ENABLED'):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr('dotenv.load_dotenv', lambda *a, **k: False, raising=False)


def test_validate_runtime_config_lists_missing_names_without_values(bare_env, monkeypatch):
    from config import validate_runtime_config

    problems = validate_runtime_config(strict=False)
    joined = '\n'.join(problems)
    assert 'SECRET_KEY' in joined
    assert 'DEEPSEEK_API_KEY' in joined and 'DART_API_KEY' in joined
    assert 'KIS_APP_KEY and KIS_APP_SECRET' in joined and 'MIROFISH_USE_KIS' in joined
    assert 'TELEGRAM' not in joined, 'telegram is only required when a *_TELEGRAM_ENABLED flag is on'

    monkeypatch.setenv('ALPHA_SCANNER_TELEGRAM_ENABLED', '1')
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'bot123:secret-value')
    problems = validate_runtime_config(strict=False)
    telegram = [p for p in problems if 'TELEGRAM_CHAT_ID' in p]
    assert telegram and 'ALPHA_SCANNER_TELEGRAM_ENABLED' in telegram[0]
    assert 'secret-value' not in '\n'.join(problems)

    monkeypatch.setenv('SECRET_KEY', 'x')
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'x')
    monkeypatch.setenv('DART_API_KEY', 'x')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', '1')
    monkeypatch.setenv('MIROFISH_USE_KIS', '0')
    monkeypatch.setenv('WORKER_SCREENER_ENABLED', '0')
    assert validate_runtime_config(strict=False) == []


def test_validate_runtime_config_strict_raises(bare_env, monkeypatch):
    from config import RuntimeConfigError, validate_runtime_config

    with pytest.raises(RuntimeConfigError) as excinfo:
        validate_runtime_config(strict=True)
    assert 'SECRET_KEY' in str(excinfo.value)

    assert validate_runtime_config() != [], 'strict=None without the env flag is lenient'
    monkeypatch.setenv('MARKETFLOW_STRICT_CONFIG', '1')
    with pytest.raises(RuntimeConfigError):
        validate_runtime_config()


def test_create_app_is_lenient_by_default_and_strict_on_flag(bare_env, monkeypatch, caplog):
    from app import create_app

    with caplog.at_level('WARNING'):
        app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                          'SQLALCHEMY_ENGINE_OPTIONS': {}})
    assert app is not None
    assert any('[config] SECRET_KEY' in rec.getMessage() for rec in caplog.records)

    monkeypatch.setenv('MARKETFLOW_STRICT_CONFIG', '1')
    with pytest.raises(RuntimeError) as excinfo:
        create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                    'SQLALCHEMY_ENGINE_OPTIONS': {}})
    assert 'MARKETFLOW_STRICT_CONFIG=1' in str(excinfo.value)

# -*- coding: utf-8 -*-
"""2026-09-02 전체 리뷰 Phase 0 quick-win 회귀 테스트.

merge note (2026-09-03): llm_analyzer 쿨다운 재개방·llm_client usage/cost 메타데이터
퀵윈 테스트 4건은 cost-aware ai_routing 스택(CircuitBreaker + 비용 원장)이 상위집합으로
대체하여 제거 — 해당 계약은 tests/test_ai_routing_router.py·test_ai_routing_telemetry.py·
test_llm_provider_fallback.py 가 검증한다.

각 테스트는 리뷰에서 확인한 결함 하나를 고정한다:
- 인증 GET 데이터 응답이 전부 no-store 였던 죽은 캐시 분기 + ETag/304 부재
- LLM rate-limit 브레이커가 프로세스 수명 동안 영구 비활성
- 검색 도구 없는 DeepSeek/OpenAI 경로에 "Google Search 로 찾은 뉴스" 요구
- alpha_scanner 의 종가베팅 점수 포화점(15) 이 ScoreDetail 정의(20)와 문서로 묶여 있지 않음
- CommandPalette 검색이 substring 만 지원 (초성·별칭 리졸버 미사용)
- LLM 메타데이터에 토큰/비용 부재
- 스케줄러 status 가 데몬 heartbeat/실행 기록을 보지 않음
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest


# ─────────────────────────── Cache-Control + ETag ───────────────────────────

@pytest.fixture()
def api_app(monkeypatch):
    monkeypatch.delenv('SECRET_KEY', raising=False)
    from app import create_app

    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
    })
    return app


def test_authenticated_get_json_is_privately_cacheable_with_etag(api_app):
    client = api_app.test_client()
    first = client.get('/api/health', headers={'Authorization': 'Bearer not-a-real-token'})
    assert first.status_code == 200
    assert first.headers['Cache-Control'].startswith('private,')
    assert 'no-store' not in first.headers['Cache-Control']
    etag = first.headers.get('ETag')
    assert etag, 'GET 200 JSON must carry an ETag'

    second = client.get('/api/health', headers={
        'Authorization': 'Bearer not-a-real-token',
        'If-None-Match': etag,
    })
    assert second.status_code == 304
    assert second.get_data() == b''


def test_sensitive_prefixes_and_errors_stay_no_store(api_app):
    client = api_app.test_client()
    auth_error = client.get('/api/auth/me')
    assert 'no-store' in auth_error.headers['Cache-Control']
    assert 'ETag' not in auth_error.headers


# ─────────────────────────── LLM circuit breaker ────────────────────────────

# ─────────────────────────── Briefing prompt honesty ─────────────────────────

def test_briefing_prompt_never_asks_for_search_on_non_grounded_path():
    from briefing_generator import BriefingGenerator

    gen = BriefingGenerator()
    data = {'indices': {'^GSPC': {'name': 'S&P500', 'price': 5000, 'change': 1.2}}}

    plain = gen._build_morning_prompt(data, search_capable=False)
    grounded = gen._build_morning_prompt(data, search_capable=True)
    closing_plain = gen._build_closing_prompt({'kospi': {}}, search_capable=False)

    assert 'Google Search' not in plain
    assert '지어내지' in plain
    assert 'Google Search' in grounded
    assert 'Google Search' not in closing_plain
    # 기본값(인자 생략)도 안전한 쪽(검색 요구 없음)이어야 한다
    assert 'Google Search' not in gen._build_morning_prompt(data)


# ─────────────────────────── Alpha scanner jongga scale ──────────────────────

def test_alpha_scanner_jongga_scale_is_documented_against_score_detail_max():
    """포화점(15) 은 이론 최대(20) 이하이고, 상수가 실제 ScoreDetail 정의와 어긋나면 잡는다."""
    from app.services.mirofish import alpha_scanner
    from engine.models import ScoreDetail

    full = ScoreDetail(news=3, volume=3, chart=2, candle=1, consolidation=1,
                       supply=2, disclosure=2, analyst=3, financial=3)
    assert alpha_scanner.JONGGA_SCORE_THEORETICAL_MAX == full.total == 20
    assert 0 < alpha_scanner.JONGGA_SCORE_SATURATION <= alpha_scanner.JONGGA_SCORE_THEORETICAL_MAX


# ─────────────────────────── Stock search: smart matches ─────────────────────

@pytest.fixture()
def kr_search_env(monkeypatch):
    from app.routes import stock_analyzer as sa

    rows = [
        {'ticker': '005930', 'yahoo': '005930.KS', 'name': '삼성전자', 'market': 'KOSPI'},
        {'ticker': '000660', 'yahoo': '000660.KS', 'name': 'SK하이닉스', 'market': 'KOSPI'},
        {'ticker': '035420', 'yahoo': '035420.KS', 'name': 'NAVER', 'market': 'KOSPI'},
    ]
    monkeypatch.setattr(sa, '_load_kr_stocks', lambda: rows)
    return sa, rows


def test_search_uses_resolver_candidates_before_substring(kr_search_env, monkeypatch):
    sa, rows = kr_search_env
    from app.services.mirofish import decision_brief

    def fake_search(query, *, limit=8):
        assert query == 'ㅅㅅㅈㅈ'
        return {'query': query, 'candidates': [
            {'symbol': '005930', 'name': '삼성전자', 'confidence': 0.85, 'reason': 'chosung_exact'},
        ]}

    monkeypatch.setattr(decision_brief, 'search_symbols', fake_search)
    out = sa._kr_smart_matches('ㅅㅅㅈㅈ', rows, limit=20)
    assert [o['code'] for o in out] == ['005930']
    assert out[0]['match'] == 'chosung_exact'
    assert out[0]['ticker'] == '005930.KS'


def test_search_survives_resolver_failure(kr_search_env, monkeypatch):
    sa, rows = kr_search_env
    from app.services.mirofish import decision_brief

    def boom(query, *, limit=8):
        raise RuntimeError('entities.db missing')

    monkeypatch.setattr(decision_brief, 'search_symbols', boom)
    assert sa._kr_smart_matches('삼성', rows, limit=20) == []


def test_search_endpoint_merges_smart_and_substring(kr_search_env, monkeypatch, api_app):
    sa, rows = kr_search_env
    from app.services.mirofish import decision_brief

    monkeypatch.setattr(decision_brief, 'search_symbols', lambda q, *, limit=8: {
        'query': q, 'candidates': [{'symbol': '000660', 'name': 'SK하이닉스', 'confidence': 0.9, 'reason': 'alias'}],
    })
    with api_app.test_request_context('/api/stock-analyzer/search?q=하이닉스'):
        payload = json.loads(sa.search_stocks().get_data(as_text=True))
    codes = [p['code'] for p in payload]
    assert codes[0] == '000660'
    assert codes.count('000660') == 1, 'resolver hit must not be duplicated by substring pass'


# ─────────────────────────── LLM usage + cost metadata ───────────────────────

def test_llm_pricing_unknown_model_returns_none_not_a_guess(monkeypatch):
    from app.services.mirofish import llm_pricing

    monkeypatch.delenv('MIROFISH_LLM_PRICE_JSON', raising=False)
    llm_pricing.reset_price_cache()
    assert llm_pricing.estimate_cost_usd('totally-unknown-model', {'prompt_tokens': 10, 'completion_tokens': 10}) is None
    assert llm_pricing.normalize_usage(None, None) is None

    monkeypatch.setenv('MIROFISH_LLM_PRICE_JSON', json.dumps({'totally-unknown-model': [1.0, 2.0]}))
    llm_pricing.reset_price_cache()
    assert llm_pricing.estimate_cost_usd('totally-unknown-model', {'prompt_tokens': 1_000_000, 'completion_tokens': 0}) == pytest.approx(1.0)
    llm_pricing.reset_price_cache()


# ─────────────────────────── Scheduler daemon status ─────────────────────────

def test_scheduler_status_reads_daemon_heartbeat_and_last_runs(tmp_path, monkeypatch):
    import app.utils.paths as paths
    from app.utils import scheduler as sch

    monkeypatch.setattr(paths, 'DATA_DIR', str(tmp_path))
    now = datetime(2026, 9, 2, 15, 0, 0)
    (tmp_path / 'scheduler_heartbeat.json').write_text(
        json.dumps({'pid': 123, 'ts': (now - timedelta(seconds=40)).isoformat(timespec='seconds')}), encoding='utf-8')
    (tmp_path / 'scheduler_last_run.json').write_text(json.dumps({
        'kr_jongga': (now - timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M:%S'),
        'us_market': (now - timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M:%S'),
    }), encoding='utf-8')

    state = sch._read_daemon_state(now=now)
    assert state['alive'] is True
    assert state['stale_seconds'] == 40.0
    assert [r['job'] for r in state['last_runs']] == ['us_market', 'kr_jongga']
    assert state['last_runs'][1]['age_minutes'] == 120.0

    status = sch.get_scheduler_status()
    assert 'daemon' in status


def test_scheduler_status_reports_dead_daemon_when_no_heartbeat(tmp_path, monkeypatch):
    import app.utils.paths as paths
    from app.utils import scheduler as sch

    monkeypatch.setattr(paths, 'DATA_DIR', str(tmp_path))
    state = sch._read_daemon_state()
    assert state['alive'] is False
    assert state['last_runs'] == []

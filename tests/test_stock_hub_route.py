# -*- coding: utf-8 -*-
"""GET /api/kr/stock/<code>/hub — Pro 게이트, 아티팩트 조립, 결측은 null (500 금지)."""
import json
from types import SimpleNamespace

import pytest
from flask import Flask

import app.auth.decorators as auth
from app.routes.kr_stock_hub import kr_stock_hub_bp
from app.services import stock_hub as svc
from app.services.mirofish import alpha_scanner
from app.services.omni import ledger as omni_ledger
from app.utils import json_cache
import marketflow_claw.memory as claw_mem


def _app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'test-only'
    app.register_blueprint(kr_stock_hub_bp, url_prefix='/api/kr/stock')
    return app


def _user(*, tier='pro', approved=True, expired=False):
    return SimpleNamespace(status='approved' if approved else 'pending', is_admin=False,
                           is_approved=approved, is_pro_expired=expired, is_aibain_active=False,
                           tier=tier)


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    """모든 아티팩트 경로를 tmp 로 돌린다. 기본은 '아무것도 없음'."""
    json_cache.invalidate()
    wave = tmp_path / 'wave'
    wave.mkdir()
    monkeypatch.setattr(svc, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(svc, 'WAVE_DIR', str(wave))
    svc._ticker_map_cache['mtime'] = None
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setitem(alpha_scanner._PRICE_HISTORY_CACHE, 'data', None)
    monkeypatch.setattr(omni_ledger, 'DB_PATH', str(tmp_path / 'omni' / 'omni.db'))
    monkeypatch.setattr(claw_mem, 'DB_PATH', str(tmp_path / 'claw' / 'claw.db'))
    yield tmp_path
    json_cache.invalidate()
    alpha_scanner._PRICE_HISTORY_CACHE['data'] = None


def _seed(tmp_path):
    (tmp_path / 'ticker_to_yahoo_map.csv').write_text(
        '﻿ticker,market,yahoo_ticker,name\n005930,KOSPI,005930.KS,삼성전자\n', encoding='utf-8')
    lines = ['ticker,date,name,current_price,change_rate,high,low,open,volume,update_time']
    for i in range(1, 131):
        lines.append(f'005930,2026-{(i - 1) // 28 + 1:02d}-{(i - 1) % 28 + 1:02d},삼성전자,{100000 + i * 10},0.1,'
                     f'{100000 + i * 10 + 50},{100000 + i * 10 - 50},{100000 + i * 10},1000,09:00')
    lines.append('000660,2026-01-01,SK하이닉스,500000,0,0,0,0,10,09:00')
    (tmp_path / 'daily_prices.csv').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    (tmp_path / 'jongga_v2_latest.json').write_text(json.dumps({
        'date': '2026-09-02', 'updated_at': '2026-09-02T15:20:00+09:00',
        'signals': [{'stock_code': '005930', 'stock_name': '삼성전자', 'market': 'KOSPI', 'sector': '반도체',
                     'grade': 'A', 'score': {'total': 8, 'news': 3, 'volume': 3, 'llm_reason': '수급 유입'},
                     'entry_price': 101300, 'stop_price': 98000, 'target_price': 106000,
                     'change_pct': 4.6, 'trading_value': 3.6e12, 'foreign_5d': 1000, 'inst_5d': 2000,
                     'themes': ['반도체', 'AI']}]}, ensure_ascii=False), encoding='utf-8')
    (tmp_path / 'screener_leading_latest.json').write_text(json.dumps({
        'timestamp': '2026-09-02T15:48:00', 'market_status': 'closed',
        'results': [{'rank': 13, 'grade': 'A', 'code': '005930', 'name': '삼성전자', 'price': 186700,
                     'change_pct': 4.65, 'trading_value_eok': 36091, 'volume_ratio': 50.4,
                     'score': {'total': 65, 'total_enriched': 67},
                     'investor': {'foreign_net': 516352, 'inst_net': 1904658},
                     'high_52w': {'distance_pct': 16.3},
                     'enrichment': {'market_cap_tier': '대형', 'consecutive_days': 1}}]}, ensure_ascii=False), encoding='utf-8')
    (tmp_path / 'vcp_kr_latest.json').write_text(json.dumps({
        'metadata': {'generated_at': '2026-09-02T17:32:13', 'gate': 'RED'},
        'signals': [{'symbol': '005930', 'name': '삼성전자', 'price': 186700,
                     'composite': {'composite_score': 74.2, 'rating': 'Strong VCP', 'entry_ready': 'True',
                                   'valid_vcp': 'False', 'guidance': '피벗 확인'},
                     'stage': {'stage_label': 'Stage 2 - Advancing'},
                     'vcp_pattern': {'pivot_price': 190000, 'num_contractions': 2},
                     'relative_strength': {'score': 95, 'rs_rank_estimate': 95}}]}, ensure_ascii=False), encoding='utf-8')
    (tmp_path / 'wave' / 'wave_screener_latest.json').write_text(json.dumps({
        'date': '2026-09-02', 'updated_at': '2026-09-02T18:00:00',
        'signals': [{'ticker': '005930', 'name': '삼성전자', 'price': 186700, 'pattern_count': 1,
                     'best_pattern': {'pattern_class': 'W', 'wave_type': 'INV_HEAD_SHOULDERS',
                                      'wave_label': '역헤드앤숄더', 'confidence': 82, 'completion_pct': 100.0,
                                      'neckline_price': 185000, 'volume_confirmed': True}}]}, ensure_ascii=False), encoding='utf-8')
    for ymd, grade in (('20260902', 'A'), ('20260827', 'S'), ('20260820', 'B')):
        (tmp_path / f'jongga_v2_results_{ymd}.json').write_text(json.dumps({
            'date': f'{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}',
            'signals': [{'stock_code': '005930', 'stock_name': '삼성전자', 'grade': grade,
                         'score': {'total': 8}, 'change_pct': 2.0, 'entry_price': 100000,
                         'stop_price': 97000, 'target_price': 105000},
                        {'stock_code': '000660', 'stock_name': 'SK하이닉스', 'grade': 'S',
                         'score': {'total': 10}, 'change_pct': 6.0}]}, ensure_ascii=False), encoding='utf-8')
    (tmp_path / 'cumulative_performance.json').write_text(json.dumps({'signals': [
        {'stock_code': '005930', 'signal_date': '2026-08-27', 'outcome': 'TARGET_HIT',
         'roi_pct': 5.0, 'hold_roi_pct': 6.0, 'days_held': 3}]}), encoding='utf-8')


def test_route_is_get_only_and_requires_pro(isolated, monkeypatch):
    app = _app()
    rule = next(r for r in app.url_map.iter_rules() if r.rule == '/api/kr/stock/<code>/hub')
    assert 'POST' not in rule.methods
    client = app.test_client()
    monkeypatch.setattr(auth, '_get_current_user', lambda: None)
    assert client.get('/api/kr/stock/005930/hub').status_code == 401
    monkeypatch.setattr(auth, '_get_current_user', lambda: _user(tier='free'))
    assert client.get('/api/kr/stock/005930/hub').status_code == 403
    monkeypatch.setattr(auth, '_get_current_user', lambda: _user(expired=True))
    assert client.get('/api/kr/stock/005930/hub').status_code == 403


def test_invalid_code_is_400(isolated, monkeypatch):
    monkeypatch.setattr(auth, '_get_current_user', lambda: _user())
    client = _app().test_client()
    assert client.get('/api/kr/stock/abc/hub').status_code == 400
    assert client.get('/api/kr/stock/%3Cscript%3E/hub').status_code == 400


def test_missing_artifacts_yield_nulls_not_500(isolated, monkeypatch):
    monkeypatch.setattr(auth, '_get_current_user', lambda: _user())
    r = _app().test_client().get('/api/kr/stock/005930/hub')
    assert r.status_code == 200
    assert 'private' in r.headers['Cache-Control']
    body = r.get_json()
    assert body['code'] == '005930' and body['name'] is None
    assert body['price'] is None and body['chart'] == []
    assert body['sources'] == {'jongga': None, 'leading': None, 'vcp': None, 'wave': None, 'claw': None}
    assert body['present'] == [] and body['history'] == [] and body['news'] == []
    assert body['errors'] == {}


def test_assembles_pro_sources_from_artifacts(isolated, monkeypatch):
    _seed(isolated)
    monkeypatch.setattr(auth, '_get_current_user', lambda: _user())
    r = _app().test_client().get('/api/kr/stock/5930/hub')   # zero-pad 허용
    assert r.status_code == 200
    body = r.get_json()
    assert body['code'] == '005930' and body['name'] == '삼성전자'
    assert body['market'] == 'KOSPI' and body['sector'] == '반도체'
    # 가격 — 마지막 120봉, 등락률은 직전 종가 대비
    assert body['price']['close'] == 101300 and body['price']['prev_close'] == 101290
    assert body['price']['change_pct'] == round((101300 / 101290 - 1) * 100, 2)
    assert len(body['chart']) == 120 and body['chart'][-1]['date'] == body['price']['date']
    # 소스
    assert body['present'] == ['jongga', 'leading', 'vcp', 'wave']
    assert body['sources']['jongga']['grade'] == 'A' and body['sources']['jongga']['score_total'] == 8
    assert body['sources']['jongga']['llm_reason'] == '수급 유입'
    assert body['sources']['leading']['rank'] == 13 and body['sources']['leading']['score_total'] == 67
    assert body['sources']['vcp']['entry_ready'] is True and body['sources']['vcp']['valid_vcp'] is False
    assert body['sources']['wave']['wave_label'] == '역헤드앤숄더' and body['sources']['wave']['confidence'] == 82
    assert body['sources']['claw'] is None   # claw.db 스냅샷 없음 → null (오류 아님)
    # 이력 — 최신순, 사후 추적은 있는 행만
    assert [h['date'] for h in body['history']] == ['2026-09-02', '2026-08-27', '2026-08-20']
    assert body['history'][1]['outcome'] == 'TARGET_HIT' and body['history'][1]['roi_pct'] == 5.0
    assert body['history'][0]['outcome'] is None
    assert body['errors'] == {}
    # AI Brain 전용 키는 없다
    dumped = json.dumps(body, ensure_ascii=False)
    for forbidden in ('scanner', 'tradingagents', 'paper', 'confidence_cap', 'agreement'):
        assert f'"{forbidden}"' not in dumped


def test_source_exception_is_isolated(isolated, monkeypatch):
    _seed(isolated)
    monkeypatch.setattr(auth, '_get_current_user', lambda: _user())
    monkeypatch.setattr(svc, '_src_claw', lambda code: (_ for _ in ()).throw(RuntimeError('db locked')))
    monkeypatch.setattr(svc, '_news', lambda code, limit=8: (_ for _ in ()).throw(OSError('no ledger')))
    r = _app().test_client().get('/api/kr/stock/005930/hub')
    assert r.status_code == 200
    body = r.get_json()
    assert body['sources']['claw'] is None and body['news'] == []
    assert body['errors']['claw'].startswith('RuntimeError') and body['errors']['news'].startswith('OSError')
    assert body['sources']['jongga']['grade'] == 'A'


def test_news_comes_from_omni_ledger(isolated, monkeypatch):
    _seed(isolated)
    monkeypatch.setattr(auth, '_get_current_user', lambda: _user())
    with omni_ledger.connect() as con:
        con.execute(
            'INSERT INTO news_events (content_hash, title, summary, link, source, sources, grade, published_ts, '
            'symbols, themes, score, corroboration, collected_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
            ('h1', '삼성전자 신규 수주', '요약', 'https://example.com/1', 'rss', '["rss"]', 'B',
             '2026-09-02T08:00:00', '["005930"]', '["반도체"]', 0.8, 1, '2026-09-02T08:05:00'))
    body = _app().test_client().get('/api/kr/stock/005930/hub').get_json()
    assert body['news'][0]['title'] == '삼성전자 신규 수주'
    assert body['news'][0]['link'] == 'https://example.com/1'

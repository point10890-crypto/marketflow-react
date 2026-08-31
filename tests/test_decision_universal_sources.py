# -*- coding: utf-8 -*-
"""판단 브리프 보편 소스 4종 — 미검출 종목(SKT 사례)도 근거가 서야 한다 (2026-09-01)."""
from datetime import datetime, timedelta

import pytest

from app.services.mirofish import decision_brief as db


def _closes_rows(closes, start='2026-01-05'):
    base = datetime.fromisoformat(start)
    return [{'date': (base + timedelta(days=i)).strftime('%Y-%m-%d'), 'current_price': c}
            for i, c in enumerate(closes)]


# ─── 가격·추세 ───────────────────────────────────────────────

def test_price_trend_uptrend_is_positive(monkeypatch):
    import app.services.mirofish.alpha_scanner as alpha_scanner
    closes = [100 + i for i in range(80)]                     # 꾸준한 상승
    monkeypatch.setattr(alpha_scanner, '_load_price_history_cached',
                        lambda: {'017670': _closes_rows(closes)})
    out = db._src_price_trend('017670')
    assert out['stance'] == 'positive'
    assert out['detail']['ma20'] and out['detail']['ret_20d_pct'] > 0
    assert out['as_of'].startswith('2026-')


def test_price_trend_downtrend_is_negative(monkeypatch):
    import app.services.mirofish.alpha_scanner as alpha_scanner
    closes = [200 - i for i in range(80)]
    monkeypatch.setattr(alpha_scanner, '_load_price_history_cached',
                        lambda: {'017670': _closes_rows(closes)})
    assert db._src_price_trend('017670')['stance'] == 'negative'


def test_price_trend_without_history_is_gap(monkeypatch):
    import app.services.mirofish.alpha_scanner as alpha_scanner
    monkeypatch.setattr(alpha_scanner, '_load_price_history_cached', lambda: {})
    assert db._src_price_trend('017670') is None


# ─── 실시간 수급 ─────────────────────────────────────────────

def test_live_flow_double_buy_is_positive(monkeypatch):
    from app.services.mirofish import live_data
    monkeypatch.setattr(live_data, 'load_kis_snapshot', lambda resolved: {
        'found': True,
        'quote': {'price': 55000, 'change_pct': 1.2, 'per': 9.1, 'pbr': 0.8},
        'investor': {'foreign_net_value': 120, 'institution_net_value': 40},
    })
    out = db._src_live_flow('017670')
    assert out['stance'] == 'positive' and out['detail']['price'] == 55000


def test_live_flow_double_sell_down_is_negative(monkeypatch):
    from app.services.mirofish import live_data
    monkeypatch.setattr(live_data, 'load_kis_snapshot', lambda resolved: {
        'found': True, 'quote': {'price': 100, 'change_pct': -2.0},
        'investor': {'foreign_net_value': -50, 'institution_net_value': -10},
    })
    assert db._src_live_flow('017670')['stance'] == 'negative'


def test_live_flow_unavailable_is_gap(monkeypatch):
    from app.services.mirofish import live_data
    monkeypatch.setattr(live_data, 'load_kis_snapshot', lambda resolved: {'found': False})
    assert db._src_live_flow('017670') is None


# ─── 상대강도 / 리스크 ───────────────────────────────────────

def test_sector_rs_reads_artifact_only(monkeypatch):
    from app.services.mirofish import sector_rs
    calls = {}
    def fake_ratings(*, data_root, allow_compute, max_age_hours=20.0):
        calls['allow_compute'] = allow_compute
        return {'generated_at': '2026-09-01T08:00:00', 'entries': {'017670': {'rs_rating': 82}}}
    monkeypatch.setattr(sector_rs, 'get_rs_ratings', fake_ratings)
    monkeypatch.setattr(sector_rs, 'score_rs_adjustment',
                        lambda e: {'rs_rating': (e or {}).get('rs_rating'), 'tag': 'leader'})
    out = db._src_sector_rs('017670')
    assert out['stance'] == 'positive' and out['detail']['rs_rating'] == 82
    assert calls['allow_compute'] is False                   # 요청 경로에서 재계산 금지


def test_risk_flags_blacklisted_is_negative(monkeypatch):
    from app.services.mirofish import blacklist as bl_service
    from app.services.mirofish import credit_balance as cb_service
    monkeypatch.setattr(bl_service, 'is_blacklisted', lambda s, allow_fetch=False: {
        'listed': True, 'categories': ['투자경고'], 'risk_level': 'hard_block',
        'fetched_at': '2026-09-01T00:00:00'})
    monkeypatch.setattr(cb_service, 'get_credit_entry', lambda s, allow_fetch=False: None)
    out = db._src_risk_flags('017670')
    assert out['stance'] == 'negative' and 'KIND' in out['detail']['flags'][0]


def test_risk_flags_clean_is_neutral_information(monkeypatch):
    from app.services.mirofish import blacklist as bl_service
    from app.services.mirofish import credit_balance as cb_service
    monkeypatch.setattr(bl_service, 'is_blacklisted', lambda s, allow_fetch=False: {
        'listed': False, 'categories': [], 'risk_level': 'none',
        'fetched_at': '2026-09-01T00:00:00'})
    monkeypatch.setattr(cb_service, 'get_credit_entry', lambda s, allow_fetch=False: {'ratio': 3.1})
    out = db._src_risk_flags('017670')
    assert out['stance'] == 'neutral' and out['detail']['flags'] == []


# ─── 감산 재조정 + 통합 ─────────────────────────────────────

def test_detection_history_gaps_collapse_into_one_penalty():
    signals = [
        {'source': 'price', 'stance': 'positive', 'grade': 'A'},
        {'source': 'flow', 'stance': 'positive', 'grade': 'A'},
    ]
    gaps = ['claw', 'jongga', 'scanner', 'detection', 'tradingagents', 'paper', 'observation']
    cap, reasons = db.compute_confidence_cap(
        signals, data_gaps=gaps, phase=None,
        agreement={'verdict': 'aligned'}, regime_conflict=False, verification=None)
    history_reasons = [r for r in reasons if '검출 이력' in r]
    assert len(history_reasons) == 1                          # 7개 개별 감산 → 1회 합산
    # 보편 근거 2개(A) 확보 → 예전 SKT(10%)보다 확실히 높은 상한
    assert cap >= 0.5


def test_brief_for_undetected_symbol_uses_universal_sources(monkeypatch):
    import app.services.mirofish.alpha_scanner as alpha_scanner
    from app.services.mirofish import live_data

    monkeypatch.setattr(db, 'resolve_symbol', lambda raw: ('017670', 'SK텔레콤'))
    monkeypatch.setattr(alpha_scanner, '_load_price_history_cached',
                        lambda: {'017670': _closes_rows([100 + i for i in range(80)])})
    monkeypatch.setattr(live_data, 'load_kis_snapshot', lambda resolved: {
        'found': True, 'quote': {'price': 55000, 'change_pct': 1.0},
        'investor': {'foreign_net_value': 10, 'institution_net_value': 5}})
    # 검출계열·기타 소스는 전부 공백으로
    for name in ('claw', 'jongga', 'scanner', 'detection', 'tradingagents', 'paper', 'observation'):
        monkeypatch.setitem(db.SOURCE_READERS, name, lambda code: None)
    monkeypatch.setitem(db.SOURCE_READERS, 'sector_rs', lambda code: None)
    monkeypatch.setitem(db.SOURCE_READERS, 'risk', lambda code: None)
    monkeypatch.setattr(db, '_read_news', lambda code: {'count': 0, 'items': []})
    monkeypatch.setattr(db, '_read_regime', lambda: {})

    out = db.build_decision_brief('017670')
    sources = [s['source'] for s in out['signals']]
    assert 'price' in sources and 'flow' in sources
    assert out['strong_evidence'] >= 2                        # A급 보편 근거 2개
    assert out['status'] != 'avoid_data_gap'
    assert out['confidence_cap'] > 0.10                       # SKT 사례(10%) 탈출

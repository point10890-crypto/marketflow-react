# -*- coding: utf-8 -*-
"""L4 기계적 검증의 실경로 연결 — 모듈 존재가 아니라 실제로 호출되는지 검증한다.

경로: analysts(LLM 리포트) → number_guard shadow 검증 → 딥검증 레코드 →
      decision_brief 신뢰 상한 감산.
shadow 원칙: 검증 실패해도 리포트를 폐기하지 않는다(관측 먼저). 정책 전환은 표본 축적 후.
"""
from app.services.mirofish import number_guard
from app.services.mirofish.tradingagents import analysts


# ─── 번들 평탄화 (중첩 수집기 구조 → 대조 가능한 수치 사전) ──

def test_flatten_numeric_collects_nested_values():
    flat = number_guard.flatten_numeric({
        'technical': {'chg_pct': 8.4, 'rsi': 64.4},
        'rs': {'rating': 95},
        'name': '삼성전자',
        'nested': {'deep': {'price': 12500}},
    })
    assert flat['technical.chg_pct'] == 8.4
    assert flat['rs.rating'] == 95
    assert flat['nested.deep.price'] == 12500
    assert 'name' not in flat  # 문자열은 대조 대상이 아니다


def test_flatten_numeric_ignores_booleans_and_none():
    flat = number_guard.flatten_numeric({'ok': True, 'missing': None, 'v': 3.0})
    assert flat == {'v': 3.0}


def test_flatten_numeric_preserves_watermark():
    flat = number_guard.flatten_numeric({'source_watermark': '2026-08-29T00:00:00+09:00',
                                         'x': 1.0})
    assert flat['source_watermark'] == '2026-08-29T00:00:00+09:00'


# ─── analysts shadow 검증 ───────────────────────────────────

BUNDLE = {'technical': {'chg_pct': 8.4}, 'rs': {'rating': 95}}


def test_llm_report_gets_shadow_verification(monkeypatch):
    """LLM 리포트에 검증 결과가 첨부되고, 실패해도 폐기되지 않는다."""
    def fake_llm(role, bundle):
        return {'role': role, 'title': 't', 'summary': '무려 99.9% 급등했다',
                'stance': 'bullish', 'score': 30.0, 'evidence': [], 'method': 'llm'}

    monkeypatch.setattr(analysts, '_llm_report', fake_llm)
    reports = analysts.run_analysts(BUNDLE, use_llm=True)
    assert reports, '리포트가 있어야 한다'
    first = reports[0]
    assert 'number_verification' in first
    assert first['number_verification']['contradicted'] >= 1
    assert first['method'] == 'llm', 'shadow 단계에서는 폐기하지 않는다'


def test_rule_report_is_not_verified(monkeypatch):
    """결정론 규칙 산출은 환각 대상이 아니므로 검증하지 않는다."""
    monkeypatch.setattr(analysts, '_llm_report', lambda role, bundle: None)
    reports = analysts.run_analysts(BUNDLE, use_llm=True)
    assert all(r['method'] == 'rule' for r in reports)
    assert all('number_verification' not in r for r in reports)


def test_verification_survives_bad_bundle(monkeypatch):
    def fake_llm(role, bundle):
        return {'role': role, 'title': 't', 'summary': '+8.4% 상승',
                'stance': 'bullish', 'score': 10.0, 'evidence': [], 'method': 'llm'}

    monkeypatch.setattr(analysts, '_llm_report', fake_llm)
    reports = analysts.run_analysts(None, use_llm=True)  # 번들 없음
    assert reports[0]['number_verification']['unverified'] >= 1


# ─── 집계: 리포트들 → 딥검증 레코드 요약 ────────────────────

def test_aggregate_verification_sums_reports():
    agg = number_guard.aggregate_verification([
        {'number_verification': {'verified': 2, 'unverified': 1, 'contradicted': 0}},
        {'number_verification': {'verified': 1, 'unverified': 0, 'contradicted': 2}},
        {'method': 'rule'},  # 검증 없음 — 무시
    ])
    assert agg == {'verified': 3, 'unverified': 1, 'contradicted': 2}


def test_aggregate_verification_returns_none_without_data():
    assert number_guard.aggregate_verification([{'method': 'rule'}]) is None


# ─── decision_brief 로의 전달 ───────────────────────────────

def test_decision_brief_applies_tradingagents_verification(monkeypatch):
    from app.services.mirofish import decision_brief as db

    for name in db.SOURCE_READERS:
        monkeypatch.setitem(db.SOURCE_READERS, name, lambda s: None)
    monkeypatch.setitem(db.SOURCE_READERS, 'claw', lambda s: {
        'stance': 'positive', 'grade': 'A', 'as_of': None, 'detail': {}})
    monkeypatch.setitem(db.SOURCE_READERS, 'jongga', lambda s: {
        'stance': 'positive', 'grade': 'A', 'as_of': None, 'detail': {}})
    monkeypatch.setitem(db.SOURCE_READERS, 'tradingagents', lambda s: {
        'stance': 'positive', 'grade': 'B', 'as_of': None,
        'detail': {'verdict': 'BUY',
                   'number_verification': {'verified': 1, 'unverified': 4, 'contradicted': 0}}})
    monkeypatch.setattr(db, '_read_regime', lambda: {'phase': 'uptrend_broadening',
                                                     'gate_status': 'GREEN', 'conflict': False})
    out = db.build_decision_brief('005930')
    assert out['verification'] == {'verified': 1, 'unverified': 4, 'contradicted': 0}
    assert any('unverified' in r for r in out['cap_reasons'])


# ─── L1(뉴스 원장) → L5(판단 브리프) 연결 ───────────────────

def test_decision_brief_attaches_news_context(monkeypatch):
    """뉴스는 방향 판정이 아니라 맥락이다 — signals 를 오염시키지 않고 별도로 붙는다."""
    from app.services.mirofish import decision_brief as db
    from app.services.omni import ledger as omni_ledger

    for name in db.SOURCE_READERS:
        monkeypatch.setitem(db.SOURCE_READERS, name, lambda s: None)
    monkeypatch.setitem(db.SOURCE_READERS, 'claw', lambda s: {
        'stance': 'positive', 'grade': 'A', 'as_of': None, 'detail': {}})
    monkeypatch.setattr(db, '_read_regime', lambda: {'phase': 'uptrend_broadening',
                                                     'gate_status': 'GREEN', 'conflict': False})
    monkeypatch.setattr(omni_ledger, 'events_for_symbol', lambda code, limit=5: [
        {'title': '삼성전자 자사주 매입', 'link': 'https://n/1', 'source': 'yonhap',
         'grade': 'B', 'score': 3.0, 'published_ts': '2026-08-29T09:00:00+09:00',
         'summary': '요약', 'symbols': [code], 'themes': [], 'corroboration': 2},
    ])

    out = db.build_decision_brief('005930')
    assert out['news']['count'] == 1
    assert out['news']['items'][0]['title'] == '삼성전자 자사주 매입'
    # 뉴스는 방향 신호가 아니므로 합의 계산에 끼어들지 않는다
    assert all(s['source'] != 'news' for s in out['signals'])
    assert out['agreement']['active'] == 1


def test_decision_brief_survives_missing_news_ledger(monkeypatch):
    from app.services.mirofish import decision_brief as db
    from app.services.omni import ledger as omni_ledger

    for name in db.SOURCE_READERS:
        monkeypatch.setitem(db.SOURCE_READERS, name, lambda s: None)
    monkeypatch.setattr(db, '_read_regime', lambda: {'phase': None, 'gate_status': None,
                                                     'conflict': False})

    def boom(code, limit=5):
        raise RuntimeError('ledger missing')

    monkeypatch.setattr(omni_ledger, 'events_for_symbol', boom)
    out = db.build_decision_brief('005930')
    assert out['news']['count'] == 0
    assert 'news' in out['errors']
    assert out['status'] in db.ALLOWED_STATUS


# ─── 마지막 홉: 딥검증 레코드가 검증 결과를 실어 나르는가 ───
# 종단 검증(2026-08-29)에서 decision_brief 의 verification 이 None 이었다.
# analysts 는 검증을 첨부했으나 레코드·요약이 그것을 전달하지 않아 끊겨 있었다.

def test_deepverify_record_carries_verification():
    from app.services.mirofish import scanner_deepverify as sd

    ta = {
        'id': 'ta_x', 'method': 'llm',
        'verdict': {'verdict': 'BUY', 'confidence': 70, 'strong_buy': False,
                    'regime': None, 'regime_adjustment': {}},
        'analyst_reports': [
            {'method': 'llm', 'number_verification': {'verified': 2, 'unverified': 1, 'contradicted': 0}},
            {'method': 'llm', 'number_verification': {'verified': 1, 'unverified': 0, 'contradicted': 1}},
        ],
    }
    rec = sd._build_record({'candidate': {'symbol': '005930', 'display_name': '삼성전자'}},
                           {'generated_at': '2026-08-29T00:00:00+09:00'}, None, ta)
    assert rec['number_verification'] == {'verified': 3, 'unverified': 1, 'contradicted': 1}


def test_deepverify_record_without_verification_is_none():
    from app.services.mirofish import scanner_deepverify as sd

    ta = {'id': 'ta_y', 'method': 'rule', 'verdict': {'verdict': 'HOLD'},
          'analyst_reports': [{'method': 'rule'}]}
    rec = sd._build_record({'candidate': {'symbol': '005930'}}, {}, None, ta)
    assert rec['number_verification'] is None


def test_feed_summary_passes_verification_through():
    from app.services.mirofish import scanner_deepverify as sd

    summary = sd._feed_summary({
        'verdict': 'BUY', 'confidence': 70, 'strong_buy': False, 'method': 'llm',
        'number_verification': {'verified': 3, 'unverified': 1, 'contradicted': 0},
    })
    assert summary['number_verification'] == {'verified': 3, 'unverified': 1, 'contradicted': 0}

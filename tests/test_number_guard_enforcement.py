# -*- coding: utf-8 -*-
"""number_guard enforce — 구독자 노출 LLM 텍스트 (Phase 1-B3).

브리핑 섹션·주도주 AI 사유에 나오는 숫자는 수집 원천과 대조된다. enforce 정책에서
모순은 본문을 정직한 짧은 문구로 교체하고, shadow 정책에서는 집계만 남긴다.
검증 자체의 실패는 생성 경로를 절대 막지 않는다.
"""
from __future__ import annotations

import pytest

from app.services.mirofish import number_guard as ng


# ─── 헬퍼 ────────────────────────────────────────────────────

def test_guard_text_against_enforce_rejects_contradiction_and_shadow_keeps_it():
    truth = {'indices': {'SPY': {'change_pct': 1.2, 'price': 5000.0}}}
    text = 'S&P 500 은 전일 대비 3.5% 상승 마감했다.'

    enforce = ng.guard_text_against(text, truth, policy='enforce')
    assert enforce.contradicted == 1
    assert enforce.accepted is False and enforce.should_drop is True

    shadow = ng.guard_text_against(text, truth, policy='shadow')
    assert shadow.contradicted == 1
    assert shadow.accepted is True and shadow.should_drop is False
    assert shadow.to_dict()['policy'] == 'shadow'


def test_guard_text_against_tolerates_display_rounding_and_negative_wording():
    truth = {'SPY': {'change_pct': 1.23}, 'QQQ': {'change_pct': -0.84}}
    ok = ng.guard_text_against('S&P 500 1.2% 상승, 나스닥 0.8% 하락', truth, policy='enforce')
    assert ok.contradicted == 0 and ok.verified == 2 and ok.accepted is True


def test_guard_text_against_never_raises(monkeypatch):
    monkeypatch.setattr(ng, 'guard_output', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom')))
    result = ng.guard_text_against('3.5% 상승', {'change_pct': 1.0}, policy='enforce')
    assert result.accepted is True and result.error and 'boom' in result.error


def test_resolve_policy_reads_env_and_defaults(monkeypatch):
    monkeypatch.delenv('NUMBER_GUARD_POLICY', raising=False)
    assert ng.resolve_policy() == 'enforce'
    monkeypatch.setenv('NUMBER_GUARD_POLICY', 'shadow')
    assert ng.resolve_policy() == 'shadow'
    monkeypatch.setenv('NUMBER_GUARD_POLICY', 'nonsense')
    assert ng.resolve_policy(default='shadow') == 'shadow'
    assert ng.resolve_policy('ENFORCE') == 'enforce'


# ─── 브리핑 ──────────────────────────────────────────────────

def _morning_data():
    return {
        'indices': {'SPY': {'name': 'S&P 500', 'price': 5000.0, 'change': 1.2},
                    'QQQ': {'name': 'NASDAQ 100', 'price': 17000.0, 'change': -0.5}},
        'vix': {'value': 15.2, 'level': 'LOW'},
        'fear_greed': {'score': 62, 'label': 'Greed'},
    }


def _llm_result():
    return {
        'title': '9/2 조간브리핑',
        'summary': 'S&P 500 이 1.2% 상승하며 위험선호가 이어졌다.',
        'sections': [
            {'heading': '🇺🇸 미국 시장', 'content': 'S&P 500 은 전일 대비 3.5% 상승 마감했다.'},
            {'heading': '📊 지표', 'content': 'VIX 15.2, Fear & Greed 62 로 탐욕 구간.'},
        ],
        'market_sentiment': 'BULLISH', 'confidence': 0.7, 'key_events': [], 'sources': [],
    }


def test_briefing_enforce_replaces_contradicted_section_only(monkeypatch):
    from briefing_generator import BriefingGenerator

    monkeypatch.setenv('NUMBER_GUARD_POLICY', 'enforce')
    gen = BriefingGenerator()
    result = _llm_result()
    gen._apply_number_guard(result, _morning_data(), kind='morning')

    assert result['sections'][0]['content'] == ng.CONTRADICTION_NOTE
    assert result['sections'][0]['number_guard_dropped'] is True
    assert result['sections'][1]['content'].startswith('VIX 15.2')   # 검증된 섹션은 유지
    assert result['summary'].startswith('S&P 500 이 1.2%')             # 검증된 요약 유지
    ng_meta = result['number_guard']
    assert ng_meta['policy'] == 'enforce'
    assert ng_meta['checked'] == 3 and ng_meta['contradicted'] == 1
    assert ng_meta['dropped'] == ['🇺🇸 미국 시장']


def test_briefing_shadow_keeps_section_but_records_verdict(monkeypatch):
    from briefing_generator import BriefingGenerator

    monkeypatch.setenv('NUMBER_GUARD_POLICY', 'shadow')
    gen = BriefingGenerator()
    result = _llm_result()
    gen._apply_number_guard(result, _morning_data(), kind='morning')

    assert result['sections'][0]['content'] == 'S&P 500 은 전일 대비 3.5% 상승 마감했다.'
    assert 'number_guard_dropped' not in result['sections'][0]
    assert result['number_guard'] == {
        'policy': 'shadow', 'checked': 3, 'contradicted': 1, 'dropped': [],
        'truth_fields': result['number_guard']['truth_fields'],
    }


def test_briefing_summary_contradiction_falls_back_to_deterministic_summary(monkeypatch):
    from briefing_generator import BriefingGenerator

    monkeypatch.setenv('NUMBER_GUARD_POLICY', 'enforce')
    gen = BriefingGenerator()
    result = _llm_result()
    result['summary'] = 'S&P 500 이 4.0% 급등하며 마감했다.'
    gen._apply_number_guard(result, _morning_data(), kind='morning')

    assert result['summary'] == gen._fallback_morning(_morning_data())['summary']
    assert 'summary' in result['number_guard']['dropped']


def test_briefing_closing_truth_covers_jongga_signals(monkeypatch):
    from briefing_generator import BriefingGenerator

    monkeypatch.setenv('NUMBER_GUARD_POLICY', 'enforce')
    gen = BriefingGenerator()
    data = {'jongga': {'total': 1, 'signals': [
        {'name': '삼성전자', 'code': '005930', 'grade': 'A', 'total': 12,
         'change_pct': 7.5, 'trading_value': 600_0000_0000, 'reason': ''}]},
        'kr_gate': {'status': 'RISK_ON', 'score': 70, 'label': 'RISK_ON', 'reasons': []}}
    result = {'summary': '삼성전자 7.5% 상승, 종가베팅 1개.',
              'sections': [{'heading': '🔥 종가베팅', 'content': '삼성전자는 12.0% 급등, 거래대금 600억.'}]}
    gen._apply_number_guard(result, data, kind='closing')

    assert result['sections'][0]['content'] == ng.CONTRADICTION_NOTE
    assert result['summary'] == '삼성전자 7.5% 상승, 종가베팅 1개.'


def test_briefing_guard_failure_never_breaks_generation(monkeypatch):
    from briefing_generator import BriefingGenerator

    gen = BriefingGenerator()
    monkeypatch.setattr(BriefingGenerator, '_number_guard_truth',
                        staticmethod(lambda data: (_ for _ in ()).throw(RuntimeError('boom'))))
    result = _llm_result()
    gen._apply_number_guard(result, _morning_data(), kind='morning')
    assert result['sections'][0]['content'] == 'S&P 500 은 전일 대비 3.5% 상승 마감했다.'
    assert result['number_guard']['policy'] == 'error'


# ─── 주도주 enricher ───────────────────────────────────────────

ROW = {'code': '005930', 'name': '삼성전자', 'grade': 'S', 'price': 80000,
       'change_pct': 7.5, 'trading_value': 600_0000_0000, 'trading_value_eok': 600, 'volume_ratio': 320.0}


def test_enricher_enforce_replaces_contradicted_reason(monkeypatch):
    from app.services import leading_enricher as le

    monkeypatch.setenv('NUMBER_GUARD_POLICY', 'enforce')
    out = le._guard_ai_reason({'ai_score': 3, 'ai_reason': 'HBM 호재로 12% 급등', 'themes': ['HBM']}, ROW)
    assert out['ai_reason'] == le.AI_REASON_GUARD_FALLBACK
    assert out['ai_score'] == 3 and out['themes'] == ['HBM']
    assert out['ai_reason_guard']['contradicted'] == 1 and out['ai_reason_guard']['policy'] == 'enforce'


def test_enricher_keeps_consistent_or_number_free_reason(monkeypatch):
    from app.services import leading_enricher as le

    monkeypatch.setenv('NUMBER_GUARD_POLICY', 'enforce')
    ok = le._guard_ai_reason({'ai_score': 2, 'ai_reason': '7.5% 상승, HBM 수주', 'themes': []}, ROW)
    assert ok['ai_reason'] == '7.5% 상승, HBM 수주'
    assert ok['ai_reason_guard']['contradicted'] == 0

    plain = le._guard_ai_reason({'ai_score': 2, 'ai_reason': 'HBM 수주 기대감', 'themes': []}, ROW)
    assert plain['ai_reason'] == 'HBM 수주 기대감'
    empty = le._guard_ai_reason({'ai_score': 0, 'ai_reason': '', 'themes': []}, ROW)
    assert empty == {'ai_score': 0, 'ai_reason': '', 'themes': []}


def test_enricher_shadow_keeps_reason(monkeypatch):
    from app.services import leading_enricher as le

    monkeypatch.setenv('NUMBER_GUARD_POLICY', 'shadow')
    out = le._guard_ai_reason({'ai_score': 3, 'ai_reason': 'HBM 호재로 12% 급등', 'themes': []}, ROW)
    assert out['ai_reason'] == 'HBM 호재로 12% 급등'
    assert out['ai_reason_guard']['contradicted'] == 1 and out['ai_reason_guard']['policy'] == 'shadow'


def test_enrich_stocks_routes_llm_reason_through_guard(monkeypatch):
    from app.services import leading_enricher as le

    monkeypatch.setenv('NUMBER_GUARD_POLICY', 'enforce')
    monkeypatch.setattr(le, '_analyze_news_llm',
                        lambda name, code, chg: {'ai_score': 3, 'ai_reason': '실적 기대 12% 급등', 'themes': []})
    monkeypatch.setattr(le, '_count_consecutive_days', lambda code: 0)
    monkeypatch.setattr(le.time, 'sleep', lambda s: None)
    with le._enrichment_lock:
        le._enrichment_cache.clear()

    enriched = le.enrich_stocks([dict(ROW)])
    assert enriched['005930']['ai_reason'] == le.AI_REASON_GUARD_FALLBACK
    assert enriched['005930']['ai_reason_guard']['contradicted'] == 1
    with le._enrichment_lock:
        le._enrichment_cache.clear()

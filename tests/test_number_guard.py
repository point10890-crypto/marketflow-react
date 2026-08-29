# -*- coding: utf-8 -*-
"""L4 기계적 검증 — LLM 산출 수치를 수집기 원천과 대조한다.

프로젝트 원칙 "LLM 은 숫자를 소유하지 않는다"를 규칙 문장이 아니라 코드로 강제한다.
LLM 이 만든 값은 진실이 아니며, 수집기가 가져온 번들 값만 대조 기준이 된다.
"""
import pytest

from app.services.mirofish import number_guard as ng


# ─── 수치 추출 ──────────────────────────────────────────────

def test_extracts_percent_and_plain_numbers():
    claims = ng.extract_claims('대우건설은 +8.4% 상승했고 거래대금은 3844억 수준이다.')
    values = [c['value'] for c in claims]
    assert 8.4 in values
    assert 3844 in values


def test_extracts_comma_separated_and_negative():
    claims = ng.extract_claims('종가 12,500원, 전일 대비 -3.2%')
    values = [c['value'] for c in claims]
    assert 12500 in values
    assert -3.2 in values


def test_ignores_years_and_ordinals():
    """2026 같은 연도·회차는 수치 주장으로 보지 않는다(오탐 방지)."""
    claims = ng.extract_claims('2026년 8월 기준 제1236회 분석')
    assert claims == []


def test_extraction_records_unit_and_context():
    claims = ng.extract_claims('상승률 +8.4% 기록')
    assert claims[0]['unit'] == 'percent'
    assert '8.4' in claims[0]['raw']


# ─── 원천 대조 ──────────────────────────────────────────────

BUNDLE = {
    'chg_pct': 8.4,
    'trading_value_eok': 3844,
    'current_price': 12500,
    'source_watermark': '2026-08-28T15:30:00+09:00',
}


def test_verifies_exact_match():
    verdict = ng.verify_claims(ng.extract_claims('+8.4% 상승'), BUNDLE)
    assert verdict['contradicted'] == []
    assert verdict['verified'][0]['matched_field'] == 'chg_pct'


def test_allows_rounding_tolerance():
    """표기 반올림 차이(상대 1% 이내)는 검증으로 통과시킨다."""
    verdict = ng.verify_claims(ng.extract_claims('8.42% 상승'), BUNDLE)
    assert verdict['verified']
    assert verdict['contradicted'] == []


def test_flags_contradiction_beyond_tolerance():
    verdict = ng.verify_claims(ng.extract_claims('무려 25.0% 급등'), BUNDLE)
    assert verdict['contradicted']
    assert verdict['contradicted'][0]['value'] == 25.0


def test_unmatched_number_is_unverified_not_contradiction():
    """번들에 대응 필드가 아예 없는 수치는 모순이 아니라 미검증이다."""
    verdict = ng.verify_claims(ng.extract_claims('PER 은 14.7 수준'), BUNDLE)
    assert verdict['unverified']
    assert verdict['contradicted'] == []


# ─── 기준일(lookahead) 검증 ────────────────────────────────

def test_future_reference_date_is_contradiction():
    verdict = ng.verify_claims(
        ng.extract_claims('9.9% 상승'), BUNDLE,
        as_of='2026-08-29T09:00:00+09:00')
    assert any(c.get('reason') == 'lookahead' for c in verdict['contradicted'])


def test_past_reference_date_passes_lookahead_check():
    verdict = ng.verify_claims(
        ng.extract_claims('+8.4% 상승'), BUNDLE,
        as_of='2026-08-28T15:00:00+09:00')
    assert not any(c.get('reason') == 'lookahead' for c in verdict['contradicted'])


# ─── 정책 적용 ──────────────────────────────────────────────

def test_guard_accepts_clean_output():
    accepted, verdict = ng.guard_output('+8.4% 상승, 거래대금 3844억', BUNDLE)
    assert accepted is True
    assert verdict['accepted'] is True
    assert verdict['schema_version'] == ng.SCHEMA_VERSION


def test_guard_discards_on_contradiction():
    accepted, verdict = ng.guard_output('무려 25.0% 급등했다', BUNDLE)
    assert accepted is False
    assert verdict['policy'] == 'discard_on_contradiction'


def test_guard_accepts_but_flags_unverified():
    accepted, verdict = ng.guard_output('PER 14.7 수준으로 보인다', BUNDLE)
    assert accepted is True
    assert verdict['unverified'] >= 1


def test_guard_handles_empty_text():
    accepted, verdict = ng.guard_output('', BUNDLE)
    assert accepted is True
    assert verdict['verified'] == 0


def test_guard_never_raises_on_malformed_bundle():
    accepted, verdict = ng.guard_output('+8.4% 상승', None)
    assert accepted is True  # 대조 불가는 폐기 사유가 아니다
    assert verdict['unverified'] >= 1


# ─── 신뢰 상한 연동 ─────────────────────────────────────────

def test_cap_penalty_scales_with_unverified_ratio():
    clean = {'verified': 4, 'unverified': 0, 'contradicted': 0}
    dirty = {'verified': 1, 'unverified': 3, 'contradicted': 0}
    assert ng.cap_penalty(clean) == 0.0
    assert ng.cap_penalty(dirty) > 0.0


def test_cap_penalty_is_bounded():
    worst = {'verified': 0, 'unverified': 50, 'contradicted': 5}
    assert ng.cap_penalty(worst) <= ng.MAX_CAP_PENALTY

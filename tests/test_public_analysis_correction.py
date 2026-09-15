from scripts.repair_public_analysis import correct_content, MARKER


def test_legacy_correction_preserves_observations_and_is_idempotent():
    html = '''<p>종가베팅 V2</p><h2>예제기업</h2><p>104,600원 · +15.33% 점수 10/17</p>
<p>📰 원문 없는 뉴스</p><p>📰 <a href="https://example.com">원문 있는 뉴스</a></p>
<h1>💵 매매 규칙</h1><p>손절 -3%, 목표 +5%</p><hr />
<h1>⚠️ 주의</h1><p>손절선 깨지면 즉시 정리 — 반등 기다리지 말 것.</p>
<p>AI Consensus 태그는 Gemini+GPT-4o 교차검증 통과.</p>
<p>2026-09-15 장마감 · 자동 생성</p>'''
    corrected = correct_content('[종가베팅] 기록', html)
    assert '104,600원 · +15.33% 점수 10/17' in corrected
    assert '원문 없는 뉴스' not in corrected
    assert 'https://example.com' in corrected
    assert '손절 -3%' not in corrected
    assert '즉시 정리' not in corrected
    assert MARKER in corrected
    assert correct_content('[종가베팅] 기록', corrected) == corrected


def test_non_matching_posts_are_untouched():
    html = '<p>원문</p>'
    assert correct_content('회원의 분석', html) == html
    assert correct_content('[종가베팅] 회원의 분석', html) == html

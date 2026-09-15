from scripts.post_daily_analysis import _build_content


def test_public_analysis_does_not_invent_provenance_or_trade_instructions():
    _, html = _build_content({
        'date': '2026-09-15', 'by_grade': {'S': 1},
        'signals': [{'stock_name': '예제기업', 'stock_code': '123456', 'grade': 'S',
                     'news_items': [{'title': '원문 없는 뉴스'}]}],
    }, {})
    assert '123456' in html
    assert '확인 불가' in html
    assert '원문 없는 뉴스' not in html
    assert '장마감 · 자동 생성' not in html
    assert 'Gemini+GPT-4o 교차검증 통과' not in html
    assert '손절선 깨지면 즉시 정리' not in html
    assert '매수가 <strong>-3%' not in html
    assert '시장 구분' in html
    assert '/guide/signal-verification-worked-example' in html


def test_public_analysis_links_and_escapes_source_material():
    _, html = _build_content({
        'date': '2026-09-15', 'by_grade': {'A': 1},
        'signals': [{'stock_name': '<img src=x onerror=alert(1)>', 'stock_code': '123456',
            'grade': 'A', 'current_price': 100, 'change_pct': 2, 'score': {'total': 8},
            'news_items': [{'title': '공시 <확인>', 'url': 'https://example.com/news?id=1&x=2'}]}],
    }, {})
    assert '<img src=x onerror' not in html
    assert '공시 &lt;확인&gt;' in html
    assert 'href="https://example.com/news?id=1&amp;x=2"' in html
    assert '100원' in html


def test_public_analysis_rejects_script_news_urls():
    _, html = _build_content({'date': '2026-09-15', 'signals': [
        {'stock_name': '예제', 'news_items': [{'title': '위험 링크', 'url': 'javascript:alert(1)'}]},
    ]}, {})
    assert 'javascript:' not in html
    assert '위험 링크' not in html

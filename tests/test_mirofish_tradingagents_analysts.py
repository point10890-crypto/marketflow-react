"""Unit tests for the four-analyst report layer.

Covers the deterministic rule scorer (the math later tasks rely on) and the
per-role LLM-with-rule fallback contract.
"""

from app.services.mirofish.tradingagents import analysts

BUNDLE = {
    'target': '삼성전자', 'symbol': '005930', 'market': 'KOSPI', 'display_name': '삼성전자',
    'price': {'found': True, 'price': 70000, 'change_pct': 4.0, 'date': '2026-07-17'},
    'corpus': '삼성전자 대규모 수주 계약 체결. 신고가 경신.',
    'technical': {'trend': 'up', 'ma_aligned': True},
    'rs': {'rs_rating': 90}, 'fundamentals': {'trailingPE': 12.0}, 'errors': {},
}


def test_rule_analysts_produce_four_reports():
    reports = analysts.run_analysts(BUNDLE, use_llm=False)
    assert [r['role'] for r in reports] == ['fundamentals', 'news', 'sentiment', 'technical']
    assert all(r['method'] == 'rule' for r in reports)
    tech = next(r for r in reports if r['role'] == 'technical')
    assert tech['stance'] == 'bullish' and tech['score'] > 0


def test_rule_news_keyword_scoring():
    bearish = dict(BUNDLE, corpus='소송 제기, 대규모 적자 전환, 유상증자 결정')
    reports = analysts.run_analysts(bearish, use_llm=False)
    news = next(r for r in reports if r['role'] == 'news')
    assert news['stance'] == 'bearish'
    assert news['score'] == -30.0


def test_technical_score_math_is_exact():
    reports = analysts.run_analysts(BUNDLE, use_llm=False)
    tech = next(r for r in reports if r['role'] == 'technical')
    # trend up (+40) + ma_aligned (+20) + rs 90>=80 (+30) = 90
    assert tech['score'] == 90.0


def test_technical_reads_real_vocab_and_derives_ma_alignment():
    real = dict(
        BUNDLE,
        technical={'trend': 'bearish', 'indicators': {'sma5': 100, 'sma20': 110, 'sma60': 120}},
        rs={'rs_rating': 10},
    )
    reports = analysts.run_analysts(real, use_llm=False)
    tech = next(r for r in reports if r['role'] == 'technical')
    # trend bearish (-40) + not aligned (0) + rs 10<=20 (-30) = -70
    assert tech['score'] == -70.0
    assert tech['stance'] == 'bearish'


def test_sentiment_combines_news_and_change_pct():
    reports = analysts.run_analysts(BUNDLE, use_llm=False)
    sent = next(r for r in reports if r['role'] == 'sentiment')
    # news +30 + change 4.0*3=12 (clamp +-30) = 42
    assert sent['score'] == 42.0
    assert sent['stance'] == 'bullish'


def test_fundamentals_no_data_is_neutral():
    no_fund = dict(BUNDLE, fundamentals={})
    reports = analysts.run_analysts(no_fund, use_llm=False)
    fund = next(r for r in reports if r['role'] == 'fundamentals')
    assert fund['score'] == 0.0
    assert fund['stance'] == 'neutral'
    assert any('데이터 부족' in e for e in fund['evidence'])


def test_report_schema_is_complete():
    reports = analysts.run_analysts(BUNDLE, use_llm=False)
    required = {'role', 'title', 'summary', 'stance', 'score', 'evidence', 'method'}
    for r in reports:
        assert required <= set(r)
        assert isinstance(r['score'], float) and -100 <= r['score'] <= 100
        assert r['stance'] in ('bullish', 'bearish', 'neutral')
        assert isinstance(r['evidence'], list)
        assert isinstance(r['summary'], str) and r['summary']


def test_llm_used_when_available_else_rule_per_role(monkeypatch):
    def fake_generate(prompt, **kwargs):
        # Only the fundamentals prompt returns valid JSON; others fail → rule.
        if '펀더멘털' in (kwargs.get('system') or '') or 'PER' in prompt or 'trailingPE' in prompt:
            return '{"title": "밸류에이션", "summary": "PER 12배로 저평가.", ' \
                   '"stance": "bullish", "score": 30, "evidence": ["PER 12"]}'
        return None

    monkeypatch.setattr(analysts.llm_client, 'generate_text', fake_generate)
    reports = analysts.run_analysts(BUNDLE, use_llm=True)
    by_role = {r['role']: r for r in reports}
    assert by_role['fundamentals']['method'] == 'llm'
    assert by_role['fundamentals']['summary'] == 'PER 12배로 저평가.'
    assert by_role['news']['method'] == 'rule'

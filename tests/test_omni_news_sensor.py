# -*- coding: utf-8 -*-
"""옴니소스 O1 — 뉴스 RSS 상시 센서 + 결정론 깔때기 + 사건 원장.

설계: docs/superpowers/specs/2026-08-24-omnisource-sensor-design.md
핵심 규율
    - 원문 본문을 저장하지 않는다(제목·요약≤500자·링크·해시만).
    - 외부 텍스트는 데이터이지 지시가 아니다 — 센서에 발송·주문·LLM 경로가 없다.
    - 1~2단은 전부 결정론(LLM 없음). 매칭 0건이면 즉시 폐기한다.
"""
import pytest

from app.services.omni import funnel, ledger


# ─── 0단: 중복 제거 ─────────────────────────────────────────

def test_content_hash_is_stable_for_same_item():
    a = funnel.content_hash('삼성전자 신고가', 'https://x.com/1')
    b = funnel.content_hash('삼성전자 신고가', 'https://x.com/1')
    assert a == b and len(a) == 64


def test_content_hash_differs_by_title_or_link():
    base = funnel.content_hash('제목', 'https://x.com/1')
    assert base != funnel.content_hash('다른 제목', 'https://x.com/1')
    assert base != funnel.content_hash('제목', 'https://x.com/2')


# ─── 1단: 결정론 매칭 ───────────────────────────────────────

UNIVERSE = {'005930': '삼성전자', '000660': 'SK하이닉스', '047040': '대우건설'}


def test_matches_symbol_by_company_name():
    hits = funnel.match_symbols('삼성전자, 신고가 경신', UNIVERSE)
    assert hits == ['005930']


def test_matches_symbol_by_ticker_digits():
    hits = funnel.match_symbols('종목코드 000660 관련 공시', UNIVERSE)
    assert '000660' in hits


def test_matches_multiple_symbols_without_duplication():
    hits = funnel.match_symbols('삼성전자와 SK하이닉스 동반 상승, 삼성전자 주도', UNIVERSE)
    assert sorted(hits) == ['000660', '005930']


def test_does_not_match_unrelated_text():
    assert funnel.match_symbols('오늘 날씨는 맑겠습니다', UNIVERSE) == []


def test_theme_matching_is_deterministic():
    themes = funnel.match_themes('정부, 원전 수출 지원 확대', {'원전': '전력기기'})
    assert themes == ['전력기기']


# ─── 2단: 중요도 스코어 ─────────────────────────────────────

def test_score_rewards_higher_source_grade():
    low = funnel.importance_score(symbols=['005930'], themes=[], grade='C', corroboration=1)
    high = funnel.importance_score(symbols=['005930'], themes=[], grade='A', corroboration=1)
    assert high > low


def test_score_rewards_multi_source_corroboration():
    single = funnel.importance_score(symbols=['005930'], themes=[], grade='B', corroboration=1)
    multi = funnel.importance_score(symbols=['005930'], themes=[], grade='B', corroboration=3)
    assert multi > single


def test_score_zero_without_any_match():
    assert funnel.importance_score(symbols=[], themes=[], grade='A', corroboration=5) == 0.0


# ─── 깔때기 통합 ────────────────────────────────────────────

def _item(title, link='https://n.example/1', summary='요약', source='yonhap', grade='B'):
    return {'title': title, 'link': link, 'summary': summary,
            'source': source, 'grade': grade, 'published_ts': '2026-08-29T09:00:00+09:00'}


def test_funnel_drops_items_with_no_match():
    kept = funnel.run_funnel([_item('오늘의 날씨 전망')], UNIVERSE, {})
    assert kept == []


def test_funnel_keeps_matched_item_with_score_and_hash():
    kept = funnel.run_funnel([_item('삼성전자 신고가 경신')], UNIVERSE, {})
    assert len(kept) == 1
    assert kept[0]['symbols'] == ['005930']
    assert kept[0]['score'] > 0
    assert len(kept[0]['content_hash']) == 64


def test_funnel_truncates_summary_and_drops_body():
    long_summary = '가' * 900
    kept = funnel.run_funnel([_item('삼성전자 실적', summary=long_summary)], UNIVERSE, {})
    assert len(kept[0]['summary']) <= funnel.SUMMARY_MAX
    assert 'body' not in kept[0] and 'content' not in kept[0]


def test_funnel_dedupes_same_item_across_sources_and_counts_corroboration():
    items = [_item('삼성전자 신고가', source='yonhap'),
             _item('삼성전자 신고가', source='hankyung')]
    kept = funnel.run_funnel(items, UNIVERSE, {})
    assert len(kept) == 1
    assert kept[0]['corroboration'] == 2


# ─── 사건 원장 ──────────────────────────────────────────────

@pytest.fixture()
def omni_db(tmp_path, monkeypatch):
    path = str(tmp_path / 'omni.db')
    monkeypatch.setattr(ledger, 'DB_PATH', path)
    return path


def test_ledger_roundtrip_and_dedupe(omni_db):
    event = {'content_hash': 'h' * 64, 'title': '삼성전자 신고가', 'summary': '요약',
             'link': 'https://n/1', 'source': 'yonhap', 'grade': 'B',
             'published_ts': '2026-08-29T09:00:00+09:00', 'symbols': ['005930'],
             'themes': [], 'score': 3.5, 'corroboration': 1}
    assert ledger.save_events([event]) == 1
    assert ledger.save_events([event]) == 0  # 같은 해시 재삽입 없음
    rows = ledger.recent_events(limit=5)
    assert rows[0]['title'] == '삼성전자 신고가'
    assert rows[0]['symbols'] == ['005930']


def test_ledger_query_by_symbol(omni_db):
    ledger.save_events([
        {'content_hash': 'a' * 64, 'title': 'A', 'summary': '', 'link': 'l1',
         'source': 's', 'grade': 'B', 'published_ts': '2026-08-29T09:00:00+09:00',
         'symbols': ['005930'], 'themes': [], 'score': 2.0, 'corroboration': 1},
        {'content_hash': 'b' * 64, 'title': 'B', 'summary': '', 'link': 'l2',
         'source': 's', 'grade': 'B', 'published_ts': '2026-08-29T09:00:00+09:00',
         'symbols': ['000660'], 'themes': [], 'score': 2.0, 'corroboration': 1},
    ])
    hits = ledger.events_for_symbol('005930', limit=10)
    assert len(hits) == 1 and hits[0]['title'] == 'A'


def test_ledger_never_stores_raw_body(omni_db):
    import sqlite3
    ledger.save_events([{'content_hash': 'c' * 64, 'title': 'T', 'summary': 'S',
                         'link': 'l', 'source': 's', 'grade': 'B',
                         'published_ts': '2026-08-29T09:00:00+09:00',
                         'symbols': ['005930'], 'themes': [], 'score': 1.0,
                         'corroboration': 1, 'body': '본문 전체'}])
    con = sqlite3.connect(omni_db)
    cols = {r[1] for r in con.execute('PRAGMA table_info(news_events)')}
    con.close()
    assert 'body' not in cols and 'content' not in cols


# ─── RSS 수집기 / 스윕 ──────────────────────────────────────

RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item><title>삼성전자 신고가 경신</title><link>https://n/1</link>
        <description>반도체 업황 개선 기대</description>
        <pubDate>Fri, 29 Aug 2026 09:00:00 +0900</pubDate></item>
  <item><title>오늘의 날씨</title><link>https://n/2</link>
        <description>전국 맑음</description></item>
</channel></rss>"""


def test_parses_rss_items():
    from app.services.omni import news_sensor
    items = news_sensor.parse_rss(RSS_XML, source='yonhap', grade='B')
    assert len(items) == 2
    assert items[0]['title'] == '삼성전자 신고가 경신'
    assert items[0]['link'] == 'https://n/1'
    assert items[0]['source'] == 'yonhap'


def test_parse_rss_tolerates_malformed_xml():
    from app.services.omni import news_sensor
    assert news_sensor.parse_rss('<rss><broken', source='s', grade='B') == []


def test_sweep_persists_only_matched_items(monkeypatch, omni_db):
    from app.services.omni import news_sensor
    monkeypatch.setattr(news_sensor, 'load_universe', lambda: UNIVERSE)
    monkeypatch.setattr(news_sensor, '_fetch', lambda url, timeout=10: RSS_XML)
    monkeypatch.setattr(news_sensor, 'active_sources',
                        lambda: [{'name': 'yonhap', 'url': 'https://x/rss', 'grade': 'B'}])

    result = news_sensor.run_news_sweep()
    assert result['fetched'] == 2
    assert result['kept'] == 1        # 날씨 기사는 1단에서 폐기
    assert result['saved'] == 1
    rows = ledger.recent_events(limit=5)
    assert rows[0]['symbols'] == ['005930']


def test_sweep_is_noop_when_killswitch_off(monkeypatch, omni_db):
    from app.services.omni import news_sensor
    monkeypatch.setenv('OMNI_ENABLED', '0')

    def explode(*_a, **_k):
        raise AssertionError('킬스위치가 꺼져 있으면 네트워크를 건드리면 안 된다')

    monkeypatch.setattr(news_sensor, '_fetch', explode)
    result = news_sensor.run_news_sweep()
    assert result['status'] == 'disabled'
    assert result['saved'] == 0


def test_sweep_isolates_failing_source(monkeypatch, omni_db):
    from app.services.omni import news_sensor
    monkeypatch.setattr(news_sensor, 'load_universe', lambda: UNIVERSE)
    monkeypatch.setattr(news_sensor, 'active_sources', lambda: [
        {'name': 'dead', 'url': 'https://dead/rss', 'grade': 'B'},
        {'name': 'ok', 'url': 'https://ok/rss', 'grade': 'B'},
    ])

    def fetch(url, timeout=10):
        if 'dead' in url:
            raise RuntimeError('unreachable')
        return RSS_XML

    monkeypatch.setattr(news_sensor, '_fetch', fetch)
    result = news_sensor.run_news_sweep()
    assert 'dead' in result['errors']
    assert result['saved'] == 1  # 살아있는 소스는 그대로 수집


def test_sensor_module_has_no_delivery_or_llm_path():
    """센서 계층에 발송·주문·LLM 경로가 없어야 한다 (외부 텍스트는 데이터일 뿐)."""
    import inspect
    from app.services.omni import funnel as f
    from app.services.omni import ledger as l
    from app.services.omni import news_sensor as ns
    for mod in (ns, f, l):
        src = inspect.getsource(mod)
        for banned in ('send_telegram', 'llm_client', 'generate_text', 'order', 'requests.post'):
            assert banned not in src, f'{mod.__name__} 에 {banned} 경로가 있으면 안 된다'


# ─── 오탐 차단: 회사명이 일반명사와 겹치는 경우 ─────────────
# 실데이터 육안 검증(2026-08-29)에서 잡힌 실제 오탐들.
# '대상'(주)·'진도'(주)·'미래산업'(주)은 실존 종목이지만 아래 문장들에서는
# 일반명사·지명이다. 금융 문맥이 없으면 종목 매칭으로 인정하지 않는다.

AMBIG_UNIVERSE = {'001680': '대상', '088790': '진도', '025560': '미래산업',
                  '005930': '삼성전자'}


@pytest.mark.parametrize('text', [
    '트럼프 행정부, 반도체 대상 고강도 관세 검토',
    '보훈 AI공모전에 제대군인 진로전환지원 서비스 대상',
    '코로나 소상공인 빚 탕감 3년 이상 연체자가 대상',
    '진도군-중소벤처기업연구원, 지역상생 업무협약',
    '오산시, 정부에 세교3지구 자족용지 확대 건의 미래산업 유치',
])
def test_ambiguous_name_without_financial_context_is_dropped(text):
    assert funnel.match_symbols(text, AMBIG_UNIVERSE) == []


@pytest.mark.parametrize('text,expected', [
    ('대상, 2분기 영업이익 전년 대비 20% 증가', '001680'),
    ('진도, 자사주 매입 결정 공시', '088790'),
    ('미래산업 주가 급등, 거래량 3배', '025560'),
])
def test_ambiguous_name_with_financial_context_is_kept(text, expected):
    assert funnel.match_symbols(text, AMBIG_UNIVERSE) == [expected]


def test_unambiguous_name_needs_no_financial_context():
    """일반명사와 겹치지 않는 이름은 문맥 없이도 매칭한다."""
    assert funnel.match_symbols('삼성전자 신제품 공개', AMBIG_UNIVERSE) == ['005930']


def test_ticker_match_bypasses_ambiguity_rule():
    """6자리 코드는 그 자체로 명시적 지목이다."""
    assert funnel.match_symbols('001680 관련 안내', AMBIG_UNIVERSE) == ['001680']


# ─── 소스 레지스트리 ────────────────────────────────────────
# 경제면 3개만으로는 종목 커버리지가 얇았다(실측 23종목).
# 증시·기업면을 포함한 복수 매체로 넓히되, 등급 규칙과 킬스위치는 그대로다.

def test_source_names_and_urls_are_unique():
    from app.services.omni import news_sensor
    names = [s['name'] for s in news_sensor.SOURCES]
    urls = [s['url'] for s in news_sensor.SOURCES]
    assert len(names) == len(set(names))
    assert len(urls) == len(set(urls))


def test_every_source_is_https_and_graded():
    from app.services.omni import news_sensor
    for src in news_sensor.SOURCES:
        assert src['url'].startswith('https://'), src['name']
        assert src['grade'] in {'S', 'A', 'B', 'C'}, src['name']


def test_registry_spans_multiple_publishers_and_desks():
    """단일 매체·단일 지면 편향을 막는다 — 4개 이상 매체, 8개 이상 피드."""
    from app.services.omni import news_sensor
    publishers = {s['name'].split('_')[0] for s in news_sensor.SOURCES}
    assert len(news_sensor.SOURCES) >= 8
    assert len(publishers) >= 4
    desks = {s['name'].split('_', 1)[1] for s in news_sensor.SOURCES}
    assert desks & {'stock', 'market', 'finance', 'company'}, '증시·기업면이 있어야 한다'


def test_per_source_killswitch_disables_only_that_source(monkeypatch):
    from app.services.omni import news_sensor
    target = news_sensor.SOURCES[0]['name']
    monkeypatch.setenv(f'OMNI_SOURCE_{target.upper()}_ENABLED', '0')
    active = {s['name'] for s in news_sensor.active_sources()}
    assert target not in active
    assert len(active) == len(news_sensor.SOURCES) - 1


def test_whitelist_limits_to_named_sources(monkeypatch):
    from app.services.omni import news_sensor
    picked = [s['name'] for s in news_sensor.SOURCES[:2]]
    monkeypatch.setenv('OMNI_NEWS_SOURCES', ','.join(picked))
    assert [s['name'] for s in news_sensor.active_sources()] == picked

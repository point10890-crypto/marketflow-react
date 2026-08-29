# -*- coding: utf-8 -*-
"""RAG 지식베이스 현황 — 검색이 무엇을 알고 있고 얼마나 신선한지 보여준다.

판단 화면이 조회 전에는 비어 있어 시스템이 아무것도 모르는 것처럼 보였다.
검색 계층이 실제로 보유한 근거(그래프·뉴스)와 커버리지·신선도를 노출한다.
읽기전용 집계이며 수집을 트리거하지 않는다.
"""
from app.services.mirofish import retrieval


GRAPH = {
    'entities': [
        {'id': 'a', 'type': 'company', 'name': '삼성전자'},
        {'id': 'b', 'type': 'company', 'name': 'SK하이닉스'},
        {'id': 'c', 'type': 'product', 'name': 'HBM'},
    ],
    'relations': [
        {'source_id': 'a', 'target_id': 'c', 'relation_type': 'produces', 'strength': 0.8},
        {'source_id': 'b', 'target_id': 'c', 'relation_type': 'produces', 'strength': 0.9},
        {'source_id': 'a', 'target_id': 'b', 'relation_type': 'competes_with', 'strength': 0.6},
    ],
    'updated_at': '2026-08-29T00:00:00+00:00',
}

NEWS = [
    {'title': 'A', 'symbols': ['005930'], 'grade': 'B', 'source': 'yonhap',
     'score': 3.0, 'published_ts': '2026-08-29T09:00:00+09:00', 'corroboration': 2},
    {'title': 'B', 'symbols': ['005930', '000660'], 'grade': 'B', 'source': 'hankyung',
     'score': 4.0, 'published_ts': '2026-08-29T08:00:00+09:00', 'corroboration': 1},
    {'title': 'C', 'symbols': ['000660'], 'grade': 'A', 'source': 'yonhap',
     'score': 2.0, 'published_ts': '2026-08-28T09:00:00+09:00', 'corroboration': 1},
]


def _patch(monkeypatch, *, graph=GRAPH, news=NEWS, stats=None):
    monkeypatch.setattr(retrieval, 'load_graph', lambda: graph)
    monkeypatch.setattr(retrieval, '_recent_news',
                        lambda limit: news)
    monkeypatch.setattr(retrieval, '_news_stats',
                        lambda: stats or {'total': len(news), 'last_24h': 2,
                                          'last_collected_at': '2026-08-29T09:10:00+00:00'})


def test_reports_graph_size_and_types(monkeypatch):
    _patch(monkeypatch)
    out = retrieval.rag_status()
    assert out['graph']['entities'] == 3
    assert out['graph']['relations'] == 3
    assert out['graph']['entity_types']['company'] == 2


def test_reports_top_relation_types(monkeypatch):
    _patch(monkeypatch)
    out = retrieval.rag_status()
    top = out['graph']['top_relations']
    assert top[0]['relation'] == 'produces' and top[0]['count'] == 2


def test_reports_news_totals_and_freshness(monkeypatch):
    _patch(monkeypatch)
    out = retrieval.rag_status()
    assert out['news']['total'] == 3
    assert out['news']['last_24h'] == 2
    assert out['news']['last_collected_at']


def test_reports_symbol_coverage(monkeypatch):
    """검색이 실제로 몇 종목을 덮고 있는가 — 커버리지가 곧 RAG 성능이다."""
    _patch(monkeypatch)
    out = retrieval.rag_status()
    assert out['coverage']['symbols'] == 2
    top = out['coverage']['top_symbols']
    assert top[0]['symbol'] in {'005930', '000660'}
    assert top[0]['count'] == 2


def test_reports_grade_and_source_mix(monkeypatch):
    _patch(monkeypatch)
    out = retrieval.rag_status()
    assert out['news']['by_grade']['B'] == 2
    assert out['news']['by_source']['yonhap'] == 2


def test_marks_stale_when_collection_is_old(monkeypatch):
    _patch(monkeypatch, stats={'total': 3, 'last_24h': 0,
                               'last_collected_at': '2026-01-01T00:00:00+00:00'})
    out = retrieval.rag_status()
    assert out['news']['stale'] is True


def test_empty_knowledge_base_is_not_an_error(monkeypatch):
    _patch(monkeypatch, graph={'entities': [], 'relations': []}, news=[],
           stats={'total': 0, 'last_24h': 0, 'last_collected_at': None})
    out = retrieval.rag_status()
    assert out['graph']['entities'] == 0
    assert out['coverage']['symbols'] == 0
    assert out['errors'] == {}


def test_source_failures_are_isolated(monkeypatch):
    def boom():
        raise RuntimeError('ekg gone')

    monkeypatch.setattr(retrieval, 'load_graph', boom)
    monkeypatch.setattr(retrieval, '_recent_news', lambda limit: NEWS)
    monkeypatch.setattr(retrieval, '_news_stats',
                        lambda: {'total': 3, 'last_24h': 2, 'last_collected_at': None})
    out = retrieval.rag_status()
    assert 'graph' in out['errors']
    assert out['news']['total'] == 3  # 살아있는 소스는 그대로 보고


def test_status_never_triggers_collection(monkeypatch):
    """현황 조회가 수집을 실행하면 안 된다 — 읽기전용."""
    from app.services.omni import news_sensor

    monkeypatch.setattr(news_sensor, 'run_news_sweep',
                        lambda: (_ for _ in ()).throw(AssertionError('수집 금지')))
    _patch(monkeypatch)
    retrieval.rag_status()

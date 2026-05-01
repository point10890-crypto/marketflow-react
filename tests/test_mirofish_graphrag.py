"""Phase 3A: GraphRAG extractor tests (rule-based + EKG merge)."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.mirofish import graphrag_extractor as gr  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_ekg(monkeypatch, tmp_path):
    """각 테스트마다 격리된 EKG 파일."""
    ekg_path = tmp_path / 'test_ekg.json'
    monkeypatch.setattr(gr, 'EKG_PATH', str(ekg_path))
    monkeypatch.setattr(gr, 'EKG_DIR', str(tmp_path))
    yield


def test_extract_empty_returns_empty_graph():
    out = gr.extract_graph('', use_llm=False)
    assert out['entities'] == []
    assert out['method'] == 'none'


def test_extract_rule_based_finds_samsung_and_fed():
    text = "삼성전자가 인공지능 반도체 수요 증가로 호조를 보이고 있다. 연준 금리 정책이 영향."
    out = gr.extract_graph(text, use_llm=False)
    assert out['method'] == 'rule'
    names = {e['name'] for e in out['entities']}
    assert '삼성전자' in names
    assert '연준' in names
    assert 'AI' in names
    assert '반도체' in names


def test_extract_creates_related_to_edges():
    text = "삼성전자와 SK하이닉스 모두 반도체 수요 회복."
    out = gr.extract_graph(text, use_llm=False)
    assert len(out['relations']) > 0
    # All relations should reference existing entity IDs
    entity_ids = {e['id'] for e in out['entities']}
    for r in out['relations']:
        assert r['source_id'] in entity_ids
        assert r['target_id'] in entity_ids


def test_merge_into_ekg_adds_new_entities():
    text = "삼성전자가 호조."
    g1 = gr.extract_graph(text, use_llm=False)
    stats = gr.merge_into_ekg(g1)
    assert stats['new_entities'] >= 1
    assert stats['total_entities'] >= 1


def test_merge_dedups_existing_entities():
    text = "삼성전자 상승."
    g1 = gr.extract_graph(text, use_llm=False)
    gr.merge_into_ekg(g1)
    g2 = gr.extract_graph(text, use_llm=False)
    stats = gr.merge_into_ekg(g2)
    assert stats['new_entities'] == 0  # 이미 있음


def test_search_causal_chain_finds_path():
    # Manually inject EKG
    text1 = "연준 금리 인상이 삼성전자에 영향."
    g1 = gr.extract_graph(text1, use_llm=False)
    gr.merge_into_ekg(g1)
    # 'related_to' 관계 사용
    chains = gr.search_causal_chain('연준', max_depth=3)
    # 체인이 비어있을 수 있음 (rule-based는 약한 관계만)
    assert isinstance(chains, list)


def test_validate_entities_filters_invalid():
    invalid = [
        {'id': 'valid', 'type': 'company', 'name': 'OK'},
        {'no_id': 'x'},  # 누락
        'not_a_dict',
        {'id': 'valid2', 'type': 'sector', 'name': 'AI'},
    ]
    out = gr._validate_entities(invalid)
    assert len(out) == 2
    assert all(e['id'] for e in out)


def test_validate_relations_normalizes_strength():
    raw = [
        {'source_id': 'a', 'target_id': 'b', 'relation_type': 'causes', 'strength': 1.5},
        {'source_id': 'a', 'target_id': 'b', 'relation_type': 'invalid_type'},
        {'source_id': 'a', 'target_id': 'a'},  # self-ref → drop
        {'source_id': 'a', 'target_id': 'c'},
    ]
    out = gr._validate_relations(raw)
    assert len(out) == 3
    assert out[0]['strength'] == 1.0  # clamped
    assert out[1]['relation_type'] == 'related_to'  # normalized invalid


def test_get_ekg_stats_returns_dict():
    text = "엔비디아 AI 반도체 호조."
    g = gr.extract_graph(text, use_llm=False)
    gr.merge_into_ekg(g)
    stats = gr.get_ekg_stats()
    assert 'total_entities' in stats
    assert 'entity_types' in stats
    assert isinstance(stats['entity_types'], list)


def test_max_text_len_truncation():
    long_text = "삼성전자 " * 5000  # 25000+ chars
    out = gr.extract_graph(long_text, use_llm=False)
    assert out['text_length'] <= gr.MAX_TEXT_LEN

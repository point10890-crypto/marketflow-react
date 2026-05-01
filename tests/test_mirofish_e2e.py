"""End-to-end pipeline test: Brain → GraphRAG → Debate → CIO → Events."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.mirofish import (  # noqa: E402
    load_brain_13d_snapshot,
    create_run,
    get_graph,
    get_report,
)
from app.services.mirofish import graphrag_extractor as gr  # noqa: E402
from app.services.mirofish import agent_debate as ad  # noqa: E402
from app.services.mirofish import document_ingestor as di  # noqa: E402
from app.services.mirofish import cio_react as cr  # noqa: E402
from app.services.mirofish import events as evt  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_ekg(monkeypatch, tmp_path):
    monkeypatch.setattr(gr, 'EKG_PATH', str(tmp_path / 'ekg.json'))
    monkeypatch.setattr(gr, 'EKG_DIR', str(tmp_path))


def test_e2e_full_pipeline_no_llm():
    """Brain → Document Ingest → GraphRAG → Debate → CIO → Events."""
    target = 'E2E_TEST'

    # 1) Brain 13D
    brain = load_brain_13d_snapshot(target)
    assert brain['name'] == 'MiroFish Brain 13D'
    assert len(brain['dimensions']) == 13

    # 2) Document → chunks → GraphRAG
    text = "삼성전자 호조. SK하이닉스 반도체 모멘텀. 연준 금리 영향 우려."
    doc = di.ingest_document('news.txt', text.encode('utf-8'))
    assert 'error' not in doc

    graph = gr.extract_graph(doc['chunks'][0], use_llm=False)
    assert len(graph['entities']) > 0
    stats = gr.merge_into_ekg(graph)
    assert stats['new_entities'] > 0

    # 3) Multi-agent debate
    debate = ad.run_debate(target, brain, rounds=2, use_llm=False)
    assert len(debate['rounds']) == 2
    assert debate['final_consensus']['action'] in ('BUY', 'HOLD', 'SELL')

    # 4) ReACT CIO
    cio = cr.run_cio(target, brain, debate, use_llm=False)
    assert cio['final_answer']['action'] in ('BUY', 'HOLD', 'SELL')
    assert cio['loops_used'] >= cr.MIN_LOOPS

    # 5) Run + events
    run = create_run({'target': target, 'mode': 'fast', 'agent_count': 5})
    evt.append_event(run['id'], 'info', 'e2e', 'pipeline_complete')
    events_out = evt.read_events(run['id'])
    assert events_out['total'] >= 1

    # 6) Graph + Report
    g = get_graph(run['id'])
    assert g['schema_version'] == 2
    assert len(g['layers']) == 3

    r = get_report(run['id'])
    assert 'markdown' in r


def test_e2e_pipeline_handles_empty_brain():
    """Brain dimension 결측에도 파이프라인 끝까지 진행."""
    empty_brain = {'dimension_scores': {}}
    debate = ad.run_debate('NULL', empty_brain, rounds=1, use_llm=False)
    assert len(debate['rounds']) == 1

    cio = cr.run_cio('NULL', empty_brain, debate, use_llm=False)
    assert cio['final_answer']['action'] in ('BUY', 'HOLD', 'SELL')


def test_e2e_csv_pipeline():
    """CSV 입력 → 청킹 → GraphRAG → EKG."""
    csv_text = (
        "ticker,name,signal\n"
        "005930,삼성전자,Bullish\n"
        "000660,SK하이닉스,Bullish\n"
        "035720,카카오,Neutral\n"
    )
    doc = di.ingest_document('signals.csv', csv_text.encode('utf-8'))
    assert doc['format'] == 'csv'
    assert len(doc['chunks']) >= 1

    graph = gr.extract_graph(doc['chunks'][0], use_llm=False)
    names = {e['name'] for e in graph['entities']}
    assert '삼성전자' in names or 'SK하이닉스' in names

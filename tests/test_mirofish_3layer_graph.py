"""Phase 2B: 3-Layer Knowledge Graph (Blue/Red/Gold) tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.mirofish import create_run, get_graph  # noqa: E402


@pytest.fixture
def run():
    return create_run({'target': 'TEST_3LAYER', 'mode': 'fast', 'agent_count': 6})


def test_graph_has_three_layers(run):
    graph = get_graph(run['id'])
    layer_ids = {l['id'] for l in graph['layers']}
    assert layer_ids == {'blue', 'red', 'gold'}


def test_layers_have_distinct_colors(run):
    graph = get_graph(run['id'])
    colors = {l['id']: l['color'] for l in graph['layers']}
    assert colors['blue'] == '#3b82f6'
    assert colors['red'] == '#ef4444'
    assert colors['gold'] == '#f59e0b'


def test_target_and_brain_in_blue_layer(run):
    graph = get_graph(run['id'])
    nodes_by_id = {n['id']: n for n in graph['nodes']}
    assert nodes_by_id['target']['layer'] == 'blue'
    assert nodes_by_id['brain13d']['layer'] == 'blue'


def test_analysts_in_red_layer(run):
    graph = get_graph(run['id'])
    analyst_nodes = [n for n in graph['nodes'] if n.get('type') == 'analyst']
    assert len(analyst_nodes) > 0
    for n in analyst_nodes:
        assert n['layer'] == 'red'


def test_verdict_in_gold_layer(run):
    graph = get_graph(run['id'])
    verdicts = [n for n in graph['nodes'] if n.get('type') == 'verdict']
    assert len(verdicts) == 1
    assert verdicts[0]['layer'] == 'gold'


def test_dimension_nodes_in_blue_layer(run):
    graph = get_graph(run['id'])
    dim_nodes = [n for n in graph['nodes'] if n.get('type') == 'dimension']
    # 데이터 가용 시 dim 노드 존재. 없으면 빈 list (fallback)
    for n in dim_nodes:
        assert n['layer'] == 'blue'
        assert n['id'].startswith('dim_')


def test_analyst_to_verdict_edges_tagged_red(run):
    graph = get_graph(run['id'])
    analyst_ids = {n['id'] for n in graph['nodes'] if n.get('type') == 'analyst'}
    # analyst → verdict 모두 layer='red'
    for e in graph['edges']:
        if e['source'] in analyst_ids and e['target'] == 'verdict':
            assert e['layer'] == 'red'


def test_brain_to_verdict_edge_tagged_blue(run):
    graph = get_graph(run['id'])
    blue_to_gold = [e for e in graph['edges']
                    if e['source'] == 'brain13d' and e['target'] == 'verdict']
    assert len(blue_to_gold) == 1
    assert blue_to_gold[0]['layer'] == 'blue'


def test_schema_version_is_2(run):
    graph = get_graph(run['id'])
    assert graph['schema_version'] == 2


def test_no_duplicate_node_ids(run):
    graph = get_graph(run['id'])
    ids = [n['id'] for n in graph['nodes']]
    assert len(ids) == len(set(ids)), 'Duplicate node IDs detected'


def test_all_edges_reference_existing_nodes(run):
    graph = get_graph(run['id'])
    node_ids = {n['id'] for n in graph['nodes']}
    for e in graph['edges']:
        assert e['source'] in node_ids, f"Dangling edge source: {e['source']}"
        assert e['target'] in node_ids, f"Dangling edge target: {e['target']}"

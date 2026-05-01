"""Phase 4A: Run events tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.mirofish import events as mf_events  # noqa: E402
from app.services.mirofish import create_run  # noqa: E402


@pytest.fixture
def run():
    return create_run({'target': 'EVENTS_TEST', 'mode': 'fast', 'agent_count': 5})


def test_append_and_read_single_event(run):
    mf_events.append_event(run['id'], 'info', 'intake', 'Started')
    out = mf_events.read_events(run['id'])
    assert out['total'] >= 1
    assert out['events'][-1]['message'] == 'Started'


def test_read_events_pagination(run):
    for i in range(15):
        mf_events.append_event(run['id'], 'info', 'graph_build', f'msg-{i}')

    out1 = mf_events.read_events(run['id'], since_index=0, max_count=10)
    assert len(out1['events']) == 10
    assert out1['next_index'] == 10
    assert out1['has_more']

    out2 = mf_events.read_events(run['id'], since_index=10, max_count=10)
    assert len(out2['events']) >= 5  # 5 more remaining (could be 5+ depending on prev tests)


def test_event_includes_payload(run):
    mf_events.append_event(run['id'], 'info', 'verdict', 'Synthesized',
                           payload={'action': 'BUY', 'confidence': 0.7})
    out = mf_events.read_events(run['id'])
    last = out['events'][-1]
    assert last['payload']['action'] == 'BUY'


def test_read_nonexistent_run_returns_empty():
    out = mf_events.read_events('does_not_exist_xxx')
    assert out['events'] == []
    assert out['total'] == 0


def test_event_has_required_fields(run):
    mf_events.append_event(run['id'], 'warn', 'analyst_mesh', 'High variance')
    out = mf_events.read_events(run['id'])
    last = out['events'][-1]
    for field in ('ts', 'level', 'phase', 'message'):
        assert field in last


def test_since_index_clamped_to_total(run):
    mf_events.append_event(run['id'], 'info', 'x', 'one')
    out = mf_events.read_events(run['id'], since_index=999)
    assert out['events'] == []
    assert not out.get('has_more', False)

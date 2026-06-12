"""Admin route and service snapshot tests for Alpha Brain Agent status."""

from flask import Flask

from app.routes.admin_mirofish import admin_mirofish_bp


def test_agent_status_route_is_registered():
    app = Flask(__name__)
    app.register_blueprint(admin_mirofish_bp, url_prefix='/api/admin/mirofish')

    rules = {str(rule) for rule in app.url_map.iter_rules()}

    assert '/api/admin/mirofish/agent/status' in rules


def test_get_agent_status_snapshot_shape(monkeypatch, tmp_path):
    from app.services.mirofish import agent_actions, alpha_brain_agent as agent

    monkeypatch.setattr(agent, 'STATE_PATH', str(tmp_path / 'agent_state.json'))
    monkeypatch.setattr(agent, 'JOURNAL_PATH', str(tmp_path / 'agent_journal.jsonl'))
    monkeypatch.setattr(agent_actions, 'OVERRIDES_PATH', str(tmp_path / 'agent_overrides.json'))
    monkeypatch.setattr(agent_actions, 'OVERLAY_PATH', str(tmp_path / 'agent_scoring_overlay.json'))
    monkeypatch.setattr(agent.edge_map, 'read_edge_map', lambda: {'generated_at': '2026-06-12T00:00:00+00:00'})

    status = agent.get_agent_status()

    assert status['service'] == 'mirofish-alpha-brain-agent'
    assert 'dry_run' in status
    assert 'circuit_open' in status
    assert status['active_overrides'] == {}
    assert status['active_scoring_overlay'] == {}
    assert status['recent_journal'] == []

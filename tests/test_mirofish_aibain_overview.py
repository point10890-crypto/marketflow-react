"""get_aibain_overview tests — section shape + source isolation. No network."""
from app.services.mirofish import pipeline_overview as po


def test_overview_has_three_sections(monkeypatch):
    monkeypatch.setattr(po, 'get_outcomes_board', lambda **kw: {
        'window_days': 30,
        'summary': {'hit_rate_pct': 46.2, 'avg_forward_return_pct': 1.15,
                    'false_positive_pct': 30.0, 'evaluated_count': 26},
        'items': [{'symbol': '005930', 'name': '삼성전자', 'entry_date': '2026-06-01',
                   'status': 'evaluated', 'hit': True, 'forward_return_pct': 6.0}],
    })
    import app.services.mirofish.workflow as wf
    monkeypatch.setattr(wf, 'read_latest_workflow', lambda: {'id': 'w1', 'completed_at': '2026-06-15T00:00:00Z'})
    monkeypatch.setattr(wf, 'build_share_payload', lambda w, rank=None: {'top_items': [
        {'rank': 1, 'name': 'A', 'symbol': '000001', 'action': 'BUY_CANDIDATE'}]})
    import app.services.mirofish.alpha_brain_agent as agent
    monkeypatch.setattr(agent, 'build_agent_observation', lambda **kw: {
        'interaction_map': {'top_positive': [{'combo': 'regime:RISK_ON & tag:foreign_buy', 'n': 6,
                                              'hit_rate': 1.0, 'expectancy_pct': 8.0}], 'top_negative': []},
        'regime_distribution': {'RISK_ON': 26}})
    monkeypatch.setattr(agent, 'get_agent_status', lambda: {'edge_map_generated_at': '2026-06-15T00:00:00Z'})

    out = po.get_aibain_overview()
    assert out['performance']['hit_rate_pct'] == 46.2
    assert out['performance']['evaluated_count'] == 26
    assert len(out['performance']['verified']) == 1
    assert out['detections']['items'][0]['symbol'] == '000001'
    assert out['learning']['regime_distribution']['RISK_ON'] == 26
    assert out['learning']['top_positive'][0]['combo'].startswith('regime:RISK_ON')


def test_overview_isolates_failing_source(monkeypatch):
    def boom(**kw):
        raise RuntimeError('board down')
    monkeypatch.setattr(po, 'get_outcomes_board', boom)
    import app.services.mirofish.workflow as wf
    monkeypatch.setattr(wf, 'read_latest_workflow', lambda: None)
    import app.services.mirofish.alpha_brain_agent as agent
    monkeypatch.setattr(agent, 'build_agent_observation', lambda **kw: {'interaction_map': {}, 'regime_distribution': {}})
    monkeypatch.setattr(agent, 'get_agent_status', lambda: {})
    out = po.get_aibain_overview()
    assert 'detections' in out and 'performance' in out and 'learning' in out
    assert out['performance'].get('error') or out['performance'].get('evaluated_count') in (0, None)

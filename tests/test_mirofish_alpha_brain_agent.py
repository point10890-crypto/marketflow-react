"""Alpha Brain Agent cycle tests with LLM and I/O dependencies mocked."""

import json

import pytest

from app.services.mirofish import alpha_brain_agent as agent


@pytest.fixture
def agent_env(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, 'STATE_PATH', str(tmp_path / 'agent_state.json'))
    monkeypatch.setattr(agent, 'JOURNAL_PATH', str(tmp_path / 'agent_journal.jsonl'))
    monkeypatch.setattr(agent.agent_actions, 'OVERRIDES_PATH', str(tmp_path / 'agent_overrides.json'))
    monkeypatch.setattr(agent.agent_actions, 'OVERLAY_PATH', str(tmp_path / 'agent_scoring_overlay.json'))
    monkeypatch.setenv('MIROFISH_AGENT_DRY_RUN', '0')
    monkeypatch.setenv('MIROFISH_AGENT_BRIEF_ENABLED', '0')
    monkeypatch.setattr(agent.edge_map, 'build_edge_map', lambda **_kw: {
        'schema_version': 'mirofish.edge_map.v1',
        'evaluated_count': 12,
        'overall': {'n': 12, 'hit_rate': 0.58, 'expectancy_pct': 1.2},
        'by_tag': {},
        'by_alpha_band': {},
        'by_market': {},
        'by_action': {},
        'by_signal_quality': {},
    })
    monkeypatch.setattr(agent, '_advisory_summary', lambda: {
        'evaluated_count': 12,
        'hit_rate_recent': 0.58,
        'by_strategy_tag': {},
        'baseline_hit_rate': 0.5,
        'lookahead_safe': True,
    })
    monkeypatch.setattr(agent, '_read_backtest_daily', lambda: {
        'generated_at': '2026-06-12T14:00:00+00:00',
        'lookahead_safe': True,
        'enhanced': {
            'sample_count': 120,
            'expectancy_r': 0.35,
            'information_coefficient': 0.09,
        },
    })
    monkeypatch.setattr(agent.agent_actions, 'enforce_rollbacks', lambda **_kw: [])
    return tmp_path


def _llm_returning(payload):
    return lambda _prompt: json.dumps(payload)


def test_observation_contains_kpi_and_freshness(agent_env):
    obs = agent.build_agent_observation(now_iso='2026-06-12T08:00:00+00:00')

    assert obs['edge_map']['evaluated_count'] == 12
    assert obs['backtest']['sample_count'] == 120
    assert obs['backtest']['stale'] is False
    assert 'active_overrides' in obs
    assert 'active_scoring_overlay' in obs


def test_observation_flags_stale_backtest(agent_env, monkeypatch):
    monkeypatch.setattr(agent, '_read_backtest_daily', lambda: {
        'generated_at': '2026-06-01T14:00:00+00:00',
        'enhanced': {'sample_count': 30},
    })

    obs = agent.build_agent_observation(now_iso='2026-06-12T08:00:00+00:00')

    assert obs['backtest']['stale'] is True


def test_maintenance_refreshes_stale_backtest_without_llm(agent_env, monkeypatch):
    monkeypatch.setattr(agent, '_read_backtest_daily', lambda: {
        'generated_at': '2026-06-01T14:00:00+00:00',
        'enhanced': {'sample_count': 30},
    })
    calls = []
    monkeypatch.setattr(
        agent.agent_actions,
        'execute_decisions',
        lambda decisions, **_kw: [
            calls.append(decision) or {'action': decision['action'], 'status': 'applied', 'reason': ''}
            for decision in decisions
        ],
    )

    obs = agent.build_agent_observation(now_iso='2026-06-12T08:00:00+00:00')
    results = agent.run_maintenance(obs, dry_run=False)

    assert [call['action'] for call in calls] == ['refresh_backtest', 'refresh_outcomes']
    assert all(result['status'] == 'applied' for result in results)


def test_cycle_executes_validated_llm_decisions(agent_env, monkeypatch):
    executed = []
    monkeypatch.setattr(
        agent.agent_actions,
        'execute_decisions',
        lambda decisions, **_kw: [
            executed.append(decision) or {'action': decision['action'], 'status': 'applied', 'reason': ''}
            for decision in decisions
        ],
    )
    payload = {
        'assessment': 'edge ok',
        'confidence': 0.8,
        'decisions': [
            {'action': 'apply_scoring_delta', 'tag': 'volume_surge', 'delta': 1.0, 'reason': 'edge'},
        ],
    }

    result = agent.run_agent_cycle('post_backtest', llm_call=_llm_returning(payload))

    assert result['status'] == 'completed'
    assert any(item['action'] == 'apply_scoring_delta' for item in executed)
    journal = agent.read_journal_tail(1)[0]
    assert journal['cycle'] == 'post_backtest'
    assert journal['llm']['decision_count'] == 1


def test_cycle_rejects_invalid_llm_json_then_no_decision(agent_env, monkeypatch):
    monkeypatch.setattr(
        agent.agent_actions,
        'execute_decisions',
        lambda decisions, **_kw: [{'action': decision['action'], 'status': 'applied', 'reason': ''} for decision in decisions],
    )

    result = agent.run_agent_cycle('evening', llm_call=lambda _prompt: 'not json at all')

    assert result['status'] == 'completed'
    assert result['llm']['status'] == 'no_decision'
    assert result['act']['llm_results'] == []


def test_cycle_filters_non_whitelisted_actions_before_execution(agent_env, monkeypatch):
    executed = []
    monkeypatch.setattr(
        agent.agent_actions,
        'execute_decisions',
        lambda decisions, **_kw: [
            executed.append(decision) or {'action': decision['action'], 'status': 'applied', 'reason': ''}
            for decision in decisions
        ],
    )
    payload = {
        'assessment': 'x',
        'confidence': 0.9,
        'decisions': [
            {'action': 'send_telegram_to_everyone', 'reason': 'bad'},
            {'action': 'revert_scoring_delta', 'tag': 'volume_surge', 'reason': 'ok'},
        ],
    }

    result = agent.run_agent_cycle('evening', llm_call=_llm_returning(payload))

    assert 'send_telegram_to_everyone' not in [item['action'] for item in executed]
    assert 'revert_scoring_delta' in [item['action'] for item in executed]
    assert result['llm']['rejected_decisions'] == 1


def test_circuit_breaker_opens_after_three_failures(agent_env, monkeypatch):
    def boom(**_kw):
        raise RuntimeError('sense exploded')

    monkeypatch.setattr(agent, 'build_agent_observation', boom)

    for _ in range(3):
        result = agent.run_agent_cycle('evening', llm_call=lambda _prompt: None)
        assert result['status'] == 'failed'
    result = agent.run_agent_cycle('evening', llm_call=lambda _prompt: None)
    assert result['status'] == 'skipped_circuit_open'


def test_dry_run_cycle_marks_mutations_proposed_only(agent_env, monkeypatch):
    monkeypatch.setenv('MIROFISH_AGENT_DRY_RUN', '1')
    payload = {
        'assessment': 'x',
        'confidence': 0.9,
        'decisions': [
            {'action': 'apply_scoring_delta', 'tag': 'volume_surge', 'delta': 1.0, 'reason': 'x'},
        ],
    }
    monkeypatch.setattr(
        agent.agent_actions.hypothesis_replay,
        'replay_tag_delta',
        lambda tag, delta, **_kw: {'passed': True, 'tag': tag, 'delta': delta},
    )

    result = agent.run_agent_cycle('post_backtest', llm_call=_llm_returning(payload))

    assert [item['status'] for item in result['act']['llm_results']] == ['proposed_only']

"""Agent action executor tests: bounds, replay gate, rollback, no LLM."""

import json

import pytest

from app.services.mirofish import agent_actions as aa


@pytest.fixture
def stores(tmp_path, monkeypatch):
    monkeypatch.setattr(aa, 'OVERRIDES_PATH', str(tmp_path / 'agent_overrides.json'))
    monkeypatch.setattr(aa, 'OVERLAY_PATH', str(tmp_path / 'agent_scoring_overlay.json'))
    if aa.edge_map is not None:
        monkeypatch.setattr(aa.edge_map, 'read_edge_map', lambda: {'by_tag': {}})
    return tmp_path


def _backtest_metrics(expectancy=0.4, ic=0.1):
    return {'expectancy_r': expectancy, 'information_coefficient': ic}


def _pass_replay(monkeypatch):
    monkeypatch.setattr(
        aa.hypothesis_replay,
        'replay_tag_delta',
        lambda tag, delta, **kw: {
            'passed': True,
            'ic_gain': 0.03,
            'sample_count': 80,
            'tagged_count': 20,
        },
    )


def test_adjust_parameter_within_bounds_records_effective_override(stores):
    result = aa.execute_decisions(
        [{'action': 'adjust_parameter', 'param': 'min_alpha', 'to': 72.0, 'reason': 'edge'}],
        dry_run=False,
        backtest_metrics=_backtest_metrics(),
    )

    assert result[0]['status'] == 'applied'
    assert aa.param_override('min_alpha') == 72.0
    assert aa.param_value('min_alpha', 70.0) == 72.0
    assert aa.read_effective_overrides() == {'min_alpha': 72.0}
    assert aa.read_effective_overrides({'min_alpha': 70.0, 'max_risk': 45.0}) == {
        'min_alpha': 72.0,
        'max_risk': 45.0,
    }
    raw = json.loads((stores / 'agent_overrides.json').read_text(encoding='utf-8'))
    entry = raw['params']['min_alpha']
    assert entry['baseline'] == {'expectancy_r': 0.4, 'information_coefficient': 0.1}
    assert entry['rollback']['worse_limit'] == aa.ROLLBACK_WORSE_LIMIT


def test_adjust_parameter_rejects_out_of_range(stores):
    result = aa.execute_decisions(
        [{'action': 'adjust_parameter', 'param': 'min_alpha', 'to': 90.0, 'reason': 'x'}],
        dry_run=False,
        backtest_metrics=_backtest_metrics(),
    )

    assert result[0]['status'] == 'rejected'
    assert result[0]['reason'] == 'out_of_bounds'
    assert aa.param_override('min_alpha') is None


def test_adjust_parameter_rejects_oversized_step(stores):
    aa.execute_decisions(
        [{'action': 'adjust_parameter', 'param': 'min_alpha', 'to': 72.0, 'reason': 'x'}],
        dry_run=False,
        backtest_metrics=_backtest_metrics(),
    )
    result = aa.execute_decisions(
        [{'action': 'adjust_parameter', 'param': 'min_alpha', 'to': 80.0, 'reason': 'x'}],
        dry_run=False,
        backtest_metrics=_backtest_metrics(),
    )

    assert result[0]['status'] == 'rejected'
    assert result[0]['reason'] == 'step_too_large'
    assert aa.param_override('min_alpha') == 72.0


def test_adjust_parameter_rejects_unknown_param(stores):
    result = aa.execute_decisions(
        [{'action': 'adjust_parameter', 'param': 'max_drawdown', 'to': 10.0, 'reason': 'x'}],
        dry_run=False,
        backtest_metrics=_backtest_metrics(),
    )

    assert result[0]['status'] == 'rejected'
    assert result[0]['reason'] == 'unknown_param'


def test_unknown_action_rejected(stores):
    result = aa.execute_decisions(
        [{'action': 'delete_everything', 'reason': 'x'}],
        dry_run=False,
        backtest_metrics=_backtest_metrics(),
    )

    assert result[0]['status'] == 'rejected'
    assert result[0]['reason'] == 'unknown_action'


def test_apply_scoring_delta_requires_passed_replay(stores, monkeypatch):
    monkeypatch.setattr(
        aa.hypothesis_replay,
        'replay_tag_delta',
        lambda tag, delta, **kw: {'passed': False, 'reason': 'replay_does_not_improve_ranking'},
    )

    result = aa.execute_decisions(
        [{'action': 'apply_scoring_delta', 'tag': 'volume_surge', 'delta': 1.5, 'reason': 'x'}],
        dry_run=False,
        backtest_metrics=_backtest_metrics(),
    )

    assert result[0]['status'] == 'rejected'
    assert result[0]['reason'] == 'replay_failed: replay_does_not_improve_ranking'
    assert aa.scoring_overlay() == {}


def test_apply_scoring_delta_applies_after_replay_pass(stores, monkeypatch):
    _pass_replay(monkeypatch)

    result = aa.execute_decisions(
        [{'action': 'apply_scoring_delta', 'tag': 'volume_surge', 'delta': 1.5, 'reason': 'x'}],
        dry_run=False,
        backtest_metrics=_backtest_metrics(0.4, 0.1),
    )

    assert result[0]['status'] == 'applied'
    overlay = aa.scoring_overlay()
    assert overlay['volume_surge']['delta'] == 1.5
    assert overlay['volume_surge']['baseline']['expectancy_r'] == 0.4
    assert overlay['volume_surge']['rollback']['metrics'] == ['expectancy_r', 'information_coefficient']
    assert aa.scoring_overlay_deltas() == {'volume_surge': 1.5}
    assert aa.read_effective_scoring_overlay() == {'volume_surge': 1.5}


def test_apply_scoring_delta_accepts_edge_map_discovered_tag(stores, monkeypatch):
    _pass_replay(monkeypatch)
    if aa.edge_map is not None:
        monkeypatch.setattr(aa.edge_map, 'read_edge_map', lambda: {'by_tag': {'new_edge_tag': {'n': 7}}})

    result = aa.execute_decisions(
        [{'action': 'apply_scoring_delta', 'tag': 'new_edge_tag', 'delta': -0.75, 'reason': 'edge'}],
        dry_run=False,
        backtest_metrics=_backtest_metrics(),
    )

    assert result[0]['status'] == 'applied'
    assert aa.scoring_overlay_deltas() == {'new_edge_tag': -0.75}


def test_apply_scoring_delta_rejects_over_cap(stores, monkeypatch):
    _pass_replay(monkeypatch)

    result = aa.execute_decisions(
        [{'action': 'apply_scoring_delta', 'tag': 'volume_surge', 'delta': 5.0, 'reason': 'x'}],
        dry_run=False,
        backtest_metrics=_backtest_metrics(),
    )

    assert result[0]['status'] == 'rejected'
    assert result[0]['reason'] == 'delta_over_cap'
    assert aa.scoring_overlay() == {}


def test_apply_scoring_delta_rejects_unknown_tag(stores, monkeypatch):
    _pass_replay(monkeypatch)

    result = aa.execute_decisions(
        [{'action': 'apply_scoring_delta', 'tag': 'unmined_tag', 'delta': 1.0, 'reason': 'x'}],
        dry_run=False,
        backtest_metrics=_backtest_metrics(),
    )

    assert result[0]['status'] == 'rejected'
    assert result[0]['reason'] == 'unknown_tag'
    assert aa.scoring_overlay() == {}


def test_dry_run_blocks_store_mutations_but_records_proposal(stores, monkeypatch):
    _pass_replay(monkeypatch)

    results = aa.execute_decisions(
        [
            {'action': 'adjust_parameter', 'param': 'min_alpha', 'to': 72.0, 'reason': 'x'},
            {'action': 'apply_scoring_delta', 'tag': 'volume_surge', 'delta': 1.0, 'reason': 'x'},
        ],
        dry_run=True,
        backtest_metrics=_backtest_metrics(),
    )

    assert all(result['status'] == 'proposed_only' for result in results)
    assert aa.param_override('min_alpha') is None
    assert aa.scoring_overlay() == {}


def test_revert_parameter_and_scoring_delta(stores, monkeypatch):
    _pass_replay(monkeypatch)
    aa.execute_decisions(
        [
            {'action': 'adjust_parameter', 'param': 'min_alpha', 'to': 72.0, 'reason': 'x'},
            {'action': 'apply_scoring_delta', 'tag': 'volume_surge', 'delta': 1.0, 'reason': 'x'},
        ],
        dry_run=False,
        backtest_metrics=_backtest_metrics(),
    )

    results = aa.execute_decisions(
        [
            {'action': 'revert_parameter', 'param': 'min_alpha', 'reason': 'undo'},
            {'action': 'revert_scoring_delta', 'tag': 'volume_surge', 'reason': 'undo'},
        ],
        dry_run=False,
        backtest_metrics=_backtest_metrics(),
    )

    assert [result['status'] for result in results] == ['applied', 'applied']
    assert aa.param_override('min_alpha') is None
    assert aa.scoring_overlay() == {}


def test_rollback_after_two_consecutive_worse_backtests(stores, monkeypatch):
    _pass_replay(monkeypatch)
    aa.execute_decisions(
        [{'action': 'apply_scoring_delta', 'tag': 'volume_surge', 'delta': 1.0, 'reason': 'x'}],
        dry_run=False,
        backtest_metrics=_backtest_metrics(0.4, 0.10),
    )

    reverted = aa.enforce_rollbacks(
        backtest_metrics=_backtest_metrics(0.1, 0.02),
        backtest_generated_at='2026-06-13T14:00:00+00:00',
    )
    assert reverted == []
    assert aa.scoring_overlay()['volume_surge']['worse_count'] == 1

    again = aa.enforce_rollbacks(
        backtest_metrics=_backtest_metrics(0.1, 0.02),
        backtest_generated_at='2026-06-13T14:00:00+00:00',
    )
    assert again == []
    assert aa.scoring_overlay()['volume_surge']['worse_count'] == 1

    reverted = aa.enforce_rollbacks(
        backtest_metrics=_backtest_metrics(0.1, 0.02),
        backtest_generated_at='2026-06-14T14:00:00+00:00',
    )
    assert reverted == [{'kind': 'scoring_delta', 'key': 'volume_surge'}]
    assert aa.scoring_overlay() == {}


def test_rollback_resets_worse_count_on_recovery(stores, monkeypatch):
    _pass_replay(monkeypatch)
    aa.execute_decisions(
        [{'action': 'apply_scoring_delta', 'tag': 'volume_surge', 'delta': 1.0, 'reason': 'x'}],
        dry_run=False,
        backtest_metrics=_backtest_metrics(0.4, 0.10),
    )

    aa.enforce_rollbacks(
        backtest_metrics=_backtest_metrics(0.1, 0.02),
        backtest_generated_at='2026-06-13T14:00:00+00:00',
    )
    aa.enforce_rollbacks(
        backtest_metrics=_backtest_metrics(0.5, 0.12),
        backtest_generated_at='2026-06-14T14:00:00+00:00',
    )

    assert aa.scoring_overlay()['volume_surge']['worse_count'] == 0


def test_rollback_also_reverts_degraded_parameter_override(stores):
    aa.execute_decisions(
        [{'action': 'adjust_parameter', 'param': 'min_alpha', 'to': 72.0, 'reason': 'x'}],
        dry_run=False,
        backtest_metrics=_backtest_metrics(0.4, 0.10),
    )

    aa.enforce_rollbacks(
        backtest_metrics=_backtest_metrics(0.1, 0.02),
        backtest_generated_at='2026-06-13T14:00:00+00:00',
    )
    reverted = aa.enforce_rollbacks(
        backtest_metrics=_backtest_metrics(0.1, 0.02),
        backtest_generated_at='2026-06-14T14:00:00+00:00',
    )

    assert reverted == [{'kind': 'parameter', 'key': 'min_alpha'}]
    assert aa.param_override('min_alpha') is None

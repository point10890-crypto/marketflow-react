"""Claw shadow outcome scheduler wiring."""
from __future__ import annotations

import inspect

import scheduler


def test_claw_outcome_schedule_is_between_existing_heavy_jobs():
    to_minutes = lambda raw: int(raw[:2]) * 60 + int(raw[3:])
    assert scheduler.Config.CLAW_OUTCOME_ENABLED is True
    assert to_minutes(scheduler.Config.WAVE_SCAN_TIME) < to_minutes(scheduler.Config.CLAW_OUTCOME_TIME)
    assert to_minutes(scheduler.Config.CLAW_OUTCOME_TIME) < to_minutes(scheduler.Config.BUY_SCREEN_TIME)


def test_claw_outcome_schedule_is_shadow_updater_only():
    source = inspect.getsource(scheduler.Scheduler.setup_schedules)
    assert 'Config.CLAW_OUTCOME_TIME' in source
    assert "'claw_outcomes'" in source
    runner = inspect.getsource(scheduler._run_claw_outcome_update)
    assert 'update_mature_outcomes' in runner
    assert 'send_telegram' not in runner


def test_claw_outcome_runner_returns_explicit_success(monkeypatch):
    monkeypatch.setattr(
        'marketflow_claw.observation.update_mature_outcomes',
        lambda: {'ok': True, 'completed': 0, 'missing': 0, 'still_pending': 0, 'data_as_of': None},
    )
    assert scheduler._run_claw_outcome_update() is True

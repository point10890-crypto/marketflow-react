"""Regression tests for Scheduler._with_record.

Background bug: the wrapper used `success = (result is None or result)`,
which silently treated a task function that forgot to `return` as a
success. All real task functions return explicit booleans, so a `None`
return is always a bug — it must be treated as a failure so the retry
+ telegram-alert path fires.

These tests pin the corrected behavior so a future refactor cannot
re-introduce the silent-success regression.
"""
from unittest.mock import patch

import pytest

import scheduler
from scheduler import Scheduler


@pytest.fixture(autouse=True)
def _silence_side_effects():
    # _with_record calls record_task_run + send_telegram on success/failure.
    # Patch them so the test stays hermetic.
    with patch("scheduler.record_task_run") as rec, \
         patch("scheduler.send_telegram") as tg, \
         patch("scheduler.time.sleep"):  # skip the 15-min retry sleep
        yield rec, tg


def _make_task(return_value, name="fake_task"):
    def task():
        return return_value
    task.__name__ = name
    return task


def test_with_record_true_is_success():
    rec_calls = []
    with patch("scheduler.record_task_run", side_effect=lambda k: rec_calls.append(k)), \
         patch("scheduler.send_telegram"), \
         patch("scheduler.time.sleep"):
        wrapped = Scheduler._with_record(_make_task(True), "task_ok", max_retries=0)
        result = wrapped()
    assert result is True
    assert rec_calls == ["task_ok"]


def test_with_record_false_triggers_failure_alert():
    tg_calls = []
    with patch("scheduler.record_task_run") as rec, \
         patch("scheduler.send_telegram", side_effect=lambda msg: tg_calls.append(msg)), \
         patch("scheduler.time.sleep"):
        wrapped = Scheduler._with_record(_make_task(False), "task_fail", max_retries=0)
        result = wrapped()
    assert result is False
    rec.assert_not_called()
    assert any("task_fail" in m for m in tg_calls)


def test_with_record_none_return_is_treated_as_failure():
    """REGRESSION: a task that forgets to return must NOT be marked success."""
    tg_calls = []
    with patch("scheduler.record_task_run") as rec, \
         patch("scheduler.send_telegram", side_effect=lambda msg: tg_calls.append(msg)), \
         patch("scheduler.time.sleep"):
        wrapped = Scheduler._with_record(_make_task(None), "task_none", max_retries=0)
        result = wrapped()
    assert result is False, "None return must be treated as failure"
    rec.assert_not_called()
    assert any("task_none" in m for m in tg_calls)


def test_with_record_exception_retries_then_fails():
    attempts = {"n": 0}
    def boom():
        attempts["n"] += 1
        raise RuntimeError("nope")
    boom.__name__ = "boom"

    tg_calls = []
    with patch("scheduler.record_task_run") as rec, \
         patch("scheduler.send_telegram", side_effect=lambda msg: tg_calls.append(msg)), \
         patch("scheduler.time.sleep"):
        wrapped = Scheduler._with_record(boom, "task_boom", max_retries=2, retry_delay=0)
        result = wrapped()
    assert result is False
    assert attempts["n"] == 3  # initial + 2 retries
    rec.assert_not_called()
    assert any("task_boom" in m for m in tg_calls)


def test_with_record_verify_fn_can_override_truthy_result():
    with patch("scheduler.record_task_run") as rec, \
         patch("scheduler.send_telegram"), \
         patch("scheduler.time.sleep"):
        wrapped = Scheduler._with_record(
            _make_task(True),
            "task_verify",
            max_retries=0,
            verify_fn=lambda: False,  # task returned True but file didn't land
        )
        result = wrapped()
    assert result is False
    rec.assert_not_called()


def test_alpha_scanner_monitor_sends_telegram_for_new_events():
    def fake_monitor(*args, send_fn=None, **kwargs):
        assert send_fn("alpha alert") is True
        return {
            "status": "sent",
            "new_event_count": 1,
            "run": {"id": "run1", "candidate_count": 1},
        }

    with patch("app.services.mirofish.alpha_scanner.run_scanner_realtime_monitor_check", side_effect=fake_monitor), \
         patch("scheduler.send_telegram_long", return_value=True) as tg:
        assert scheduler.run_alpha_scanner_monitor() is True
    tg.assert_called_once_with("alpha alert", channel=False)


def test_alpha_scanner_monitor_keeps_event_pending_when_telegram_fails():
    def fake_monitor(*args, send_fn=None, **kwargs):
        assert send_fn("alpha alert") is False
        return {
            "status": "send_failed",
            "new_event_count": 1,
            "run": {"id": "run1", "candidate_count": 1},
        }

    with patch("app.services.mirofish.alpha_scanner.run_scanner_realtime_monitor_check", side_effect=fake_monitor), \
         patch("scheduler.send_telegram_long", return_value=False) as tg:
        assert scheduler.run_alpha_scanner_monitor() is False
    tg.assert_called_once_with("alpha alert", channel=False)


def test_alpha_scanner_monitor_skips_telegram_without_new_events():
    result = {
        "status": "no_new_events",
        "new_event_count": 0,
        "run": {"id": "run1", "candidate_count": 20},
    }
    with patch("app.services.mirofish.alpha_scanner.run_scanner_realtime_monitor_check", return_value=result), \
         patch("scheduler.send_telegram_long") as tg:
        assert scheduler.run_alpha_scanner_monitor() is True
    tg.assert_not_called()


def test_alpha_scanner_monitor_skips_scan_when_source_unchanged():
    result = {
        "status": "unchanged",
        "new_event_count": 0,
        "source_changed": False,
    }
    with patch("app.services.mirofish.alpha_scanner.run_scanner_realtime_monitor_check", return_value=result), \
         patch("scheduler.send_telegram_long") as tg:
        assert scheduler.run_alpha_scanner_monitor() is True
    tg.assert_not_called()


def test_alpha_scanner_monitor_treats_blocked_stale_sources_as_handled():
    result = {
        "status": "blocked",
        "new_event_count": 0,
        "blocked_reason": "source_freshness:stale",
    }
    with patch("app.services.mirofish.alpha_scanner.run_scanner_realtime_monitor_check", return_value=result), \
         patch("scheduler.send_telegram_long") as tg:
        assert scheduler.run_alpha_scanner_monitor() is True
    tg.assert_not_called()


def test_mirofish_workflow_monitor_starts_on_new_events():
    result = {
        "status": "queued",
        "id": "mcp_test",
        "event_count": 3,
        "scanner_run_id": "mfas_test",
    }
    with patch("app.services.mirofish.workflow.run_workflow_monitor_check", return_value=result) as workflow_check:
        assert scheduler.run_mirofish_workflow_monitor() is True
    payload = workflow_check.call_args.args[0]
    assert payload["min_alpha"] == scheduler.Config.MIROFISH_WORKFLOW_MIN_ALPHA
    assert payload["max_risk"] == scheduler.Config.MIROFISH_WORKFLOW_MAX_RISK
    assert payload["actions"] == scheduler.Config.MIROFISH_WORKFLOW_ACTIONS
    assert payload["max_events"] == scheduler.Config.MIROFISH_WORKFLOW_BATCH_SIZE
    assert payload["top_n"] == scheduler.Config.MIROFISH_WORKFLOW_TOP_N
    assert payload["allow_stale_sources"] == scheduler.Config.MIROFISH_WORKFLOW_ALLOW_STALE_SOURCES
    assert payload["sync"] is True
    assert payload["commit_event_state"] is False


def test_mirofish_workflow_monitor_sends_top3_and_commits_after_success(monkeypatch):
    monkeypatch.setattr(scheduler.Config, "MIROFISH_WORKFLOW_TELEGRAM_ENABLED", True)
    monkeypatch.setattr(scheduler.Config, "MIROFISH_WORKFLOW_TELEGRAM_CHANNEL", False)
    result = {
        "ok": True,
        "status": "completed",
        "id": "mcp_test",
        "event_count": 3,
        "scanner_run_id": "mfas_test",
        "top3": [{"symbol": "000001", "target": "Alpha One"}],
        "candidates": [{"symbol": "000001", "action": "BUY_CANDIDATE", "price": {"date": "2026-05-07"}}],
    }
    with patch("app.services.mirofish.workflow.run_workflow_monitor_check", return_value=result), \
         patch("app.services.mirofish.workflow.build_workflow_top3_telegram_message", return_value="top3 message") as build_msg, \
         patch("app.services.mirofish.workflow.commit_workflow_event_state", return_value={"sent_event_count": 1}) as commit_state, \
         patch("scheduler.send_telegram_long", return_value=True) as tg:
        assert scheduler.run_mirofish_workflow_monitor() is True

    build_msg.assert_called_once_with(result)
    tg.assert_called_once_with("top3 message", channel=False)
    committed = commit_state.call_args.args[0]
    assert committed["telegram_sent"] is True
    assert committed["telegram_sent_at"]


def test_mirofish_workflow_monitor_keeps_events_pending_when_top3_telegram_fails(monkeypatch):
    monkeypatch.setattr(scheduler.Config, "MIROFISH_WORKFLOW_TELEGRAM_ENABLED", True)
    result = {
        "ok": True,
        "status": "completed",
        "id": "mcp_test",
        "event_count": 3,
        "scanner_run_id": "mfas_test",
        "top3": [{"symbol": "000001", "target": "Alpha One"}],
        "candidates": [{"symbol": "000001", "action": "BUY_CANDIDATE", "price": {"date": "2026-05-07"}}],
    }
    with patch("app.services.mirofish.workflow.run_workflow_monitor_check", return_value=result), \
         patch("app.services.mirofish.workflow.build_workflow_top3_telegram_message", return_value="top3 message"), \
         patch("app.services.mirofish.workflow.commit_workflow_event_state") as commit_state, \
         patch("scheduler.send_telegram_long", return_value=False) as tg:
        assert scheduler.run_mirofish_workflow_monitor() is False

    tg.assert_called_once()
    commit_state.assert_not_called()


def test_scheduler_registers_single_alpha_realtime_interval(monkeypatch):
    scheduler.schedule.clear()
    monkeypatch.setattr(scheduler.Config, "ALPHA_SCANNER_ENABLED", True)
    monkeypatch.setattr(scheduler.Config, "ALPHA_SCANNER_MONITOR_INTERVAL_MINUTES", 5)
    monkeypatch.setattr(scheduler.Config, "ALPHA_SCANNER_TIMES", [])
    monkeypatch.setattr(scheduler.Config, "MIROFISH_WORKFLOW_ENABLED", False)

    try:
        scheduler.Scheduler().setup_schedules()

        interval_jobs = [
            job for job in scheduler.schedule.jobs
            if job.unit == "minutes" and job.interval == 5
        ]
        assert len(interval_jobs) == 1
    finally:
        scheduler.schedule.clear()


def test_scheduler_registers_mcp_workflow_interval_when_enabled(monkeypatch):
    scheduler.schedule.clear()
    monkeypatch.setattr(scheduler.Config, "ALPHA_SCANNER_ENABLED", True)
    monkeypatch.setattr(scheduler.Config, "MIROFISH_WORKFLOW_ENABLED", True)
    monkeypatch.setattr(scheduler.Config, "ALPHA_SCANNER_MONITOR_INTERVAL_MINUTES", 5)
    monkeypatch.setattr(scheduler.Config, "ALPHA_SCANNER_TIMES", [])

    try:
        scheduler.Scheduler().setup_schedules()

        interval_jobs = [
            job for job in scheduler.schedule.jobs
            if job.unit == "minutes" and job.interval == 5
        ]
        assert len(interval_jobs) == 2
        assert {job.job_func.__name__ for job in interval_jobs} == {
            "run_alpha_scanner_monitor[alpha_scanner_monitor]",
            "run_mirofish_workflow_monitor[mirofish_workflow_monitor]",
        }
    finally:
        scheduler.schedule.clear()

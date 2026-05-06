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
    result = {
        "events": [{"event_key": "000001:BUY_CANDIDATE"}],
        "message": "alpha alert",
        "run": {"id": "run1", "candidate_count": 1},
    }
    with patch("app.services.mirofish.alpha_scanner.run_scanner_alert_check", return_value=result), \
         patch("app.services.mirofish.alpha_scanner.commit_scanner_alert_events") as commit, \
         patch("scheduler.send_telegram_long", return_value=True) as tg:
        assert scheduler.run_alpha_scanner_monitor() is True
    tg.assert_called_once_with("alpha alert", channel=False)
    commit.assert_called_once_with(result)


def test_alpha_scanner_monitor_keeps_event_pending_when_telegram_fails():
    result = {
        "events": [{"event_key": "000001:BUY_CANDIDATE"}],
        "message": "alpha alert",
        "run": {"id": "run1", "candidate_count": 1},
    }
    with patch("app.services.mirofish.alpha_scanner.run_scanner_alert_check", return_value=result), \
         patch("app.services.mirofish.alpha_scanner.commit_scanner_alert_events") as commit, \
         patch("scheduler.send_telegram_long", return_value=False) as tg:
        assert scheduler.run_alpha_scanner_monitor() is False
    tg.assert_called_once_with("alpha alert", channel=False)
    commit.assert_not_called()


def test_alpha_scanner_monitor_skips_telegram_without_new_events():
    result = {
        "events": [],
        "message": "no alert",
        "run": {"id": "run1", "candidate_count": 20},
    }
    with patch("app.services.mirofish.alpha_scanner.run_scanner_alert_check", return_value=result), \
         patch("app.services.mirofish.alpha_scanner.commit_scanner_alert_events") as commit, \
         patch("scheduler.send_telegram_long") as tg:
        assert scheduler.run_alpha_scanner_monitor() is True
    tg.assert_not_called()
    commit.assert_called_once_with(result)

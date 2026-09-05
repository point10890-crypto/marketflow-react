"""Regression tests for Scheduler._with_record.

Background bug: the wrapper used `success = (result is None or result)`,
which silently treated a task function that forgot to `return` as a
success. All real task functions return explicit booleans, so a `None`
return is always a bug — it must be treated as a failure so the retry
+ telegram-alert path fires.

These tests pin the corrected behavior so a future refactor cannot
re-introduce the silent-success regression.
"""
import json
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import scheduler
from scheduler import Scheduler

ORIGINAL_SEND_TELEGRAM = scheduler.send_telegram


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


def test_telegram_automation_defaults_are_fail_closed():
    assert scheduler.Config.ALPHA_SCANNER_TELEGRAM_ENABLED is False
    assert scheduler.Config.MIROFISH_WORKFLOW_TELEGRAM_ENABLED is False
    assert scheduler.Config.ALPHA_SCANNER_CURRENT_TELEGRAM_ENABLED is False


def test_send_telegram_can_skip_failure_queue_for_guard(monkeypatch):
    """Guard alerts must not accumulate duplicate queued messages during Telegram outages."""
    scheduler._telegram_queue.clear()
    monkeypatch.setattr(scheduler, "_flush_telegram_queue", lambda: None)
    monkeypatch.setattr(scheduler, "_try_send_telegram", lambda *args, **kwargs: False)

    assert ORIGINAL_SEND_TELEGRAM("guard down", channel=False, queue_on_failure=False) is False
    assert scheduler._telegram_queue == []


def test_aibrain_service_guard_uses_nonqueued_telegram(monkeypatch):
    """The periodic guard should not queue failed sends and then retry a fresh duplicate."""
    calls = []

    def fake_run_guard(send_fn, *, now=None):
        assert send_fn("guard fail") is False
        return {"overall": "fail", "services": {"decision": {"status": "fail"}}}

    monkeypatch.setattr(
        "app.services.mirofish.service_guard.run_guard",
        fake_run_guard,
    )
    monkeypatch.setattr(
        scheduler,
        "send_telegram",
        lambda message, **kwargs: calls.append((message, kwargs)) or False,
    )

    assert scheduler.run_aibrain_service_guard() is True
    assert calls == [("guard fail", {"channel": False, "queue_on_failure": False})]


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


def test_with_record_can_skip_verify_for_explicit_no_candidate_success():
    result_payload = {
        "ok": True,
        "status": "no_candidates",
        "_scheduler_skip_verify": True,
    }
    verify_calls = []
    rec_calls = []

    with patch("scheduler.record_task_run", side_effect=lambda k: rec_calls.append(k)), \
         patch("scheduler.send_telegram"), \
         patch("scheduler.time.sleep"):
        wrapped = Scheduler._with_record(
            _make_task(result_payload),
            "leading_screener_1507",
            max_retries=0,
            verify_fn=lambda: verify_calls.append("verify") or False,
        )
        result = wrapped()

    assert result == result_payload
    assert verify_calls == []
    assert rec_calls == ["leading_screener_1507"]


def test_leading_screener_refresh_treats_below_threshold_empty_as_handled(monkeypatch):
    payload = {
        "results": [],
        "source_counts": {
            "volume_by_amount": 30,
            "fluctuation": 30,
            "volume_by_surge": 30,
        },
        "market_status": "open",
        "empty_reason": "below_grade_threshold",
        "filter_summary": {
            "scored_candidates": 11,
            "filtered_grade_c": 11,
            "min_grade": "B",
        },
    }

    monkeypatch.setattr("app.services.kis_screener.run_screening", lambda force=True: payload)

    result = scheduler.run_leading_screener_refresh()

    assert result["ok"] is True
    assert result["status"] == "no_candidates"
    assert result["_scheduler_skip_verify"] is True


def test_leading_screener_refresh_rejects_unsaved_quality_result(monkeypatch):
    payload = {
        "results": [{"code": "000001"}],
        "source_counts": {
            "volume_by_amount": 30,
            "fluctuation": 30,
            "volume_by_surge": 30,
        },
        "market_status": "open",
        "data_quality": {
            "status": "partial",
            "safe_to_replace_latest": False,
            "resolved_candidate_coverage": 0.9333,
            "unresolved_potential_codes": ["000002", "000003"],
            "missing_sources": [],
        },
    }

    monkeypatch.setattr("app.services.kis_screener.run_screening", lambda force=True: payload)

    assert scheduler.run_leading_screener_refresh() is False


def test_interval_monitor_uses_cooldown_not_daily_skip(monkeypatch):
    monkeypatch.setattr(scheduler.Config, "ALPHA_SCANNER_MONITOR_INTERVAL_MINUTES", 5)
    calls = []

    def task():
        calls.append("run")
        return True

    task.__name__ = "interval_task"
    with patch("scheduler._was_run_recently", return_value=False) as recent, \
         patch("scheduler._was_run_today", return_value=True) as today:
        wrapped = Scheduler._with_record(task, "alpha_scanner_monitor", max_retries=0)
        result = wrapped()

    assert result is True
    assert calls == ["run"]
    recent.assert_called_once()
    today.assert_not_called()


def test_interval_monitor_skips_inside_cooldown(monkeypatch):
    monkeypatch.setattr(scheduler.Config, "ALPHA_SCANNER_MONITOR_INTERVAL_MINUTES", 5)
    task = _make_task(True, name="interval_task")
    with patch("scheduler._was_run_recently", return_value=True) as recent, \
         patch("scheduler._was_run_today") as today:
        wrapped = Scheduler._with_record(task, "mirofish_workflow_monitor", max_retries=0)
        result = wrapped()

    assert result is None
    recent.assert_called_once()
    today.assert_not_called()


def test_new_interval_jobs_use_cooldown_not_daily_skip(monkeypatch):
    """REGRESSION: 10분 가드·15분 뉴스 스윕이 '오늘 이미 실행' 게이트에 걸려
    하루 1회로 죽으면 안 된다 (kiwoom_ai_theme 에서 이미 고친 버그의 재발)."""
    monkeypatch.setattr(scheduler.Config, "OMNI_NEWS_INTERVAL_MINUTES", 15)
    monkeypatch.setattr(scheduler.Config, "AIBRAIN_GUARD_INTERVAL_MINUTES", 10)
    for key in ("omni_news_sweep", "aibrain_service_guard"):
        calls = []

        def task():
            calls.append("run")
            return True

        task.__name__ = f"interval_{key}"
        with patch("scheduler._was_run_recently", return_value=False) as recent, \
             patch("scheduler._was_run_today", return_value=True) as today:
            wrapped = Scheduler._with_record(task, key, max_retries=0)
            result = wrapped()

        assert result is True, key
        assert calls == ["run"], key
        recent.assert_called_once()
        today.assert_not_called()


def test_new_interval_jobs_skip_inside_cooldown(monkeypatch):
    monkeypatch.setattr(scheduler.Config, "OMNI_NEWS_INTERVAL_MINUTES", 15)
    monkeypatch.setattr(scheduler.Config, "AIBRAIN_GUARD_INTERVAL_MINUTES", 10)
    for key in ("omni_news_sweep", "aibrain_service_guard"):
        task = _make_task(True, name=f"interval_{key}")
        with patch("scheduler._was_run_recently", return_value=True) as recent, \
             patch("scheduler._was_run_today") as today:
            wrapped = Scheduler._with_record(task, key, max_retries=0)
            result = wrapped()

        assert result is None, key
        recent.assert_called_once()
        today.assert_not_called()


def test_omni_news_sweep_reports_failure_when_all_sources_fail():
    """전 소스 실패(프록시/DNS 장애)를 성공으로 기록하면 재시도·알림이 전부 막힌다."""
    result = {
        'status': 'ok', 'started_at': 'x',
        'sources': ['a', 'b'], 'fetched': 0, 'kept': 0, 'saved': 0,
        'errors': {'a': 'ConnectionError: x', 'b': 'ConnectionError: y'},
    }
    with patch("app.services.omni.news_sensor.run_news_sweep", return_value=result):
        assert scheduler.run_omni_news_sweep() is False


def test_omni_news_sweep_partial_source_failure_is_success():
    result = {
        'status': 'ok', 'started_at': 'x',
        'sources': ['a', 'b'], 'fetched': 12, 'kept': 3, 'saved': 3,
        'errors': {'a': 'ConnectionError: x'},
    }
    with patch("app.services.omni.news_sensor.run_news_sweep", return_value=result):
        assert scheduler.run_omni_news_sweep() is True


def test_omni_news_sweep_empty_but_healthy_run_is_success():
    """소스가 다 살아있고 기사만 없는 새벽 스윕은 정상이다."""
    result = {
        'status': 'ok', 'started_at': 'x',
        'sources': ['a', 'b'], 'fetched': 0, 'kept': 0, 'saved': 0, 'errors': {},
    }
    with patch("app.services.omni.news_sensor.run_news_sweep", return_value=result):
        assert scheduler.run_omni_news_sweep() is True


def test_setup_schedules_skips_invalid_prewarm_times(monkeypatch):
    """잘못된 AIBRAIN_PREWARM_TIMES 항목 하나가 데몬 기동을 죽이면 안 된다
    (ScheduleValueError → 워치독 5분 재기동 크래시 루프)."""
    scheduler.schedule.clear()
    monkeypatch.setattr(scheduler.Config, "ALPHA_SCANNER_ENABLED", False)
    monkeypatch.setattr(scheduler.Config, "AIBRAIN_GUARD_ENABLED", True)
    monkeypatch.setattr(scheduler.Config, "AIBRAIN_PREWARM_TIMES",
                        ["8:25", "0825", "25:00", "08:61", "", "08:25"])
    try:
        scheduler.Scheduler().setup_schedules()  # must not raise
        jobs = [j for j in scheduler.schedule.jobs
                if "aibrain_prewarm" in j.job_func.__name__]
        assert len(jobs) == 5  # 유효한 '08:25' 하나 × 평일 5일
        assert all(str(j.at_time) == "08:25:00" for j in jobs)
    finally:
        scheduler.schedule.clear()


def test_missed_catchup_includes_aibrain_prewarm(monkeypatch):
    """고정시각 prewarm 슬롯도 catch-up invariant 에 포함되어야 한다."""
    real_dt = scheduler.datetime

    class FrozenDT(real_dt):
        @classmethod
        def now(cls, tz=None):
            return real_dt(2026, 9, 2, 9, 0)  # 수요일 09:00 — 08:25 슬롯 마감 전

    calls = []
    monkeypatch.setattr(scheduler, "datetime", FrozenDT)
    monkeypatch.setattr(scheduler.Config, "AIBRAIN_GUARD_ENABLED", True)
    monkeypatch.setattr(scheduler.Config, "AIBRAIN_PREWARM_TIMES", ["08:25", "15:05"])
    monkeypatch.setattr(scheduler, "run_aibrain_prewarm",
                        lambda: calls.append("prewarm") or True)
    monkeypatch.setattr(scheduler, "_kr_market_task_allowed", lambda *a, **k: False)
    monkeypatch.setattr(scheduler, "_was_run_recently", lambda *a, **k: True)
    monkeypatch.setattr(scheduler, "_was_run_today",
                        lambda key: not key.startswith("aibrain_prewarm"))
    monkeypatch.setattr(scheduler, "_load_last_run", lambda: {"crypto": "2026-09-02T08:00:00"})
    monkeypatch.setattr(scheduler, "record_task_run", lambda key: None)

    scheduler.check_and_run_missed_tasks()

    # 08:25 슬롯만 복구 (마감 09:55 전), 15:05 슬롯은 아직 예정 전
    assert calls == ["prewarm"]


def test_missed_catchup_respects_prewarm_deadline(monkeypatch):
    real_dt = scheduler.datetime

    class FrozenDT(real_dt):
        @classmethod
        def now(cls, tz=None):
            return real_dt(2026, 9, 2, 11, 0)  # 08:25+90분 마감(09:55) 지난 시각

    calls = []
    monkeypatch.setattr(scheduler, "datetime", FrozenDT)
    monkeypatch.setattr(scheduler.Config, "AIBRAIN_GUARD_ENABLED", True)
    monkeypatch.setattr(scheduler.Config, "AIBRAIN_PREWARM_TIMES", ["08:25"])
    monkeypatch.setattr(scheduler, "run_aibrain_prewarm",
                        lambda: calls.append("prewarm") or True)
    monkeypatch.setattr(scheduler, "_kr_market_task_allowed", lambda *a, **k: False)
    monkeypatch.setattr(scheduler, "_was_run_recently", lambda *a, **k: True)
    monkeypatch.setattr(scheduler, "_was_run_today",
                        lambda key: not key.startswith("aibrain_prewarm"))
    monkeypatch.setattr(scheduler, "_load_last_run", lambda: {"crypto": "2026-09-02T08:00:00"})
    monkeypatch.setattr(scheduler, "record_task_run", lambda key: None)

    scheduler.check_and_run_missed_tasks()

    assert calls == []  # 마감 지남 → 복구하지 않음


@pytest.mark.parametrize(
    ("now_value", "last_success", "worker_result", "expected_runs", "expected_records"),
    [
        ("2026-09-06T19:21:00", "2026-09-06T19:18:00", True, 0, 0),
        ("2026-09-06T23:21:00", "2026-09-06T19:18:00", False, 1, 0),
        ("2026-09-06T23:21:00", "2026-09-06T19:18:00", True, 1, 1),
    ],
)
def test_crypto_missed_catchup_uses_slot_and_records_only_verified_success(
    monkeypatch, now_value, last_success, worker_result, expected_runs, expected_records
):
    real_dt = scheduler.datetime
    frozen = real_dt.fromisoformat(now_value)

    class FrozenDT(real_dt):
        @classmethod
        def now(cls, tz=None):
            return frozen

    runs = []
    records = []
    monkeypatch.setattr(scheduler, "datetime", FrozenDT)
    monkeypatch.setattr(scheduler.Config, "CRYPTO_TIMES", ["00:00", "04:00", "08:00", "12:00", "16:00", "20:00"])
    monkeypatch.setattr(scheduler, "_load_last_run", lambda: {"crypto": last_success})
    monkeypatch.setattr(
        scheduler,
        "run_crypto_pipeline",
        lambda: runs.append("crypto") or worker_result,
    )
    monkeypatch.setattr(scheduler, "record_task_run", lambda key: records.append(key))

    scheduler.check_and_run_missed_tasks()

    assert len(runs) == expected_runs
    assert records.count("crypto") == expected_records


def test_crypto_fixed_wrapper_runs_new_slot_even_inside_old_three_hour_window(monkeypatch):
    real_dt = scheduler.datetime

    class FrozenDT(real_dt):
        @classmethod
        def now(cls, tz=None):
            return real_dt(2026, 9, 3, 20, 0)

    calls = []
    records = []
    monkeypatch.setattr(scheduler, "datetime", FrozenDT)
    monkeypatch.setattr(scheduler.Config, "CRYPTO_TIMES", ["00:00", "04:00", "08:00", "12:00", "16:00", "20:00"])
    monkeypatch.setattr(scheduler, "_load_last_run", lambda: {"crypto": "2026-09-03T19:18:00"})
    monkeypatch.setattr(scheduler, "record_task_run", records.append)
    monkeypatch.setattr(
        scheduler,
        "_was_run_recently",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("crypto used rolling-hour gate")),
    )
    task = lambda: calls.append("run") or True
    task.__name__ = "crypto_task"

    assert Scheduler._with_record(task, "crypto", max_retries=0)() is True
    assert calls == ["run"]
    assert records == ["crypto"]


def test_crypto_wrapper_rechecks_slot_after_busy_or_failed_first_attempt(monkeypatch):
    real_dt = scheduler.datetime

    class FrozenDT(real_dt):
        @classmethod
        def now(cls, tz=None):
            return real_dt(2026, 9, 3, 20, 10)

    last_run = {"crypto": "2026-09-03T19:18:00"}
    calls = []
    monkeypatch.setattr(scheduler, "datetime", FrozenDT)
    monkeypatch.setattr(scheduler.Config, "CRYPTO_TIMES", ["00:00", "04:00", "08:00", "12:00", "16:00", "20:00"])
    monkeypatch.setattr(scheduler, "_load_last_run", lambda: dict(last_run))
    # The autouse fixture already patches this shared stdlib-module attribute.
    # Configure that mock instead of stacking monkeypatch on the same target;
    # mixed fixture teardown order can otherwise leak a MagicMock globally.
    scheduler.time.sleep.side_effect = (
        lambda _seconds: last_run.update(crypto="2026-09-03T20:05:00")
    )
    task = lambda: calls.append("run") or False
    task.__name__ = "crypto_task"

    assert Scheduler._with_record(task, "crypto", max_retries=1, retry_delay=600)() is None
    assert calls == ["run"]


def test_alpha_scanner_monitor_sends_telegram_for_new_events(monkeypatch):
    monkeypatch.setattr(scheduler.Config, "ALPHA_SCANNER_TELEGRAM_ENABLED", True, raising=False)
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


def test_alpha_scanner_monitor_keeps_event_pending_when_telegram_fails(monkeypatch):
    monkeypatch.setattr(scheduler.Config, "ALPHA_SCANNER_TELEGRAM_ENABLED", True, raising=False)
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


def test_alpha_scanner_monitor_default_mode_analyzes_without_transport(monkeypatch):
    monkeypatch.setattr(scheduler.Config, "ALPHA_SCANNER_TELEGRAM_ENABLED", False, raising=False)

    def fake_monitor(*args, send_fn=None, **kwargs):
        assert send_fn is None
        return {
            "status": "pending_send",
            "new_event_count": 1,
            "run": {"id": "run-pending", "candidate_count": 1},
        }

    with patch("app.services.mirofish.alpha_scanner.run_scanner_realtime_monitor_check", side_effect=fake_monitor), \
         patch("scheduler.send_telegram_long") as tg:
        assert scheduler.run_alpha_scanner_monitor() is True

    tg.assert_not_called()


def test_alpha_scanner_monitor_default_mode_does_not_send_error_telegram(monkeypatch):
    monkeypatch.setattr(scheduler.Config, "ALPHA_SCANNER_TELEGRAM_ENABLED", False, raising=False)

    with patch(
        "app.services.mirofish.alpha_scanner.run_scanner_realtime_monitor_check",
        side_effect=RuntimeError("scanner failed"),
    ), patch(
        "scheduler.send_telegram",
        side_effect=lambda *args, **kwargs: pytest.fail("disabled mode sent an error Telegram"),
    ):
        assert scheduler.run_alpha_scanner_monitor() is False


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


def test_alpha_scanner_monitor_never_sends_current_top5_without_new_events(monkeypatch, tmp_path):
    monkeypatch.setattr(scheduler.Config, "ALPHA_SCANNER_CURRENT_TELEGRAM_ENABLED", True)
    monkeypatch.setattr(scheduler.Config, "ALPHA_SCANNER_CURRENT_TELEGRAM_LIMIT", 5)
    monkeypatch.setattr(scheduler.Config, "ALPHA_SCANNER_CURRENT_TELEGRAM_MIN_INTERVAL_MINUTES", 120)
    state_path = tmp_path / "alpha_scanner_current_summary_state.json"
    monkeypatch.setattr(scheduler, "_alpha_current_summary_state_path", lambda: str(state_path))
    result = {
        "status": "no_new_events",
        "new_event_count": 0,
        "run": {
            "id": "run1",
            "candidate_count": 5,
            "candidates": [
                {"rank": 1, "symbol": "000001", "display_name": "Alpha One"},
                {"rank": 2, "symbol": "000002", "display_name": "Alpha Two"},
            ],
        },
    }
    with patch("app.services.mirofish.alpha_scanner.run_scanner_realtime_monitor_check", return_value=result), \
         patch("app.services.mirofish.alpha_scanner.build_scanner_run_telegram_message", return_value="current top5") as build_msg, \
         patch("scheduler.send_telegram_long", return_value=True) as tg:
        assert scheduler.run_alpha_scanner_monitor() is True

    build_msg.assert_not_called()
    tg.assert_not_called()
    assert not state_path.exists()


def test_alpha_scanner_monitor_throttles_duplicate_current_top5(monkeypatch, tmp_path):
    monkeypatch.setattr(scheduler.Config, "ALPHA_SCANNER_TELEGRAM_ENABLED", True, raising=False)
    monkeypatch.setattr(scheduler.Config, "ALPHA_SCANNER_CURRENT_TELEGRAM_ENABLED", True)
    monkeypatch.setattr(scheduler.Config, "ALPHA_SCANNER_CURRENT_TELEGRAM_LIMIT", 5)
    monkeypatch.setattr(scheduler.Config, "ALPHA_SCANNER_CURRENT_TELEGRAM_MIN_INTERVAL_MINUTES", 120)
    state_path = tmp_path / "alpha_scanner_current_summary_state.json"
    monkeypatch.setattr(scheduler, "_alpha_current_summary_state_path", lambda: str(state_path))
    result = {
        "status": "sent",
        "new_event_count": 0,
        "run": {
            "id": "run1",
            "candidate_count": 5,
            "candidates": [
                {"rank": 1, "symbol": "000001", "market": "KOSPI", "action": "WATCH", "horizon": "SWING_5_20D"},
                {"rank": 2, "symbol": "000002", "market": "KOSPI", "action": "WATCH", "horizon": "SWING_5_20D"},
            ],
        },
    }
    with patch("app.services.mirofish.alpha_scanner.run_scanner_realtime_monitor_check", return_value=result), \
         patch("app.services.mirofish.alpha_scanner.build_scanner_run_telegram_message", return_value="current top5") as build_msg, \
         patch("scheduler.send_telegram_long", return_value=True) as tg:
        assert scheduler.run_alpha_scanner_monitor() is True
        assert scheduler.run_alpha_scanner_monitor() is True

    build_msg.assert_called_once_with(result["run"], limit=5)
    tg.assert_called_once_with("current top5", channel=False)


def test_alpha_scanner_monitor_sends_changed_top5_after_cooldown(monkeypatch, tmp_path):
    monkeypatch.setattr(scheduler.Config, "ALPHA_SCANNER_TELEGRAM_ENABLED", True, raising=False)
    monkeypatch.setattr(scheduler.Config, "ALPHA_SCANNER_CURRENT_TELEGRAM_ENABLED", True)
    monkeypatch.setattr(scheduler.Config, "ALPHA_SCANNER_CURRENT_TELEGRAM_LIMIT", 5)
    monkeypatch.setattr(scheduler.Config, "ALPHA_SCANNER_CURRENT_TELEGRAM_MIN_INTERVAL_MINUTES", 120)
    state_path = tmp_path / "alpha_scanner_current_summary_state.json"
    monkeypatch.setattr(scheduler, "_alpha_current_summary_state_path", lambda: str(state_path))
    state_path.write_text(json.dumps({
        "last_sent_at": "2000-01-01T00:00:00",
        "last_sent_date": "2000-01-01",
        "last_fingerprint": "older",
    }), encoding="utf-8")
    result = {
        "status": "sent",
        "new_event_count": 0,
        "run": {
            "id": "run2",
            "candidate_count": 5,
            "candidates": [
                {"rank": 1, "symbol": "000003", "market": "KOSPI", "action": "WATCH", "horizon": "SWING_5_20D"},
            ],
        },
    }
    with patch("app.services.mirofish.alpha_scanner.run_scanner_realtime_monitor_check", return_value=result), \
         patch("app.services.mirofish.alpha_scanner.build_scanner_run_telegram_message", return_value="changed top5") as build_msg, \
         patch("scheduler.send_telegram_long", return_value=True) as tg:
        assert scheduler.run_alpha_scanner_monitor() is True

    build_msg.assert_called_once_with(result["run"], limit=5)
    tg.assert_called_once_with("changed top5", channel=False)


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


def test_orphan_file_audit_runs_in_isolated_subprocess(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        payload = {'ok': True, 'total': 0, 'scanned': 7, 'orphans': []}
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr='')

    monkeypatch.setattr(scheduler.subprocess, 'run', fake_run)
    monkeypatch.setattr(scheduler.Config, 'PYTHON_PATH', 'python-test')

    assert scheduler._run_orphan_file_audit() is True
    assert calls
    cmd, kwargs = calls[0]
    assert cmd[0] == 'python-test'
    assert cmd[1].endswith('scripts\\orphan_file_audit.py') or cmd[1].endswith('scripts/orphan_file_audit.py')
    assert '--json' in cmd
    assert kwargs['cwd'] == scheduler.Config.BASE_DIR
    assert kwargs['env']['PYTHONPATH'] == scheduler.Config.BASE_DIR


def test_orphan_file_audit_reports_subprocess_failure(monkeypatch):
    def fake_run(cmd, **kwargs):
        return SimpleNamespace(returncode=2, stdout='{"ok":false}', stderr='boom')

    monkeypatch.setattr(scheduler.subprocess, 'run', fake_run)

    assert scheduler._run_orphan_file_audit() is False


def test_run_alpha_brain_agent_cycles_invoke_agent(monkeypatch):
    calls = []
    import app.services.mirofish.alpha_brain_agent as agent_mod

    monkeypatch.setattr(
        agent_mod,
        'run_agent_cycle',
        lambda cycle, **_kw: calls.append(cycle) or {'status': 'completed'},
    )

    assert scheduler.run_alpha_brain_agent_evening() is True
    assert scheduler.run_alpha_brain_agent_night() is True
    assert calls == ['evening', 'post_backtest']


def test_run_alpha_brain_agent_reports_failure(monkeypatch):
    import app.services.mirofish.alpha_brain_agent as agent_mod

    monkeypatch.setattr(agent_mod, 'run_agent_cycle', lambda cycle, **_kw: {'status': 'failed'})

    assert scheduler.run_alpha_brain_agent_evening() is False


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
    assert payload["require_buy"] == scheduler.Config.MIROFISH_WORKFLOW_REQUIRE_BUY
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
         patch("app.services.mirofish.alpha_scanner.scanner_alert_delivery_guard", return_value=nullcontext()), \
         patch("app.services.mirofish.alpha_scanner.revalidate_scanner_alert_delivery", return_value={
             "ok": True, "status": "ready", "event_keys": ["000001:BUY_CANDIDATE:2026-05-07"],
             "conflicting_event_keys": [],
         }), \
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
         patch("app.services.mirofish.alpha_scanner.scanner_alert_delivery_guard", return_value=nullcontext()), \
         patch("app.services.mirofish.alpha_scanner.revalidate_scanner_alert_delivery", return_value={
             "ok": True, "status": "ready", "event_keys": ["000001:BUY_CANDIDATE:2026-05-07"],
             "conflicting_event_keys": [],
         }), \
         patch("scheduler.send_telegram_long", return_value=False) as tg:
        assert scheduler.run_mirofish_workflow_monitor() is False

    tg.assert_called_once()
    commit_state.assert_not_called()


def test_mirofish_workflow_monitor_skips_transport_on_canonical_overlap(monkeypatch):
    monkeypatch.setattr(scheduler.Config, "MIROFISH_WORKFLOW_TELEGRAM_ENABLED", True)
    result = {
        "ok": True,
        "status": "completed",
        "id": "mcp_overlap",
        "top3": [{"symbol": "000001", "target": "Alpha One"}],
        "event_candidates": [{
            "symbol": "000001", "action": "BUY_CANDIDATE", "price": {"date": "2026-05-07"},
        }],
    }
    overlap = {
        "ok": False,
        "status": "event_overlap",
        "event_keys": ["000001:BUY_CANDIDATE:2026-05-07"],
        "conflicting_event_keys": ["000001:BUY_CANDIDATE:2026-05-07"],
    }
    with patch("app.services.mirofish.workflow.run_workflow_monitor_check", return_value=result), \
         patch("app.services.mirofish.workflow.build_workflow_top3_telegram_message", return_value="top3 message"), \
         patch("app.services.mirofish.workflow.commit_workflow_event_state", return_value={}) as commit_state, \
         patch("app.services.mirofish.alpha_scanner.scanner_alert_delivery_guard", return_value=nullcontext()), \
         patch("app.services.mirofish.alpha_scanner.revalidate_scanner_alert_delivery", return_value=overlap), \
         patch("scheduler.send_telegram_long") as tg:
        assert scheduler.run_mirofish_workflow_monitor() is True

    tg.assert_not_called()
    commit_state.assert_called_once_with(result, sync_dashboard=False)


def test_mirofish_workflow_monitor_disabled_commits_only_workflow_dedupe(monkeypatch):
    monkeypatch.setattr(scheduler.Config, "MIROFISH_WORKFLOW_TELEGRAM_ENABLED", False)
    result = {
        "ok": True,
        "status": "completed",
        "id": "mcp_disabled",
        "top3": [{"symbol": "000001", "target": "Alpha One"}],
        "event_candidates": [{
            "symbol": "000001", "action": "BUY_CANDIDATE", "price": {"date": "2026-05-07"},
        }],
    }
    with patch("app.services.mirofish.workflow.run_workflow_monitor_check", return_value=result), \
         patch("app.services.mirofish.workflow.commit_workflow_event_state", return_value={}) as commit_state, \
         patch("scheduler.send_telegram_long") as tg:
        assert scheduler.run_mirofish_workflow_monitor() is True

    tg.assert_not_called()
    commit_state.assert_called_once_with(result, sync_dashboard=False)


def test_mirofish_workflow_monitor_disabled_does_not_send_error_telegram(monkeypatch):
    monkeypatch.setattr(scheduler.Config, "MIROFISH_WORKFLOW_TELEGRAM_ENABLED", False)

    with patch(
        "app.services.mirofish.workflow.run_workflow_monitor_check",
        side_effect=RuntimeError("workflow failed"),
    ), patch(
        "scheduler.send_telegram",
        side_effect=lambda *args, **kwargs: pytest.fail("disabled workflow sent an error Telegram"),
    ):
        assert scheduler.run_mirofish_workflow_monitor() is False


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


def test_scheduler_registers_alpha_backtest_daily(monkeypatch):
    scheduler.schedule.clear()
    monkeypatch.setattr(scheduler.Config, "ALPHA_BACKTEST_ENABLED", True)
    monkeypatch.setattr(scheduler.Config, "ALPHA_BACKTEST_TIME", "23:11")
    monkeypatch.setattr(scheduler.Config, "ALPHA_SCANNER_ENABLED", False)

    try:
        scheduler.Scheduler().setup_schedules()

        jobs = [
            job for job in scheduler.schedule.jobs
            if job.job_func.__name__ == "run_alpha_backtest_daily[alpha_backtest_daily]"
        ]
        assert len(jobs) == 1
        assert str(jobs[0].at_time) == "23:11:00"
    finally:
        scheduler.schedule.clear()


def test_lotto_runner_uses_bounded_subprocess(monkeypatch):
    completed = SimpleNamespace(returncode=0)
    run_calls = []

    def fake_run(cmd, **kwargs):
        run_calls.append((cmd, kwargs))
        return completed

    monkeypatch.setattr(scheduler.subprocess, "run", fake_run)
    monkeypatch.setattr(scheduler, "send_telegram", lambda *args, **kwargs: True)
    monkeypatch.setattr(scheduler.Config, "PYTHON_PATH", "python-test")

    assert scheduler.run_lotto_analysis_bounded() is True
    cmd, kwargs = run_calls[0]
    assert cmd[0] == "python-test"
    assert cmd[1].endswith("scripts\\lotto_analysis.py") or cmd[1].endswith("scripts/lotto_analysis.py")
    assert kwargs["timeout"] == 1200
    assert kwargs["check"] is False


def test_scheduler_registers_saturday_lotto_recovery(monkeypatch):
    scheduler.schedule.clear()
    monkeypatch.setattr(scheduler.Config, "ALPHA_SCANNER_ENABLED", False)

    try:
        scheduler.Scheduler().setup_schedules()
        jobs = [
            job for job in scheduler.schedule.jobs
            if job.job_func.__name__ == "run_lotto_analysis_bounded[lotto_analysis_recovery]"
        ]
        assert len(jobs) == 1
        assert str(jobs[0].at_time) == "09:00:00"
    finally:
        scheduler.schedule.clear()

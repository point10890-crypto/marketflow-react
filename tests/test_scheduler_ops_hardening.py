import logging
from pathlib import Path
from types import SimpleNamespace

import scheduler


_GIT_SYNC_ENV = "MARKETFLOW_SCHEDULER_GIT_SYNC_ENABLED"


def test_auto_git_push_intentionally_skips_without_explicit_opt_in(
    monkeypatch,
    caplog,
):
    monkeypatch.delenv(_GIT_SYNC_ENV, raising=False)
    git_calls = []
    monkeypatch.setattr(
        scheduler.subprocess,
        "run",
        lambda *args, **kwargs: git_calls.append((args, kwargs)),
    )

    with caplog.at_level(logging.INFO, logger=scheduler.logger.name):
        result = scheduler.auto_git_push("vcp")

    assert result is True
    assert git_calls == []
    assert "auto git push intentionally skipped" in caplog.text.lower()


def test_remote_git_pull_intentionally_skips_without_explicit_opt_in(
    monkeypatch,
    caplog,
):
    monkeypatch.delenv(_GIT_SYNC_ENV, raising=False)
    git_calls = []
    monkeypatch.setattr(
        scheduler.subprocess,
        "run",
        lambda *args, **kwargs: git_calls.append((args, kwargs)),
    )

    with caplog.at_level(logging.INFO, logger=scheduler.logger.name):
        scheduler._sync_code_from_remote()

    assert git_calls == []
    assert "remote git pull intentionally skipped" in caplog.text.lower()


def test_git_automation_runs_only_after_explicit_opt_in(monkeypatch):
    monkeypatch.setenv(_GIT_SYNC_ENV, "true")
    git_commands = []

    def fake_git_run(command, *args, **kwargs):
        git_commands.append(command)
        if command[:3] == ["git", "status", "--porcelain"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if command[:4] == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout="not-main\n", stderr="")
        raise AssertionError(f"unexpected git command: {command}")

    monkeypatch.setattr(scheduler.subprocess, "run", fake_git_run)

    assert scheduler.auto_git_push("vcp") is True
    scheduler._sync_code_from_remote()

    assert git_commands == [
        ["git", "status", "--porcelain"],
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
    ]


def test_remote_git_pull_does_not_race_an_active_git_operation(monkeypatch, caplog):
    class BusyGitLock:
        def __init__(self):
            self.acquire_timeouts = []

        def acquire(self, *, timeout):
            self.acquire_timeouts.append(timeout)
            return False

        def release(self):
            raise AssertionError("unacquired Git lock was released")

    busy_lock = BusyGitLock()
    git_calls = []
    monkeypatch.setenv(_GIT_SYNC_ENV, "true")
    monkeypatch.setattr(scheduler, "_git_lock", busy_lock)
    monkeypatch.setattr(
        scheduler.subprocess,
        "run",
        lambda *args, **kwargs: git_calls.append((args, kwargs)),
    )

    with caplog.at_level(logging.WARNING, logger=scheduler.logger.name):
        scheduler._sync_code_from_remote()

    assert busy_lock.acquire_timeouts == [120]
    assert git_calls == []
    assert "git sync lock timeout" in caplog.text.lower()


def test_16h_vcp_batch_leaves_crypto_to_dedicated_pipeline(monkeypatch):
    scan_calls = []
    telegram_messages = []

    monkeypatch.setattr(
        scheduler,
        "run_vcp_signal_scan",
        lambda *, send_alert: scan_calls.append(("signal", "KR", send_alert)) or True,
    )
    monkeypatch.setattr(
        scheduler,
        "run_vcp_enhanced_scan",
        lambda market: scan_calls.append(("enhanced", market)) or True,
    )
    monkeypatch.setattr(
        scheduler,
        "send_telegram",
        lambda message, *, channel: telegram_messages.append((message, channel)),
    )

    assert scheduler.run_vcp_all_markets(skip_sync=True) is True
    assert scan_calls == [
        ("signal", "KR", True),
        ("enhanced", "KR"),
        ("enhanced", "US"),
    ]
    assert len(telegram_messages) == 1
    assert "3/3" in telegram_messages[0][0]


def test_16h_vcp_verifier_does_not_depend_on_crypto_artifact(monkeypatch, tmp_path):
    for filename in ("vcp_kr_latest.json", "vcp_us_latest.json"):
        Path(tmp_path, filename).write_text('{"signals": []}', encoding="utf-8")

    monkeypatch.setattr(scheduler.Config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(scheduler.Config, "ALPHA_SCANNER_ENABLED", False)
    monkeypatch.setattr(scheduler, "build_freshness", lambda *_args, **_kwargs: {"is_stale": False})
    monkeypatch.setattr(scheduler, "run_vcp_all_markets", lambda: True)
    monkeypatch.setattr(scheduler, "_was_run_today", lambda _task_key: False)
    monkeypatch.setattr(scheduler, "record_task_run", lambda _task_key: None)
    monkeypatch.setattr(scheduler, "send_telegram", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(scheduler.time, "sleep", lambda _seconds: None)
    scheduler.schedule.clear()

    try:
        scheduler.Scheduler().setup_schedules()
        jobs = [
            job
            for job in scheduler.schedule.jobs
            if job.job_func.__name__.endswith("[vcp_all]")
        ]

        assert len(jobs) == 5
        assert jobs[0].job_func() is True
    finally:
        scheduler.schedule.clear()


def test_full_update_reports_disabled_git_as_intentional_skip(monkeypatch):
    messages = []
    monkeypatch.delenv(_GIT_SYNC_ENV, raising=False)
    monkeypatch.setattr(scheduler, "run_us_market_update", lambda *, skip_sync: True)
    monkeypatch.setattr(scheduler, "run_kr_full_update", lambda *, skip_sync: True)
    monkeypatch.setattr(scheduler, "run_vcp_all_markets", lambda *, skip_sync: True)
    monkeypatch.setattr(scheduler, "run_crypto_pipeline", lambda *, skip_sync: True)
    monkeypatch.setattr(
        scheduler,
        "send_telegram",
        lambda message, *, channel: messages.append((message, channel)),
    )

    assert scheduler.run_full_update() is True
    assert len(messages) == 1
    assert "Git 자동 동기화 비활성 (의도적 스킵)" in messages[0][0]
    assert "Git 푸시 완료" not in messages[0][0]


def _configure_only_vcp_catch_up(monkeypatch, task_result):
    real_datetime = scheduler.datetime

    class FrozenDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return real_datetime(2026, 9, 3, 16, 1)

    records = []
    monkeypatch.setattr(scheduler, "datetime", FrozenDatetime)
    monkeypatch.setattr(scheduler.Config, "AIBRAIN_GUARD_ENABLED", False)
    monkeypatch.setattr(scheduler, "_kr_market_task_allowed", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(scheduler, "_jongga_artifact_is_today", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        scheduler,
        "_was_run_today",
        lambda task_key: task_key != "vcp_all",
    )
    monkeypatch.setattr(scheduler, "run_vcp_all_markets", lambda: task_result)
    monkeypatch.setattr(scheduler, "_crypto_slot_due", lambda *_args, **_kwargs: (False, None))
    monkeypatch.setattr(scheduler, "record_task_run", records.append)
    return records


def test_vcp_false_catch_up_is_not_recorded_as_recovered(monkeypatch, caplog):
    records = _configure_only_vcp_catch_up(monkeypatch, False)

    with caplog.at_level(logging.ERROR, logger=scheduler.logger.name):
        scheduler.check_and_run_missed_tasks()

    assert "vcp_all" not in records
    assert "복구 실패: VCP KR·US" in caplog.text


def test_vcp_none_catch_up_preserves_legacy_success_contract(monkeypatch):
    records = _configure_only_vcp_catch_up(monkeypatch, None)

    scheduler.check_and_run_missed_tasks()

    assert records == ["vcp_all"]


def test_vcp_zero_catch_up_is_not_recorded_as_recovered(monkeypatch):
    records = _configure_only_vcp_catch_up(monkeypatch, 0)

    scheduler.check_and_run_missed_tasks()

    assert "vcp_all" not in records

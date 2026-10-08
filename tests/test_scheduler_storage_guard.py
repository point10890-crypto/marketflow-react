"""Disk exhaustion must stop collection before spending provider calls/retries."""
import errno
import json
import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import scheduler


GIB = 1_073_741_824
ENV_NAME = 'MARKETFLOW_SCHEDULER_MIN_FREE_BYTES'


@pytest.fixture
def isolated_scheduler(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_NAME, raising=False)
    monkeypatch.setattr(scheduler.Config, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(scheduler.Config, 'DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setattr(scheduler.Config, 'LOG_DIR', str(tmp_path / 'logs'))
    last_run = tmp_path / 'scheduler_last_run.json'
    original = b'{"completed_task": "2026-10-08T09:00:00"}\n'
    last_run.write_bytes(original)
    monkeypatch.setattr(scheduler, '_LAST_RUN_FILE', str(last_run))
    sleep, notify = Mock(), Mock(return_value=True)
    monkeypatch.setattr(scheduler.time, 'sleep', sleep)
    monkeypatch.setattr(scheduler, 'send_telegram', notify)
    return SimpleNamespace(root=tmp_path, last_run=last_run, original=original,
                           sleep=sleep, notify=notify)


def disk(monkeypatch, free):
    monkeypatch.setattr('shutil.disk_usage', lambda _path: SimpleNamespace(
        total=10 * GIB, used=10 * GIB-free, free=free))


@pytest.mark.parametrize('free', [0, GIB-1])
def test_low_disk_never_runs_task_or_retries_and_preserves_successes(
        isolated_scheduler, monkeypatch, caplog, free):
    disk(monkeypatch, free)
    calls = []

    def collect():
        calls.append('provider')
        return True

    with caplog.at_level(logging.ERROR, logger=scheduler.logger.name):
        result = scheduler.Scheduler._with_record(
            collect, 'omni_news_sweep', max_retries=1, retry_delay=120, force=True)()

    assert result is False
    assert calls == []
    assert isolated_scheduler.last_run.read_bytes() == isolated_scheduler.original
    isolated_scheduler.sleep.assert_not_called()
    isolated_scheduler.notify.assert_not_called()
    assert 'low_space' in caplog.text
    assert 'omni_news_sweep' in caplog.text
    assert f'free_bytes={free}' in caplog.text


def test_exact_threshold_allows_success_and_records_it(isolated_scheduler, monkeypatch):
    disk(monkeypatch, GIB)
    calls = []

    def collect():
        calls.append('provider')
        return True

    assert scheduler.Scheduler._with_record(collect, 'guarded_task', force=True)() is True
    assert calls == ['provider']
    saved = json.loads(isolated_scheduler.last_run.read_text())
    assert saved['completed_task'] == '2026-10-08T09:00:00'
    assert saved['guarded_task']


def test_healthy_disk_keeps_existing_retry_behavior(isolated_scheduler, monkeypatch):
    disk(monkeypatch, 2 * GIB)
    calls = []

    def collect():
        calls.append('provider')
        return len(calls) == 2

    assert scheduler.Scheduler._with_record(
        collect, 'guarded_task', max_retries=1, retry_delay=60, force=True)() is True
    assert calls == ['provider', 'provider']
    isolated_scheduler.sleep.assert_called_once_with(60)


def test_disk_filling_during_failed_attempt_stops_before_retry_sleep(
        isolated_scheduler, monkeypatch, caplog):
    disk(monkeypatch, 2 * GIB)
    calls = []

    def collect():
        calls.append('provider')
        disk(monkeypatch, 0)
        return False

    with caplog.at_level(logging.ERROR, logger=scheduler.logger.name):
        result = scheduler.Scheduler._with_record(
            collect, 'guarded_task', max_retries=1, retry_delay=60, force=True)()
    assert result is False
    assert calls == ['provider']
    isolated_scheduler.sleep.assert_not_called()
    isolated_scheduler.notify.assert_not_called()
    assert isolated_scheduler.last_run.read_bytes() == isolated_scheduler.original
    assert 'low_space' in caplog.text


def test_disk_filling_during_retry_delay_prevents_second_provider_call(
        isolated_scheduler, monkeypatch):
    disk(monkeypatch, 2 * GIB)
    isolated_scheduler.sleep.side_effect = lambda _seconds: disk(monkeypatch, 0)
    calls = []

    def collect():
        calls.append('provider')
        return False

    assert scheduler.Scheduler._with_record(
        collect, 'guarded_task', max_retries=1, retry_delay=60, force=True)() is False
    assert calls == ['provider']
    assert isolated_scheduler.last_run.read_bytes() == isolated_scheduler.original


def test_storage_inspection_failure_is_classified_without_raw_error(
        isolated_scheduler, monkeypatch, caplog):
    def unavailable(_path):
        raise PermissionError('sensitive-provider-body')

    monkeypatch.setattr('shutil.disk_usage', unavailable)
    calls = []

    def collect():
        calls.append('provider')
        return True

    with caplog.at_level(logging.ERROR, logger=scheduler.logger.name):
        result = scheduler.Scheduler._with_record(collect, 'guarded_task', force=True)()
    assert result is False
    assert calls == []
    assert 'unavailable' in caplog.text
    assert 'sensitive-provider-body' not in caplog.text
    assert isolated_scheduler.last_run.read_bytes() == isolated_scheduler.original
    isolated_scheduler.sleep.assert_not_called()


@pytest.mark.parametrize('configured', ['0', '-1', 'not-a-number', '1.5'])
def test_invalid_threshold_blocks_execution(isolated_scheduler, monkeypatch, configured, caplog):
    monkeypatch.setenv(ENV_NAME, configured)
    disk(monkeypatch, 2 * GIB)
    calls = []

    def collect():
        calls.append('provider')
        return True

    with caplog.at_level(logging.ERROR, logger=scheduler.logger.name):
        assert scheduler.Scheduler._with_record(collect, 'guarded_task', force=True)() is False
    assert calls == []
    assert 'invalid_config' in caplog.text
    assert isolated_scheduler.last_run.read_bytes() == isolated_scheduler.original


def test_explicit_positive_threshold_is_respected(isolated_scheduler, monkeypatch):
    monkeypatch.setenv(ENV_NAME, '2048')
    disk(monkeypatch, 2048)
    assert scheduler.Scheduler._with_record(lambda: True, 'guarded_task', force=True)() is True


@pytest.mark.parametrize('error', [OSError(errno.ENOSPC, 'sensitive-error'),
                                 OSError(errno.ENOSPC, 'disk full')])
def test_enospc_after_preflight_does_not_repeat_collection(
        isolated_scheduler, monkeypatch, caplog, error):
    disk(monkeypatch, 2 * GIB)
    calls = []

    def collect():
        calls.append('provider')
        raise error

    with caplog.at_level(logging.ERROR, logger=scheduler.logger.name):
        assert scheduler.Scheduler._with_record(
            collect, 'guarded_task', max_retries=1, retry_delay=60, force=True)() is False
    assert calls == ['provider']
    assert 'disk_full' in caplog.text
    assert 'sensitive-error' not in caplog.text
    assert isolated_scheduler.last_run.read_bytes() == isolated_scheduler.original
    isolated_scheduler.sleep.assert_not_called()
    isolated_scheduler.notify.assert_not_called()


def test_missing_output_directories_probe_existing_ancestor(isolated_scheduler, monkeypatch):
    seen = []

    def usage(path):
        assert path.exists()
        seen.append(path)
        return SimpleNamespace(total=10 * GIB, used=8 * GIB, free=2 * GIB)

    monkeypatch.setattr('shutil.disk_usage', usage)
    assert scheduler.Scheduler._with_record(lambda: True, 'guarded_task', force=True)() is True
    assert seen and all(path == isolated_scheduler.root for path in seen)
    assert not (isolated_scheduler.root / 'data').exists()
    assert not (isolated_scheduler.root / 'logs').exists()


def test_separate_log_volume_must_also_have_room(isolated_scheduler, monkeypatch):
    log_dir = isolated_scheduler.root / 'logs'
    log_dir.mkdir()

    def usage(path):
        return SimpleNamespace(total=10 * GIB, used=10 * GIB if path == log_dir else 8 * GIB,
                               free=0 if path == log_dir else 2 * GIB)

    monkeypatch.setattr('shutil.disk_usage', usage)
    calls = []

    def collect():
        calls.append('provider')
        return True

    assert scheduler.Scheduler._with_record(collect, 'guarded_task', force=True)() is False
    assert calls == []
    assert isolated_scheduler.last_run.read_bytes() == isolated_scheduler.original


def test_enospc_during_result_verification_stops_without_recollecting(
        isolated_scheduler, monkeypatch, caplog):
    disk(monkeypatch, 2 * GIB)
    calls = []

    def collect():
        calls.append('provider')
        return True

    def verify():
        raise OSError(errno.ENOSPC, 'sensitive-verification-body')

    with caplog.at_level(logging.ERROR, logger=scheduler.logger.name):
        assert scheduler.Scheduler._with_record(
            collect, 'guarded_task', max_retries=1, retry_delay=60,
            verify_fn=verify, force=True)() is False
    assert calls == ['provider']
    assert 'disk_full' in caplog.text
    assert 'sensitive-verification-body' not in caplog.text
    assert isolated_scheduler.last_run.read_bytes() == isolated_scheduler.original
    isolated_scheduler.sleep.assert_not_called()
    isolated_scheduler.notify.assert_not_called()


@pytest.mark.parametrize('kind', ['windows', 'sqlite'])
def test_native_disk_full_codes_also_prevent_collection_retries(
        isolated_scheduler, monkeypatch, kind):
    disk(monkeypatch, 2 * GIB)
    if kind == 'windows':
        error = OSError('full')
        error.winerror = 112
    else:
        import sqlite3
        error = sqlite3.OperationalError('full')
        error.sqlite_errorcode = sqlite3.SQLITE_FULL
    calls = []

    def collect():
        calls.append('provider')
        raise error

    assert scheduler.Scheduler._with_record(
        collect, 'guarded_task', max_retries=1, force=True)() is False
    assert calls == ['provider']
    isolated_scheduler.sleep.assert_not_called()
    isolated_scheduler.notify.assert_not_called()


def test_recovery_reuses_completed_stage_without_a_failed_success_record(
        isolated_scheduler, monkeypatch):
    data_dir = isolated_scheduler.root / 'data'
    data_dir.mkdir()
    completed_stage = data_dir / 'completed.json'
    original = b'{"stage":"price","state":"complete","sha256":"original"}\n'
    completed_stage.write_bytes(original)
    calls = []

    def collect():
        calls.append('remaining_stage')
        assert completed_stage.read_bytes() == original
        return True

    wrapped = scheduler.Scheduler._with_record(collect, 'guarded_task', force=True)
    disk(monkeypatch, 0)
    assert wrapped() is False
    assert calls == []
    assert isolated_scheduler.last_run.read_bytes() == isolated_scheduler.original
    disk(monkeypatch, 2 * GIB)
    assert wrapped() is True
    assert calls == ['remaining_stage']
    assert completed_stage.read_bytes() == original

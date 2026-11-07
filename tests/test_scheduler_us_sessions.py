"""US jobs follow completed NYSE sessions, including Friday's KST Saturday."""
from datetime import datetime

import pytest

import scheduler


@pytest.fixture(autouse=True)
def _no_notifications(monkeypatch):
    monkeypatch.setattr(scheduler, 'send_telegram', lambda *a, **k: True)


@pytest.mark.parametrize(('now', 'expected'), [
    (datetime(2026, 11, 7, 7), '2026-11-06'),
    (datetime(2026, 7, 11, 7), '2026-07-10'),
    (datetime(2026, 11, 7, 6, 59), None),
    (datetime(2026, 7, 11, 4, 59), None),
    (datetime(2026, 11, 8, 7), None),
    (datetime(2026, 11, 9, 7), None),
    (datetime(2026, 11, 27, 7), None),  # Thanksgiving
    (datetime(2026, 7, 4, 7), None),  # July 3 observed holiday
])
def test_us_post_close_session_uses_new_york_calendar(now, expected):
    helper = getattr(scheduler, '_us_completed_session_for_scheduler', None)
    assert callable(helper), 'US scheduling needs an explicit completed-session gate'
    assert helper(now) == expected


def test_us_jobs_register_daily_after_close_and_publish_calendar(monkeypatch):
    monkeypatch.setattr(scheduler.Config, 'US_UPDATE_TIME', '07:00')
    monkeypatch.setattr(scheduler.Config, 'US_AI_CHART_TIME', '07:30')
    monkeypatch.setattr(scheduler.Config, 'US_TRACK_TIME', '09:30')
    scheduler.schedule.clear()
    try:
        scheduler.Scheduler().setup_schedules()
        for key, expected in [('us_market', '07:00'), ('us_ai_chart', '07:30'),
                              ('us_vcp', scheduler.Config.US_VCP_TIME), ('us_track', '09:30')]:
            jobs = [j for j in scheduler.schedule.jobs if j.job_func.__name__.endswith(f'[{key}]')]
            assert len(jobs) == 1, key
            assert jobs[0].unit == 'days' and jobs[0].start_day is None
            assert str(jobs[0].at_time) == expected + ':00'
            entry = scheduler._build_job_registry()[key]
            assert entry['calendar'] == 'us_post_close'
            assert entry['schedule'].startswith('매일 ' + expected)
        assert all(j['calendar'] == 'us_post_close' for j in scheduler.describe_jobs()
                   if j['key'] in ('us_market', 'us_ai_chart', 'us_track', 'us_vcp'))
    finally:
        scheduler.schedule.clear()


def test_non_session_us_wrapper_does_not_run_or_record_success(monkeypatch):
    calls = []
    monkeypatch.setattr(scheduler, '_us_completed_session_for_scheduler', lambda *_: None, raising=False)
    monkeypatch.setattr(scheduler, 'record_task_run', lambda *_: calls.append('record'))
    monkeypatch.setattr(scheduler, '_was_run_today', lambda *_: False)
    wrapped = scheduler.Scheduler._with_record(lambda: calls.append('run'), 'us_market', max_retries=0)
    wrapped()
    assert calls == []


def test_saturday_us_catchup_uses_configured_post_close_slot(monkeypatch):
    real_datetime = datetime

    class FrozenDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 7, 7, 5)

    calls = []
    monkeypatch.setattr(scheduler, 'datetime', FrozenDatetime)
    monkeypatch.setattr(scheduler.Config, 'US_UPDATE_TIME', '07:00')
    monkeypatch.setattr(scheduler.Config, 'AIBRAIN_GUARD_ENABLED', False)
    monkeypatch.setattr(scheduler, '_was_run_today', lambda key: key != 'us_market')
    monkeypatch.setattr(scheduler, 'run_us_market_update', lambda: calls.append('run') or True)
    monkeypatch.setattr(scheduler, 'record_task_run', lambda key: calls.append(key))
    monkeypatch.setattr(scheduler, '_crypto_slot_due', lambda *a, **k: (False, None))
    scheduler.check_and_run_missed_tasks()
    assert calls == ['run', 'us_market']


@pytest.mark.parametrize(('configured', 'earliest', 'expected'), [
    ('04:00', '07:00', '07:00'), ('04:30', '07:30', '07:30'),
    ('08:15', '07:00', '08:15'), ('bad', '07:00', '07:00'),
])
def test_legacy_us_pre_close_overrides_migrate(configured, earliest, expected):
    assert scheduler._us_post_close_time(configured, earliest) == expected

"""Scheduler monitoring follows due occurrences without manufacturing success."""
from datetime import datetime
import json

import pytest

from app.services.control_center import local_checks
from app.services.control_center.model import KST


def kst(value):
    return datetime.fromisoformat(value).replace(tzinfo=KST)


@pytest.mark.parametrize('schedule,last_run,expected', [
    ('매일 23:00', '2026-10-12T23:04:59', 'fail'),
    ('매일 23:30', '2026-10-30T23:48:12', 'fail'),
    ('매일 09:00', '2026-11-07T09:00:37', 'ok'),
    ('금요일 17:00', '2026-11-06T17:20:42', 'ok'),
    ('토요일 21:10', '2026-11-07T21:10:45', 'ok'),
    ('토요일 10:00', '2026-11-07T10:00:10', 'ok'),
])
def test_midnight_uses_latest_due_occurrence(schedule, last_run, expected):
    job = {'key': 'test', 'schedule': schedule, 'market': 'KR'}
    result = local_checks.evaluate_job(job, {'test': last_run}, kst('2026-11-08T00:42:00'))
    assert result.status == expected
    if expected == 'fail':
        assert '2026-11-07' in result.detail


@pytest.mark.parametrize('now,last_run,expected', [
    ('2026-11-06T16:00:00', '2026-10-30T17:01:00', 'ok'),
    ('2026-11-06T16:00:00', '2026-10-23T17:01:00', 'fail'),
    ('2026-11-06T17:10:00', '2026-10-30T17:01:00', 'ok'),
    ('2026-11-06T17:46:00', '2026-10-30T17:01:00', 'fail'),
    ('2026-11-06T17:46:00', '2026-11-06T17:05:00', 'ok'),
    ('2026-11-08T01:00:00', '2026-11-13T17:05:00', 'unknown'),
])
def test_weekly_grace_does_not_hide_a_stale_previous_week(now, last_run, expected):
    job = {'key': 'weekly', 'schedule': '금요일 17:00', 'market': 'System'}
    assert local_checks.evaluate_job(job, {'weekly': last_run}, kst(now)).status == expected


@pytest.mark.parametrize('now,last_run,expected', [
    ('2026-11-09T10:10:00', '2026-11-09T10:01:00', 'ok'),
    ('2026-11-09T10:10:00', '2026-11-06T15:20:00', 'fail'),
    ('2026-11-09T10:10:00', None, 'unknown'),
    ('2026-11-09T10:10:00', '2026-11-09T10:11:00', 'unknown'),
    ('2026-11-08T10:10:00', None, 'skipped'),
    ('2026-11-09T09:00:00', None, 'skipped'),
    ('2026-11-09T15:26:00', None, 'skipped'),
    ('2026-12-25T10:10:00', None, 'skipped'),
])
def test_window_schedule_requires_evidence_only_inside_trading_window(now, last_run, expected):
    job = {'key': 'theme', 'schedule': '평일 09:10~15:25 (15분)', 'market': 'KR'}
    runs = {'theme': last_run} if last_run else {}
    assert local_checks.evaluate_job(job, runs, kst(now)).status == expected


def test_preopen_uses_previous_trading_day_across_holiday():
    job = {'key': 'daily', 'schedule': '평일 09:00', 'market': 'KR'}
    now = kst('2026-12-28T08:00:00')  # Friday Dec 25 is a KR holiday.
    assert local_checks.evaluate_job(job, {'daily': '2026-12-24T09:02:00'}, now).status == 'ok'
    assert local_checks.evaluate_job(job, {'daily': '2026-12-23T09:02:00'}, now).status == 'fail'


@pytest.mark.parametrize('last_run', ['2026-11-08T09:01:00', 'not-a-date'])
def test_future_or_malformed_success_cannot_make_pending_job_healthy(last_run):
    job = {'key': 'daily', 'schedule': '매일 09:00'}
    assert local_checks.evaluate_job(job, {'daily': last_run}, kst('2026-11-08T00:30:00')).status == 'unknown'


def test_shared_record_cannot_prove_every_slot_after_midnight():
    job = {'key': 'daily', 'schedule': '매일 09:00, 16:00'}
    result = local_checks.evaluate_job(job, {'daily': '2026-11-07T16:01:00'}, kst('2026-11-08T00:30:00'))
    assert result.status == 'unknown'
    assert result.value['unverified'] == ['09:00']


def test_separate_records_can_prove_prior_day_slots():
    job = {'key': 'daily', 'schedule': '매일 09:00, 16:00', 'record_keys': ['morning', 'closing']}
    runs = {'morning': '2026-11-07T09:01:00', 'closing': '2026-11-07T16:01:00'}
    result = local_checks.evaluate_job(job, runs, kst('2026-11-08T00:30:00'))
    assert result.status == 'ok'


def test_duplicate_record_keys_do_not_invent_separate_slot_evidence():
    job = {'key': 'daily', 'schedule': '매일 09:00, 16:00', 'record_keys': ['same', 'same']}
    result = local_checks.evaluate_job(job, {'same': '2026-11-07T16:01:00'}, kst('2026-11-08T00:30:00'))
    assert result.status == 'unknown'


@pytest.mark.parametrize('schedule', ['매 0분', '매일 25:00, 09:00', '평일 15:25~09:10 (15분)',
                                      '평일 09:10~15:25 (0분)', '매일 09:00 nonsense'])
def test_invalid_schedule_cannot_be_partly_accepted(schedule):
    assert local_checks.parse_schedule(schedule)['kind'] == 'unknown'


@pytest.mark.parametrize('now,last_run,expected', [
    ('2026-11-08T00:42:00', '2026-11-07T07:10:00', 'ok'),
    ('2026-11-08T00:42:00', '2026-11-06T07:10:00', 'fail'),
    ('2026-11-09T08:00:00', '2026-11-07T07:10:00', 'ok'),
    ('2026-11-07T08:00:00', '2026-11-06T07:10:00', 'fail'),
    ('2026-11-07T06:30:00', '2026-11-06T07:10:00', 'ok'),
    ('2026-07-04T08:00:00', '2026-07-03T07:10:00', 'ok'),
    ('2026-07-04T08:00:00', '2026-07-02T07:10:00', 'fail'),
    ('2026-03-10T06:30:00', '2026-03-07T07:10:00', 'ok'),
    ('2026-03-10T08:00:00', '2026-03-07T07:10:00', 'fail'),
])
def test_us_post_close_uses_completed_new_york_session(now, last_run, expected):
    job = {'key': 'us_market', 'market': 'US', 'calendar': 'us_post_close',
           'schedule': '매일 07:00 (미국 거래일 마감 후)'}
    result = local_checks.evaluate_job(job, {'us_market': last_run}, kst(now))
    assert result.status == expected


def test_us_calendar_also_applies_to_plain_daily_schedule():
    job = {'key': 'us_market', 'market': 'US', 'calendar': 'us_post_close', 'schedule': '매일 07:00'}
    result = local_checks.evaluate_job(job, {'us_market': '2026-11-07T07:10:00'}, kst('2026-11-09T08:00:00'))
    assert result.status == 'ok'


def test_registry_with_future_success_is_not_a_valid_baseline(tmp_path, monkeypatch):
    monkeypatch.setattr(local_checks, 'DATA_DIR', str(tmp_path))
    (tmp_path / 'scheduler_jobs.json').write_text(json.dumps({'jobs': [
        {'key': 'future', 'schedule': '매일 09:00'},
    ]}), encoding='utf-8')
    (tmp_path / 'scheduler_last_run.json').write_text(json.dumps({
        'future': '2026-11-09T09:00:00',
    }), encoding='utf-8')
    results = {row.id: row for row in local_checks.check_jobs({}, kst('2026-11-08T00:30:00'))}
    assert results['job:_baseline'].status == 'unknown'

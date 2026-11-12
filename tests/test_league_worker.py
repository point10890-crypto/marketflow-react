import json
from datetime import date, datetime, timedelta, timezone

import pytest

from app.services.forecast_league import baselines, db
from app.services.league_worker import __main__ as worker, handlers, jobs, schedule

WEEKDAYS = lambda day: day.weekday() < 5  # noqa: E731
T0 = datetime(2026, 11, 13, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def clock_at(monkeypatch):
    state = {'now': T0}
    monkeypatch.setattr(jobs, '_now', lambda: state['now'])
    return state


def _statuses(conn):
    return [(row['kind'], row['status'], row['attempts']) for row in conn.execute('SELECT * FROM jobs ORDER BY job_id')]


def test_enqueue_is_deduplicated(league_conn, clock_at):
    assert jobs.enqueue(league_conn, 'score', {'today': '2026-11-13'}, 'score:2026-11-13') is True
    assert jobs.enqueue(league_conn, 'score', {'today': '2026-11-13'}, 'score:2026-11-13') is False
    assert _statuses(league_conn) == [('score', 'queued', 0)]


def test_jobs_are_claimed_in_order_and_completed(league_conn, clock_at):
    jobs.enqueue(league_conn, 'a', {}, 'a')
    jobs.enqueue(league_conn, 'b', {}, 'b')
    first = jobs.claim_next(league_conn)
    assert (first['kind'], first['attempts']) == ('a', 1)
    jobs.complete(league_conn, first['job_id'], {'ok': 1})
    assert jobs.claim_next(league_conn)['kind'] == 'b'
    assert jobs.claim_next(league_conn) is None
    assert json.loads(league_conn.execute("SELECT result FROM jobs WHERE kind = 'a'").fetchone()[0]) == {'ok': 1}


def test_failed_job_waits_then_fails_for_good_on_the_third_attempt(league_conn, clock_at):
    jobs.enqueue(league_conn, 'a', {}, 'a')
    job = jobs.claim_next(league_conn)
    assert jobs.fail(league_conn, job['job_id'], 'boom') is False
    assert jobs.claim_next(league_conn) is None                       # 5분 대기
    clock_at['now'] = T0 + timedelta(minutes=5)
    assert jobs.fail(league_conn, jobs.claim_next(league_conn)['job_id'], 'boom') is False
    clock_at['now'] = T0 + timedelta(minutes=10)
    assert jobs.fail(league_conn, jobs.claim_next(league_conn)['job_id'], 'boom') is True
    row = league_conn.execute('SELECT status, attempts, last_error FROM jobs').fetchone()
    assert tuple(row) == ('failed', 3, 'boom')


def test_running_jobs_are_requeued_on_restart(league_conn, clock_at):
    jobs.enqueue(league_conn, 'a', {}, 'a')
    jobs.claim_next(league_conn)
    assert jobs.recover_running(league_conn) == 1
    assert _statuses(league_conn) == [('a', 'queued', 1)]


def test_schedule_enqueues_each_slot_once(league_conn, clock_at):
    assert schedule.enqueue_slot(league_conn, 'morning', date(2026, 11, 16), trading_day=WEEKDAYS) == 2
    assert schedule.enqueue_slot(league_conn, 'morning', date(2026, 11, 16), trading_day=WEEKDAYS) == 0
    assert schedule.enqueue_slot(league_conn, 'evening', date(2026, 11, 16), trading_day=WEEKDAYS) == 3
    rows = [(row['kind'], json.loads(row['args'])) for row in league_conn.execute('SELECT * FROM jobs ORDER BY job_id')]
    assert rows == [('sync_universe', {'today': '2026-11-16'}),
                    ('submit_baselines', {'asof_date': '2026-11-13'}),       # 월요일 아침 → 금요일 기준
                    ('collect_regular', {'today': '2026-11-16'}),
                    ('resolve', {'today': '2026-11-16'}), ('score', {'today': '2026-11-16'})]
    with pytest.raises(ValueError):
        schedule.enqueue_slot(league_conn, 'noon', date(2026, 11, 16))


def test_drain_runs_jobs_and_records_failures(tmp_path, monkeypatch, clock_at):
    monkeypatch.setenv('FORECAST_LEAGUE_DIR', str(tmp_path / 'league'))
    alerts = []
    monkeypatch.setattr(worker, '_alert', alerts.append)

    def explode(conn, args):
        raise baselines.UniverseBarsMissing('2026-11-12')

    monkeypatch.setattr(handlers, 'HANDLERS', {'ok': lambda conn, args: {'echo': args['x']}, 'bad': explode})
    with db.connect() as conn:
        jobs.enqueue(conn, 'ok', {'x': 1}, 'ok')
        jobs.enqueue(conn, 'bad', {}, 'bad')
        jobs.enqueue(conn, 'unknown', {}, 'unknown')
    assert worker.drain() == 3
    with db.connect() as conn:
        assert _statuses(conn) == [('ok', 'done', 1), ('bad', 'queued', 1), ('unknown', 'queued', 1)]
    assert alerts == []
    for minutes in (5, 10):
        clock_at['now'] = T0 + timedelta(minutes=minutes)
        worker.drain()
    with db.connect() as conn:
        assert _statuses(conn) == [('ok', 'done', 1), ('bad', 'failed', 3), ('unknown', 'failed', 3)]
    assert len(alerts) == 2 and 'bad' in alerts[0] and 'UniverseBarsMissing' in alerts[0]


def test_handlers_cover_every_scheduled_kind():
    assert set(handlers.HANDLERS) == {'sync_universe', 'submit_baselines', 'collect_regular', 'resolve', 'score'}


def test_cli_dispatches_drain_and_enqueue(tmp_path, monkeypatch, clock_at, capsys):
    monkeypatch.setenv('FORECAST_LEAGUE_DIR', str(tmp_path / 'league'))
    monkeypatch.setattr(handlers, 'HANDLERS', {})
    assert worker.main(['enqueue', 'evening']) == 0
    assert worker.main(['status']) == 0
    assert '"queued": 3' in capsys.readouterr().out

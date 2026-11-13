from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from filelock import FileLock

from app.services.forecast_league import db, paths
from app.services.league_worker import __main__ as worker, handlers, jobs, schedule


def test_dependent_submission_waits_for_retrying_collection(league_conn, monkeypatch):
    monkeypatch.setattr(jobs, '_now', lambda: datetime(2026, 11, 13, tzinfo=timezone.utc))
    schedule.enqueue_slot(league_conn, 'morning', date(2026, 11, 13), lambda d: d.weekday() < 5)
    first = jobs.claim_next(league_conn)
    assert first['kind'] == 'sync_universe'
    jobs.fail(league_conn, first['job_id'], 'source unavailable')
    assert jobs.claim_next(league_conn) is None


def test_recovery_does_not_reset_exhausted_attempts(league_conn, monkeypatch):
    jobs.enqueue(league_conn, 'score', {}, 'a')
    league_conn.execute("UPDATE jobs SET status='running', attempts=3")
    jobs.recover_running(league_conn)
    assert jobs.claim_next(league_conn) is None
    assert league_conn.execute('SELECT status FROM jobs').fetchone()[0] == 'failed'


def test_overlapping_drain_does_not_steal_active_work(tmp_path, monkeypatch):
    monkeypatch.setenv('FORECAST_LEAGUE_DIR', str(tmp_path / 'league'))
    with db.connect() as conn:
        jobs.enqueue(conn, 'score', {}, 'a')
        jobs.claim_next(conn)
    monkeypatch.setitem(handlers.HANDLERS, 'score', lambda *a: pytest.fail('stole running job'))
    with FileLock(str(Path(paths.league_dir()) / 'worker.lock')):
        assert worker.drain() == 0
    with db.connect() as conn:
        assert conn.execute('SELECT status FROM jobs').fetchone()[0] == 'running'


def test_closed_day_does_not_enqueue_a_new_forecast(league_conn):
    assert schedule.enqueue_slot(league_conn, 'morning', date(2026, 11, 14), lambda d: d.weekday() < 5) == 0


def test_regular_collection_partial_failure_is_retryable(league_conn, monkeypatch):
    from app.services.forecast_league import price_sources
    monkeypatch.setattr(price_sources, 'needed_regular_targets', lambda *a, **k: [('005930','2026-11-13')])
    monkeypatch.setattr(price_sources, 'collect_regular_bars', lambda *a, **k: {'stored':0,'failed':[['005930','2026-11-13','regular_boundaries']]})
    with pytest.raises(RuntimeError, match='incomplete'):
        handlers.HANDLERS['collect_regular'](league_conn, {'today':'2026-11-13'})


def test_unavailable_symbol_does_not_block_resolving_other_stored_paths(league_conn):
    from datetime import date
    from app.services.league_worker import schedule, jobs
    schedule.enqueue_slot(league_conn, 'evening', date(2026, 11, 13), trading_day=lambda d: True)
    first = jobs.claim_next(league_conn)
    assert first['kind'] == 'collect_regular'
    jobs.fail(league_conn, first['job_id'], 'one_symbol_suspended')
    assert jobs.claim_next(league_conn) is None  # Wait for the retry budget before void decisions.
    league_conn.execute("UPDATE jobs SET attempts=3 WHERE job_id=?", (first['job_id'],))
    jobs.fail(league_conn, first['job_id'], 'one_symbol_suspended')
    next_job = jobs.claim_next(league_conn)
    assert next_job and next_job['kind'] == 'resolve'

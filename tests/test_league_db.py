import os
import sqlite3
from datetime import date, datetime, timezone

import pytest

from app.services.forecast_league import clock, db, paths

WEEKDAYS = lambda day: day.weekday() < 5  # noqa: E731


def test_db_is_created_under_the_env_directory(league_conn, tmp_path):
    assert paths.db_path() == os.path.join(str(tmp_path / 'league'), 'league.db')
    assert os.path.isfile(paths.db_path())
    tables = {row[0] for row in league_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {'forecasters', 'forecasts', 'abstentions', 'capsules', 'resolutions',
            'scorecards', 'bars', 'jobs'} <= tables
    assert league_conn.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'


def test_forecasts_and_capsules_cannot_be_changed(league_conn):
    league_conn.execute("INSERT INTO forecasters VALUES ('fx','1','engine','native','t')")
    league_conn.execute("INSERT INTO capsules VALUES ('h', x'00', 't')")
    league_conn.execute(
        "INSERT INTO forecasts VALUES ('f1','fx','1','005930','2026-11-12T06:30:00Z','E1',0.5,NULL,'h','',1,'t')")
    for statement in ("UPDATE forecasts SET probability=0.9", "DELETE FROM forecasts",
                      "UPDATE capsules SET payload=x'01'", "DELETE FROM capsules"):
        with pytest.raises(sqlite3.DatabaseError):
            league_conn.execute(statement)


def test_connect_rolls_back_on_error(tmp_path, monkeypatch):
    monkeypatch.setenv('FORECAST_LEAGUE_DIR', str(tmp_path / 'league'))
    with pytest.raises(RuntimeError):
        with db.connect() as conn:
            conn.execute("INSERT INTO forecasters VALUES ('fx','1','engine','native','t')")
            raise RuntimeError('boom')
    with db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM forecasters').fetchone()[0] == 0


def test_parse_ts_requires_an_offset():
    assert clock.parse_ts('2026-11-12T15:30:00+09:00') == datetime(2026, 11, 12, 6, 30, tzinfo=timezone.utc)
    assert clock.iso(clock.parse_ts('2026-11-12T15:30:00+09:00')) == '2026-11-12T06:30:00Z'
    with pytest.raises(ValueError):
        clock.parse_ts('2026-11-12T15:30:00')


def test_next_session_open_after():
    thursday_close = clock.parse_ts('2026-11-12T15:30:00+09:00')
    assert clock.iso(clock.next_session_open_after(thursday_close, WEEKDAYS)) == '2026-11-13T00:00:00Z'
    friday_close = clock.parse_ts('2026-11-13T15:30:00+09:00')
    assert clock.iso(clock.next_session_open_after(friday_close, WEEKDAYS)) == '2026-11-16T00:00:00Z'
    before_open = clock.parse_ts('2026-11-12T08:00:00+09:00')
    assert clock.iso(clock.next_session_open_after(before_open, WEEKDAYS)) == '2026-11-12T00:00:00Z'


def test_trading_day_helpers():
    assert clock.trading_days('2026-11-13', '2026-11-17', WEEKDAYS) == ['2026-11-13', '2026-11-16', '2026-11-17']
    assert clock.previous_trading_day(date(2026, 11, 16), WEEKDAYS) == date(2026, 11, 13)
    assert clock.close_ts('2026-11-12') == '2026-11-12T15:30:00+09:00'
    assert clock.kst_date(clock.parse_ts('2026-11-12T16:00:00Z')) == '2026-11-13'

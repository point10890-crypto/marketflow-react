"""Claw polling must not run an unbounded database integrity scan."""
from contextlib import contextmanager
import sqlite3

import pytest

from marketflow_claw import memory
from marketflow_claw import observation as obs


@pytest.fixture
def quality_db(monkeypatch, tmp_path):
    path = tmp_path / 'claw.db'
    monkeypatch.setattr(memory, 'DB_PATH', str(path))
    monkeypatch.setattr(memory, 'ensure_dirs', lambda: None)
    with memory.connect():
        pass
    with obs.connect(write=True):
        pass
    return path


def test_polling_quality_skips_integrity_and_reports_unchecked(quality_db, monkeypatch):
    original_connect = obs.connect
    statements = []

    @contextmanager
    def traced_connect(**kwargs):
        with original_connect(**kwargs) as con:
            con.set_trace_callback(statements.append)
            yield con

    monkeypatch.setattr(obs, 'connect', traced_connect)

    result = obs.build_quality(check_integrity=False)

    assert not any('foreign_key_check' in sql.lower() for sql in statements)
    assert result['status'] == 'degraded'
    assert result['integrity'] == {'status': 'not_checked', 'complete': False}
    assert 'integrity_not_checked' in result['errors']
    assert result['database']['schema_version'] == obs.SCHEMA_VERSION


def test_explicit_quality_still_checks_all_foreign_keys(quality_db):
    with sqlite3.connect(quality_db) as con:
        con.executescript(
            'CREATE TABLE integrity_parent (id INTEGER PRIMARY KEY);'
            'CREATE TABLE integrity_child (parent_id INTEGER REFERENCES integrity_parent(id));'
            'INSERT INTO integrity_child VALUES (999);'
        )

    result = obs.build_quality()

    assert result['status'] == 'degraded'
    assert result['integrity'] == {'status': 'violations', 'complete': True}
    assert 'foreign_key_violations:1' in result['errors']


def test_completed_quality_is_healthy(quality_db):
    result = obs.build_quality()

    assert result['status'] == 'ok'
    assert result['integrity'] == {'status': 'ok', 'complete': True}
    assert result['errors'] == []


@pytest.mark.parametrize('blocked_sql', [
    'SELECT COUNT(*) FROM observation_scans',
    'PRAGMA foreign_key_check',
])
def test_quality_sql_budget_interrupts_work_and_closes_connection(
    quality_db, monkeypatch, blocked_sql,
):
    original_connect = obs.connect
    connections = []
    handlers = []
    clock = iter((0.0, 2.0))
    monkeypatch.setattr(obs.time, 'monotonic', lambda: next(clock, 2.0))

    class SlowConnection:
        def __init__(self, con):
            self.con = con

        def set_progress_handler(self, callback, instructions):
            handlers.append((callback, instructions))
            self.con.set_progress_handler(callback, instructions)

        def execute(self, sql, *args):
            if sql == blocked_sql:
                sql = (
                    'WITH RECURSIVE n(x) AS '
                    '(SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<1000000) '
                    'SELECT sum(x) FROM n'
                )
            return self.con.execute(sql, *args)

    @contextmanager
    def slow_connect(**kwargs):
        with original_connect(**kwargs) as con:
            connections.append(con)
            yield SlowConnection(con)

    monkeypatch.setattr(obs, 'connect', slow_connect)

    result = obs.build_quality()

    assert result['status'] == 'degraded'
    assert result['integrity'] == {'status': 'incomplete', 'complete': False}
    assert 'quality_sql_budget_exceeded' in result['errors']
    assert callable(handlers[0][0]) and handlers[0][1] > 0
    assert handlers[-1] == (None, 0)
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        connections[0].execute('SELECT 1')

import pytest

from app.services.forecast_league import derive

ASOF = '2026-06-01T15:30:00+09:00'
EDGES = [0.5]


def _seed(conn, forecaster, count, *, score, outcome, exit_date='2026-05-01', start=0):
    conn.execute('INSERT OR IGNORE INTO forecasters VALUES (?, ?, ?, ?, ?)', (forecaster, '1', 'engine', 'derived', 't'))
    conn.execute("INSERT OR IGNORE INTO capsules VALUES ('h', x'00', 't')")
    for index in range(start, start + count):
        forecast_id = f'{forecaster}-{index}'
        conn.execute('INSERT INTO forecasts VALUES (?, ?, ?, ?, ?, ?, 0.5, ?, ?, ?, 1, ?)',
                     (forecast_id, forecaster, '1', '005930', f'2026-01-01T00:{index // 60:02d}:{index % 60:02d}Z',
                      'E1', score, 'h', '', 't'))
        conn.execute("INSERT INTO resolutions VALUES (?, 'resolved', ?, 't', ?, 100, ?, 100, 'expiry', 0, 'v')",
                     (forecast_id, outcome, exit_date, exit_date))


def _derive(conn, score, forecaster='fx'):
    return derive.derived_probability(conn, forecaster_id=forecaster, version='1', event_id='E1',
                                      raw_score=score, asof_ts=ASOF, bin_edges=EDGES, fallback=0.2)


def test_uses_the_score_bin_when_it_has_thirty_samples(league_conn):
    _seed(league_conn, 'fx', 30, score=0.9, outcome=1)
    _seed(league_conn, 'fx', 30, score=0.1, outcome=0, start=30)
    assert _derive(league_conn, 0.8) == (0.98, 'score_bin')
    assert _derive(league_conn, 0.2) == (0.02, 'score_bin')


def test_falls_back_to_the_forecaster_overall_rate(league_conn):
    _seed(league_conn, 'fx', 29, score=0.9, outcome=1)
    _seed(league_conn, 'fx', 29, score=0.1, outcome=0, start=29)
    assert _derive(league_conn, 0.8) == (pytest.approx(0.5), 'forecaster_overall')


def test_falls_back_to_the_league_rate_then_to_the_given_value(league_conn):
    _seed(league_conn, 'other', 40, score=0.5, outcome=1)
    _seed(league_conn, 'other', 40, score=0.5, outcome=0, start=40)
    assert _derive(league_conn, 0.8) == (pytest.approx(0.5), 'league_base_rate')
    assert _derive(league_conn, 0.8, forecaster='other')[1] in {'score_bin', 'forecaster_overall'}


def test_uses_the_fallback_when_nothing_is_resolved(league_conn):
    assert _derive(league_conn, 0.8) == (0.2, 'fallback')


def test_samples_that_exit_on_or_after_the_asof_date_are_not_used(league_conn):
    _seed(league_conn, 'fx', 30, score=0.9, outcome=1, exit_date='2026-05-29')
    _seed(league_conn, 'fx', 500, score=0.9, outcome=0, exit_date='2026-06-01', start=30)
    _seed(league_conn, 'fx', 500, score=0.9, outcome=0, exit_date='2026-06-02', start=530)
    assert _derive(league_conn, 0.8) == (0.98, 'score_bin')

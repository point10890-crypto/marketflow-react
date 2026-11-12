import pytest

from app.services.forecast_league import derive

ASOF = '2026-06-01T15:30:00+09:00'
EDGES = [0.5]


def _seed(conn, forecaster, count, *, score, outcome, exit_date='2026-05-01', start=0, day='2026-01-01',
          version='1', official=1):
    """같은 KST 날짜(day)의 예측 count 건 = 한 코호트. outcome 이 None 이면 미청산으로 남긴다."""
    conn.execute('INSERT OR IGNORE INTO forecasters VALUES (?, ?, ?, ?, ?)',
                 (forecaster, version, 'engine', 'derived', 't'))
    conn.execute("INSERT OR IGNORE INTO capsules VALUES ('h', x'00', 't')")
    ids = []
    for index in range(start, start + count):
        forecast_id = f'{forecaster}-{version}-{index}'
        conn.execute('INSERT INTO forecasts VALUES (?, ?, ?, ?, ?, ?, 0.5, ?, ?, ?, ?, ?)',
                     (forecast_id, forecaster, version, '005930', f'{day}T00:{index // 60:02d}:{index % 60:02d}Z',
                      'E1', score, 'h', '', official, 't'))
        if outcome is not None:
            _resolve(conn, forecast_id, outcome, exit_date)
        ids.append(forecast_id)
    return ids


def _resolve(conn, forecast_id, outcome, exit_date):
    conn.execute("INSERT INTO resolutions VALUES (?, 'resolved', ?, 't', ?, 100, ?, 100, 'expiry', 0, 'v')",
                 (forecast_id, outcome, exit_date, exit_date))


def _derive(conn, score, forecaster='fx', version='1'):
    return derive.derived_probability(conn, forecaster_id=forecaster, version=version, event_id='E1',
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
    _seed(league_conn, 'fx', 30, score=0.9, outcome=1, exit_date='2026-05-29', day='2026-05-18')
    _seed(league_conn, 'fx', 500, score=0.9, outcome=0, exit_date='2026-06-01', start=30, day='2026-05-19')
    _seed(league_conn, 'fx', 500, score=0.9, outcome=0, exit_date='2026-06-02', start=530, day='2026-05-20')
    assert _derive(league_conn, 0.8) == (0.98, 'score_bin')


def test_an_open_cohort_contributes_nothing_until_it_closes(league_conn):
    _seed(league_conn, 'fx', 30, score=0.9, outcome=0)
    _seed(league_conn, 'fx', 3, score=0.9, outcome=1, exit_date='2026-05-21', start=30, day='2026-05-20')
    pending = _seed(league_conn, 'fx', 5, score=0.9, outcome=None, start=33, day='2026-05-20')
    assert _derive(league_conn, 0.8) == (0.02, 'score_bin')
    assert _derive(league_conn, 0.8, forecaster='nobody') == (0.02, 'league_base_rate')

    for forecast_id in pending:
        _resolve(league_conn, forecast_id, 0, '2026-05-29')
    assert _derive(league_conn, 0.8) == (pytest.approx(3 / 38), 'score_bin')
    assert _derive(league_conn, 0.8, forecaster='nobody') == (pytest.approx(3 / 38), 'league_base_rate')


def test_a_cohort_with_any_exit_on_or_after_asof_is_excluded_whole(league_conn):
    _seed(league_conn, 'fx', 30, score=0.9, outcome=1, exit_date='2026-05-29', day='2026-05-20')
    _seed(league_conn, 'fx', 1, score=0.9, outcome=0, exit_date='2026-06-01', start=30, day='2026-05-20')
    assert _derive(league_conn, 0.8) == (0.2, 'fallback')
    assert _derive(league_conn, 0.8, forecaster='nobody') == (0.2, 'fallback')


def test_league_rate_ignores_unofficial_forecasts(league_conn):
    _seed(league_conn, 'other', 40, score=0.5, outcome=1)
    _seed(league_conn, 'shadow', 40, score=0.5, outcome=0, official=0)
    assert _derive(league_conn, 0.8) == (0.98, 'league_base_rate')


def test_league_rate_ignores_cohorts_that_exit_on_or_after_asof(league_conn):
    _seed(league_conn, 'other', 30, score=0.5, outcome=1, exit_date='2026-05-29', day='2026-05-18')
    _seed(league_conn, 'other', 30, score=0.5, outcome=0, exit_date='2026-06-01', start=30, day='2026-05-19')
    assert _derive(league_conn, 0.8) == (0.98, 'league_base_rate')


def test_own_samples_come_from_the_requested_version_only(league_conn):
    _seed(league_conn, 'fx', 30, score=0.9, outcome=1, version='1')
    _seed(league_conn, 'fx', 30, score=0.9, outcome=0, version='2')
    assert _derive(league_conn, 0.8, version='1') == (0.98, 'score_bin')
    assert _derive(league_conn, 0.8, version='2') == (0.02, 'score_bin')


def test_own_samples_without_a_raw_score_are_ignored(league_conn):
    _seed(league_conn, 'fx', 30, score=0.9, outcome=1)
    _seed(league_conn, 'fx', 30, score=None, outcome=0, start=30, day='2026-01-02')
    assert _derive(league_conn, 0.2) == (0.98, 'forecaster_overall')

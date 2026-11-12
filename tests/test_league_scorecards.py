import json

import pytest

from app.services.forecast_league import scorecards


def _seed(conn, forecaster, count, *, probability=0.6, hit_every=2, official=1, start=0, kind='engine'):
    conn.execute('INSERT OR IGNORE INTO forecasters VALUES (?, ?, ?, ?, ?)', (forecaster, '1', kind, 'native', 't'))
    conn.execute("INSERT OR IGNORE INTO capsules VALUES ('h', x'00', 't')")
    for index in range(start, start + count):
        day = f'2026-{1 + index // 28:02d}-{1 + index % 28:02d}'
        forecast_id = f'{forecaster}-{index}'
        conn.execute('INSERT INTO forecasts VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)',
                     (forecast_id, forecaster, '1', '005930', f'{day}T06:30:00Z', 'E1', probability, 'h', '',
                      official, 't'))
        outcome = 1 if index % hit_every == 0 else 0
        conn.execute("INSERT INTO resolutions VALUES (?, 'resolved', ?, 't', ?, 100, ?, 108, 'target', ?, 'v')",
                     (forecast_id, outcome, day, day, 7.77 if outcome else -7.23))


def _card(conn, forecaster):
    row = conn.execute('SELECT * FROM scorecards WHERE forecaster_id = ?', (forecaster,)).fetchone()
    return row, json.loads(row['metrics_json'])


def test_fewer_than_one_hundred_resolved_is_insufficient(league_conn):
    _seed(league_conn, 'fx', 99)
    scorecards.compute_scorecards(league_conn)
    row, metrics = _card(league_conn, 'fx')
    assert (row['status'], row['n_resolved'], row['window_id']) == ('insufficient', 99, 'all')
    assert metrics == {'n_resolved': 99, 'n_void': 0, 'n_pending': 0}


def test_scored_card_has_every_metric(league_conn):
    _seed(league_conn, 'fx', 120)
    scorecards.compute_scorecards(league_conn)
    row, metrics = _card(league_conn, 'fx')
    assert (row['status'], row['n_resolved']) == ('scored', 120)
    assert metrics['hit_rate'] == pytest.approx(0.5)
    assert metrics['brier'] == pytest.approx(0.26)
    assert metrics['mean_net_return_pct'] == pytest.approx(0.27)
    assert metrics['top3_precision'] == pytest.approx(0.5)
    assert metrics['calibration'][0]['n'] == 120
    assert metrics['brier_ci95'][0] <= metrics['brier'] <= metrics['brier_ci95'][1]
    assert metrics['mean_net_return_ci95'][0] <= 0.27 <= metrics['mean_net_return_ci95'][1]
    assert metrics['baseline'] is None


def test_baseline_difference_uses_matched_forecasts_only(league_conn):
    _seed(league_conn, 'fx', 120, probability=0.6)
    _seed(league_conn, scorecards.BASELINE_ID, 100, probability=0.5, kind='baseline')
    scorecards.compute_scorecards(league_conn)
    _, metrics = _card(league_conn, 'fx')
    assert metrics['baseline']['forecaster_id'] == scorecards.BASELINE_ID
    assert metrics['baseline']['n_matched'] == 100
    assert metrics['baseline']['brier_diff'] == pytest.approx(0.26 - 0.25)
    _, baseline_metrics = _card(league_conn, scorecards.BASELINE_ID)
    assert baseline_metrics['baseline'] is None


def test_unofficial_void_and_pending_forecasts_are_not_scored(league_conn):
    _seed(league_conn, 'fx', 100)
    _seed(league_conn, 'fx', 30, official=0, start=100)
    league_conn.execute("INSERT INTO forecasts VALUES ('p1','fx','1','000660','2026-06-01T06:30:00Z','E1',0.5,NULL,'h','',1,'t')")
    league_conn.execute("INSERT INTO forecasts VALUES ('v1','fx','1','000660','2026-06-02T06:30:00Z','E1',0.5,NULL,'h','',1,'t')")
    league_conn.execute("INSERT INTO resolutions (forecast_id, status, resolved_at, price_source_version) VALUES ('v1','void','t','v')")
    scorecards.compute_scorecards(league_conn)
    row, metrics = _card(league_conn, 'fx')
    assert row['n_resolved'] == 100
    assert (metrics['n_void'], metrics['n_pending']) == (1, 1)


def test_recomputing_does_not_add_rows(league_conn):
    _seed(league_conn, 'fx', 120)
    first = scorecards.compute_scorecards(league_conn)
    before = _card(league_conn, 'fx')[1]
    second = scorecards.compute_scorecards(league_conn)
    assert len(first) == len(second) == 1
    assert league_conn.execute('SELECT COUNT(*) FROM scorecards').fetchone()[0] == 1
    assert _card(league_conn, 'fx')[1] == before

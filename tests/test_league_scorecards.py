import json

import pytest

from app.services.forecast_league import scorecards


def _day(index):
    return f'2026-{1 + index // 28:02d}-{1 + index % 28:02d}'


def _register(conn, forecaster, *, version='1', kind='engine', registered_at='t'):
    conn.execute('INSERT OR IGNORE INTO forecasters VALUES (?, ?, ?, ?, ?)',
                 (forecaster, version, kind, 'native', registered_at))
    conn.execute("INSERT OR IGNORE INTO capsules VALUES ('h', x'00', 't')")


def _resolve(conn, forecast_id, outcome, day):
    conn.execute("INSERT INTO resolutions VALUES (?, 'resolved', ?, 't', ?, 100, ?, 108, 'target', ?, 'v')",
                 (forecast_id, outcome, day, day, 7.77 if outcome else -7.23))


def _add(conn, forecaster, day, *, stock='005930', probability=0.6, outcome=1, version='1', time='15:30:00',
         raw_score=None):
    """예측 한 건. outcome 이 None 이면 미청산으로 남긴다."""
    forecast_id = f'{forecaster}-{version}-{stock}-{day}T{time}'
    conn.execute('INSERT INTO forecasts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)',
                 (forecast_id, forecaster, version, stock, f'{day}T{time}+09:00', 'E1', probability, raw_score,
                  'h', '', 't'))
    if outcome is not None:
        _resolve(conn, forecast_id, outcome, day)
    return forecast_id


def _seed(conn, forecaster, count, *, probability=0.6, hit_every=2, official=1, start=0, kind='engine'):
    _register(conn, forecaster, kind=kind)
    for index in range(start, start + count):
        day = _day(index)
        forecast_id = f'{forecaster}-{index}'
        conn.execute('INSERT INTO forecasts VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)',
                     (forecast_id, forecaster, '1', '005930', f'{day}T06:30:00Z', 'E1', probability, 'h', '',
                      official, 't'))
        _resolve(conn, forecast_id, 1 if index % hit_every == 0 else 0, day)


def _card(conn, forecaster):
    row = conn.execute('SELECT * FROM scorecards WHERE forecaster_id = ?', (forecaster,)).fetchone()
    return row, json.loads(row['metrics_json'])


def test_fewer_than_one_hundred_resolved_is_insufficient(league_conn):
    _seed(league_conn, 'fx', 99)
    scorecards.compute_scorecards(league_conn)
    row, metrics = _card(league_conn, 'fx')
    assert (row['status'], row['n_resolved'], row['window_id']) == ('insufficient', 99, 'all')
    assert metrics == {'n_resolved': 99, 'n_void': 0, 'n_pending': 0, 'n_scored': 99}


def test_scored_card_has_every_metric(league_conn):
    _seed(league_conn, 'fx', 120)
    scorecards.compute_scorecards(league_conn)
    row, metrics = _card(league_conn, 'fx')
    assert (row['status'], row['n_resolved']) == ('scored', 120)
    assert (metrics['n_resolved'], metrics['n_scored'], metrics['n_entry_dates']) == (120, 120, 120)
    assert metrics['hit_rate'] == pytest.approx(0.5)
    assert metrics['brier'] == pytest.approx(0.26)
    assert metrics['mean_net_return_pct'] == pytest.approx(0.27)
    assert metrics['top3_precision'] == pytest.approx(0.5)
    assert metrics['calibration'][0]['n'] == 120
    assert metrics['brier_ci95'][0] <= metrics['brier'] <= metrics['brier_ci95'][1]
    assert metrics['mean_net_return_ci95'][0] <= 0.27 <= metrics['mean_net_return_ci95'][1]
    assert metrics['baseline'] is None


def test_an_open_cohort_is_not_scored_until_every_forecast_resolves(league_conn):
    _seed(league_conn, 'fx', 100)
    pending = []
    for number in range(8):
        early_hit = number < 3
        forecast_id = _add(league_conn, 'fx', '2026-06-01', stock=f'10000{number}',
                           outcome=1 if early_hit else None)
        if not early_hit:
            pending.append(forecast_id)
    scorecards.compute_scorecards(league_conn)
    row, metrics = _card(league_conn, 'fx')
    assert (row['status'], row['n_resolved']) == ('scored', 100)
    assert (metrics['n_resolved'], metrics['n_pending'], metrics['n_scored']) == (103, 5, 100)
    assert metrics['hit_rate'] == pytest.approx(0.5)
    assert metrics['calibration'][0]['n'] == 100

    for forecast_id in pending:
        _resolve(league_conn, forecast_id, 0, '2026-06-12')
    scorecards.compute_scorecards(league_conn)
    row, metrics = _card(league_conn, 'fx')
    assert row['n_resolved'] == 108
    assert (metrics['n_resolved'], metrics['n_pending'], metrics['n_scored']) == (108, 0, 108)
    assert metrics['hit_rate'] == pytest.approx(53 / 108)


def test_early_exits_of_an_open_cohort_do_not_cross_the_gate(league_conn):
    _seed(league_conn, 'fx', 97)
    for number in range(8):
        _add(league_conn, 'fx', '2026-06-01', stock=f'10000{number}', outcome=1 if number < 3 else None)
    scorecards.compute_scorecards(league_conn)
    row, metrics = _card(league_conn, 'fx')
    assert (row['status'], row['n_resolved']) == ('insufficient', 97)
    assert metrics == {'n_resolved': 100, 'n_void': 0, 'n_pending': 5, 'n_scored': 97}


def test_a_void_forecast_does_not_keep_its_cohort_open(league_conn):
    _seed(league_conn, 'fx', 99)
    _add(league_conn, 'fx', '2026-06-01', stock='100001', outcome=1)
    void_id = _add(league_conn, 'fx', '2026-06-01', stock='100002', outcome=None)
    league_conn.execute("INSERT INTO resolutions (forecast_id, status, resolved_at, price_source_version) "
                        "VALUES (?, 'void', 't', 'v')", (void_id,))
    scorecards.compute_scorecards(league_conn)
    row, metrics = _card(league_conn, 'fx')
    assert (row['status'], row['n_resolved']) == ('scored', 100)
    assert (metrics['n_void'], metrics['n_scored']) == (1, 100)


def test_confidence_intervals_are_null_with_too_few_entry_dates(league_conn):
    _register(league_conn, 'fx')
    for day_index in range(3):
        for number in range(40):
            _add(league_conn, 'fx', _day(day_index), stock=f'1{number:05d}', outcome=number % 2)
    scorecards.compute_scorecards(league_conn)
    row, metrics = _card(league_conn, 'fx')
    assert (row['status'], metrics['n_scored'], metrics['n_entry_dates']) == ('scored', 120, 3)
    assert metrics['brier_ci95'] is None and metrics['mean_net_return_ci95'] is None
    assert metrics['brier'] == pytest.approx(0.26)


def test_top3_precision_ranks_the_whole_kst_day(league_conn):
    plan = [('100001', '15:00:00', 0.2, 0), ('100002', '15:05:00', 0.3, 0), ('100003', '15:10:00', 0.7, 1),
            ('100004', '15:20:00', 0.8, 1), ('100005', '15:30:00', 0.9, 1)]
    _register(league_conn, 'fx')
    for day_index in range(30):
        for stock, time, probability, outcome in plan:
            _add(league_conn, 'fx', _day(day_index), stock=stock, time=time, probability=probability,
                 outcome=outcome)
    scorecards.compute_scorecards(league_conn)
    _, metrics = _card(league_conn, 'fx')
    assert metrics['n_scored'] == 150
    assert metrics['hit_rate'] == pytest.approx(0.6)
    assert metrics['top3_precision'] == pytest.approx(1.0)


def test_top3_precision_uses_raw_score_and_is_null_when_undetermined(league_conn):
    _register(league_conn, 'scored_ties')
    _register(league_conn, 'flat')
    for day_index in range(30):
        for number, raw_score in enumerate((0.1, 0.9, 0.8, 0.7)):
            _add(league_conn, 'scored_ties', _day(day_index), stock=f'10000{number}', probability=0.5,
                 raw_score=raw_score, outcome=1 if raw_score > 0.5 else 0)
            _add(league_conn, 'flat', _day(day_index), stock=f'10000{number}', probability=0.5,
                 outcome=1 if number else 0)
    scorecards.compute_scorecards(league_conn)
    assert _card(league_conn, 'scored_ties')[1]['top3_precision'] == pytest.approx(1.0)
    flat = _card(league_conn, 'flat')[1]
    assert flat['hit_rate'] == pytest.approx(0.75) and flat['top3_precision'] is None


def test_baseline_difference_uses_matched_forecasts_only(league_conn):
    _register(league_conn, 'fx')
    _register(league_conn, scorecards.BASELINE_ID, kind='baseline')
    for index in range(100):
        stock = '005930' if index % 2 == 0 else '000660'
        outcome = 1 if index % 4 < 2 else 0
        _add(league_conn, 'fx', _day(index), stock=stock, probability=0.6, outcome=outcome)
        _add(league_conn, scorecards.BASELINE_ID, _day(index), stock=stock, probability=0.5, outcome=outcome)
    for index in range(100, 120):
        # 같은 날 다른 종목: 짝이 아니다. 여기까지 own 에 넣으면 Brier 가 0.81 쪽으로 끌려간다.
        _add(league_conn, 'fx', _day(index), stock='035420', probability=0.9, outcome=0)
        _add(league_conn, scorecards.BASELINE_ID, _day(index), stock='005930', probability=0.5, outcome=0)
    scorecards.compute_scorecards(league_conn)
    _, metrics = _card(league_conn, 'fx')
    assert metrics['n_scored'] == 120
    assert metrics['brier'] == pytest.approx((100 * 0.26 + 20 * 0.81) / 120)
    assert metrics['baseline'] == {'forecaster_id': scorecards.BASELINE_ID, 'version': '1', 'n_matched': 100,
                                   'brier_diff': pytest.approx(0.26 - 0.25)}
    _, baseline_metrics = _card(league_conn, scorecards.BASELINE_ID)
    assert baseline_metrics['baseline'] is None


def test_baseline_is_pinned_to_its_latest_registered_version(league_conn):
    _seed(league_conn, 'fx', 100, probability=0.6)
    _register(league_conn, scorecards.BASELINE_ID, version='3', kind='baseline', registered_at='2026-02-01T00:00:00Z')
    _register(league_conn, scorecards.BASELINE_ID, version='2', kind='baseline', registered_at='2026-02-01T00:00:00Z')
    _register(league_conn, scorecards.BASELINE_ID, version='1', kind='baseline', registered_at='2026-01-01T00:00:00Z')
    for version, probability in (('3', 0.5), ('2', 0.9), ('1', 0.9)):
        for index in range(100):
            _add(league_conn, scorecards.BASELINE_ID, _day(index), version=version, probability=probability,
                 outcome=1 if index % 2 == 0 else 0)
    scorecards.compute_scorecards(league_conn)
    first = _card(league_conn, 'fx')[1]['baseline']
    scorecards.compute_scorecards(league_conn)
    assert _card(league_conn, 'fx')[1]['baseline'] == first
    assert first == {'forecaster_id': scorecards.BASELINE_ID, 'version': '3', 'n_matched': 100,
                     'brier_diff': pytest.approx(0.26 - 0.25)}


def test_baseline_matches_on_stock_and_kst_date_not_on_the_exact_timestamp(league_conn):
    _register(league_conn, 'fx')
    for index in range(100):
        _add(league_conn, 'fx', _day(index), time='15:10:00', probability=0.6, outcome=1 if index % 2 == 0 else 0)
    for index in range(4):  # 같은 날 같은 종목을 한 번 더 낸 예측도 그날 기준선과 짝이 된다.
        _add(league_conn, 'fx', _day(index), time='15:20:00', probability=0.6, outcome=1 if index % 2 == 0 else 0)
    _seed(league_conn, scorecards.BASELINE_ID, 100, probability=0.5, kind='baseline')  # 06:30Z = 15:30 KST
    scorecards.compute_scorecards(league_conn)
    baseline = _card(league_conn, 'fx')[1]['baseline']
    assert baseline['n_matched'] == 104
    assert baseline['brier_diff'] == pytest.approx(0.26 - 0.25)


def test_baseline_rows_from_an_open_cohort_are_not_matched(league_conn):
    _seed(league_conn, 'fx', 100, probability=0.6)
    _seed(league_conn, scorecards.BASELINE_ID, 100, probability=0.5, kind='baseline')
    _add(league_conn, 'fx', '2026-06-01', stock='100001', outcome=1)
    _add(league_conn, scorecards.BASELINE_ID, '2026-06-01', stock='100001', probability=0.5, outcome=1)
    _add(league_conn, scorecards.BASELINE_ID, '2026-06-01', stock='100002', probability=0.5, outcome=None)
    scorecards.compute_scorecards(league_conn)
    _, metrics = _card(league_conn, 'fx')
    assert metrics['n_scored'] == 101
    assert metrics['baseline']['n_matched'] == 100


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

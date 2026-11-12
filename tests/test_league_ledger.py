from datetime import datetime, timezone

import pytest

from app.services.forecast_league import capsules, ledger

WEEKDAYS = lambda day: day.weekday() < 5  # noqa: E731
ASOF = '2026-11-12T15:30:00+09:00'          # 목요일 종가


def _at(monkeypatch, text):
    moment = datetime.fromisoformat(text).astimezone(timezone.utc)
    monkeypatch.setattr(ledger, '_now', lambda: moment)


def _ready(conn):
    ledger.register_forecaster(conn, 'fx', '1', 'engine', 'native')
    return capsules.put_capsule(conn, {'k': 1})


def _submit(conn, capsule, **over):
    args = dict(forecaster_id='fx', version='1', stock_code='005930', asof_ts=ASOF, event_id='E1',
                probability=0.4, capsule_hash=capsule, trading_day=WEEKDAYS)
    args.update(over)
    return ledger.submit_forecast(conn, **args)


def test_submission_is_recorded_with_server_time(league_conn, monkeypatch):
    _at(monkeypatch, '2026-11-12T20:00:00+09:00')
    forecast_id = _submit(league_conn, _ready(league_conn), raw_score=11.0, source_ref='run-1')
    row = league_conn.execute('SELECT * FROM forecasts WHERE forecast_id = ?', (forecast_id,)).fetchone()
    assert row['asof_ts'] == '2026-11-12T06:30:00Z'
    assert row['created_at'] == '2026-11-12T11:00:00Z'
    assert (row['probability'], row['raw_score'], row['source_ref'], row['official']) == (0.4, 11.0, 'run-1', 1)


def test_submission_at_or_after_the_next_open_is_rejected(league_conn, monkeypatch):
    capsule = _ready(league_conn)
    _at(monkeypatch, '2026-11-13T09:00:00+09:00')
    with pytest.raises(ledger.SubmissionRejected) as error:
        _submit(league_conn, capsule)
    assert error.value.code == 'late_submission'
    _at(monkeypatch, '2026-11-13T08:59:59+09:00')
    assert _submit(league_conn, capsule)


def test_friday_forecast_can_be_submitted_over_the_weekend(league_conn, monkeypatch):
    capsule = _ready(league_conn)
    _at(monkeypatch, '2026-11-15T22:00:00+09:00')
    assert _submit(league_conn, capsule, asof_ts='2026-11-13T15:30:00+09:00')
    _at(monkeypatch, '2026-11-16T09:00:00+09:00')
    with pytest.raises(ledger.SubmissionRejected) as error:
        _submit(league_conn, capsule, asof_ts='2026-11-13T15:30:00+09:00', stock_code='000660')
    assert error.value.code == 'late_submission'


def test_future_asof_is_rejected(league_conn, monkeypatch):
    capsule = _ready(league_conn)
    _at(monkeypatch, '2026-11-12T15:00:00+09:00')
    with pytest.raises(ledger.SubmissionRejected) as error:
        _submit(league_conn, capsule)
    assert error.value.code == 'asof_in_future'


@pytest.mark.parametrize('probability', [0.0, 0.019, 0.981, 1.0, float('nan'), True, '0.5'])
def test_probability_outside_the_range_is_rejected_not_clipped(league_conn, monkeypatch, probability):
    _at(monkeypatch, '2026-11-12T20:00:00+09:00')
    with pytest.raises(ledger.SubmissionRejected) as error:
        _submit(league_conn, _ready(league_conn), probability=probability)
    assert error.value.code in {'probability_out_of_range', 'invalid_probability'}
    assert league_conn.execute('SELECT COUNT(*) FROM forecasts').fetchone()[0] == 0


def test_boundary_probabilities_are_accepted(league_conn, monkeypatch):
    _at(monkeypatch, '2026-11-12T20:00:00+09:00')
    capsule = _ready(league_conn)
    assert _submit(league_conn, capsule, probability=0.02)
    assert _submit(league_conn, capsule, probability=0.98, stock_code='000660')


def test_duplicate_key_is_rejected(league_conn, monkeypatch):
    _at(monkeypatch, '2026-11-12T20:00:00+09:00')
    capsule = _ready(league_conn)
    _submit(league_conn, capsule)
    with pytest.raises(ledger.SubmissionRejected) as error:
        _submit(league_conn, capsule, probability=0.9, asof_ts='2026-11-12T06:30:00Z')
    assert error.value.code == 'duplicate'


def test_missing_capsule_forecaster_event_or_code_is_rejected(league_conn, monkeypatch):
    _at(monkeypatch, '2026-11-12T20:00:00+09:00')
    capsule = _ready(league_conn)
    cases = [(dict(capsule_hash='0' * 64), 'capsule_missing'), (dict(forecaster_id='nobody'), 'unknown_forecaster'),
             (dict(event_id='E9'), 'unknown_event'), (dict(stock_code='5930'), 'invalid_stock_code'),
             (dict(asof_ts='2026-11-12T15:30:00'), 'invalid_asof')]
    for override, code in cases:
        with pytest.raises(ledger.SubmissionRejected) as error:
            _submit(league_conn, capsule, **override)
        assert error.value.code == code


def test_forecaster_registration_is_idempotent_but_not_mutable(league_conn):
    ledger.register_forecaster(league_conn, 'fx', '1', 'engine', 'native')
    ledger.register_forecaster(league_conn, 'fx', '1', 'engine', 'native')
    assert league_conn.execute('SELECT COUNT(*) FROM forecasters').fetchone()[0] == 1
    with pytest.raises(ValueError):
        ledger.register_forecaster(league_conn, 'fx', '1', 'engine', 'derived')
    with pytest.raises(ValueError):
        ledger.register_forecaster(league_conn, 'fy', '1', 'robot', 'native')


def test_abstention_is_recorded_once(league_conn):
    ledger.register_forecaster(league_conn, 'fx', '1', 'engine', 'native')
    for _ in range(2):
        ledger.record_abstention(league_conn, forecaster_id='fx', version='1', stock_code='005930',
                                 asof_ts=ASOF, event_id='E1', reason='tool_failure')
    rows = league_conn.execute('SELECT asof_ts, reason FROM abstentions').fetchall()
    assert [tuple(row) for row in rows] == [('2026-11-12T06:30:00Z', 'tool_failure')]


def test_module_exposes_no_way_to_change_a_forecast():
    public = [name for name in dir(ledger) if not name.startswith('_')]
    assert not [name for name in public if any(word in name.lower() for word in
                                               ('update', 'delete', 'remove', 'edit', 'amend', 'replace'))]


def test_clamp_probability():
    assert ledger.clamp_probability(0.0) == 0.02
    assert ledger.clamp_probability(1.0) == 0.98
    assert ledger.clamp_probability(0.5) == 0.5

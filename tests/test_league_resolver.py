from datetime import datetime, timezone

import pytest

from app.services.forecast_league import bars, capsules, ledger, resolver

WEEKDAYS = lambda day: day.weekday() < 5  # noqa: E731
SESSIONS = ['2026-11-13', '2026-11-16', '2026-11-17', '2026-11-18', '2026-11-19', '2026-11-20',
            '2026-11-23', '2026-11-24']


@pytest.fixture
def forecast(league_conn, monkeypatch):
    moment = datetime(2026, 11, 12, 11, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(ledger, '_now', lambda: moment)
    monkeypatch.setattr(ledger, '_is_trading_day', WEEKDAYS)
    monkeypatch.setattr(resolver, '_now', lambda: datetime(2026, 12, 1, tzinfo=timezone.utc))
    monkeypatch.delenv('MIROFISH_SLIPPAGE_PCT', raising=False)
    ledger.register_forecaster(league_conn, 'fx', '1', 'engine', 'native')
    return ledger.submit_forecast(
        league_conn, forecaster_id='fx', version='1', stock_code='005930',
        asof_ts='2026-11-12T15:30:00+09:00', event_id='E1', probability=0.4,
        capsule_hash=capsules.put_capsule(league_conn, {'k': 1}))


def _bar(conn, day, open_=100.0, high=103.0, low=97.0, close=100.0, basis=bars.BASIS_REGULAR):
    bars.put_bar(conn, stock_code='005930', session_date=day, basis=basis, open=open_, high=high,
                 low=low, close=close, captured_at='t')


def _row(conn, forecast_id):
    return conn.execute('SELECT * FROM resolutions WHERE forecast_id = ?', (forecast_id,)).fetchone()


def test_target_resolves_as_a_success(league_conn, forecast):
    _bar(league_conn, SESSIONS[0])
    _bar(league_conn, SESSIONS[1], high=108.5)
    summary = resolver.resolve_pending(league_conn, today='2026-11-16', trading_day=WEEKDAYS)
    row = _row(league_conn, forecast)
    assert summary == {'resolved': 1, 'void': 0, 'pending': 0}
    assert (row['status'], row['outcome'], row['exit_reason']) == ('resolved', 1, 'target')
    assert (row['entry_date'], row['exit_date'], row['entry_price']) == ('2026-11-13', '2026-11-16', 100.0)
    assert row['net_return'] == pytest.approx(7.77)
    assert row['price_source_version'] == bars.REGULAR_SOURCE_VERSION
    assert row['resolved_at'] == '2026-12-01T00:00:00Z'


def test_missing_session_keeps_the_forecast_pending(league_conn, forecast):
    _bar(league_conn, SESSIONS[0])
    _bar(league_conn, SESSIONS[2], high=120.0)          # 11-16 봉이 없으므로 11-17 은 쓰지 않는다
    summary = resolver.resolve_pending(league_conn, today='2026-11-17', trading_day=WEEKDAYS)
    assert summary == {'resolved': 0, 'void': 0, 'pending': 1}
    assert _row(league_conn, forecast) is None


def test_only_regular_session_bars_are_used(league_conn, forecast):
    _bar(league_conn, SESSIONS[0], high=120.0, basis=bars.BASIS_UNIVERSE)
    assert resolver.resolve_pending(league_conn, today='2026-11-13', trading_day=WEEKDAYS)['pending'] == 1


def test_expiry_resolves_as_a_failure(league_conn, forecast):
    for day in SESSIONS:
        _bar(league_conn, day)
    resolver.resolve_pending(league_conn, today='2026-11-24', trading_day=WEEKDAYS)
    row = _row(league_conn, forecast)
    assert (row['outcome'], row['exit_reason'], row['exit_date']) == (0, 'expiry', '2026-11-24')


def test_resolution_is_idempotent(league_conn, forecast):
    _bar(league_conn, SESSIONS[0], low=90.0)
    first = resolver.resolve_pending(league_conn, today='2026-11-13', trading_day=WEEKDAYS)
    second = resolver.resolve_pending(league_conn, today='2026-11-13', trading_day=WEEKDAYS)
    assert first['resolved'] == 1 and second == {'resolved': 0, 'void': 0, 'pending': 0}
    assert league_conn.execute('SELECT COUNT(*) FROM resolutions').fetchone()[0] == 1


def test_unresolvable_forecast_is_voided_after_twenty_sessions(league_conn, forecast):
    assert resolver.resolve_pending(league_conn, today='2026-12-10', trading_day=WEEKDAYS)['pending'] == 1
    summary = resolver.resolve_pending(league_conn, today='2026-12-11', trading_day=WEEKDAYS)  # 21번째 거래일
    row = _row(league_conn, forecast)
    assert summary == {'resolved': 0, 'void': 1, 'pending': 0}
    assert (row['status'], row['outcome'], row['net_return']) == ('void', None, None)


def test_forecast_is_not_resolved_before_its_entry_session(league_conn, forecast):
    assert resolver.resolve_pending(league_conn, today='2026-11-12', trading_day=WEEKDAYS) == {
        'resolved': 0, 'void': 0, 'pending': 1}

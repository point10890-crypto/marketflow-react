import pytest

from app.services.forecast_league import bars


def _put(conn, **over):
    args = dict(stock_code='005930', session_date='2026-11-12', basis=bars.BASIS_REGULAR,
                open=100.0, high=110.0, low=95.0, close=105.0, captured_at='2026-11-12T11:40:00Z')
    args.update(over)
    return bars.put_bar(conn, **args)


def test_regular_bar_is_stored_once_and_never_replaced(league_conn):
    assert _put(league_conn) is True
    assert _put(league_conn, close=999.0, high=999.0) is False
    assert [row['close'] for row in bars.get_bars(league_conn, '005930', bars.BASIS_REGULAR, '2026-11-01')] == [105.0]
    with pytest.raises(ValueError):
        _put(league_conn, replace=True)


def test_universe_bar_can_be_replaced(league_conn):
    _put(league_conn, basis=bars.BASIS_UNIVERSE)
    assert _put(league_conn, basis=bars.BASIS_UNIVERSE, close=50.0, low=45.0, open=50.0, high=55.0, replace=True) is True
    assert bars.get_bars(league_conn, '005930', bars.BASIS_UNIVERSE, '2026-11-01')[0]['close'] == 50.0


@pytest.mark.parametrize('over', [dict(open=0), dict(low=101.0), dict(high=104.0), dict(close=-1),
                                   dict(session_date='20261112'), dict(basis='other')])
def test_invalid_bars_are_not_stored(league_conn, over):
    assert _put(league_conn, **over) is False
    assert league_conn.execute('SELECT COUNT(*) FROM bars').fetchone()[0] == 0


def test_bars_are_returned_in_date_order_within_the_range(league_conn):
    for day in ('2026-11-13', '2026-11-11', '2026-11-12'):
        _put(league_conn, session_date=day)
    _put(league_conn, session_date='2026-11-12', stock_code='000660')
    rows = bars.get_bars(league_conn, '005930', bars.BASIS_REGULAR, '2026-11-12', '2026-11-13')
    assert [row['date'] for row in rows] == ['2026-11-12', '2026-11-13']
    assert set(rows[0]) == {'date', 'open', 'high', 'low', 'close'}

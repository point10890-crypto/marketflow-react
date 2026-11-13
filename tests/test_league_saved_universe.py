from copy import deepcopy
from datetime import date, datetime, timedelta, timezone

import pytest

from app.services.forecast_league import baselines, clock, ledger, saved_universe
from app.services.league_worker import handlers


@pytest.fixture
def sealed(monkeypatch):
    monkeypatch.setattr(clock, 'is_trading_day', lambda d: d.weekday() < 5)
    monkeypatch.setattr(ledger, '_is_trading_day', lambda d: d.weekday() < 5)
    monkeypatch.setattr(ledger, '_now', lambda: datetime(2026, 11, 12, 22, 30, tzinfo=timezone.utc))
    cursor, days = date(2026, 11, 12), []
    while len(days) < 60:
        if cursor.weekday() < 5:
            days.append(cursor.isoformat())
        cursor -= timedelta(days=1)
    return {'latest_session': '2026-11-12', 'prices_by_symbol': {
        code: [dict(date=d, open=100, high=110, low=99, close=100) for d in reversed(days)]
        for code in ['005930', '000660']}}


def test_frozen_inputs_submit_without_new_provider_requests(league_conn, sealed):
    first = saved_universe.sync_saved_universe(league_conn, today='2026-11-13', loader=lambda: sealed)
    summary = handlers._submit_baselines(league_conn, {'asof_date': '2026-11-12'})
    assert summary == {'candidates': 2, 'submitted': 4, 'abstained': 0, 'duplicate': 0}
    def unexpected_network():
        raise AssertionError('already complete')
    again = saved_universe.sync_saved_universe(league_conn, today='2026-11-13', loader=unexpected_network)
    assert again['reused'] and again['capsule_hash'] == first['capsule_hash']
    assert handlers._submit_baselines(league_conn, {'asof_date': '2026-11-12'})['duplicate'] == 4


@pytest.mark.parametrize('kind', ['stale', 'empty', 'too_many'])
def test_invalid_scope_cannot_publish(league_conn, sealed, kind):
    data = deepcopy(sealed)
    if kind == 'stale':
        data['latest_session'] = '2026-11-11'
    elif kind == 'empty':
        data['prices_by_symbol'] = {}
    else:
        data['prices_by_symbol'] = {str(i): [] for i in range(101)}
    with pytest.raises(RuntimeError):
        saved_universe.sync_saved_universe(league_conn, today='2026-11-13', loader=lambda: data)
    assert league_conn.execute('SELECT COUNT(*) FROM universe_snapshots').fetchone()[0] == 0

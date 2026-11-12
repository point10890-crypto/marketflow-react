from datetime import datetime, timezone

import pandas as pd
import pytest

from app.services.forecast_league import bars, capsules, ledger, price_sources

WEEKDAYS = lambda day: day.weekday() < 5  # noqa: E731


class FakeProvider:
    def __init__(self, failing=()):
        self.calls, self.failing = [], set(failing)

    def fetch_session(self, symbol, session):
        self.calls.append((symbol, session))
        if (symbol, session) in self.failing:
            error = ValueError('regular_boundaries')
            error.code = 'regular_boundaries'
            raise error
        return {'symbol': symbol, 'session': session, 'captured_at': '2026-11-13T11:45:00Z',
                'bar': {'open': 100.0, 'high': 110.0, 'low': 95.0, 'close': 105.0, 'volume': 10, 'traded_value': 1},
                'pages': [{'params': {}, 'response': {'output2': [1, 2, 3]}}],
                'source': {'version': 'kis-regular-j-minute-v1'}}


@pytest.fixture
def forecast(league_conn, monkeypatch):
    monkeypatch.setattr(ledger, '_now', lambda: datetime(2026, 11, 12, 11, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(ledger, '_is_trading_day', WEEKDAYS)
    ledger.register_forecaster(league_conn, 'fx', '1', 'engine', 'native')
    capsule = capsules.put_capsule(league_conn, {'k': 1})
    for code in ('005930', '000660'):
        ledger.submit_forecast(league_conn, forecaster_id='fx', version='1', stock_code=code,
                               asof_ts='2026-11-12T15:30:00+09:00', event_id='E1', probability=0.4,
                               capsule_hash=capsule)


def _targets(conn, now_kst):
    now = datetime.fromisoformat(now_kst).astimezone(timezone.utc)
    return price_sources.needed_regular_targets(conn, now=now, trading_day=WEEKDAYS)


def test_targets_cover_missing_sessions_of_unresolved_forecasts(league_conn, forecast):
    assert _targets(league_conn, '2026-11-12T21:00:00+09:00') == []            # 진입일 전
    assert _targets(league_conn, '2026-11-13T20:39:00+09:00') == []            # 당일은 20:40 이후
    assert _targets(league_conn, '2026-11-13T20:40:00+09:00') == [('000660', '2026-11-13'), ('005930', '2026-11-13')]
    bars.put_bar(league_conn, stock_code='005930', session_date='2026-11-13', basis=bars.BASIS_REGULAR,
                 open=1, high=1, low=1, close=1, captured_at='t')
    assert _targets(league_conn, '2026-11-17T08:00:00+09:00') == [
        ('000660', '2026-11-13'), ('000660', '2026-11-16'), ('005930', '2026-11-16')]


def test_targets_stop_at_eight_sessions_and_skip_resolved(league_conn, forecast):
    assert len(_targets(league_conn, '2026-12-31T21:00:00+09:00')) == 16
    league_conn.execute("INSERT INTO resolutions (forecast_id, status, resolved_at, price_source_version) "
                        "SELECT forecast_id, 'void', 't', 'v' FROM forecasts WHERE stock_code = '005930'")
    assert {code for code, _ in _targets(league_conn, '2026-12-31T21:00:00+09:00')} == {'000660'}


def test_collect_stores_bars_with_compact_evidence(league_conn):
    provider = FakeProvider(failing={('000660', '2026-11-13')})
    summary = price_sources.collect_regular_bars(
        league_conn, provider=provider, targets=[('005930', '2026-11-13'), ('000660', '2026-11-13')])
    assert summary == {'stored': 1, 'failed': [['000660', '2026-11-13', 'regular_boundaries']]}
    row = league_conn.execute('SELECT * FROM bars').fetchone()
    assert (row['stock_code'], row['basis'], row['open'], row['high'], row['low'], row['close']) == (
        '005930', bars.BASIS_REGULAR, 100.0, 110.0, 95.0, 105.0)
    evidence = capsules.get_capsule(league_conn, row['evidence_hash'])
    assert evidence['source_version'] == 'kis-regular-j-minute-v1'
    assert len(evidence['pages_sha256']) == 64 and 'pages' not in evidence


def test_universe_sync_never_stores_todays_bar(league_conn, monkeypatch):
    monkeypatch.setattr(price_sources, '_now', lambda: datetime(2026, 11, 12, 22, 30, tzinfo=timezone.utc))
    requested = []

    def reader(code, start, end):
        requested.append((code, start, end))
        index = pd.to_datetime(['2026-11-11', '2026-11-12', '2026-11-13'])
        return pd.DataFrame({'Open': [100, 0, 100], 'High': [110, 110, 110], 'Low': [95, 95, 95],
                             'Close': [105, 105, 105]}, index=index)

    summary = price_sources.sync_universe_bars(league_conn, today='2026-11-13', codes=['005930', 'ABCDEF'],
                                               reader=reader)
    assert requested == [('005930', '2025-09-19', '2026-11-12')]              # 처음: 420일, 어제까지
    assert summary == {'codes': 1, 'stored': 1, 'failed': 0}                   # 11-12 는 시가 0, 11-13 은 오늘
    assert [row['session_date'] for row in league_conn.execute('SELECT session_date FROM bars')] == ['2026-11-11']


def test_universe_sync_refreshes_a_recent_window_and_survives_reader_errors(league_conn, monkeypatch):
    monkeypatch.setattr(price_sources, '_now', lambda: datetime(2026, 11, 12, 22, 30, tzinfo=timezone.utc))
    bars.put_bar(league_conn, stock_code='005930', session_date='2026-11-11', basis=bars.BASIS_UNIVERSE,
                 open=100, high=110, low=95, close=105, captured_at='t')
    requested = []

    def reader(code, start, end):
        requested.append(start)
        if code == '000660':
            raise RuntimeError('network')
        return pd.DataFrame({'Open': [50], 'High': [55], 'Low': [45], 'Close': [52]},
                            index=pd.to_datetime(['2026-11-11']))

    summary = price_sources.sync_universe_bars(league_conn, today='2026-11-13', codes=['005930', '000660'],
                                               reader=reader)
    assert set(requested) == {'2026-09-29'}                                     # 45일 창
    assert summary == {'codes': 2, 'stored': 1, 'failed': 1}
    assert league_conn.execute('SELECT close FROM bars').fetchone()[0] == 52.0  # 덮어씀

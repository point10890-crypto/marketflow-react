import hashlib
import json
from datetime import datetime, timezone

import pandas as pd
import pytest

from app.services.forecast_league import bars, capsules, ledger, price_sources
from tests.test_league_regular_vi import result as regular_result

@pytest.fixture(autouse=True)
def collection_clock(monkeypatch):
    monkeypatch.setattr(price_sources.clock, 'now_utc', lambda: datetime(2026, 11, 14, 3, tzinfo=timezone.utc))


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
        return regular_result(delayed=False, symbol=symbol, session=session, now=datetime(2026,11,13,11,45,tzinfo=timezone.utc))


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
    assert evidence['source_version'] == 'league-kis-regular-vi-v2'
    assert len(evidence['pages_sha256']) == 64 and evidence['source_evidence']['pages']


def test_universe_sync_never_stores_todays_bar(league_conn, monkeypatch):
    monkeypatch.setattr(price_sources, '_now', lambda: datetime(2026, 11, 12, 22, 30, tzinfo=timezone.utc))
    requested = []

    def reader(code, start, end):
        requested.append((code, start, end))
        index = pd.to_datetime(['2026-11-11', '2026-11-12', '2026-11-13'])
        return pd.DataFrame({'Open': [100, 0, 100], 'High': [110, 110, 110], 'Low': [95, 95, 95],
                             'Close': [105, 105, 105]}, index=index)

    summary = price_sources.sync_universe_bars(league_conn, today='2026-11-13', codes=['005930', 'ABCDEF'],
                                               reader=reader, trading_day=WEEKDAYS)
    assert requested == [('005930', '2025-09-19', '2026-11-12')]              # 처음: 420일, 어제까지
    assert summary == {'codes': 1, 'stored': 1, 'failed': 0, 'empty': 0}       # 11-12 는 시가 0, 11-13 은 오늘
    assert [row['session_date'] for row in league_conn.execute('SELECT session_date FROM bars')] == ['2026-11-11']


def test_universe_sync_refreshes_a_recent_window_and_survives_reader_errors(league_conn, monkeypatch):
    monkeypatch.setattr(price_sources, '_now', lambda: datetime(2026, 11, 12, 22, 30, tzinfo=timezone.utc))
    bars.put_bar(league_conn, stock_code='005930', session_date='2026-11-11', basis=bars.BASIS_UNIVERSE,
                 open=100, high=110, low=95, close=105, captured_at='t')
    requested = {}

    def reader(code, start, end):
        requested[code] = start
        if code == '000660':
            raise RuntimeError('network')
        return pd.DataFrame({'Open': [50], 'High': [55], 'Low': [45], 'Close': [52]},
                            index=pd.to_datetime(['2026-11-11']))

    summary = price_sources.sync_universe_bars(league_conn, today='2026-11-13', codes=['005930', '000660'],
                                               reader=reader, trading_day=WEEKDAYS)
    assert requested['005930'] == '2026-09-29'                                  # 봉이 있는 종목은 45일 창
    assert summary == {'codes': 2, 'stored': 1, 'failed': 1, 'empty': 0}
    assert league_conn.execute('SELECT close FROM bars').fetchone()[0] == 52.0  # 덮어씀


def _frame(dates, open_=100):
    count = len(dates)
    return pd.DataFrame({'Open': [open_] * count, 'High': [110] * count, 'Low': [95] * count,
                         'Close': [105] * count}, index=pd.to_datetime(dates))


@pytest.fixture
def sync_clock(monkeypatch):
    monkeypatch.setattr(price_sources, '_now', lambda: datetime(2026, 11, 12, 22, 30, tzinfo=timezone.utc))


def test_universe_sync_picks_the_window_per_stock(league_conn, sync_clock):
    bars.put_bar(league_conn, stock_code='005930', session_date='2026-11-11', basis=bars.BASIS_UNIVERSE,
                 open=100, high=110, low=95, close=105, captured_at='t')
    bars.put_bar(league_conn, stock_code='000660', session_date='2026-11-11', basis=bars.BASIS_REGULAR,
                 open=100, high=110, low=95, close=105, captured_at='t')        # 정규장 봉은 이력으로 치지 않는다
    requested = {}

    def reader(code, start, end):
        requested[code] = start
        return _frame(['2026-11-12'])

    price_sources.sync_universe_bars(league_conn, today='2026-11-13', codes=['005930', '000660'],
                                     reader=reader, trading_day=WEEKDAYS)
    assert requested == {'005930': '2026-09-29', '000660': '2025-09-19'}        # 있는 종목 45일, 없는 종목 420일


def test_universe_sync_raises_when_every_reader_returns_nothing(league_conn, sync_clock):
    frames = iter([_frame([]), None, _frame([])])
    with pytest.raises(RuntimeError) as error:
        price_sources.sync_universe_bars(league_conn, today='2026-11-13', codes=['005930', '000660', '035720'],
                                         reader=lambda code, start, end: next(frames), trading_day=WEEKDAYS)
    assert 'empty=3' in str(error.value) and 'stored=0' in str(error.value)


def test_universe_sync_raises_when_more_than_half_fail_but_keeps_stored_bars(league_conn, sync_clock):
    def reader(code, start, end):
        if code == '005930':
            return _frame(['2026-11-12'])
        if code == '000660':
            raise RuntimeError('network')
        return _frame([])

    with pytest.raises(RuntimeError) as error:
        price_sources.sync_universe_bars(league_conn, today='2026-11-13', codes=['005930', '000660', '035720'],
                                         reader=reader, trading_day=WEEKDAYS)
    assert 'failed=1' in str(error.value) and 'empty=1' in str(error.value) and 'codes=3' in str(error.value)
    league_conn.rollback()
    assert league_conn.execute('SELECT COUNT(*) FROM bars').fetchone()[0] == 1   # 이미 커밋된 봉은 남는다


def test_universe_sync_reports_empty_codes_without_raising_at_half(league_conn, sync_clock):
    summary = price_sources.sync_universe_bars(
        league_conn, today='2026-11-13', codes=['005930', '000660'], trading_day=WEEKDAYS,
        reader=lambda code, start, end: _frame(['2026-11-12'] if code == '005930' else []))
    assert summary == {'codes': 2, 'stored': 1, 'failed': 0, 'empty': 1}


def test_universe_sync_skips_rows_on_non_trading_days(league_conn, sync_clock):
    summary = price_sources.sync_universe_bars(
        league_conn, today='2026-11-13', codes=['005930'], trading_day=WEEKDAYS,
        reader=lambda code, start, end: _frame(['2026-11-06', '2026-11-07', '2026-11-09']))   # 금, 토, 월
    assert summary['stored'] == 2
    assert [row[0] for row in league_conn.execute('SELECT session_date FROM bars ORDER BY session_date')] == [
        '2026-11-06', '2026-11-09']


def test_universe_sync_uses_the_league_calendar_by_default(league_conn, sync_clock, monkeypatch):
    monkeypatch.setattr(price_sources.clock, 'is_trading_day', lambda day: day.isoformat() != '2026-11-10')
    price_sources.sync_universe_bars(league_conn, today='2026-11-13', codes=['005930'],
                                     reader=lambda code, start, end: _frame(['2026-11-09', '2026-11-10']))
    assert [row[0] for row in league_conn.execute('SELECT session_date FROM bars')] == ['2026-11-09']


class StaticProvider:
    def __init__(self, bar=None, captured=None):
        self.bar = bar or {'open': 100.0, 'high': 110.0, 'low': 95.0, 'close': 105.0}
        self.captured = iter(captured or [])

    def fetch_session(self, symbol, session):
        captured = next(self.captured, '2026-11-13T11:45:00Z')
        value = regular_result(delayed=False, symbol=symbol, session=session, now=datetime.fromisoformat(captured.replace('Z','+00:00')))
        value['bar'].update(self.bar)
        return value


def test_collect_reports_an_invalid_bar_and_leaves_no_capsule(league_conn):
    provider = StaticProvider(bar={'open': 0, 'high': 110.0, 'low': 95.0, 'close': 105.0})
    summary = price_sources.collect_regular_bars(league_conn, provider=provider, targets=[('005930', '2026-11-13')])
    assert summary == {'stored': 0, 'failed': [['005930', '2026-11-13', 'invalid_bar']]}
    assert league_conn.execute('SELECT COUNT(*) FROM capsules').fetchone()[0] == 0
    assert league_conn.execute('SELECT COUNT(*) FROM bars').fetchone()[0] == 0


def test_collect_does_not_report_an_existing_bar_as_failed(league_conn):
    bars.put_bar(league_conn, stock_code='005930', session_date='2026-11-13', basis=bars.BASIS_REGULAR,
                 open=1, high=1, low=1, close=1, captured_at='t')
    summary = price_sources.collect_regular_bars(league_conn, provider=StaticProvider(),
                                                 targets=[('005930', '2026-11-13')])
    assert summary == {'stored': 0, 'failed': []}
    assert league_conn.execute('SELECT open FROM bars').fetchone()[0] == 1.0


def test_source_capsule_is_self_contained_and_replayable(league_conn, monkeypatch):
    from app.services.forecast_league import regular_vi
    monkeypatch.setattr(price_sources.clock, 'now_utc', lambda: datetime(2026, 11, 14, 3, tzinfo=timezone.utc))
    provider = StaticProvider(captured=['2026-11-13T11:45:00Z', '2026-11-14T02:00:00Z'])
    summary = price_sources.collect_regular_bars(league_conn, provider=provider,
                         targets=[('005930', '2026-11-13'), ('000660', '2026-11-13')])
    assert summary['stored'] == 2
    for row in league_conn.execute('SELECT * FROM bars'):
        evidence = capsules.get_capsule(league_conn, row['evidence_hash'])
        regular_vi.replay(evidence['source_evidence'], row['stock_code'], row['session_date'], price_sources.clock.now_utc())

"""Regression probes from the independent outcome-ledger review; no live I/O."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone

import pytest

from app.services.catalyst_outcomes import analytics, prices, service, sources
from app.services.surge_trace.common import stamp


NOW = datetime(2026, 11, 11, 2, tzinfo=timezone.utc)


def civil_days(start, end):
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    return [(first + timedelta(days=n)).isoformat() for n in range((last - first).days + 1)]


def fixtures():
    days = [day for day in civil_days('2026-06-01', '2026-11-10')
            if date.fromisoformat(day).weekday() < 5]
    rows = [dict(date=day, close=100 + n, fetched_at=NOW.isoformat(),
                 source='naver_closed_daily', price_basis='provider_adjusted') for n, day in enumerate(days)]
    anchor = days[65]
    event = dict(id='first', symbol='005930', name='삼성전자', title='삼성전자 공급 계약',
                 url='https://one.example.com/article', source='omni', event_type='contract',
                 published_at=anchor + 'T08:00:00+09:00', first_seen_at=anchor + 'T10:00:00+09:00',
                 anchor_at=anchor + 'T10:00:00+09:00', analysis_basis='received',
                 verification='reported_unverified', verification_at=None)
    known = {day: date.fromisoformat(day).weekday() < 5 for day in civil_days(days[0], days[-1])}
    return rows, event, known


class CalendarProvider:
    def __init__(self, omitted=()):
        self.omitted = set(omitted)
        self.calls = []

    def fetch_calendar(self, base):
        self.calls.append(base)
        last = (date.fromisoformat(base) + timedelta(days=30)).isoformat()
        return dict(source='KIS:CTCA0903R', captured_at=NOW.isoformat(), days=[
            dict(date=day, is_open=date.fromisoformat(day).weekday() < 5)
            for day in civil_days(base, last) if day not in self.omitted])


def test_unknown_calendar_day_cannot_shift_a_completed_horizon(tmp_path):
    rows, event, _ = fixtures()
    missing = rows[69]['date']
    provider = CalendarProvider(omitted=[missing])
    diagnostic = prices.acquire_calendar(tmp_path, event['anchor_at'][:10], rows[87]['date'], NOW,
                                         provider=provider, max_fetch=1)
    result = analytics.evaluate_case(event, rows, diagnostic['calendar_sessions'], NOW,
                                     verified_days=diagnostic['calendar_confirmed_days'])
    assert missing not in diagnostic['calendar_confirmed_days']
    assert diagnostic['calendar_verified'] is False
    assert result['horizons']['10']['status'] == 'blocked'
    assert result['horizons']['10']['net_return'] is None


@pytest.mark.parametrize('missing_index', [66, 69, 76])
def test_confirmed_open_day_without_price_blocks_without_moving_exit(missing_index):
    rows, event, known = fixtures()
    calendar = [day for day, opened in known.items() if opened]
    complete = analytics.evaluate_case(event, rows, calendar, NOW, verified_days=known)
    absent = rows[:missing_index] + rows[missing_index + 1:]
    result = analytics.evaluate_case(event, absent, calendar, NOW, verified_days=known)
    assert result['horizons']['10']['status'] == 'missing'
    assert result['horizons']['10']['exit_date'] == complete['horizons']['10']['exit_date']
    assert result['horizons']['10']['net_return'] is None


def test_lost_calendar_confirmation_blocks_and_restores_first_completed_numbers():
    rows, event, known = fixtures()
    calendar = [day for day, opened in known.items() if opened]
    complete = analytics.evaluate_case(event, rows, calendar, NOW, verified_days=known)
    incomplete = dict(known)
    del incomplete[rows[69]['date']]
    blocked = analytics.evaluate_case(event, rows, calendar, NOW, previous=complete, verified_days=incomplete)
    assert blocked['horizons']['10']['status'] == 'blocked'
    assert blocked['horizons']['10']['source_revision'] is False
    for field in ('entry_date', 'exit_date', 'entry_price', 'exit_price', 'net_return', 'source_hash'):
        assert blocked['horizons']['10'][field] == complete['horizons']['10'][field]
    restored = analytics.evaluate_case(event, rows, calendar, NOW, previous=blocked, verified_days=known)
    assert restored['horizons'] == complete['horizons']


def test_official_calendar_seed_conflict_is_not_silently_certified(tmp_path):
    evidence = {day: dict(is_open=True, source='KIS:CTCA0903R', captured_at=NOW.isoformat())
                for day in ('2026-11-09', '2026-11-10')}
    seed = prices._calendar_diagnostics(evidence, {'2026-11-09'})
    assert not prices.calendar_window_verified(seed, '2026-11-09', '2026-11-10')
    result = prices.acquire_calendar(tmp_path, '2026-11-09', '2026-11-10', NOW,
                                     provider=CalendarProvider(), max_fetch=0, seed=seed)
    assert '2026-11-09' in result['calendar_conflicts']
    assert result['calendar_verified'] is False


def test_ledger_keeps_completed_returns_and_withdrawal_after_source_retention(tmp_path, monkeypatch):
    rows, event, known = fixtures()
    state = dict(events=[event], withdrawn=[])
    calendar = [day for day, opened in known.items() if opened]
    monkeypatch.setattr(sources, 'load_events', lambda *args: (deepcopy(state['events']),
        dict(status='ready', source_counts={}, withdrawn_keys=state['withdrawn'])))
    monkeypatch.setattr(prices, 'load_closes', lambda *args: ({'005930': rows}, dict(status='ready')))
    monkeypatch.setattr(prices, 'acquire_calendar', lambda *args, **kwargs:
        dict(calendar_sessions=calendar, calendar_confirmed_days=known, calendar_verified=True))
    monkeypatch.setattr(prices, 'load_current_prices', lambda *args, **kwargs:
        ({}, dict(pending_symbols=[], errors={})))
    service.run_once(root=tmp_path, project_root=tmp_path, now=NOW)
    first = service.read_view(root=tmp_path, now=NOW, filter='all')['cases'][0]
    assert first['horizons']['10']['status'] == 'completed'
    state.update(events=[], withdrawn=[['005930', 'url', event['url']]])
    service.run_once(root=tmp_path, project_root=tmp_path, now=NOW + timedelta(hours=5))
    state.update(events=[event], withdrawn=[])
    service.run_once(root=tmp_path, project_root=tmp_path, now=NOW + timedelta(days=1))
    final = service.read_view(root=tmp_path, now=NOW + timedelta(days=1), filter='all')
    assert len(final['cases']) == 1
    assert final['cases'][0]['exclusion'] == 'withdrawn'
    assert final['cases'][0]['horizons'] == first['horizons']
    assert final['coverage']['positive_events'] == final['coverage']['matured_events'] == 0
    assert service.read_view(root=tmp_path, now=NOW + timedelta(days=1), filter='rising')['cases'] == []


def test_syndicated_reappearance_keeps_original_anchor_and_completed_outcome():
    rows, event, known = fixtures()
    calendar = [day for day, opened in known.items() if opened]
    complete = analytics.evaluate_case(event, rows, calendar, NOW, verified_days=known)
    later = dict(event, id='second', url='https://two.example.com/article',
                 first_seen_at=rows[66]['date'] + 'T10:00:00+09:00',
                 anchor_at=rows[66]['date'] + 'T10:00:00+09:00')
    reconciled = service._reconcile({complete['id']: complete}, [later],
                                    {'identity_aliases': {'second': sources.event_keys(later)}}, [])
    assert len(reconciled) == 1
    assert reconciled[0]['id'] == event['id']
    assert reconciled[0]['anchor_at'] == event['anchor_at']
    restored = analytics.evaluate_case(reconciled[0], rows, calendar, NOW, previous=complete, verified_days=known)
    assert restored['horizons'] == complete['horizons']
    assert analytics.support([restored], NOW)['005930']['matured'] == 1


def test_live_publication_clock_is_not_before_its_consumed_price_capture(tmp_path, monkeypatch):
    rows, event, known = fixtures()
    latest = dict(event, id='recent', url='https://one.example.com/new', title='삼성전자 신규 공급 계약',
                  published_at=rows[-1]['date'] + 'T08:00:00+09:00',
                  anchor_at=rows[-1]['date'] + 'T10:00:00+09:00',
                  first_seen_at=rows[-1]['date'] + 'T10:00:00+09:00')
    captured = NOW + timedelta(seconds=8)
    finished = NOW + timedelta(seconds=10)
    bars = [dict(row, open=row['close'], high=row['close'] + 1, low=row['close'] - 1,
                 volume=10_000_000, traded_value=2_000_000_000, quality_flags=[]) for row in rows]
    monkeypatch.setattr(sources, 'load_events', lambda *args: ([event, latest], dict(status='ready')))
    monkeypatch.setattr(prices, 'load_closes', lambda *args: ({'005930': rows}, dict(status='ready')))
    monkeypatch.setattr(prices, 'acquire_calendar', lambda *args, **kwargs:
        dict(calendar_sessions=[day for day, opened in known.items() if opened],
             calendar_confirmed_days=known, calendar_verified=True))
    monkeypatch.setattr(prices, 'load_current_prices', lambda *args, **kwargs:
        ({'005930': dict(captured_at=captured.isoformat(), bars=bars)}, dict(pending_symbols=[], errors={})))
    monkeypatch.setattr(service, 'clock', lambda value=None: finished if value is None else stamp(value))
    db = service._connect(tmp_path, write=True)
    try:
        result = service._calculate(db, tmp_path, tmp_path, NOW, None, float('inf'), live=True)
    finally:
        db.close()
    assert len(result['candidates']) == 1
    assert stamp(result['generated_at']) >= stamp(result['candidates'][0]['price_fetched_at'])


def test_missing_latest_csv_session_does_not_shorten_calendar_scope(tmp_path, monkeypatch):
    rows, event, known = fixtures()
    calendar_requests = []
    monkeypatch.setattr(sources, 'load_events', lambda *args: ([event], dict(status='ready')))
    monkeypatch.setattr(prices, 'load_closes', lambda *args: ({'005930': rows[:-1]}, dict(status='ready')))

    def calendar(root, start, end, now, **kwargs):
        calendar_requests.append((start, end))
        return dict(calendar_sessions=[day for day, opened in known.items() if opened],
                    calendar_confirmed_days=known, calendar_verified=True)

    monkeypatch.setattr(prices, 'acquire_calendar', calendar)
    monkeypatch.setattr(prices, 'load_current_prices', lambda *args, **kwargs:
        ({}, dict(pending_symbols=[], errors={})))
    result = service.run_once(root=tmp_path, project_root=tmp_path, now=NOW)
    assert calendar_requests[0][1] == '2026-11-10'
    assert result['as_of_session'] == '2026-11-10'
    assert result['status'] == 'partial'
    assert result['candidates'] == []

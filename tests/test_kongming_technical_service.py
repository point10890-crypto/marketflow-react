from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json

import pytest

from app.services.mirofish.kongming_technical import service as s

NOW = datetime(2026, 11, 13, 3, tzinfo=timezone.utc)
SESSIONS = sorted([(date(2026, 11, 12)-timedelta(days=i)).isoformat() for i in range(35)
                   if (date(2026, 11, 12)-timedelta(days=i)).weekday() < 5])[-20:]


class Provider:
    def __init__(self):
        self.calendar_calls = 0
        self.history_calls = []
        self.fail = False

    def fetch_sessions(self, now):
        self.calendar_calls += 1
        return dict(sessions=list(SESSIONS), source='KIS:KOSPI:FHKUP03500100',
                    captured_at=now.isoformat(), through=s.completed_through(now))

    def fetch_history(self, symbol, sessions, now):
        self.history_calls.append(symbol)
        if self.fail:
            raise RuntimeError('private provider credential')
        return dict(name='시험종목', source='KIS:FHKST03010100:J:D:1', fetched_at=now.isoformat(),
                    bars=[dict(symbol=symbol, date=d, open=100, high=110, low=90, close=100,
                               volume=1000, traded_value=100000, source_flags={}) for d in sessions],
                    raw_bars=[{'private_test_marker': 'never public'}])


@pytest.fixture
def news(monkeypatch):
    rows = []
    monkeypatch.setattr(s.articles, 'read_view', lambda *a, **kw: dict(items=deepcopy(rows)))
    return rows


def test_get_empty_does_not_create_files(tmp_path):
    root = tmp_path/'missing'
    assert s.read_view(root, now=NOW)['items'] == []
    assert not root.exists()


def test_queue_deduplicates_and_worker_reuses_completed_symbol(tmp_path, news):
    p = Provider()
    assert s.enqueue('0162D0', tmp_path, now=NOW)['status'] == 'queued'
    assert s.enqueue('0162D0', tmp_path, now=NOW)['status'] == 'queued'
    news.extend([dict(freshness='recent', entities=[dict(symbol='0162D0', name='동원파츠')])]*2)
    s.run_once(tmp_path, now=NOW, provider=p)
    result = s.read_view(tmp_path, now=NOW)
    assert result['items'][0]['status'] == 'ready'
    assert result['items'][0]['sessions_used'] == 20
    assert p.history_calls == ['0162D0']
    assert s.enqueue('0162D0', tmp_path, now=NOW)['status'] == 'cached'
    s.run_once(tmp_path, now=NOW+timedelta(minutes=2), provider=p)
    assert p.history_calls == ['0162D0'] and p.calendar_calls == 1
    assert 'never public' not in json.dumps(result)


def test_batch_limit_and_explicit_queue_priority(tmp_path, news):
    news.extend(dict(freshness='recent', entities=[dict(symbol=f'{i:06}', name=str(i))]) for i in range(1, 9))
    s.enqueue('005930', tmp_path, now=NOW)
    p = Provider()
    s.run_once(tmp_path, now=NOW, provider=p, max_symbols=3)
    assert len(p.history_calls) == 3 and p.history_calls[0] == '005930'
    assert len(s.read_view(tmp_path, now=NOW)['items']) == 9


def test_refresh_failure_preserves_completed_profile_and_cools_down(tmp_path, news):
    p = Provider()
    s.enqueue('005930', tmp_path, now=NOW)
    s.run_once(tmp_path, now=NOW, provider=p)
    before = (tmp_path/'profiles'/'005930.json').read_bytes()
    # Force a later input window (same window is intentionally reusable).
    p.fetch_sessions = lambda now: dict(sessions=SESSIONS[1:]+['2026-11-13'],
        source='KIS:KOSPI:FHKUP03500100', captured_at=now.isoformat(), through=s.completed_through(now))
    later = NOW+timedelta(days=1)
    p.fail = True
    s.run_once(tmp_path, now=later, provider=p)
    view = s.read_view(tmp_path, now=later)
    assert view['items'][0]['status'] == 'stale'
    assert view['items'][0]['poc'] is not None
    assert (tmp_path/'profiles'/'005930.json').read_bytes() == before
    count = len(p.history_calls)
    s.enqueue('005930', tmp_path, now=later)
    s.run_once(tmp_path, now=later+timedelta(minutes=1), provider=p)
    assert len(p.history_calls) == count
    assert 'private provider' not in json.dumps(view)


@pytest.mark.parametrize('symbol', ['../x', '000000', 'abc123', '', '1234567', None])
def test_queue_rejects_invalid_symbols(tmp_path, symbol):
    with pytest.raises(ValueError):
        s.enqueue(symbol, tmp_path, now=NOW)


def test_corrupt_state_is_not_silently_reset(tmp_path):
    (tmp_path/'state.json').write_text('{broken', encoding='utf8')
    with pytest.raises(ValueError):
        s.enqueue('005930', tmp_path, now=NOW)
    assert (tmp_path/'state.json').read_text() == '{broken'


def test_calendar_failure_does_not_refetch_each_tick(tmp_path, news):
    p = Provider()
    def fail(now):
        p.calendar_calls += 1
        raise RuntimeError('private calendar')
    p.fetch_sessions = fail
    s.enqueue('005930', tmp_path, now=NOW)
    s.run_once(tmp_path, now=NOW, provider=p)
    s.run_once(tmp_path, now=NOW+timedelta(minutes=1), provider=p)
    assert p.calendar_calls == 1 and not p.history_calls
    assert s.read_view(tmp_path, now=NOW)['items'][0]['status'] == 'source_unavailable'


@pytest.mark.parametrize('status', ['insufficient_history', 'price_event_review'])
def test_no_level_result_remains_readable_after_day_change(tmp_path, news, status):
    s.enqueue('005930', tmp_path, now=NOW)
    profile = s._pending('005930', {})
    profile['status'] = status
    s.write_json_atomic(tmp_path/'profiles'/'005930.json', profile)
    s._finish(tmp_path, '005930', NOW, s.completed_through(NOW), profile=profile)
    assert s.read_view(tmp_path, now=NOW+timedelta(days=1))['items'][0]['status'] == status


def test_missing_completed_profile_is_reacquired(tmp_path, news):
    p = Provider()
    s.enqueue('005930', tmp_path, now=NOW)
    s.run_once(tmp_path, now=NOW, provider=p)
    (tmp_path/'profiles'/'005930.json').unlink()
    assert s.enqueue('005930', tmp_path, now=NOW)['status'] == 'queued'
    s.run_once(tmp_path, now=NOW+timedelta(minutes=1), provider=p)
    assert p.history_calls == ['005930', '005930']


def test_existing_auto_entry_cannot_bypass_manual_queue_cap(tmp_path, news):
    news.append(dict(freshness='recent', entities=[dict(symbol='005930', name='삼성전자')]))
    s._discover(tmp_path, None, NOW)
    for n in range(1, s.MAX_QUEUED+1):
        s.enqueue(f'{n:06}', tmp_path, now=NOW)
    with pytest.raises(ValueError, match='technical_queue_full'):
        s.enqueue('005930', tmp_path, now=NOW)


@pytest.mark.parametrize('mutation', ['premature', 'duplicate', 'invalid_date'])
def test_cached_calendar_is_revalidated(tmp_path, mutation):
    p = Provider()
    cached = p.fetch_sessions(NOW)
    if mutation == 'premature':
        cached['captured_at'] = '2026-11-12T05:00:00Z'
    elif mutation == 'duplicate':
        cached['sessions'] = [SESSIONS[0]]*20
    else:
        cached['sessions'][0] = '2026-10-99'
    s.write_json_atomic(tmp_path/'calendar.json', cached)
    fresh = s._sessions(tmp_path, p, NOW)
    assert fresh['sessions'] == SESSIONS and p.calendar_calls == 2


def test_failed_requests_release_priority_then_retry_hourly_without_manual_recovery(tmp_path, news):
    p = Provider()
    p.fail = True
    s.enqueue('005930', tmp_path, now=NOW)
    for i in range(4):
        s.run_once(tmp_path, now=NOW+timedelta(minutes=16*i), provider=p)
    assert len(p.history_calls) == 3
    assert not s._state(tmp_path)['entries']['005930']['priority']
    # Provider recovery is detected automatically after the longer cooldown.
    p.fail = False
    s.run_once(tmp_path, now=NOW+timedelta(hours=2), provider=p)
    assert len(p.history_calls) == 4
    assert s.read_view(tmp_path, now=NOW+timedelta(hours=2))['items'][0]['status'] == 'ready'


def test_expired_automatic_candidates_stop_refreshing(tmp_path, news):
    p = Provider()
    news.append(dict(freshness='recent', entities=[dict(symbol='005930', name='삼성전자')]))
    s.run_once(tmp_path, now=NOW, provider=p)
    news.clear()
    p.fetch_sessions = lambda now: pytest.fail('inactive candidates must not query KIS')
    s.run_once(tmp_path, now=NOW+timedelta(days=4), provider=p)


def test_expired_queue_entry_can_be_replaced_without_deleting_history(tmp_path, news, monkeypatch):
    monkeypatch.setattr(s, 'MAX_ENTRIES', 1)
    s.enqueue('005930', tmp_path, now=NOW)
    s.run_once(tmp_path, now=NOW, provider=Provider())
    history = list((tmp_path/'history').rglob('*.json'))
    assert history
    s.enqueue('000660', tmp_path, now=NOW+timedelta(days=8))
    assert list(s._state(tmp_path)['entries']) == ['000660']
    assert all(path.is_file() for path in history)

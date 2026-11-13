"""Decision reads must verify stored technical evidence without acquiring it."""
from datetime import date, datetime, timedelta, timezone
import json

import pytest

from app.services.mirofish.kongming_technical import service


NOW = datetime(2026, 11, 13, 3, tzinfo=timezone.utc)
SESSIONS = sorted(
    (date(2026, 11, 12) - timedelta(days=i)).isoformat()
    for i in range(35)
    if (date(2026, 11, 12) - timedelta(days=i)).weekday() < 5
)[-20:]
SYMBOL = '005930'


class Provider:
    def __init__(self, mode='ready', sessions=None):
        self.mode = mode
        self.sessions = sessions or SESSIONS

    def fetch_sessions(self, now):
        return dict(sessions=list(self.sessions), source='KIS:KOSPI:FHKUP03500100',
                    captured_at=now.isoformat(), through=service.completed_through(now))

    def fetch_history(self, symbol, sessions, now):
        if self.mode == 'fail':
            raise RuntimeError('secret credential at C:/private/token.json')
        bars = [dict(symbol=symbol, date=day, open=100, high=112, low=88,
                     close=100, volume=1200, traded_value=123456, source_flags={})
                for day in sessions]
        if self.mode == 'insufficient_history':
            bars.pop(0)
        elif self.mode == 'price_event_review':
            bars[-1]['source_flags'] = {'prtt_rate': '50'}
        return dict(name='삼성전자', source='KIS:FHKST03010100:J:D:1',
                    fetched_at=now.isoformat(), bars=bars,
                    raw_bars=[{'private_marker': 'secret provider body'}])


@pytest.fixture
def adapter():
    from app.services.mirofish import decision_technical
    return decision_technical


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setattr(service.articles, 'read_view', lambda *a, **kw: dict(items=[]))

    def create(mode='ready', now=NOW, sessions=None, symbol=SYMBOL):
        service.enqueue(symbol, tmp_path, now=now)
        service.run_once(tmp_path, now=now, provider=Provider(mode, sessions))
        return tmp_path

    return create


def _read(path):
    return json.loads(path.read_text(encoding='utf8'))


def _write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf8')


def _receipt(root):
    return next((root / 'history' / SYMBOL).glob('*.json'))


def test_ready_reconstructs_conserved_evidence_and_reports_reference_distances(adapter, prepared):
    root = prepared()
    result = adapter.read_analysis(SYMBOL, root=root, now=NOW)
    assert set(result) == {'schema_version', 'agent', 'symbol', 'market', 'status',
                           'profile', 'summary', 'observations', 'independent_evidence'}
    assert result['status'] == 'ready'
    assert result['symbol'] == SYMBOL and result['market'] == 'KR'
    assert result['independent_evidence'] is False
    profile = result['profile']
    assert profile['sessions_used'] == 20
    assert profile['as_of'] == '2026-11-12' and profile['reference_price'] == 100
    assert sum(zone['volume'] for zone in profile['bins']) == pytest.approx(24000)
    assert sum(zone['traded_value'] for zone in profile['bins']) == pytest.approx(2469120)
    assert sum(zone['volume_pct'] for zone in profile['bins']) == pytest.approx(100)
    assert profile['source'] == 'KIS:FHKST03010100:J:D:1'
    assert profile['calendar_source'] == 'KIS:KOSPI:FHKUP03500100'
    observations = '\n'.join(result['observations'])
    for expected in ('2026-11-12', '종가', '100', '지지', '저항', '거래량', '거래대금', '%', '거리'):
        assert expected in observations
    assert '-12.00%' in observations and '-11.00%' in observations
    assert '+1.00%' in observations and '+2.00%' in observations
    context = adapter.format_context(result)
    assert 0 < len(context) <= 2000
    assert 'KIS' in context and '독립' in context and '매수' in context
    assert profile['fingerprint'] in context and profile['as_of'] in context
    assert 'secret' not in json.dumps(result) and 'raw_bars' not in json.dumps(result)


@pytest.mark.parametrize('symbol, expected', [
    ('005930', True), ('0162D0', True), ('000000', False), ('ABCDEF', False),
    ('A12345', False), ('TSLA', False), ('BRK.B', False), ('0162d0', False),
    (' 005930', False), ('../x', False), ('', False), (None, False), (5930, False),
])
def test_domestic_identity_is_strict_and_digit_leading(adapter, symbol, expected):
    assert adapter.is_domestic_symbol(symbol) is expected


def test_foreign_symbols_never_touch_store(adapter, monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        pytest.fail('unsupported market attempted a technical store read')
    monkeypatch.setattr(service, 'read_view', forbidden)
    for symbol in ['TSLA', 'ABCDEF', 'A12345']:
        result = adapter.read_analysis(symbol, root=tmp_path / 'missing', now=NOW)
        assert result['status'] == 'unsupported_market'
        assert result['market'] == 'unsupported' and result['profile'] is None
        assert adapter.format_context(result) == ''
    assert not (tmp_path / 'missing').exists()


def test_missing_and_pending_do_not_create_or_acquire(adapter, tmp_path, monkeypatch):
    root = tmp_path / 'missing'
    result = adapter.read_analysis(SYMBOL, root=root, now=NOW)
    assert result['status'] == 'not_requested' and result['profile'] is None
    assert not root.exists()
    service.enqueue(SYMBOL, root, now=NOW)
    before = {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}
    monkeypatch.setattr(service, 'enqueue', lambda *a, **kw: pytest.fail('read enqueued work'))
    monkeypatch.setattr(service, 'run_once', lambda *a, **kw: pytest.fail('read ran worker'))
    result = adapter.read_analysis(SYMBOL, root=root, now=NOW)
    assert result['status'] == 'pending' and result['profile'] is None
    assert adapter.format_context(result) == ''
    after = {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}
    assert after == before


def test_ready_read_is_selected_symbol_only_and_does_not_write(adapter, prepared, monkeypatch):
    root = prepared()
    service.enqueue('000660', root, now=NOW)
    (root / 'profiles' / '000660.json').write_text('invalid unrelated profile', encoding='utf8')
    before = {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}
    original = service.read_view

    def selected_only(*args, **kwargs):
        assert kwargs['symbol'] == SYMBOL
        return original(*args, **kwargs)

    monkeypatch.setattr(service, 'read_view', selected_only)
    assert adapter.read_analysis(SYMBOL, root=root, now=NOW)['status'] == 'ready'
    after = {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}
    assert after == before


@pytest.mark.parametrize('field, value', [
    ('symbol', '000660'), ('source', 'invented'), ('calendar_source', 'invented'),
    ('method', 'holdings'), ('price_basis', 'adjusted'), ('sessions_used', 19),
    ('sessions_required', 19), ('reference_price', 999), ('total_volume', 999),
    ('as_of', '2026-11-13'), ('fetched_at', '2026-11-14T03:00:00Z'),
    ('fingerprint', '../../private'), ('fingerprint', 'a' * 64),
])
def test_bad_saved_profile_is_never_accepted(adapter, prepared, field, value):
    root = prepared()
    path = root / 'profiles' / f'{SYMBOL}.json'
    profile = _read(path)
    profile[field] = value
    _write(path, profile)
    result = adapter.read_analysis(SYMBOL, root=root, now=NOW)
    assert result['status'] == 'source_unavailable' and result['profile'] is None
    assert not result['observations']


@pytest.mark.parametrize('mutation', ['zone', 'nan', 'missing_bar', 'identity', 'source', 'calendar', 'clock', 'future_clock', 'future_calendar'])
def test_receipt_tampering_fails_closed(adapter, prepared, mutation):
    root = prepared()
    path = _receipt(root)
    receipt = _read(path)
    if mutation == 'zone':
        receipt['profile']['support']['volume'] += 1
    elif mutation == 'nan':
        receipt['profile']['bins'][0]['volume'] = float('nan')
    elif mutation == 'missing_bar':
        receipt['input']['bars'].pop()
    elif mutation == 'identity':
        receipt['input']['bars'][0]['symbol'] = '000660'
    elif mutation == 'source':
        receipt['input']['source'] = 'fabricated'
    elif mutation == 'calendar':
        receipt['calendar']['sessions'].pop()
    elif mutation == 'clock':
        receipt['calendar']['captured_at'] = '2026-11-12T05:00:00Z'
    elif mutation == 'future_clock':
        receipt['input']['fetched_at'] = '2026-11-14T03:00:00Z'
    else:
        receipt['calendar']['captured_at'] = '2026-11-14T03:00:00Z'
    _write(path, receipt)
    result = adapter.read_analysis(SYMBOL, root=root, now=NOW)
    assert result['status'] == 'source_unavailable' and result['profile'] is None
    assert adapter.format_context(result) == ''


@pytest.mark.parametrize('mode', ['insufficient_history', 'price_event_review'])
def test_no_level_results_cannot_supply_active_observations(adapter, prepared, mode):
    root = prepared(mode)
    result = adapter.read_analysis(SYMBOL, root=root, now=NOW)
    assert result['status'] == mode
    assert result['profile']['bins'] == []
    assert result['profile']['support'] is None and result['profile']['resistance'] is None
    assert not result['observations'] and adapter.format_context(result) == ''


def test_buffer_cutoff_changes_ready_to_stale_without_hiding_history(adapter, prepared):
    root = prepared()
    before = adapter.read_analysis(SYMBOL, root=root, now='2026-11-13T11:29:59Z')
    after = adapter.read_analysis(SYMBOL, root=root, now='2026-11-13T11:30:00Z')
    assert before['status'] == 'ready'
    assert after['status'] == 'stale' and after['profile']['status'] == 'stale'
    assert after['profile']['fingerprint'] == before['profile']['fingerprint']
    assert after['profile']['reference_price'] == 100
    assert not after['observations'] and adapter.format_context(after) == ''


def test_weekend_uses_service_freshness_without_inventing_sessions(adapter, prepared):
    friday_night = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
    root = prepared(now=friday_night, sessions=SESSIONS[1:] + ['2026-11-13'])
    assert adapter.read_analysis(SYMBOL, root=root, now='2026-11-14T03:00:00Z')['status'] == 'ready'
    result = adapter.read_analysis(SYMBOL, root=root, now='2026-11-15T03:00:00Z')
    assert result['status'] == 'stale'
    assert result['profile']['as_of'] == '2026-11-13'
    assert not result['observations']


def test_acquisition_failure_is_bounded_and_does_not_expose_reason(adapter, prepared):
    root = prepared('fail')
    result = adapter.read_analysis(SYMBOL, root=root, now=NOW)
    assert result['status'] == 'source_unavailable' and result['profile'] is None
    serialized = json.dumps(result, ensure_ascii=False)
    assert 'secret' not in serialized and 'C:/' not in serialized and len(serialized) < 2000


@pytest.mark.parametrize('failure', ['missing_receipt', 'oversized_receipt', 'corrupt_state', 'exception'])
def test_read_failures_return_bounded_unavailable(adapter, prepared, monkeypatch, failure):
    root = prepared()
    if failure == 'missing_receipt':
        _receipt(root).unlink()
    elif failure == 'oversized_receipt':
        _receipt(root).write_text(' ' * 8_000_001, encoding='utf8')
    elif failure == 'corrupt_state':
        (root / 'state.json').write_text('{broken', encoding='utf8')
    else:
        def fail(*args, **kwargs):
            raise RuntimeError('C:/private/token.json secret token')
        monkeypatch.setattr(service, 'read_view', fail)
    result = adapter.read_analysis(SYMBOL, root=root, now=NOW)
    assert result['status'] == 'source_unavailable'
    assert result['profile'] is None and result['observations'] == []
    assert 'secret' not in json.dumps(result) and 'C:/' not in json.dumps(result)


def test_context_does_not_copy_untrusted_observation_text(adapter, prepared):
    root = prepared()
    result = adapter.read_analysis(SYMBOL, root=root, now=NOW)
    result['observations'] = ['private text' * 1000]
    context = adapter.format_context(result)
    assert 'private text' not in context and len(context) <= 2000


@pytest.mark.parametrize('mutation', ['missing_field', 'nan_zone', 'finite_zone', 'receipt_mismatch'])
def test_saved_levels_must_match_the_replayed_receipt(adapter, prepared, mutation):
    root = prepared()
    path = root / 'profiles' / f'{SYMBOL}.json'
    profile = _read(path)
    if mutation == 'missing_field':
        del profile['total_volume']
    elif mutation == 'nan_zone':
        profile['support']['low'] = float('nan')
    elif mutation == 'finite_zone':
        profile['support']['traded_value'] += 100
    else:
        # Neither record can legitimize values if both are altered together.
        profile['reference_price'] = 101
        receipt = _read(_receipt(root))
        receipt['profile']['reference_price'] = 101
        _write(_receipt(root), receipt)
    _write(path, profile)
    result = adapter.read_analysis(SYMBOL, root=root, now=NOW)
    assert result['status'] == 'source_unavailable' and result['profile'] is None


def test_extra_private_fields_never_cross_the_public_projection(adapter, prepared):
    root = prepared()
    for path in [root / 'profiles' / f'{SYMBOL}.json', _receipt(root)]:
        value = _read(path)
        target = value.get('profile', value)
        target['private_secret'] = 'secret local receipt path'
        _write(path, value)
    result = adapter.read_analysis(SYMBOL, root=root, now=NOW)
    assert result['status'] == 'ready'
    assert 'private_secret' not in json.dumps(result) and 'secret local' not in json.dumps(result)


def test_failed_refresh_keeps_only_validated_past_profile(adapter, prepared):
    root = prepared()
    service._finish(root, SYMBOL, NOW, service.completed_through(NOW),
                    error='private secret provider failure')
    result = adapter.read_analysis(SYMBOL, root=root, now=NOW)
    assert result['status'] == 'stale' and result['profile']['reference_price'] == 100
    assert result['observations'] == [] and adapter.format_context(result) == ''
    assert 'private secret' not in json.dumps(result)


def test_future_fetched_evidence_is_not_visible_before_capture(adapter, prepared):
    root = prepared()
    result = adapter.read_analysis(SYMBOL, root=root, now=NOW - timedelta(seconds=1))
    assert result['status'] == 'source_unavailable' and result['profile'] is None


def test_invalid_hash_is_rejected_before_history_path_access(adapter, prepared, monkeypatch):
    root = prepared()
    path = root / 'profiles' / f'{SYMBOL}.json'
    profile = _read(path)
    profile['fingerprint'] = '../../private'
    _write(path, profile)
    original = service._read
    history_reads = []

    def bounded_read(path, *args, **kwargs):
        if 'history' in path.parts:
            history_reads.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(service, '_read', bounded_read)
    assert adapter.read_analysis(SYMBOL, root=root, now=NOW)['status'] == 'source_unavailable'
    assert history_reads == []


def test_repeated_insufficient_history_reuses_receipt_with_new_capture_clock(adapter, prepared):
    root = prepared('insufficient_history')
    receipt_path = _receipt(root)
    immutable_receipt = receipt_path.read_bytes()
    later = NOW + timedelta(days=1)
    result = service.run_once(root, now=later, provider=Provider('insufficient_history'))
    assert result['processed'] == 1
    assert receipt_path.read_bytes() == immutable_receipt
    latest = _read(root / 'profiles' / f'{SYMBOL}.json')
    assert latest['fetched_at'] == '2026-11-14T03:00:00Z'
    assert latest['fingerprint'] == _read(receipt_path)['profile']['fingerprint']

    analysis = adapter.read_analysis(SYMBOL, root=root, now=later)
    assert analysis['status'] == 'insufficient_history'
    assert analysis['profile']['status'] == analysis['status']
    assert analysis['profile']['fetched_at'] == '2026-11-14T03:00:00Z'
    assert analysis['profile']['sessions_used'] == 19
    assert analysis['profile']['bins'] == []
    assert analysis['observations'] == [] and adapter.format_context(analysis) == ''


def test_missing_ready_profile_can_rebuild_from_same_evidence_at_later_clock(adapter, prepared):
    root = prepared()
    receipt_path = _receipt(root)
    immutable_receipt = receipt_path.read_bytes()
    (root / 'profiles' / f'{SYMBOL}.json').unlink()
    later = NOW + timedelta(minutes=5)
    result = service.run_once(root, now=later, provider=Provider())
    assert result['processed'] == 1
    assert receipt_path.read_bytes() == immutable_receipt
    assert len(list((root / 'history' / SYMBOL).glob('*.json'))) == 1

    analysis = adapter.read_analysis(SYMBOL, root=root, now=later)
    assert analysis['status'] == 'ready'
    assert analysis['profile']['status'] == analysis['status']
    assert analysis['profile']['fetched_at'] == '2026-11-13T03:05:00Z'
    assert analysis['profile']['reference_price'] == 100
    assert analysis['profile']['total_volume'] == 24000
    assert analysis['profile']['fingerprint'] == _read(receipt_path)['profile']['fingerprint']
    assert analysis['observations'] and adapter.format_context(analysis)
    stale = adapter.read_analysis(SYMBOL, root=root, now='2026-11-13T11:30:00Z')
    assert stale['status'] == stale['profile']['status'] == 'stale'
    assert stale['profile']['fetched_at'] == '2026-11-13T03:05:00Z'
    assert stale['observations'] == [] and adapter.format_context(stale) == ''


def test_latest_capture_clock_cannot_predate_immutable_receipt(adapter, prepared):
    root = prepared()
    path = root / 'profiles' / f'{SYMBOL}.json'
    profile = _read(path)
    profile['fetched_at'] = '2026-11-13T02:59:59Z'
    _write(path, profile)
    analysis = adapter.read_analysis(SYMBOL, root=root, now=NOW)
    assert analysis['status'] == 'source_unavailable' and analysis['profile'] is None

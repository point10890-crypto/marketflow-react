"""Causal saved monitoring references, separate from paper execution outcomes."""
from copy import deepcopy
import importlib
import importlib.util
import json
from datetime import datetime

import pytest

from app.services.mirofish.alpha_lab import store
from tests.test_alpha_lab_opportunities import status as opportunity_status

ORIGIN = '2026-10-04T05:00:00Z'
REGISTER = '2026-10-04T06:00:00Z'
OPEN = '2026-10-06T00:05:00Z'


def monitor():
    name = 'app.services.mirofish.alpha_lab.monitor'
    assert importlib.util.find_spec(name) is not None, 'saved cadence monitor is not implemented'
    return importlib.import_module(name)


def report():
    value = opportunity_status()['report']
    value['input_fingerprint'] = 'a'*64
    value['provenance']['price_basis'] = 'provider_reported_unverified'
    value['opportunity_scan']['audit_hash'] = 'b'*64
    value['buy_candidates'][0]['plan']['atr'] = 2.
    value['opportunity_scan']['forward'] = dict(decisions=1, matured=0, win_rate=None,
        mean_net_return=None, counts=dict(pending=1, open=0, unfilled=0, missing_session=0,
                                       source_revision=0, closed=0), excluded_revised_closed=0,
        basis='frozen_watchlist_next_open_outcomes_not_account_pnl')
    return value


class Provider:
    """Synthetic exchange dates: Oct5 deliberately closed, Oct6 first open."""
    def __init__(self, *, calendar=None, quote=None, failure=None):
        self.calendar = calendar
        self.quote = quote
        self.failure = failure
        self.calendar_calls = 0
        self.quote_calls = 0

    def fetch_calendar(self, base_date, now):
        self.calendar_calls += 1
        if self.failure == 'calendar':
            raise RuntimeError('must not expose request credentials')
        return deepcopy(self.calendar) if self.calendar is not None else dict(
            source='KIS:CTCA0903R', captured_at=now,
            days=[dict(date=f'2026-10-{day:02d}', is_open=day in (6, 7, 8, 9, 12))
                  for day in range(4, 13)])

    def fetch_quote(self, symbol, now):
        self.quote_calls += 1
        if self.failure == 'quote':
            raise RuntimeError('must not expose request credentials')
        return deepcopy(self.quote) if self.quote is not None else dict(symbol=symbol,
            price=101., opening_price=101., quote_at='2026-10-06T00:04:30Z',
            fetched_at=now, source='KIS:J:FHKST03010200+FHKST01010100')


def seed(root):
    value = report()
    monitor().register_report(root, value, now=REGISTER)
    store.publish(root, value, now=REGISTER, held=True)
    return value


def projected(root, now=OPEN, state='held', value=None):
    return monitor().attach_operations(dict(state=state, report=value or report()), root, now=now)


def test_next_official_session_skips_weekend_and_holiday(tmp_path):
    seed(tmp_path)
    result = monitor().run_monitor(tmp_path, Provider(), now=REGISTER)
    assert result['cadence']['market_state'] == 'closed'
    view = projected(tmp_path, REGISTER)
    window = view['report']['proposal_window']
    assert window['origin_at'] == ORIGIN
    assert window['entry_session'] == '2026-10-06'
    assert window['valid_until'] == '2026-10-06T06:30:00Z'
    assert window['opportunity_audit_hash'] == 'b'*64


def test_same_source_rescan_cannot_renew_origin_or_entry_window(tmp_path):
    seed(tmp_path)
    monitor().run_monitor(tmp_path, Provider(), now=REGISTER)
    later = report(); later['decision_at'] = '2026-10-06T01:00:00Z'
    monitor().register_report(tmp_path, later, now=later['decision_at'])
    monitor().calendar_check(tmp_path, Provider(), now=later['decision_at'])
    window = projected(tmp_path, now=later['decision_at'], value=later)['report']['proposal_window']
    assert window['origin_at'] == ORIGIN
    assert window['valid_until'] == '2026-10-06T06:30:00Z'


def test_registered_identity_without_calendar_has_null_window_not_renewed_24h(tmp_path):
    seed(tmp_path)
    window = projected(tmp_path, REGISTER)['report']['proposal_window']
    assert window['policy_version'] == 'next-session-proposal-v1'
    assert window['origin_at'] == ORIGIN
    assert window['entry_session'] is None and window['valid_until'] is None


def test_closed_calendar_day_makes_no_quote_requests(tmp_path):
    seed(tmp_path); provider = Provider(failure='quote')
    result = monitor().run_monitor(tmp_path, provider, now=REGISTER)
    assert provider.quote_calls == 0
    assert result['monitoring']['quotes'][0]['price'] is None


def test_accepted_open_reprices_frozen_atr_without_fill_or_authority(tmp_path):
    value = seed(tmp_path)
    result = monitor().run_monitor(tmp_path, Provider(), now=OPEN)
    quote = result['monitoring']['quotes'][0]
    assert quote['entry_state'] == 'within_band'
    assert quote['opening_price'] == 101.
    assert quote['adjusted_plan'] == dict(entry_price=101., stop_price=97., target_price=109.,
        loss_fraction=4/101, proposed_weight=.05)
    assert quote['stop_price'] == 96. and quote['target_price'] == 108.
    assert value['approval']['approved_exposure'] == 0. and value['approval']['live_orders'] is False
    assert 'fill_price' not in quote and 'actual_position' not in result['monitoring']


@pytest.mark.parametrize('opening,state', [(103., 'above_ceiling'), (95., 'below_stop')])
def test_open_gap_skip_is_pinned_even_when_later_price_enters_band(tmp_path, opening, state):
    seed(tmp_path)
    quote = dict(symbol='196170', price=101., opening_price=opening,
        quote_at='2026-10-06T00:04:30Z', fetched_at=OPEN,
        source='KIS:J:FHKST03010200+FHKST01010100')
    monitor().run_monitor(tmp_path, Provider(quote=quote), now=OPEN)
    quote.update(quote_at='2026-10-06T00:09:30Z', fetched_at='2026-10-06T00:10:00Z', price=100.)
    result = monitor().run_monitor(tmp_path, Provider(quote=quote), now=quote['fetched_at'])
    row = result['monitoring']['quotes'][0]
    assert row['entry_state'] == state
    assert row.get('adjusted_plan') is None


@pytest.mark.parametrize('change,reason', [
    (dict(symbol='005930'), 'quote_symbol_mismatch'),
    (dict(quote_at='2026-10-05T00:04:30Z'), 'quote_stale'),
    (dict(quote_at='2026-10-06T00:05:01Z'), 'quote_future'),
    (dict(price=float('nan')), 'quote_invalid'),
    (dict(opening_price=True), 'quote_invalid'),
    (dict(source='unbound_provider'), 'quote_invalid'),
])
def test_invalid_provider_quote_never_becomes_price_guidance(tmp_path, change, reason):
    seed(tmp_path)
    quote = Provider().fetch_quote('196170', OPEN); quote.update(change)
    result = monitor().run_monitor(tmp_path, Provider(quote=quote), now=OPEN)
    row = result['monitoring']['quotes'][0]
    assert row['price'] is None and row.get('adjusted_plan') is None
    assert reason in row['reasons']
    json.dumps(result, allow_nan=False)


def test_late_quote_failure_replaces_prior_success_and_masks_guidance(tmp_path):
    seed(tmp_path)
    monitor().run_monitor(tmp_path, Provider(), now=OPEN)
    result = monitor().run_monitor(tmp_path, Provider(failure='quote'), now='2026-10-06T00:10:00Z')
    assert result['monitoring']['status'] == 'failed'
    assert result['monitoring']['quotes'][0]['price'] is None
    assert 'credentials' not in json.dumps(result)
    assert projected(tmp_path, '2026-10-06T00:10:00Z')['operations']['monitoring']['quotes'][0]['price'] is None


def test_saved_quote_expires_at_ttl_boundary_without_writes_or_network(tmp_path):
    seed(tmp_path)
    monitor().run_monitor(tmp_path, Provider(), now=OPEN)
    before = {str(p): p.read_bytes() for p in tmp_path.rglob('*.json')}
    result = projected(tmp_path, '2026-10-06T00:11:30Z')
    assert result['operations']['monitoring']['quotes'][0]['entry_state'] == 'stale'
    assert result['operations']['monitoring']['quotes'][0]['price'] is None
    assert before == {str(p): p.read_bytes() for p in tmp_path.rglob('*.json')}


@pytest.mark.parametrize('state', ['running', 'failed', 'missing'])
def test_research_unavailable_hides_prior_monitor_guidance(tmp_path, state):
    seed(tmp_path)
    monitor().run_monitor(tmp_path, Provider(), now=OPEN)
    result = projected(tmp_path, state=state)
    assert result['operations']['monitoring']['quotes'][0]['price'] is None
    assert result['report']['proposal_window']['entry_session'] is None


def test_changed_identity_cannot_attach_old_current_quotes(tmp_path):
    seed(tmp_path)
    monitor().run_monitor(tmp_path, Provider(), now=OPEN)
    changed = report(); changed['input_fingerprint'] = 'c'*64
    view = projected(tmp_path, value=changed)
    assert view['operations']['monitoring']['quotes'][0]['price'] is None
    assert 'identity_mismatch' in view['operations']['monitoring']['reasons']


@pytest.mark.parametrize('mutation', ['source', 'gap', 'bool', 'future'])
def test_invalid_calendar_cannot_certify_entry_or_today_open(tmp_path, mutation):
    seed(tmp_path)
    calendar = Provider().fetch_calendar('2026-10-04', OPEN)
    if mutation == 'source': calendar['source'] = 'weekday_guess'
    if mutation == 'gap': calendar['days'] = [r for r in calendar['days'] if r['date'] != '2026-10-05']
    if mutation == 'bool': calendar['days'][0]['is_open'] = 'N'
    if mutation == 'future': calendar['captured_at'] = '2026-10-06T00:05:01Z'
    result = monitor().run_monitor(tmp_path, Provider(calendar=calendar), now=OPEN)
    assert result['cadence']['market_state'] == 'unknown'
    assert projected(tmp_path)['report']['proposal_window']['entry_session'] is None


def test_calendar_is_fetched_once_per_day_and_priming_makes_no_quotes(tmp_path):
    seed(tmp_path); provider = Provider()
    result = monitor().run_monitor(tmp_path, provider, now='2026-10-06T23:55:00+09:00')
    assert result['monitoring']['quotes'][0]['price'] is None
    monitor().calendar_check(tmp_path, provider, now='2026-10-06T23:56:00+09:00')
    assert provider.calendar_calls == 1 and provider.quote_calls == 0


def test_preopen_calendar_prime_is_held_until_session_open(tmp_path):
    seed(tmp_path); provider = Provider()
    result = monitor().run_monitor(tmp_path, provider, now='2026-10-06T08:55:00+09:00')
    assert result['monitoring']['quotes'][0]['entry_state'] == 'wait_open'
    assert provider.quote_calls == 0


def test_saved_corruption_is_safe_and_registration_integrity_fails_closed(tmp_path):
    seed(tmp_path)
    path = tmp_path/'monitor'/'registry.json'
    raw = json.loads(path.read_text(encoding='utf-8')); raw['sha256'] = '0'*64
    path.write_text(json.dumps(raw), encoding='utf-8')
    view = projected(tmp_path)
    assert view['operations']['monitoring']['status'] == 'failed'
    assert 'monitor_corrupt' in view['operations']['monitoring']['reasons']
    with pytest.raises(ValueError, match='monitor_integrity'):
        monitor().register_report(tmp_path, report(), now=REGISTER)


def test_monitor_projection_preserves_paper_denominator_and_both_journals(tmp_path):
    value = seed(tmp_path); original = deepcopy(value)
    for root in (tmp_path, tmp_path/'opportunities'):
        root.mkdir(exist_ok=True); (root/'forward.json').write_text('existing sealed journal')
    monitor().run_monitor(tmp_path, Provider(), now=OPEN)
    source = dict(state='held', report=value)
    result = monitor().attach_operations(source, tmp_path, now=OPEN)
    assert source['report'] == original
    assert result['operations']['paper']['matured'] == 0
    assert result['operations']['paper']['win_rate'] is None
    assert result['operations']['paper']['entry_guard_applied'] is False
    for root in (tmp_path, tmp_path/'opportunities'):
        assert (root/'forward.json').read_text() == 'existing sealed journal'


def test_sparse_legacy_report_is_optional_and_never_requires_a_monitor_registry(tmp_path):
    assert monitor().register_report(tmp_path, dict(schema_version=1, mode='research'), now=REGISTER) is None
    result = monitor().attach_operations(dict(state='held', report=None), tmp_path, now=REGISTER)
    assert result['operations']['monitoring']['status'] == 'held'
    assert result['operations']['paper']['excluded_revised_closed'] == 0
    assert not list(tmp_path.rglob('*.json'))


def test_live_provider_uses_post_request_clock_not_request_start(tmp_path, monkeypatch):
    seed(tmp_path)
    clocks = iter([OPEN, '2026-10-06T00:05:03Z', '2026-10-06T00:05:04Z', '2026-10-06T00:05:06Z'])
    original = monitor()._now
    monkeypatch.setattr(monitor(), '_now', lambda value: original(next(clocks)) if value is None else original(value))
    class Delayed(Provider):
        def fetch_calendar(self, base_date, now):
            assert now is None
            return super().fetch_calendar(base_date, '2026-10-06T00:05:02Z')
        def fetch_quote(self, symbol, now):
            assert now is None
            result = super().fetch_quote(symbol, '2026-10-06T00:05:05Z')
            result['quote_at'] = '2026-10-06T00:05:00Z'
            return result
    result = monitor().run_monitor(tmp_path, Delayed())
    assert result['monitoring']['status'] == 'ready'
    assert result['monitoring']['quotes'][0]['fetched_at'] == '2026-10-06T00:05:05Z'
    assert result['generated_at'] == '2026-10-06T00:05:06Z'


def test_source_capture_change_cannot_reuse_the_same_fingerprint_window(tmp_path):
    seed(tmp_path)
    monitor().run_monitor(tmp_path, Provider(), now=OPEN)
    changed = report(); changed['provenance']['captured_at'] = '2026-10-04T04:30:00Z'
    result = projected(tmp_path, value=changed)
    assert result['operations']['monitoring']['quotes'][0]['price'] is None
    assert result['report']['proposal_window']['entry_session'] is None


def test_report_replacement_during_quote_request_never_publishes_or_accepts_old_reference(tmp_path):
    seed(tmp_path)
    class Racing(Provider):
        def fetch_quote(self, symbol, now):
            store.set_running(tmp_path, now=OPEN)
            return super().fetch_quote(symbol, now)
    result = monitor().run_monitor(tmp_path, Racing(), now=OPEN)
    assert result['monitoring']['quotes'][0]['price'] is None
    entries = tmp_path/'monitor'/'entries.json'
    assert not entries.exists() or json.loads(entries.read_text(encoding='utf-8'))['data'] == {}


def test_later_session_preserves_accepted_opening_and_does_not_renew_proposal(tmp_path):
    seed(tmp_path)
    monitor().run_monitor(tmp_path, Provider(), now=OPEN)
    quote = dict(symbol='196170', price=104., opening_price=105.,
        quote_at='2026-10-07T00:04:30Z', fetched_at='2026-10-07T00:05:00Z',
        source='KIS:J:FHKST03010200+FHKST01010100')
    result = monitor().run_monitor(tmp_path, Provider(quote=quote), now=quote['fetched_at'])
    row = result['monitoring']['quotes'][0]
    assert row['price'] == 104. and row['opening_price'] == 101.
    assert row['adjusted_plan']['entry_price'] == 101.
    assert projected(tmp_path, quote['fetched_at'])['report']['proposal_window']['valid_until'] == '2026-10-06T06:30:00Z'


@pytest.mark.parametrize('now,state,is_open,next_monitor', [
    ('2026-10-06T08:55:00+09:00', 'closed', True, '2026-10-06T00:00:00Z'),
    ('2026-10-06T09:02:00+09:00', 'open', True, '2026-10-06T00:05:00Z'),
    ('2026-10-06T09:05:00+09:00', 'open', True, '2026-10-06T00:10:00Z'),
    ('2026-10-06T15:28:00+09:00', 'open', True, '2026-10-06T06:30:00Z'),
    ('2026-10-06T15:30:00+09:00', 'closed', True, '2026-10-07T00:00:00Z'),
    ('2026-10-06T18:00:00+09:00', 'closed', True, '2026-10-07T00:00:00Z'),
])
def test_calendar_day_and_live_session_clock_are_distinct(tmp_path, now, state, is_open, next_monitor):
    seed(tmp_path); provider = Provider()
    calendar = monitor().calendar_check(tmp_path, provider, now=now)
    result = projected(tmp_path, now)
    assert calendar['market_state'] == state and calendar['is_open'] is is_open
    assert result['operations']['cadence']['next_monitor_at'] == next_monitor


def test_calendar_revision_cannot_move_a_previously_certified_entry_window(tmp_path):
    seed(tmp_path)
    monitor().run_monitor(tmp_path, Provider(), now=REGISTER)
    revised = Provider().fetch_calendar('2026-10-04', OPEN)
    next(row for row in revised['days'] if row['date'] == '2026-10-05')['is_open'] = True
    result = monitor().run_monitor(tmp_path, Provider(calendar=revised), now=OPEN)
    assert result['monitoring']['quotes'][0]['price'] is None
    view = projected(tmp_path)
    assert view['report']['proposal_window']['entry_session'] is None
    assert 'calendar_revision' in view['operations']['monitoring']['reasons']


def test_request_crossing_close_cannot_commit_a_new_opening_reference(tmp_path, monkeypatch):
    seed(tmp_path)
    monitor().calendar_check(tmp_path, Provider(), now='2026-10-06T08:55:00+09:00')
    clocks = iter(['2026-10-06T06:29:58Z', '2026-10-06T06:29:59Z', '2026-10-06T06:30:05Z'])
    original = monitor()._now
    monkeypatch.setattr(monitor(), '_now', lambda value: original(next(clocks)) if value is None else original(value))
    class Closing(Provider):
        def fetch_quote(self, symbol, now):
            return dict(symbol=symbol, price=101., opening_price=101.,
                quote_at='2026-10-06T06:29:59Z', fetched_at='2026-10-06T06:30:04Z',
                source='KIS:J:FHKST03010200+FHKST01010100')
    result = monitor().run_monitor(tmp_path, Closing())
    assert result['monitoring']['quotes'][0]['price'] is None
    entries = tmp_path/'monitor'/'entries.json'
    assert not entries.exists() or json.loads(entries.read_text(encoding='utf-8'))['data'] == {}


def test_failed_calendar_retries_after_15_minutes_then_success_caches_for_day(tmp_path):
    seed(tmp_path); provider = Provider(failure='calendar')
    assert monitor().calendar_check(tmp_path, provider, now='2026-10-06T08:55:00+09:00')['is_open'] is None
    provider.failure = None
    assert monitor().calendar_check(tmp_path, provider, now='2026-10-06T09:09:59+09:00')['is_open'] is None
    assert provider.calendar_calls == 1
    assert monitor().calendar_check(tmp_path, provider, now='2026-10-06T09:10:00+09:00')['is_open'] is True
    assert monitor().calendar_check(tmp_path, provider, now='2026-10-06T18:45:00+09:00')['is_open'] is True
    assert provider.calendar_calls == 2


def test_failed_calendar_is_bounded_to_three_attempts_per_kst_day(tmp_path):
    seed(tmp_path); provider = Provider(failure='calendar')
    for clock in ('08:55:00', '09:10:00', '09:25:00', '09:40:00', '18:45:00'):
        assert monitor().calendar_check(tmp_path, provider, now=f'2026-10-06T{clock}+09:00')['is_open'] is None
    assert provider.calendar_calls == 3
    monitor().calendar_check(tmp_path, provider, now='2026-10-07T08:55:00+09:00')
    assert provider.calendar_calls == 4


def test_saved_quote_binds_complete_candidate_plan_identity_not_only_scalar_source_hashes(tmp_path):
    seed(tmp_path)
    monitor().run_monitor(tmp_path, Provider(), now=OPEN)
    changed = report()
    changed['buy_candidates'][0]['plan'].update(atr=3., stop_price=94., target_price=112., loss_fraction=.06)
    monitor().register_report(tmp_path, changed, now=OPEN)
    monitor().calendar_check(tmp_path, Provider(), now=OPEN)
    view = projected(tmp_path, value=changed)
    assert view['operations']['monitoring']['quotes'][0]['price'] is None
    assert 'identity_mismatch' in view['operations']['monitoring']['reasons']

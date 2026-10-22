"""Frozen candidate plan monitoring: offline IO boundaries and saved-only reads."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_alpha_lab_candidate_store import data, desk

NOW = datetime(2026, 10, 23, 0, 5, tzinfo=timezone.utc)
STAMP = '2026-10-23T00:05:00Z'
SOURCE = 'KIS:J:FHKST03010200+FHKST01010100'


def module():
    try:
        return importlib.import_module('app.services.mirofish.alpha_lab.candidate_monitor')
    except ModuleNotFoundError:
        pytest.fail('candidate monitor implementation missing')


def seed(root, *, count=1):
    from app.services.mirofish.alpha_lab import candidate_store
    value, inputs = desk(), data()
    for index, symbol in enumerate(('000660', '035420')[:count-1], start=2):
        candidate = deepcopy(value['candidates'][0])
        candidate.update(symbol=symbol, name=symbol, rank=index)
        value['candidates'].append(candidate)
        inputs['prices_by_symbol'][symbol] = [dict(row, symbol=symbol) for row in inputs['prices_by_symbol']['005930']]
        inputs['names'][symbol] = symbol
    return candidate_store.publish(root/'candidate-desk', value, inputs, now=value['generated_at'])


def public(root, now=NOW):
    from app.services.mirofish.alpha_lab import candidate_store
    moment = now.isoformat().replace('+00:00', 'Z') if isinstance(now, datetime) else now
    return candidate_store.read_public(root/'candidate-desk', now=moment)


class Provider:
    def __init__(self, *, opened=True, change=None, calendar_change=None, fail_quote=False):
        self.opened, self.change, self.calendar_change, self.fail_quote = opened, change, calendar_change, fail_quote
        self.calls = []

    def fetch_calendar(self, base_date, now=None):
        self.calls.append(('calendar', base_date))
        result = dict(source='KIS:CTCA0903R', captured_at=STAMP,
            days=[dict(date='2026-10-23', is_open=self.opened)])
        if self.calendar_change:
            self.calendar_change(result)
        return result

    def fetch_quote(self, symbol, now=None):
        self.calls.append(('quote', symbol))
        if self.fail_quote:
            raise RuntimeError('credential must never print')
        result = dict(symbol=symbol, source=SOURCE, quote_at=STAMP, fetched_at=STAMP,
            price=100., opening_price=100.)
        if self.change:
            self.change(result)
        return result


def test_tick_uses_frozen_band_and_publishes_saved_only_view_without_changing_first_desk(tmp_path):
    seed(tmp_path, count=3)
    before = {p: p.read_bytes() for p in (tmp_path/'candidate-desk').rglob('*.json')}
    provider = Provider()
    result = module().tick(tmp_path, provider, now=NOW)
    assert set(result) == {'state', 'checked_at', 'decision_id', 'quotes'}
    assert result['state'] == 'monitoring' and result['checked_at'] == STAMP
    assert [row['state'] for row in result['quotes']] == ['within_band']*3
    assert provider.calls == [('calendar', '2026-10-23'), ('quote', '005930'), ('quote', '000660'), ('quote', '035420')]
    assert all(p.read_bytes() == raw for p, raw in before.items())
    saved_before = {p: p.read_bytes() for p in (tmp_path/'candidate-desk'/'monitor').rglob('*.json')}
    assert module().read_view(tmp_path, public(tmp_path), now=NOW) == result
    assert {p: p.read_bytes() for p in (tmp_path/'candidate-desk'/'monitor').rglob('*.json')} == saved_before


@pytest.mark.parametrize('moment,state', [
    ('2026-10-22T00:05:00Z', 'waiting'),
    ('2026-10-23T00:00:00Z', 'monitoring'),
    ('2026-10-22T23:59:59Z', 'waiting'),
    ('2026-10-23T06:30:01Z', 'closed'),
    ('2026-10-24T00:05:00Z', 'closed'),
])
def test_only_entry_session_during_official_market_hours_can_fetch_quotes(tmp_path, moment, state):
    seed(tmp_path)
    provider = Provider(calendar_change=lambda r: r.update(captured_at=moment),
                        change=lambda r: r.update(quote_at=moment, fetched_at=moment))
    result = module().tick(tmp_path, provider, now=moment)
    assert result['state'] == state
    assert bool([call for call in provider.calls if call[0] == 'quote']) == (state == 'monitoring')
    if state in ('waiting', 'closed'):
        assert provider.calls == [] and result['quotes'] == []


@pytest.mark.parametrize('change', [
    lambda r: r.update(source='weekday_guess'),
    lambda r: r.update(captured_at='2026-10-23T00:05:01Z'),
    lambda r: r['days'].append(dict(date='2026-10-23', is_open=True)),
    lambda r: r['days'][0].update(is_open=1),
])
def test_unverified_calendar_never_opens_price_monitoring(tmp_path, change):
    seed(tmp_path); provider = Provider(calendar_change=change)
    result = module().tick(tmp_path, provider, now=NOW)
    assert result['state'] == 'held' and result['quotes'] == []
    assert provider.calls == [('calendar', '2026-10-23')]


def test_official_closed_day_has_no_quote_requests(tmp_path):
    seed(tmp_path); provider = Provider(opened=False)
    result = module().tick(tmp_path, provider, now=NOW)
    assert result['state'] == 'closed' and result['quotes'] == []
    assert provider.calls == [('calendar', '2026-10-23')]


@pytest.mark.parametrize('price,opening,state', [
    (100., 100., 'within_band'),  # Below original close 101 remains allowed above frozen stop.
    (103.02, 103.02, 'within_band'),
    (95., 100., 'skip'), (100., 95., 'skip'),
    (103.03, 100., 'skip'), (100., 104., 'skip'),
    (113., 100., 'skip'),
])
def test_both_current_and_official_open_must_fit_the_original_plan(tmp_path, price, opening, state):
    seed(tmp_path)
    result = module().tick(tmp_path, Provider(change=lambda r:r.update(price=price, opening_price=opening)), now=NOW)
    assert result['quotes'][0]['state'] == state


@pytest.mark.parametrize('change', [
    lambda r:r.update(symbol='000001'), lambda r:r.update(source='NAVER'),
    lambda r:r.update(price=float('nan')), lambda r:r.update(opening_price=-1.),
    lambda r:r.update(quote_at='2026-10-23T00:05:01Z'),
    lambda r:r.update(fetched_at='2026-10-23T00:05:01Z'),
    lambda r:r.update(quote_at='2026-10-23T00:02:59Z'),
    lambda r:r.update(fetched_at='2026-10-23T00:04:59Z'),
])
def test_wrong_source_identity_future_and_old_trade_cannot_be_actionable(tmp_path, change):
    seed(tmp_path)
    result = module().tick(tmp_path, Provider(change=change), now=NOW)
    assert result['state'] == 'failed'
    assert result['quotes'] == [{'symbol': '005930', 'state': 'unavailable'}]


def test_trade_age_120_seconds_is_accepted_but_saved_view_expires_at_420(tmp_path):
    seed(tmp_path)
    result = module().tick(tmp_path, Provider(change=lambda r:r.update(quote_at='2026-10-23T00:03:00Z')), now=NOW)
    assert result['quotes'][0]['state'] == 'within_band'
    assert module().read_view(tmp_path, public(tmp_path), now=NOW+timedelta(seconds=300))['state'] == 'monitoring'
    stale = module().read_view(tmp_path, public(tmp_path), now=NOW+timedelta(seconds=301))
    assert stale['state'] == 'stale' and stale['quotes'] == []


def test_changed_current_desk_during_fetch_cannot_publish_old_actionable_quotes(tmp_path):
    seed(tmp_path)
    from app.services.mirofish.alpha_lab import candidate_store
    before = candidate_store.read_decisions(tmp_path/'candidate-desk')

    def change_current(result):
        candidate_store.set_attempt(tmp_path/'candidate-desk', 'failed', now=STAMP, error='source_unavailable')

    result = module().tick(tmp_path, Provider(change=change_current), now=NOW)
    assert result['state'] == 'held' and result['quotes'] == []
    assert candidate_store.read_decisions(tmp_path/'candidate-desk') == before


def test_calendar_request_crossing_close_does_not_start_a_quote_request(tmp_path, monkeypatch):
    seed(tmp_path, count=3)
    mod = module(); original_clock = mod._clock
    moments = iter(['2026-10-23T06:29:59Z', '2026-10-23T06:30:01Z'])
    last = '2026-10-23T06:30:01Z'
    monkeypatch.setattr(mod, '_clock', lambda value=None: original_clock(value if value is not None else next(moments, last)))
    provider = Provider(calendar_change=lambda r:r.update(captured_at='2026-10-23T06:30:01Z'))
    result = mod.tick(tmp_path, provider)
    assert result['state'] == 'closed' and result['quotes'] == []
    assert provider.calls == [('calendar', '2026-10-23')]


def test_new_current_identity_during_quote_fetch_does_not_publish_old_monitor(tmp_path):
    first = seed(tmp_path)
    from app.services.mirofish.alpha_lab import candidate_store

    def replace_current(result):
        revised, inputs = desk(), data()
        revised.update(latest_session='2026-10-22', generated_at='2026-10-22T12:00:00Z')
        revised['source']['captured_at']='2026-10-22T11:31:00Z'
        revised['candidates'][0]['quote_session'] = '2026-10-22'
        inputs['latest_session'] = '2026-10-22'
        inputs['prices_by_symbol']['005930'].append(dict(inputs['prices_by_symbol']['005930'][-1],date='2026-10-22'))
        candidate_store.publish(tmp_path/'candidate-desk', revised, inputs, now=revised['generated_at'])

    result = module().tick(tmp_path, Provider(change=replace_current), now=NOW)
    assert result['state'] == 'held' and result['quotes'] == []
    latest = public(tmp_path)
    assert latest['decision_id'] != first['decision_id']
    assert not (tmp_path/'candidate-desk'/'monitor'/'latest.json').exists()
    assert module().read_view(tmp_path, latest, now=NOW)['quotes'] == []


def test_reader_discards_wrong_id_future_and_corrupt_saved_observation(tmp_path):
    seed(tmp_path); module().tick(tmp_path, Provider(), now=NOW)
    value = public(tmp_path)
    wrong = dict(value, decision_id='f'*64)
    assert module().read_view(tmp_path, wrong, now=NOW)['quotes'] == []
    assert module().read_view(tmp_path, value, now=NOW-timedelta(seconds=1))['quotes'] == []
    path = tmp_path/'candidate-desk'/'monitor'/'latest.json'
    path.write_text('{"broken":true}', encoding='utf-8')
    assert module().read_view(tmp_path, value, now=NOW)['quotes'] == []


def test_provider_failure_and_extra_private_fields_are_sanitized(tmp_path, capsys):
    seed(tmp_path)
    failure = module().tick(tmp_path, Provider(fail_quote=True), now=NOW)
    assert failure['state'] == 'failed'
    assert 'credential' not in str(failure)+capsys.readouterr().out
    value = module().tick(tmp_path, Provider(change=lambda r:r.update(headers={'authorization':'secret'})), now=NOW)
    assert 'secret' not in str(value)
    assert 'secret' not in ''.join(p.read_text(encoding='utf-8') for p in (tmp_path/'candidate-desk'/'monitor').rglob('*.json'))


def cli():
    path = Path(__file__).resolve().parents[1]/'scripts'/'run_alpha_lab_monitor.py'
    spec = importlib.util.spec_from_file_location('candidate_monitor_cli', path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


@pytest.mark.parametrize('mode', ['prime', 'tick'])
def test_cli_runs_candidate_bridge_only_when_a_desk_pointer_exists(tmp_path, mode, capsys):
    seed(tmp_path); calls = []
    legacy = SimpleNamespace(run_monitor=lambda *a,**k:dict(cadence=dict(market_state='open', calendar_status='ready'),
        monitoring=dict(status='ready')))
    bridge = SimpleNamespace(tick=lambda root,provider,**kwargs:calls.append((root, provider)) or dict(state='monitoring'))
    provider = object()
    assert cli().main([mode, '--root', str(tmp_path)], provider=provider, monitor_module=legacy,
        candidate_monitor_module=bridge, now=NOW) == 0
    assert calls == [(tmp_path, provider)]
    assert json.loads(capsys.readouterr().out)['candidate_monitor_state'] == 'monitoring'

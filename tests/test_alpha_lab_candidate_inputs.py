"""Immutable isolated input snapshots: no external calls and no legacy writes."""
from copy import deepcopy
from datetime import datetime, timezone
import importlib
import json

import pytest

NOW = datetime(2026, 10, 22, 0, tzinfo=timezone.utc)
STAMP = '2026-10-22T00:00:00Z'
NAMES = {'005930': '삼성전자', '000660': 'SK하이닉스'}


def module():
    try:
        return importlib.import_module('app.services.mirofish.alpha_lab.candidate_inputs')
    except ModuleNotFoundError:
        pytest.fail('candidate inputs implementation missing')


def history(symbol, **changes):
    daily = importlib.import_module('app.services.mirofish.alpha_lab.daily_source')
    events = dict(flng_cls_code='00', prtt_rate='0.00', mod_yn='N', revl_issu_reas='')
    row = dict(symbol=symbol, date='2026-10-21', open=100., high=110., low=90., close=105.,
        volume=10000000., traded_value=1050000000., tradable=True, quality_flags=[], source_flags=events)
    params = dict(FID_COND_MRKT_DIV_CODE='J', FID_INPUT_ISCD=symbol,
        FID_INPUT_DATE_1='20251016', FID_INPUT_DATE_2='20261021', FID_PERIOD_DIV_CODE='D', FID_ORG_ADJ_PRC='0')
    empty_params = dict(params, FID_INPUT_DATE_1='20251015', FID_INPUT_DATE_2='20261020')
    raw = dict(stck_bsop_date='20261021', stck_oprc='100', stck_hgpr='110', stck_lwpr='90',
        stck_clpr='105', acml_vol='10000000', acml_tr_pbmn='1050000000', **events)
    pages = [dict(params=params, captured_at=STAMP, response=dict(rt_cd='0',
        output1=dict(stck_shrn_iscd=symbol), output2=[raw])),
        dict(params=empty_params, captured_at=STAMP, response=dict(rt_cd='0',
        output1=dict(stck_shrn_iscd=symbol), output2=[]))]
    value = dict(symbol=symbol, bars=[row], source=deepcopy(daily.SOURCE_CONTRACT),
        captured_at=STAMP, capture={'first': STAMP, 'last': STAMP}, pages=pages,
        history_status='insufficient_history')
    value.update(changes)
    return value


class Provider:
    def __init__(self, failures=(), mutate=None):
        self.failures, self.mutate, self.calls = set(failures), mutate, []

    def fetch_history(self, symbol, end_session, *, count=756):
        self.calls.append((symbol, end_session, count))
        if symbol in self.failures:
            raise RuntimeError('never-store-auth-secret')
        result = history(symbol)
        if self.mutate:
            self.mutate(result)
        return result


def collect(root, provider=None, **kwargs):
    return module().collect_inputs(root, list(NAMES), latest_session='2026-10-21',
        scope_hash='a'*64, names=NAMES, provider=provider or Provider(), now=NOW, **kwargs)


def test_round_trip_seals_real_inputs_capture_and_source_provenance(tmp_path):
    value = collect(tmp_path)
    assert set(value) == {'prices_by_symbol', 'names', 'latest_session', 'input_fingerprint', 'provenance', 'capture_audit'}
    assert value == module().load_inputs(tmp_path)
    assert value['names'] == NAMES and value['latest_session'] == '2026-10-21'
    assert value['capture_audit'] == {symbol: {'first': STAMP, 'last': STAMP} for symbol in NAMES}
    assert value['provenance']['source_contract']['market'] == 'J'
    assert value['provenance']['history_status'] == {symbol: 'insufficient_history' for symbol in NAMES}
    assert value['provenance']['historical_vintage_verified'] is False
    assert len(value['input_fingerprint']) == 64


def test_partial_failure_keeps_success_immutable_and_resumes_only_failed_symbol(tmp_path):
    first = Provider(failures={'000660'})
    with pytest.raises(ValueError, match='candidate_inputs_incomplete') as caught:
        collect(tmp_path, first)
    assert caught.value.failed_symbols == ['000660']
    assert not (tmp_path/'current.json').exists()
    objects = list((tmp_path/'objects').glob('*.json'))
    before = {path: path.read_bytes() for path in objects}
    second = Provider()
    result = collect(tmp_path, second)
    assert second.calls == [('000660', '2026-10-21', 756)]
    assert set(result['prices_by_symbol']) == set(NAMES)
    assert all(path.read_bytes() == raw for path, raw in before.items())
    assert 'never-store-auth-secret' not in ''.join(path.read_text(encoding='utf-8') for path in tmp_path.rglob('*.json'))


def test_same_spec_reuses_sealed_snapshot_but_scope_and_symbol_set_change_identity(tmp_path):
    first = collect(tmp_path)
    provider = Provider(failures=NAMES)
    assert collect(tmp_path, provider) == first and provider.calls == []
    changed = module().collect_inputs(tmp_path, ['005930'], latest_session='2026-10-21',
        scope_hash='a'*64, names=NAMES, provider=Provider(), now=NOW)
    changed_scope = module().collect_inputs(tmp_path, ['005930'], latest_session='2026-10-21',
        scope_hash='b'*64, names=NAMES, provider=Provider(), now=NOW)
    assert len({row['provenance']['snapshot_id'] for row in (first, changed, changed_scope)}) == 3


def test_tampered_success_hash_fails_closed_instead_of_silently_refetching(tmp_path):
    with pytest.raises(ValueError, match='candidate_inputs_incomplete'):
        collect(tmp_path, Provider(failures={'000660'}))
    path = next((tmp_path/'objects').glob('*.json'))
    raw = json.loads(path.read_text(encoding='utf-8'))
    raw['data']['bars'][0]['close'] = 103.
    path.write_text(json.dumps(raw), encoding='utf-8')
    provider = Provider()
    with pytest.raises(ValueError, match='candidate_inputs_integrity'):
        collect(tmp_path, provider)
    assert provider.calls == [] and not (tmp_path/'current.json').exists()


@pytest.mark.parametrize('change,reason', [
    (lambda r: r['source'].update(provider='NAVER'), 'candidate_inputs_source'),
    (lambda r: r.update(symbol='000001'), 'candidate_inputs_identity'),
    (lambda r: r['bars'][0].update(symbol='000001'), 'candidate_inputs_identity'),
    (lambda r: r['bars'][0].update(close=1000.), 'candidate_inputs_ohlcv'),
    (lambda r: r['capture'].update(first='2026-10-21T10:00:00Z'), 'candidate_inputs_capture'),
    (lambda r: r.update(captured_at='2026-10-23T02:00:00Z'), 'candidate_inputs_capture'),
])
def test_provider_injection_cannot_bypass_validation_or_mix_sources(tmp_path, change, reason):
    with pytest.raises(ValueError, match='candidate_inputs_incomplete') as caught:
        collect(tmp_path, Provider(mutate=change))
    assert set(caught.value.failures.values()) == {reason}
    assert not (tmp_path/'current.json').exists()


def test_failed_new_snapshot_preserves_last_good_pointer(tmp_path):
    old = collect(tmp_path)
    before = (tmp_path/'current.json').read_bytes()
    with pytest.raises(ValueError, match='candidate_inputs_incomplete'):
        module().collect_inputs(tmp_path, list(NAMES), latest_session='2026-10-21', scope_hash='b'*64,
            names=NAMES, provider=Provider(failures=NAMES), now=NOW)
    assert (tmp_path/'current.json').read_bytes() == before
    assert module().load_inputs(tmp_path) == old


def test_atomic_pointer_write_failure_keeps_old_snapshot(tmp_path, monkeypatch):
    old = collect(tmp_path)
    real_write = module().write_json_atomic

    def fail_pointer(path, data, **kwargs):
        if str(path).endswith('current.json'):
            raise OSError('disk full')
        return real_write(path, data, **kwargs)

    monkeypatch.setattr(module(), 'write_json_atomic', fail_pointer)
    with pytest.raises(ValueError, match='candidate_inputs_publish'):
        module().collect_inputs(tmp_path, list(NAMES), latest_session='2026-10-21', scope_hash='b'*64,
            names=NAMES, provider=Provider(), now=NOW)
    assert module().load_inputs(tmp_path) == old


def test_latest_session_before_kst_completion_buffer_cannot_start_network(tmp_path):
    provider = Provider()
    with pytest.raises(ValueError, match='candidate_inputs_session_incomplete'):
        module().collect_inputs(tmp_path, list(NAMES), latest_session='2026-10-22', scope_hash='a'*64,
            names=NAMES, provider=provider, now=NOW)
    assert provider.calls == []


@pytest.mark.parametrize('change', [
    lambda r: r.update(pages=[]),
    lambda r: r['pages'][0]['response']['output2'][0].update(stck_clpr='104'),
    lambda r: r['pages'][0]['params'].update(FID_INPUT_DATE_2='20261020'),
    lambda r: r['pages'][1]['params'].update(FID_INPUT_DATE_2='20261021'),
])
def test_raw_pages_must_prove_same_prices_and_backward_contract(tmp_path, change):
    with pytest.raises(ValueError, match='candidate_inputs_incomplete') as caught:
        collect(tmp_path, Provider(mutate=change))
    assert set(caught.value.failures.values()) == {'candidate_inputs_source'}


def test_fresh_acquisition_cannot_claim_an_earlier_actual_capture(tmp_path):
    def backdated(result):
        result['capture'] = {'first': '2026-10-21T12:00:00Z', 'last': '2026-10-21T12:00:00Z'}
        result['captured_at'] = '2026-10-21T12:00:00Z'

    with pytest.raises(ValueError, match='candidate_inputs_incomplete') as caught:
        collect(tmp_path, Provider(mutate=backdated))
    assert set(caught.value.failures.values()) == {'candidate_inputs_capture'}


def test_saved_reader_rejects_object_tampering_and_does_not_repair_it(tmp_path):
    collect(tmp_path)
    path = next((tmp_path/'objects').glob('*.json'))
    raw = path.read_text(encoding='utf-8').replace('105.0', '104.0')
    path.write_text(raw, encoding='utf-8')
    with pytest.raises(ValueError, match='candidate_inputs_integrity'):
        module().load_inputs(tmp_path)
    assert path.read_text(encoding='utf-8') == raw

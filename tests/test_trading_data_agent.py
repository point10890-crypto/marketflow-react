import asyncio
import copy
import hashlib
import importlib
from datetime import datetime, timezone
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def models():
    assert (ROOT / 'app/services/mirofish/trading_agents/models.py').exists(), 'Agent message protocol is not implemented'
    return importlib.import_module('app.services.mirofish.trading_agents.models')


def data_agent():
    assert (ROOT / 'app/services/mirofish/trading_agents/data_agent.py').exists(), 'Data agent is not implemented'
    return importlib.import_module('app.services.mirofish.trading_agents.data_agent')


def test_message_identifier_is_canonical_and_verified_when_deserialized():
    module = models()
    message = module.create_message('run-1', 'request', {'label': '삼성전자', 'a': [1, True, None]})
    canonical = ('{"parent_id":null,"payload":{"a":[1,true,null],"label":"삼성전자"},'
                 '"run_id":"run-1","schema_version":1,"stage":"request"}')
    assert message.message_id == hashlib.sha256(canonical.encode('utf-8')).hexdigest()
    serialized = message.to_dict()
    assert module.AgentMessage.from_dict(serialized).message_id == message.message_id
    serialized['payload']['a'][0] = 2
    with pytest.raises(ValueError, match='identifier'):
        module.AgentMessage.from_dict(serialized)


def test_message_is_a_deep_immutable_snapshot_but_deepcopy_is_editable_for_next_stage():
    module = models()
    source = {'nested': {'numbers': [1, 2]}}
    message = module.create_message('run-2', 'request', source)
    source['nested']['numbers'].append(3)
    assert message.payload['nested']['numbers'] == [1, 2]
    with pytest.raises(FrozenInstanceError):
        message.stage = 'data'
    with pytest.raises(TypeError):
        message.payload['nested']['numbers'].append(3)
    next_payload = copy.deepcopy(message.payload)
    next_payload['nested']['numbers'].append(3)
    assert next_payload['nested']['numbers'] == [1, 2, 3]
    assert message.payload['nested']['numbers'] == [1, 2]


@pytest.mark.parametrize('run_id', ['', '../run', 'run/path', 'x' * 81, 'bad run'])
def test_unsafe_run_identifiers_are_rejected(run_id):
    module = models()
    with pytest.raises(ValueError):
        module.create_message(run_id, 'request', {})


@pytest.mark.parametrize('payload', [{'number': float('nan')}, {'number': float('inf')},
                                     {1: 'not a JSON key'}, {'tuple': (1, 2)}, {'object': object()}])
def test_messages_require_strict_finite_json_payloads(payload):
    module = models()
    with pytest.raises(ValueError):
        module.create_message('safe-run', 'request', payload)


def test_invalid_protocol_stage_version_or_missing_identifier_is_rejected():
    module = models()
    for kwargs in ({'stage': 'broker'}, {'schema_version': 2}, {'schema_version': True}, {'schema_version': 1.0}, {'parent_id': 7}):
        with pytest.raises(ValueError):
            module.AgentMessage('safe-run', kwargs.pop('stage', 'request'), {}, **kwargs)
    serialized = module.create_message('safe-run', 'request', {}).to_dict()
    serialized.pop('message_id')
    with pytest.raises(ValueError):
        module.AgentMessage.from_dict(serialized)


def test_next_stage_parent_identifier_is_part_of_the_content_identity():
    module = models()
    request = module.create_message('chain', 'request', {'input': {}})
    next_stage = module.create_message('chain', 'data', {'input': {}}, parent_id=request.message_id)
    assert next_stage.parent_id == request.message_id and next_stage.message_id != request.message_id
    assert next_stage.to_dict()['payload'] == {'input': {}}


@pytest.mark.parametrize('key', ['api_key', 'crtfc_key', 'authorization', 'access_token', 'refresh_token',
                                 'app_secret', 'kis_app_secret', 'client_secret', 'password', 'API_KEY'])
def test_messages_reject_secret_fields_before_any_payload_can_be_persisted(key):
    module = models()
    with pytest.raises(ValueError, match='secret'):
        module.create_message('safe-run', 'request', {'input': {'nested': [{key: 'sensitive'}]}})


NOW = datetime(2026, 10, 3, 9, 0, tzinfo=timezone.utc)


def request_input(symbols=('005930', '000660')):
    universe = [{'symbol': symbol, 'name': symbol, 'market': 'KOSPI', 'market_cap': 2e12 - index * 1e9,
                 'volume': 1e6, 'share_type': 'common', 'date': '2026-10-01', 'source': 'fixture_listing'}
                for index, symbol in enumerate(symbols)]
    financials = [{'symbol': symbol, 'available_date': '2026-08-15', 'period_end': '2026-06-30',
                   'equity': 100, 'liabilities': 50, 'net_income': 10, 'operating_profit': 20,
                   'fs_div': 'CFS', 'source': 'fixture_DART', 'fetched_at': '2026-10-02T01:00:00Z'}
                  for symbol in symbols]
    return {'as_of': '2026-10-01', 'universe': universe, 'current_financials': financials,
            'prices': [{'symbol': symbol, 'date': '2026-09-30', 'open': 100, 'close': 101, 'volume': 1000}
                       for symbol in symbols],
            'fundamentals': [{'symbol': symbol, 'available_date': '2026-08-15', 'market_cap': 1e12,
                              'debt_ratio': 50, 'tradable': True} for symbol in symbols],
            'evidence': {'price_adjustment_verified': True, 'financial_vintage_verified': True,
                         'source_timestamps': {source: '2026-10-02T01:00:00Z'
                                               for source in ('universe', 'prices', 'current_financials', 'fundamentals')},
                         'source_hashes': {source: 'a' * 64
                                          for source in ('universe', 'prices', 'current_financials', 'fundamentals')}},
            'splits': {'train_end': '2024-12-31', 'validation_end': '2025-12-31', 'test_end': '2026-10-01'},
            'config': {}, 'portfolio': {'cash': 1e6, 'positions': {}}, 'account_id': 'paper-fixture',
            'execution': {'date': '2026-10-02', 'quotes': {}}}


def run_data(request):
    protocol = models()
    message = protocol.create_message('data-test', 'request', {'input': request})
    return asyncio.run(data_agent().DataAgent(now=NOW).handle(message))


def test_data_agent_scopes_top100_before_validation_and_never_refills_failed_quality():
    request = request_input(tuple(f'{index:06}' for index in range(1, 102)))
    request['current_financials'][0]['net_income'] = -1
    request['prices'].append({'symbol': '000001', 'date': 'bad', 'close': 'bad'})
    request['prices'].append({'symbol': '000101', 'date': 'bad', 'close': 'bad'})
    request['fundamentals'].append({'symbol': '000101', 'available_date': 'bad', 'market_cap': 'bad'})
    output = run_data(request)
    data = output.payload['data']
    assert output.stage == 'data' and output.parent_id == models().create_message('data-test', 'request', {'input': request}).message_id
    assert len(data['ranked']) == 100 and len(data['eligible_symbols']) == 99
    assert '000001' not in data['eligible_symbols'] and '000101' not in data['eligible_symbols']
    assert len(data['prices']) == len(data['fundamentals']) == 99 and data['status'] == 'ready'
    assert data['metadata']['current_cohort_bias'] is True and data['metadata']['refill_after_quality'] is False
    assert data['metadata']['win_rate_certified'] is False
    assert output.payload['input'] == request


@pytest.mark.parametrize('flag', ['price_adjustment_verified', 'financial_vintage_verified'])
def test_unverified_evidence_blocks_before_unusable_historical_bars_are_validated(flag):
    request = request_input()
    request['evidence'][flag] = False
    request['prices'] = [{'symbol': '005930', 'date': 'bad', 'open': 0, 'close': 0, 'volume': 0}]
    data = run_data(request).payload['data']
    assert data['status'] == 'blocked' and flag in data['metadata']
    assert data['metadata'][flag] is False and data['prices'] == []
    assert data['reasons'] and len(data['ranked']) == 2


def test_missing_source_artifact_and_future_capture_are_explicit_blocked_results():
    request = request_input()
    request['evidence']['source_hashes'].pop('prices')
    request['evidence']['source_timestamps']['fundamentals'] = '2026-10-04T00:00:00Z'
    data = run_data(request).payload['data']
    assert data['status'] == 'blocked'
    assert 'missing_source_hash:prices' in data['reasons']
    assert 'future_source_capture:fundamentals' in data['reasons']


def test_actual_late_capture_is_not_confused_with_future_historical_asof():
    data = run_data(request_input()).payload['data']
    assert data['status'] == 'ready'
    assert data['metadata']['source_timestamps']['prices'] == '2026-10-02T01:00:00Z'
    assert data['metadata']['future_win_probability_certified'] is False


@pytest.mark.parametrize('trusted', [False, True])
def test_synthetic_fixture_requires_explicit_trust_and_never_claims_performance(trusted):
    request = request_input()
    request['evidence'].update(synthetic=True, trusted_fixture=trusted)
    data = run_data(request).payload['data']
    assert data['status'] == ('ready' if trusted else 'blocked')
    assert data['metadata']['synthetic'] is True and data['metadata']['performance_claims_allowed'] is False


def test_price_quality_flags_block_without_dropping_or_repairing_a_bar():
    request = request_input()
    request['prices'][0].update(open=0, volume=0, quality_flags=['zero_ohl', 'no_tradable_volume'])
    data = run_data(request).payload['data']
    assert data['status'] == 'blocked' and data['prices'][0]['open'] == 0
    assert len(data['prices']) == 2 and data['prices'][0]['volume'] == 0
    assert 'price_quality_flags:005930' in data['reasons']


@pytest.mark.parametrize('mutation', ['price_date', 'price_duplicate', 'price_type', 'fundamental_date',
                                      'fundamental_duplicate', 'tradable_type', 'split_order', 'hash_format',
                                      'naive_source_time', 'flag_type', 'empty_holdout'])
def test_malformed_declared_verified_data_raise_without_producing_a_ready_message(mutation):
    request = request_input()
    if mutation == 'price_date': request['prices'][0]['date'] = '2026-02-30'
    elif mutation == 'price_duplicate': request['prices'].append(dict(request['prices'][0]))
    elif mutation == 'price_type': request['prices'][0]['close'] = '101'
    elif mutation == 'fundamental_date': request['fundamentals'][0]['available_date'] = '2026-02-30'
    elif mutation == 'fundamental_duplicate': request['fundamentals'].append(dict(request['fundamentals'][0]))
    elif mutation == 'tradable_type': request['fundamentals'][0]['tradable'] = 'true'
    elif mutation == 'split_order': request['splits']['train_end'] = '2026-10-01'
    elif mutation == 'hash_format': request['evidence']['source_hashes']['prices'] = 'not-a-hash'
    elif mutation == 'naive_source_time': request['evidence']['source_timestamps']['prices'] = '2026-10-02T01:00:00'
    elif mutation == 'flag_type': request['evidence']['price_adjustment_verified'] = 'true'
    elif mutation == 'empty_holdout': request['splits']['validation_end'] = request['splits']['test_end']
    with pytest.raises(ValueError):
        run_data(request)


def test_missing_eligible_price_history_or_financial_quality_is_a_hold_not_refill():
    request = request_input()
    request['current_financials'][0]['net_income'] = -1
    request['prices'] = []
    data = run_data(request).payload['data']
    assert data['status'] == 'blocked' and data['eligible_symbols'] == ['000660']
    assert 'missing_prices:000660' in data['reasons']
    assert data['quality']['held'][0]['symbol'] == '005930'


def test_wrong_incoming_stage_or_missing_input_is_rejected():
    module = data_agent()
    protocol = models()
    for message in (protocol.create_message('wrong-stage', 'quant', {'input': request_input()}),
                    protocol.create_message('missing-input', 'request', {})):
        with pytest.raises(ValueError):
            asyncio.run(module.DataAgent(now=NOW).handle(message))

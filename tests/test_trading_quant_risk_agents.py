"""Offline stage contracts: frozen evidence, empirical sizing, and cash limits."""
import asyncio
import copy
import importlib
from datetime import date, timedelta
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def agents():
    directory = ROOT / 'app/services/mirofish/trading_agents'
    assert (directory / 'quant_agent.py').exists(), 'Quant stage is not implemented'
    assert (directory / 'risk_agent.py').exists(), 'Risk stage is not implemented'
    return (importlib.import_module('app.services.mirofish.trading_agents.quant_agent'),
            importlib.import_module('app.services.mirofish.trading_agents.risk_agent'),
            importlib.import_module('app.services.mirofish.trading_agents.models'))


def synthetic_request(symbols=('AAA',)):
    days = [(date(2024, 1, 1) + timedelta(days=i)).isoformat() for i in range(631)]
    rows, funds = [], []
    for symbol in symbols:
        close = 100.
        rows.append(dict(symbol=symbol, name='price-provider-name', date=days[0],
                         close=close, open=close, volume=1000.))
        for index in range(1, 628):
            cycle, offset = divmod(index - 1, 7)
            outcome = -.02 if cycle % 5 == 4 else .035
            change = [.01, .012, .008, -.06, 0., outcome, 0.][offset]
            close *= 1 + change
            rows.append(dict(symbol=symbol, name='price-provider-name', date=days[index],
                             close=close, open=close, volume=1000.))
        for index in range(0, 628, 100):
            funds.append(dict(symbol=symbol, available_date=days[index], market_cap=1e12,
                              debt_ratio=30., tradable=True))
    request = dict(as_of=days[627], universe=[dict(symbol=s, name=f'{s} Quality', market='KOSPI')
                   for s in symbols], prices=rows, fundamentals=funds, current_financials=[],
                   evidence={'kind': 'synthetic_demo'},
                   splits=dict(train_end=days[210], validation_end=days[420], test_end=days[627]),
                   config={'research': {'lookback': 3, 'horizon': 2}, 'risk': {}},
                   portfolio={'cash': 1000., 'positions': {}}, account_id='paper',
                   execution={'date': days[628], 'quotes': {s: dict(price=100., volume=1000.,
                              date=days[628], source='synthetic_demo') for s in symbols},
                              'cost_bps': 5., 'slippage_bps': 10., 'sell_tax_bps': 0.})
    data = dict(status='ready', reasons=[], eligible_symbols=list(symbols), prices=rows,
                fundamentals=funds, metadata={'current_cohort_bias': True})
    return request, data


def run_quant(request=None, data=None, **kwargs):
    quant, _, models = agents()
    base_request, base_data = synthetic_request()
    message = models.create_message('run-1', 'data', {'input': request or base_request,
                                                   'data': data if data is not None else base_data})
    return asyncio.run(quant.QuantAgent(**kwargs).handle(message)), message


def metric(**changes):
    return dict({'samples': 40, 'win_rate': .8, 'win_lower': .65, 'payoff': 1.5,
                 'expected_net_return': .02, 'avg_win': .03, 'avg_loss': .02}, **changes)


def qualified(symbol='AAA', *, kelly=.3, volatility=.02, current=True):
    return dict(symbol=symbol, name=f'{symbol} Quality', market='KOSPI', eligible=True,
                reason='qualified', train=metric(), validation=metric(), estimated_kelly=kelly,
                prior_volatility=volatility, has_current_signal=current,
                signal_date=(date(2024, 1, 1) + timedelta(days=627)).isoformat(), signal_z=-3.)


def run_risk(*, candidates=None, qualifications=None, request=None, data=None, status='ready'):
    _, risk, models = agents()
    base_request, base_data = synthetic_request()
    request = copy.deepcopy(request or base_request)
    data = data if data is not None else base_data
    candidates = [qualified()] if candidates is None else candidates
    qualifications = copy.deepcopy(candidates) if qualifications is None else qualifications
    quant = dict(status=status, reasons=[], qualification_complete=True,
                 as_of=request['as_of'], frozen_at=request['splits']['validation_end'],
                 candidates=candidates, qualified=qualifications, qualification=qualifications,
                 config={'min_samples': 30, 'min_win_rate': .6, 'min_win_lower': .6,
                         'min_payoff': 1., 'volatility_threshold': .03})
    message = models.create_message('run-1', 'quant', {'input': request, 'data': data, 'quant': quant})
    return asyncio.run(risk.RiskAgent().handle(message)), message


def test_blocked_data_is_held_without_research_computation():
    request, data = synthetic_request()
    data.update(status='blocked', reasons=['unverified_price_basis'])
    def forbidden(*args, **kwargs):
        pytest.fail('Blocked data must not run research')
    result, parent = run_quant(request, data, research_runner=forbidden)
    assert result.stage == 'quant' and result.parent_id == parent.message_id
    assert result.payload['quant']['status'] == 'held'
    assert result.payload['quant']['candidates'] == []
    assert 'unverified_price_basis' in result.payload['quant']['reasons']


def test_real_engine_qualifies_and_requires_the_asof_current_signal():
    request, data = synthetic_request()
    result, _ = run_quant(request, data)
    quant = result.payload['quant']
    assert quant['status'] == 'ready' and len(quant['candidates']) == 1
    item = quant['candidates'][0]
    assert (item['symbol'], item['name'], item['market']) == ('AAA', 'AAA Quality', 'KOSPI')
    assert item['train']['samples'] == 30 and item['validation']['samples'] == 30
    assert item['has_current_signal'] is True and item['estimated_kelly'] > 0
    assert quant['frozen_at'] == request['splits']['validation_end']
    assert 'test' not in quant['qualified'][0] and 'test' not in item


def test_holdout_mutation_does_not_change_qualification_or_kelly():
    request, data = synthetic_request()
    first, _ = run_quant(request, data)
    changed = copy.deepcopy(data)
    for row in changed['prices']:
        if row['date'] > request['splits']['validation_end']:
            row['open'] *= .7
            row['close'] *= .7
    second, _ = run_quant(request, changed)
    assert first.payload['quant']['qualified'] == second.payload['quant']['qualified']


def test_old_test_end_has_no_stale_buy_candidate():
    request, data = synthetic_request()
    request['splits']['test_end'] = data['prices'][-8]['date']
    result, _ = run_quant(request, data)
    assert result.payload['quant']['status'] == 'held'
    assert result.payload['quant']['candidates'] == []
    assert result.payload['quant']['qualified']


def test_cannot_expand_data_scope_or_use_future_test_end():
    request, data = synthetic_request()
    data['eligible_symbols'] = ['AAA', 'OUTSIDE']
    result, _ = run_quant(request, data)
    assert result.payload['quant']['status'] == 'held'
    request, data = synthetic_request()
    request['splits']['test_end'] = request['execution']['date']
    result, _ = run_quant(request, data)
    assert result.payload['quant']['status'] == 'held'


def test_more_than_one_hundred_universe_symbols_is_held_before_computation():
    request, data = synthetic_request()
    request['universe'] = [dict(symbol=f'S{index}', name=f'S{index}', market='KOSPI') for index in range(101)]
    result, _ = run_quant(request, data, research_runner=lambda *a, **k: pytest.fail('Oversized scope'))
    assert result.payload['quant']['status'] == 'held'


def test_full_listing_uses_verified_ranked_cohort_only():
    request, data = synthetic_request()
    request['universe'].extend(dict(symbol=f'S{index}', name=f'S{index}', market='KOSPI') for index in range(100))
    data['ranked'] = copy.deepcopy(request['universe'][:100])
    result, _ = run_quant(request, data)
    assert result.payload['quant']['status'] == 'ready'
    assert [row['symbol'] for row in result.payload['quant']['candidates']] == ['AAA']
    data['ranked'][0]['name'] = 'Unknown Company'
    result, _ = run_quant(request, data)
    assert result.payload['quant']['status'] == 'held'


def test_quant_failure_cannot_be_interpreted_as_verified_loss_of_qualification():
    quant, risk, models = agents()
    request, data = synthetic_request()
    request['portfolio']['positions'] = {'AAA': 2.}
    def broken(*args, **kwargs):
        raise ValueError('Invalid research calculation')
    parent = models.create_message('run-1', 'data', {'input': request, 'data': data})
    failed = asyncio.run(quant.QuantAgent(research_runner=broken).handle(parent))
    result = asyncio.run(risk.RiskAgent().handle(failed))
    assert failed.payload['quant']['qualification_complete'] is False
    assert result.payload['risk']['status'] == 'held'
    assert result.payload['risk']['targets'] == {}


def test_risk_sizes_half_empirical_kelly_and_caps_and_volatility():
    result, parent = run_risk(candidates=[qualified(kelly=.3, volatility=.1)])
    risk = result.payload['risk']
    assert result.stage == 'risk' and result.parent_id == parent.message_id
    assert risk['status'] == 'approved'
    assert risk['targets']['AAA'] == pytest.approx(.075)
    assert risk['max_exposure'] == .6 and risk['min_cash'] == .4
    result, _ = run_risk(candidates=[qualified(kelly=1., volatility=.02)])
    assert result.payload['risk']['targets']['AAA'] == pytest.approx(.2)


def test_risk_maintains_only_qualified_existing_holdings_without_new_signal():
    request, data = synthetic_request()
    request['portfolio']['positions'] = {'AAA': 2.}
    result, _ = run_risk(request=request, data=data, candidates=[],
                         qualifications=[qualified(current=False)], status='held')
    assert result.payload['risk']['status'] == 'approved'
    assert result.payload['risk']['targets']['AAA'] == pytest.approx(.15)
    request['portfolio']['positions'] = {}
    result, _ = run_risk(request=request, data=data, candidates=[],
                         qualifications=[qualified(current=False)], status='held')
    assert result.payload['risk']['status'] == 'held' and result.payload['risk']['targets'] == {}


def test_ready_data_can_risk_exit_removed_eligibility_but_blocked_data_cannot():
    request, data = synthetic_request()
    request['portfolio']['positions'] = {'AAA': 2.}
    result, _ = run_risk(request=request, data=data, candidates=[], qualifications=[], status='held')
    assert result.payload['risk']['status'] == 'approved'
    assert result.payload['risk']['targets'] == {'AAA': 0.}
    data = dict(data, status='blocked', reasons=['missing_fundamental'])
    result, _ = run_risk(request=request, data=data, candidates=[], qualifications=[], status='held')
    assert result.payload['risk']['status'] == 'held' and result.payload['risk']['targets'] == {}


@pytest.mark.parametrize('change', [
    {'max_weight': .21}, {'max_exposure': .61}, {'min_cash': .39},
    {'max_positions': 4}, {'kelly_fraction': .51}, {'kelly_fraction': 0},
])
def test_risk_limits_may_only_tighten(change):
    request, data = synthetic_request()
    request['config']['risk'] = change
    result, _ = run_risk(request=request, data=data)
    assert result.payload['risk']['status'] == 'rejected'
    assert result.payload['risk']['targets'] == {}


def test_tightened_exposure_and_cash_floor_scale_without_using_quote_prices_to_rank():
    request, data = synthetic_request(('AAA', 'BBB', 'CCC', 'DDD'))
    request['config']['risk'] = {'max_exposure': .3, 'min_cash': .6}
    items = [qualified(symbol, kelly=1.) for symbol in ('DDD', 'CCC', 'BBB', 'AAA')]
    result, _ = run_risk(request=request, data=data, candidates=items, qualifications=items)
    risk = result.payload['risk']
    assert list(risk['targets']) == ['AAA', 'BBB', 'CCC']
    assert sum(risk['targets'].values()) == pytest.approx(.3)
    changed = copy.deepcopy(request)
    changed['execution']['quotes']['AAA']['price'] = 100000.
    second, _ = run_risk(request=changed, data=data, candidates=items, qualifications=items)
    assert risk['targets'] == second.payload['risk']['targets']


@pytest.mark.parametrize('mutation', ['stale_quote', 'missing_quote', 'zero_volume', 'negative_quantity', 'wrong_name'])
def test_risk_rejects_bad_valuation_or_candidate_identity(mutation):
    request, data = synthetic_request()
    request['portfolio']['positions'] = {'AAA': 1.}
    item = qualified()
    if mutation == 'stale_quote': request['execution']['quotes']['AAA']['date'] = request['as_of']
    if mutation == 'missing_quote': request['execution']['quotes'] = {}
    if mutation == 'zero_volume': request['execution']['quotes']['AAA']['volume'] = 0.
    if mutation == 'negative_quantity': request['portfolio']['positions']['AAA'] = -1.
    if mutation == 'wrong_name': item['name'] = 'Other Company'
    result, _ = run_risk(request=request, data=data, candidates=[item])
    assert result.payload['risk']['status'] == 'rejected' and result.payload['risk']['targets'] == {}


def test_holdout_success_cannot_replace_train_validation_gates():
    item = qualified()
    item['train']['samples'] = 1
    item['test'] = metric(samples=1000, win_rate=1., win_lower=.99, payoff=100.)
    result, _ = run_risk(candidates=[item])
    assert result.payload['risk']['status'] == 'rejected' and result.payload['risk']['targets'] == {}


@pytest.mark.parametrize('mutation', ['missing_signal_date', 'stale_signal_date', 'positive_signal_z'])
def test_new_entry_requires_exact_current_signal_evidence(mutation):
    item = qualified()
    if mutation == 'missing_signal_date': item.pop('signal_date')
    if mutation == 'stale_signal_date': item['signal_date'] = '2024-01-01'
    if mutation == 'positive_signal_z': item['signal_z'] = 2.
    result, _ = run_risk(candidates=[item])
    assert result.payload['risk']['status'] == 'rejected'


def test_held_symbol_outside_ranked_cohort_can_be_exit_only_with_a_quote():
    request, data = synthetic_request()
    request['portfolio']['positions'] = {'LEGACY': 2.}
    request['execution']['quotes']['LEGACY'] = dict(price=100., volume=1000.,
        date=request['execution']['date'], source='verified_supplied_quote')
    result, _ = run_risk(request=request, data=data, candidates=[], qualifications=[], status='held')
    assert result.payload['risk']['status'] == 'approved'
    assert result.payload['risk']['targets'] == {'LEGACY': 0.}

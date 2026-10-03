import asyncio
import copy
import hashlib
import importlib
import json
from pathlib import Path

import pytest

from app.services.mirofish.trading_agents.models import create_message


def module():
    path = Path(__file__).resolve().parents[1] / 'app/services/mirofish/trading_agents/orchestrator.py'
    assert path.exists(), 'CIO orchestrator has not been implemented'
    return importlib.import_module('app.services.mirofish.trading_agents.orchestrator')


def request():
    return {'as_of': '2026-10-01', 'account_id': 'paper-test',
            'universe': [{'symbol': '000001', 'name': 'Fixture stock', 'market': 'KOSPI'}],
            'evidence': {'price_adjustment_verified': True, 'financial_vintage_verified': True,
                         'source_timestamps': {key: '2026-10-02T01:00:00Z' for key in
                                               ('universe', 'prices', 'current_financials', 'fundamentals')},
                         'source_hashes': {key: 'a' * 64 for key in
                                          ('universe', 'prices', 'current_financials', 'fundamentals')}},
            'config': {}, 'portfolio': {'cash': 10000., 'positions': {}},
            'execution': {'date': '2026-10-02', 'quotes': {
                '000001': {'price': 100., 'volume': 1000., 'date': '2026-10-02', 'source': 'fixture'}}}}


def qualified():
    metrics = {'samples': 50, 'win_rate': .8, 'win_lower': .65, 'payoff': 2., 'expected_net_return': .01}
    return {'symbol': '000001', 'name': 'Fixture stock', 'market': 'KOSPI',
            'train': metrics, 'validation': dict(metrics), 'estimated_kelly': .4, 'prior_volatility': .01,
            'has_current_signal': True, 'signal_date': '2026-10-01', 'signal_z': -2.5, 'eligible': True}


class MemoryStore:
    def __init__(self):
        self.runs, self.stages, self.reports, self.errors = {}, {}, {}, []

    def begin_run(self, run_id, request_hash):
        if run_id in self.runs and self.runs[run_id] != request_hash:
            raise ValueError('Changed request identity')
        self.runs[run_id] = request_hash

    def load_stage(self, run_id, stage):
        return copy.deepcopy(self.stages.get((run_id, stage)))

    def save_stage(self, run_id, stage, message):
        self.stages[(run_id, stage)] = copy.deepcopy(message)

    def load_report(self, run_id):
        return copy.deepcopy(self.reports.get(run_id))

    def save_report(self, run_id, report):
        self.reports[run_id] = copy.deepcopy(report)

    def record_error(self, run_id, stage, error_type):
        self.errors.append((run_id, stage, error_type))


class Actor:
    def __init__(self, stage, output, *, delay=0, failure=False, wrong_parent=False):
        self.stage, self.output, self.delay = stage, output, delay
        self.failure, self.wrong_parent = failure, wrong_parent

    async def handle(self, message):
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.failure:
            raise ValueError('An authenticated URL must never enter the error journal')
        payload = copy.deepcopy(message.payload)
        payload[self.stage] = copy.deepcopy(self.output)
        return create_message(message.run_id, self.stage, payload,
                              'wrong-parent' if self.wrong_parent else message.message_id)


def actors(*, blocked=False, weight=.2):
    return {'data': Actor('data', {'status': 'blocked' if blocked else 'ready',
                                 'reasons': ['unverified_source'] if blocked else [],
                                 'ranked': request()['universe'], 'eligible_symbols': ['000001'],
                                 'metadata': dict(copy.deepcopy(request()['evidence']), synthetic=False)}),
            'quant': Actor('quant', {'status': 'ready', 'qualification_complete': True,
                                    'qualified': [qualified()], 'candidates': [qualified()]}),
            'risk': Actor('risk', {'status': 'approved', 'targets': {'000001': weight}, 'reasons': []}),
            'execution': Actor('execution', {'status': 'executed', 'fills': [],
                                           'portfolio': request()['portfolio']})}


def run(orch, value=None, run_id='fixture-run'):
    return asyncio.run(orch.run(value or request(), run_id=run_id))


def test_message_queues_persist_a_complete_parent_chain_and_cio_approval():
    mod, store = module(), MemoryStore()
    result = run(mod.TradingOrchestrator(store=store, actors=actors()))
    assert result['status'] == 'completed'
    assert result['live_orders'] is False and result['paper_only'] is True
    approval = store.load_stage('fixture-run', 'approval')
    assert approval['payload']['approval']['decision'] == 'approved'
    assert approval['payload']['approval']['risk_message_id'] == store.load_stage('fixture-run', 'risk')['message_id']
    stages = [store.load_stage('fixture-run', stage) for stage in mod.STAGE_ORDER]
    assert all(current['parent_id'] == previous['message_id'] for previous, current in zip(stages, stages[1:]))


@pytest.mark.parametrize('weight', [.21, .7, 1.])
def test_cio_vetoes_a_risk_actor_that_exceeds_hard_caps(weight):
    mod, store = module(), MemoryStore()
    run(mod.TradingOrchestrator(store=store, actors=actors(weight=weight)))
    assert store.load_stage('fixture-run', 'approval')['payload']['approval']['decision'] == 'held'


def test_cio_vetoes_unverified_data_even_when_other_actors_claim_approval():
    mod, store = module(), MemoryStore()
    run(mod.TradingOrchestrator(store=store, actors=actors(blocked=True)))
    assert store.load_stage('fixture-run', 'approval')['payload']['approval']['decision'] == 'held'


def test_cio_does_not_accept_a_weak_validation_statistic_or_new_stale_entry():
    mod = module()
    for change in ('weak', 'stale'):
        store, nodes = MemoryStore(), actors()
        if change == 'weak':
            nodes['quant'].output['qualified'][0]['validation']['win_lower'] = .5
        else:
            nodes['quant'].output['candidates'] = []
        run(mod.TradingOrchestrator(store=store, actors=nodes))
        assert store.load_stage('fixture-run', 'approval')['payload']['approval']['decision'] == 'held'


def test_interruption_reuses_completed_data_stage_and_records_no_exception_text():
    mod, store, nodes = module(), MemoryStore(), actors()
    nodes['quant'].failure = True
    with pytest.raises(mod.PipelineError):
        run(mod.TradingOrchestrator(store=store, actors=nodes))
    preserved = store.load_stage('fixture-run', 'data')
    assert store.load_report('fixture-run') is None
    assert store.errors == [('fixture-run', 'quant', 'ValueError')]
    nodes = actors()
    nodes['data'].failure = True
    result = run(mod.TradingOrchestrator(store=store, actors=nodes))
    assert result['status'] == 'completed'
    assert store.load_stage('fixture-run', 'data') == preserved


def test_wrong_parent_and_timeout_are_recoverable_without_final_report():
    mod = module()
    for mode in ('parent', 'timeout'):
        store, nodes = MemoryStore(), actors()
        nodes['quant'].wrong_parent = mode == 'parent'
        nodes['quant'].delay = .1 if mode == 'timeout' else 0
        with pytest.raises(mod.PipelineError):
            run(mod.TradingOrchestrator(store=store, actors=nodes, stage_timeout=.02))
        assert store.load_stage('fixture-run', 'quant') is None
        assert store.load_report('fixture-run') is None


def test_completed_run_replays_its_report_and_changed_input_is_rejected():
    mod, store = module(), MemoryStore()
    first = run(mod.TradingOrchestrator(store=store, actors=actors()))
    nodes = actors()
    for actor in nodes.values():
        actor.failure = True
    assert run(mod.TradingOrchestrator(store=store, actors=nodes)) == first
    changed = request()
    changed['portfolio']['cash'] = 10001.
    with pytest.raises(ValueError):
        run(mod.TradingOrchestrator(store=store, actors=nodes), changed)


def approval(value=None, nodes=None):
    value, nodes = value or request(), nodes or actors()
    payload = {'input': value, **{stage: copy.deepcopy(nodes[stage].output) for stage in ('data', 'quant', 'risk')}}
    return module().cio_approval(create_message('cio-review', 'risk', payload)).payload['approval']


def test_cio_allows_executable_zero_weight_exits_and_counts_only_positive_positions():
    value, nodes = request(), actors()
    value['config'] = {'risk': {'max_positions': 1}}
    for symbol in ('000002', '000003', '000004'):
        value['portfolio']['positions'][symbol] = 10.
        value['execution']['quotes'][symbol] = dict(value['execution']['quotes']['000001'])
        nodes['risk'].output['targets'][symbol] = 0.
    assert approval(value, nodes)['decision'] == 'approved'


@pytest.mark.parametrize('mode', ['unheld', 'zero_holding', 'missing_quote'])
def test_cio_rejects_an_exit_without_positive_holding_or_executable_quote(mode):
    value, nodes = request(), actors()
    nodes['risk'].output['targets']['000002'] = 0.
    value['execution']['quotes']['000002'] = dict(value['execution']['quotes']['000001'])
    if mode == 'zero_holding': value['portfolio']['positions']['000002'] = 0.
    elif mode == 'missing_quote':
        value['portfolio']['positions']['000002'] = 10.
        value['execution']['quotes'].pop('000002')
    assert approval(value, nodes)['decision'] == 'held'


@pytest.mark.parametrize('change', ['impossible_bound', 'confidence_z', 'min_samples', 'min_payoff'])
def test_cio_recomputes_wilson_and_applies_configured_train_validation_gates(change):
    value, nodes = request(), actors()
    if change == 'impossible_bound':
        nodes['quant'].output['qualified'][0]['validation'].update(samples=30, win_rate=.6, win_lower=.6)
    else:
        value['config'] = {'research': {change: {'confidence_z': 2.58, 'min_samples': 100, 'min_payoff': 3}[change]}}
    assert approval(value, nodes)['decision'] == 'held'


@pytest.mark.parametrize('overrides,updates', [
    ({'min_samples': 1}, {'samples': 20, 'win_rate': .95, 'win_lower': .7}),
    ({'min_win_rate': .5, 'min_win_lower': .1}, {'win_rate': .55, 'win_lower': .3}),
    ({'min_win_lower': .3}, {'win_lower': .5}),
    ({'min_payoff': .5}, {'payoff': .8}),
])
def test_cio_experimental_research_overrides_cannot_lower_hard_qualification_floors(overrides, updates):
    value, nodes = request(), actors()
    value['config'] = {'research': overrides}
    for group in ('qualified', 'candidates'):
        for split in ('train', 'validation'):
            nodes['quant'].output[group][0][split].update(updates)
    assert approval(value, nodes)['decision'] == 'held'


@pytest.mark.parametrize('change', ['not_eligible', 'weak_signal', 'missing_signal'])
def test_cio_checks_explicit_qualification_and_empirical_current_signal(change):
    nodes = actors()
    if change == 'not_eligible': nodes['quant'].output['qualified'][0]['eligible'] = False
    elif change == 'weak_signal': nodes['quant'].output['candidates'][0]['signal_z'] = 0.
    elif change == 'missing_signal': nodes['quant'].output['candidates'][0].pop('signal_z')
    assert approval(nodes=nodes)['decision'] == 'held'


@pytest.mark.parametrize('weight,expected', [(.2, 'held'), (.1, 'approved')])
def test_cio_independently_halves_high_volatility_target_limit(weight, expected):
    nodes = actors(weight=weight)
    nodes['quant'].output['qualified'][0]['prior_volatility'] = .05
    nodes['quant'].output['candidates'][0]['prior_volatility'] = .05
    assert approval(nodes=nodes)['decision'] == expected


@pytest.mark.parametrize('frozen,current,expected', [(.05, .01, 'approved'), (.01, .05, 'held')])
def test_cio_sizes_fresh_signals_with_current_volatility_instead_of_frozen_volatility(frozen, current, expected):
    nodes = actors()
    nodes['quant'].output['qualified'][0]['prior_volatility'] = frozen
    nodes['quant'].output['candidates'][0]['prior_volatility'] = current
    assert approval(nodes=nodes)['decision'] == expected


def test_actual_risk_agent_legacy_exit_passes_independent_cio_validation():
    from app.services.mirofish.trading_agents.risk_agent import RiskAgent
    value, nodes = request(), actors()
    value['splits'] = {'train_end': '2024-12-31', 'validation_end': '2025-12-31', 'test_end': '2026-10-01'}
    value['portfolio']['positions']['000099'] = 20.
    value['execution']['quotes']['000099'] = dict(value['execution']['quotes']['000001'])
    quant = {'status': 'held', 'qualification_complete': True, 'qualified': [], 'candidates': [],
             'as_of': value['as_of'], 'frozen_at': value['splits']['validation_end']}
    payload = {'input': value, 'data': nodes['data'].output, 'quant': quant}
    risk = asyncio.run(RiskAgent().handle(create_message('actual-risk-exit', 'quant', payload)))
    assert risk.payload['risk']['targets'] == {'000099': 0.}
    assert module().cio_approval(risk).payload['approval']['decision'] == 'approved'


@pytest.mark.parametrize('change', ['missing_timestamps', 'missing_hashes', 'future_capture',
                                    'untrusted_synthetic', 'metadata_mismatch'])
def test_cio_requires_the_complete_data_provenance_contract(change):
    value, nodes = request(), actors()
    if change == 'missing_timestamps': value['evidence'].pop('source_timestamps')
    elif change == 'missing_hashes': value['evidence'].pop('source_hashes')
    elif change == 'future_capture': value['evidence']['source_timestamps']['prices'] = '2999-01-01T00:00:00Z'
    elif change == 'untrusted_synthetic': value['evidence'].update(synthetic=True, trusted_fixture=False)
    elif change == 'metadata_mismatch': nodes['data'].output['metadata']['price_adjustment_verified'] = False
    assert approval(value, nodes)['decision'] == 'held'


@pytest.mark.parametrize('change', ['run_id', 'portfolio', 'missing_stage', 'broken_parent'])
def test_completed_report_replay_requires_a_matching_verified_full_stage_chain(change):
    mod, store = module(), MemoryStore()
    run(mod.TradingOrchestrator(store=store, actors=actors()))
    if change == 'run_id': store.reports['fixture-run']['run_id'] = 'other-run'
    elif change == 'portfolio': store.reports['fixture-run']['execution']['portfolio']['cash'] = 999999.
    elif change == 'missing_stage': store.stages.pop(('fixture-run', 'quant'))
    elif change == 'broken_parent':
        cached = store.stages[('fixture-run', 'risk')]
        store.stages[('fixture-run', 'risk')] = create_message('fixture-run', 'risk', cached['payload'], 'bad-parent').to_dict()
    nodes = actors()
    for actor in nodes.values(): actor.failure = True
    with pytest.raises(mod.PipelineError):
        run(mod.TradingOrchestrator(store=store, actors=nodes))
    assert store.errors[-1] == ('fixture-run', 'execution', 'ValueError')


def test_a_caller_mutation_during_async_processing_cannot_change_held_execution_input():
    value, nodes, store = request(), actors(blocked=True), MemoryStore()

    class MutatingData(Actor):
        async def handle(self, message):
            value['portfolio']['cash'] = 1.
            value['execution']['date'] = '2026-10-03'
            return await super().handle(message)

    nodes['data'] = MutatingData('data', nodes['data'].output)
    result = run(module().TradingOrchestrator(store=store, actors=nodes), value)
    assert result['execution']['portfolio']['cash'] == 10000.
    assert result['execution']['date'] == '2026-10-02'

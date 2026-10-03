import asyncio
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.services.mirofish.trading_agents.models import AgentMessage, create_message


def module_store():
    source = Path(__file__).resolve().parents[1] / 'app/services/mirofish/trading_agents/store.py'
    assert source.exists(), 'Durable trading agent store has not been implemented'
    from app.services.mirofish.trading_agents.store import AgentStore
    return AgentStore


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                                     allow_nan=False).encode('utf-8')).hexdigest()


def new_store(tmp_path):
    return module_store()(tmp_path / 'agents.sqlite3')


def request(store, run='run-1'):
    value = create_message(run, 'request', {'input': {'as_of': '2026-10-02'}})
    store.begin_run(run, value.message_id)
    store.save_stage(run, 'request', value.to_dict())
    return value


def test_completed_stage_and_report_survive_new_store_instance(tmp_path):
    store = new_store(tmp_path)
    message = request(store)
    store.save_report('run-1', {'status': 'held', 'message_id': message.message_id})
    restarted = module_store()(tmp_path / 'agents.sqlite3')
    assert restarted.load_stage('run-1', 'request') == message.to_dict()
    assert restarted.load_report('run-1') == {'status': 'held', 'message_id': message.message_id}
    assert restarted.load_stage('run-1', 'execution') is None


def test_same_run_id_cannot_change_request_hash(tmp_path):
    store = new_store(tmp_path)
    message = request(store)
    store.begin_run('run-1', message.message_id)
    with pytest.raises(ValueError):
        store.begin_run('run-1', 'b' * 64)
    with pytest.raises(ValueError):
        store.begin_run('other', 'unverified-short-hash')


def test_completed_stage_is_immutable_but_same_message_is_idempotent(tmp_path):
    store = new_store(tmp_path)
    message = request(store)
    store.save_stage('run-1', 'request', message.to_dict())
    changed = create_message('run-1', 'request', {'input': {'as_of': '2026-10-01'}})
    with pytest.raises(ValueError):
        store.save_stage('run-1', 'request', changed.to_dict())
    assert store.load_stage('run-1', 'request') == message.to_dict()


def test_corrupt_message_identifier_and_unknown_run_are_not_persisted(tmp_path):
    store = new_store(tmp_path)
    message = request(store).to_dict()
    message['message_id'] = 'a' * 64
    with pytest.raises(ValueError):
        store.save_stage('run-1', 'request', message)
    unknown = create_message('unknown', 'request', {'input': {}})
    with pytest.raises(ValueError):
        store.save_stage('unknown', 'request', unknown.to_dict())


def test_existing_previous_stage_requires_exact_parent_identity(tmp_path):
    store = new_store(tmp_path)
    previous = request(store)
    wrong = create_message('run-1', 'data', {'input': {}}, parent_id='wrong-parent')
    with pytest.raises(ValueError):
        store.save_stage('run-1', 'data', wrong.to_dict())
    correct = create_message('run-1', 'data', dict(previous.payload), parent_id=previous.message_id)
    store.save_stage('run-1', 'data', correct.to_dict())


def test_reports_do_not_accept_secrets_or_nonfinite_numbers(tmp_path):
    store = new_store(tmp_path)
    request(store)
    for report in [{'nested': {'api_key': 'never-persist-me'}}, {'app_secret': 'never-persist-me'}, {'cash': float('nan')}]:
        with pytest.raises(ValueError):
            store.save_report('run-1', report)
    assert store.load_report('run-1') is None


def test_errors_store_only_safe_type_names(tmp_path):
    store = new_store(tmp_path)
    request(store)
    store.record_error('run-1', 'execution', 'ValueError')
    store.record_error('run-1', 'execution', 'https://secret.example/?key=never-persist-me')
    with sqlite3.connect(tmp_path / 'agents.sqlite3') as connection:
        names = [row[0] for row in connection.execute('SELECT error_type FROM agent_errors ORDER BY id')]
    assert names == ['ValueError', 'Error']
    assert b'never-persist-me' not in (tmp_path / 'agents.sqlite3').read_bytes()


def test_report_is_immutable_after_completion(tmp_path):
    store = new_store(tmp_path)
    request(store)
    store.save_report('run-1', {'status': 'held'})
    store.save_report('run-1', {'status': 'held'})
    with pytest.raises(ValueError):
        store.save_report('run-1', {'status': 'executed'})
    assert store.load_report('run-1') == {'status': 'held'}


def test_concurrent_begin_run_cannot_overwrite_identity(tmp_path):
    cls = module_store()
    path = tmp_path / 'agents.sqlite3'
    cls(path)
    def claim(hash_value):
        try:
            cls(path).begin_run('contended', hash_value)
            return True
        except ValueError:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(claim, ['a' * 64, 'b' * 64]))
    assert sorted(result) == [False, True]


def execution_class():
    source = Path(__file__).resolve().parents[1] / 'app/services/mirofish/trading_agents/execution_agent.py'
    assert source.exists(), 'Paper execution agent has not been implemented'
    from app.services.mirofish.trading_agents.execution_agent import ExecutionAgent
    return ExecutionAgent


def approved(store, run='paper-1', *, portfolio=None, targets=None, quotes=None, candidates=None,
             decision='approved', mode='paper', as_of='2026-10-02', execution_date='2026-10-05',
             data_status='ready', approval_overrides=None, costs=None):
    symbols = ['005930', '000660', '042700']
    input_value = dict(as_of=as_of, account_id='paper-account',
        portfolio=portfolio if portfolio is not None else dict(cash=1000, positions={}),
        execution=dict(date=execution_date, quotes=quotes if quotes is not None else {
            symbol: dict(price=price, volume=100000, date=execution_date, source='synthetic_fixture')
            for symbol, price in zip(symbols, [10, 20, 30])}, cost_bps=5, slippage_bps=10, sell_tax_bps=0))
    if costs:
        input_value['execution'].update(costs)
    payload = dict(input=input_value)
    previous = create_message(run, 'request', payload)
    store.begin_run(run, previous.message_id)
    store.save_stage(run, 'request', previous.to_dict())
    payload['data'] = dict(status=data_status, ranked=[dict(symbol=s) for s in symbols], eligible_symbols=symbols)
    data_message = create_message(run, 'data', payload, previous.message_id)
    store.save_stage(run, 'data', data_message.to_dict())
    payload['quant'] = dict(qualified=[dict(symbol=s) for s in symbols],
        candidates=[dict(symbol=s) for s in (symbols if candidates is None else candidates)])
    quant_message = create_message(run, 'quant', payload, data_message.message_id)
    store.save_stage(run, 'quant', quant_message.to_dict())
    payload['risk'] = dict(status='approved', targets=targets if targets is not None else {s: 0.2 for s in symbols})
    risk_message = create_message(run, 'risk', payload, quant_message.message_id)
    store.save_stage(run, 'risk', risk_message.to_dict())
    payload['approval'] = dict(decision=decision, mode=mode, risk_message_id=risk_message.message_id,
        targets_sha256=digest(payload['risk']['targets']), account_id=input_value['account_id'],
        execution_date=execution_date, reason='synthetic_fixture')
    payload['approval'].update(approval_overrides or {})
    message = create_message(run, 'approval', payload, risk_message.message_id)
    store.save_stage(run, 'approval', message.to_dict())
    return message


def execute(store, message):
    return asyncio.run(execution_class()(store).handle(message))


def table_count(tmp_path, table):
    with sqlite3.connect(tmp_path / 'agents.sqlite3') as connection:
        return connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]


def test_paper_buy_caps_and_cost_ledger_reconcile(tmp_path):
    store = new_store(tmp_path)
    message = approved(store)
    result = execute(store, message)
    output = result.payload['execution']
    assert output['status'] == 'executed' and result.parent_id == message.message_id
    assert len(output['fills']) == 3 and all(fill['side'] == 'BUY' for fill in output['fills'])
    cash, positions = output['portfolio']['cash'], output['portfolio']['positions']
    quotes = message.payload['input']['execution']['quotes']
    nav = cash + sum(quantity * quotes[s]['price'] for s, quantity in positions.items())
    assert cash >= 0.4 * nav - 1e-9
    assert all(quantity * quotes[s]['price'] <= 0.2 * nav + 1e-9 for s, quantity in positions.items())
    assert cash == pytest.approx(1000 + sum(fill['cash_delta'] for fill in output['fills']))
    assert 1000 - nav == pytest.approx(sum(fill['fee'] + fill['tax'] + fill['slippage_amount'] for fill in output['fills']))
    assert table_count(tmp_path, 'paper_executions') == 1 and table_count(tmp_path, 'paper_fills') == 3
    assert AgentMessage.from_dict(store.load_stage('paper-1', 'execution')).message_id == result.message_id


def test_sell_oversized_position_before_buys_and_recheck_caps_after_fees(tmp_path):
    store = new_store(tmp_path)
    message = approved(store, portfolio=dict(cash=400, positions={'005930': 60}),
                       costs=dict(cost_bps=50, slippage_bps=30, sell_tax_bps=20))
    output = execute(store, message).payload['execution']
    assert output['status'] == 'executed' and output['fills'][0]['side'] == 'SELL'
    sells = [i for i, fill in enumerate(output['fills']) if fill['side'] == 'SELL']
    buys = [i for i, fill in enumerate(output['fills']) if fill['side'] == 'BUY']
    assert max(sells) < min(buys)
    cash, positions = output['portfolio']['cash'], output['portfolio']['positions']
    quotes = message.payload['input']['execution']['quotes']
    nav = cash + sum(quantity * quotes[s]['price'] for s, quantity in positions.items())
    assert cash >= 0.4 * nav - 1e-9
    assert all(quantity * quotes[s]['price'] <= 0.2 * nav + 1e-9 for s, quantity in positions.items())
    assert 1000 - nav == pytest.approx(sum(f['fee'] + f['tax'] + f['slippage_amount'] for f in output['fills']))
    assert all(f['tax'] == 0 for f in output['fills'] if f['side'] == 'BUY')


def test_same_run_replay_after_restart_returns_exact_fills_without_double_trade(tmp_path):
    store = new_store(tmp_path)
    message = approved(store)
    result = execute(store, message)
    restarted = module_store()(tmp_path / 'agents.sqlite3')
    replay = execute(restarted, message)
    assert replay.to_dict() == result.to_dict()
    assert table_count(tmp_path, 'paper_executions') == 1 and table_count(tmp_path, 'paper_fills') == 3


def test_different_run_same_account_day_is_duplicate_not_another_rebalance(tmp_path):
    store = new_store(tmp_path)
    first = execute(store, approved(store, 'first'))
    duplicate = execute(store, approved(store, 'second'))
    output = duplicate.payload['execution']
    assert output['status'] == 'duplicate_day' and output['fills'] == [] and output['daily_slot_reused']
    assert output['portfolio'] == first.payload['execution']['portfolio']
    assert table_count(tmp_path, 'paper_executions') == 1


def test_concurrent_different_runs_can_fill_daily_slot_only_once(tmp_path):
    store = new_store(tmp_path)
    messages = [approved(store, run) for run in ['race-a', 'race-b']]
    def process(message):
        instance = module_store()(tmp_path / 'agents.sqlite3')
        return execute(instance, message).payload['execution']['status']
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(process, messages))
    assert sorted(statuses) == ['duplicate_day', 'executed']
    assert table_count(tmp_path, 'paper_executions') == 1 and table_count(tmp_path, 'paper_fills') == 3


def test_stale_portfolio_on_later_day_is_rejected_without_reset(tmp_path):
    store = new_store(tmp_path)
    first = execute(store, approved(store, 'day-one'))
    stale = approved(store, 'day-two-stale', as_of='2026-10-05', execution_date='2026-10-06')
    with pytest.raises(ValueError):
        execute(store, stale)
    assert store.load_account('paper-account') == first.payload['execution']['portfolio']
    assert table_count(tmp_path, 'paper_executions') == 1
    valid = approved(store, 'day-two-valid', as_of='2026-10-05', execution_date='2026-10-06',
                     portfolio=json.loads(json.dumps(first.payload['execution']['portfolio'])))
    assert execute(store, valid).payload['execution']['status'] == 'executed'
    assert table_count(tmp_path, 'paper_executions') == 2


def test_transaction_failure_rolls_back_account_fills_slot_and_stage(tmp_path):
    store = new_store(tmp_path)
    message = approved(store)
    execution_class()
    with sqlite3.connect(tmp_path / 'agents.sqlite3') as connection:
        connection.execute("CREATE TRIGGER fail_paper_fill BEFORE INSERT ON paper_fills BEGIN SELECT RAISE(ABORT,'simulated persistence failure'); END")
    with pytest.raises(ValueError):
        execute(store, message)
    assert store.load_account('paper-account') is None
    assert store.load_stage('paper-1', 'execution') is None
    assert table_count(tmp_path, 'paper_executions') == table_count(tmp_path, 'paper_fills') == 0
    with sqlite3.connect(tmp_path / 'agents.sqlite3') as connection:
        connection.execute('DROP TRIGGER fail_paper_fill')
    assert execute(store, message).payload['execution']['status'] == 'executed'


@pytest.mark.parametrize('kind', ['approval_held', 'data_blocked', 'live_mode'])
def test_held_or_nonpaper_decision_cannot_create_account_or_orders(tmp_path, kind):
    store = new_store(tmp_path)
    options = {'approval_held': dict(decision='held'), 'data_blocked': dict(data_status='blocked'),
               'live_mode': dict(mode='live')}[kind]
    output = execute(store, approved(store, **options)).payload['execution']
    assert output['status'] == 'held' and output['fills'] == []
    assert output['portfolio'] == {'cash': 1000, 'positions': {}}
    assert store.load_account('paper-account') is None and table_count(tmp_path, 'paper_executions') == 0


@pytest.mark.parametrize('field,value', [('risk_message_id', 'b' * 64), ('targets_sha256', 'b' * 64),
                                        ('account_id', 'different-account'), ('execution_date', '2026-10-06')])
def test_approval_must_match_stored_risk_account_date_and_target_hash(tmp_path, field, value):
    store = new_store(tmp_path)
    message = approved(store, approval_overrides={field: value})
    with pytest.raises(ValueError):
        execute(store, message)
    assert table_count(tmp_path, 'paper_executions') == 0


def test_incoming_approval_must_be_exact_persisted_message(tmp_path):
    store = new_store(tmp_path)
    original = approved(store)
    payload = json.loads(json.dumps(original.payload))
    payload['approval']['reason'] = 'tampered'
    tampered = create_message(original.run_id, 'approval', payload, original.parent_id)
    with pytest.raises(ValueError):
        execute(store, tampered)
    assert table_count(tmp_path, 'paper_executions') == 0


@pytest.mark.parametrize('targets', [{'005930': 0.21}, {'005930': -0.1}, {'005930': True},
                                      {'999990': 0.1}])
def test_execution_rechecks_target_caps_and_eligibility(tmp_path, targets):
    store = new_store(tmp_path)
    output = execute(store, approved(store, targets=targets)).payload['execution']
    assert output['status'] == 'held' and output['fills'] == []
    assert table_count(tmp_path, 'paper_executions') == 0


@pytest.mark.parametrize('field,value', [('volume', 0), ('price', 0), ('date', '2026-10-02'), ('source', '')])
def test_invalid_or_stale_quote_is_held_without_partial_fills(tmp_path, field, value):
    store = new_store(tmp_path)
    quotes = {s: dict(price=10, volume=100, date='2026-10-05', source='fixture') for s in ['005930', '000660', '042700']}
    quotes['005930'][field] = value
    output = execute(store, approved(store, quotes=quotes)).payload['execution']
    assert output['status'] == 'held' and output['fills'] == []
    assert table_count(tmp_path, 'paper_executions') == 0


def test_unknown_held_stock_quote_is_required_even_for_liquidation(tmp_path):
    store = new_store(tmp_path)
    output = execute(store, approved(store, targets={}, portfolio=dict(cash=900, positions={'000010': 10}))).payload['execution']
    assert output['status'] == 'held' and output['fills'] == []
    assert output['portfolio']['positions'] == {'000010': 10}


def test_verified_loss_of_qualification_can_liquidate_outside_cohort_with_no_new_buy(tmp_path):
    store = new_store(tmp_path)
    quotes = {'000010': dict(price=10, volume=100, date='2026-10-05', source='fixture')}
    output = execute(store, approved(store, targets={}, quotes=quotes, portfolio=dict(cash=900, positions={'000010': 10}))).payload['execution']
    assert output['status'] == 'executed' and len(output['fills']) == 1
    assert output['fills'][0]['side'] == 'SELL' and output['portfolio']['positions'] == {}
    assert output['portfolio']['cash'] == pytest.approx(999.85005)


def test_only_new_position_requires_fresh_candidate(tmp_path):
    store = new_store(tmp_path)
    held = execute(store, approved(store, 'no-fresh', targets={'005930': 0.2}, candidates=[])).payload['execution']
    assert held['status'] == 'held' and held['fills'] == []
    existing = execute(store, approved(store, 'existing', targets={'005930': 0.2}, candidates=[],
                                      portfolio=dict(cash=900, positions={'005930': 10}))).payload['execution']
    assert existing['status'] == 'executed'


@pytest.mark.parametrize('execution_date', ['2026-10-02', '2026-10-01', '2026-02-30'])
def test_execution_requires_valid_date_strictly_after_observation(tmp_path, execution_date):
    store = new_store(tmp_path)
    output = execute(store, approved(store, execution_date=execution_date)).payload['execution']
    assert output['status'] == 'held' and output['fills'] == []
    assert table_count(tmp_path, 'paper_executions') == 0


def test_request_stage_digest_must_match_registered_run_identity(tmp_path):
    store = new_store(tmp_path)
    message = create_message('mismatch', 'request', {'input': {'as_of': '2026-10-02'}})
    store.begin_run('mismatch', 'a' * 64)
    with pytest.raises(ValueError):
        store.save_stage('mismatch', 'request', message.to_dict())
    assert store.load_stage('mismatch', 'request') is None


def test_child_stage_requires_a_persisted_predecessor(tmp_path):
    store = new_store(tmp_path)
    store.begin_run('orphan', 'a' * 64)
    risk = create_message('orphan', 'risk', {'input': {}, 'risk': {'targets': {}}}, 'missing-quant')
    with pytest.raises(ValueError):
        store.save_stage('orphan', 'risk', risk.to_dict())
    assert store.load_stage('orphan', 'risk') is None


def test_child_stage_cannot_rewrite_stored_upstream_evidence(tmp_path):
    store = new_store(tmp_path)
    previous = request(store)
    data = create_message('run-1', 'data', dict(previous.payload, data={'status': 'blocked'}), previous.message_id)
    store.save_stage('run-1', 'data', data.to_dict())
    rewritten = create_message('run-1', 'quant', dict(previous.payload, data={'status': 'ready'}, quant={}), data.message_id)
    with pytest.raises(ValueError):
        store.save_stage('run-1', 'quant', rewritten.to_dict())
    assert store.load_stage('run-1', 'quant') is None


def raw_stage(store, message):
    # Simulate an artifact produced by an older version; no public write guard.
    with sqlite3.connect(store.path) as connection:
        connection.execute('INSERT INTO agent_stages(run_id,stage,message_id,message_json) VALUES(?,?,?,?)',
            (message.run_id, message.stage, message.message_id,
             json.dumps(message.to_dict(), sort_keys=True, separators=(',', ':'), ensure_ascii=False)))


def test_execution_independently_rejects_legacy_orphan_approval_chain(tmp_path):
    cls = module_store()
    seed = cls(tmp_path / 'seed.sqlite3')
    original = approved(seed, 'orphan')
    base = json.loads(json.dumps(original.payload))
    store = new_store(tmp_path)
    store.begin_run('orphan', seed.load_stage('orphan', 'request')['message_id'])
    risk = create_message('orphan', 'risk', {k: base[k] for k in ('input', 'data', 'quant', 'risk')}, 'missing-quant')
    base['approval']['risk_message_id'] = risk.message_id
    approval = create_message('orphan', 'approval', base, risk.message_id)
    raw_stage(store, risk)
    raw_stage(store, approval)
    with pytest.raises(ValueError):
        execute(store, approval)
    assert store.load_account('paper-account') is None and table_count(tmp_path, 'paper_fills') == 0


def test_execution_independently_rejects_legacy_rewritten_data_chain(tmp_path):
    cls = module_store()
    seed = cls(tmp_path / 'seed.sqlite3')
    original = approved(seed, 'drift')
    base = json.loads(json.dumps(original.payload))
    store = new_store(tmp_path)
    initial = AgentMessage.from_dict(seed.load_stage('drift', 'request'))
    store.begin_run('drift', initial.message_id)
    raw_stage(store, initial)
    blocked_data = create_message('drift', 'data', dict(input=base['input'], data=dict(base['data'], status='blocked')),
                                  initial.message_id)
    raw_stage(store, blocked_data)
    quant = create_message('drift', 'quant', {k: base[k] for k in ('input', 'data', 'quant')}, blocked_data.message_id)
    raw_stage(store, quant)
    risk = create_message('drift', 'risk', {k: base[k] for k in ('input', 'data', 'quant', 'risk')}, quant.message_id)
    raw_stage(store, risk)
    base['approval']['risk_message_id'] = risk.message_id
    approval = create_message('drift', 'approval', base, risk.message_id)
    raw_stage(store, approval)
    with pytest.raises(ValueError):
        execute(store, approval)
    assert store.load_account('paper-account') is None and table_count(tmp_path, 'paper_fills') == 0


def test_past_duplicate_returns_that_days_portfolio_without_future_ledger_leak(tmp_path):
    store = new_store(tmp_path)
    first = execute(store, approved(store, 'first'))
    first_portfolio = json.loads(json.dumps(first.payload['execution']['portfolio']))
    second = execute(store, approved(store, 'second', portfolio=first_portfolio, targets={},
                                    as_of='2026-10-05', execution_date='2026-10-06'))
    assert second.payload['execution']['portfolio'] != first_portfolio
    duplicate = execute(store, approved(store, 'past-duplicate'))
    assert duplicate.payload['execution']['status'] == 'duplicate_day'
    assert duplicate.payload['execution']['portfolio'] == first_portfolio
    assert store.load_account('paper-account') == second.payload['execution']['portfolio']
    assert table_count(tmp_path, 'paper_executions') == 2

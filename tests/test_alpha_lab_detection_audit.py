"""Offline comparison contracts: a frozen schedule, real fills, honest coverage."""
from datetime import date, timedelta
import importlib.util
import json
from pathlib import Path

import pytest


def module():
    path = Path(__file__).resolve().parents[1]/'scripts'/'audit_alpha_lab_detection.py'
    assert path.is_file(), 'the saved-input-only audit CLI must exist'
    spec = importlib.util.spec_from_file_location('alpha_detection_audit', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def days(count=1512):
    start = date(2020, 1, 1)
    return [(start+timedelta(days=index)).isoformat() for index in range(count)]


def bars(calendar):
    return [dict(symbol='005930', date=day, open=100., high=101., low=99., close=100., volume=1000.) for day in calendar]


def test_cli_declares_explicit_read_only_input_and_private_output_defaults():
    args = module().build_parser().parse_args([])
    assert args.input_root.name == 'alpha_lab'
    assert args.output_dir.name == 'alpha_lab_detection_audit'
    assert not hasattr(args, 'refresh') and not hasattr(args, 'publish')
    actual = module().build_parser().parse_args(['--input-root', 'source', '--output-dir', 'report'])
    assert actual.input_root == Path('source') and actual.output_dir == Path('report')


def test_fixed_252_window_uses_four_63_session_blocks_and_twelve_signals():
    mod = module(); calendar = days(); schedule = mod.make_schedule(calendar)
    window = calendar[-252:]
    assert schedule['start'] == window[0] and schedule['end'] == window[-1]
    assert schedule['signal_sessions'] == [window[block*63+offset] for block in range(4) for offset in (0, 20, 40)]
    assert [(row['start'], row['end']) for row in schedule['blocks']] == [(window[i*63], window[i*63+62]) for i in range(4)]
    assert len(schedule['signal_sessions']) == 12


@pytest.mark.parametrize('calendar', [days(1260), days(1512)[:-1]+[days(1512)[-2]], days(1512)[::-1]])
def test_schedule_rejects_short_or_noncanonical_history(calendar):
    with pytest.raises(ValueError):
        module().make_schedule(calendar)


def test_empty_slots_are_cash_not_missing_observations():
    mod = module(); calendar = days(30)
    result = mod.evaluate_slots({'candidates': []}, {'005930': bars(calendar)}, calendar[5], calendar)
    assert result['coverage'] == dict(selected=0, cash=3, closed=0, pending=0, unfilled=0, unobserved=0)
    assert [row['net_return'] for row in result['slots']] == [0., 0., 0.]
    assert result['mean_of_three_slots'] == 0. and result['stress_mean_of_three_slots'] == 0.


def test_closed_next_open_trade_and_cost_stress_share_identical_fill_prices():
    mod = module(); calendar = days(40); rows = bars(calendar)
    result = mod.evaluate_slots({'candidates': [dict(symbol='005930', strategy_id='momentum')]}, {'005930': rows}, calendar[15], calendar)
    trade = result['slots'][0]
    assert trade['status'] == 'closed' and trade['entry_date'] == calendar[16]
    assert trade['entry_price'] == 100. and trade['exit_price'] == 100.
    assert trade['net_return'] == pytest.approx(100*.997/(100*1.001)-1)
    assert trade['stress_net_return'] == pytest.approx(100*.994/(100*1.002)-1)
    assert result['mean_of_three_slots'] == pytest.approx(trade['net_return']/3)


def test_pending_and_missing_union_quote_are_not_zero_return_winners():
    mod = module(); calendar = days(30); rows = bars(calendar)
    board = {'candidates': [dict(symbol='005930', strategy_id='momentum')]}
    pending = mod.evaluate_slots(board, {'005930': rows}, calendar[-2], calendar)
    assert pending['coverage']['pending'] == 1
    assert pending['mean_of_three_slots'] is None
    assert pending['slots'][0]['net_return'] is None
    sparse = [row for row in rows if row['date'] != calendar[6]]
    missing = mod.evaluate_slots(board, {'005930': sparse}, calendar[5], calendar)
    assert missing['coverage']['unobserved'] == 1
    assert missing['slots'][0]['reason'] == 'missing_next_union_quote'


def test_protocol_is_sealed_before_work_and_rejects_changed_inputs_or_code(tmp_path):
    mod = module(); protocol = {'schema_version': 1, 'input_fingerprint': 'a'*64,
                              'code_hashes': {'detector': 'b'*64}, 'schedule': mod.make_schedule(days())}
    first = mod.seal_protocol(tmp_path, protocol)
    assert (tmp_path/'protocol.json').is_file()
    assert mod.seal_protocol(tmp_path, protocol) == first
    changed = dict(protocol, input_fingerprint='c'*64)
    with pytest.raises(ValueError, match='protocol_mismatch'):
        mod.seal_protocol(tmp_path, changed)
    changed = dict(protocol, code_hashes={'detector': 'c'*64})
    with pytest.raises(ValueError, match='protocol_mismatch'):
        mod.seal_protocol(tmp_path, changed)


def test_portfolio_report_separates_continuous_account_from_three_unit_slots():
    mod = module(); calendar = days(40); prices = {'005930': bars(calendar)}
    decisions = {calendar[15]: [dict(symbol='005930', weight=.05)]}
    portfolio = mod.evaluate_portfolio(prices, decisions, calendar[0], calendar[-1])
    assert portfolio['basis'] == 'continuous_account_equity_with_max_three_5pct_positions_and_cash'
    assert portfolio['normal']['closed_trades'] == portfolio['stress']['closed_trades'] == 1
    assert portfolio['same_fill_identity'] is True
    assert portfolio['normal']['net_total_return'] > -.001
    assert portfolio['stress']['net_total_return'] < portfolio['normal']['net_total_return'] < 0
    assert portfolio['allocation_limits']['position_cap'] == .05
    json.dumps(portfolio, allow_nan=False)


def test_each_block_counts_only_its_three_frozen_signal_sessions():
    mod = module(); calendar = days(); schedule = mod.make_schedule(calendar)
    empty = mod.evaluate_slots({'candidates': []}, {}, calendar[0], calendar)
    rows = [dict(signal_session=day, policies={'v2': dict(slot_evaluation=empty, discovery={'audit': []})})
            for day in schedule['signal_sessions']]
    blocks = mod.summarize_blocks(rows, schedule, 'v2')
    assert len(blocks) == 4
    assert all(block['summary']['decisions'] == 3 and block['summary']['coverage']['cash'] == 9 for block in blocks)
    assert [block['start'] for block in blocks] == [calendar[-252+63*index] for index in range(4)]


def test_research_ranking_sees_only_signal_prefix_and_preserves_actual_source_time(monkeypatch):
    mod = module(); calendar = days(); signal = calendar[-100]; seen = []
    def discover(prices, **kwargs):
        assert kwargs['as_of'] == signal and kwargs['candidate_limit'] == 100
        assert all(row['date'] <= signal for rows in prices.values() for row in rows)
        assert kwargs['reference_calendar'][-1] == signal
        return dict(policy_version='test', selection_basis='test', latest_session=signal,
                    inspected_count=1, eligible_count=0, active_setup_count=0,
                    candidates=[], audit=[], diagnostics={}, reasons=[], warnings=[])
    def build(scan, prices, report, **kwargs):
        seen.append(report['provenance']['captured_at'])
        assert prices['005930'][-1]['date'] == signal
        return {'candidates': []}
    monkeypatch.setattr(mod, 'discover_opportunities', discover)
    monkeypatch.setattr(mod, 'discover_opportunities_v2', discover)
    monkeypatch.setattr(mod, 'build_opportunity_board', build)
    monkeypatch.setattr(mod, 'build_opportunity_board_v2', build)
    actual = '2026-10-19T11:30:00Z'
    inputs = dict(prices_by_symbol={'005930': bars(calendar)}, names={}, input_fingerprint='a'*64,
                  provenance={'captured_at': actual}, universe={}, diagnostics={})
    result = mod._compare_at(inputs, calendar, signal)
    assert seen == [actual, actual]
    assert result['signal_session'] == signal


def test_completed_decision_checkpoints_are_reused_instead_of_rescanning(tmp_path, monkeypatch):
    mod = module(); calendar = days(); calls = []
    from app.services.mirofish.alpha_lab import service
    files = [tmp_path/f'source{index}.json' for index in range(3)]
    for path in files:
        path.write_text('{}', encoding='utf-8')
    monkeypatch.setattr(service, 'resolve_inputs', lambda root: files)
    inputs = dict(prices_by_symbol={'005930': bars(calendar)}, names={}, input_fingerprint='a'*64,
                  provenance={}, universe={}, diagnostics={})
    monkeypatch.setattr(mod, 'load_inputs', lambda *args, **kwargs: inputs)
    def compare(inputs, calendar, signal):
        calls.append(signal)
        policy = dict(discovery={'audit': []}, board={'candidates': []},
                      slot_evaluation=mod.evaluate_slots({'candidates': []}, {}, signal, calendar))
        return dict(signal_session=signal, policies={'v1': policy, 'v2': policy})
    monkeypatch.setattr(mod, '_compare_at', compare)
    output = tmp_path/'private-report'
    first = mod.run_audit(tmp_path/'read-only-source', output)
    assert len(calls) == 13
    (output/'result.json').unlink()
    calls.clear()
    second = mod.run_audit(tmp_path/'read-only-source', output)
    assert calls == [] and first['protocol_hash'] == second['protocol_hash']
    assert second['source']['historical_revision_coverage']['status'] == 'unavailable'

"""One frozen retrospective v1/v2 comparison from saved inputs, with no publication.

Defaults read data/alpha_lab and write data/reviews/alpha_lab_detection_audit.
This CLI performs no acquisition, API call, Telegram send, order or source write.
It reports current-cohort/vintage bias; historical prefixes are not untouched OOS.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
from statistics import fmean
import sys
import time

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from app.services.mirofish.alpha_lab.data import file_hash, load_inputs
from app.services.mirofish.alpha_lab.discovery import discover_opportunities
from app.services.mirofish.alpha_lab.discovery_v2 import discover_opportunities_v2
from app.services.mirofish.alpha_lab.decision_engine import build_opportunity_board, build_opportunity_board_v2
from app.services.mirofish.alpha_lab.execution import ExecutionPolicy, simulate_trade, simulate_portfolio

KST = timezone(timedelta(hours=9))
CODE_PATHS = ('scripts/audit_alpha_lab_detection.py',
    'app/services/mirofish/alpha_lab/discovery.py', 'app/services/mirofish/alpha_lab/discovery_v2.py',
    'app/services/mirofish/alpha_lab/decision_engine.py', 'app/services/mirofish/alpha_lab/execution.py',
    'app/services/mirofish/alpha_lab/features.py', 'app/services/mirofish/alpha_lab/risk.py',
    'app/services/mirofish/alpha_lab/data.py', 'app/services/mirofish/kelly_position.py')
LIMITATIONS = ['retrospective_current_financial_quality_cohort_not_point_in_time_universe',
    'saved_prices_not_proven_historical_vintages', 'corporate_action_adjustment_not_independently_certified',
    'not_untouched_out_of_sample_or_calibrated_future_probability',
    'hypothetical_next_session_open_fills_not_executable_quote_or_order_approval',
    'unit_slot_returns_are_not_continuous_account_returns',
    'no_threshold_tuning_no_profit_guarantee_no_live_orders']


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-root', type=Path, default=REPO/'data'/'alpha_lab',
                        help='Read-only saved AlphaLab input root (default: data/alpha_lab).')
    parser.add_argument('--output-dir', type=Path, default=REPO/'data'/'reviews'/'alpha_lab_detection_audit',
                        help='Private immutable comparison output directory; never a service root.')
    return parser


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def make_schedule(calendar):
    if (not isinstance(calendar, list) or len(calendar) < 1511
            or any(not isinstance(day, str) or date.fromisoformat(day).isoformat() != day for day in calendar)
            or any(left >= right for left, right in zip(calendar, calendar[1:]))):
        raise ValueError('audit_requires_1260_history_at_first_of_last252_sessions')
    window = calendar[-252:]
    blocks = [dict(block=index+1, start=window[index*63], end=window[index*63+62],
                   signals=[window[index*63+offset] for offset in (0, 20, 40)]) for index in range(4)]
    return dict(start=window[0], end=window[-1], sessions=252, block_sessions=63,
                signal_offsets=[0, 20, 40], blocks=blocks,
                signal_sessions=[day for block in blocks for day in block['signals']])


def seal_protocol(output_dir, protocol):
    output_dir = Path(output_dir); output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir/'protocol.json'
    protocol_hash = _hash(protocol)
    if path.exists():
        saved = json.loads(path.read_text(encoding='utf-8'))
        if (saved.get('protocol_hash') != protocol_hash
                or _hash({key: value for key, value in saved.items() if key not in ('protocol_hash', 'declared_at')}) != protocol_hash):
            raise ValueError('audit_protocol_mismatch_new_version_required')
        return saved
    sealed = dict(protocol, protocol_hash=protocol_hash, declared_at=datetime.now(KST).isoformat())
    with path.open('x', encoding='utf-8') as handle:
        json.dump(sealed, handle, ensure_ascii=False, indent=2, allow_nan=False)
    return sealed


def evaluate_slots(board, prices_by_symbol, signal, calendar, policy=None):
    policy = policy or ExecutionPolicy()
    slots, coverage = [], dict(selected=0, cash=0, closed=0, pending=0, unfilled=0, unobserved=0)
    global_index = {day: index for index, day in enumerate(calendar)}
    for candidate in board.get('candidates', [])[:3]:
        symbol = candidate['symbol']; rows = prices_by_symbol.get(symbol, [])
        local_index = {row['date']: index for index, row in enumerate(rows)}
        at = local_index.get(signal); global_at = global_index[signal]
        slot = dict(symbol=symbol, strategy_id=candidate.get('strategy_id'), signal_date=signal,
                    status='unobserved', reason=None, net_return=None, stress_net_return=None)
        coverage['selected'] += 1
        if at is None:
            slot['reason'] = 'missing_signal_quote'
        elif global_at+1 >= len(calendar):
            slot.update(status='pending', reason='next_session_not_observed')
        elif at+1 >= len(rows) or rows[at+1]['date'] != calendar[global_at+1]:
            slot['reason'] = 'missing_next_union_quote'
        else:
            trade = simulate_trade(rows, at, policy)
            if trade is None:
                slot.update(status='unfilled', reason='next_session_order_unfilled', net_return=0., stress_net_return=0.)
            elif trade['status'] != 'closed':
                slot.update(trade, reason='outcome_not_matured', status='pending')
            else:
                exit_at, exit_global = local_index[trade['exit_date']], global_index[trade['exit_date']]
                if [row['date'] for row in rows[at+1:exit_at+1]] != calendar[global_at+1:exit_global+1]:
                    slot['reason'] = 'missing_holding_interval'
                else:
                    stress = replace(policy, fee_bps=2*policy.fee_bps, slippage_bps=2*policy.slippage_bps,
                                     sell_tax_bps=2*policy.sell_tax_bps)
                    slot.update(trade, reason='same_observed_fill_prices_costs_only_stress',
                        stress_net_return=trade['exit_price']*(1-stress.exit_cost)/(trade['entry_price']*(1+stress.entry_cost))-1)
        coverage[slot['status']] += 1
        slots.append(slot)
    while len(slots) < 3:
        slots.append(dict(symbol=None, status='cash', reason='empty_slot_cash', net_return=0., stress_net_return=0.))
        coverage['cash'] += 1
    complete = all(row['net_return'] is not None for row in slots)
    return dict(coverage=coverage, slots=slots,
        mean_of_three_slots=fmean(row['net_return'] for row in slots) if complete else None,
        stress_mean_of_three_slots=fmean(row['stress_net_return'] for row in slots) if complete else None,
        basis='equal_weight_three_unit_notional_slots_empty_cash_not_account_return')


def _portfolio_summary(result, start, end):
    curve = [row for row in result['equity'] if start <= row['date'] <= end]
    trades = result['trades']; closed = [row for row in trades if row['status'] == 'closed']
    peak, drawdown = 1., 0.
    for row in curve:
        peak = max(peak, row['equity']); drawdown = min(drawdown, row['equity']/peak-1)
    return dict(net_total_return=curve[-1]['equity']-1 if curve else 0., max_drawdown=drawdown,
        closed_trades=len(closed), pending_trades=len(result['open_positions']),
        final_cash=curve[-1]['cash'] if curve else 1., final_equity=curve[-1]['equity'] if curve else 1.,
        fills=result['fills'], trades=trades, equity=curve)


def evaluate_portfolio(prices_by_symbol, decisions, start, end):
    normal = ExecutionPolicy()
    stress = replace(normal, fee_bps=2*normal.fee_bps, slippage_bps=2*normal.slippage_bps,
                     sell_tax_bps=2*normal.sell_tax_bps)
    first = simulate_portfolio(prices_by_symbol, decisions, normal, max_positions=3, position_cap=.05, cash_buffer=.4)
    doubled = simulate_portfolio(prices_by_symbol, decisions, stress, max_positions=3, position_cap=.05, cash_buffer=.4)
    def identities(result):
        return [(row['date'], row['symbol'], row['side'], row['price'], row['reason']) for row in result['fills']]
    if identities(first) != identities(doubled):
        raise ValueError('cost_stress_changed_fill_identity')
    return dict(basis='continuous_account_equity_with_max_three_5pct_positions_and_cash',
        allocation_limits=dict(position_cap=.05, max_positions=3, cash_buffer=.4, reference_weight=.05),
        same_fill_identity=True, normal=_portfolio_summary(first, start, end), stress=_portfolio_summary(doubled, start, end))


def _compact_discovery(scan):
    audits = []
    for row in scan['audit']:
        value = {key: row.get(key) for key in ('symbol', 'name', 'strategy_id', 'setup_active', 'selected', 'eligible', 'reasons', 'current_setup')}
        for phase in ('calibration', 'confirmation', 'recent'):
            value[phase] = (row.get(phase) or {}).get('summary')
        audits.append(value)
    return dict(policy_version=scan['policy_version'], selection_basis=scan['selection_basis'],
        latest_session=scan['latest_session'], inspected_count=scan['inspected_count'], eligible_count=scan['eligible_count'],
        active_setup_count=scan['active_setup_count'], candidates=scan['candidates'], audit=audits,
        diagnostics=scan['diagnostics'], reasons=scan['reasons'], warnings=scan['warnings'])


def _compare_at(inputs, calendar, signal):
    prices = inputs['prices_by_symbol']
    observed = {symbol: [row for row in rows if row['date'] <= signal] for symbol, rows in prices.items()}
    observed = {symbol: rows for symbol, rows in observed.items() if rows}
    prefix_calendar = [day for day in calendar if day <= signal]
    # Preserve the real capture/scope timestamps. Source holds are expected for
    # old prefixes; never fabricate point-in-time source provenance for a replay.
    report = dict(schema_version=1, mode='research', latest_session=signal,
        decision_at=signal+'T09:45:00Z', input_fingerprint=_hash(dict(snapshot=inputs['input_fingerprint'], signal=signal)),
        provenance=inputs['provenance'], universe=inputs['universe'], diagnostics=inputs['diagnostics'])
    results = {}
    for version, discover, build in (('v1', discover_opportunities, build_opportunity_board),
                                    ('v2', discover_opportunities_v2, build_opportunity_board_v2)):
        started = time.monotonic()
        scan = discover(observed, names=inputs['names'], as_of=signal, reference_calendar=prefix_calendar, candidate_limit=100)
        snapshot = dict(report, opportunity_scan=dict(status='ready', audit_hash=_hash(scan), reasons=[]))
        board = build(scan, observed, snapshot, now=snapshot['decision_at'])
        results[version] = dict(discovery=_compact_discovery(scan), board=board,
            slot_evaluation=evaluate_slots(board, prices, signal, calendar), elapsed_seconds=round(time.monotonic()-started, 3))
    return dict(signal_session=signal, policies=results)


def _aggregate(decisions, version):
    evaluations = [row['policies'][version]['slot_evaluation'] for row in decisions]
    coverage = Counter()
    for row in evaluations:
        coverage.update(row['coverage'])
    values = [row['mean_of_three_slots'] for row in evaluations if row['mean_of_three_slots'] is not None]
    stress = [row['stress_mean_of_three_slots'] for row in evaluations if row['stress_mean_of_three_slots'] is not None]
    reject = Counter(reason for row in decisions for audit in row['policies'][version]['discovery']['audit']
                     for reason in audit.get('reasons', []))
    closed = [slot for row in evaluations for slot in row['slots'] if slot['status'] == 'closed']
    return dict(decisions=len(evaluations), three_slot_opportunities=3*len(evaluations), coverage=dict(coverage),
        completed_slot_batches=len(values), pending_or_unobserved_batches=len(evaluations)-len(values),
        mean_three_slot_net_return=fmean(values) if values else None,
        mean_three_slot_stress_net_return=fmean(stress) if stress else None,
        closed_selected_mean_net_return=fmean(row['net_return'] for row in closed) if closed else None,
        closed_selected_win_rate=sum(row['net_return'] > 0 for row in closed)/len(closed) if closed else None,
        rejection_reason_counts=dict(reject), basis='decision_slots_not_continuous_account_equity')


def summarize_blocks(comparisons, schedule, version):
    return [dict(block=block['block'], start=block['start'], end=block['end'],
                 summary=_aggregate([row for row in comparisons if row['signal_session'] in block['signals']], version))
            for block in schedule['blocks']]


def run_audit(input_root, output_dir):
    # Importing this read-only resolver neither creates an app nor scans sources.
    from app.services.mirofish.alpha_lab.service import resolve_inputs
    input_root, output_dir = Path(input_root).resolve(), Path(output_dir).resolve()
    if output_dir == input_root or output_dir.is_relative_to(input_root):
        raise ValueError('audit_output_must_be_separate_from_input_root')
    paths = resolve_inputs(input_root)
    inputs = load_inputs(*paths, as_of=datetime.now(KST).date().isoformat())
    calendar = sorted({row['date'] for rows in inputs['prices_by_symbol'].values() for row in rows})
    schedule = make_schedule(calendar)
    protocol = dict(schema_version=1, policy='alpha-detection-v1-v2-retrospective-252-fixed-v1',
        input_fingerprint=inputs['input_fingerprint'], source_hashes={str(i): file_hash(path) for i, path in enumerate(paths)},
        code_hashes={path: file_hash(REPO/path) for path in CODE_PATHS}, schedule=schedule,
        policies=['quality-setup-opportunity-v1', 'quality-setup-opportunity-v2'],
        universe='entire_saved_current_top100_financial_quality_cohort',
        execution=asdict(ExecutionPolicy()), cost_stress_multiplier=2., candidate_limit=100,
        portfolio=dict(max_positions=3, position_cap=.05, cash_buffer=.4, decision_weight=.05),
        vintage_and_revision_coverage='unavailable_no_historical_saved_first_decision_hashes',
        source_bias=LIMITATIONS)
    sealed = seal_protocol(output_dir, protocol)
    result_path = output_dir/'result.json'
    if result_path.exists():
        existing = json.loads(result_path.read_text(encoding='utf-8'))
        if existing.get('protocol_hash') != sealed['protocol_hash']:
            raise ValueError('audit_result_protocol_mismatch')
        return existing
    all_rows = {}
    for index, signal in enumerate([*schedule['signal_sessions'], calendar[-1]]):
        checkpoint = output_dir/'decisions'/f'{signal}.json'
        if checkpoint.exists():
            row = json.loads(checkpoint.read_text(encoding='utf-8'))
            if row.get('protocol_hash') != sealed['protocol_hash'] or row.get('signal_session') != signal:
                raise ValueError('audit_checkpoint_protocol_mismatch')
        else:
            row = dict(_compare_at(inputs, calendar, signal), protocol_hash=sealed['protocol_hash'])
            _write(checkpoint, row)
        all_rows[signal] = row
        print(json.dumps(dict(stage='fixed_decision', complete=index+1, total=13, signal_session=signal,
            selected={version: len(row['policies'][version]['board']['candidates']) for version in ('v1', 'v2')})), flush=True)
    comparisons = [all_rows[day] for day in schedule['signal_sessions']]
    policies = {}
    for version in ('v1', 'v2'):
        decisions = {row['signal_session']: [dict(symbol=candidate['symbol'], weight=.05)
            for candidate in row['policies'][version]['board']['candidates']] for row in comparisons}
        policies[version] = dict(slots=_aggregate(comparisons, version), blocks=summarize_blocks(comparisons, schedule, version),
            portfolio=evaluate_portfolio(inputs['prices_by_symbol'], decisions, schedule['start'], schedule['end']))
    result = dict(schema_version=1, status='observed', protocol_hash=sealed['protocol_hash'],
        generated_at=datetime.now(KST).isoformat(), schedule=schedule, source=dict(
            input_fingerprint=inputs['input_fingerprint'], provenance=inputs['provenance'],
            universe=inputs['universe'], diagnostics=inputs['diagnostics'],
            historical_revision_coverage=dict(status='unavailable', checked=0,
                reason='single_current_snapshot_cannot_establish_historical_revision_or_vintage_truth')),
        policies=policies, latest=all_rows[calendar[-1]], decisions=comparisons,
        limitations=LIMITATIONS, approval=dict(approved_exposure=0., live_orders=False),
        interpretation='one_frozen_retrospective_diagnostic_not_strategy_promotion_or_profit_claim')
    _write(result_path, result)
    return result


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        result = run_audit(args.input_root, args.output_dir)
        print(json.dumps(dict(status=result['status'], protocol_hash=result['protocol_hash'],
            latest_session=result['schedule']['end'],
            policies={version: dict(slots=result['policies'][version]['slots'],
                account_net=result['policies'][version]['portfolio']['normal']['net_total_return'],
                stress_account_net=result['policies'][version]['portfolio']['stress']['net_total_return'])
                for version in ('v1', 'v2')}), ensure_ascii=False), flush=True)
        return 0
    except (OSError, ValueError, KeyError, TypeError):
        print(json.dumps(dict(status='failed', reason='saved_input_audit_contract_failed_no_source_or_policy_mutated')), flush=True)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

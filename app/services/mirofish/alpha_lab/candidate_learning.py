"""Experimental formation-only context inference, separate from failed v3.

The unconditional v3 formation/confirmation results remain diagnostic controls.
They are not this model's holdout results. A fixed nearest-neighbor hypothesis
uses causal formation events from other symbols and ten-session block means;
only future frozen decisions can validate this new model. No I/O, search over
thresholds, broker access or order approval occurs here.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict
import math
from statistics import fmean, pstdev

from . import candidate_detection as v3
from .candidate_execution import build_candidate_reference_plan
from .execution import ExecutionPolicy

POLICY_VERSION = 'contextual-candidates-v4'
MODEL_NAME = 'causal-context-neighbors-v1'
FEATURES = ('return20', 'momentum60', 'relative_return20', 'extension_sma20',
            'extension_sma60', 'prior_high_proximity', 'volume_ratio', 'cohort_median_return20')
NEIGHBORS, MIN_EVENTS, MIN_SYMBOLS, MIN_BLOCKS = 60, 30, 5, 5
PRIOR_BLOCKS = 5


def _vector(item):
    return (item['return20'], item['momentum60'], item['relative_return20'],
            item['close']/item['sma20']-1, item['close']/item['sma60']-1,
            item['prior_high_proximity']-1, item['volume_ratio'], item['cohort_median_return20'])


def _block_returns(events):
    blocks = defaultdict(list)
    for event in events:
        blocks[event['block']].append(event)
    return [dict(block=block, samples=len(values), net_return=fmean(row['net_return'] for row in values),
                 stress_net_return=fmean(row['stress_net_return'] for row in values))
            for block, values in sorted(blocks.items())]


def _estimate(events, *, prior_net, prior_stress):
    """Shrink equal-weight local block means toward formation-only block means."""
    blocks = _block_returns(events)
    net = fmean(block['net_return'] for block in blocks) if blocks else None
    stress = fmean(block['stress_net_return'] for block in blocks) if blocks else None
    weight = len(blocks)/(len(blocks)+PRIOR_BLOCKS)
    return dict(samples=len(events), wins=sum(row['net_return'] > 0 for row in events),
                win_rate=sum(row['net_return'] > 0 for row in events)/len(events) if events else None,
                block_count=len(blocks), unique_symbols=len({row['symbol'] for row in events}),
                mean_net_return=net, stress_mean_net_return=stress,
                expected_net_return=prior_net+weight*(net-prior_net) if blocks else None,
                expected_stress_net_return=prior_stress+weight*(stress-prior_stress) if blocks else None)


def _context_reasons(estimate):
    reasons = []
    for key, minimum, reason in (('samples', MIN_EVENTS, 'insufficient_context_events'),
                                  ('unique_symbols', MIN_SYMBOLS, 'insufficient_context_symbols'),
                                  ('block_count', MIN_BLOCKS, 'insufficient_context_blocks')):
        if estimate[key] < minimum:
            reasons.append(reason)
    for key in ('mean_net_return', 'stress_mean_net_return', 'expected_net_return', 'expected_stress_net_return'):
        if estimate[key] is None or estimate[key] <= 0:
            reasons.append('nonpositive_'+key)
    return reasons


def _scales(events):
    values = [event['vector'] for event in events]
    return [dict(feature=name, mean=fmean(vector[at] for vector in values),
                 standard_deviation=pstdev(vector[at] for vector in values))
            for at, name in enumerate(FEATURES)] if values else []


def _distance(left, right, scales):
    # Explicit accurate accumulation keeps the same norm and neighbor audits
    # reproducible across Python's different builtin floating sum algorithms.
    return math.sqrt(math.fsum(((a-b)/scale['standard_deviation'])**2
                              for a, b, scale in zip(left, right, scales) if scale['standard_deviation'] > 0))


def _proposal(item, plan, evidence, neighbors, names, latest):
    symbol = item['symbol']
    name = (names or {}).get(symbol, symbol)
    if isinstance(name, dict):
        name = name.get('name')
    name = name.strip()[:120] if isinstance(name, str) and name.strip() else symbol
    raw = v3.empirical_long_only_kelly([block['net_return'] for block in _block_returns(neighbors)])
    weight = min(.01, .25*raw, .01/plan['loss_fraction'])
    return dict(symbol=symbol, name=name, rank=0, strength_score=item['strength_score'], quote_session=latest,
        reason_facts=[f"20-session return {item['return20']:.2%}; cohort median {item['cohort_median_return20']:.2%}.",
                      f"60-session return {item['momentum60']:.2%}; SMA20 above SMA60.",
                      f"Other-symbol context: {evidence['samples']} events, {evidence['block_count']} calendar blocks.",
                      f"Experimental cost-stress expectation {evidence['expected_stress_net_return']:.2%}; forward validation collecting."],
        plan={key: plan[key] for key in ('entry_price', 'entry_upper', 'stop_price', 'target_price', 'loss_fraction')}
             | dict(horizon_sessions=10),
        risk=dict(reference_weight=weight, raw_kelly=raw, kelly_fraction=.25, adjusted_kelly=.25*raw,
                  planned_account_loss=weight*plan['loss_fraction'], approved_exposure=0., live_orders=False),
        model_evidence=evidence)


def discover_context_candidates(prices_by_symbol, *, names=None, as_of=None):
    """Infer at most three experimental proposals from fixed causal contexts."""
    if as_of is not None:
        v3._day(as_of)
    if names is not None and not isinstance(names, dict):
        raise ValueError('Candidate names must be a symbol mapping')
    groups, calendar, warnings = v3._prepare(prices_by_symbol, as_of)
    policy, empty = ExecutionPolicy(), v3._summary([], calendar, None, None)
    snapshots = v3._Snapshots(groups, calendar)
    ranked, current = snapshots.at(len(calendar)-1) if calendar else ([], [])
    result = dict(policy_version=POLICY_VERSION, latest_session=calendar[-1] if calendar else None,
        inspected_count=len(groups), eligible_count=0, candidates=[], reasons=[], rejection_counts={}, funnel=[],
        evidence=dict(formation=empty, confirmation=dict(empty), embargo=None),
        model=dict(name=MODEL_NAME, status='experimental', training_end=None,
                   comparison_interpretation='v3_unconditional_retrospective_control_not_v4_holdout',
                   validation='forward_collecting'),
        policy=dict(execution=asdict(policy), features=list(FEATURES), nearest_events=NEIGHBORS,
                    minimum_events=MIN_EVENTS, minimum_symbols=MIN_SYMBOLS, minimum_blocks=MIN_BLOCKS,
                    prior_blocks=PRIOR_BLOCKS, training='formation_only_other_symbols',
                    distance='euclidean_formation_population_standardization_zero_variance_ignored',
                    aggregation='equal_weight_nonoverlapping_ten_session_signal_blocks',
                    reference_weight_cap=.01, cost_stress_multiplier=2.),
        audit=dict(current=current, current_ranking=ranked, phases={}, contexts={},
                   training_scales=[], source_warnings=warnings),
        warnings=[*v3.WARNINGS, 'experimental_context_model_not_holdout_validated',
                  'unconditional_v3_comparison_is_not_v4_model_performance',
                  'context_expectations_are_model_estimates_not_profit_guarantees'])
    rejections = Counter(reason for item in current for reason in item['reasons'])
    memory, qualified = [], []
    if len(calendar) < v3.LOOKBACK:
        result['reasons'].append('insufficient_union_history')
    else:
        start = v3.LOOKBACK-v3.FORMATION-v3.EMBARGO-v3.CONFIRMATION
        end, confirmation_start = start+v3.FORMATION-1, start+v3.FORMATION+v3.EMBARGO
        result['model']['training_end'] = calendar[end]
        result['evidence']['embargo'] = dict(start=calendar[end+1], end=calendar[confirmation_start-1], sessions=v3.EMBARGO)
        for key, first, last in (('formation', start, end), ('confirmation', confirmation_start, len(calendar)-1)):
            phase = v3._phase(snapshots, calendar, first, last, policy)
            result['evidence'][key] = phase['summary']
            result['audit']['phases'][key] = dict(trades=phase['trades'], diagnostics=phase['diagnostics'])
        indices = {day: at for at, day in enumerate(calendar)}
        for trade in result['audit']['phases']['formation']['trades']:
            at = indices[trade['signal_date']]
            item = next(item for item in snapshots.at(at)[0] if item['symbol'] == trade['symbol'])
            memory.append(dict(symbol=trade['symbol'], signal_date=trade['signal_date'], exit_date=trade['exit_date'],
                               block=(at-start)//10, net_return=trade['net_return'],
                               stress_net_return=trade['stress_net_return'], vector=_vector(item)))
        # Targets are excluded before scaling, prior aggregation and neighbors,
        # so even indirect target-label dependence cannot enter inference.
        scales_by_target = {}
        for item in ranked:
            symbol = item['symbol']
            others = [event for event in memory if event['symbol'] != symbol]
            scales = _scales(others)
            scales_by_target[symbol] = scales
            vector = _vector(item)
            ordered = sorted((dict(event, distance=_distance(vector, event['vector'], scales)) for event in others),
                             key=lambda event: (event['distance'], event['signal_date'], event['symbol']))
            neighbors = ordered[:NEIGHBORS]
            prior_blocks = _block_returns(others)
            prior_net = fmean(block['net_return'] for block in prior_blocks) if prior_blocks else 0.
            prior_stress = fmean(block['stress_net_return'] for block in prior_blocks) if prior_blocks else 0.
            estimate = _estimate(neighbors, prior_net=prior_net, prior_stress=prior_stress)
            estimate.update(training_end=calendar[end], neighbors_exclude_target=True)
            reasons = _context_reasons(estimate)
            plan = build_candidate_reference_plan(groups[symbol], policy=policy)
            if plan['status'] != 'ready':
                reasons.append('current_entry_band_invalid')
            result['audit']['contexts'][symbol] = dict(neighbors=neighbors, estimate=estimate,
                prior_net_return=prior_net, prior_stress_net_return=prior_stress,
                prior_block_count=len(prior_blocks), reasons=reasons)
            rejections.update(reasons)
            if not reasons:
                qualified.append(_proposal(item, plan, estimate, neighbors, names, calendar[-1]))
        result['audit']['training_scales'] = scales_by_target
    qualified.sort(key=lambda item: (-item['model_evidence']['expected_stress_net_return'],
                                    -item['strength_score'], item['symbol']))
    result['eligible_count'], result['candidates'] = len(qualified), qualified[:3]
    for rank, item in enumerate(result['candidates'], 1):
        item['rank'] = rank
    if not result['candidates']:
        result['reasons'].append('no_positive_context_proposals' if ranked else 'no_current_setup')
    rejections.update(result['reasons'])
    result['rejection_counts'] = dict(sorted(rejections.items()))
    result['funnel'] = [dict(id='inspected', label='Inspected quality-cohort symbols', count=len(groups)),
                        dict(id='current_setup', label='Current fixed structure passed', count=len(ranked)),
                        dict(id='training_events', label='Formation-only training events', count=len(memory)),
                        dict(id='model_context', label='Other-symbol positive context qualified', count=len(qualified)),
                        dict(id='eligible', label='Experimental conditional proposals', count=len(qualified)),
                        dict(id='returned', label='Returned proposals (maximum three)', count=len(result['candidates']))]
    return result

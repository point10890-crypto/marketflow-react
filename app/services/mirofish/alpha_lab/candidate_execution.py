"""Candidate-only entry gates around unchanged shared paper execution.

Historical labels and forward observations must use this same boundary. The
signal's fixed entry ceiling/stop/target decide whether the next open fills;
the shared engine then recalculates ATR brackets from that actual open. Source
warning/info flags are normalized on copies, while fatal/nontradable flags
continue to block execution. This module performs no I/O and approves no orders.
"""
from __future__ import annotations

import math

from .execution import ExecutionPolicy, build_bracket_plan, simulate_trade


def normalize_candidate_rows(rows):
    """Copy bars, removing only explicit benign flag severities."""
    normalized = []
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError('Candidate execution requires OHLCV objects')
        row = dict(raw)
        flags = raw.get('quality_flags')
        if isinstance(flags, list):
            flags = [flag for flag in flags if not (
                isinstance(flag, dict) and isinstance(flag.get('code'), str) and flag['code'].strip()
                and isinstance(flag.get('severity'), str) and flag['severity'].lower() in {'warning', 'info'})]
            if flags:
                row['quality_flags'] = flags
            else:
                row.pop('quality_flags', None)
        elif flags is not None and not isinstance(flags, str):
            raise ValueError('Candidate quality flags must be explicit objects or flag strings')
        if raw.get('tradable') is False:
            row['quality_flags'] = ['source_nontradable']
        normalized.append(row)
    return normalized


def build_candidate_reference_plan(rows, signal_index=None, policy=None):
    """Build the causal signal bracket plus its fixed two-percent entry ceiling."""
    policy = policy or ExecutionPolicy()
    if not rows:
        return dict(build_bracket_plan([], policy=policy), entry_upper=None)
    at = len(rows)-1 if signal_index is None else signal_index
    if isinstance(at, bool) or not isinstance(at, int) or not 0 <= at < len(rows):
        raise ValueError('signal_index is outside the supplied rows')
    observed = normalize_candidate_rows(rows[:at+1])
    plan = build_bracket_plan(observed, at, policy)
    plan['entry_upper'] = plan['entry_price']*1.02 if plan['status'] == 'ready' else None
    if plan['status'] == 'ready' and plan['target_price'] <= plan['entry_upper']:
        plan.update(status='held', reasons=['target_not_above_entry_upper'])
    return plan


def _usable_reference(plan):
    if not isinstance(plan, dict) or plan.get('status', 'ready') != 'ready':
        return False
    keys = ('entry_price', 'entry_upper', 'stop_price', 'target_price')
    if any(isinstance(plan.get(key), bool) or not isinstance(plan.get(key), (int, float))
           or not math.isfinite(plan[key]) or plan[key] <= 0 for key in keys):
        return False
    return plan['stop_price'] < plan['entry_price'] < plan['entry_upper'] < plan['target_price']


def simulate_candidate_trade(rows, signal_index, policy=None, *, reference_plan=None):
    """Return the shared trade, or None when the original entry conditions fail.

    A supplied public reference_plan pins original entry gates. Its ATR is
    recomputed by the shared helper from the original frozen signal prefix;
    callers must quarantine source revisions instead of replacing that prefix.
    """
    policy = policy or ExecutionPolicy()
    causal = build_candidate_reference_plan(rows, signal_index, policy)
    reference = causal if reference_plan is None else reference_plan
    if causal['status'] != 'ready' or not _usable_reference(reference) or signal_index+1 >= len(rows):
        return None
    normalized = normalize_candidate_rows(rows)
    opening = normalized[signal_index+1].get('open')
    if (isinstance(opening, bool) or not isinstance(opening, (int, float)) or not math.isfinite(opening)
            or opening > reference['entry_upper'] or opening <= reference['stop_price']
            or opening >= reference['target_price']):
        return None
    return simulate_trade(normalized, signal_index, policy)

"""Pure, bounded prospective comparisons of fixed watchlists.

The three-slot return includes cash. It is descriptive watchlist evidence,
never an overlapping account return, order, confidence grade or promotion.
All provider IO and immutable experiment receipts belong to evolution_store.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import math
import re
from statistics import fmean, stdev

from . import decision_engine as ranking
from .execution import ExecutionPolicy, build_bracket_plan
from .features import features_at

POLICY = 'alpha-evolution-v1'
KST = timezone(timedelta(hours=9))
ARMS = (
    ('control', '현재 선정', 'issued_board_next_open'),
    ('entry-band-v1', '진입 범위', 'issued_board_frozen_band_next_open'),
    ('recovery-confirmed-v1', '회복 확인', 'full_pool_closed_recovery_strict_breakout'),
    ('positive-rank-v1', '양수 순위', 'full_pool_positive_final_correlation_rank'),
)
ARM_IDS = tuple(row[0] for row in ARMS)
TERMINAL = frozenset({'cash', 'skipped', 'unfilled', 'closed'})
STATES = TERMINAL | {'pending', 'open', 'missing'}


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()


def _hex(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except OverflowError:
        return None


def _day(value):
    try:
        if isinstance(value, str) and date.fromisoformat(value).isoformat() == value:
            return value
    except ValueError:
        pass
    raise ValueError('evolution_session_invalid')


def _time(value):
    try:
        current = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
        if isinstance(current, datetime) and current.utcoffset() is not None:
            return current.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        pass
    raise ValueError('evolution_timezone_required')


def _stamp(value):
    return _time(value).isoformat().replace('+00:00', 'Z')


def protocol_spec():
    """The finite predeclared catalogue; the store adds the declaration clock."""
    policy = ExecutionPolicy()
    value = dict(schema_version=1, protocol_version=POLICY,
        arms=[dict(id=identifier, label=label, selection=selection) for identifier, label, selection in ARMS],
        execution_policy=asdict(policy),
        stress_policy=asdict(replace(policy, fee_bps=2*policy.fee_bps,
            slippage_bps=2*policy.slippage_bps, sell_tax_bps=2*policy.sell_tax_bps)),
        slots=3, frozen_prefix_bars=64,
        window=dict(decision_sessions=106, nomination_sessions=36, embargo_sessions=10,
            confirmation_sessions=60, maturation_sessions=10, block_sessions=10, minimum_blocks=6),
        gates=dict(minimum_entered_outcomes=30, lower_bound_multiplier=3.5,
            positive_normal_mean=True, positive_stress_mean=True,
            positive_paired_advantage=True, downside_tail_nonworse=True,
            complete_unrevised_confirmation=True, complete_unrevised_declared_window=True,
            complete_capture_audit=True),
        acquisition_buffer_kst='20:30:00',
        return_basis='equal_three_slot_watchlist_not_account_pnl',
        tail_basis='worst_ten_percent_three_slot_stress_loss',
        nomination_basis='first_36_paired_stress_mean_only',
        confirmation_basis='after_10_session_embargo_60_session_rejection_only',
        research_only=True, live_orders=False, approved_exposure=0.)
    return dict(value, protocol_hash=_hash(value))


def _protocol(value):
    fixed = protocol_spec()
    if not isinstance(value, dict) or any(value.get(key) != wanted for key, wanted in fixed.items()):
        raise ValueError('evolution_protocol_changed')
    _time(value.get('declared_at'))
    receipt = value.get('nomination')
    if receipt is not None and (not isinstance(receipt, dict)
            or receipt.get('status') not in {'fixed', 'none'}
            or receipt.get('session_count') != fixed['window']['nomination_sessions']
            or receipt.get('arm_id') not in ARM_IDS[1:]+(None,)
            or (receipt['status'] == 'fixed') != (receipt.get('arm_id') is not None)):
        raise ValueError('evolution_nomination_invalid')
    return fixed


def _bar(raw, symbol):
    if not isinstance(raw, dict) or raw.get('symbol', symbol) != symbol:
        raise ValueError('evolution_price_identity')
    value = dict(symbol=symbol, date=_day(raw.get('date')))
    for key in ('open', 'high', 'low', 'close', 'volume'):
        number = _number(raw.get(key))
        if number is None or number < 0 or key != 'volume' and number == 0:
            raise ValueError('evolution_nonfinite_or_invalid_price')
        value[key] = number
    if not value['low'] <= min(value['open'], value['close']) <= max(value['open'], value['close']) <= value['high']:
        raise ValueError('evolution_price_extrema')
    if raw.get('quality_flags'):
        value['quality_flags'] = deepcopy(raw['quality_flags'])
    return value


def _rows(raw, symbol, cutoff):
    if not isinstance(raw, list) or len(raw) > 20000:
        raise ValueError('evolution_prices_invalid')
    rows, previous = [], None
    for value in raw:
        day = _day(value.get('date')) if isinstance(value, dict) else _day(None)
        # Exclude future rows before examining their prices or symbol.
        if day > cutoff:
            continue
        if previous is not None and day <= previous:
            raise ValueError('evolution_prices_not_chronological')
        rows.append(_bar(value, symbol))
        previous = day
    return rows


def _provenance_verified(value, decision_at):
    if not isinstance(value, dict) or any(not _hex(value.get(key)) for key in
                                          ('source_hash', 'manifest_hash', 'scope_hash')):
        return False
    source = value.get('price_source')
    try:
        captured = _time(value.get('captured_at'))
        return (isinstance(source, str) and bool(source.strip()) and source.lower() not in {'unknown', 'unavailable'}
                and captured <= _time(decision_at))
    except ValueError:
        return False


def _capture_in_buffer(capture, latest, origin):
    captured = _time(capture)
    lower = datetime.combine(date.fromisoformat(latest), time(20, 30), KST).astimezone(timezone.utc)
    if not lower <= captured <= origin:
        raise ValueError('evolution_capture_outside_current_buffer')
    return captured


def _capture_audit_guard(audit, names, latest, origin):
    if not isinstance(audit, dict) or set(audit) != set(names):
        raise ValueError('evolution_capture_audit_incomplete')
    for value in audit.values():
        if not isinstance(value, dict) or set(value) != {'first', 'last'}:
            raise ValueError('evolution_capture_audit_invalid')
        first = _capture_in_buffer(value['first'], latest, origin)
        last = _capture_in_buffer(value['last'], latest, origin)
        if first > last:
            raise ValueError('evolution_capture_audit_order')


def _capture_guard(inputs, names, latest, origin):
    provenance = inputs.get('provenance', {})
    _capture_in_buffer(provenance.get('captured_at'), latest, origin)
    if 'capture_audit' in inputs:
        _capture_audit_guard(inputs['capture_audit'], names, latest, origin)
    explicit = provenance.get('captured_at_by_symbol')
    if explicit is not None:
        if not isinstance(explicit, dict) or not set(names).issubset(explicit):
            raise ValueError('evolution_symbol_capture_incomplete')
        for symbol in names:
            _capture_in_buffer(explicit[symbol], latest, origin)
    for symbol in names:
        for row in inputs['prices_by_symbol'].get(symbol, []):
            if isinstance(row, dict) and row.get('date') == latest and 'captured_at' in row:
                _capture_in_buffer(row['captured_at'], latest, origin)


def _cohort_capture_verified(cohort):
    try:
        origin = _time(cohort['decision_at'])
        latest = _day(cohort['latest_session'])
        _capture_in_buffer(cohort['provenance']['captured_at'], latest, origin)
        _capture_audit_guard(cohort.get('capture_audit'), cohort['names'], latest, origin)
        return True
    except (KeyError, TypeError, ValueError):
        return False


def _selection(raw, slot, frozen):
    symbol = raw.get('symbol')
    if (not isinstance(symbol, str) or re.fullmatch('[0-9]{6}', symbol) is None
            or symbol not in frozen or not isinstance(raw.get('name'), str)
            or raw.get('strategy_id') not in ranking.SETUPS):
        raise ValueError('evolution_selected_identity')
    plan = deepcopy(raw.get('plan'))
    if not isinstance(plan, dict) or any(_number(plan.get(key)) is None for key in ('entry_low', 'entry_high')):
        raise ValueError('evolution_selected_plan')
    if not 0 < plan['entry_low'] <= plan['entry_high']:
        raise ValueError('evolution_selected_band')
    bracket = build_bracket_plan(frozen[symbol], policy=ExecutionPolicy())
    return dict(slot=slot, symbol=symbol, name=raw['name'][:200], market='KR',
        strategy_id=raw['strategy_id'], plan=plan, ranking=deepcopy(raw.get('ranking', {})), bracket=bracket)


def _cash(slot):
    return dict(slot=slot, symbol=None, name=None, status='cash', reason='unused_slot_cash',
        entry_date=None, exit_date=None, net_return=0., stress_net_return=0.)


def _pending(selected):
    return dict(slot=selected['slot'], symbol=selected['symbol'], name=selected['name'],
        status='pending', reason='awaiting_next_closed_union_session',
        entry_date=None, exit_date=None, net_return=None, stress_net_return=None)


def _gated_pool(discovery, frozen, report):
    """Reuse incumbent evidence gates, retaining every qualified survivor."""
    result = []
    for raw in discovery.get('candidates', []):
        one = dict(discovery, candidates=[raw])
        board = ranking.build_opportunity_board(one, frozen, report, now=report['decision_at'])
        result.extend(board['candidates'])
    return result


def _positive_rank(discovery, frozen, report, latest):
    remaining, selected, rejected = _gated_pool(discovery, frozen, report), [], []
    for row in remaining:
        row['_returns'] = ranking._price_returns(frozen.get(row['symbol']), row['symbol'], latest)[0]
    while remaining and len(selected) < 3:
        eligible = []
        for row in remaining:
            penalty, unknown = ranking._penalty(row, selected)
            row['ranking']['correlation_penalty'] = penalty
            row['ranking']['score'] = row['ranking']['conservative_score']-penalty
            row['_unknown'] = unknown
            if row['ranking']['score'] > 0:
                eligible.append(row)
            else:
                rejected.append(dict(symbol=row['symbol'], name=row['name'],
                    reason='final_correlation_rank_nonpositive', score=row['ranking']['score']))
        remaining = eligible
        if not remaining:
            break
        remaining.sort(key=lambda row: (-row['ranking']['score'], row['symbol']))
        selected.append(remaining.pop(0))
    for row in selected:
        row.pop('_returns', None)
        row.pop('_unknown', None)
    return selected, rejected


def build_cohort(inputs, report, discovery, *, protocol, now):
    """Freeze one current, after-declaration decision without acquiring data."""
    manifest = _protocol(protocol)
    current = _time(now)
    if not all(isinstance(value, dict) for value in (inputs, report, discovery)):
        raise ValueError('evolution_inputs_invalid')
    board = report.get('opportunity_board')
    if not isinstance(board, dict) or board.get('schema_version') != 1 or board.get('policy_version') != ranking.POLICY:
        raise ValueError('evolution_board_unavailable')
    binding = {key:board.get(key) for key in ('decision_id', 'input_fingerprint', 'source_audit_hash')}
    if (any(not _hex(value) for value in binding.values())
            or binding['input_fingerprint'] != inputs.get('input_fingerprint')
            or binding['input_fingerprint'] != report.get('input_fingerprint')
            or binding['source_audit_hash'] != report.get('opportunity_scan', {}).get('audit_hash')):
        raise ValueError('evolution_source_identity_mismatch')
    origin = _time(board.get('origin_at') or board.get('generated_at'))
    if not _time(protocol['declared_at']) < origin <= _time(report.get('decision_at')) <= current:
        raise ValueError('evolution_decision_not_after_declaration')
    latest = _day(inputs.get('latest_session'))
    decision_session = origin.astimezone(KST).date().isoformat()
    if (latest != decision_session or report.get('latest_session') != latest
            or board.get('latest_session') != latest or discovery.get('latest_session') != latest
            or origin.astimezone(KST).time() < time(15, 30)
            or current.astimezone(KST).date().isoformat() != decision_session):
        raise ValueError('evolution_noncurrent_source_session')
    if (inputs.get('status') != 'ready' or report.get('opportunity_scan', {}).get('status') != 'ready'
            or any(reason in ranking.BLOCKERS for reason in board.get('reasons', []))):
        raise ValueError('evolution_source_unavailable')
    names = inputs.get('names')
    prices = inputs.get('prices_by_symbol')
    if not isinstance(names, dict) or not 1 <= len(names) <= 100 or not isinstance(prices, dict):
        raise ValueError('evolution_quality_cohort_invalid')
    _capture_guard(inputs, names, latest, origin)
    frozen = {}
    for symbol in sorted(names):
        if re.fullmatch('[0-9]{6}', symbol) is None or not isinstance(names[symbol], str):
            raise ValueError('evolution_quality_identity_invalid')
        frozen[symbol] = _rows(prices.get(symbol, []), symbol, latest)[-64:]
    raw_pool = discovery.get('candidates')
    if (not isinstance(raw_pool, list) or len(raw_pool) > 100
            or discovery.get('eligible_count') != len(raw_pool)
            or len({row.get('symbol') for row in raw_pool if isinstance(row, dict)}) != len(raw_pool)):
        raise ValueError('evolution_full_discovery_pool_required')
    candidates = board.get('candidates')
    if (not isinstance(candidates, list) or len(candidates) > 3
            or len({row.get('symbol') for row in candidates}) != len(candidates)):
        raise ValueError('evolution_board_selection_invalid')
    recovery_pool, recovery_rejected = [], []
    for raw in raw_pool:
        symbol, rows = raw.get('symbol'), frozen.get(raw.get('symbol'), [])
        values = features_at(rows, len(rows)-1) if len(rows) >= 61 else None
        reason = None
        if values is None:
            reason = 'closed_recovery_features_unavailable'
        elif values['candle_body'] <= 0 or rows[-1]['close'] <= rows[-2]['close']:
            reason = 'closed_recovery_not_confirmed'
        elif raw.get('strategy_id') == 'liquidity_breakout' and values['breakout_20'] <= 0:
            reason = 'breakout_not_cleared'
        if reason:
            recovery_rejected.append(dict(symbol=symbol, name=raw.get('name', symbol), reason=reason))
        else:
            recovery_pool.append(raw)
    recovery = ranking.build_opportunity_board(dict(discovery, candidates=recovery_pool), frozen, report,
                                               now=report['decision_at'])['candidates']
    positive, positive_rejected = _positive_rank(discovery, frozen, report, latest)
    arms, observed_arms = [], []
    selections = dict(control=candidates, **{'entry-band-v1':candidates,
        'recovery-confirmed-v1':recovery, 'positive-rank-v1':positive})
    rejections = {'recovery-confirmed-v1':recovery_rejected, 'positive-rank-v1':positive_rejected}
    for identifier, label, _ in ARMS:
        picked = [_selection(raw, slot, frozen) for slot, raw in enumerate(selections[identifier], 1)]
        arms.append(dict(id=identifier, label=label, selections=picked, rejections=rejections.get(identifier, [])))
        slots = [_pending(row) for row in picked]+[_cash(slot) for slot in range(len(picked)+1, 4)]
        observed_arms.append(dict(id=identifier, slots=slots))
    value = dict(schema_version=1, protocol_version=POLICY, protocol_hash=manifest['protocol_hash'],
        protocol_id=protocol.get('protocol_id'), decision_at=_stamp(origin), decision_session=decision_session,
        latest_session=latest, binding=binding, provenance=deepcopy(inputs.get('provenance', {})),
        capture_audit=deepcopy(inputs.get('capture_audit')),
        universe=deepcopy(inputs.get('universe', {})), names=deepcopy(names), discovery=deepcopy(discovery),
        frozen_prices=frozen, arms=arms)
    identity = _hash(value)
    observation = dict(observed_at=None, calendar=[], prices={symbol:[] for symbol in frozen},
        source_hashes={}, arms=observed_arms, revision_evidence=[])
    return dict(value, cohort_id=identity, observation=observation)


def _closed_cutoff(current):
    local = current.astimezone(KST)
    return (local.date() if local.time() >= time(15, 30) else local.date()-timedelta(days=1)).isoformat()


def _revision(observation, reason, *, symbol=None, session=None, original=None, current=None):
    evidence = dict(reason=reason, symbol=symbol, session=session, original=original, current=current)
    if evidence not in observation['revision_evidence']:
        observation['revision_evidence'].append(evidence)


def _executable(row):
    return bool(row and row['volume'] > 0 and not row.get('quality_flags'))


def _result(selected, identifier, calendar, lookup, policy, stressed):
    value = _pending(selected)
    if not calendar:
        return value
    next_session = calendar[0]
    value['next_session'] = next_session
    first = lookup.get(next_session)
    if not _executable(first):
        value.update(status='unfilled', reason='missing_next_union_quote' if first is None else 'next_open_nontradable',
                     net_return=0., stress_net_return=0.)
        return value
    opening = first['open']
    band = selected['plan']
    if identifier == 'entry-band-v1' and not band['entry_low'] <= opening <= band['entry_high']:
        value.update(status='skipped', reason='next_open_outside_frozen_band', net_return=0., stress_net_return=0.)
        return value
    bracket = selected['bracket']
    if bracket['status'] != 'ready':
        value.update(status='unfilled', reason='frozen_bracket_unavailable', net_return=0., stress_net_return=0.)
        return value
    distance = min(policy.atr_multiplier*bracket['atr'], opening*policy.max_stop_fraction)
    value.update(status='open', reason='awaiting_closed_horizon', entry_date=next_session,
        entry_price=opening, atr=bracket['atr'], stop_price=opening-distance,
        target_price=opening+policy.reward_risk*distance, holding_sessions=0,
        exit_price=None, exit_reason=None, gross_return=None, ambiguous_bar=False)
    for index, session in enumerate(calendar[:policy.horizon]):
        row = lookup.get(session)
        value['holding_sessions'] = index+1
        if not _executable(row):
            # Unknown intervals cannot silently skip an earlier stop/target.
            value.update(status='missing', reason='missing_or_nontradable_holding_quote')
            return value
        hit = None
        if index and row['open'] <= value['stop_price']:
            hit = row['open'], 'stop_gap'
        elif index and row['open'] >= value['target_price']:
            hit = row['open'], 'target_gap'
        elif row['low'] <= value['stop_price']:
            hit = value['stop_price'], 'stop'
        elif row['high'] >= value['target_price']:
            hit = value['target_price'], 'target'
        elif index+1 == policy.horizon:
            hit = row['close'], 'time'
        if hit:
            price, reason = hit
            value.update(status='closed', reason=None, exit_date=session, exit_price=price, exit_reason=reason,
                gross_return=price/opening-1.,
                net_return=price*(1-policy.exit_cost)/(opening*(1+policy.entry_cost))-1.,
                stress_net_return=price*(1-stressed.exit_cost)/(opening*(1+stressed.entry_cost))-1.,
                ambiguous_bar=reason == 'stop' and row['high'] >= value['target_price'])
            break
    return value


def observe_cohort(cohort, prices_by_symbol, *, now):
    """Replay original decisions, sealing terminal bodies and auditing revisions."""
    current = _time(now)
    if (not isinstance(cohort, dict) or cohort.get('protocol_version') != POLICY
            or cohort.get('protocol_hash') != protocol_spec()['protocol_hash']
            or not isinstance(prices_by_symbol, dict)):
        raise ValueError('evolution_cohort_invalid')
    value = deepcopy(cohort)
    observation = value['observation']
    if observation.get('observed_at') and current < _time(observation['observed_at']):
        raise ValueError('evolution_observation_clock_regressed')
    cutoff = _closed_cutoff(current)
    signal = _day(value['latest_session'])
    old_calendar = observation['calendar']
    horizon = ExecutionPolicy().horizon
    dates = set()
    for symbol, raw in prices_by_symbol.items():
        if not isinstance(symbol, str) or re.fullmatch('[0-9]{6}', symbol) is None:
            raise ValueError('evolution_price_identity')
        if not isinstance(raw, list) or len(raw) > 20000:
            raise ValueError('evolution_prices_invalid')
        for row in raw:
            day = _day(row.get('date')) if isinstance(row, dict) else _day(None)
            if signal < day <= cutoff:
                dates.add(day)
    observed_calendar = sorted(dates)[:horizon]
    # Later prices cannot affect an already frozen ten-session label window.
    capture_cutoff = (old_calendar[-1] if len(old_calendar) >= horizon
                      else max([signal, *old_calendar, *observed_calendar]))
    for symbol in set(prices_by_symbol)-set(value['frozen_prices']):
        _rows(prices_by_symbol[symbol], symbol, capture_cutoff)
    fresh = {symbol:_rows(prices_by_symbol.get(symbol, []), symbol, capture_cutoff) for symbol in value['frozen_prices']}
    lookups = {symbol:{row['date']:row for row in rows} for symbol, rows in fresh.items()}
    for symbol, rows in value['frozen_prices'].items():
        for original in rows:
            updated = lookups[symbol].get(original['date'])
            if updated != original:
                _revision(observation, 'frozen_prefix_changed', symbol=symbol, session=original['date'],
                    original=_hash(original), current=_hash(updated) if updated else None)
    old_last = old_calendar[-1] if old_calendar else signal
    if [day for day in observed_calendar if day <= old_last] != old_calendar:
        _revision(observation, 'observed_union_calendar_changed', original=_hash(old_calendar),
            current=_hash([day for day in observed_calendar if day <= old_last]))
    # Preserve each first observed calendar/quote; append only new evidence.
    observation['calendar'] = (old_calendar+[day for day in observed_calendar if day > old_last])[:horizon]
    for symbol, rows in fresh.items():
        original_rows = observation['prices'].setdefault(symbol, [])
        saved = {row['date']:row for row in original_rows}
        for day, original in saved.items():
            updated = lookups[symbol].get(day)
            if updated != original:
                _revision(observation, 'observed_price_changed', symbol=symbol, session=day,
                    original=_hash(original), current=_hash(updated) if updated else None)
        for row in rows:
            day = row['date']
            if day <= signal or day in saved:
                continue
            if day <= old_last:
                _revision(observation, 'previously_missing_quote_added', symbol=symbol, session=day,
                    original=None, current=_hash(row))
            original_rows.append(row)
            observation['source_hashes'][symbol+'|'+day] = _hash(row)
        original_rows.sort(key=lambda row:row['date'])
    policy = ExecutionPolicy()
    stressed = replace(policy, fee_bps=2*policy.fee_bps,
        slippage_bps=2*policy.slippage_bps, sell_tax_bps=2*policy.sell_tax_bps)
    for selected_arm, observed_arm in zip(value['arms'], observation['arms']):
        if selected_arm['id'] != observed_arm['id']:
            raise ValueError('evolution_arm_identity')
        for selected in selected_arm['selections']:
            slot = selected['slot']-1
            if observed_arm['slots'][slot]['status'] in TERMINAL:
                continue
            lookup = {row['date']:row for row in observation['prices'][selected['symbol']]}
            observed_arm['slots'][slot] = _result(selected, selected_arm['id'], observation['calendar'], lookup, policy, stressed)
    observation['observed_at'] = _stamp(current)
    json.dumps(value, allow_nan=False)
    return value


def _arm(cohort, identifier, *, observed=False):
    rows = cohort.get('observation', {}).get('arms', []) if observed else cohort.get('arms', [])
    return next((row for row in rows if row.get('id') == identifier), {})


def _revised(cohort):
    return bool(cohort.get('observation', {}).get('revision_evidence'))


def _resolved_slot(cohort, row):
    state = row.get('status')
    normal, stress = _number(row.get('net_return')), _number(row.get('stress_net_return'))
    if state not in TERMINAL or normal is None or stress is None:
        return False
    if state != 'closed':
        return normal == stress == 0 and row.get('entry_date') is None and row.get('exit_date') is None
    if not -1 < stress <= normal:
        return False
    try:
        entry, exit_day = _day(row.get('entry_date')), _day(row.get('exit_date'))
        signal = _day(cohort['decision_session'])
        observed = _time(cohort['observation']['observed_at'])
        calendar = cohort['observation']['calendar']
        return (bool(calendar) and signal < entry <= exit_day <= _closed_cutoff(observed)
                and entry == calendar[0] and exit_day in calendar[:ExecutionPolicy().horizon])
    except (KeyError, TypeError, ValueError):
        return False


def _return(cohort, identifier, key):
    if _revised(cohort):
        return None
    slots = _arm(cohort, identifier, observed=True).get('slots', [])
    if (not isinstance(slots, list) or len(slots) != 3
            or any(not _resolved_slot(cohort, row) for row in slots)):
        return None
    if any(row['status'] != 'closed' and row[key] != 0 for row in slots):
        return None
    return sum(row[key] for row in slots)/3.


def _paired(cohorts, identifier):
    rows = []
    for cohort in cohorts:
        normal, stress, control, control_stress = (_return(cohort, arm_id, key) for arm_id, key in (
            (identifier, 'net_return'), (identifier, 'stress_net_return'),
            ('control', 'net_return'), ('control', 'stress_net_return')))
        if None not in (normal, stress, control, control_stress):
            rows.append(dict(session=cohort['decision_session'], normal=normal, stress=stress,
                control=control, control_stress=control_stress, advantage=normal-control,
                stress_advantage=stress-control_stress))
    return rows


def _tail(values):
    if not values:
        return None
    return max(0., -fmean(sorted(values)[:max(1, math.ceil(len(values)*.1))]))


def _mean(rows, key):
    return fmean(row[key] for row in rows) if rows else None


def _counts(cohorts, identifier):
    counts = dict(entered=0, resolved=0, closed=0, skipped=0, cash=0, unfilled=0,
        pending=0, open=0, missing=0, revised=0, paired_sessions=0,
        missed_control_winners=0, avoided_control_losers=0)
    for cohort in cohorts:
        slots = _arm(cohort, identifier, observed=True).get('slots', [])
        for row in slots:
            state = row.get('status')
            if state not in STATES:
                continue
            counts[state] += 1
            counts['entered'] += state in {'closed', 'open', 'missing'}
            counts['resolved'] += state in TERMINAL
            counts['revised'] += _revised(cohort)
        if identifier == 'control' or _revised(cohort):
            continue
        accepted = {row.get('symbol') for row in slots if row.get('status') == 'closed'}
        if _return(cohort, identifier, 'net_return') is None or _return(cohort, 'control', 'net_return') is None:
            continue
        for baseline in _arm(cohort, 'control', observed=True).get('slots', []):
            if baseline.get('status') == 'closed' and baseline.get('symbol') not in accepted:
                counts['missed_control_winners'] += baseline['net_return'] > 0
                counts['avoided_control_losers'] += baseline['net_return'] < 0
    counts['paired_sessions'] = len(_paired(cohorts, identifier))
    return counts


def _nominate(protocol, cohorts, window):
    if protocol.get('nomination') is not None:
        return deepcopy(protocol['nomination'])
    n = window['nomination_sessions']
    nomination = dict(status='pending', arm_id=None, session_count=n, reason='awaiting_nomination_labels')
    if len(cohorts) < n:
        return nomination
    first = cohorts[:n]
    choices = []
    for identifier in ARM_IDS[1:]:
        paired = _paired(first, identifier)
        if len(paired) == n:
            choices.append((_mean(paired, 'stress'), identifier))
    if len(choices) != 3:
        if len(cohorts) >= n+window['embargo_sessions']:
            return dict(nomination, status='none', reason='nomination_coverage_unresolved_at_fixed_boundary')
        return nomination
    choices.sort(key=lambda row:(-row[0], row[1]))
    return dict(nomination, status='fixed', arm_id=choices[0][1], reason='fixed_nomination_paired_stress_mean')


def summarize(protocol, cohorts):
    """Bounded saved public evidence; confirmation can only reject a fixed arm."""
    manifest = _protocol(protocol)
    if not isinstance(cohorts, list) or len(cohorts) > manifest['window']['decision_sessions']:
        raise ValueError('evolution_window_capacity')
    ordered = sorted(cohorts, key=lambda row:row['decision_session'])
    if (len({row['decision_session'] for row in ordered}) != len(ordered)
            or any(row.get('protocol_hash') != manifest['protocol_hash']
                   or row.get('protocol_id') != protocol.get('protocol_id')
                   or _time(row.get('decision_at')) <= _time(protocol['declared_at'])
                   or _day(row.get('decision_session')) != row.get('latest_session')
                   or _time(row['decision_at']).astimezone(KST).date().isoformat() != row['decision_session']
                   for row in ordered)):
        raise ValueError('evolution_cohort_binding')
    window = deepcopy(manifest['window'])
    window.update(enrolled_sessions=len(ordered),
        resolved_sessions=sum(_return(row, 'control', 'net_return') is not None for row in ordered),
        maturation_observed=0)
    if ordered:
        final_day = ordered[-1]['decision_session']
        maturation = {day for row in ordered for day in row.get('observation', {}).get('calendar', []) if day > final_day}
        if len(ordered) == window['decision_sessions']:
            window['maturation_observed'] = min(window['maturation_sessions'], len(maturation))
    nomination = _nominate(protocol, ordered, window)
    offset = window['nomination_sessions']+window['embargo_sessions']
    confirmation = ordered[offset:]
    selected = nomination['arm_id']
    paired = _paired(confirmation, selected) if selected else []
    confirmation_count = window['confirmation_sessions']
    normal, stress = _mean(paired, 'normal'), _mean(paired, 'stress')
    advantage, stress_advantage = _mean(paired, 'advantage'), _mean(paired, 'stress_advantage')
    block_means = []
    by_session = {row['session']:row for row in paired}
    for start in range(0, len(confirmation), window['block_sessions']):
        block = confirmation[start:start+window['block_sessions']]
        if len(block) == window['block_sessions'] and all(row['decision_session'] in by_session for row in block):
            block_means.append(fmean(by_session[row['decision_session']]['stress_advantage'] for row in block))
    bound = (fmean(block_means)-manifest['gates']['lower_bound_multiplier']*stdev(block_means)/math.sqrt(len(block_means))
             if len(block_means) >= 2 else None)
    tail_delta = (_tail([row['stress'] for row in paired])-_tail([row['control_stress'] for row in paired])) if paired else None
    reasons = []
    full = len(ordered) == window['decision_sessions']
    resolved = len(paired) == confirmation_count
    all_resolved = all(_return(row, identifier, 'net_return') is not None for row in ordered for identifier in ARM_IDS)
    revised = any(_revised(row) for row in ordered)
    provenance_ok = all(_provenance_verified(row.get('provenance'), row.get('decision_at'))
                        and _cohort_capture_verified(row) for row in ordered)
    if not full:
        reasons.append('fixed_window_incomplete')
    if not selected:
        reasons.append('no_fixed_nominated_challenger')
    if full and not resolved:
        reasons.append('confirmation_coverage_unresolved')
    if full and not all_resolved:
        reasons.append('declared_window_coverage_unresolved')
    if revised:
        reasons.append('revised_coverage')
    if not provenance_ok:
        reasons.append('unverifiable_input_provenance')
    entered = sum(row.get('status') == 'closed' for cohort in confirmation if not _revised(cohort)
                  for row in _arm(cohort, selected, observed=True).get('slots', [])) if selected else 0
    control_entered = sum(row.get('status') == 'closed' for cohort in confirmation if not _revised(cohort)
                         for row in _arm(cohort, 'control', observed=True).get('slots', []))
    if full:
        if entered < manifest['gates']['minimum_entered_outcomes']:
            reasons.append('insufficient_entered_outcomes')
        if control_entered < manifest['gates']['minimum_entered_outcomes']:
            reasons.append('insufficient_control_entered_outcomes')
        if len(block_means) < window['minimum_blocks']:
            reasons.append('insufficient_confirmation_blocks')
        for metric, value in (('normal_mean', normal), ('stress_mean', stress),
                              ('paired_advantage', advantage), ('paired_stress_advantage', stress_advantage)):
            if value is None or value <= 0:
                reasons.append('confirmation_nonpositive_'+metric)
        if bound is None or bound <= 0:
            reasons.append('confirmation_block_lower_bound_nonpositive')
        if tail_delta is None or tail_delta > 0:
            reasons.append('confirmation_downside_tail_worse_or_unknown')
    # Fixed maturation deadline cannot renew itself based on the results.
    terminal = full and (resolved and all_resolved or revised or window['maturation_observed'] >= window['maturation_sessions'])
    review_status = 'awaiting_review' if terminal and not reasons else 'rejected' if terminal else 'collecting'
    if review_status == 'awaiting_review':
        phase, next_step = 'awaiting_review', '독립 관찰 결과를 연구 후보로 검토해 주세요.'
    elif review_status == 'rejected':
        phase, next_step = 'incumbent_retained', '고정 기준을 통과하지 못해 현재 선정 정책을 유지합니다.'
    elif full:
        phase, next_step = 'maturing', '정해진 10개 거래일 안에서 남은 관찰 결과를 기다립니다.'
    elif len(ordered) >= offset:
        phase, next_step = 'collecting_confirmation', '고정 후보의 별도 60개 거래일 결과를 관찰합니다.'
    elif len(ordered) >= window['nomination_sessions']:
        phase, next_step = 'embargo', '10개 거래일 동안 앞 구간의 라벨이 닫히기를 기다립니다.'
    else:
        phase, next_step = 'collecting_nomination', '처음 36개 거래일의 고정 도전 정책을 함께 관찰합니다.'
    arms = []
    for identifier, label, _ in ARMS:
        comparisons = _paired(ordered, identifier)
        last = _arm(ordered[-1], identifier).get('selections', []) if ordered else []
        arms.append(dict(id=identifier, label=label,
            selected=[{key:row.get(key) for key in ('symbol', 'name', 'market', 'strategy_id', 'slot')} for row in last],
            counts=_counts(ordered, identifier),
            metrics=dict(mean_net_return=_mean(comparisons, 'normal'), stress_mean_net_return=_mean(comparisons, 'stress'),
                paired_advantage=_mean(comparisons, 'advantage'), stress_paired_advantage=_mean(comparisons, 'stress_advantage'),
                downside_tail_loss=_tail([row['stress'] for row in comparisons])),
            reasons=['revised_coverage'] if revised else []))
    result = dict(schema_version=1, protocol_version=POLICY, protocol_hash=manifest['protocol_hash'],
        binding=deepcopy(ordered[-1]['binding']) if ordered else dict(decision_id=None, input_fingerprint=None, source_audit_hash=None),
        phase=phase, next_step=next_step, research_only=True, live_orders=False, approved_exposure=0.,
        return_basis=manifest['return_basis'], window=window, nomination=nomination,
        review=dict(status=review_status, arm_id=selected, reasons=reasons,
            limitations=[reason for reason, applicable in (
                ('historical_vintage_unverified', any(row.get('provenance', {}).get('historical_vintage_verified') is not True for row in ordered)),
                ('corporate_action_adjustment_unverified', any(row.get('provenance', {}).get('price_adjustment_verified') is not True for row in ordered)),
                ('current_quality_cohort_survivorship_bias', any(row.get('provenance', {}).get('point_in_time_universe_verified') is not True for row in ordered)),
                ('paper_costs_and_fills_not_brokerage_execution', True)) if applicable],
            normal_mean=normal, stress_mean=stress, paired_advantage=advantage,
            stress_paired_advantage=stress_advantage, block_lower_bound=bound, downside_tail_delta=tail_delta,
            entered_outcomes=entered, control_entered_outcomes=control_entered, completed_blocks=len(block_means)),
        arms=arms, reasons=reasons)
    json.dumps(result, allow_nan=False)
    return result

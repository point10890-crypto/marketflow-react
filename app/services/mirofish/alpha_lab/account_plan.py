"""Pure, request-only reference sizing; strategy approval and orders stay held.

``ready`` means the arithmetic passes the stated account limits. It never
promotes M0 research, certifies a future forecast or authorizes an order.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR, localcontext
import math
import re


POLICY = 'evidence-account-v1'
LIMITS = dict(trade_risk=.005, daily_stop=-.015, weekly_stop=-.04,
              symbol_cap=.05, theme_cap=.30, cash_floor=.40)
WARNINGS = ['research_reference_only', 'strategy_promotion_held',
            'forecast_unavailable', 'gap_losses_may_exceed_planned_loss']
ACCOUNT_KEYS = {'equity', 'available_cash', 'daily_pnl', 'weekly_pnl',
                'positions_confirmed', 'positions'}
MAX_SAFE_INTEGER = 2**53 - 1
QUOTE_SOURCE = 'KIS:J:FHKST03010200+FHKST01010100'
KST = timezone(timedelta(hours=9))


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except OverflowError:
        return None


def _timestamp(value):
    try:
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if isinstance(value, datetime) and value.utcoffset() is not None:
            return value.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        pass
    return None


def _stamp(value):
    return value.isoformat().replace('+00:00', 'Z') if value is not None else None


def _symbol(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9]{6}', value) is not None and value != '000000'


def _identity(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def _theme(value):
    if (not isinstance(value, str) or not 1 <= len(value.strip()) <= 100
            or any(ord(char) < 32 for char in value)):
        return None
    normalized = value.strip().casefold()
    return None if normalized in {'unknown', 'unavailable', 'none', 'null', 'n/a',
                                 '미확인', '미분류', '알 수 없음'} else normalized


def _decimal(value):
    return Decimal(str(value))


def _validate_account(account):
    """Return normalized values or bounded reason codes, never echo inputs."""
    reasons, normalized = [], {}
    if not isinstance(account, dict):
        return None, ['account_required']
    if set(account) - ACCOUNT_KEYS:
        reasons.append('account_unknown_fields')
    for key in ('equity', 'available_cash', 'daily_pnl', 'weekly_pnl'):
        if key not in account:
            reasons.append('account_'+key+'_required')
            continue
        number = _number(account[key])
        if (number is None or abs(number) > MAX_SAFE_INTEGER or key == 'equity' and number <= 0
                or key == 'available_cash' and number < 0):
            reasons.append('account_'+key+'_invalid')
        else:
            normalized[key] = number
    if 'positions_confirmed' not in account:
        reasons.append('account_positions_confirmed_required')
    elif account['positions_confirmed'] is not True:
        reasons.append('account_positions_confirmed_invalid')
    if 'positions' not in account:
        reasons.append('account_positions_required')
        holdings = None
    else:
        holdings = account['positions']
    valid = isinstance(holdings, list) and len(holdings) <= 100
    positions, symbols = [], set()
    if valid:
        for row in holdings:
            row = _mapping(row)
            symbol, theme, value = row.get('symbol'), _theme(row.get('theme')), _number(row.get('market_value'))
            if (set(row) != {'symbol', 'theme', 'market_value'} or not _symbol(symbol)
                    or symbol in symbols or theme is None or value is None or not 0 < value <= MAX_SAFE_INTEGER):
                valid = False
                break
            symbols.add(symbol)
            positions.append(dict(symbol=symbol, theme=theme, market_value=value))
    if not valid and 'positions' in account:
        reasons.append('account_positions_invalid')
    equity, cash = normalized.get('equity'), normalized.get('available_cash')
    if equity is not None and cash is not None:
        if cash > equity:
            reasons.append('account_available_cash_invalid')
        elif valid:
            with localcontext() as context:
                context.prec = 700
                exposure = sum((_decimal(row['market_value']) for row in positions), _decimal(cash))
                if exposure > _decimal(equity):
                    reasons.append('account_exposure_inconsistent')
    normalized['positions'] = positions
    return (None if reasons else normalized), list(dict.fromkeys(reasons))


def _prices(row):
    plan = _mapping(row.get('plan'))
    low, entry, stop, target = [_number(plan.get(key)) for key in
                              ('entry_low', 'entry_high', 'stop_price', 'target_price')]
    if None in (low, entry, stop, target) or not 0 < stop < low <= entry < target:
        return None, None, None
    return entry, stop, target


def _empty_plan(row, reasons=(), state='held'):
    row = _mapping(row)
    entry, stop, target = _prices(row)
    return dict(opportunity_id=row.get('opportunity_id') if isinstance(row.get('opportunity_id'), str) else '',
        symbol=row.get('symbol') if isinstance(row.get('symbol'), str) else '',
        name=row.get('name', '')[:200] if isinstance(row.get('name'), str) else '',
        status=state, reasons=list(dict.fromkeys(reasons)), quantity=None, weight=0.,
        budget=0., planned_loss=0., entry_price=entry, stop_price=stop, target_price=target)


def _themes(status, candidates):
    """Only explicit saved report classifications can identify a stock's theme."""
    source = _mapping(status.get('report')).get('buy_candidates')
    rows = source[:100] if isinstance(source, list) else []
    result = {}
    for candidate in candidates:
        if not _symbol(candidate.get('symbol')):
            continue
        matches = [_theme(row.get('theme')) for row in rows
                   if isinstance(row, dict) and row.get('symbol') == candidate.get('symbol')]
        if len(matches) == 1 and matches[0] is not None:
            result[candidate['symbol']] = matches[0]
    return result


def _allocate_plans(candidates, account, themes):
    """Allocate sequentially so holdings and preceding plans share every cap.

    The public builder must validate account, quote identity and evidence first.
    This helper has no IO or dispatch path, and accepts only server candidates.
    Decimal arithmetic prevents a rounded cash/risk boundary buying one extra
    share; precision covers the full finite IEEE-754 input exponent range.
    """
    plans = []
    with localcontext() as context:
        context.prec = 700
        equity, cash = _decimal(account['equity']), _decimal(account['available_cash'])
        available = max(Decimal(0), cash - equity * _decimal(LIMITS['cash_floor']))
        symbols, theme_values = {}, {}
        for position in account['positions']:
            symbol, theme, value = position['symbol'], _theme(position['theme']), _decimal(position['market_value'])
            symbols[symbol] = symbols.get(symbol, Decimal(0)) + value
            theme_values[theme] = theme_values.get(theme, Decimal(0)) + value
        for row in candidates:
            plan = _empty_plan(row)
            symbol, theme = row.get('symbol'), _theme(themes.get(row.get('symbol')))
            entry, stop, target = _prices(row)
            kelly = _mapping(row.get('kelly'))
            reference, raw = _number(row.get('reference_weight')), _number(kelly.get('raw_fraction'))
            if theme is None:
                plan['reasons'] = ['theme_unavailable']
            elif entry is None or reference is None or raw is None or reference <= 0 or raw <= 0:
                plan['reasons'] = ['reference_plan_invalid']
            elif len(symbols) > 3 or symbol not in symbols and len(symbols) >= 3:
                plan['reasons'] = ['position_limit_reached']
            elif any(position['symbol'] == symbol and _theme(position['theme']) != theme
                     for position in account['positions']):
                plan['reasons'] = ['holding_theme_mismatch']
            else:
                price, loss = _decimal(entry), _decimal(entry) - _decimal(stop)
                ceiling = min(_decimal(reference), _decimal(raw) * Decimal('.25'), Decimal('.05'), Decimal('.10'))
                symbol_budget = max(Decimal(0), equity * ceiling - symbols.get(symbol, Decimal(0)))
                theme_budget = max(Decimal(0), equity * Decimal('.30') - theme_values.get(theme, Decimal(0)))
                risk_budget = equity * Decimal('.005')
                budget = min(available, symbol_budget, theme_budget, risk_budget * price / loss)
                quantity = int((budget / price).to_integral_value(rounding=ROUND_FLOOR))
                if quantity > MAX_SAFE_INTEGER:
                    plan['reasons'] = ['quantity_not_representable']
                elif quantity <= 0:
                    reason = ('cash_floor_reached' if available <= 0 else
                              'symbol_cap_reached' if symbol_budget <= 0 else
                              'theme_cap_reached' if theme_budget <= 0 else 'minimum_quantity_unavailable')
                    plan['reasons'] = [reason]
                else:
                    spend, planned_loss = price * quantity, loss * quantity
                    plan.update(status='ready', quantity=quantity, weight=float(spend/equity),
                                budget=float(spend), planned_loss=float(planned_loss))
                    available -= spend
                    symbols[symbol] = symbols.get(symbol, Decimal(0)) + spend
                    theme_values[theme] = theme_values.get(theme, Decimal(0)) + spend
            plans.append(plan)
    return plans


def _flow_fx_missing(desk_row):
    missing = desk_row.get('missing')
    missing = {value for value in missing if isinstance(value, str)} if isinstance(missing, list) else set()
    reasons = _mapping(desk_row.get('audit')).get('reasons')
    reasons = reasons if isinstance(reasons, list) else []
    return ({'fx_liquidity', 'flow'} <= missing or {'foreign_flow', 'fx'} <= missing
            or 'fx_and_flow_missing' in reasons)


def _candidate_checks(row, board, desk_row, current, themes):
    reasons, deadlines = [], []
    if (not _symbol(row.get('symbol')) or row.get('market') != 'KR'
            or not _identity(row.get('opportunity_id'))
            or any(row.get(key) != board.get(key) for key in ('decision_id', 'input_fingerprint', 'source_audit_hash'))):
        reasons.append('opportunity_identity_mismatch')
    if not desk_row or any(row.get(key) != desk_row.get(key) for key in ('opportunity_id', 'symbol', 'name')):
        reasons.append('agent_identity_mismatch')
    if row.get('action') != 'entry_candidate':
        reasons.append('current_entry_unavailable')
    if desk_row.get('state') not in ('Watch', 'Conditional plan'):
        reasons.append('agent_entry_unavailable')
    probability = _mapping(desk_row.get('probability'))
    if (probability.get('kind') != 'unavailable' or not all(key in probability and probability[key] is None
            for key in ('bull', 'base', 'bear'))):
        reasons.append('forecast_contract_invalid')
    for value in (board.get('valid_until'), row.get('valid_until'),
                  _mapping(desk_row.get('invalidation')).get('valid_until')):
        deadline = _timestamp(value)
        if deadline is None or deadline <= current:
            reasons.append('plan_expired_or_unavailable')
        else:
            deadlines.append(deadline)
    quoted, fetched = _timestamp(row.get('quote_at')), _timestamp(row.get('fetched_at'))
    price = _number(row.get('current_price'))
    if (None in (quoted, fetched, price) or price <= 0 or row.get('quote_source') != QUOTE_SOURCE):
        reasons.append('current_quote_unavailable')
    elif (not quoted <= fetched <= current or (current-quoted).total_seconds() >= 420
            or (current-fetched).total_seconds() >= 420 or (fetched-quoted).total_seconds() > 120
            or quoted.astimezone(KST).date() != current.astimezone(KST).date()
            or not time(9) <= quoted.astimezone(KST).time().replace(tzinfo=None) < time(15, 30)):
        reasons.append('current_quote_stale_or_future')
    else:
        deadlines.extend((quoted + timedelta(seconds=420), fetched + timedelta(seconds=420)))
    entry, stop, target = _prices(row)
    invalidation = _mapping(desk_row.get('invalidation'))
    if (entry is None or _number(invalidation.get('price_below')) != stop
            or _number(invalidation.get('price_above')) != entry):
        reasons.append('invalidation_identity_mismatch')
    kelly = _mapping(row.get('kelly'))
    if (entry is None or price is None or not stop < price <= entry < target
            or _number(_mapping(row.get('plan')).get('entry_low')) != price
            or _mapping(row.get('plan')).get('basis') != 'observed_quote_reference'
            or any(_number(kelly.get(key)) != value for key, value in
                   (('fraction', .25), ('cap', .05), ('account_risk_cap', .01)))
            or (_number(row.get('reference_weight')) or 0) <= 0
            or (_number(kelly.get('raw_fraction')) or 0) <= 0):
        reasons.append('reference_plan_invalid')
    audit = _mapping(desk_row.get('audit'))
    sources = audit.get('independent_sources')
    if (audit.get('status') != 'passed' or isinstance(sources, bool) or not isinstance(sources, int)
            or sources < 2 or _mapping(row.get('audit')).get('status') != 'passed'):
        reasons.append('source_audit_held')
    missing = desk_row.get('missing')
    if not isinstance(missing, list) or any(not isinstance(value, str) for value in missing):
        reasons.append('source_contract_invalid')
    elif _flow_fx_missing(desk_row):
        reasons.append('flow_and_fx_unavailable')
    if not _symbol(row.get('symbol')) or row['symbol'] not in themes:
        reasons.append('theme_unavailable')
    return list(dict.fromkeys(reasons)), deadlines


def build_account_plan(status, account, *, now=None):
    """Build bounded account arithmetic from the current server projection only."""
    current = datetime.now(timezone.utc) if now is None else _timestamp(now)
    if current is None:
        raise ValueError('timezone_required')
    status = _mapping(status)
    board, desk = _mapping(status.get('opportunity_engine')), _mapping(status.get('agent_desk'))
    candidates = board.get('candidates')
    candidates = [row for row in candidates[:3] if isinstance(row, dict)] if isinstance(candidates, list) else []
    normalized, reasons = _validate_account(account)
    result = dict(schema_version=1, policy_version=POLICY, status='held', reasons=[],
                  generated_at=_stamp(current), valid_until=None, order_allowed=False,
                  limits=dict(LIMITS), plans=[])
    halts = []
    if normalized is not None:
        equity = _decimal(normalized['equity'])
        if _decimal(normalized['daily_pnl']) <= equity * Decimal('-.015'):
            halts.append('daily_loss_limit')
        if _decimal(normalized['weekly_pnl']) <= equity * Decimal('-.04'):
            halts.append('weekly_loss_limit')
    board_candidates = board.get('candidates')
    if (type(board.get('schema_version')) is not int or board.get('schema_version') != 1
            or board.get('policy_version') != 'profit-opportunity-v1'
            or not all(_identity(board.get(key)) for key in ('decision_id', 'input_fingerprint', 'source_audit_hash'))
            or board.get('status') != 'ready' or board.get('research_only') is not True
            or board.get('live_orders') is not False or not isinstance(board_candidates, list)
            or not 1 <= len(board_candidates) <= 3 or len(candidates) != len(board_candidates)
            or len({row.get('symbol') for row in candidates if isinstance(row.get('symbol'), str)}) != len(candidates)):
        reasons.append('current_opportunities_unavailable')
    desk_rows = desk.get('candidates')
    if (type(desk.get('schema_version')) is not int or desk.get('schema_version') != 1
            or desk.get('policy_version') != POLICY
            or desk.get('order_allowed') is not False or _mapping(desk.get('promotion')).get('stage') != 'M0'
            or not isinstance(desk_rows, list) or len(desk_rows) != len(candidates)):
        reasons.append('agent_desk_unavailable')
        desk_rows = []
    generated = _timestamp(desk.get('generated_at'))
    if generated is None or generated > current or (current-generated).total_seconds() >= 420:
        reasons.append('agent_desk_stale_or_future')
    if board.get('entry_session') != current.astimezone(KST).date().isoformat():
        reasons.append('entry_session_mismatch')
    reasons = list(dict.fromkeys(reasons))
    if any(_flow_fx_missing(_mapping(row)) for row in desk_rows):
        halts.append('flow_and_fx_unavailable')
    themes = _themes(status, candidates)
    eligible, held, deadlines = [], {}, []
    if generated is not None and generated <= current:
        deadlines.append(generated + timedelta(seconds=420))
    for index, row in enumerate(candidates):
        desk_row = _mapping(desk_rows[index]) if index < len(desk_rows) else {}
        blocked, until = _candidate_checks(row, board, desk_row, current, themes)
        from .desk_evidence import contract_blockers
        market_reasons, market_until = contract_blockers(desk, board, row, now=current)
        blocked.extend(market_reasons)
        if market_until is not None:
            until.append(market_until)
        deadlines.extend(until)
        if reasons or halts or blocked:
            held[index] = _empty_plan(row, [*halts, *reasons, *blocked], 'halt' if halts else 'held')
        else:
            eligible.append((index, row))
    allocations = iter(_allocate_plans([row for _, row in eligible], normalized, themes) if eligible else [])
    result['plans'] = [held[index] if index in held else next(allocations) for index in range(len(candidates))]
    if deadlines:
        result['valid_until'] = _stamp(min(deadlines))
    result['status'] = 'halt' if halts else 'ready' if any(row['status'] == 'ready' for row in result['plans']) else 'held'
    result['reasons'] = list(dict.fromkeys([*halts, *reasons,
        *(reason for plan in result['plans'] for reason in plan['reasons']), *WARNINGS]))
    return result

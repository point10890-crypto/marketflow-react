"""Causal open-entry paper execution; no data fetching, broker or approval.

Opening exits and buys precede every intraday/closing exit. Allocation limits
apply after entry costs; later market-price drift is reported, not rebalanced.
"""
from dataclasses import asdict, dataclass
from datetime import date
import math
from statistics import fmean, stdev


def _number(value, label, *, minimum=0., positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(label + ' must be a finite number')
    value = float(value)
    if not math.isfinite(value) or value < minimum or positive and value <= 0:
        raise ValueError(label + ' is outside the finite allowed range')
    return value


@dataclass(frozen=True)
class ExecutionPolicy:
    horizon: int = 10
    atr_period: int = 14
    atr_multiplier: float = 2.
    max_stop_fraction: float = .08
    reward_risk: float = 2.
    fee_bps: float = 5.
    slippage_bps: float = 5.
    sell_tax_bps: float = 20.

    def __post_init__(self):
        for key in ('horizon', 'atr_period'):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(key + ' must be a positive integer')
        for key in ('atr_multiplier', 'max_stop_fraction', 'reward_risk'):
            _number(getattr(self, key), key, positive=True)
        if self.max_stop_fraction >= 1:
            raise ValueError('max_stop_fraction must remain below one')
        for key in ('fee_bps', 'slippage_bps', 'sell_tax_bps'):
            _number(getattr(self, key), key)
        if self.fee_bps + self.slippage_bps + self.sell_tax_bps >= 10000:
            raise ValueError('exit costs must remain below the gross proceeds')

    @property
    def entry_cost(self):
        return (self.fee_bps + self.slippage_bps) / 10000

    @property
    def exit_cost(self):
        return self.entry_cost + self.sell_tax_bps / 10000


def _day(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError('date must use canonical YYYY-MM-DD')
    return value


def _quote(row):
    if not isinstance(row, dict) or row.get('quality_flags'):
        return False
    try:
        o, h, l, c = (_number(row[key], key, positive=True) for key in ('open', 'high', 'low', 'close'))
    except (KeyError, ValueError, OverflowError):
        return False
    return l <= min(o, c) <= max(o, c) <= h


def _executable(row):
    if not _quote(row):
        return False
    try:
        return _number(row.get('volume'), 'volume', positive=True) > 0
    except (ValueError, OverflowError):
        return False


def build_bracket_plan(rows, signal_index=None, policy=None):
    """Freeze simple trailing ATR using only the requested observed prefix."""
    policy = policy or ExecutionPolicy()
    if not isinstance(policy, ExecutionPolicy):
        raise ValueError('policy must be an ExecutionPolicy')
    plan = dict(status='warmup', referenceentry_price=None, entry_price=None,
                stop_price=None, target_price=None, atr=None, loss_fraction=None,
                gain_fraction=None, reasons=['insufficient_atr_history'])
    if not rows:
        return plan
    index = len(rows)-1 if signal_index is None else signal_index
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(rows):
        raise ValueError('signal_index is outside the supplied rows')
    if index + 1 < policy.atr_period:
        return plan
    window = rows[max(0, index-policy.atr_period):index+1]
    if any(not _quote(row) for row in window):
        plan.update(status='held', reasons=['invalid_atr_window'])
        return plan
    days = [_day(row['date']) for row in window]
    if any(a >= b for a, b in zip(days, days[1:])):
        raise ValueError('price dates must be unique and chronological')
    ranges, previous = [], None
    for row in window:
        tr = row['high']-row['low']
        if previous is not None:
            tr = max(tr, abs(row['high']-previous), abs(row['low']-previous))
        ranges.append(tr)
        previous = row['close']
    value = fmean(ranges[-policy.atr_period:])
    entry = float(rows[index]['close'])
    if value <= 0:
        plan.update(status='held', atr=value, reasons=['nonpositive_atr'])
        return plan
    distance = min(policy.atr_multiplier * value, entry * policy.max_stop_fraction)
    plan.update(status='ready', referenceentry_price=entry, entry_price=entry,
                stop_price=entry-distance, target_price=entry+policy.reward_risk*distance,
                atr=value, loss_fraction=distance/entry,
                gain_fraction=policy.reward_risk*distance/entry, reasons=[])
    return plan


def _new_trade(symbol, signal_date, bar, plan, policy):
    fill = float(bar['open'])
    distance = min(policy.atr_multiplier*plan['atr'], fill*policy.max_stop_fraction)
    return dict(symbol=symbol, signal_date=signal_date, entry_date=bar['date'],
                entry_price=fill, stop_price=fill-distance,
                target_price=fill+policy.reward_risk*distance, atr=plan['atr'],
                loss_fraction=distance/fill, gain_fraction=policy.reward_risk*distance/fill,
                status='open', exit_date=None, exit_price=None, exit_reason=None,
                holding_sessions=1, gross_return=None, net_return=None, ambiguous_bar=False)


def _gap(bar, trade):
    if bar['open'] <= trade['stop_price']:
        return float(bar['open']), 'stop_gap'
    if bar['open'] >= trade['target_price']:
        return float(bar['open']), 'target_gap'
    return None


def _barrier(bar, trade):
    if bar['low'] <= trade['stop_price']:
        return trade['stop_price'], 'stop'
    if bar['high'] >= trade['target_price']:
        return trade['target_price'], 'target'
    return None


def _finish(trade, bar, price, reason, sessions, policy):
    trade.update(status='closed', exit_date=bar['date'], exit_price=price,
                 exit_reason=reason, holding_sessions=sessions,
                 gross_return=price/trade['entry_price']-1,
                 net_return=price*(1-policy.exit_cost)/(trade['entry_price']*(1+policy.entry_cost))-1,
                 ambiguous_bar=reason == 'stop' and bar['high'] >= trade['target_price'])


def simulate_trade(rows, signal_index, policy=None):
    """One next-observed-open entry, with unresolved outcomes kept null."""
    policy = policy or ExecutionPolicy()
    plan = build_bracket_plan(rows, signal_index, policy)
    entry_index = signal_index+1
    if plan['status'] != 'ready' or entry_index >= len(rows) or not _executable(rows[entry_index]):
        return None
    bar = rows[entry_index]
    if _day(bar['date']) <= _day(rows[signal_index]['date']):
        raise ValueError('entry must follow the signal session')
    symbol = rows[signal_index].get('symbol', rows[signal_index].get('code'))
    trade = _new_trade(symbol, rows[signal_index]['date'], bar, plan, policy)
    for index in range(entry_index, len(rows)):
        bar, sessions = rows[index], index-entry_index+1
        trade['holding_sessions'] = sessions
        if not _executable(bar):
            continue
        hit = (_gap(bar, trade) if index > entry_index else None) or _barrier(bar, trade)
        if hit is None and sessions >= policy.horizon:
            hit = float(bar['close']), 'time'
        if hit:
            _finish(trade, bar, *hit, sessions, policy)
            break
    return trade


def _metrics(curve, capital):
    if not curve:
        return dict(net_total_return=0., cagr=None, max_drawdown=0., sharpe=None)
    final = curve[-1]['equity']
    days = (date.fromisoformat(curve[-1]['date'])-date.fromisoformat(curve[0]['date'])).days
    try:
        cagr = (final/capital)**(365.25/days)-1 if days > 0 else None
    except OverflowError:
        cagr = None
    peak, drawdown = capital, 0.
    for point in curve:
        peak = max(peak, point['equity'])
        drawdown = min(drawdown, point['equity']/peak-1)
    returns = [b['equity']/a['equity']-1 for a, b in zip(curve, curve[1:])]
    sd = stdev(returns) if len(returns) > 1 else 0.
    sharpe = fmean(returns)/sd*math.sqrt(252) if sd > 0 else None
    return dict(net_total_return=final/capital-1, cagr=cagr,
                max_drawdown=drawdown, sharpe=sharpe)


def simulate_portfolio(prices_by_symbol, decisions, policy=None, initial_cash=1.,
                       cash_buffer=.4, max_positions=3, position_cap=.2):
    """Replay closing decisions as next-calendar-open paper orders.

    Missing or nontradable next-session quotes cancel that opening order. No
    intraday proceeds or closing NAV are available to the opening allocation.
    """
    policy = policy or ExecutionPolicy()
    if not isinstance(policy, ExecutionPolicy):
        raise ValueError('policy must be an ExecutionPolicy')
    initial_cash = _number(initial_cash, 'initial_cash', positive=True)
    cash_buffer = _number(cash_buffer, 'cash_buffer')
    position_cap = _number(position_cap, 'position_cap', positive=True)
    if not .4 <= cash_buffer < 1 or position_cap > .2:
        raise ValueError('allocation limits must preserve at least 40% cash and at most 20% per position')
    if isinstance(max_positions, bool) or not isinstance(max_positions, int) or not 1 <= max_positions <= 3:
        raise ValueError('max_positions must be between one and three')
    lookup, indices, calendar = {}, {}, set()
    for symbol, rows in prices_by_symbol.items():
        quotes, local = {}, {}
        previous = None
        for index, row in enumerate(rows):
            day = _day(row['date'])
            if previous is not None and day <= previous:
                raise ValueError('price dates must be unique and chronological')
            quotes[day], local[day], previous = row, index, day
            calendar.add(day)
        lookup[symbol], indices[symbol] = quotes, local
    for day in decisions:
        _day(day)
    cash, positions, trades, fills, curve = initial_cash, {}, [], [], []
    pending, previous_day = [], None

    def nav():
        return cash+sum(p['quantity']*p['last_mark'] for p in positions.values())

    def sell(symbol, day_index, bar, price, reason):
        nonlocal cash
        position = positions.pop(symbol)
        trade, quantity = position['trade'], position['quantity']
        gross = quantity*price
        cost = gross*policy.exit_cost
        cash += gross-cost
        _finish(trade, bar, price, reason, day_index-position['entry_index']+1, policy)
        trade.update(exit_cost=cost, net_profit=gross-cost-trade['notional']-trade['entry_cost'])
        fills.append(dict(date=bar['date'], symbol=symbol, side='SELL', price=price,
                          quantity=quantity, notional=gross, cost=cost, reason=reason))

    for day_index, day in enumerate(sorted(calendar)):
        # Only observable opening marks and executable gap exits precede buys.
        for symbol, position in list(positions.items()):
            bar = lookup[symbol].get(day)
            if _quote(bar):
                position['last_mark'] = float(bar['open'])
            if _executable(bar):
                hit = _gap(bar, position['trade'])
                if hit:
                    sell(symbol, day_index, bar, *hit)
        for order in pending:
            symbol = order.get('symbol')
            if symbol not in lookup or symbol in positions or len(positions) >= max_positions:
                continue
            bar = lookup[symbol].get(day)
            signal_index = indices[symbol].get(previous_day)
            if signal_index is None or not _executable(bar):
                continue
            weight = min(position_cap, _number(order.get('weight'), 'weight'))
            if weight <= 0:
                continue
            plan = build_bracket_plan(prices_by_symbol[symbol], signal_index, policy)
            if plan['status'] != 'ready':
                continue
            value = nav()
            # Solve cash_after >= buffer * NAV_after, including entry fees.
            room = (cash-cash_buffer*value)/(1+policy.entry_cost*(1-cash_buffer))
            notional = min(weight*value/(1+weight*policy.entry_cost), room)
            if notional <= value*1e-12:
                continue
            quantity, cost = notional/bar['open'], notional*policy.entry_cost
            cash -= notional+cost
            trade = _new_trade(symbol, previous_day, bar, plan, policy)
            trade.update(quantity=quantity, notional=notional, entry_cost=cost,
                         exit_cost=None, net_profit=None,
                         allocation_weight=notional/(value-cost))
            trades.append(trade)
            positions[symbol] = dict(trade=trade, quantity=quantity, last_mark=float(bar['open']), entry_index=day_index)
            fills.append(dict(date=day, symbol=symbol, side='BUY', price=float(bar['open']),
                              quantity=quantity, notional=notional, cost=cost, reason='next_open',
                              allocation_weight=trade['allocation_weight']))
        # Now, and only now, intraday barriers and closing time exits occur.
        for symbol, position in list(positions.items()):
            bar = lookup[symbol].get(day)
            sessions = day_index-position['entry_index']+1
            position['trade']['holding_sessions'] = sessions
            if _executable(bar):
                hit = _barrier(bar, position['trade'])
                if hit is None and sessions >= policy.horizon:
                    hit = float(bar['close']), 'time'
                if hit:
                    sell(symbol, day_index, bar, *hit)
                    continue
            if _quote(bar):
                position['last_mark'] = float(bar['close'])
        value = nav()
        exposure = (value-cash)/value
        curve.append(dict(date=day, equity=value, cash=cash, exposure=exposure))
        pending, previous_day = list(decisions.get(day, [])), day
    max_exposure = max((point['exposure'] for point in curve), default=0.)
    return dict(equity=curve, trades=trades, fills=fills, metrics=_metrics(curve, initial_cash),
                open_positions=[dict(position['trade']) for position in positions.values()],
                policy=asdict(policy),
                mark_policy='observed_valid_open_then_close; missing_quotes_carry_last_observed_mark',
                allocation_limits=dict(cash_buffer=cash_buffer, max_exposure=1-cash_buffer,
                                       position_cap=position_cap, max_positions=max_positions,
                                       basis='post_entry_cost_opening_NAV; subsequent_price_drift_not_rebalanced'),
                observed_limit_drift=dict(max_exposure=max_exposure,
                                          exposure_above_allocation_limit=max_exposure > 1-cash_buffer+1e-12))

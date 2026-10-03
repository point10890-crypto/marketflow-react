"""Paper-only execution actor: persisted approval, bounded rebalance, no broker."""
from __future__ import annotations

import hashlib
import json
import math
import re
from decimal import Decimal, localcontext

from .models import AgentMessage, create_message
from .store import iso_date, normalize_portfolio, safe_identifier


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()


def _decimal(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('Paper prices and weights require finite numeric values')
    try:
        if not math.isfinite(value):
            raise ValueError('Paper prices and weights require finite numeric values')
    except OverflowError:
        raise ValueError('Paper numeric value exceeds the supported range') from None
    return Decimal(str(value))


def _symbols(rows):
    if not isinstance(rows, list) or any(not isinstance(row, dict) or not re.fullmatch(r'\d{6}', str(row.get('symbol') or '')) for row in rows):
        raise ValueError('Paper selection requires explicit stock identities')
    return {row['symbol'] for row in rows}


class ExecutionAgent:
    def __init__(self, store):
        self.store = store

    def _authorize(self, message):
        if not isinstance(message, AgentMessage) or message.stage != 'approval':
            raise ValueError('Execution requires an approval message')
        # Reconstruct and verify both hashes rather than trusting a supplied ID.
        message = AgentMessage.from_dict(message.to_dict())
        chain, parent = {}, None
        for stage in ('request', 'data', 'quant', 'risk', 'approval'):
            stored = self.store.load_stage(message.run_id, stage)
            if stored is None:
                raise ValueError('Execution requires the complete persisted CIO evidence chain')
            current = AgentMessage.from_dict(stored)
            if current.run_id != message.run_id or current.stage != stage:
                raise ValueError('Persisted evidence has an invalid run or stage identity')
            if parent is None:
                if current.parent_id is not None:
                    raise ValueError('Persisted request has an invalid parent')
            elif current.parent_id != parent.message_id or any(key not in current.payload or _hash(current.payload[key]) != _hash(value)
                    for key, value in parent.payload.items()):
                raise ValueError('Persisted evidence chain rewrote a parent or upstream payload')
            chain[stage], parent = current, current
        if chain['approval'].message_id != message.message_id:
            raise ValueError('Execution requires the exact persisted CIO approval')
        risk = chain['risk']
        payload = message.to_dict()['payload']
        approval, input_value = payload['approval'], payload['input']
        if message.parent_id != risk.message_id or approval.get('risk_message_id') != risk.message_id:
            raise ValueError('Approval does not identify its persisted risk parent')
        if any(_hash(payload.get(key)) != _hash(risk.payload.get(key)) for key in ('input', 'data', 'quant', 'risk')):
            raise ValueError('Approval changed the stored risk input or evidence snapshot')
        if approval.get('targets_sha256') != _hash(risk.payload['risk']['targets']):
            raise ValueError('Approval target digest does not match the risk target map')
        if approval.get('account_id') != input_value.get('account_id') or approval.get('execution_date') != input_value.get('execution', {}).get('date'):
            raise ValueError('Approval account or date does not match its execution request')
        return message, payload

    def _held(self, message, payload, reason):
        input_value = payload['input']
        account_id = safe_identifier(input_value['account_id'])
        portfolio = self.store.load_account(account_id) or normalize_portfolio(input_value['portfolio'])
        result = dict(status='held', fills=[], portfolio=portfolio, account_id=account_id,
            date=input_value.get('execution', {}).get('date'), daily_slot_reused=False, reason=reason)
        output = create_message(message.run_id, 'execution', dict(payload, execution=result), message.message_id)
        self.store.save_stage(message.run_id, 'execution', output.to_dict())
        return output

    @staticmethod
    def _prepare(payload):
        input_value, risk, data, quant = (payload[key] for key in ('input', 'risk', 'data', 'quant'))
        account_id = safe_identifier(input_value['account_id'])
        portfolio = normalize_portfolio(input_value['portfolio'])
        execution = input_value['execution']
        as_of, execution_date = iso_date(input_value['as_of']), iso_date(execution['date'])
        if execution_date <= as_of:
            raise ValueError('Paper execution must follow the closed observation date')
        targets = risk['targets']
        if not isinstance(targets, dict):
            raise ValueError('Paper target weights must be a symbol map')
        weights = {}
        for symbol, value in targets.items():
            if not isinstance(symbol, str) or not re.fullmatch(r'\d{6}', symbol):
                raise ValueError('Target symbol is invalid')
            weight = _decimal(value)
            if not Decimal(0) <= weight <= Decimal('0.2'):
                raise ValueError('Paper position target exceeds the hard weight cap')
            if weight:
                weights[symbol] = weight
        if len(weights) > 3 or sum(weights.values(), Decimal(0)) > Decimal('0.6'):
            raise ValueError('Paper targets exceed position count or exposure limits')
        ranked, qualified, candidates = _symbols(data['ranked']), _symbols(quant['qualified']), _symbols(quant['candidates'])
        eligible_raw = data['eligible_symbols']
        if not isinstance(eligible_raw, list):
            raise ValueError('Paper quality eligibility must be an explicit list')
        eligible = set(eligible_raw)
        if not set(weights) <= ranked & eligible & qualified:
            raise ValueError('Paper targets must remain ranked, quality eligible and independently qualified')
        if any(symbol not in candidates for symbol in weights if portfolio['positions'].get(symbol, 0) == 0):
            raise ValueError('New paper positions require a fresh candidate')
        quotes = execution['quotes']
        if not isinstance(quotes, dict):
            raise ValueError('Paper execution requires explicit quotes')
        verified_quotes = {}
        for symbol in set(portfolio['positions']) | set(weights):
            quote = quotes.get(symbol)
            if not isinstance(quote, dict) or quote.get('date') != execution_date:
                raise ValueError('Paper quote is missing or belongs to another date')
            price, volume = _decimal(quote['price']), _decimal(quote['volume'])
            if price <= 0 or volume <= 0 or not isinstance(quote.get('source'), str) or not quote['source'].strip():
                raise ValueError('Paper quote requires a positive price, positive volume and source')
            verified_quotes[symbol] = dict(quote, decimal_price=price)
        cost = _decimal(execution.get('cost_bps', 5)) / Decimal(10000)
        slippage = _decimal(execution.get('slippage_bps', 10)) / Decimal(10000)
        tax = _decimal(execution.get('sell_tax_bps', 0)) / Decimal(10000)
        if any(not Decimal(0) <= rate < Decimal(1) for rate in (cost, slippage, tax)) or cost + tax >= 1:
            raise ValueError('Paper cost assumptions must permit positive sale proceeds')
        return dict(account_id=account_id, portfolio=portfolio, date=execution_date, weights=weights,
                    quotes=verified_quotes, cost=cost, slippage=slippage, tax=tax, identities={row['symbol']: row for row in data['ranked']})

    @staticmethod
    def _rebalance(plan, portfolio):
        """Solve post-cost target NAV before applying sells then buys.

        Sizing from pre-fee NAV can exceed 20%/60% after costs. The fixed point
        accounts for each side's slippage, fee and sale tax before allocating.
        Quantities are fractional research quantities, never brokerage orders.
        """
        with localcontext() as context:
            context.prec = 42
            cash = _decimal(portfolio['cash'])
            before = {s: _decimal(q) for s, q in portfolio['positions'].items()}
            quotes, weights = plan['quotes'], plan['weights']
            prices = {s: quote['decimal_price'] for s, quote in quotes.items()}
            symbols = sorted(set(before) | set(weights))
            nav_before = cash + sum((q * prices[s] for s, q in before.items()), Decimal(0))
            cost, slip, tax = plan['cost'], plan['slippage'], plan['tax']
            buy_loss, sell_loss = slip + cost * (1 + slip), slip + (cost + tax) * (1 - slip)
            def loss(nav):
                total = Decimal(0)
                for symbol in symbols:
                    desired = weights.get(symbol, Decimal(0)) * nav / prices[symbol]
                    change = desired - before.get(symbol, Decimal(0))
                    total += abs(change) * prices[symbol] * (buy_loss if change > 0 else sell_loss)
                return total
            low, high = Decimal(0), nav_before
            for _ in range(160):
                middle = (low + high) / 2
                if middle == low or middle == high:
                    break
                if nav_before - loss(middle) >= middle:
                    low = middle
                else:
                    high = middle
            after = {}
            for symbol, weight in weights.items():
                desired = weight * low / prices[symbol]
                quantity = float(desired)
                if not math.isfinite(quantity):
                    raise ValueError('Paper quantity exceeds the supported finite range')
                # Round down so JSON float representation cannot increase a cap.
                if quantity > 0 and Decimal(str(quantity)) > desired:
                    quantity = math.nextafter(quantity, 0)
                if quantity:
                    after[symbol] = Decimal(str(quantity))
            fills = []
            for side in ('SELL', 'BUY'):
                for symbol in symbols:
                    change = after.get(symbol, Decimal(0)) - before.get(symbol, Decimal(0))
                    if (side == 'SELL' and change >= 0) or (side == 'BUY' and change <= 0):
                        continue
                    quantity = abs(change)
                    price = prices[symbol] * (1 - slip if side == 'SELL' else 1 + slip)
                    gross, slippage_amount = quantity * price, quantity * prices[symbol] * slip
                    fee = gross * cost
                    sale_tax = gross * tax if side == 'SELL' else Decimal(0)
                    delta = gross - fee - sale_tax if side == 'SELL' else -gross - fee
                    cash += delta
                    identity = plan['identities'].get(symbol, {})
                    fills.append(dict(symbol=symbol, name=identity.get('name'), market=identity.get('market'), side=side,
                        quantity=float(quantity), quote_price=float(prices[symbol]), price=float(price),
                        gross_value=float(gross), fee=float(fee), tax=float(sale_tax), slippage_amount=float(slippage_amount),
                        cash_delta=float(delta), date=plan['date'], source=quotes[symbol]['source']))
            updated = normalize_portfolio(dict(cash=float(cash), positions={s: float(q) for s, q in after.items()}))
            nav = _decimal(updated['cash']) + sum((_decimal(q) * prices[s] for s, q in updated['positions'].items()), Decimal(0))
            tolerance = max(nav, Decimal(1)) * Decimal('1e-12')
            if _decimal(updated['cash']) + tolerance < nav * Decimal('0.4') or any(_decimal(q) * prices[s] > nav * Decimal('0.2') + tolerance for s, q in updated['positions'].items()):
                raise ValueError('Post-cost paper portfolio violates the hard cash or position limits')
            return dict(status='executed', fills=fills, portfolio=updated, account_id=plan['account_id'],
                date=plan['date'], daily_slot_reused=False, reason='approved_paper_rebalance',
                nav_before=float(nav_before), nav_after=float(nav), fractional_quantities=True,
                cost_assumptions=dict(cost_bps=float(cost * 10000), slippage_bps=float(slip * 10000), sell_tax_bps=float(tax * 10000)))

    async def handle(self, incoming):
        try:
            message, payload = self._authorize(incoming)
            cached = self.store.load_stage(message.run_id, 'execution')
            if cached is not None:
                saved = AgentMessage.from_dict(cached)
                if saved.parent_id != message.message_id:
                    raise ValueError('Cached paper result has a different approval parent')
                return saved
            if payload['approval'].get('decision') != 'approved':
                return self._held(message, payload, 'approval_held')
            if payload['approval'].get('mode') != 'paper':
                return self._held(message, payload, 'paper_mode_only')
            if payload['data'].get('status') != 'ready' or payload['risk'].get('status') != 'approved':
                return self._held(message, payload, 'source_or_risk_held')
            try:
                plan = self._prepare(payload)
            except (ValueError, TypeError, KeyError, OverflowError):
                return self._held(message, payload, 'invalid_execution_or_risk_constraints')
            def build(portfolio):
                result = self._rebalance(plan, portfolio)
                return create_message(message.run_id, 'execution', dict(payload, execution=result), message.message_id).to_dict()
            outcome = self.store.execute_paper(run_id=message.run_id, account_id=plan['account_id'], execution_date=plan['date'],
                supplied_portfolio=plan['portfolio'], approval_message_id=message.message_id, build_message=build)
            if outcome['status'] == 'duplicate_day':
                result = dict(status='duplicate_day', fills=[], portfolio=outcome['portfolio'], account_id=plan['account_id'],
                    date=plan['date'], daily_slot_reused=True, reason='account_already_rebalanced_for_date')
                output = create_message(message.run_id, 'execution', dict(payload, execution=result), message.message_id)
                self.store.save_stage(message.run_id, 'execution', output.to_dict())
                return output
            return AgentMessage.from_dict(outcome['message'])
        except Exception as error:
            if isinstance(incoming, AgentMessage):
                try:
                    self.store.record_error(incoming.run_id, 'execution', type(error).__name__)
                except Exception:
                    pass
            raise ValueError('Paper execution validation or transaction failed') from None

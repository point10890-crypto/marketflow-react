"""Independent empirical Kelly limits and supplied paper-account valuation."""
from __future__ import annotations

import copy
import math

from ..kelly_research import _failed_metrics
from .models import AgentMessage, create_message
from .quant_agent import finite_number, iso_day, research_configuration, universe_map


DEFAULT_LIMITS = {'max_weight': .2, 'max_exposure': .6, 'min_cash': .4,
                  'max_positions': 3, 'kelly_fraction': .5, 'volatility_threshold': .03}


def risk_limits(request):
    config = request.get('config', {})
    if not isinstance(config, dict) or set(config) - {'research', 'risk'}:
        raise ValueError('Configuration requires nested sections')
    overrides = config.get('risk', {})
    if not isinstance(overrides, dict) or set(overrides) - set(DEFAULT_LIMITS):
        raise ValueError('Unknown risk limit')
    limits = dict(DEFAULT_LIMITS, **overrides)
    count = limits['max_positions']
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 3:
        raise ValueError('Position limit exceeds three')
    for key in ('max_weight', 'max_exposure', 'kelly_fraction'):
        limits[key] = finite_number(limits[key], key, minimum=0, maximum=DEFAULT_LIMITS[key])
        if limits[key] <= 0:
            raise ValueError('Allocation limits must be positive')
    limits['min_cash'] = finite_number(limits['min_cash'], 'min cash', minimum=.4, maximum=1)
    limits['volatility_threshold'] = finite_number(limits['volatility_threshold'], 'volatility threshold', minimum=0)
    if limits['volatility_threshold'] <= 0:
        raise ValueError('Volatility threshold must be positive')
    return limits


def _metric_check(metrics, cfg):
    if not isinstance(metrics, dict):
        raise ValueError('Missing train/validation metrics')
    n = metrics.get('samples')
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise ValueError('Invalid sample count')
    p = finite_number(metrics['win_rate'], 'win rate', minimum=0, maximum=1)
    lower = finite_number(metrics['win_lower'], 'Wilson lower', minimum=0, maximum=1)
    finite_number(metrics['payoff'], 'payoff', minimum=0)
    finite_number(metrics['expected_net_return'], 'net expectancy')
    z = cfg['confidence_z']
    calculated = (p + z*z/(2*n) - z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))) / (1 + z*z/n)
    if lower > max(0., calculated) + 1e-9 or _failed_metrics(metrics, cfg):
        raise ValueError('Independent train/validation gates failed')


def _qualified_row(raw, identities, cfg):
    if not isinstance(raw, dict) or raw.get('eligible') is not True:
        raise ValueError('Candidate is not independently qualified')
    symbol = raw.get('symbol')
    if symbol not in identities or any(raw.get(key) != identities[symbol][key] for key in ('name', 'market')):
        raise ValueError('Candidate identity differs from the supplied universe')
    _metric_check(raw.get('train'), cfg)
    _metric_check(raw.get('validation'), cfg)
    row = {key: copy.deepcopy(raw[key]) for key in ('symbol', 'name', 'market', 'train', 'validation')}
    row.update(estimated_kelly=finite_number(raw['estimated_kelly'], 'empirical Kelly', minimum=0, maximum=1),
               prior_volatility=finite_number(raw['prior_volatility'], 'prior volatility', minimum=0))
    return row


class RiskAgent:
    async def handle(self, message: AgentMessage) -> AgentMessage:
        if not isinstance(message, AgentMessage) or message.stage != 'quant':
            raise ValueError('Risk stage requires a quant message')
        payload = copy.deepcopy(message.payload)
        request, data, quant = payload.get('input'), payload.get('data'), payload.get('quant')
        result = dict(status='held', reasons=[], targets={}, max_exposure=.6, min_cash=.4,
                      max_weight=.2, max_positions=3, candidate_evidence=[], orders=[])
        payload['risk'] = result
        if isinstance(data, dict) and data.get('status') == 'blocked':
            result['reasons'] = ['data_blocked', *data.get('reasons', [])]
            return create_message(message.run_id, 'risk', payload, message.message_id)
        try:
            if not isinstance(request, dict) or not isinstance(data, dict) or data.get('status') != 'ready':
                raise ValueError('Data is not ready')
            if not isinstance(quant, dict) or quant.get('status') not in {'ready', 'held'}:
                raise ValueError('Quant state is malformed')
            if quant.get('qualification_complete') is not True:
                result['reasons'] = ['quant_not_completed']
                return create_message(message.run_id, 'risk', payload, message.message_id)
            identities = universe_map(request, data.get('ranked'))
            limits, cfg = risk_limits(request), research_configuration(request)
            result.update(limits)
            as_of = iso_day(request['as_of'])
            if quant.get('as_of') != as_of or quant.get('frozen_at') != request['splits']['validation_end']:
                raise ValueError('Qualification identity or frozen date differs')
            execution = request['execution']
            execution_date = iso_day(execution['date'])
            if execution_date <= as_of:
                raise ValueError('Execution requires a supplied subsequent session')
            portfolio = request['portfolio']
            cash = finite_number(portfolio['cash'], 'portfolio cash', minimum=0)
            positions = portfolio['positions']
            if not isinstance(positions, dict):
                raise ValueError('Positions require a quantity map')
            quantities = {symbol: finite_number(quantity, 'position quantity', minimum=0)
                          for symbol, quantity in positions.items()}
            if any(not isinstance(symbol, str) or not symbol.strip() for symbol in quantities):
                raise ValueError('Invalid held symbol')
            held = {symbol for symbol, quantity in quantities.items() if quantity > 0}
            quotes = execution['quotes']
            if not isinstance(quotes, dict):
                raise ValueError('Execution quotes require a mapping')
            prices = {}
            for symbol, quote in quotes.items():
                if not isinstance(quote, dict) or quote.get('date') != execution_date:
                    raise ValueError('Execution quote is stale or malformed')
                price = finite_number(quote.get('price'), 'execution quote price', minimum=0)
                volume = finite_number(quote.get('volume'), 'execution quote volume', minimum=0)
                if price <= 0 or volume <= 0 or not isinstance(quote.get('source'), str) or not quote['source'].strip():
                    raise ValueError('Quote is not executable or has no source')
                prices[symbol] = price
            if held - set(prices):
                raise ValueError('A held position has no current execution quote')
            costs = {key: finite_number(execution.get(key, default), key, minimum=0)
                     for key, default in (('cost_bps', 5.), ('slippage_bps', 10.), ('sell_tax_bps', 0.))}
            if sum(costs.values()) >= 10000:
                raise ValueError('Execution costs exceed the allowed range')
            equity = cash + sum(quantity * prices[symbol] for symbol, quantity in quantities.items() if quantity > 0)
            finite_number(equity, 'portfolio equity', minimum=0)
            result.update(portfolio_equity=equity, execution_date=execution_date, execution_costs=costs)
            eligible = data.get('eligible_symbols')
            if not isinstance(eligible, list) or len(eligible) > 100 or not set(eligible).issubset(identities):
                raise ValueError('Risk scope differs from the approved universe')
            qualifications, candidates = quant.get('qualified'), quant.get('candidates')
            if not isinstance(qualifications, list) or not isinstance(candidates, list):
                raise ValueError('Qualification and candidate lists are required')
            qualified = {}
            for raw in qualifications:
                row = _qualified_row(raw, identities, cfg)
                symbol = row['symbol']
                if symbol not in eligible or symbol in qualified:
                    raise ValueError('Duplicate or unapproved qualified symbol')
                qualified[symbol] = row
            fresh = {}
            for raw in candidates:
                row = _qualified_row(raw, identities, cfg)
                symbol = row['symbol']
                if (symbol not in qualified or symbol in fresh or raw.get('has_current_signal') is not True
                        or raw.get('signal_date') != as_of):
                    raise ValueError('New position lacks a fresh qualified signal')
                if finite_number(raw.get('signal_z'), 'current signal z') > cfg['z_threshold']:
                    raise ValueError('New position does not meet the empirical signal threshold')
                if any(row[key] != qualified[symbol][key] for key in ('train', 'validation', 'estimated_kelly')):
                    raise ValueError('Candidate differs from the frozen qualification')
                fresh[symbol] = row
            allowable = (held & set(qualified)) | set(fresh)
            chosen = sorted((fresh.get(symbol, qualified[symbol]) for symbol in allowable),
                            key=lambda row: (-row['validation']['expected_net_return'], row['symbol']))[:limits['max_positions']]
            if any(row['symbol'] not in prices for row in chosen):
                raise ValueError('A selected position lacks an executable quote')
            targets = {}
            evidence = []
            for row in chosen:
                base = min(limits['max_weight'], limits['kelly_fraction'] * row['estimated_kelly'])
                reduced = row['prior_volatility'] > limits['volatility_threshold']
                weight = base * (.5 if reduced else 1.)
                if weight > 0:
                    targets[row['symbol']] = weight
                    evidence.append(dict(row, base_target_weight=base, target_weight=weight,
                                         high_volatility_reduction=reduced,
                                         new_position=row['symbol'] not in held))
            maximum = min(limits['max_exposure'], 1. - limits['min_cash'])
            total = sum(targets.values())
            if total > maximum and total > 0:
                factor = maximum / total
                targets = {symbol: weight * factor for symbol, weight in targets.items()}
            if equity <= 0:
                result.update(status='held', reasons=['no_portfolio_equity'])
            elif targets or held:
                for symbol in sorted(held - set(targets)):
                    targets[symbol] = 0.
                for row in evidence:
                    row['target_weight'] = targets[row['symbol']]
                result.update(status='approved', reasons=['risk_exit'] if not any(targets.values()) else [],
                              targets=targets, candidate_evidence=evidence,
                              target_exposure=sum(targets.values()),
                              qualification_frozen_at=quant['frozen_at'])
            else:
                result.update(status='held', reasons=['no_fresh_or_existing_qualified_position'])
        except (ValueError, KeyError, TypeError, IndexError, OverflowError):
            result.update(status='rejected', reasons=['invalid_risk_input_or_evidence'], targets={}, candidate_evidence=[])
        return create_message(message.run_id, 'risk', payload, message.message_id)

"""Frozen train/validation research with an explicit current-signal gate."""
from __future__ import annotations

import asyncio
import copy
import math
from datetime import date

from ..kelly_research import DEFAULT_CONFIG, _configuration, run_research
from .models import AgentMessage, create_message


def finite_number(value, label, *, minimum=None, maximum=None):
    try:
        valid = not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid or minimum is not None and value < minimum or maximum is not None and value > maximum:
        raise ValueError(f'Invalid finite {label}')
    return float(value)


def iso_day(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError('Date requires YYYY-MM-DD')
    return value


def universe_map(request, ranked=None):
    source = request.get('universe')
    if not isinstance(source, list) or not source:
        raise ValueError('The source listing is required')
    originals = {}
    for row in source:
        if not isinstance(row, dict) or not isinstance(row.get('symbol'), str) or row['symbol'] in originals:
            raise ValueError('Source listing identities are malformed or duplicated')
        originals[row['symbol']] = row
    rows = source if ranked is None else ranked
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        raise ValueError('Universe requires one to one hundred rows')
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Universe rows require objects')
        for key in ('symbol', 'name', 'market'):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError('Universe identity is incomplete')
        if row['symbol'] in result:
            raise ValueError('Universe contains duplicate symbols')
        original = originals.get(row['symbol'])
        if original is None or original.get('name') != row['name']:
            raise ValueError('Ranked identity is not present in the source listing')
        market = 'KOSDAQ' if original.get('market') == 'KOSDAQ GLOBAL' else original.get('market')
        if market != row['market']:
            raise ValueError('Ranked market identity differs from the source listing')
        result[row['symbol']] = row
    return result


class _UnsupportedKellyModel(ValueError):
    """The trading agent contract accepts empirical net-return sizing only."""


def research_configuration(request):
    config = request.get('config', {})
    if not isinstance(config, dict) or set(config) - {'research', 'risk'}:
        raise ValueError('Configuration requires nested research/risk objects')
    research = config.get('research', {})
    if not isinstance(research, dict) or not isinstance(config.get('risk', {}), dict):
        raise ValueError('Configuration sections require objects')
    if research.get('kelly_model', 'empirical') != 'empirical':
        raise _UnsupportedKellyModel('Trading agents require empirical Kelly; generalized Kelly is offline research only')
    research = copy.deepcopy(research)
    # Allocation overrides cannot relax the architecture's hard limits.
    for field, maximum in (('max_weight', .2), ('max_exposure', .6), ('kelly_fraction', .5)):
        if field in research:
            research[field] = min(finite_number(research[field], field, minimum=0), maximum)
    if 'max_positions' in research:
        value = research['max_positions']
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError('Invalid max_positions')
        research['max_positions'] = min(value, 3)
    return _configuration(research)


class QuantAgent:
    def __init__(self, *, research_runner=None):
        self._research_runner = research_runner or run_research

    async def handle(self, message: AgentMessage) -> AgentMessage:
        if not isinstance(message, AgentMessage) or message.stage != 'data':
            raise ValueError('Quant stage requires a data message')
        payload = copy.deepcopy(message.payload)
        request, data = payload.get('input'), payload.get('data')
        quant = dict(status='held', reasons=[], candidates=[], qualified=[], qualification=[], qualification_complete=False,
                     frozen_at=None, as_of=request.get('as_of') if isinstance(request, dict) else None,
                     config={}, methodology='empirical_net_returns_no_distribution_assumption')
        payload['quant'] = quant
        if isinstance(data, dict) and data.get('status') == 'blocked':
            quant['reasons'] = ['data_blocked', *data.get('reasons', [])]
            return create_message(message.run_id, 'quant', payload, message.message_id)
        try:
            if not isinstance(request, dict) or not isinstance(data, dict) or data.get('status') != 'ready':
                raise ValueError('Data is not ready')
            identities = universe_map(request, data.get('ranked'))
            eligible = data.get('eligible_symbols')
            if not isinstance(eligible, list) or len(eligible) > 100 or len(set(eligible)) != len(eligible):
                raise ValueError('Invalid eligible scope')
            if any(not isinstance(symbol, str) or symbol not in identities for symbol in eligible):
                raise ValueError('Eligible scope is outside the requested universe')
            as_of = iso_day(request['as_of'])
            splits = request['splits']
            train, validation, test = (iso_day(splits[key]) for key in ('train_end', 'validation_end', 'test_end'))
            if not train < validation < test <= as_of:
                raise ValueError('Splits are unordered or extend after as_of')
            cfg = research_configuration(request)
            quant.update(config=cfg, frozen_at=validation)
            if not eligible:
                quant['reasons'] = ['no_eligible_symbols']
                quant['qualification_complete'] = True
                return create_message(message.run_id, 'quant', payload, message.message_id)
            source_prices, source_fundamentals = data['prices'], data['fundamentals']
            if not isinstance(source_prices, list) or not isinstance(source_fundamentals, list):
                raise ValueError('Scoped data requires price/fundamental lists')
            if any(not isinstance(row, dict) for row in source_prices + source_fundamentals):
                raise ValueError('Scoped data contains a malformed row')
            prices = [row for row in source_prices if row.get('symbol') in eligible
                      and iso_day(row.get('date')) <= as_of]
            fundamentals = [row for row in source_fundamentals if row.get('symbol') in eligible
                            and iso_day(row.get('available_date')) <= as_of]
            benchmark = request.get('benchmark_symbol')
            if benchmark is not None and benchmark not in eligible:
                raise ValueError('Benchmark is outside the approved price scope')
            report = await asyncio.to_thread(self._research_runner, prices, fundamentals,
                train_end=train, validation_end=validation, test_end=test,
                benchmark_symbol=benchmark, config=cfg)
            if not isinstance(report, dict) or not isinstance(report.get('qualification'), list):
                raise ValueError('Research returned an invalid report')
            frozen = []
            for raw in report['qualification']:
                symbol = raw['symbol']
                if symbol not in eligible or not isinstance(raw.get('eligible'), bool):
                    raise ValueError('Research qualification is outside the approved scope')
                item = {key: copy.deepcopy(raw[key]) for key in ('symbol', 'eligible', 'reason', 'train',
                        'validation', 'estimated_kelly', 'prior_volatility')}
                item.update(name=identities[symbol]['name'], market=identities[symbol]['market'],
                            has_current_signal=False)
                finite_number(item['estimated_kelly'], 'estimated Kelly', minimum=0, maximum=1)
                if item['prior_volatility'] is not None:
                    finite_number(item['prior_volatility'], 'prior volatility', minimum=0)
                frozen.append(item)
            quant['qualification'] = frozen
            quant['qualified'] = [row for row in frozen if row['eligible'] and row['estimated_kelly'] > 0]
            quant['qualification_complete'] = True
            by_symbol = {row['symbol']: row for row in quant['qualified']}
            selected = report.get('selected_symbols', [])
            if not isinstance(selected, list) or len(selected) > 3 or len(set(selected)) != len(selected):
                raise ValueError('Research selected too many positions')
            signals = report.get('signals', [])
            if not isinstance(signals, list):
                raise ValueError('Research signals are malformed')
            candidates = []
            seen = set()
            for signal in signals:
                symbol = signal.get('symbol')
                if symbol in seen:
                    raise ValueError('Duplicate current signal')
                seen.add(symbol)
                if (symbol not in selected or symbol not in by_symbol or signal.get('eligible') is not True
                        or signal.get('fundamental_ok') is not True
                        or signal.get('date') != as_of or signal.get('as_of') != as_of):
                    continue
                item = copy.deepcopy(by_symbol[symbol])
                signal_z = finite_number(signal['z'], 'signal z')
                if signal_z > cfg['z_threshold']:
                    raise ValueError('Signal does not meet the configured empirical threshold')
                item.update(has_current_signal=True, signal_date=as_of,
                            signal_z=signal_z,
                            prior_volatility=finite_number(signal['prior_volatility'], 'signal prior volatility', minimum=0))
                candidates.append(item)
            candidates.sort(key=lambda row: (-row['validation']['expected_net_return'], row['symbol']))
            quant['candidates'] = candidates[:3]
            quant['status'] = 'ready' if candidates else 'held'
            quant['reasons'] = [] if candidates else ['no_fresh_qualified_signal']
            quant['warnings'] = report.get('warnings', [])
            quant['benchmark'] = report.get('benchmark')
        except _UnsupportedKellyModel:
            quant.update(status='held', reasons=['unsupported_agent_kelly_model'],
                         candidates=[], qualified=[], qualification=[], qualification_complete=False)
        except (ValueError, KeyError, TypeError, IndexError, OverflowError):
            quant.update(status='held', reasons=['invalid_quant_input_or_research'],
                         candidates=[], qualified=[], qualification=[], qualification_complete=False)
        return create_message(message.run_id, 'quant', payload, message.message_id)

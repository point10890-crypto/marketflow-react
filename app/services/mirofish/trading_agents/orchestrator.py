"""Async CIO coordination with content-checked recovery and paper-only approval."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import math
from contextlib import nullcontext
from datetime import date, datetime, timezone
from pathlib import Path

from filelock import FileLock

from ..kelly_research import DEFAULT_CONFIG, _failed_metrics
from .data_agent import _evidence
from .models import AgentMessage, create_message
from .quant_agent import research_configuration
from .risk_agent import risk_limits

STAGE_ORDER = ('request', 'data', 'quant', 'risk', 'approval', 'execution')
ACTOR_STAGES = ('data', 'quant', 'risk', 'execution')


class PipelineError(RuntimeError):
    def __init__(self, stage, error_type):
        self.stage, self.error_type = stage, error_type
        super().__init__(f'Trading stage {stage} failed ({error_type}); completed stages retained')


def targets_hash(targets):
    return hashlib.sha256(json.dumps(targets, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()


def _number(value, *, minimum=0, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('Expected a finite numerical risk field')
    try:
        valid = math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid or value < minimum or (maximum is not None and value > maximum):
        raise ValueError('Risk field exceeds its permitted range')
    return float(value)


def _statistics_verified(row, cfg):
    if row.get('eligible') is not True:
        return False
    cfg = dict(cfg)
    for key in ('min_samples', 'min_win_rate', 'min_win_lower', 'min_payoff'):
        cfg[key] = max(cfg[key], DEFAULT_CONFIG[key])
    for split in ('train', 'validation'):
        stats = row.get(split) or {}
        try:
            n = stats.get('samples')
            if isinstance(n, bool) or not isinstance(n, int) or n < 1:
                return False
            probability = _number(stats.get('win_rate'), maximum=1)
            lower = _number(stats.get('win_lower'), maximum=1)
            _number(stats.get('payoff'))
            _number(stats.get('expected_net_return'))
            z = cfg['confidence_z']
            calculated = (probability + z*z/(2*n) - z*math.sqrt(
                probability*(1-probability)/n + z*z/(4*n*n))) / (1 + z*z/n)
            if lower > max(0., calculated) + 1e-9 or _failed_metrics(stats, cfg):
                return False
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            return False
    return True


def _indexed(rows):
    if not isinstance(rows, list):
        raise ValueError('Expected a list of stock identities')
    result = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('symbol'), str) or not row['symbol'].strip():
            raise ValueError('Stock identity is incomplete')
        if row['symbol'] in result:
            raise ValueError('Stock identity is duplicated')
        result[row['symbol']] = row
    return result


def cio_approval(message):
    """Vetoes are independent of an actor's own approval label."""
    payload = copy.deepcopy(message.payload)
    request = payload['input']
    data, quant, risk = (payload.get(key) or {} for key in ('data', 'quant', 'risk'))
    targets, reasons = risk.get('targets') or {}, []
    if not isinstance(targets, dict):
        targets = {}
        reasons.append('invalid_target_map')
    if data.get('status') != 'ready':
        reasons.append('data_not_verified')
    if risk.get('status') != 'approved':
        reasons.append('risk_not_approved')
    try:
        evidence = request.get('evidence') or {}
        evidence_reasons = _evidence(evidence, datetime.now(timezone.utc))
        if evidence_reasons:
            reasons.extend(['source_evidence_not_verified', *evidence_reasons])
        metadata = data.get('metadata') or {}
        for key in ('source_timestamps', 'source_hashes', 'price_adjustment_verified',
                    'financial_vintage_verified', 'synthetic'):
            expected = evidence.get(key, False if key == 'synthetic' else None)
            if targets_hash(metadata.get(key)) != targets_hash(expected):
                reasons.append('data_provenance_mismatch')
        limits, cfg = risk_limits(request), research_configuration(request)
        max_weight, max_exposure, min_cash = (limits[key] for key in ('max_weight', 'max_exposure', 'min_cash'))
        fraction, max_positions = limits['kelly_fraction'], limits['max_positions']
        if quant.get('qualification_complete') is not True:
            reasons.append('qualification_not_complete')
        weights = [_number(weight, maximum=max_weight) for weight in targets.values()]
        if sum(weight > 0 for weight in weights) > max_positions:
            reasons.append('too_many_positions')
        if sum(weights) > min(max_exposure, 1 - min_cash) + 1e-12:
            reasons.append('exposure_or_cash_floor')
        ranked = _indexed(data.get('ranked', []))
        allowed = set(data.get('eligible_symbols') or [])
        qualified = _indexed(quant.get('qualified', []))
        candidates = _indexed(quant.get('candidates', []))
        portfolio = request.get('portfolio') or {}
        positions = portfolio.get('positions') or {}
        _number(portfolio.get('cash'))
        for quantity in positions.values():
            _number(quantity)
        for symbol, weight in targets.items():
            if not isinstance(symbol, str) or not symbol.strip():
                raise ValueError('Target symbol is invalid')
            if weight == 0:
                if positions.get(symbol, 0) <= 0:
                    reasons.append('exit_without_positive_holding')
                continue
            row = qualified.get(symbol)
            if symbol not in allowed or symbol not in ranked or row is None:
                reasons.append('target_outside_validated_cohort')
                continue
            if any(row.get(field) != ranked[symbol].get(field) for field in ('name', 'market')):
                reasons.append('target_identity_mismatch')
            if not _statistics_verified(row, cfg):
                reasons.append('qualification_not_verified')
            empirical = _number(row.get('estimated_kelly'), maximum=1)
            candidate = candidates.get(symbol)
            sizing_row = candidate or row
            if candidate is not None:
                if (candidate.get('eligible') is not True or candidate.get('has_current_signal') is not True
                        or candidate.get('signal_date') != request['as_of']
                        or any(candidate.get(key) != row.get(key) for key in
                               ('name', 'market', 'train', 'validation', 'estimated_kelly'))):
                    reasons.append('fresh_signal_or_qualification_mismatch')
                if _number(candidate.get('signal_z'), minimum=-math.inf) > cfg['z_threshold']:
                    reasons.append('current_signal_threshold_not_met')
            volatility = _number(sizing_row.get('prior_volatility'))
            permitted = min(max_weight, fraction * empirical)
            if volatility > limits['volatility_threshold']:
                permitted *= .5
            if weight > permitted + 1e-12:
                reasons.append('weight_exceeds_empirical_kelly')
            if positions.get(symbol, 0) <= 0 and symbol not in candidates:
                reasons.append('new_entry_without_fresh_signal')
        execution = request.get('execution') or {}
        execution_date = execution.get('date')
        if date.fromisoformat(execution_date) <= date.fromisoformat(request['as_of']):
            reasons.append('execution_not_after_observation')
        quotes = execution.get('quotes') or {}
        for symbol in set(targets) | {symbol for symbol, qty in positions.items() if qty > 0}:
            quote = quotes.get(symbol) or {}
            if _number(quote.get('price')) <= 0 or _number(quote.get('volume')) <= 0:
                reasons.append('unexecutable_quote')
            if quote.get('date') != execution_date or not str(quote.get('source') or '').strip():
                reasons.append('quote_date_or_source_unverified')
        if not targets and not any(qty > 0 for qty in positions.values()):
            reasons.append('no_qualified_position')
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        reasons.append('invalid_risk_or_execution_contract')
    approval = {'decision': 'held' if reasons else 'approved',
                'reason': ','.join(sorted(set(reasons))) if reasons else 'risk_limits_verified',
                'risk_message_id': message.message_id, 'targets_sha256': targets_hash(targets),
                'mode': 'paper', 'account_id': request.get('account_id'),
                'execution_date': (request.get('execution') or {}).get('date')}
    payload['approval'] = approval
    return create_message(message.run_id, 'approval', payload, message.message_id)


class TradingOrchestrator:
    def __init__(self, database=None, *, store=None, actors=None, stage_timeout=60.):
        if isinstance(stage_timeout, bool) or not isinstance(stage_timeout, (int, float)) or not math.isfinite(stage_timeout) or not 0 < stage_timeout <= 60:
            raise ValueError('Stage timeout must be positive and at most 60 seconds')
        self.stage_timeout = float(stage_timeout)
        self.database = Path(database) if database is not None else None
        if store is None:
            from .store import AgentStore
            self.database = self.database or Path(__file__).resolve().parents[4] / 'data/kelly_research/trading_agents/agents.sqlite'
            store = AgentStore(self.database)
        self.store = store
        if actors is None:
            from .data_agent import DataAgent
            from .quant_agent import QuantAgent
            from .risk_agent import RiskAgent
            from .execution_agent import ExecutionAgent
            actors = {'data': DataAgent(), 'quant': QuantAgent(), 'risk': RiskAgent(),
                      'execution': ExecutionAgent(store)}
        if set(actors) != set(ACTOR_STAGES):
            raise ValueError('Four independent data/quant/risk/execution actors are required')
        self.actors = actors

    async def _serve(self, stage, queue):
        while True:
            message, reply = await queue.get()
            try:
                output = await self.actors[stage].handle(message)
                if not reply.done():
                    reply.set_result(output)
            except asyncio.CancelledError:
                if not reply.done():
                    reply.cancel()
                raise
            except Exception as error:
                if not reply.done():
                    reply.set_exception(error)
            finally:
                queue.task_done()

    @staticmethod
    def _validate(message, parent, stage):
        if not isinstance(message, AgentMessage):
            raise ValueError('Actor did not return an AgentMessage')
        # Serial round trip also verifies the immutable content identifier.
        checked = AgentMessage.from_dict(message.to_dict())
        if checked.run_id != parent.run_id or checked.stage != stage or checked.parent_id != parent.message_id:
            raise ValueError('Actor message has the wrong run, stage or parent')
        if targets_hash(checked.payload.get('input')) != targets_hash(parent.payload.get('input')):
            raise ValueError('Actor changed the immutable run input')
        for previous in ('data', 'quant', 'risk', 'approval'):
            if previous in parent.payload and targets_hash(checked.payload.get(previous)) != targets_hash(parent.payload[previous]):
                raise ValueError('Actor changed completed upstream evidence')
        return checked

    @staticmethod
    def _report(chain):
        initial = chain[0]
        request = initial.payload['input']
        output = copy.deepcopy(chain[-1].payload)
        execution = output['execution']
        status = {'executed': 'completed', 'duplicate_day': 'duplicate_day'}.get(execution['status'], 'held')
        return {'schema_version': 1, 'run_id': initial.run_id, 'request_message_id': initial.message_id,
                'status': status, 'paper_only': True, 'live_orders': False,
                'performance_claims_allowed': False, 'current_cohort_bias': True,
                'synthetic': bool((request.get('evidence') or {}).get('synthetic')),
                'stages': [{'stage': m.stage, 'message_id': m.message_id, 'parent_id': m.parent_id} for m in chain],
                'data': output['data'], 'quant': output['quant'], 'risk': output['risk'],
                'approval': output['approval'], 'execution': execution}

    def _verified_report(self, initial, report):
        stored = AgentMessage.from_dict(self.store.load_stage(initial.run_id, 'request'))
        if stored.message_id != initial.message_id:
            raise ValueError('Cached report request identity does not match')
        chain = [stored]
        for stage in STAGE_ORDER[1:]:
            current = AgentMessage.from_dict(self.store.load_stage(initial.run_id, stage))
            chain.append(self._validate(current, chain[-1], stage))
        expected = self._report(chain)
        if targets_hash(report) != targets_hash(expected):
            raise ValueError('Cached report does not match its complete stage chain')
        return expected

    async def run(self, request, *, run_id):
        initial = create_message(run_id, 'request', {'input': request})
        request = copy.deepcopy(initial.payload['input'])
        lock = FileLock(str(self.database) + f'.{run_id}.lock', timeout=0) if self.database is not None else nullcontext()
        with lock:
            self.store.begin_run(run_id, initial.message_id)
            previous_report = self.store.load_report(run_id)
            if previous_report is not None:
                try:
                    return self._verified_report(initial, previous_report)
                except Exception as error:
                    self.store.record_error(run_id, 'execution', type(error).__name__)
                    raise PipelineError('execution', type(error).__name__) from None
            self.store.save_stage(run_id, 'request', initial.to_dict())
            queues = {stage: asyncio.Queue(maxsize=1) for stage in ACTOR_STAGES}
            tasks = [asyncio.create_task(self._serve(stage, queue), name=f'{run_id}:{stage}')
                     for stage, queue in queues.items()]
            chain, previous, stage = [initial], initial, 'request'
            try:
                for stage in STAGE_ORDER[1:]:
                    cached = self.store.load_stage(run_id, stage)
                    if cached is not None:
                        current = self._validate(AgentMessage.from_dict(cached), previous, stage)
                    elif stage == 'approval':
                        current = cio_approval(previous)
                    elif stage == 'execution' and previous.payload['approval']['decision'] != 'approved':
                        payload = copy.deepcopy(previous.payload)
                        payload['execution'] = {'status': 'held', 'fills': [],
                                                'portfolio': copy.deepcopy(request.get('portfolio') or {}),
                                                'account_id': request.get('account_id'),
                                                'date': (request.get('execution') or {}).get('date'),
                                                'daily_slot_reused': False, 'reason': 'cio_veto'}
                        current = create_message(run_id, 'execution', payload, previous.message_id)
                    else:
                        reply = asyncio.get_running_loop().create_future()
                        await queues[stage].put((previous, reply))
                        current = await asyncio.wait_for(reply, self.stage_timeout)
                        current = self._validate(current, previous, stage)
                    self.store.save_stage(run_id, stage, current.to_dict())
                    chain.append(current)
                    previous = current
                report = self._report(chain)
                self.store.save_report(run_id, report)
                return report
            except Exception as error:
                self.store.record_error(run_id, stage, type(error).__name__)
                raise PipelineError(stage, type(error).__name__) from None
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

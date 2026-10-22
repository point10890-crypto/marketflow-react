"""Separate versioned candidate evidence; never mutates legacy experiment files."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
import hashlib
import math
from pathlib import Path
import re

from filelock import FileLock

from . import store
from .execution import ExecutionPolicy

POLICY = 'contextual-candidates-v4'
LEGACY_POLICY = 'cross-sectional-candidates-v3'
KST = timezone(timedelta(hours=9))


def _clock(now=None):
    return datetime.fromisoformat(store.timestamp(now).replace('Z', '+00:00'))


def _load(path, default=None):
    raw = store._read(Path(path))
    if raw is None:
        return deepcopy(default)
    if not isinstance(raw, dict) or set(raw) != {'data', 'sha256'} or raw['sha256'] != store._hash(raw['data']):
        raise ValueError('candidate_integrity')
    return raw['data']


def _save(path, data):
    store._write(Path(path), dict(data=data, sha256=store._hash(data)))


def _code_hash():
    names = ('candidate_store.py', 'candidate_service.py', 'candidate_detection.py', 'candidate_learning.py',
             'candidate_inputs.py', 'daily_source.py', 'candidate_execution.py', 'execution.py')
    base = Path(__file__).parent
    return store._hash({name: hashlib.sha256((base/name).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
                       if (base/name).is_file() else 'not_implemented' for name in names})


def _protocol(root, inputs, now, *, policy_version=POLICY):
    path = root/'protocol.json'
    contract = inputs['provenance']['source_contract_hash']
    policy = dict(policy_version=policy_version, code_hash=_code_hash(), source_contract_hash=contract,
                  decision_sessions=60, maturation_sessions=10, approved_exposure=0., live_orders=False,
                  promotion='human_review_only_not_automatic', costs_bps=dict(fee=5, slippage=5, sell_tax=20))
    saved = _load(path)
    if saved is not None:
        if any(saved.get(key) != value for key, value in policy.items()):
            raise ValueError('candidate_policy_changed')
        return saved
    saved = dict(policy, declared_at=store.timestamp(now),
                 earliest_session=(_clock(now).astimezone(KST).date()+timedelta(days=1)).isoformat())
    saved['protocol_hash'] = store._hash(saved)
    _save(path, saved)
    return saved


def read_decisions(root):
    value = _load(Path(root)/'decisions.json', dict(schema_version=1, records=[]))
    if value.get('schema_version') != 1 or not isinstance(value.get('records'), list) or len(value['records']) > 730:
        raise ValueError('candidate_journal_integrity')
    sessions = set()
    for row in value['records']:
        if (row.get('sha256') != store._hash({k:v for k,v in row.items() if k != 'sha256'})
                or row['desk']['decision_id'] != store._hash({k:v for k,v in row['desk'].items() if k != 'decision_id'})
                or row['desk']['latest_session'] in sessions):
            raise ValueError('candidate_decision_integrity')
        sessions.add(row['desk']['latest_session'])
    return value


def set_attempt(root, state, *, now=None, error=None):
    if state not in ('running', 'complete', 'failed'):
        raise ValueError('candidate_attempt_state')
    value = dict(state=state, at=store.timestamp(now), error=error if error in
                 ('source_unavailable', 'analysis_unavailable', 'calendar_unavailable') else None)
    _save(Path(root)/'attempt.json', value)


def _number(value, *, low=None, high=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('candidate_numeric')
    if low is not None and value < low or high is not None and value > high:
        raise ValueError('candidate_numeric')
    return float(value)


def _integer(value, *, low=0, high=1000000):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('candidate_numeric')
    return value


def _day(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError('candidate_session')
    return value


def _text(value, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise ValueError('candidate_text')
    return value


def _stats(value):
    samples = _integer(value['samples'])
    wins = _integer(value['wins'], high=samples)
    blocks = _integer(value['block_count'], high=samples)
    symbols = _integer(value['unique_symbols'], high=samples)
    if samples:
        rate = _number(value['win_rate'], low=0, high=1)
        if not math.isclose(rate, wins/samples, rel_tol=1e-9, abs_tol=1e-9):
            raise ValueError('candidate_evidence')
        net, stress = _number(value['mean_net_return']), _number(value['stress_mean_net_return'])
    else:
        if any(value[key] is not None for key in ('win_rate', 'mean_net_return', 'stress_mean_net_return')):
            raise ValueError('candidate_evidence')
        net = stress = None
    return dict(samples=samples, blocks=blocks, symbols=symbols, net=net, stress=stress)


def _validate_new(desk, inputs, now):
    """Validate semantics before any first decision or declaration is written."""
    try:
        created = _clock(desk['generated_at']); current = _clock(now)
        source = _clock(desk['source']['captured_at'])
        day = created.astimezone(KST).date().isoformat()
        version, candidates = desk['policy_version'], desk['candidates']
        if (type(desk.get('schema_version')) is not int or desk['schema_version'] != 1
                or version not in (POLICY, LEGACY_POLICY)
                or desk.get('input_fingerprint') != inputs['input_fingerprint']
                or re.fullmatch(r'[0-9a-f]{64}', desk['input_fingerprint']) is None
                or _day(desk['latest_session']) != inputs['latest_session'] or desk['latest_session'] > day
                or created != current or source > created
                or _number(desk['approved_exposure']) != 0 or desk.get('live_orders') is not False
                or desk['source'].get('provider') != 'KIS' or desk['source'].get('venue') != 'KRX'
                or desk['source'].get('adjusted_requested') is not True
                or not isinstance(candidates, list) or len(candidates) > 3
                or desk.get('state') not in ('ready', 'held')
                or (desk['state'] == 'ready') != bool(candidates)):
            raise ValueError('candidate_binding')
        if desk.get('entry_session') is not None:
            expiry = _clock(desk['valid_until']).astimezone(KST)
            if (_day(desk['entry_session']) <= day or expiry.date().isoformat() != desk['entry_session']
                    or (expiry.hour, expiry.minute, expiry.second, expiry.microsecond) != (15, 30, 0, 0)):
                raise ValueError('candidate_entry_not_prospective')
        elif candidates or desk.get('valid_until') is not None:
            raise ValueError('candidate_entry_not_prospective')
        phases = {key: _stats(desk['evidence'][key]) for key in ('formation', 'confirmation')}
        model = desk.get('model')
        if version == POLICY:
            if (not isinstance(model, dict) or model.get('name') != 'causal-context-neighbors-v1'
                    or model.get('status') != 'experimental' or model.get('validation') != 'forward_collecting'
                    or model.get('comparison_interpretation') != 'v3_unconditional_retrospective_control_not_v4_holdout'):
                raise ValueError('candidate_context')
            training_end = model.get('training_end')
            if training_end is not None and _day(training_end) >= desk['latest_session']:
                raise ValueError('candidate_context')
            if candidates and training_end is None:
                raise ValueError('candidate_context')
        elif candidates:
            for key, count, blocks in (('formation', 30, 5), ('confirmation', 10, 3)):
                phase = phases[key]
                if (phase['samples'] < count or phase['blocks'] < blocks
                        or phase['net'] is None or phase['net'] <= 0 or phase['stress'] <= 0
                        or key == 'formation' and phase['symbols'] < 5):
                    raise ValueError('candidate_global_evidence')
        symbols, ranks = set(), set()
        for candidate in candidates:
            symbol = candidate['symbol']
            rank = _integer(candidate['rank'], low=1, high=3)
            if (not isinstance(symbol, str) or re.fullmatch(r'[0-9]{6}', symbol) is None
                    or symbol == '000000' or symbol in symbols or rank in ranks
                    or symbol not in inputs['prices_by_symbol'] or candidate['quote_session'] != desk['latest_session']):
                raise ValueError('candidate_identity')
            symbols.add(symbol); ranks.add(rank)
            _text(candidate['name'], 120); _number(candidate['strength_score'], low=0, high=100)
            facts = candidate['reason_facts']
            if not isinstance(facts, list) or not 1 <= len(facts) <= 12:
                raise ValueError('candidate_facts')
            for fact in facts:_text(fact, 600)
            plan, risk = candidate['plan'], candidate['risk']
            entry, upper, stop, target = (_number(plan[key], low=1e-12, high=1e12)
                for key in ('entry_price', 'entry_upper', 'stop_price', 'target_price'))
            loss = _number(plan['loss_fraction'], low=1e-12, high=.08+1e-9)
            if (not stop < entry <= upper < target or type(plan['horizon_sessions']) is not int
                    or plan['horizon_sessions'] != 10 or not math.isclose(loss, 1-stop/entry, rel_tol=1e-9, abs_tol=1e-9)):
                raise ValueError('candidate_plan')
            latest = inputs['prices_by_symbol'][symbol][-1]
            if latest['date'] != desk['latest_session'] or _number(latest['close']) != entry:
                raise ValueError('candidate_source_price')
            raw = _number(risk['raw_kelly'], low=0, high=1)
            cap = .01 if version == POLICY else .05
            weight = _number(risk['reference_weight'], low=0, high=cap)
            adjusted = _number(risk['adjusted_kelly'], low=0, high=.25)
            planned_loss = _number(risk['planned_account_loss'], low=0, high=.01)
            if (raw <= 0 or weight <= 0 or _number(risk['kelly_fraction']) != .25
                    or not math.isclose(adjusted, .25*raw, rel_tol=1e-9, abs_tol=1e-12)
                    or weight > min(adjusted, .01/loss)+1e-12
                    or not math.isclose(planned_loss, weight*loss, rel_tol=1e-9, abs_tol=1e-12)
                    or _number(risk['approved_exposure']) != 0 or risk['live_orders'] is not False):
                raise ValueError('candidate_risk')
            if version == POLICY:
                context = candidate['model_evidence']; counts = _stats(context)
                if (counts['samples'] < 30 or counts['blocks'] < 5 or counts['symbols'] < 5
                        or context.get('neighbors_exclude_target') is not True
                        or context.get('training_end') != model['training_end']
                        or any(_number(context[key]) <= 0 for key in ('mean_net_return', 'stress_mean_net_return',
                                                                    'expected_net_return', 'expected_stress_net_return'))):
                    raise ValueError('candidate_context')
    except (ValueError, KeyError, TypeError, IndexError, AttributeError, OverflowError):
        raise ValueError('candidate_semantics') from None


def _decision_day(record):
    return _clock(record['created_at']).astimezone(KST).date().isoformat()


def _in_fixed_window(journal, protocol, moment):
    day = _clock(moment).astimezone(KST).date().isoformat()
    used = {_decision_day(row) for row in journal['records'] if row['in_fixed_window']}
    return day >= protocol['earliest_session'] and day not in used and len(used) < protocol['decision_sessions']


def publish(root, desk, inputs, *, now=None):
    """Freeze the first result for a price session; even cash gets a record."""
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    moment = store.timestamp(now)
    with FileLock(str(root/'publication.lock'), timeout=30):
        journal = read_decisions(root)
        existing = next((r for r in journal['records'] if r['desk']['latest_session'] == desk['latest_session']), None)
        if existing:
            value = deepcopy(existing['desk'])
            _protocol(root, inputs, moment, policy_version=value['policy_version'])
        else:
            _validate_new(desk, inputs, moment)
            protocol = _protocol(root, inputs, moment, policy_version=desk['policy_version'])
            if len(journal['records']) >= 730:
                raise ValueError('candidate_archive_required')
            value = deepcopy(desk)
            value['protocol'] = dict(protocol_hash=protocol['protocol_hash'],
                declared_at=protocol['declared_at'], earliest_session=protocol['earliest_session'],
                decision_sessions=60, maturation_sessions=10)
            value['decision_id'] = store._hash(value)
            signal = {symbol:deepcopy(rows[-61:]) for symbol,rows in inputs['prices_by_symbol'].items()}
            _save(root/'signals'/f"{value['decision_id']}.json", signal)
            record = dict(desk=value, created_at=moment, source_contract_hash=inputs['provenance']['source_contract_hash'],
                          signal_hash=store._hash(signal),
                          in_fixed_window=_in_fixed_window(journal, protocol, moment))
            record['sha256'] = store._hash(record)
            journal['records'].append(record)
            _save(root/'decisions.json', journal)
        # Repair partial publication from the newest sealed price session. An
        # old-session replay must never move this pointer or observation back.
        newest = max(journal['records'], key=lambda row: row['desk']['latest_session'])['desk']
        pointer = _load(root/'current.json')
        if pointer is None or pointer.get('decision_id') != newest['decision_id']:
            _save(root/'current.json', dict(decision_id=newest['decision_id']))
    if inputs['latest_session'] >= newest['latest_session']:
        observe(root, inputs, now=moment)
        set_attempt(root, 'complete', now=moment)
    return deepcopy(value)


def _forward(root, record, signal, inputs, now, blocked):
    """Same v3 conditional-entry execution in formation and forward observation."""
    from .candidate_execution import simulate_candidate_trade, normalize_candidate_rows
    desk = record['desk']; root.mkdir(parents=True, exist_ok=True)
    prices = inputs['prices_by_symbol']; moment = store.timestamp(now)
    observed_day = _clock(now).astimezone(KST).date().isoformat()
    with FileLock(str(root/'forward.lock'), timeout=30):
        journal = store.read_journal(root)
        if not journal['decisions'] and desk['candidates']:
            frozen = dict(decision_date=_clock(record['created_at']).astimezone(KST).date().isoformat(),
                created_at=record['created_at'], price_as_of=desk['latest_session'],
                candidates=deepcopy(desk['candidates']), provenance=dict(price_basis='KIS:J:D:adjusted_requested'),
                policy=asdict(ExecutionPolicy()), entry_session=desk['entry_session'],
                snapshots={row['symbol']:deepcopy(signal[row['symbol']][-15:]) for row in desk['candidates']})
            journal['decisions'].append(dict(frozen, sha256=store._hash(frozen), outcomes=[
                store._seal_result(dict(symbol=row['symbol'],status='pending',net_return=None),
                                   frozen,row,signal,frozen['decision_date']) for row in desk['candidates']]))
        for decision in journal['decisions']:
            updated = []
            by_symbol = {row['symbol']:row for row in decision['outcomes']}
            for candidate in decision['candidates']:
                previous = by_symbol[candidate['symbol']]
                report = dict(provenance=decision['provenance'])
                previous = store._record_revision(previous, decision, report, prices, moment)
                if (blocked or previous['source_revisions'] or previous['status'] in ('closed','unfilled','source_revision')):
                    updated.append(previous); continue
                symbol = candidate['symbol']; original = decision['snapshots'][symbol]
                future = [row for row in prices.get(symbol,[]) if decision['entry_session'] <= row['date'] <= observed_day]
                if not future or future[0]['date'] != decision['entry_session']:
                    updated.append(previous); continue
                calendar = sorted({row['date'] for rows in prices.values() for row in rows
                                   if decision['entry_session'] <= row['date'] <= future[-1]['date']})
                if [row['date'] for row in future] != calendar:
                    updated.append(previous); continue
                trade = simulate_candidate_trade(original+future,len(original)-1,
                    ExecutionPolicy(**decision['policy']),reference_plan=candidate['plan'])
                result = dict(symbol=symbol,status='unfilled',net_return=None) if trade is None else dict(
                    symbol=symbol,status=trade['status'],entry_date=trade['entry_date'],
                    exit_date=trade.get('exit_date'),net_return=trade.get('net_return'),exit_reason=trade.get('exit_reason'))
                if trade is not None:
                    interval = normalize_candidate_rows([row for row in future
                        if trade.get('exit_date') is None or row['date'] <= trade['exit_date']])
                    if any(row.get('volume',0)<=0 or row.get('tradable') is False or row.get('quality_flags') for row in interval):
                        result['evidence_excluded_nontradable'] = True
                updated.append(store._seal_result(result,decision,candidate,prices,observed_day))
            decision['outcomes'] = updated
        journal['sha256'] = store._hash({k:v for k,v in journal.items() if k!='sha256'})
        store._write(root/'forward.json',journal)
    outcomes = [r for d in journal['decisions'] for r in d['outcomes']]
    valid = [r['net_return'] for r in outcomes if r['status']=='closed' and not r['source_revisions']
             and not r.get('evidence_excluded_nontradable') and not blocked]
    return dict(decisions=len(journal['decisions']),matured=len(valid),
        win_rate=sum(v>0 for v in valid)/len(valid) if valid else None,
        mean_net_return=sum(valid)/len(valid) if valid else None,
        counts={state:sum(r['status']==state for r in outcomes) for state in
                ('pending','open','closed','unfilled','source_revision')},
        excluded_source_revised_decision=blocked,basis='frozen_conditional_next_official_open_not_account_pnl')


def observe(root, inputs, *, now=None):
    """Advance only this desk's paper records and preserve source corrections."""
    root = Path(root)
    with FileLock(str(root/'observation.lock'), timeout=30):
        journal = read_decisions(root)
        observations = _load(root/'observations.json', dict(records={}))
        for record in journal['records']:
            desk = record['desk']; identity = desk['decision_id']
            signal = _load(root/'signals'/f'{identity}.json')
            if store._hash(signal) != record['signal_hash']:
                raise ValueError('candidate_signal_integrity')
            reasons = []
            if record['source_contract_hash'] != inputs['provenance']['source_contract_hash']:
                reasons.append('source_contract_changed')
            for symbol, rows in signal.items():
                replacement = {r['date']:r for r in inputs['prices_by_symbol'].get(symbol, [])}
                if any(bar['date'] not in replacement for bar in rows):
                    reasons.append('signal_data_missing')
                if any(bar['date'] in replacement and any(bar.get(k) != replacement[bar['date']].get(k)
                       for k in ('open','high','low','close','volume','traded_value')) for bar in rows):
                    reasons.append('source_revision')
            if (desk['entry_session'] and inputs['latest_session'] >= desk['entry_session']
                    and any(not any(r['date']==desk['entry_session'] for r in inputs['prices_by_symbol'].get(c['symbol'],[]))
                            for c in desk['candidates'])):
                reasons.append('official_entry_data_missing')
            # The frozen helper detects changed bars and ADDED union sessions,
            # but intentionally does not treat absent bars as revisions. Check
            # consumed identities explicitly here, including dates removed from
            # EVERY symbol, before simulation can shrink the holding calendar.
            forward_journal = store.read_journal(root/'forward'/identity)
            missing_consumed = []
            for decision in forward_journal['decisions']:
                for outcome in decision['outcomes']:
                    available = {bar['date'] for bar in inputs['prices_by_symbol'].get(outcome['symbol'], [])}
                    missing_consumed.extend(dict(symbol=outcome['symbol'], date=bar['date'])
                        for bar in outcome['consumed_ohlcv'] if bar['date'] not in available)
            if missing_consumed:
                reasons.append('consumed_price_data_missing')
            reasons = sorted(set(reasons))
            previous = observations['records'].get(identity, {})
            revisions = list(previous.get('revisions', []))
            if reasons:
                evidence = dict(reasons=reasons, fingerprint=inputs['input_fingerprint'],
                                missing_consumed_prices=missing_consumed)
                digest = store._hash(evidence)
                if not any(row['hash'] == digest for row in revisions):
                    revisions.append(dict(hash=digest, observed_at=store.timestamp(now), **evidence))
            forward = _forward(root/'forward'/identity,record,signal,inputs,now,bool(revisions))
            observations['records'][identity] = dict(revisions=revisions, forward=forward)
        _save(root/'observations.json', observations)


def read_public(root, *, now=None):
    """Cheap saved-only projection; no locks, fetches, fitting or file writes."""
    root = Path(root)
    try:
        pointer = _load(root/'current.json')
        if pointer is None:
            return None
        record = next(r for r in read_decisions(root)['records'] if r['desk']['decision_id'] == pointer['decision_id'])
        desk = deepcopy(record['desk']); current = _clock(now)
        attempt = _load(root/'attempt.json') or {}
        observations = _load(root/'observations.json', dict(records={}))['records'].get(desk['decision_id'], {})
        if observations.get('revisions'):
            desk['state'] = 'held'; desk['reasons'] = list(dict.fromkeys([*desk['reasons'], 'source_revision']))
        if desk['valid_until'] is None or current > _clock(desk['valid_until']):
            desk['state'] = 'held'; desk['reasons'] = list(dict.fromkeys([*desk['reasons'], 'entry_window_unavailable']))
        if _clock(desk['generated_at']) > current or _clock(desk['source']['captured_at']) > _clock(desk['generated_at']):
            return None
        if (current.astimezone(KST).date()-datetime.fromisoformat(desk['latest_session']).date()).days > 7:
            desk['state'] = 'held'; desk['reasons'] = list(dict.fromkeys([*desk['reasons'], 'source_stale']))
        if attempt.get('state') in ('running', 'failed'):
            desk['state'] = attempt['state']
            if desk['state'] == 'running' and current-_clock(attempt['at']) > timedelta(minutes=20):
                desk['state'] = 'failed'
            desk['reasons'] = list(dict.fromkeys([*desk['reasons'], 'refresh_unavailable']))
        desk['forward'] = deepcopy(observations.get('forward'))
        return desk
    except (OSError, ValueError, KeyError, TypeError, StopIteration):
        return None

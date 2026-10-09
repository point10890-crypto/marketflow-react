"""Private append-only evidence receipts beside frozen alpha decisions.

Only explicit admin/collector writes publish evidence. Member GETs read bounded
local snapshots; no provider, model, quote, strategy or account collection runs.
Source claims must have existed at the original alpha cutoff. Current market
events are separate observations bound to that decision and cannot rewrite it.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock

from . import store
from .account_plan import LIMITS
from .decision_contract import (CORE_CLAIMS, MAX_RECORDS, MAX_SOURCE_AGE,
    _candidate_rows, _hash_valid, _mapping, _record, _stamp, _timestamp)
from .desk_market_guard import evaluate_market_guard


VERSION = 'desk-evidence-v2'
MAX_BUNDLE_BYTES = 262144
IDENTITY_KEYS = ('decision_id', 'input_fingerprint', 'source_audit_hash')
BUNDLE_KEYS = {'schema_version', *IDENTITY_KEYS, 'policy_hash', 'evidence', 'market_states'}
SEMANTIC_KEYS = {'direction', 'figure', 'unit', 'conflict_group', 'missing_reason'}
RECORD_KEYS = {'symbol', 'opportunity_id', 'role', 'claim_id', 'core', 'kind',
    'source_grade', 'lineage_id', 'origin_ids', 'source', 'source_at', 'available_at',
    'fetched_at', 'valid_until', 'status', 'confidence', 'evidence_id', *SEMANTIC_KEYS}
MARKET_KEYS = {'symbol', 'opportunity_id', 'decision_id', 'source', 'source_grade',
    'source_at', 'available_at', 'fetched_at', 'valid_until', 'trading_session',
    'vi_active', 'sidecar_active', 'circuit_active', 'vi_released_at',
    'sidecar_released_at', 'circuit_released_at'}


def policy_snapshot():
    """Return an owned snapshot of actual enforced settings and a full hash."""
    policy = dict(policy_version=VERSION, source_max_age_seconds=dict(MAX_SOURCE_AGE),
        core_claims=list(CORE_CLAIMS), independent_sources_per_claim=2,
        required_plan_roles=['flow', 'disclosure'],
        structured_semantics_required=True, calibrated_forecast=False, orders=False,
        account_limits=dict(LIMITS), market=dict(max_market_age_seconds=420,
            vi_cooldown_seconds=300, systemic_cooldown_seconds=900,
            session_start='09:00', plan_cutoff='15:05'))
    return dict(policy=policy, policy_hash=store._hash(policy))


def _clock(now):
    current = datetime.now(timezone.utc) if now is None else _timestamp(now)
    if current is None:
        raise ValueError('timezone_required')
    return current


def _validate(board, payload, current):
    rows = _candidate_rows(_mapping(board))
    if not rows:
        raise ValueError('desk_current_decision_unavailable')
    if (not isinstance(payload, dict) or set(payload) != BUNDLE_KEYS
            or type(payload.get('schema_version')) is not int or payload['schema_version'] != 1):
        raise ValueError('desk_evidence_invalid')
    if any(payload.get(key) != board[key] for key in IDENTITY_KEYS):
        raise ValueError('desk_evidence_identity_changed')
    snapshot = policy_snapshot()
    if payload.get('policy_hash') != snapshot['policy_hash']:
        raise ValueError('desk_policy_changed')
    if len(store._encode(payload)) > MAX_BUNDLE_BYTES:
        raise ValueError('desk_evidence_capacity')
    by_symbol = {row['symbol']: row for row in rows}
    evidence, states = payload['evidence'], payload['market_states']
    if (not isinstance(evidence, dict) or not isinstance(states, dict)
            or set(evidence) - set(by_symbol) or set(states) - set(by_symbol)):
        raise ValueError('desk_evidence_symbols_invalid')
    cutoff = _timestamp(board.get('generated_at'))
    for symbol, records in evidence.items():
        if not isinstance(records, list) or len(records) > MAX_RECORDS:
            raise ValueError('desk_evidence_records_invalid')
        for raw in records:
            if (not isinstance(raw, dict) or set(raw)-RECORD_KEYS
                    or not SEMANTIC_KEYS <= set(raw) or 'evidence_id' not in raw):
                raise ValueError('desk_evidence_record_invalid')
            _, reason = _record(raw, by_symbol[symbol], cutoff, current)
            if reason:
                raise ValueError('desk_evidence_record_invalid')
    for symbol, state in states.items():
        if (not isinstance(state, dict) or set(state)-MARKET_KEYS
                or any(state.get(key) != by_symbol[symbol].get(key)
                       for key in ('symbol', 'opportunity_id', 'decision_id'))):
            raise ValueError('desk_market_identity_invalid')
        if not isinstance(state.get('source'), str) or not 1 <= len(state['source']) <= 300:
            raise ValueError('desk_market_source_invalid')
        for event in ('vi', 'sidecar', 'circuit'):
            release = state.get(event+'_released_at')
            if (type(state.get(event+'_active')) is not bool
                    or event+'_released_at' not in state
                    or release is not None and _timestamp(release) is None):
                raise ValueError('desk_market_event_history_invalid')
        # Adverse/unknown events may be archived and displayed as held. Their
        # substantive validity is evaluated by the pure guard on every read.
        moments = [_timestamp(state.get(key)) for key in ('source_at', 'available_at', 'fetched_at')]
        if (None in moments or not moments[0] <= moments[1] <= moments[2] <= current):
            raise ValueError('desk_market_timestamp_invalid')
    return dict(deepcopy(payload), policy_snapshot=snapshot['policy'])


def _empty(status='missing'):
    return dict(status=status, snapshot_id=None, policy_hash=policy_snapshot()['policy_hash'],
                evidence={}, market_states={})


def read_bundle(root, board):
    """Read the exact decision's receipt; absent/corrupt data stays explicit."""
    board = _mapping(board)
    decision_id = board.get('decision_id')
    if not _hash_valid(decision_id):
        return _empty()
    try:
        base = Path(root)/'desk-evidence'
        path = base/'current'/f'{decision_id}.json'
        if not path.exists():
            return _empty()
        if path.stat().st_size > 4096:
            raise ValueError('desk_pointer_capacity')
        pointer = store._read(path)
        body = pointer['body']
        if (set(body) != {'decision_id', 'snapshot_id'} or body['decision_id'] != decision_id
                or not _hash_valid(body['snapshot_id']) or pointer['sha256'] != store._hash(body)):
            raise ValueError('desk_pointer_integrity')
        snapshot_id = body['snapshot_id']
        target = base/'runs'/f'{snapshot_id}.json'
        if target.stat().st_size > MAX_BUNDLE_BYTES+8192:
            raise ValueError('desk_snapshot_capacity')
        document = store._read(target)
        raw = document['body']
        policy = policy_snapshot()
        if (document['sha256'] != snapshot_id or store._hash(raw) != snapshot_id
                or set(raw) != BUNDLE_KEYS | {'policy_snapshot'}
                or any(raw.get(key) != board.get(key) for key in IDENTITY_KEYS)
                or raw.get('policy_hash') != policy['policy_hash']
                or raw.get('policy_snapshot') != policy['policy']
                or not isinstance(raw.get('evidence'), dict) or not isinstance(raw.get('market_states'), dict)):
            raise ValueError('desk_snapshot_integrity')
        return dict(status='ready', snapshot_id=snapshot_id, policy_hash=policy['policy_hash'],
                    evidence=deepcopy(raw['evidence']), market_states=deepcopy(raw['market_states']))
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        return _empty('held')


def publish_bundle(root, status, payload, *, now=None):
    """Append a checked receipt and atomically select it under a decision lock."""
    board = _mapping(_mapping(status).get('opportunity_engine'))
    current = _clock(now)
    body = _validate(board, payload, current)
    snapshot_id = store._hash(body)
    base = Path(root)/'desk-evidence'
    base.mkdir(parents=True, exist_ok=True)
    with FileLock(str(base/'publish.lock'), timeout=10):
        previous = read_bundle(root, board)
        if previous['status'] == 'held':
            raise ValueError('desk_existing_receipt_invalid')
        if set(previous['market_states']) - set(body['market_states']):
            # A partial write must not erase the capture high-water mark and
            # then permit an older safe state to replace a newer adverse one.
            raise ValueError('desk_market_observation_regression')
        for symbol, state in body['market_states'].items():
            old = previous['market_states'].get(symbol)
            if isinstance(old, dict) and old != state:
                before, after = _timestamp(old.get('source_at')), _timestamp(state.get('source_at'))
                if before is not None and (after is None or after <= before):
                    raise ValueError('desk_market_observation_regression')
                for event in ('vi', 'sidecar', 'circuit'):
                    if state[event+'_active']:
                        continue
                    released = _timestamp(state[event+'_released_at'])
                    prior_release = _timestamp(old.get(event+'_released_at'))
                    if ((old.get(event+'_active') is True and (released is None or released < before))
                            or (prior_release is not None and (released is None or released < prior_release))):
                        raise ValueError('desk_market_event_history_invalid')
        target = base/'runs'/f'{snapshot_id}.json'
        if target.exists():
            existing = store._read(target)
            if existing.get('sha256') != snapshot_id or store._hash(existing.get('body')) != snapshot_id:
                raise ValueError('desk_existing_receipt_invalid')
        else:
            store._write(target, dict(body=body, created_at=_stamp(current), sha256=snapshot_id))
        if previous['snapshot_id'] != snapshot_id:
            pointer = dict(decision_id=board['decision_id'], snapshot_id=snapshot_id)
            store._write(base/'current'/f"{board['decision_id']}.json",
                         dict(body=pointer, sha256=store._hash(pointer)))
    return dict(schema_version=1, status='stored', decision_id=board['decision_id'],
        snapshot_id=snapshot_id, policy_hash=body['policy_hash'],
        evidence_records=sum(len(rows) for rows in body['evidence'].values()))


def attach_contract(desk, board, snapshot, *, now=None):
    """Add policy/market diagnostics, with no changes to saved alpha or ordering."""
    result, board, snapshot = deepcopy(desk), _mapping(board), _mapping(snapshot)
    current, policy = _clock(now), policy_snapshot()
    candidates = _candidate_rows(board)
    checks = []
    for candidate, source in zip(result['candidates'], candidates):
        checked = evaluate_market_guard(source, _mapping(snapshot.get('market_states')).get(source['symbol']),
                                       now=current, policy=policy['policy']['market'])
        if checked['status'] == 'passed':
            entry_until = _timestamp(source.get('valid_until'))
            if entry_until is None or entry_until <= current:
                checked = dict(status='held', reasons=['market_entry_window_unavailable'], valid_until=None)
            else:
                checked['valid_until'] = _stamp(min(entry_until, _timestamp(checked['valid_until'])))
        checks.append(dict(symbol=source['symbol'], opportunity_id=source['opportunity_id'], **checked))
        reasons = list(checked['reasons'])
        if snapshot.get('status') != 'ready':
            reasons.append('desk_evidence_integrity' if snapshot.get('status') == 'held' else 'desk_evidence_missing')
        if snapshot.get('policy_hash') != policy['policy_hash']:
            reasons.append('desk_policy_changed')
        if 'directional_semantics' in candidate['missing']:
            reasons.append('directional_semantics_missing')
        for role in policy['policy']['required_plan_roles']:
            if role in candidate['missing']:
                reasons.append(role+'_required_for_plan')
        if reasons:
            candidate['audit']['reasons'] = list(dict.fromkeys([*candidate['audit']['reasons'], *reasons]))
            candidate['audit']['status'] = 'held'
        else:
            deadline, until = _timestamp(checked['valid_until']), _timestamp(candidate['invalidation']['valid_until'])
            if deadline is not None and until is not None:
                candidate['invalidation']['valid_until'] = _stamp(min(deadline, until))
    result['contract'] = dict(schema_version=1, policy_version=VERSION, policy_hash=policy['policy_hash'],
        decision_id=board.get('decision_id') if _hash_valid(board.get('decision_id')) else None,
        evidence_snapshot_id=snapshot.get('snapshot_id') if _hash_valid(snapshot.get('snapshot_id')) else None,
        evidence_status=snapshot.get('status') if snapshot.get('status') in ('ready', 'held', 'missing') else 'held',
        market_checks=checks)
    # Source auditor remains provenance/claim-only in detail; passing market
    # checks do not promote research or produce an execution authorization.
    auditor = next(role for role in result['roles'] if role['id'] == 'auditor')
    auditor['status'] = 'passed' if result['candidates'] and all(
        row['audit']['status'] == 'passed' for row in result['candidates']) else 'held'
    return result


def contract_blockers(desk, board, row, *, now):
    """Recheck the saved market boundary before request-only account arithmetic."""
    contract = _mapping(desk.get('contract'))
    if (set(contract) != {'schema_version', 'policy_version', 'policy_hash', 'decision_id',
            'evidence_snapshot_id', 'evidence_status', 'market_checks'}
            or type(contract.get('schema_version')) is not int or contract['schema_version'] != 1
            or contract.get('policy_version') != VERSION
            or contract.get('policy_hash') != policy_snapshot()['policy_hash']
            or not _hash_valid(contract.get('decision_id'))
            or contract.get('decision_id') != board.get('decision_id')
            or not _hash_valid(contract.get('evidence_snapshot_id'))
            or contract.get('evidence_status') != 'ready'):
        return ['desk_market_guard_invalid'], None
    checks = contract.get('market_checks')
    rows = board.get('candidates')
    if (not isinstance(checks, list) or not isinstance(rows, list) or len(checks) != len(rows)
            or any(not isinstance(check, dict) or not isinstance(candidate, dict)
                   or not _hash_valid(candidate.get('opportunity_id'))
                   or check.get('symbol') != candidate.get('symbol')
                   or check.get('opportunity_id') != candidate.get('opportunity_id')
                   for check, candidate in zip(checks, rows))):
        return ['desk_market_guard_invalid'], None
    match = next((check for check in checks if check.get('opportunity_id') == row.get('opportunity_id')), {})
    reasons = match.get('reasons')
    if (set(match) != {'symbol', 'opportunity_id', 'status', 'reasons', 'valid_until'}
            or not isinstance(reasons, list) or len(reasons) > 100
            or any(not isinstance(reason, str) or not reason.startswith('market_') or len(reason) > 100
                   for reason in reasons)):
        return ['desk_market_guard_invalid'], None
    if match.get('status') != 'passed':
        return reasons or ['desk_market_guard_held'], None
    expires, entry_until = _timestamp(match.get('valid_until')), _timestamp(row.get('valid_until'))
    if reasons or expires is None or entry_until is None or expires > entry_until:
        return ['desk_market_guard_invalid'], None
    if now >= expires:
        return ['market_guard_expired'], None
    return [], expires

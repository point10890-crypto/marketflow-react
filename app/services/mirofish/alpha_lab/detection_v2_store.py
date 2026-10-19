"""Separate fixed-window v2 paper evidence; never rewrites v1 experiments."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, time, timedelta, timezone
import hashlib
from pathlib import Path

from filelock import FileLock

from . import store
from .execution import ExecutionPolicy

POLICY = 'alpha-detection-comparison-v2'
KST = timezone(timedelta(hours=9))
SOURCE_ROOT = Path(__file__).parent
_CODE_FILES = ('discovery.py', 'discovery_v2.py', 'decision_engine.py', 'execution.py',
               'detection_v2_store.py', 'features.py', 'store.py', 'risk.py', 'service.py',
               'data.py', '../kelly_position.py')


def _clock(value):
    if isinstance(value,datetime):
        if value.utcoffset() is None:
            raise ValueError('detection_v2_timezone')
        return value.astimezone(timezone.utc)
    value = store.timestamp(value)
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)


def _code_hash():
    return store._hash({name: hashlib.sha256((SOURCE_ROOT/name).read_bytes().replace(b'\r\n',b'\n')
                                             .replace(b'\r',b'\n')).hexdigest() for name in _CODE_FILES})


def _read(path):
    raw = store._read(path)
    if (not isinstance(raw, dict) or set(raw) != {'data', 'sha256'}
            or not isinstance(raw['data'], dict) or raw['sha256'] != store._hash(raw['data'])):
        raise ValueError('detection_v2_integrity')
    return raw['data']


def _write(path, value):
    store._write(path, dict(data=value, sha256=store._hash(value)))


def ensure_protocol(root, *, now=None):
    base = Path(root)/'detection-v2'; base.mkdir(parents=True, exist_ok=True)
    moment = _clock(now)
    spec = dict(policy_version=POLICY, challenger='quality-setup-opportunity-v2',
        control='quality-setup-opportunity-v1', code_hash=_code_hash(),
        decision_sessions=60, maturation_sessions=10, slots=3,
        costs_bps=dict(fee=5,slippage=5,sell_tax=20), stress_multiplier=2,
        execution='next_union_session_open_IOC_ATR14x2_stop8pct_2R_10sessions',
        entry_band_applied=False, order_approval=False,
        interpretation='fixed_comparison_paper_not_account_pnl_not_probability',
        promotion='human_review_only_no_early_or_automatic_promotion',
        minimum_completed_per_arm=30, blocks=6, block_sessions=10)
    with FileLock(str(base/'protocol.lock')):
        path = base/'protocol.json'
        if path.exists():
            saved = _read(path)
            if any(saved.get(key) != value for key,value in spec.items()):
                raise ValueError('detection_v2_policy_changed')
            expected = store._hash({k:v for k,v in saved.items() if k != 'protocol_hash'})
            if saved.get('protocol_hash') != expected:
                raise ValueError('detection_v2_integrity')
            return saved
        declared_day = moment.astimezone(KST).date()
        saved = dict(spec, declared_at=moment.isoformat().replace('+00:00','Z'),
            activation_session=declared_day.isoformat(),
            earliest_session=(declared_day+timedelta(days=1)).isoformat())
        saved['protocol_hash'] = store._hash(saved)
        _write(path, saved)
        return saved


def active_for(protocol, session):
    return isinstance(session,str) and session >= protocol['activation_session']


def _binding(report, inputs):
    board = report.get('opportunity_board') or {}
    if (report.get('input_fingerprint') != inputs['input_fingerprint']
            or board.get('input_fingerprint') != inputs['input_fingerprint']
            or not all(isinstance(board.get(k),str) and len(board[k]) == 64
                       and all(c in '0123456789abcdef' for c in board[k])
                       for k in ('decision_id','input_fingerprint','source_audit_hash'))):
        raise ValueError('detection_v2_binding')
    return {key:board[key] for key in ('decision_id','input_fingerprint','source_audit_hash')}


def _captures(inputs, session, moment):
    captures = inputs.get('capture_audit') or {}
    symbols = inputs.get('prices_by_symbol') or {}
    if not 1 <= len(symbols) <= 100 or set(captures) != set(symbols):
        raise ValueError('detection_v2_capture')
    cutoff = datetime.combine(datetime.fromisoformat(session).date(),time(20,30),KST)
    try:
        for value in captures.values():
            if not cutoff <= _clock(value['first']) <= _clock(value['last']) <= moment:
                raise ValueError('detection_v2_capture')
    except (KeyError,TypeError,ValueError) as exc:
        raise ValueError('detection_v2_capture') from exc


def _cohort_arm(report, inputs, session, identity):
    """Seal enough original material before attempting either arm's IO."""
    candidates = deepcopy(report['buy_candidates'])
    if (not isinstance(candidates, list) or len(candidates) > 3
            or any(not isinstance(row, dict) or not isinstance(row.get('symbol'), str) for row in candidates)
            or len({row['symbol'] for row in candidates}) != len(candidates)):
        raise ValueError('detection_v2_frozen_report')
    snapshots = {}
    for row in candidates:
        symbol = row['symbol']
        observed = [bar for bar in inputs['prices_by_symbol'].get(symbol, []) if bar['date'] <= session][-15:]
        days = [bar['date'] for bar in observed]
        if len(days) != 15 or days != sorted(set(days)) or days[-1] != session:
            raise ValueError('detection_v2_snapshot')
        snapshots[symbol] = [{key: bar.get(key) for key in ('symbol', 'date', 'open', 'high', 'low', 'close', 'volume')}
                             for bar in observed]
    return dict(report=dict(as_of=report['as_of'], provenance=deepcopy(report['provenance']),
                    candidates=candidates, first_identity=deepcopy(identity)), snapshots=snapshots)


def _freeze_arm(root, cohort, arm):
    """Append a missing original first decision, without observing older outcomes.

    Recovery always uses the cohort's sealed clock and 15-bar snapshot. Passing
    a truncated seed into observe_and_freeze would also observe existing open
    records; this append-only stage never invokes that state transition.
    """
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    try:
        payload = cohort['frozen'][arm]
        report = payload['report']
        moment = store.timestamp(cohort['created_at'])
        session = cohort['session']
        if (_clock(moment).astimezone(KST).date().isoformat() != session
                or report['first_identity'] != cohort[arm]
                or set(payload['snapshots']) != {row['symbol'] for row in report['candidates']}):
            raise ValueError('detection_v2_frozen_report')
        frozen = dict(decision_date=session, created_at=moment, price_as_of=report['as_of'],
            candidates=deepcopy(report['candidates']), provenance=deepcopy(report['provenance']),
            first_identity=deepcopy(report['first_identity']), policy=asdict(ExecutionPolicy()),
            snapshots=deepcopy(payload['snapshots']))
    except (KeyError, TypeError) as exc:
        raise ValueError('detection_v2_frozen_report') from exc
    # Empty selections remain in the sealed cohort as cash; no fabricated
    # symbol or forward trade record is inserted for a cash-only arm.
    if not frozen['candidates']:
        return False
    with FileLock(str(root/'forward.lock'), timeout=30):
        journal = store.read_journal(root)
        existing = next((row for row in journal['decisions'] if row['decision_date'] == session), None)
        if existing is not None:
            if existing['sha256'] != store._hash(frozen):
                raise ValueError('detection_v2_arm_identity')
            return False
        if any(row['decision_date'] > session for row in journal['decisions']):
            raise ValueError('detection_v2_arm_gap')
        if len(journal['decisions']) >= store.MAX_DECISIONS:
            raise ValueError('archive_journal_before_capacity')
        journal['decisions'].append(dict(frozen, sha256=store._hash(frozen), outcomes=[
            store._seal_result(dict(symbol=row['symbol'], status='pending', net_return=None),
                               frozen, row, frozen['snapshots'], session) for row in frozen['candidates']]))
        journal['sha256'] = store._hash({key:value for key,value in journal.items() if key != 'sha256'})
        store._write(root/'forward.json', journal)
        return True


def refresh(root, inputs, report, control_report, *, now=None):
    moment = _clock(now or report['decision_at'])
    protocol = ensure_protocol(root, now=moment)
    base = Path(root)/'detection-v2'
    with FileLock(str(base/'refresh.lock')):
        path = base/'cohorts.json'
        saved = _read(path) if path.exists() else dict(protocol_hash=protocol['protocol_hash'], sessions=[])
        if saved.get('protocol_hash') != protocol['protocol_hash'] or not isinstance(saved.get('sessions'),list):
            raise ValueError('detection_v2_integrity')
        sessions = saved['sessions']
        if (len(sessions) > 60 or any(not isinstance(row, dict) or not isinstance(row.get('session'), str) for row in sessions)
                or [row['session'] for row in sessions] != sorted({row['session'] for row in sessions})):
            raise ValueError('detection_v2_integrity')
        # Recover older, partially written cohorts before enrolling a later day.
        # This remains active after day60 and never extends the fixed window.
        for cohort in sessions:
            for arm in ('challenger', 'control'):
                _freeze_arm(base/arm, cohort, arm)
        day = moment.astimezone(KST).date().isoformat()
        enroll = (day == inputs['latest_session'] == report['latest_session']
                  and day >= protocol['earliest_session'] and len(sessions) < 60)
        if enroll and not any(row['session'] == day for row in sessions):
            if sessions and sessions[-1]['session'] >= day:
                raise ValueError('detection_v2_cohort_gap')
            _captures(inputs, day, moment)
            challenger = _binding(report, inputs); control = _binding(control_report, inputs)
            cohort = dict(session=day, created_at=moment.isoformat().replace('+00:00','Z'),
                input_fingerprint=inputs['input_fingerprint'], challenger=challenger, control=control,
                challenger_symbols=[r['symbol'] for r in report['buy_candidates']],
                control_symbols=[r['symbol'] for r in control_report['buy_candidates']],
                frozen=dict(challenger=_cohort_arm(report,inputs,day,challenger),
                            control=_cohort_arm(control_report,inputs,day,control)))
            sessions.append(cohort)
            _write(path, saved)
            for arm in ('challenger', 'control'):
                _freeze_arm(base/arm, cohort, arm)
        # Preserve first issued plans on reruns. Empty selections are recorded
        # above as cash cohorts, rather than disappearing from coverage counts.
        observations = {}
        if sessions:
            for arm,source in (('challenger',report),('control',control_report)):
                frozen = deepcopy(source)
                # All original first decisions are appended above. Observation
                # always sees the complete current prices and cannot enroll.
                frozen['candidates'] = []
                observations[arm] = store.observe_and_freeze(base/arm,frozen,inputs['prices_by_symbol'],now=moment.isoformat())
        return dict(policy_version=POLICY,
            status='window_complete' if len(sessions) == 60 else 'collecting' if sessions else 'waiting',
            declared_at=protocol['declared_at'],earliest_session=protocol['earliest_session'],
            decision_sessions=60,enrolled_sessions=len(sessions),maturation_sessions=10,
            approved_exposure=0.,live_orders=False,
            forward=observations.get('challenger',dict(decisions=0,matured=0,
                win_rate=None,mean_net_return=None,
                counts=dict(pending=0,open=0,unfilled=0,missing_session=0,source_revision=0,closed=0),
                excluded_revised_closed=0,
                revision_policy='preserve_terminal_result_exclude_revised_closed_from_statistics',
                basis='frozen_watchlist_next_open_outcomes_not_account_pnl')))

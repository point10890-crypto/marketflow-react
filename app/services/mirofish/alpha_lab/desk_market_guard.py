"""Pure current-market entry guard; never rewrites or halts source alpha decisions.

State binds symbol/opportunity_id/decision_id and explicitly supplies source,
S/A source_grade, source_at <= available_at <= fetched_at <= now, trading_session,
and vi/sidecar/circuit_active booleans. Each false flag requires its corresponding
*_released_at: aware timestamp, or explicit null when never active. All event
facts describe source_at, so a release cannot follow that capture. Market facts
may follow the alpha decision they monitor. Optional valid_until may shorten
freshness but cannot extend it. Outputs contain UTC ISO timestamps only.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import datetime, time, timedelta, timezone
from typing import Any


UTC = timezone.utc
KST = timezone(timedelta(hours=9))


def _timestamp(value: Any) -> datetime | None:
    try:
        stamp = (datetime.fromisoformat(value.replace('Z', '+00:00'))
            if isinstance(value, str) else value)
        if not isinstance(stamp, datetime) or stamp.tzinfo is None or stamp.utcoffset() is None:
            return None
        return stamp.astimezone(UTC)
    except (ValueError, TypeError, OverflowError):
        return None


def _clock(value: Any) -> time | None:
    if not isinstance(value, str) or len(value) != 5 or value[2] != ':':
        return None
    try:
        return time(int(value[:2]), int(value[3:]))
    except ValueError:
        return None


def _duration(value: Any, *, positive: bool = False) -> timedelta | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        if not math.isfinite(value) or value < 0 or (positive and value == 0):
            return None
        return timedelta(seconds=value)
    except (ValueError, OverflowError):
        return None


def _held(reasons: list[str]) -> dict[str, Any]:
    return dict(status='held', reasons=sorted(set(reasons)), valid_until=None)


def evaluate_market_guard(row: Any, state: Any, *, now: Any, policy: Any) -> dict[str, Any]:
    """Validate immutable trusted market facts for this candidate, without I/O.

    A passed result expires at the earliest capture-freshness deadline, explicit
    source expiration, or KST plan cutoff. Missing facts always hold. Defaults
    apply only to guard policy, never market facts. Cooldowns release exactly at
    released_at + configured seconds; freshness expires at its maximum-age edge.
    """
    current = _timestamp(now)
    if current is None:
        return _held(['market_now_invalid'])
    if not isinstance(policy, Mapping):
        return _held(['market_policy_invalid'])
    age = _duration(policy.get('max_market_age_seconds', 420), positive=True)
    vi_wait = _duration(policy.get('vi_cooldown_seconds', 300))
    systemic_wait = _duration(policy.get('systemic_cooldown_seconds', 900))
    start = _clock(policy.get('session_start', '09:00'))
    cutoff = _clock(policy.get('plan_cutoff', '15:05'))
    if age is None or vi_wait is None or systemic_wait is None or start is None or cutoff is None or start >= cutoff:
        return _held(['market_policy_invalid'])
    if not isinstance(state, Mapping):
        return _held(['market_state_invalid'])
    if not isinstance(row, Mapping):
        return _held(['market_identity_mismatch'])

    reasons: list[str] = []
    for key in ('symbol', 'opportunity_id', 'decision_id'):
        identity = row.get(key)
        if (not isinstance(identity, str) or not identity.strip()
                or not isinstance(state.get(key), str) or state.get(key) != identity):
            reasons.append('market_identity_mismatch')
    source = state.get('source')
    if not isinstance(source, str) or not source.strip():
        reasons.append('market_source_missing')
    grade = state.get('source_grade')
    if not isinstance(grade, str) or grade not in ('S', 'A'):
        reasons.append('market_source_grade_invalid')

    captured, available, fetched = [_timestamp(state.get(key))
        for key in ('source_at', 'available_at', 'fetched_at')]
    if captured is None or available is None or fetched is None:
        reasons.append('market_timestamp_invalid')
    else:
        if not captured <= available <= fetched:
            reasons.append('market_time_order_invalid')
        if max(captured, available, fetched) > current:
            reasons.append('market_timestamp_future')
        if current - captured >= age:
            reasons.append('market_state_stale')

    if state.get('trading_session') != 'CONTINUOUS':
        reasons.append('market_session_not_continuous')
    try:
        local = current.astimezone(KST)
        if local.weekday() >= 5:
            reasons.append('market_weekend')
        if not start <= local.time() < cutoff:
            reasons.append('market_outside_plan_session')
        session_deadline = datetime.combine(local.date(), cutoff, KST).astimezone(UTC)
    except (ValueError, OverflowError):
        return _held(reasons + ['market_now_invalid'])

    for event, wait in (('vi', vi_wait), ('sidecar', systemic_wait), ('circuit', systemic_wait)):
        active = state.get(event+'_active')
        release_key = event+'_released_at'
        if not isinstance(active, bool):
            reasons.append('market_'+event+'_flag_invalid')
            continue
        if active:
            reasons.append('market_'+event+'_active')
            continue
        if release_key not in state:
            reasons.append('market_'+event+'_release_missing')
            continue
        if state[release_key] is None:
            continue
        released = _timestamp(state[release_key])
        if released is None or released > current:
            reasons.append('market_'+event+'_release_invalid')
        elif captured is not None and released > captured:
            reasons.append('market_'+event+'_release_after_capture')
        elif current - released < wait:
            reasons.append('market_'+event+'_cooldown')

    expiration = None
    if 'valid_until' in state:
        expiration = _timestamp(state['valid_until'])
        if expiration is None:
            reasons.append('market_expiration_invalid')
        elif expiration <= current:
            reasons.append('market_state_expired')
    if reasons:
        return _held(reasons)
    try:
        deadline = min(captured + age, session_deadline)
    except OverflowError:
        return _held(['market_timestamp_invalid'])
    if expiration is not None:
        deadline = min(deadline, expiration)
    return dict(status='passed', reasons=[], valid_until=deadline.isoformat().replace('+00:00', 'Z'))

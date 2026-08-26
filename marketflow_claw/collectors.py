"""수집기 — 주도주 스냅샷(파일/KIS)과 레짐 입력(market_gate 캐시).

단일 폴러 원칙: Flask ScreenerWorker가 canonical producer 이며 auto 모드는
정상적으로 screener_leading_latest.json 을 소비한다. 다만 파일과 producer 상태가
모두 stale/unavailable 이면 공통 poller lock/cooldown 아래 한 번만 KIS failover 를
시도한다. active producer, busy poller, unsafe scan 은 계속 fail-closed 처리한다.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import Any

from marketflow_claw.paths import DATA_DIR, LEADERS_LATEST, MARKET_GATE_CACHE, ensure_dirs

FILE_FRESH_SECONDS = 90
# Canonical worker can spend about 120 seconds in its capped unsafe-result
# backoff plus one 20-30 second scan.  A longer grace window prevents Claw from
# racing a healthy but deliberately resting producer while still recovering a
# dead 5001 producer within a few minutes.
PRODUCER_STATE_FRESH_SECONDS = 180.0
GRADE_RANK = {'S': 3, 'A': 2, 'B': 1}


def _now() -> datetime:
    """Clock seam used by freshness tests and observation metadata."""
    return datetime.now()


def _observation_timestamp() -> str:
    return _now().isoformat(timespec='seconds')


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).strip().replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None


def _aligned_timestamps(data_ts: Any, observed_at: Any) -> tuple[datetime, datetime] | None:
    data_time = _parse_timestamp(data_ts)
    observed_time = _parse_timestamp(observed_at)
    if data_time is None or observed_time is None:
        return None
    if data_time.tzinfo is not None and observed_time.tzinfo is None:
        observed_time = observed_time.replace(tzinfo=data_time.tzinfo)
    elif observed_time.tzinfo is not None and data_time.tzinfo is None:
        data_time = data_time.replace(tzinfo=observed_time.tzinfo)
    return data_time, observed_time


def _data_age_seconds(data_ts: Any, observed_at: Any) -> float | None:
    aligned = _aligned_timestamps(data_ts, observed_at)
    if aligned is None:
        return None
    data_time, observed_time = aligned
    delta = (observed_time - data_time).total_seconds()
    # A few seconds of clock skew is harmless; a materially future timestamp
    # is not valid freshness evidence.
    if delta < -5:
        return None
    return max(0.0, delta)


def _ensure_observation_metadata(snap: dict[str, Any], *, file_age_s: float | None = None) -> dict[str, Any]:
    observed_at = str(snap.get('observed_at') or _observation_timestamp())
    data_ts = str(snap.get('data_ts') or snap.get('ts') or '')
    snap['observed_at'] = observed_at
    snap['data_ts'] = data_ts or None
    if file_age_s is not None:
        snap['file_age_s'] = round(max(0.0, file_age_s), 1)
    if snap.get('data_age_s') is None:
        age = _data_age_seconds(data_ts, observed_at)
        snap['data_age_s'] = round(age, 1) if age is not None else None
    return snap


def snapshot_stale_reasons(snap: dict[str, Any], *, max_age_seconds: float = FILE_FRESH_SECONDS) -> list[str]:
    """Explain why a file snapshot is unsafe for live transition detection."""
    observed_at = snap.get('observed_at')
    data_ts = snap.get('data_ts') or snap.get('ts')
    aligned = _aligned_timestamps(data_ts, observed_at)
    reasons: list[str] = []
    if aligned is None:
        reasons.append('data_timestamp_invalid')
    else:
        data_time, observed_time = aligned
        if data_time.date() != observed_time.date():
            reasons.append('data_day_mismatch')

    file_age = snap.get('file_age_s')
    if not isinstance(file_age, (int, float)):
        reasons.append('file_age_unknown')
    elif file_age > max_age_seconds:
        reasons.append('file_age_exceeded')

    data_age = snap.get('data_age_s')
    if not isinstance(data_age, (int, float)):
        reasons.append('data_age_unknown')
    elif data_age > max_age_seconds:
        reasons.append('data_age_exceeded')
    return reasons


def snapshot_is_fresh(snap: dict[str, Any], *, max_age_seconds: float = FILE_FRESH_SECONDS) -> bool:
    return not snapshot_stale_reasons(snap, max_age_seconds=max_age_seconds)


def _screening_quality_is_safe(payload: dict[str, Any]) -> bool:
    if payload.get('error'):
        return False
    quality = payload.get('data_quality')
    return not isinstance(quality, dict) or (
        quality.get('critical_complete') is not False
        and quality.get('score_reliable') is not False
        and quality.get('safe_to_replace_latest') is not False
    )


def _detection_grade(raw_grade: Any, total: Any) -> str:
    """Use the synchronous KIS score for transitions, not async enrichment.

    ``grade`` in the public screener payload may be promoted later by the
    15-minute AI/consecutive cache. That cache is useful for analysis, but its
    warm-up after a process restart is not a market event.
    """
    try:
        score = float(total)
    except (TypeError, ValueError):
        return str(raw_grade or '')
    if score >= 80:
        return 'S'
    if score >= 60:
        return 'A'
    if score >= 40:
        return 'B'
    return 'C'


def _normalize_row(raw_row: dict[str, Any], *, detection_unknown: bool = False) -> dict[str, Any]:
    score = raw_row.get('score') or {}
    total = score.get('total') if isinstance(score, dict) else score
    row_quality = raw_row.get('data_quality') if isinstance(raw_row.get('data_quality'), dict) else {}
    score_complete = raw_row.get('score_complete')
    if score_complete is None:
        score_complete = row_quality.get('score_complete', True)
    incomplete_reasons = raw_row.get('incomplete_reasons')
    if not isinstance(incomplete_reasons, list):
        incomplete_reasons = row_quality.get('missing_score_inputs') or []
    price = raw_row.get('price')
    high_52w = raw_row.get('high_52w')
    if isinstance(high_52w, dict):  # enricher 형식: {'high_52w': 9690, 'distance_pct': ...}
        high_52w = high_52w.get('high_52w')
    return {
        'code': str(raw_row.get('code') or ''),
        'name': raw_row.get('name') or '',
        'grade': _detection_grade(raw_row.get('grade'), total),
        'score': int(total or 0),
        'chg': float(raw_row.get('change_pct') or 0.0),
        'trval_eok': float(raw_row.get('trading_value_eok') or 0.0),
        'volx': float(raw_row.get('volume_ratio') or 0.0),
        'price': float(price) if price not in (None, '') else None,
        'high_52w': float(high_52w) if high_52w not in (None, '') else None,
        'rank': int(raw_row.get('rank') or 0),
        'score_complete': bool(score_complete),
        'incomplete_reasons': list(incomplete_reasons),
        'data_quality': dict(row_quality),
        'detection_unknown': bool(detection_unknown),
    }


def normalize_snapshot(raw: dict[str, Any], *, source: str,
                       observed_at: str | None = None) -> dict[str, Any]:
    """KIS result rows plus hidden quality guards for uncertain disappearances."""
    observed_at = observed_at or _observation_timestamp()
    data_ts = str(raw.get('timestamp') or observed_at)
    snapshot_quality = raw.get('data_quality') if isinstance(raw.get('data_quality'), dict) else {}
    result_rows = (raw.get('results') or [])[:30]
    rows = [_normalize_row(r) for r in result_rows]
    seen_codes = {r['code'] for r in rows if r.get('code')}
    candidate_by_code: dict[str, dict[str, Any]] = {}
    candidate_uncertain_codes: set[str] = set()
    for candidate in raw.get('candidate_pool') or []:
        code = str(candidate.get('code') or '')
        if code:
            candidate_by_code[code] = candidate
        quality = candidate.get('data_quality') if isinstance(candidate.get('data_quality'), dict) else {}
        complete = candidate.get('score_complete')
        if complete is None:
            complete = quality.get('score_complete', True)
        if code and complete is False:
            candidate_uncertain_codes.add(code)
        if not code or code in seen_codes or complete is not False:
            continue
        rows.append(_normalize_row(candidate, detection_unknown=True))
        seen_codes.add(code)

    uncertain_codes = candidate_uncertain_codes | {
        str(code) for code in (snapshot_quality.get('incomplete_score_codes') or []) if code
    }
    for section_name in ('detail', 'investor', 'volume_baseline'):
        section = snapshot_quality.get(section_name)
        if isinstance(section, dict):
            uncertain_codes.update(str(code) for code in (section.get('missing_codes') or []) if code)

    rows_by_code = {r['code']: r for r in rows if r.get('code')}
    for code in sorted(uncertain_codes):
        existing = rows_by_code.get(code)
        if existing is not None:
            existing['score_complete'] = False
            reasons = existing.setdefault('incomplete_reasons', [])
            if 'snapshot_quality_missing' not in reasons:
                reasons.append('snapshot_quality_missing')
            continue
        candidate = candidate_by_code.get(code) or {
            'code': code,
            'score_complete': False,
            'incomplete_reasons': ['snapshot_quality_missing'],
            'data_quality': {'status': 'partial', 'score_complete': False},
        }
        guard = _normalize_row(candidate, detection_unknown=True)
        rows.append(guard)
        rows_by_code[code] = guard
        seen_codes.add(code)

    by_grade: dict[str, int] = {}
    for r in rows:
        if r.get('detection_unknown'):
            continue
        by_grade[r['grade']] = by_grade.get(r['grade'], 0) + 1
    error = raw.get('error')
    if not error and snapshot_quality and snapshot_quality.get('critical_complete') is False:
        error = 'kis_critical_sources_incomplete'
    snap = {
        'ts': data_ts,
        'data_ts': data_ts,
        'observed_at': observed_at,
        'market_status': raw.get('market_status') or 'unknown',
        'source': source,
        'error': error,
        'data_quality': dict(snapshot_quality),
        'uncertain_codes': sorted(uncertain_codes),
        'by_grade': by_grade,
        'rows': rows,
    }
    return _ensure_observation_metadata(snap)


def _file_age_seconds(path: str) -> float | None:
    if not os.path.isfile(path):
        return None
    return time.time() - os.path.getmtime(path)


def _canonical_producer_poller_state(*, now: float | None = None) -> str:
    """Return ``active``, ``stale``, or ``unavailable`` for the shared poller.

    The canonical Flask worker records an outcome only after a scan finishes.
    ``retry_not_before`` therefore counts as active too: it is the shared
    cooldown contract, not evidence that the producer is dead.  This check is
    advisory; the actual failover still goes through ``run_screening()``, whose
    FileLock and persisted cooldown are the final dual-poller/quota guards.
    """
    from app.services import kis_screener

    state_path = f'{kis_screener.SCREENER_POLLER_LOCK}.state.json'
    try:
        with open(state_path, 'r', encoding='utf-8') as f:
            state = json.load(f)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return 'unavailable'

    accounts = state.get('accounts') if isinstance(state, dict) else None
    if not isinstance(accounts, dict):
        return 'unavailable'
    try:
        namespace = kis_screener._token_namespace()
    except (AttributeError, TypeError, ValueError):
        namespace = None
    account = accounts.get(namespace) if namespace else None
    if not isinstance(account, dict) and len(accounts) == 1:
        # A single persisted account is still useful when configuration is not
        # fully available during early process startup.
        account = next(iter(accounts.values()))
    if not isinstance(account, dict):
        return 'unavailable'

    try:
        completed_at = float(account.get('completed_at') or 0.0)
        retry_not_before = float(account.get('retry_not_before') or 0.0)
    except (TypeError, ValueError):
        return 'unavailable'
    current = time.time() if now is None else float(now)
    if retry_not_before > current:
        return 'active'
    if completed_at <= 0 or completed_at > current + 5.0:
        return 'unavailable'
    return (
        'active'
        if current - completed_at <= PRODUCER_STATE_FRESH_SECONDS
        else 'stale'
    )


def _missing(source: str, error: str) -> dict[str, Any]:
    observed_at = _observation_timestamp()
    return {'ts': observed_at, 'data_ts': None, 'observed_at': observed_at,
            'data_age_s': None, 'market_status': 'unknown', 'source': source,
            'error': error, 'by_grade': {}, 'rows': []}


def _fail_closed_file_snapshot(snap: dict[str, Any], *, error: str,
                               stale_reasons: list[str] | None = None) -> dict[str, Any]:
    """Return an observed-now error without treating cached rows as live input."""
    failed = dict(snap)
    data_ts = failed.get('data_ts') or failed.get('ts')
    observed_at = str(failed.get('observed_at') or _observation_timestamp())
    reasons = list(stale_reasons or [])
    failed.update({
        'ts': observed_at,
        'data_ts': data_ts,
        'source': 'file(stale)' if reasons else 'file(unsafe)',
        'error': failed.get('error') or error,
        'data_stale': bool(reasons),
        'stale_reasons': reasons,
    })
    return failed


def load_leaders_file(path: str = LEADERS_LATEST) -> dict[str, Any] | None:
    if not os.path.isfile(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        raw = json.load(f)
    observed_at = _observation_timestamp()
    snap = normalize_snapshot(raw, source='file', observed_at=observed_at)
    return _ensure_observation_metadata(snap, file_age_s=_file_age_seconds(path))


def load_leaders_history(date_str: str) -> dict[str, Any] | None:
    path = os.path.join(DATA_DIR, f'screener_leading_{date_str}.json')
    if not os.path.isfile(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        raw = json.load(f)
    return normalize_snapshot(raw, source=f'history:{date_str}')


def fetch_leaders_kis() -> dict[str, Any]:
    """KIS 직접 호출. busy/unsafe scan은 known-good latest로 폴백."""
    from app.services.kis_screener import run_screening

    ensure_dirs()
    t0 = time.time()
    raw = run_screening(force=True)
    poller_busy = bool(raw.get('poller_busy'))
    unsafe_scan = not poller_busy and not _screening_quality_is_safe(raw)
    if poller_busy or unsafe_scan:
        fallback_kind = 'poller_busy' if poller_busy else 'unsafe_scan'
        snap = load_leaders_file()
        if snap is None or not _screening_quality_is_safe(snap):
            if unsafe_scan:
                snap = normalize_snapshot(raw, source='kis(unsafe_scan)')
                snap.update({
                    'error': 'kis_unsafe_scan_and_no_safe_file',
                    'unsafe_scan': True,
                    'rejected_scan_quality': dict(raw.get('data_quality') or {}),
                    'elapsed_s': round(time.time() - t0, 1),
                    'api_calls': raw.get('api_calls'),
                })
                return snap
            return _missing('kis', 'kis_poller_busy_and_no_file')
        _ensure_observation_metadata(snap)
        snap['source'] = f'file({fallback_kind})'
        snap[fallback_kind] = True
        if unsafe_scan:
            snap['rejected_scan_quality'] = dict(raw.get('data_quality') or {})
        stale_reasons = snapshot_stale_reasons(snap)
        if stale_reasons:
            # Persist the observation under today's clock, not the stale data
            # timestamp.  The original timestamp remains explicit for audit.
            data_ts = snap.get('data_ts') or snap.get('ts')
            observed_at = str(snap.get('observed_at') or _observation_timestamp())
            snap.update({
                'ts': observed_at,
                'data_ts': data_ts,
                'error': snap.get('error') or (
                    'kis_poller_busy_stale_file'
                    if poller_busy
                    else 'kis_unsafe_scan_stale_file'
                ),
                'data_stale': True,
                'stale_reasons': stale_reasons,
            })
        return snap
    snap = normalize_snapshot(raw, source='kis')
    snap['elapsed_s'] = round(time.time() - t0, 1)
    snap['api_calls'] = raw.get('api_calls')
    return snap


def fetch_leaders(mode: str = 'auto') -> dict[str, Any]:
    """Read leaders with a guarded failover for a dead canonical producer.

    ``auto`` consumes the canonical file while it is fresh.  Only a stale file
    plus a stale/unavailable producer state may attempt one direct scan, and
    that attempt still uses the screener's process-shared lock and cooldown.
    """
    if mode == 'file':
        return load_leaders_file() or _missing('file', 'leaders_file_missing')
    if mode == 'kis':
        return fetch_leaders_kis()

    age = _file_age_seconds(LEADERS_LATEST)
    try:
        snap = load_leaders_file()
    except (OSError, TypeError, ValueError):
        return _missing('file(auto)', 'leaders_file_unreadable')
    if snap is None:
        return _missing('file(auto)', 'leaders_file_missing')

    _ensure_observation_metadata(snap, file_age_s=age)
    stale_reasons = snapshot_stale_reasons(snap)
    if stale_reasons:
        producer_state = _canonical_producer_poller_state()
        if producer_state != 'active':
            try:
                recovered = dict(fetch_leaders_kis())
            except Exception as exc:  # failover must never break the resident loop
                failed = _fail_closed_file_snapshot(
                    snap, error='leaders_file_stale', stale_reasons=stale_reasons,
                )
                failed.update({
                    'producer_poller_state': producer_state,
                    'auto_failover_attempted': True,
                    'auto_failover_error': type(exc).__name__,
                })
                return failed
            recovered.update({
                'producer_poller_state': producer_state,
                'auto_failover_attempted': True,
            })
            return recovered

        failed = _fail_closed_file_snapshot(
            snap, error='leaders_file_stale', stale_reasons=stale_reasons,
        )
        failed.update({
            'producer_poller_state': producer_state,
            'auto_failover_attempted': False,
        })
        return failed
    if not _screening_quality_is_safe(snap):
        return _fail_closed_file_snapshot(snap, error='leaders_file_unsafe')
    return snap


def load_regime_inputs() -> dict[str, Any]:
    """market_gate 캐시(일 1회 갱신)에서 레짐 입력을 읽는다. 없으면 unknown."""
    if not os.path.isfile(MARKET_GATE_CACHE):
        return {'available': False, 'status': None, 'age_hours': None}
    with open(MARKET_GATE_CACHE, 'r', encoding='utf-8') as f:
        d = json.load(f)
    age_h = None
    try:
        upd = datetime.fromisoformat(d.get('updated_at'))
        age_h = round((datetime.now() - upd).total_seconds() / 3600, 1)
    except Exception:  # noqa: BLE001
        pass
    return {
        'available': True,
        'status': d.get('status'),      # GREEN / YELLOW / RED
        'label': d.get('label'),
        'score': d.get('score'),
        'kospi_close': d.get('kospi_close'),
        'kospi_change_pct': d.get('kospi_change_pct'),
        'updated_at': d.get('updated_at'),
        'age_hours': age_h,
    }

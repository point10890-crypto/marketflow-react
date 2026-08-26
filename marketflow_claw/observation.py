"""Shadow-only Claw observation ledger and read-only scorecards.

This module deliberately sits beside the operational ``memory`` tables.  A
failure here must never change event detection, delivery, or HALT behaviour.
All writes are append-oriented and versioned; the only mutable rows are the
derived instance status and outcome materialisations, both of which retain an
immutable state/outcome history key.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

from marketflow_claw import memory
from marketflow_claw.paths import DAILY_PRICES, REPO_ROOT

SCHEMA_VERSION = 1
CONTEXT_SCHEMA = 'marketflow.claw.regime_context.v1'
SCAN_SCHEMA = 'marketflow.claw.observation_scan.v1'
DETECTOR_VERSION = 'marketflow.claw.events.v1'
SCORE_MODEL_VERSION = 'kis.base_score.v1'
OUTCOME_METHOD_VERSION = 'daily_prices_current_price_unadjusted.v1'
DEFAULT_HORIZONS = (1, 5)
MIN_SCORECARD_COMPLETE = 5
FRESH_SCAN_SECONDS = 300
STRUCTURAL_MAX_CALENDAR_DAYS = 7
KST = timezone(timedelta(hours=9))

REGIME_TIMELINE_PATH = os.path.join(
    REPO_ROOT, 'data', 'admin_mirofish', 'intelligence', 'regime_timeline.json',
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS observation_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS regime_contexts (
  id INTEGER PRIMARY KEY,
  context_hash TEXT NOT NULL UNIQUE,
  captured_at TEXT NOT NULL,
  available_at TEXT NOT NULL,
  structural_phase TEXT NOT NULL,
  structural_as_of_date TEXT,
  structural_available_at TEXT,
  live_gate_status TEXT,
  live_gate_score REAL,
  live_gate_available_at TEXT,
  live_halt INTEGER NOT NULL DEFAULT 0,
  payload_json TEXT NOT NULL,
  schema_version INTEGER NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS regime_contexts_immutable_update
BEFORE UPDATE ON regime_contexts
BEGIN
  SELECT RAISE(ABORT, 'regime_contexts are immutable');
END;

CREATE TRIGGER IF NOT EXISTS regime_contexts_immutable_delete
BEFORE DELETE ON regime_contexts
BEGIN
  SELECT RAISE(ABORT, 'regime_contexts are immutable');
END;

CREATE TABLE IF NOT EXISTS observation_scans (
  id INTEGER PRIMARY KEY,
  scan_key TEXT NOT NULL UNIQUE,
  snapshot_id INTEGER REFERENCES snapshots(id) ON DELETE SET NULL,
  regime_context_id INTEGER NOT NULL REFERENCES regime_contexts(id),
  observed_at TEXT NOT NULL,
  data_ts TEXT,
  day TEXT NOT NULL,
  source TEXT,
  usable INTEGER NOT NULL,
  source_error TEXT,
  input_hash TEXT NOT NULL,
  detector_version TEXT NOT NULL,
  score_model_version TEXT NOT NULL,
  data_quality_json TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  schema_version INTEGER NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_observation_scans_day
  ON observation_scans(day, observed_at);
CREATE INDEX IF NOT EXISTS ix_observation_scans_context
  ON observation_scans(regime_context_id);

CREATE TABLE IF NOT EXISTS observation_daily_markers (
  id INTEGER PRIMARY KEY,
  day TEXT NOT NULL,
  marker_type TEXT NOT NULL,
  scan_id INTEGER NOT NULL REFERENCES observation_scans(id),
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(day, marker_type)
);

CREATE TABLE IF NOT EXISTS signal_instances (
  id INTEGER PRIMARY KEY,
  instance_key TEXT NOT NULL UNIQUE,
  opened_scan_id INTEGER NOT NULL REFERENCES observation_scans(id),
  opened_event_id INTEGER REFERENCES events(id) ON DELETE SET NULL,
  opened_at TEXT NOT NULL,
  day TEXT NOT NULL,
  code TEXT NOT NULL,
  name TEXT,
  trigger_type TEXT NOT NULL,
  grade TEXT,
  score REAL,
  ref_price REAL,
  ref_price_source TEXT,
  status TEXT NOT NULL DEFAULT 'OPEN',
  closed_at TEXT,
  close_reason TEXT,
  detector_version TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_signal_instances_day
  ON signal_instances(day, opened_at);
CREATE INDEX IF NOT EXISTS ix_signal_instances_code_status
  ON signal_instances(code, status, opened_at);

CREATE TABLE IF NOT EXISTS signal_state_events (
  id INTEGER PRIMARY KEY,
  idempotency_key TEXT NOT NULL UNIQUE,
  signal_instance_id INTEGER NOT NULL REFERENCES signal_instances(id) ON DELETE CASCADE,
  scan_id INTEGER REFERENCES observation_scans(id) ON DELETE SET NULL,
  source_event_id INTEGER REFERENCES events(id) ON DELETE SET NULL,
  event_type TEXT NOT NULL,
  state_from TEXT,
  state_to TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  reason TEXT,
  price REAL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_signal_state_instance
  ON signal_state_events(signal_instance_id, observed_at, id);

CREATE TABLE IF NOT EXISTS signal_outcomes (
  id INTEGER PRIMARY KEY,
  signal_instance_id INTEGER NOT NULL REFERENCES signal_instances(id) ON DELETE CASCADE,
  horizon_sessions INTEGER NOT NULL CHECK(horizon_sessions > 0),
  method_version TEXT NOT NULL,
  target_session_date TEXT,
  status TEXT NOT NULL CHECK(status IN ('pending', 'complete', 'missing', 'not_comparable')),
  entry_price REAL,
  exit_price REAL,
  return_pct REAL,
  price_source TEXT,
  source_watermark TEXT,
  computed_at TEXT,
  error_code TEXT,
  metadata_json TEXT NOT NULL,
  UNIQUE(signal_instance_id, horizon_sessions, method_version)
);
CREATE INDEX IF NOT EXISTS ix_signal_outcomes_status
  ON signal_outcomes(status, horizon_sessions, target_session_date);
"""


def _now_iso(now: datetime | None = None) -> str:
    return (now or datetime.now()).isoformat(timespec='seconds')


def _day(ts: str) -> str:
    return str(ts or '')[:10].replace('-', '')


def _db_path() -> str:
    # Resolve at call time so tests can isolate ``memory.DB_PATH``.
    return memory.DB_PATH


def _health_path() -> str:
    return os.path.join(os.path.dirname(_db_path()), 'observation_health.json')


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=KST)
    return parsed.astimezone(timezone.utc)


def _safe_age_seconds(value: Any, now: datetime) -> float | None:
    parsed = _parse_time(value)
    current = now
    if current.tzinfo is None:
        current = current.replace(tzinfo=KST)
    current = current.astimezone(timezone.utc)
    if parsed is None:
        return None
    return max(0.0, (current - parsed).total_seconds())


def _meta_set(con: sqlite3.Connection, key: str, value: Any, *, now: str) -> None:
    con.execute(
        'INSERT INTO observation_meta(key,value,updated_at) VALUES (?,?,?) '
        'ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at',
        (key, str(value), now),
    )


def _meta_get(con: sqlite3.Connection, key: str) -> str | None:
    row = con.execute('SELECT value FROM observation_meta WHERE key=?', (key,)).fetchone()
    return str(row[0]) if row else None


def _ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript(_SCHEMA)
    row = con.execute(
        "SELECT value FROM observation_meta WHERE key='schema_version'"
    ).fetchone()
    current = int(row[0]) if row and str(row[0]).isdigit() else 0
    if current > SCHEMA_VERSION:
        raise RuntimeError(f'observation schema {current} is newer than supported {SCHEMA_VERSION}')
    # Version 1 is entirely additive. Future versions must migrate from
    # ``current`` here before advancing this marker.
    now = _now_iso()
    _meta_set(con, 'schema_version', SCHEMA_VERSION, now=now)


@contextmanager
def connect(*, write: bool = True, path: str | None = None) -> Iterator[sqlite3.Connection]:
    db_path = path or _db_path()
    if write:
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        con = sqlite3.connect(db_path, timeout=0.75)
    else:
        if not os.path.isfile(db_path):
            raise FileNotFoundError(db_path)
        con = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=0.75)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    con.execute('PRAGMA busy_timeout=750')
    if write:
        con.execute('PRAGMA journal_mode=WAL')
        _ensure_schema(con)
    try:
        yield con
        if write:
            con.commit()
    except Exception:
        if write:
            con.rollback()
        raise
    finally:
        con.close()


def _read_health() -> dict[str, Any]:
    try:
        with open(_health_path(), encoding='utf-8') as f:
            value = json.load(f)
        return value if isinstance(value, dict) else {}
    except (OSError, TypeError, ValueError):
        return {}


def _write_health(payload: dict[str, Any]) -> None:
    """Best-effort cross-process diagnostic; never raises into Claw."""
    try:
        path = _health_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f'{path}.tmp.{os.getpid()}'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, sort_keys=True)
        os.replace(tmp, path)
    except OSError:
        pass


def _health_success(now: str) -> None:
    health = _read_health()
    health.update({'last_write_at': now, 'consecutive_errors': 0})
    _write_health(health)


def _health_failure(exc: BaseException, now: str) -> None:
    health = _read_health()
    health.update({
        'last_error_at': now,
        'last_error': f'{type(exc).__name__}: {str(exc)[:180]}',
        'consecutive_errors': int(health.get('consecutive_errors') or 0) + 1,
    })
    _write_health(health)


def _structural_phase(observed_at: str) -> dict[str, Any]:
    """Load only a phase artifact proven available at the decision time."""
    empty = {
        'phase': 'unknown', 'as_of_date': None, 'breadth': None,
        'breadth_change_5d': None, 'source': 'regime_timeline',
        'source_schema_version': None, 'source_available_at': None,
        'lookahead_safe': False, 'status': 'missing',
    }
    try:
        with open(REGIME_TIMELINE_PATH, encoding='utf-8-sig') as f:
            timeline = json.load(f)
    except (OSError, TypeError, ValueError):
        return empty

    generated_at = timeline.get('generated_at')
    decision_time = _parse_time(observed_at)
    artifact_time = _parse_time(generated_at)
    base = {
        **empty,
        'source_schema_version': timeline.get('schema_version'),
        'source_available_at': generated_at,
        'lookahead_safe': bool(timeline.get('lookahead_safe')),
    }
    if decision_time is None or artifact_time is None or artifact_time > decision_time:
        base['status'] = 'not_available_at_decision'
        return base

    by_date = timeline.get('by_date') if isinstance(timeline.get('by_date'), dict) else {}
    decision_date = str(observed_at)[:10]
    # Structural EOD data from the signal session is not available intraday.
    dates = sorted(d for d in by_date if d < decision_date)
    if not dates:
        base['status'] = 'no_prior_session'
        return base
    as_of = dates[-1]
    latest = by_date.get(as_of) or {}
    try:
        breadth = float(latest.get('breadth'))
    except (TypeError, ValueError):
        base['status'] = 'invalid_breadth'
        return base
    prior_date = dates[-6] if len(dates) >= 6 else dates[0]
    try:
        prior_breadth = float((by_date.get(prior_date) or {}).get('breadth'))
    except (TypeError, ValueError):
        prior_breadth = breadth
    change = breadth - prior_breadth
    regime = str(latest.get('regime') or 'NEUTRAL')
    if regime == 'RISK_ON':
        phase = 'uptrend_broadening'
    elif regime == 'RISK_OFF':
        phase = 'rebound_early' if change >= 0.05 else 'downtrend'
    else:
        phase = 'rebound_early' if change >= 0.05 else 'leader_market'
    result = {
        **base, 'phase': phase, 'as_of_date': as_of,
        'breadth': round(breadth, 4), 'breadth_change_5d': round(change, 4),
        'regime': regime, 'status': 'available',
    }
    try:
        stale_days = (datetime.fromisoformat(decision_date).date()
                      - datetime.fromisoformat(as_of).date()).days
    except ValueError:
        stale_days = STRUCTURAL_MAX_CALENDAR_DAYS + 1
    result['stale_calendar_days'] = stale_days
    if stale_days > STRUCTURAL_MAX_CALENDAR_DAYS:
        # Preserve the raw artifact facts for audit, but never present an old
        # structural label as decision-time context.
        result['raw_phase'] = phase
        result['phase'] = 'unknown'
        result['status'] = 'stale'
    return result


def build_regime_context(*, observed_at: str, snapshot: dict[str, Any],
                         gate: dict[str, Any], regime: dict[str, Any]) -> dict[str, Any]:
    """Build the immutable, dual-axis context captured for one observation."""
    structural = _structural_phase(observed_at)
    live = {
        'gate_status': gate.get('status'),
        'gate_label': gate.get('label'),
        'gate_score': gate.get('score'),
        'gate_available_at': gate.get('updated_at'),
        'gate_age_hours': gate.get('age_hours'),
        'evaluated_regime': regime.get('regime'),
        'halt': bool(regime.get('halt')),
        'halt_reasons': list(regime.get('reasons') or []),
        'breadth_pct': regime.get('breadth_pct'),
        'leader_count': regime.get('leader_count'),
    }
    conflicts: list[str] = []
    phase = structural.get('phase')
    gate_status = live.get('gate_status')
    if phase in {'uptrend_broadening', 'leader_market'} and gate_status == 'RED':
        conflicts.append('structural_positive_live_gate_red')
    if phase in {'downtrend', 'rebound_early'} and gate_status == 'GREEN':
        conflicts.append('structural_cautious_live_gate_green')
    payload = {
        'schema_version': CONTEXT_SCHEMA,
        'captured_at': observed_at,
        'available_at': observed_at,
        'structural': structural,
        'live': live,
        'snapshot': {
            'data_ts': snapshot.get('data_ts') or snapshot.get('ts'),
            'source': snapshot.get('source'),
            'market_status': snapshot.get('market_status'),
        },
        'conflicts': conflicts,
        # Axes intentionally remain separate. No fallback label is promoted to
        # an operational decision.
        'resolution_rule': 'preserve_structural_and_live_axes',
    }
    return payload


def _insert_context(con: sqlite3.Connection, context: dict[str, Any], now: str) -> tuple[int, str]:
    context_hash = _digest(context)
    structural = context['structural']
    live = context['live']
    con.execute(
        'INSERT OR IGNORE INTO regime_contexts('
        'context_hash,captured_at,available_at,structural_phase,structural_as_of_date,'
        'structural_available_at,live_gate_status,live_gate_score,live_gate_available_at,'
        'live_halt,payload_json,schema_version,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (
            context_hash, context['captured_at'], context['available_at'],
            structural.get('phase') or 'unknown', structural.get('as_of_date'),
            structural.get('source_available_at'), live.get('gate_status'),
            live.get('gate_score'), live.get('gate_available_at'), int(bool(live.get('halt'))),
            _canonical(context), SCHEMA_VERSION, now,
        ),
    )
    row = con.execute(
        'SELECT id FROM regime_contexts WHERE context_hash=?', (context_hash,),
    ).fetchone()
    if not row:
        raise RuntimeError('regime context insert failed')
    return int(row[0]), context_hash


def _core_event_id(con: sqlite3.Connection, event: dict[str, Any]) -> int | None:
    row = con.execute(
        'SELECT id FROM events WHERE day=? AND type=? AND code=? ORDER BY id DESC LIMIT 1',
        (_day(str(event.get('ts') or '')), event.get('type'), event.get('code')),
    ).fetchone()
    return int(row[0]) if row else None


def _open_instance(con: sqlite3.Connection, *, scan_id: int, event_id: int | None,
                   event: dict[str, Any], now: str) -> int | None:
    if event.get('type') not in {'LEADER_NEW', 'LEADER_UPGRADE', 'BASELINE_OPEN'}:
        return None
    event_identity = f'core-event:{event_id}' if event_id is not None else f'event:{_digest(event)}'
    instance_key = f'{event_identity}:signal:{DETECTOR_VERSION}'
    raw_price = event.get('price')
    try:
        ref_price = float(raw_price) if raw_price not in (None, '') else None
    except (TypeError, ValueError):
        ref_price = None
    if ref_price is not None and ref_price <= 0:
        ref_price = None
    con.execute(
        'INSERT OR IGNORE INTO signal_instances('
        'instance_key,opened_scan_id,opened_event_id,opened_at,day,code,name,trigger_type,'
        'grade,score,ref_price,ref_price_source,status,detector_version,payload_json,created_at) '
        'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (
            instance_key, scan_id, event_id, event.get('ts'), _day(str(event.get('ts') or '')),
            event.get('code'), event.get('name'), event.get('type'),
            event.get('grade_to') or event.get('grade'), event.get('score'), ref_price,
            'kis_snapshot' if ref_price is not None else None, 'OPEN', DETECTOR_VERSION,
            _canonical(event), now,
        ),
    )
    row = con.execute(
        'SELECT id,ref_price FROM signal_instances WHERE instance_key=?', (instance_key,),
    ).fetchone()
    if not row:
        raise RuntimeError('signal instance insert failed')
    instance_id = int(row[0])
    state_key = f'{instance_key}:state:open'
    con.execute(
        'INSERT OR IGNORE INTO signal_state_events('
        'idempotency_key,signal_instance_id,scan_id,source_event_id,event_type,state_from,'
        'state_to,observed_at,reason,price,payload_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
        (
            state_key, instance_id, scan_id, event_id, 'SIGNAL_OPEN', None, 'OPEN',
            event.get('ts'), event.get('type'), row[1], _canonical(event), now,
        ),
    )
    initial_status = 'pending' if row[1] is not None else 'missing'
    error_code = None if row[1] is not None else 'reference_price_missing'
    for horizon in DEFAULT_HORIZONS:
        con.execute(
            'INSERT OR IGNORE INTO signal_outcomes('
            'signal_instance_id,horizon_sessions,method_version,status,entry_price,error_code,'
            'metadata_json) VALUES (?,?,?,?,?,?,?)',
            (
                instance_id, horizon, OUTCOME_METHOD_VERSION, initial_status, row[1], error_code,
                _canonical({'definition': 'sessions_after_signal_session', 'adjusted': False}),
            ),
        )
    return instance_id


def _record_drop(con: sqlite3.Connection, *, scan_id: int, event_id: int | None,
                 event: dict[str, Any], now: str) -> int:
    if event.get('type') != 'LEADER_DROP':
        return 0
    rows = con.execute(
        "SELECT id,status FROM signal_instances WHERE code=? AND status='OPEN' ORDER BY opened_at,id",
        (event.get('code'),),
    ).fetchall()
    changed = 0
    for row in rows:
        instance_id = int(row[0])
        source_key = f'core-event:{event_id}' if event_id is not None else f'event:{_digest(event)}'
        key = f'{source_key}:instance:{instance_id}:leader-drop'
        inserted = con.execute(
            'INSERT OR IGNORE INTO signal_state_events('
            'idempotency_key,signal_instance_id,scan_id,source_event_id,event_type,state_from,'
            'state_to,observed_at,reason,price,payload_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
            (
                key, instance_id, scan_id, event_id, 'LEADER_DROP', 'OPEN', 'INVALIDATED',
                event.get('ts'), 'drop_confirmed', event.get('price'), _canonical(event), now,
            ),
        ).rowcount
        if inserted:
            con.execute(
                "UPDATE signal_instances SET status='INVALIDATED',closed_at=?,close_reason=? "
                "WHERE id=? AND status='OPEN'",
                (event.get('ts'), 'drop_confirmed', instance_id),
            )
            changed += 1
    return changed


def _open_daily_baseline(con: sqlite3.Connection, *, scan_id: int,
                         snapshot: dict[str, Any], excluded_codes: set[str],
                         now: str) -> int:
    """Open the first post-stabilization S/A cohort without core events."""
    observed_at = str(snapshot.get('observed_at') or snapshot.get('ts') or now)
    day = _day(observed_at)
    inserted = con.execute(
        'INSERT OR IGNORE INTO observation_daily_markers('
        'day,marker_type,scan_id,payload_json,created_at) VALUES (?,?,?,?,?)',
        (
            day, 'BASELINE_OPEN', scan_id,
            _canonical({'observed_at': observed_at, 'mode': 'shadow'}), now,
        ),
    ).rowcount
    if not inserted:
        return 0
    opened = 0
    for row in snapshot.get('rows') or []:
        code = str(row.get('code') or '')
        if (
            not code or code in excluded_codes or row.get('detection_unknown')
            or row.get('score_complete') is False or row.get('grade') not in {'S', 'A'}
        ):
            continue
        event = {
            'ts': observed_at, 'type': 'BASELINE_OPEN', 'code': code,
            'name': row.get('name'), 'grade': row.get('grade'),
            'grade_from': '', 'grade_to': row.get('grade'), 'score': row.get('score'),
            'chg': row.get('chg'), 'price': row.get('price'),
            'data_quality': row.get('data_quality') or {},
            'score_complete': row.get('score_complete') is not False,
            'shadow_only': True,
        }
        if _open_instance(con, scan_id=scan_id, event_id=None, event=event, now=now):
            opened += 1
    return opened


def record_tick(*, snapshot_id: int | None, snapshot: dict[str, Any], gate: dict[str, Any],
                regime: dict[str, Any], events: list[dict[str, Any]],
                allow_baseline_open: bool = False) -> dict[str, Any]:
    """Persist one observation. Raises on failure; use ``record_tick_fail_open`` live."""
    observed_at = str(snapshot.get('observed_at') or snapshot.get('ts') or _now_iso())
    now = _now_iso()
    context = build_regime_context(
        observed_at=observed_at, snapshot=snapshot, gate=gate, regime=regime,
    )
    scan_payload = {
        'schema_version': SCAN_SCHEMA,
        'observed_at': observed_at,
        'data_ts': snapshot.get('data_ts') or snapshot.get('ts'),
        'source': snapshot.get('source'),
        'market_status': snapshot.get('market_status'),
        'usable': not bool(snapshot.get('error')),
        'error': snapshot.get('error'),
        'by_grade': snapshot.get('by_grade') or {},
        'row_count': len(snapshot.get('rows') or []),
        'data_quality': snapshot.get('data_quality') or {},
        'uncertain_codes': snapshot.get('uncertain_codes') or [],
    }
    input_hash = _digest({
        'data_ts': scan_payload['data_ts'], 'source': scan_payload['source'],
        'rows': snapshot.get('rows') or [], 'error': scan_payload['error'],
    })
    with connect(write=True) as con:
        context_id, context_hash = _insert_context(con, context, now)
        scan_key = _digest({
            'snapshot_id': snapshot_id, 'observed_at': observed_at,
            'input_hash': input_hash, 'context_hash': context_hash,
        })
        con.execute(
            'INSERT OR IGNORE INTO observation_scans('
            'scan_key,snapshot_id,regime_context_id,observed_at,data_ts,day,source,usable,'
            'source_error,input_hash,detector_version,score_model_version,data_quality_json,'
            'payload_json,schema_version,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (
                scan_key, snapshot_id, context_id, observed_at, scan_payload['data_ts'],
                _day(observed_at), scan_payload['source'], int(scan_payload['usable']),
                scan_payload['error'], input_hash, DETECTOR_VERSION, SCORE_MODEL_VERSION,
                _canonical(scan_payload['data_quality']), _canonical(scan_payload), SCHEMA_VERSION, now,
            ),
        )
        scan_row = con.execute(
            'SELECT id FROM observation_scans WHERE scan_key=?', (scan_key,),
        ).fetchone()
        if not scan_row:
            raise RuntimeError('observation scan insert failed')
        scan_id = int(scan_row[0])
        opened = 0
        invalidated = 0
        rows_by_code = {
            str(row.get('code')): row for row in (snapshot.get('rows') or []) if row.get('code')
        }
        for event in events:
            # Operational events intentionally stay compact. Enrich only the
            # shadow copy with the decision-time price already present in the
            # same scan; this cannot affect detection or delivery payloads.
            event_view = dict(event)
            source_row = rows_by_code.get(str(event.get('code') or '')) or {}
            for key in ('price', 'high_52w', 'data_quality', 'score_complete'):
                if event_view.get(key) is None and source_row.get(key) is not None:
                    event_view[key] = source_row[key]
            event_id = _core_event_id(con, event_view)
            if _open_instance(con, scan_id=scan_id, event_id=event_id, event=event_view, now=now):
                opened += 1
            invalidated += _record_drop(
                con, scan_id=scan_id, event_id=event_id, event=event_view, now=now,
            )
        if allow_baseline_open and scan_payload['usable']:
            opened += _open_daily_baseline(
                con, scan_id=scan_id, snapshot=snapshot,
                excluded_codes={
                    str(event.get('code') or '') for event in events
                    if event.get('type') in {'LEADER_NEW', 'LEADER_UPGRADE'}
                },
                now=now,
            )
        _meta_set(con, 'last_write_at', now, now=now)
    _health_success(now)
    return {
        'ok': True, 'mode': 'shadow', 'scan_id': scan_id,
        'context_hash': context_hash, 'instances_opened': opened,
        'instances_invalidated': invalidated,
    }


def record_tick_fail_open(**kwargs: Any) -> dict[str, Any]:
    """Live seam: observation failures are diagnostics, never control flow."""
    try:
        return record_tick(**kwargs)
    except Exception as exc:  # noqa: BLE001 - the fail-open boundary is deliberate
        now = _now_iso()
        _health_failure(exc, now)
        return {
            'ok': False, 'mode': 'shadow', 'scan_id': None,
            'error': f'{type(exc).__name__}: {str(exc)[:180]}',
        }


def _pending_outcomes(con: sqlite3.Connection, method_version: str) -> list[sqlite3.Row]:
    return con.execute(
        'SELECT o.id,o.signal_instance_id,o.horizon_sessions,i.opened_at,i.code,i.ref_price '
        'FROM signal_outcomes o JOIN signal_instances i ON i.id=o.signal_instance_id '
        "WHERE o.status='pending' AND o.method_version=? ORDER BY i.opened_at,o.horizon_sessions",
        (method_version,),
    ).fetchall()


def _load_price_material(path: str, codes: set[str]) -> tuple[list[str], dict[tuple[str, str], set[float]]]:
    sessions: set[str] = set()
    prices: dict[tuple[str, str], set[float]] = {}
    with open(path, encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            day = str(row.get('date') or '').strip()
            if len(day) != 10:
                continue
            sessions.add(day)
            code = str(row.get('ticker') or '').strip()
            if code not in codes:
                continue
            try:
                price = float(row.get('current_price') or 0)
            except (TypeError, ValueError):
                continue
            if price > 0:
                prices.setdefault((code, day), set()).add(price)
    return sorted(sessions), prices


def update_mature_outcomes(*, now: datetime | None = None, price_path: str = DAILY_PRICES,
                           method_version: str = OUTCOME_METHOD_VERSION) -> dict[str, Any]:
    """Fill only horizons whose target trading session exists in the EOD cache.

    The function never fabricates calendar-day horizons. Conflicting duplicate
    prices are marked missing instead of selecting a favourable observation.
    Re-running is idempotent because only ``pending`` rows are updated.
    """
    computed_at = _now_iso(now)
    try:
        with connect(write=True) as con:
            pending = _pending_outcomes(con, method_version)
        if not pending:
            _health_success(computed_at)
            return {
                'ok': True, 'method_version': method_version, 'pending_before': 0,
                'completed': 0, 'missing': 0, 'still_pending': 0, 'data_as_of': None,
            }
        if not os.path.isfile(price_path):
            raise FileNotFoundError(price_path)
        codes = {str(row['code']) for row in pending}
        sessions, prices = _load_price_material(price_path, codes)
        watermark = sessions[-1] if sessions else None
        completed = 0
        missing = 0
        with connect(write=True) as con:
            for row in _pending_outcomes(con, method_version):
                opened_date = str(row['opened_at'])[:10]
                future_sessions = [day for day in sessions if day > opened_date]
                horizon = int(row['horizon_sessions'])
                if len(future_sessions) < horizon:
                    continue
                target = future_sessions[horizon - 1]
                observed_prices = prices.get((str(row['code']), target), set())
                status = 'complete'
                error_code = None
                exit_price: float | None = None
                return_pct: float | None = None
                if not observed_prices:
                    status = 'missing'
                    error_code = 'target_price_missing'
                elif len(observed_prices) > 1:
                    status = 'missing'
                    error_code = 'duplicate_price_conflict'
                else:
                    exit_price = next(iter(observed_prices))
                    entry = float(row['ref_price'])
                    return_pct = round(100.0 * (exit_price / entry - 1.0), 6)
                changed = con.execute(
                    'UPDATE signal_outcomes SET target_session_date=?,status=?,exit_price=?,return_pct=?,'
                    'price_source=?,source_watermark=?,computed_at=?,error_code=? '
                    "WHERE id=? AND status='pending'",
                    (
                        target, status, exit_price, return_pct,
                        'daily_prices.csv:current_price', watermark, computed_at, error_code, row['id'],
                    ),
                ).rowcount
                if changed:
                    completed += int(status == 'complete')
                    missing += int(status == 'missing')
            _meta_set(con, 'outcomes_data_as_of', watermark or '', now=computed_at)
            still_pending = con.execute(
                "SELECT COUNT(*) FROM signal_outcomes WHERE status='pending' AND method_version=?",
                (method_version,),
            ).fetchone()[0]
        _health_success(computed_at)
        return {
            'ok': True, 'method_version': method_version, 'pending_before': len(pending),
            'completed': completed, 'missing': missing, 'still_pending': int(still_pending),
            'data_as_of': watermark,
        }
    except Exception as exc:  # noqa: BLE001 - scheduled observation must not affect other jobs
        _health_failure(exc, computed_at)
        return {
            'ok': False, 'method_version': method_version, 'pending_before': None,
            'completed': 0, 'missing': 0, 'still_pending': None,
            'data_as_of': None, 'error': f'{type(exc).__name__}: {str(exc)[:180]}',
        }


def _empty_scorecards(now: datetime, error: str) -> dict[str, Any]:
    return {
        'schema_version': 'marketflow.claw.scorecards.v1',
        'generated_at': _now_iso(now), 'data_as_of': None,
        'outcome_method_version': OUTCOME_METHOD_VERSION,
        'window': {'start': None, 'end': now.date().isoformat()},
        'coverage': {
            'instances': 0, 'eligible_n': 0, 'complete_n': 0,
            'pending_n': 0, 'missing_n': 0, 'ratio': 0.0,
        },
        'horizons': [], 'recent_instances': [], 'stale': True,
        'insufficient': True, 'insufficient_reason': 'ledger_unavailable',
        'errors': [error],
    }


def build_scorecards(*, now: datetime | None = None, window_days: int = 30,
                     recent_limit: int = 50,
                     method_version: str = OUTCOME_METHOD_VERSION) -> dict[str, Any]:
    """Read-only scorecard projection. Never creates schema or starts a scan."""
    now = now or datetime.now()
    start = (now.date() - timedelta(days=max(1, min(int(window_days), 365)))).isoformat()
    try:
        with connect(write=False) as con:
            version = _meta_get(con, 'schema_version')
            if version is None:
                return _empty_scorecards(now, 'observation_schema_missing')
            where = 'WHERE substr(i.opened_at,1,10)>=?'
            instances = int(con.execute(
                f'SELECT COUNT(*) FROM signal_instances i {where}', (start,),
            ).fetchone()[0])
            grouped = con.execute(
                'SELECT o.horizon_sessions,o.status,COUNT(*) AS n,AVG(o.return_pct) AS avg_ret,'
                'SUM(CASE WHEN o.return_pct>0 THEN 1 ELSE 0 END) AS positives '
                'FROM signal_outcomes o JOIN signal_instances i ON i.id=o.signal_instance_id '
                f'{where} AND o.method_version=? '
                'GROUP BY o.horizon_sessions,o.status ORDER BY o.horizon_sessions,o.status',
                (start, method_version),
            ).fetchall()
            recent = con.execute(
                'SELECT i.id,i.opened_at,i.code,i.name,i.trigger_type,i.grade,i.score,i.status,'
                'c.structural_phase,c.live_gate_status,c.live_halt '
                'FROM signal_instances i JOIN observation_scans s ON s.id=i.opened_scan_id '
                'JOIN regime_contexts c ON c.id=s.regime_context_id '
                f'{where} ORDER BY i.opened_at DESC,i.id DESC LIMIT ?',
                (start, max(1, min(int(recent_limit), 200))),
            ).fetchall()
            ids = [int(row['id']) for row in recent]
            outcome_rows: list[sqlite3.Row] = []
            if ids:
                marks = ','.join('?' for _ in ids)
                outcome_rows = con.execute(
                    'SELECT signal_instance_id,horizon_sessions,status,target_session_date,return_pct,error_code '
                    f'FROM signal_outcomes WHERE signal_instance_id IN ({marks}) '
                    'AND method_version=? ORDER BY signal_instance_id,horizon_sessions',
                    (*ids, method_version),
                ).fetchall()
            data_as_of = _meta_get(con, 'outcomes_data_as_of') or None
            last_scan = con.execute(
                'SELECT observed_at FROM observation_scans ORDER BY id DESC LIMIT 1',
            ).fetchone()
    except Exception as exc:  # noqa: BLE001 - partial/unavailable API contract
        return _empty_scorecards(now, f'{type(exc).__name__}: {str(exc)[:180]}')

    by_horizon: dict[int, dict[str, Any]] = {}
    total_complete = total_pending = total_missing = 0
    for row in grouped:
        horizon = int(row['horizon_sessions'])
        bucket = by_horizon.setdefault(horizon, {
            'horizon_sessions': horizon, 'complete_n': 0, 'pending_n': 0,
            'missing_n': 0, '_return_sum': 0.0, '_positive_n': 0,
        })
        status = str(row['status'])
        count = int(row['n'])
        key = f'{status}_n'
        if key in bucket:
            bucket[key] += count
        if status == 'complete':
            bucket['_return_sum'] += float(row['avg_ret'] or 0) * count
            bucket['_positive_n'] += int(row['positives'] or 0)
            total_complete += count
        elif status == 'pending':
            total_pending += count
        elif status in {'missing', 'not_comparable'}:
            bucket['missing_n'] += count if status == 'not_comparable' else 0
            total_missing += count

    horizons: list[dict[str, Any]] = []
    for horizon in sorted(by_horizon):
        bucket = by_horizon[horizon]
        complete_n = bucket['complete_n']
        eligible_n = complete_n + bucket['missing_n']
        coverage = round(complete_n / eligible_n, 4) if eligible_n else 0.0
        insufficient = complete_n < MIN_SCORECARD_COMPLETE
        horizons.append({
            'horizon_sessions': horizon, 'eligible_n': eligible_n,
            'complete_n': complete_n, 'pending_n': bucket['pending_n'],
            'missing_n': bucket['missing_n'], 'coverage': coverage,
            'avg_return_pct': round(bucket['_return_sum'] / complete_n, 4) if complete_n else None,
            'positive_rate_pct': round(100 * bucket['_positive_n'] / complete_n, 1) if complete_n else None,
            'status': 'insufficient' if insufficient else 'observed',
            'insufficient_reason': (
                f'complete_n<{MIN_SCORECARD_COMPLETE}' if insufficient else None
            ),
        })

    outcomes_by_instance: dict[int, list[dict[str, Any]]] = {}
    for row in outcome_rows:
        outcomes_by_instance.setdefault(int(row['signal_instance_id']), []).append({
            'horizon_sessions': int(row['horizon_sessions']), 'status': row['status'],
            'target_session_date': row['target_session_date'], 'return_pct': row['return_pct'],
            'error_code': row['error_code'],
        })
    recent_items = [{
        'id': int(row['id']), 'opened_at': row['opened_at'], 'code': row['code'],
        'name': row['name'], 'trigger_type': row['trigger_type'], 'grade': row['grade'],
        'score': row['score'], 'status': row['status'],
        'structural_phase': row['structural_phase'], 'live_gate_status': row['live_gate_status'],
        'live_halt': bool(row['live_halt']), 'outcomes': outcomes_by_instance.get(int(row['id']), []),
    } for row in recent]
    age = _safe_age_seconds(last_scan['observed_at'] if last_scan else None, now)
    eligible = total_complete + total_missing
    coverage_ratio = round(total_complete / eligible, 4) if eligible else 0.0
    insufficient = not horizons or all(item['status'] == 'insufficient' for item in horizons)
    return {
        'schema_version': 'marketflow.claw.scorecards.v1',
        'generated_at': _now_iso(now), 'data_as_of': data_as_of,
        'outcome_method_version': method_version,
        'window': {'start': start, 'end': now.date().isoformat()},
        'coverage': {
            'instances': instances, 'eligible_n': eligible, 'complete_n': total_complete,
            'pending_n': total_pending, 'missing_n': total_missing, 'ratio': coverage_ratio,
        },
        'horizons': horizons, 'recent_instances': recent_items,
        'stale': age is None or age > FRESH_SCAN_SECONDS,
        'insufficient': insufficient,
        'insufficient_reason': 'not_enough_complete_outcomes' if insufficient else None,
        'errors': [],
    }


def build_quality(*, now: datetime | None = None) -> dict[str, Any]:
    """Read-only health projection. Never creates schema or starts a scan."""
    now = now or datetime.now()
    health = _read_health()
    errors: list[str] = []
    counts = {'scans': 0, 'contexts': 0, 'instances': 0, 'state_events': 0}
    outcome_counts = {'pending': 0, 'complete': 0, 'missing': 0}
    schema_version: int | None = None
    db_last_write_at = None
    foreign_keys = False
    last_scan_at = None
    data_as_of = None
    path_exists = os.path.isfile(_db_path())
    try:
        db_bytes = os.path.getsize(_db_path()) if path_exists else 0
    except OSError:
        db_bytes = 0
    try:
        with connect(write=False) as con:
            foreign_keys = bool(con.execute('PRAGMA foreign_keys').fetchone()[0])
            raw_version = _meta_get(con, 'schema_version')
            schema_version = int(raw_version) if raw_version is not None else None
            db_last_write_at = _meta_get(con, 'last_write_at')
            for key, table in (
                ('scans', 'observation_scans'), ('contexts', 'regime_contexts'),
                ('instances', 'signal_instances'), ('state_events', 'signal_state_events'),
            ):
                counts[key] = int(con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0])
            for row in con.execute(
                'SELECT status,COUNT(*) AS n FROM signal_outcomes GROUP BY status'
            ).fetchall():
                status = str(row['status'])
                if status in outcome_counts:
                    outcome_counts[status] = int(row['n'])
                elif status == 'not_comparable':
                    outcome_counts['missing'] += int(row['n'])
            scan = con.execute(
                'SELECT observed_at FROM observation_scans ORDER BY id DESC LIMIT 1'
            ).fetchone()
            last_scan_at = scan['observed_at'] if scan else None
            data_as_of = _meta_get(con, 'outcomes_data_as_of') or None
            fk_issues = con.execute('PRAGMA foreign_key_check').fetchall()
            if fk_issues:
                errors.append(f'foreign_key_violations:{len(fk_issues)}')
    except Exception as exc:  # noqa: BLE001 - diagnostics must remain available
        errors.append(f'{type(exc).__name__}: {str(exc)[:180]}')
    age = _safe_age_seconds(last_scan_at, now)
    consecutive = int(health.get('consecutive_errors') or 0)
    if schema_version is None:
        status = 'unavailable'
    elif errors or consecutive:
        status = 'degraded'
    else:
        status = 'ok'
    return {
        'schema_version': 'marketflow.claw.quality.v1',
        'generated_at': _now_iso(now), 'status': status,
        'database': {
            'path_exists': path_exists, 'bytes': db_bytes, 'foreign_keys': foreign_keys,
            'schema_version': schema_version,
        },
        'ledger': {
            'last_write_at': health.get('last_write_at') or db_last_write_at,
            'last_error_at': health.get('last_error_at'), 'last_error': health.get('last_error'),
            'consecutive_errors': consecutive, **counts,
        },
        'outcomes': {**outcome_counts, 'data_as_of': data_as_of},
        'freshness': {
            'last_scan_at': last_scan_at,
            'age_seconds': round(age) if age is not None else None,
            'stale': age is None or age > FRESH_SCAN_SECONDS,
        },
        'errors': errors,
    }

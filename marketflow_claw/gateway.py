"""상주 루프 — 틱 1회 = 수집 → 메모리 → 이벤트 → 레짐 → (이벤트 있으면) 보고.

- PID 락: data/claw/claw.pid (단일 인스턴스)
- 하트비트: data/claw/heartbeat.json (워치독 180초 기준)
- LEADER_DROP 은 CLAW_DROP_CONFIRM_TICKS(기본 3) 연속 틱 확정 후에만 발행
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, time as clock_time
from typing import Any

from app.utils.atomic_json import write_json_atomic
from marketflow_claw import (
    collectors,
    delivery,
    events as ev,
    memory,
    observation,
    regime as rg,
    reporter,
)
from marketflow_claw.paths import CLAW_DIR, HEARTBEAT_PATH, ensure_dirs

PID_PATH = os.path.join(CLAW_DIR, 'claw.pid')
EVENT_BATCH_SIZE = 5
MIN_LOOP_YIELD_SECONDS = 0.1
COLLECTION_ERROR_BACKOFF_BASE_SECONDS = 30.0
COLLECTION_ERROR_BACKOFF_MAX_SECONDS = 300.0
HEARTBEAT_ERROR_LOG_INTERVAL_SECONDS = 60.0
_event_retry_not_before = 0.0
_halt_retry_not_before = 0.0
_halt_retry_episode: str | None = None
_halt_reported_episode: str | None = None
_collection_error_key: tuple[str, str] | None = None
_collection_error_streak = 0
_collection_persist_not_before = 0.0
_heartbeat_error_log_not_before = 0.0
_heartbeat_errors_suppressed = 0


def claw_enabled() -> bool:
    """Master kill switch.  Missing means enabled for backward compatibility."""
    return os.environ.get('CLAW_ENABLED', '1').strip().lower() in {'1', 'true', 'yes', 'on'}


def drop_confirm_ticks() -> int:
    try:
        return max(1, int(os.environ.get('CLAW_DROP_CONFIRM_TICKS', '3')))
    except ValueError:
        return 3


def delivery_retry_seconds() -> float:
    try:
        return max(0.0, float(os.environ.get('CLAW_DELIVERY_RETRY_SECONDS', '60')))
    except ValueError:
        return 60.0


def _monotonic() -> float:
    return time.monotonic()


def _collection_monotonic() -> float:
    return time.monotonic()


def _heartbeat_monotonic() -> float:
    return time.monotonic()


def collection_error_backoff_seconds(streak: int) -> float:
    """Bound repeated error-state writes while continuing five-second probes."""
    exponent = min(16, max(0, int(streak) - 1))
    return min(
        COLLECTION_ERROR_BACKOFF_MAX_SECONDS,
        COLLECTION_ERROR_BACKOFF_BASE_SECONDS * (2 ** exponent),
    )


def snapshot_persistence_decision(snap: dict[str, Any]) -> tuple[bool, float, int]:
    """Persist fresh data immediately and repeated collection errors sparsely.

    The resident loop still reads the producer file and writes heartbeat on
    every tick. Only duplicate DB snapshot/regime rows are backed off.
    """
    global _collection_error_key, _collection_error_streak, _collection_persist_not_before

    error = str(snap.get('error') or '')
    if not error:
        _collection_error_key = None
        _collection_error_streak = 0
        _collection_persist_not_before = 0.0
        return True, 0.0, 0

    # The producer may keep rewriting an unusable payload with a new data_ts.
    # Error identity therefore deliberately excludes payload timestamps; only
    # a recovery or a materially different source/error starts a new episode.
    key = (str(snap.get('source') or ''), error)
    now = _collection_monotonic()
    if key != _collection_error_key:
        _collection_error_key = key
        _collection_error_streak = 1
        delay = collection_error_backoff_seconds(_collection_error_streak)
        _collection_persist_not_before = now + delay
        return True, delay, _collection_error_streak

    if now < _collection_persist_not_before:
        return False, max(0.0, _collection_persist_not_before - now), _collection_error_streak

    _collection_error_streak += 1
    delay = collection_error_backoff_seconds(_collection_error_streak)
    _collection_persist_not_before = now + delay
    return True, delay, _collection_error_streak


def same_source_observation(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    """Return True when both snapshots identify the same producer scan."""
    if not previous or previous.get('error') or current.get('error'):
        return False
    return (
        str(previous.get('ts') or '') == str(current.get('ts') or '')
        and str(previous.get('source') or '') == str(current.get('source') or '')
    )


def same_source_snapshot(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    """Return True when the producer scan and normalized content are unchanged.

    Claw probes the producer file every five seconds while KIS normally
    publishes about every thirty seconds.  Treating every probe as a new tick
    makes drop confirmation count the same market observation repeatedly.
    """
    if not same_source_observation(previous, current):
        return False
    return (
        str(previous.get('market_status') or '') == str(current.get('market_status') or '')
        and dict(previous.get('by_grade') or {}) == dict(current.get('by_grade') or {})
        and list(previous.get('rows') or []) == list(current.get('rows') or [])
    )


def same_regime_state(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    """Compare the material regime fields while ignoring observation time."""
    if not previous:
        return False
    return (
        str(previous.get('regime') or '') == str(current.get('regime') or '')
        and bool(previous.get('halt')) == bool(current.get('halt'))
        and previous.get('breadth_pct') == current.get('breadth_pct')
        and list(previous.get('reasons') or []) == list(current.get('reasons') or [])
    )


def next_tick_delay(interval: float, elapsed: float) -> float:
    """Hold a start-to-start cadence without spinning after a slow scan."""
    return max(MIN_LOOP_YIELD_SECONDS, float(interval) - max(0.0, float(elapsed)))


def event_batch_delivery_id(events: list[dict[str, Any]]) -> str:
    """Stable ID for exactly the FIFO event rows represented by one message."""
    identities = [
        [str(event.get('ts') or ''), str(event.get('type') or ''), str(event.get('code') or '')]
        for event in events
    ]
    encoded = json.dumps(identities, ensure_ascii=False, separators=(',', ':'))
    return f'event-batch:v1:{delivery.digest_of(encoded)}'


def halt_delivery_id(episode_ts: str) -> str:
    """Stable per-entry HALT ID; full timestamp separates same-minute episodes."""
    return f'halt-episode:v1:{episode_ts}'


def market_open_now() -> bool:
    from app.services.kis_screener import is_market_open
    return bool(is_market_open())


def _observed_clock(ts: str) -> clock_time | None:
    try:
        return datetime.fromisoformat(ts).time().replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def in_open_stabilization(ts: str) -> bool:
    """Suppress transition events during the noisy first five minutes."""
    observed = _observed_clock(ts)
    if observed is None:
        return False
    return clock_time(9, 0) <= observed < clock_time(9, 5)


def suppress_new_leaders(ts: str) -> bool:
    """Do not open a new leader episode from 15:20 through market close."""
    observed = _observed_clock(ts)
    return observed is not None and observed >= clock_time(15, 20)


def _log_heartbeat_write_failure(error: Exception) -> None:
    """Rate-limit heartbeat storage errors without risking another loop exit."""
    global _heartbeat_error_log_not_before, _heartbeat_errors_suppressed

    now = _heartbeat_monotonic()
    if now < _heartbeat_error_log_not_before:
        _heartbeat_errors_suppressed += 1
        return

    suppressed = _heartbeat_errors_suppressed
    _heartbeat_errors_suppressed = 0
    _heartbeat_error_log_not_before = now + HEARTBEAT_ERROR_LOG_INTERVAL_SECONDS
    detail = str(error).replace('\r', ' ').replace('\n', ' ')[:240]
    suffix = f' (suppressed {suppressed} similar errors)' if suppressed else ''
    try:
        print(
            f'[claw] heartbeat write failed; monitoring continues: '
            f'{type(error).__name__}: {detail}{suffix}',
            file=sys.stderr,
            flush=True,
        )
    except Exception:  # noqa: BLE001
        # A closed/broken stderr must not turn an already non-critical
        # heartbeat failure into a resident-loop failure.
        pass


def write_heartbeat(extra: dict[str, Any] | None = None) -> bool:
    """Best-effort liveness signal; storage failures never stop monitoring."""
    payload = {'ts': datetime.now().isoformat(timespec='seconds'), 'pid': os.getpid(), **(extra or {})}
    try:
        ensure_dirs()
        # The live dashboard reads this file frequently. On Windows a reader
        # can transiently block os.replace(), so the shared writer uses a
        # unique temp file and bounded replace retry.
        write_json_atomic(HEARTBEAT_PATH, payload, indent=0)
    except Exception as error:  # noqa: BLE001
        _log_heartbeat_write_failure(error)
        return False
    return True


def _pid_alive(pid: int) -> bool:
    try:
        import psutil  # type: ignore
        return psutil.pid_exists(pid)
    except Exception:  # noqa: BLE001
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def acquire_pid_lock() -> bool:
    """다른 인스턴스가 살아 있으면 False. 죽은 PID 파일은 덮어쓴다."""
    ensure_dirs()
    if os.path.isfile(PID_PATH):
        try:
            other = int(open(PID_PATH, encoding='utf-8').read().strip() or 0)
        except ValueError:
            other = 0
        if other and other != os.getpid() and _pid_alive(other):
            return False
    with open(PID_PATH, 'w', encoding='utf-8') as f:
        f.write(str(os.getpid()))
    return True


def release_pid_lock() -> None:
    try:
        if os.path.isfile(PID_PATH) and open(PID_PATH, encoding='utf-8').read().strip() == str(os.getpid()):
            os.remove(PID_PATH)
    except OSError:
        pass


def run_tick(*, source: str = 'auto', send: bool = False) -> dict[str, Any]:
    global _event_retry_not_before, _halt_retry_not_before, _halt_retry_episode, _halt_reported_episode
    t0 = time.time()
    if not claw_enabled():
        now = datetime.now().isoformat(timespec='seconds')
        write_heartbeat({'state': 'disabled', 'disabled': True})
        return {
            'ts': now, 'source': None, 'rows': 0, 'by_grade': {}, 'snapshot_id': None,
            'baseline': False, 'stabilizing': False, 'new_entries_suppressed': False,
            'disabled': True,
            'events_found': 0, 'events_new': 0, 'events_pending': 0,
            'events_batch': 0, 'events_reported': 0, 'delivery_attempted': False,
            'drop_confirm_ticks': drop_confirm_ticks(),
            'regime': 'DISABLED', 'halt': False, 'halt_reasons': [], 'report': None,
            'elapsed_s': round(time.time() - t0, 1),
        }

    snap = collectors.fetch_leaders(source)
    gate = collectors.load_regime_inputs()
    reg = rg.evaluate(snap, gate, market_open=market_open_now())
    observed_at = str(snap.get('observed_at') or snap['ts'])
    day = observed_at[:10].replace('-', '')
    n_confirm = drop_confirm_ticks()
    stabilizing = in_open_stabilization(observed_at)
    new_entries_suppressed = suppress_new_leaders(observed_at)
    snapshot_usable = not bool(snap.get('error'))
    snapshot_persisted, collection_backoff_s, collection_error_streak = (
        snapshot_persistence_decision(snap)
    )

    with memory.connect() as con:
        prev = memory.last_snapshot(con, day=day)
        comparison_prev = prev if prev and not prev.get('error') else None
        source_revision_baseline = bool(
            snapshot_persisted
            and snapshot_usable
            and same_source_observation(comparison_prev, snap)
            and not same_source_snapshot(comparison_prev, snap)
        )
        if source_revision_baseline:
            # Same producer timestamp with different normalized content means
            # a scoring/normalization deployment, not a market transition.
            comparison_prev = None
        duplicate_source_snapshot = bool(
            snapshot_persisted and snapshot_usable and same_source_snapshot(comparison_prev, snap)
        )
        if duplicate_source_snapshot:
            snapshot_persisted = False
        snap_id = None
        regime_persisted = False
        found: list[dict[str, Any]] = []
        new_n = 0
        if snapshot_persisted:
            snap_id = memory.save_snapshot(con, snap)
            memory.save_regime(con, observed_at, reg)
            regime_persisted = True
            already = memory.today_event_keys(con, day)
            if not (reg['halt'] or stabilizing or not snapshot_usable):
                found = ev.diff(
                    comparison_prev, snap, already=already,
                    include_drops=(n_confirm <= 1), include_new=not new_entries_suppressed,
                )
                if n_confirm > 1:
                    window = memory.last_n_snapshots(con, n_confirm + 1, day=day)
                    found += ev.confirmed_drops(window, n_confirm, already=already)
            new_n = memory.save_events(con, found)
        elif duplicate_source_snapshot and not same_regime_state(memory.last_regime(con), reg):
            # The market gate can change while the KIS source timestamp stays
            # constant. Preserve that transition without reprocessing events.
            memory.save_regime(con, observed_at, reg)
            regime_persisted = True
        # Detection remains day-scoped, but delivery drains older failures so
        # a 15:29 transport outage is not silently abandoned at day rollover.
        pending = memory.pending_events(con, day, include_prior=True)
        queued = [] if reg['halt'] or stabilizing or not snapshot_usable else pending
        halt_episode = memory.current_halt_episode(con, day) if reg['halt'] else None

    # The observation ledger is intentionally outside the operational DB
    # transaction. Its fail-open boundary guarantees schema/lock/data errors
    # cannot roll back detection rows or suppress delivery.
    observation_result: dict[str, Any] = {
        'ok': True, 'mode': 'shadow', 'skipped': True, 'scan_id': None,
    }
    if snapshot_persisted or regime_persisted:
        observation_result = observation.record_tick_fail_open(
            snapshot_id=snap_id,
            snapshot=snap,
            gate=gate,
            regime=reg,
            events=found,
            allow_baseline_open=not stabilizing,
        )

    batch = queued[:EVENT_BATCH_SIZE]
    event_delivery_id = event_batch_delivery_id(batch) if batch else None
    halt_key = str((halt_episode or {}).get('ts') or '') or None
    current_halt_delivery_id = halt_delivery_id(halt_key) if halt_key else None
    halt_text = reporter.halt_message(halt_episode or reg, halt_key or observed_at) if halt_key else None
    halt_already_delivered = False
    if halt_text and halt_key and current_halt_delivery_id:
        with memory.connect() as con:
            digest = delivery.delivery_digest(
                'halt', halt_text, delivery_id=current_halt_delivery_id,
            )
            halt_already_delivered = memory.brief_exists(con, digest)
        halt_already_delivered = halt_already_delivered or _halt_reported_episode == halt_key

    if halt_key != _halt_retry_episode:
        _halt_retry_episode = halt_key
        _halt_retry_not_before = 0.0
    if not halt_key:
        _halt_reported_episode = None

    report = None
    reported_n = 0
    delivery_attempted = False
    if batch:
        now_mono = _monotonic()
        if now_mono < _event_retry_not_before:
            report = {
                'kind': 'event', 'sent': False, 'mode': 'backoff', 'error': 'delivery_backoff',
                'retry_in_s': round(_event_retry_not_before - now_mono, 1),
            }
        else:
            delivery_attempted = True
            # Pass the full queue so the message states how many rows remain,
            # but only mark the five rows represented by this delivery.
            text = reporter.event_message(queued, reg)
            report = delivery.deliver(
                'event', text, send=send, delivery_id=event_delivery_id,
            )
        delivered = bool(report.get('sent') or report.get('already_delivered'))
        if delivery_attempted and delivered:
            with memory.connect() as con:
                memory.mark_reported(con, batch, datetime.now().isoformat(timespec='seconds'))
            reported_n = len(batch)
            _event_retry_not_before = 0.0
        elif delivery_attempted:
            _event_retry_not_before = now_mono + delivery_retry_seconds()
    elif halt_text and halt_key and not halt_already_delivered:
        now_mono = _monotonic()
        if now_mono < _halt_retry_not_before:
            report = {
                'kind': 'halt', 'sent': False, 'mode': 'backoff', 'error': 'delivery_backoff',
                'retry_in_s': round(_halt_retry_not_before - now_mono, 1),
            }
        else:
            delivery_attempted = True
            report = delivery.deliver(
                'halt', halt_text, send=send, delivery_id=current_halt_delivery_id,
            )
            delivered = bool(report.get('sent') or report.get('already_delivered'))
            if delivered:
                _halt_reported_episode = halt_key
                _halt_retry_not_before = 0.0
            else:
                _halt_retry_not_before = now_mono + delivery_retry_seconds()

    out = {
        'ts': snap['ts'], 'source': snap.get('source'),
        'rows': sum(1 for row in (snap.get('rows') or []) if not row.get('detection_unknown')),
        'by_grade': snap.get('by_grade'), 'snapshot_id': snap_id,
        'baseline': comparison_prev is None, 'observed_at': observed_at,
        'stabilizing': stabilizing, 'new_entries_suppressed': new_entries_suppressed,
        'disabled': False, 'snapshot_persisted': snapshot_persisted,
        'duplicate_source_snapshot': duplicate_source_snapshot,
        'source_revision_baseline': source_revision_baseline,
        'regime_persisted': regime_persisted,
        'collection_backoff_s': round(collection_backoff_s, 1),
        'collection_error_streak': collection_error_streak,
        'events_found': len(found), 'events_new': new_n, 'drop_confirm_ticks': n_confirm,
        'events_pending': len(pending) - reported_n,
        'events_batch': len(batch) if delivery_attempted else 0,
        'events_reported': reported_n, 'delivery_attempted': delivery_attempted,
        'regime': reg['regime'], 'halt': reg['halt'], 'halt_reasons': reg['reasons'],
        'observation': observation_result,
        'report': report, 'elapsed_s': round(time.time() - t0, 1),
    }
    write_heartbeat({'state': 'halt' if reg['halt'] else 'running', 'last_tick': out['ts'],
                     'halt': reg['halt'], 'stabilizing': stabilizing,
                      'new_entries_suppressed': new_entries_suppressed,
                      'snapshot_persisted': snapshot_persisted,
                      'duplicate_source_snapshot': duplicate_source_snapshot,
                      'source_revision_baseline': source_revision_baseline,
                      'collection_backoff_s': out['collection_backoff_s'],
                     'collection_error_streak': collection_error_streak,
                     'events_found': len(found), 'events_pending': out['events_pending'],
                     'observation_ok': bool(observation_result.get('ok'))})
    return out


def run_loop(*, source: str = 'auto', interval: int = 5, idle_interval: int = 60, send: bool = False) -> int:
    if not acquire_pid_lock():
        print('[claw] another instance holds data/claw/claw.pid — exiting')
        return 2
    consecutive_errors = 0
    try:
        write_heartbeat({'state': 'starting'})
        while True:
            try:
                if not claw_enabled():
                    write_heartbeat({'state': 'disabled', 'disabled': True})
                    time.sleep(idle_interval)
                    continue
                if not market_open_now():
                    write_heartbeat({'state': 'idle'})
                    time.sleep(idle_interval)
                    continue
                tick_started = _monotonic()
                out = run_tick(source=source, send=send)
                consecutive_errors = 0
                print(json.dumps(out, ensure_ascii=False), flush=True)
                time.sleep(next_tick_delay(interval, _monotonic() - tick_started))
            except KeyboardInterrupt:
                return 0
            except Exception as e:  # noqa: BLE001
                consecutive_errors += 1
                print(f"[claw] tick error #{consecutive_errors}: {type(e).__name__}: {e}", flush=True)
                write_heartbeat({'state': 'error', 'consecutive_errors': consecutive_errors})
                time.sleep(30 if consecutive_errors >= 3 else interval)
    finally:
        release_pid_lock()

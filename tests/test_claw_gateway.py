"""Claw resident gateway safety and delivery-queue contracts."""
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from marketflow_claw import gateway as gw
from marketflow_claw import memory as mem


def _row(code: str, grade: str) -> dict:
    return {
        'code': code, 'name': f'종목{code}', 'grade': grade, 'score': 70,
        'chg': 3.0, 'trval_eok': 100.0, 'volx': 100.0, 'price': 1000,
        'high_52w': 1200, 'rank': int(code),
    }


def _snap(ts: str, grades: list[str]) -> dict:
    rows = [_row(f'{idx:03d}', grade) for idx, grade in enumerate(grades, 1)]
    return {
        'ts': ts, 'market_status': 'open', 'source': 'test', 'error': None,
        'by_grade': {grade: grades.count(grade) for grade in set(grades)}, 'rows': rows,
    }


def _setup(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(mem, 'DB_PATH', str(tmp_path / 'claw.db'))
    monkeypatch.setenv('CLAW_ENABLED', '1')
    monkeypatch.setenv('CLAW_DROP_CONFIRM_TICKS', '1')
    monkeypatch.setenv('CLAW_DELIVERY_RETRY_SECONDS', '60')
    monkeypatch.setattr(gw, '_event_retry_not_before', 0.0)
    monkeypatch.setattr(gw, '_halt_retry_not_before', 0.0)
    monkeypatch.setattr(gw, '_halt_retry_episode', None)
    monkeypatch.setattr(gw, '_halt_reported_episode', None)
    monkeypatch.setattr(gw, '_collection_error_key', None)
    monkeypatch.setattr(gw, '_collection_error_streak', 0)
    monkeypatch.setattr(gw, '_collection_persist_not_before', 0.0)
    monkeypatch.setattr(gw, 'write_heartbeat', lambda extra=None: None)
    monkeypatch.setattr(gw, 'market_open_now', lambda: True)
    monkeypatch.setattr(gw.collectors, 'load_regime_inputs', lambda: {'available': True})
    monkeypatch.setattr(
        gw.rg,
        'evaluate',
        lambda snap, gate, market_open: {
            'regime': 'NEUTRAL', 'halt': False, 'reasons': [], 'breadth_pct': 50,
            'gate_status': 'GREEN', 'gate_score': 70,
        },
    )


def _save_snapshot(snap: dict) -> None:
    with mem.connect() as con:
        mem.save_snapshot(con, snap)


def test_first_tick_of_new_trading_day_is_baseline(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    _save_snapshot(_snap('2026-08-21T15:29:55', ['B']))
    monkeypatch.setattr(gw.collectors, 'fetch_leaders', lambda source: _snap('2026-08-24T10:00:00', ['A']))
    monkeypatch.setattr(
        gw.delivery, 'deliver',
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('baseline must not deliver')),
    )

    out = gw.run_tick(send=True)

    assert out['baseline'] is True
    assert out['events_found'] == out['events_new'] == out['events_pending'] == 0
    with mem.connect() as con:
        assert mem.list_events(con, '20260824') == []


def test_open_stabilization_suppresses_events_until_0905(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    _save_snapshot(_snap('2026-08-24T09:00:00', ['B', 'B']))
    snapshots = iter([
        _snap('2026-08-24T09:04:59', ['A', 'B']),
        _snap('2026-08-24T09:05:00', ['A', 'A']),
    ])
    monkeypatch.setattr(gw.collectors, 'fetch_leaders', lambda source: next(snapshots))
    delivered = []
    observation_baseline_flags = []
    monkeypatch.setattr(
        gw.observation, 'record_tick_fail_open',
        lambda **kwargs: observation_baseline_flags.append(kwargs['allow_baseline_open']) or {
            'ok': True, 'mode': 'shadow', 'scan_id': 1,
        },
    )
    monkeypatch.setattr(
        gw.delivery, 'deliver',
        lambda kind, text, send=False, delivery_id=None: delivered.append(text) or {
            'kind': kind, 'sent': True, 'mode': 'test', 'error': None,
        },
    )

    suppressed = gw.run_tick(send=True)
    emitted = gw.run_tick(send=True)

    assert suppressed['stabilizing'] is True and suppressed['events_found'] == 0
    assert emitted['stabilizing'] is False and emitted['events_found'] == 1
    assert observation_baseline_flags == [False, True]
    assert len(delivered) == 1 and '종목002' in delivered[0] and '종목001' not in delivered[0]


def test_late_cutoff_suppresses_only_new_and_still_delivers_pending(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    _save_snapshot({
        **_snap('2026-08-24T15:19:55', []),
        'rows': [_row('001', 'B')],
        'by_grade': {'B': 1},
    })
    pending = {
        **_row('900', 'A'),
        'type': 'LEADER_NEW', 'ts': '2026-08-24T15:10:00',
        'grade_from': '', 'grade_to': 'A',
    }
    with mem.connect() as con:
        mem.save_events(con, [pending])

    current = {
        **_snap('2026-08-24T15:20:00', []),
        'observed_at': '2026-08-24T15:20:00',
        'rows': [_row('001', 'A'), _row('002', 'S')],
        'by_grade': {'A': 1, 'S': 1},
    }
    monkeypatch.setattr(gw.collectors, 'fetch_leaders', lambda source: current)
    messages = []
    monkeypatch.setattr(
        gw.delivery, 'deliver',
        lambda kind, text, send=False, delivery_id=None: messages.append(text) or {
            'kind': kind, 'sent': True, 'mode': 'test', 'error': None,
        },
    )

    out = gw.run_tick(send=True)
    with mem.connect() as con:
        rows = mem.list_events(con, '20260824')

    assert out['new_entries_suppressed'] is True
    assert out['events_found'] == out['events_new'] == 1
    assert out['events_reported'] == 2 and out['events_pending'] == 0
    assert {(row['type'], row['code']) for row in rows} == {
        ('LEADER_NEW', '900'), ('LEADER_UPGRADE', '001'),
    }
    assert len(messages) == 1
    assert '종목900' in messages[0] and '종목001' in messages[0] and '종목002' not in messages[0]


def test_stale_prior_day_fallback_cannot_seed_monday_transitions(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    _save_snapshot(_snap('2026-08-23T15:29:55', ['B']))
    stale = {
        **_snap('2026-08-24T09:00:30', ['A']),
        'data_ts': '2026-08-23T20:54:20',
        'observed_at': '2026-08-24T09:00:30',
        'source': 'file(poller_busy)',
        'error': 'kis_poller_busy_stale_file',
        'data_stale': True,
    }
    snapshots = iter([
        stale,
        _snap('2026-08-24T09:05:05', ['B']),
        _snap('2026-08-24T09:05:10', ['A']),
    ])
    monkeypatch.setattr(gw.collectors, 'fetch_leaders', lambda source: next(snapshots))
    delivered = []
    monkeypatch.setattr(
        gw.delivery, 'deliver',
        lambda kind, text, send=False, delivery_id=None: delivered.append(text) or {
            'kind': kind, 'sent': True, 'mode': 'test', 'error': None,
        },
    )

    stale_tick = gw.run_tick(send=True)
    fresh_baseline = gw.run_tick(send=True)
    transition = gw.run_tick(send=True)

    assert stale_tick['stabilizing'] is True and stale_tick['events_found'] == 0
    assert fresh_baseline['baseline'] is True and fresh_baseline['events_found'] == 0
    assert transition['baseline'] is False and transition['events_found'] == 1
    assert len(delivered) == 1 and '종목001' in delivered[0]


def test_error_snapshot_cannot_emit_transitions_outside_stabilization(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    _save_snapshot(_snap('2026-08-24T09:59:55', ['B']))
    failed = {
        **_snap('2026-08-24T10:00:00', []),
        'observed_at': '2026-08-24T10:00:00',
        'error': 'kis_unsafe_scan_and_no_safe_file',
    }
    monkeypatch.setattr(gw.collectors, 'fetch_leaders', lambda source: failed)
    monkeypatch.setattr(
        gw.delivery,
        'deliver',
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError('an error snapshot must not create or deliver transitions')
        ),
    )

    out = gw.run_tick(send=True)

    assert out['stabilizing'] is False
    assert out['events_found'] == out['events_new'] == 0


def test_failed_or_unsent_event_retries_then_marks_only_success(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    _save_snapshot(_snap('2026-08-24T09:59:55', ['B']))
    snapshots = iter([
        _snap('2026-08-24T10:00:00', ['A']),
        _snap('2026-08-24T10:00:05', ['A']),
        _snap('2026-08-24T10:01:05', ['A']),
    ])
    monkeypatch.setattr(gw.collectors, 'fetch_leaders', lambda source: next(snapshots))
    monotonic = iter([100.0, 105.0, 161.0])
    monkeypatch.setattr(gw, '_monotonic', lambda: next(monotonic))
    results = iter([
        {'kind': 'event', 'sent': False, 'mode': 'test', 'error': 'network'},
        {'kind': 'event', 'sent': True, 'mode': 'test', 'error': None},
    ])
    calls = []
    monkeypatch.setattr(
        gw.delivery, 'deliver',
        lambda kind, text, send=False, delivery_id=None: calls.append(text) or next(results),
    )

    failed = gw.run_tick(send=True)
    with mem.connect() as con:
        after_failure = mem.list_events(con, '20260824')
    backed_off = gw.run_tick(send=True)
    with mem.connect() as con:
        after_backoff = mem.list_events(con, '20260824')
    succeeded = gw.run_tick(send=True)
    with mem.connect() as con:
        after_success = mem.list_events(con, '20260824')

    assert failed['events_new'] == 1 and failed['events_reported'] == 0
    assert after_failure[0]['reported_at'] is None
    assert backed_off['delivery_attempted'] is False
    assert backed_off['report']['mode'] == 'backoff' and backed_off['report']['retry_in_s'] == 55.0
    assert after_backoff[0]['reported_at'] is None
    assert succeeded['events_new'] == 0 and succeeded['events_reported'] == 1
    assert after_success[0]['reported_at'] is not None
    assert len(calls) == 2


def test_event_batches_over_five_carry_to_next_tick(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    _save_snapshot(_snap('2026-08-24T09:59:55', ['B'] * 7))
    snapshots = iter([
        _snap('2026-08-24T10:00:00', ['A'] * 7),
        _snap('2026-08-24T10:00:05', ['A'] * 7),
    ])
    monkeypatch.setattr(gw.collectors, 'fetch_leaders', lambda source: next(snapshots))
    queue_sizes = []
    monkeypatch.setattr(
        gw.reporter, 'event_message',
        lambda events, reg: queue_sizes.append(len(events)) or f'queue:{len(events)}',
    )
    monkeypatch.setattr(
        gw.delivery, 'deliver',
        lambda kind, text, send=False, delivery_id=None: {
            'kind': kind, 'sent': True, 'mode': 'test', 'error': None,
        },
    )

    first = gw.run_tick(send=True)
    with mem.connect() as con:
        remaining = mem.pending_events(con, '20260824')
    second = gw.run_tick(send=True)
    with mem.connect() as con:
        done = mem.pending_events(con, '20260824')

    assert first['events_new'] == 7 and first['events_reported'] == 5 and first['events_pending'] == 2
    assert [event['code'] for event in remaining] == ['006', '007']
    assert second['events_new'] == 0 and second['events_reported'] == 2 and second['events_pending'] == 0
    assert done == [] and queue_sizes == [7, 2]


def test_event_batch_delivery_id_is_day_scoped_and_retry_stable():
    first = {
        **_row('001', 'A'), 'type': 'LEADER_UPGRADE',
        'ts': '2026-08-24T15:29:55', 'grade_from': 'B', 'grade_to': 'A',
    }
    next_day = {**first, 'ts': '2026-08-25T15:29:55'}

    first_id = gw.event_batch_delivery_id([first])
    retry_id = gw.event_batch_delivery_id([dict(first)])
    next_day_id = gw.event_batch_delivery_id([next_day])

    assert retry_id == first_id
    assert next_day_id != first_id
    assert gw.delivery.delivery_digest('event', '같은 본문', delivery_id=next_day_id) != (
        gw.delivery.delivery_digest('event', '같은 본문', delivery_id=first_id)
    )


def test_failed_1529_event_retries_next_day_without_redetection(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    _save_snapshot(_snap('2026-08-24T15:29:50', ['B']))
    snapshots = iter([
        _snap('2026-08-24T15:29:55', ['A']),
        _snap('2026-08-25T09:05:00', ['A']),
    ])
    monkeypatch.setattr(gw.collectors, 'fetch_leaders', lambda source: next(snapshots))
    monotonic = iter([100.0, 1_000.0])
    monkeypatch.setattr(gw, '_monotonic', lambda: next(monotonic))
    responses = iter([
        {'kind': 'event', 'sent': False, 'mode': 'test', 'error': 'network'},
        {'kind': 'event', 'sent': True, 'mode': 'test', 'error': None},
    ])
    calls = []
    monkeypatch.setattr(
        gw.delivery, 'deliver',
        lambda kind, text, send=False, delivery_id=None: (
            calls.append((text, delivery_id)) or next(responses)
        ),
    )

    failed = gw.run_tick(send=True)
    retried = gw.run_tick(send=True)

    with mem.connect() as con:
        prior_events = mem.list_events(con, '20260824')
        current_events = mem.list_events(con, '20260825')
        backlog = mem.pending_events(con, '20260825', include_prior=True)

    assert failed['new_entries_suppressed'] is True
    assert failed['events_new'] == 1 and failed['events_pending'] == 1
    assert retried['baseline'] is True and retried['events_new'] == 0
    assert retried['events_reported'] == 1 and retried['events_pending'] == 0
    assert len(prior_events) == 1 and prior_events[0]['reported_at'] is not None
    assert current_events == [] and backlog == []
    assert len(calls) == 2 and calls[0][1] == calls[1][1]


def test_delivery_disabled_result_uses_retry_backoff(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    _save_snapshot(_snap('2026-08-24T09:59:55', ['B']))
    snapshots = iter([
        _snap('2026-08-24T10:00:00', ['A']),
        _snap('2026-08-24T10:00:05', ['A']),
    ])
    monkeypatch.setattr(gw.collectors, 'fetch_leaders', lambda source: next(snapshots))
    monotonic = iter([200.0, 205.0])
    monkeypatch.setattr(gw, '_monotonic', lambda: next(monotonic))
    calls = []
    monkeypatch.setattr(
        gw.delivery, 'deliver',
        lambda kind, text, send=False, delivery_id=None: calls.append(text) or {
            'kind': kind, 'sent': False, 'mode': 'dry-run',
            'error': 'CLAW_DELIVERY_ENABLED is not set',
        },
    )

    disabled = gw.run_tick(send=True)
    backed_off = gw.run_tick(send=True)

    assert disabled['delivery_attempted'] is True and disabled['events_pending'] == 1
    assert backed_off['delivery_attempted'] is False
    assert backed_off['report']['mode'] == 'backoff' and backed_off['events_pending'] == 1
    assert len(calls) == 1


def test_repeated_halt_only_notifies_on_entry(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    snapshots = iter([
        _snap('2026-08-24T13:00:00', []),
        _snap('2026-08-24T13:00:05', []),
    ])
    monkeypatch.setattr(gw.collectors, 'fetch_leaders', lambda source: next(snapshots))
    monkeypatch.setattr(
        gw.rg, 'evaluate',
        lambda snap, gate, market_open: {
            'regime': 'NEUTRAL', 'halt': True, 'reasons': ['source error'], 'breadth_pct': 0,
        },
    )
    calls = []
    monkeypatch.setattr(
        gw.delivery, 'deliver',
        lambda kind, text, send=False, delivery_id=None: calls.append((kind, text)) or {
            'kind': kind, 'sent': True, 'mode': 'test', 'error': None,
        },
    )

    first = gw.run_tick(send=True)
    second = gw.run_tick(send=True)

    assert first['report'] is not None and second['report'] is None
    assert len(calls) == 1 and calls[0][0] == 'halt'


def test_same_minute_halt_reentry_gets_a_new_logical_delivery(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    snapshots = iter([
        _snap('2026-08-24T13:00:00', []),
        _snap('2026-08-24T13:00:05', []),
        _snap('2026-08-24T13:00:10', []),
    ])
    monkeypatch.setattr(gw.collectors, 'fetch_leaders', lambda source: next(snapshots))
    halt_states = iter([True, False, True])

    def evaluate(snap, gate, market_open):
        halted = next(halt_states)
        return {
            'regime': 'NEUTRAL', 'halt': halted,
            'reasons': ['source error'] if halted else [], 'breadth_pct': 0,
        }

    monkeypatch.setattr(gw.rg, 'evaluate', evaluate)
    calls = []
    monkeypatch.setattr(
        gw.delivery, 'deliver',
        lambda kind, text, send=False, delivery_id=None: (
            calls.append((kind, text, delivery_id)) or {
                'kind': kind, 'sent': True, 'mode': 'test', 'error': None,
            }
        ),
    )

    entered = gw.run_tick(send=True)
    cleared = gw.run_tick(send=True)
    reentered = gw.run_tick(send=True)

    assert entered['report'] is not None and cleared['report'] is None
    assert reentered['report'] is not None and len(calls) == 2
    assert calls[0][1] == calls[1][1]  # rendered HH:MM text is intentionally identical
    assert calls[0][2] != calls[1][2]
    assert gw.delivery.delivery_digest('halt', calls[0][1], delivery_id=calls[0][2]) != (
        gw.delivery.delivery_digest('halt', calls[1][1], delivery_id=calls[1][2])
    )


def test_failed_halt_retries_after_backoff_then_suppresses_episode(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    snapshots = iter([
        _snap('2026-08-24T13:00:00', []),
        _snap('2026-08-24T13:00:05', []),
        _snap('2026-08-24T13:01:01', []),
        _snap('2026-08-24T13:01:06', []),
    ])
    monkeypatch.setattr(gw.collectors, 'fetch_leaders', lambda source: next(snapshots))
    monkeypatch.setattr(
        gw.rg, 'evaluate',
        lambda snap, gate, market_open: {
            'regime': 'NEUTRAL', 'halt': True, 'reasons': ['source error'], 'breadth_pct': 0,
        },
    )
    monotonic = iter([100.0, 105.0, 161.0])
    monkeypatch.setattr(gw, '_monotonic', lambda: next(monotonic))
    responses = iter([
        {'kind': 'halt', 'sent': False, 'mode': 'test', 'error': 'network'},
        {'kind': 'halt', 'sent': True, 'mode': 'test', 'error': None},
    ])
    messages = []
    monkeypatch.setattr(
        gw.delivery, 'deliver',
        lambda kind, text, send=False, delivery_id=None: messages.append(text) or next(responses),
    )

    failed = gw.run_tick(send=True)
    backed_off = gw.run_tick(send=True)
    succeeded = gw.run_tick(send=True)
    suppressed = gw.run_tick(send=True)

    assert failed['delivery_attempted'] is True and failed['report']['sent'] is False
    assert backed_off['delivery_attempted'] is False and backed_off['report']['mode'] == 'backoff'
    assert succeeded['delivery_attempted'] is True and succeeded['report']['sent'] is True
    assert suppressed['delivery_attempted'] is False and suppressed['report'] is None
    assert len(messages) == 2 and messages[0] == messages[1]


def test_master_kill_switch_prevents_collection(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    monkeypatch.setenv('CLAW_ENABLED', 'false')
    heartbeats = []
    monkeypatch.setattr(gw, 'write_heartbeat', lambda extra=None: heartbeats.append(extra))
    monkeypatch.setattr(
        gw.collectors, 'fetch_leaders',
        lambda source: (_ for _ in ()).throw(AssertionError('disabled Claw must not collect')),
    )

    out = gw.run_tick(send=True)

    assert out['disabled'] is True and out['regime'] == 'DISABLED'
    assert heartbeats == [{'state': 'disabled', 'disabled': True}]
    assert not (tmp_path / 'claw.db').exists()


def test_run_loop_keeps_start_to_start_cadence_after_slow_tick(monkeypatch):
    monkeypatch.setenv('CLAW_ENABLED', '1')
    monkeypatch.setattr(gw, 'acquire_pid_lock', lambda: True)
    released = []
    monkeypatch.setattr(gw, 'release_pid_lock', lambda: released.append(True))
    monkeypatch.setattr(gw, 'write_heartbeat', lambda extra=None: None)
    monkeypatch.setattr(gw, 'market_open_now', lambda: True)
    ticks = []

    def fake_tick(*, source='auto', send=False):
        ticks.append((source, send))
        if len(ticks) == 3:
            raise KeyboardInterrupt
        return {'tick': len(ticks)}

    monkeypatch.setattr(gw, 'run_tick', fake_tick)
    monotonic = iter([100.0, 102.0, 105.0, 113.0, 114.0])
    monkeypatch.setattr(gw, '_monotonic', lambda: next(monotonic))
    sleeps = []
    monkeypatch.setattr(gw.time, 'sleep', lambda seconds: sleeps.append(seconds))

    result = gw.run_loop(source='auto', interval=5, send=True)

    assert result == 0 and released == [True]
    assert sleeps == [3.0, gw.MIN_LOOP_YIELD_SECONDS]
    assert ticks == [('auto', True), ('auto', True), ('auto', True)]


def test_heartbeat_write_failure_is_nonfatal_and_rate_limited(monkeypatch, capsys):
    monkeypatch.setattr(gw, 'ensure_dirs', lambda: None)
    attempts = []

    def fail_write(*args, **kwargs):
        attempts.append((args, kwargs))
        raise PermissionError(5, 'destination is temporarily locked')

    monkeypatch.setattr(gw, 'write_json_atomic', fail_write)
    monkeypatch.setattr(gw, '_heartbeat_error_log_not_before', 0.0)
    monkeypatch.setattr(gw, '_heartbeat_errors_suppressed', 0)
    clocks = iter([100.0, 105.0, 161.0])
    monkeypatch.setattr(gw, '_heartbeat_monotonic', lambda: next(clocks))

    results = [gw.write_heartbeat({'state': 'running'}) for _ in range(3)]

    lines = capsys.readouterr().err.strip().splitlines()
    assert results == [False, False, False]
    assert len(attempts) == 3
    assert len(lines) == 2
    assert all('monitoring continues' in line for line in lines)
    assert 'suppressed 1 similar errors' in lines[1]


def test_run_loop_survives_repeated_heartbeat_storage_failures(monkeypatch):
    monkeypatch.setenv('CLAW_ENABLED', '1')
    monkeypatch.setattr(gw, 'acquire_pid_lock', lambda: True)
    released = []
    monkeypatch.setattr(gw, 'release_pid_lock', lambda: released.append(True))
    monkeypatch.setattr(gw, 'market_open_now', lambda: True)
    monkeypatch.setattr(gw, '_heartbeat_error_log_not_before', 0.0)
    monkeypatch.setattr(gw, '_heartbeat_errors_suppressed', 0)
    monkeypatch.setattr(gw, '_heartbeat_monotonic', lambda: 100.0)
    writes = []

    def fail_write(*args, **kwargs):
        writes.append((args, kwargs))
        raise PermissionError(5, 'destination is temporarily locked')

    monkeypatch.setattr(gw, 'write_json_atomic', fail_write)
    ticks = []

    def fake_tick(*, source='auto', send=False):
        ticks.append((source, send))
        gw.write_heartbeat({'state': 'running', 'last_tick': len(ticks)})
        if len(ticks) == 3:
            raise KeyboardInterrupt
        return {'tick': len(ticks)}

    monkeypatch.setattr(gw, 'run_tick', fake_tick)
    monotonic = iter([100.0, 101.0, 105.0, 106.0, 110.0])
    monkeypatch.setattr(gw, '_monotonic', lambda: next(monotonic))
    sleeps = []
    monkeypatch.setattr(gw.time, 'sleep', lambda seconds: sleeps.append(seconds))

    result = gw.run_loop(source='auto', interval=5, send=True)

    assert result == 0 and released == [True]
    assert ticks == [('auto', True), ('auto', True), ('auto', True)]
    assert len(writes) == 4  # starting heartbeat plus all three tick heartbeats
    assert sleeps == [4.0, 4.0]


def test_resident_launcher_enables_real_delivery():
    launcher = Path(__file__).parents[1] / 'deploy' / 'start_claw.vbs'
    command = launcher.read_text(encoding='utf-8')
    assert 'marketflow_claw start --source auto --send' in command


def test_text_leaders_cli_hides_detection_unknown_guards(monkeypatch, capsys):
    from marketflow_claw import cli

    visible = _row('001', 'A')
    guard = dict(_row('002', 'C'), detection_unknown=True, score_complete=False)
    monkeypatch.setattr(
        cli.collectors, 'fetch_leaders',
        lambda source: {
            'ts': '2026-08-24T10:00:00', 'market_status': 'open', 'source': 'test',
            'by_grade': {'A': 1}, 'error': None, 'rows': [visible, guard],
        },
    )

    assert cli.cmd_leaders(SimpleNamespace(source='file', json=False, top=10)) == 0
    output = capsys.readouterr().out
    assert '001' in output and '002' not in output


def test_auto_source_accepts_worker_file_during_long_scan(monkeypatch):
    from marketflow_claw import collectors

    expected = _snap('2026-08-24T10:00:00', ['A'])
    monkeypatch.setattr(collectors, '_now', lambda: datetime(2026, 8, 24, 10, 0, 45))
    monkeypatch.setattr(collectors, '_file_age_seconds', lambda path: 45.0)
    monkeypatch.setattr(collectors, 'load_leaders_file', lambda: expected)
    monkeypatch.setattr(
        collectors,
        '_canonical_producer_poller_state',
        lambda: (_ for _ in ()).throw(AssertionError('fresh file must not inspect producer failover')),
    )
    monkeypatch.setattr(
        collectors, 'fetch_leaders_kis',
        lambda: (_ for _ in ()).throw(AssertionError('45-second worker file must remain fresh')),
    )

    assert collectors.FILE_FRESH_SECONDS >= 90
    assert collectors.fetch_leaders('auto') is expected


def test_claw_direct_scan_falls_back_when_common_poller_busy(monkeypatch, tmp_path):
    from filelock import FileLock
    from app.services import kis_screener
    from marketflow_claw import collectors

    lock_path = str(tmp_path / 'kis_poller.lock')
    monkeypatch.setattr(kis_screener, 'SCREENER_POLLER_LOCK', lock_path)
    monkeypatch.setattr(collectors, '_now', lambda: datetime(2026, 8, 24, 10, 0, 30))
    fallback = dict(_snap('2026-08-24T10:00:00', ['A']), file_age_s=30.0)
    monkeypatch.setattr(collectors, 'load_leaders_file', lambda: dict(fallback))
    monkeypatch.setattr(
        kis_screener, '_run_screening_unlocked',
        lambda force=False: (_ for _ in ()).throw(AssertionError('busy poller must not nest a scan')),
    )

    with FileLock(lock_path):
        result = collectors.fetch_leaders_kis()

    assert result['source'] == 'file(poller_busy)'
    assert result['ts'] == fallback['ts']
    assert result['poller_busy'] is True and result['error'] is None
    assert fallback['source'] == 'test'  # fallback object/file payload was not mutated


def test_claw_poller_busy_prior_day_file_is_marked_stale_at_observation_time(monkeypatch):
    from app.services import kis_screener
    from marketflow_claw import collectors

    monkeypatch.setattr(collectors, '_now', lambda: datetime(2026, 8, 24, 9, 0, 30))
    monkeypatch.setattr(kis_screener, 'run_screening', lambda force=False: {'poller_busy': True})
    prior_day = dict(_snap('2026-08-23T20:54:20', ['A']), file_age_s=43_000.0)
    monkeypatch.setattr(collectors, 'load_leaders_file', lambda: dict(prior_day))

    result = collectors.fetch_leaders_kis()

    assert result['ts'] == result['observed_at'] == '2026-08-24T09:00:30'
    assert result['data_ts'] == '2026-08-23T20:54:20'
    assert result['error'] == 'kis_poller_busy_stale_file'
    assert result['data_stale'] is True
    assert {'data_day_mismatch', 'file_age_exceeded', 'data_age_exceeded'} <= set(result['stale_reasons'])


def test_claw_unsafe_scan_falls_back_to_known_good_file(monkeypatch):
    from app.services import kis_screener
    from marketflow_claw import collectors

    unsafe = {
        'timestamp': '2026-08-24T10:00:30',
        'market_status': 'open',
        'results': [{'code': '999999', 'grade': 'A', 'score': {'total': 70}}],
        'data_quality': {
            'critical_complete': True,
            'score_reliable': False,
            'safe_to_replace_latest': False,
            'partial_failure_reasons': ['investor_missing'],
        },
    }
    fallback = dict(
        _snap('2026-08-24T10:00:00', ['A']),
        observed_at='2026-08-24T10:00:30',
        data_ts='2026-08-24T10:00:00',
        data_age_s=30.0,
        file_age_s=30.0,
    )
    monkeypatch.setattr(kis_screener, 'run_screening', lambda force=False: unsafe)
    monkeypatch.setattr(collectors, 'load_leaders_file', lambda: dict(fallback))

    result = collectors.fetch_leaders_kis()

    assert result['source'] == 'file(unsafe_scan)'
    assert result['unsafe_scan'] is True
    assert result['error'] is None
    assert [row['code'] for row in result['rows']] == ['001']
    assert result['rejected_scan_quality']['score_reliable'] is False


def test_claw_unsafe_scan_without_safe_file_is_explicit_error(monkeypatch):
    from app.services import kis_screener
    from marketflow_claw import collectors

    unsafe = {
        'timestamp': '2026-08-24T10:00:30',
        'market_status': 'open',
        'results': [],
        'candidate_pool': [],
        'data_quality': {
            'critical_complete': True,
            'score_reliable': False,
            'safe_to_replace_latest': False,
        },
    }
    monkeypatch.setattr(kis_screener, 'run_screening', lambda force=False: unsafe)
    monkeypatch.setattr(collectors, 'load_leaders_file', lambda: None)

    result = collectors.fetch_leaders_kis()

    assert result['source'] == 'kis(unsafe_scan)'
    assert result['unsafe_scan'] is True
    assert result['error'] == 'kis_unsafe_scan_and_no_safe_file'


def test_claw_direct_scan_acquires_common_lock_without_nesting(monkeypatch, tmp_path):
    from app.services import kis_screener
    from marketflow_claw import collectors

    monkeypatch.setattr(kis_screener, 'SCREENER_POLLER_LOCK', str(tmp_path / 'kis_poller.lock'))
    raw = {
        'timestamp': '2026-08-24T10:00:00', 'market_status': 'open',
        'results': [], 'candidate_pool': [], 'by_grade': {}, 'api_calls': 0,
    }
    calls = []
    monkeypatch.setattr(
        kis_screener, '_run_screening_unlocked',
        lambda force=False: calls.append(force) or raw,
    )

    result = collectors.fetch_leaders_kis()

    assert result['source'] == 'kis' and result['ts'] == raw['timestamp']
    assert calls == [True]


def test_auto_stale_file_with_active_producer_fails_closed_without_direct_kis_scan(monkeypatch):
    from marketflow_claw import collectors

    cached = _snap('2026-08-24T09:00:00', ['A'])
    monkeypatch.setattr(collectors, '_now', lambda: datetime(2026, 8, 24, 10, 0, 0))
    monkeypatch.setattr(collectors, '_file_age_seconds', lambda path: 3_600.0)
    monkeypatch.setattr(collectors, 'load_leaders_file', lambda: dict(cached))
    monkeypatch.setattr(collectors, '_canonical_producer_poller_state', lambda: 'active')
    monkeypatch.setattr(
        collectors, 'fetch_leaders_kis',
        lambda: (_ for _ in ()).throw(AssertionError('auto must never become a KIS poller')),
    )

    result = collectors.fetch_leaders('auto')

    assert result['source'] == 'file(stale)'
    assert result['ts'] == result['observed_at'] == '2026-08-24T10:00:00'
    assert result['data_ts'] == cached['ts']
    assert result['error'] == 'leaders_file_stale'
    assert result['data_stale'] is True
    assert result['producer_poller_state'] == 'active'
    assert result['auto_failover_attempted'] is False
    assert {'file_age_exceeded', 'data_age_exceeded'} <= set(result['stale_reasons'])
    assert cached['source'] == 'test' and cached['error'] is None


@pytest.mark.parametrize('producer_state', ['stale', 'unavailable'])
def test_auto_stale_file_with_dead_or_unknown_producer_attempts_one_bounded_failover(
        monkeypatch, producer_state):
    from marketflow_claw import collectors

    cached = _snap('2026-08-24T09:00:00', ['A'])
    recovered = _snap('2026-08-24T10:00:00', ['A'])
    recovered['source'] = 'kis'
    calls = []
    monkeypatch.setattr(collectors, '_now', lambda: datetime(2026, 8, 24, 10, 0, 0))
    monkeypatch.setattr(collectors, '_file_age_seconds', lambda path: 3_600.0)
    monkeypatch.setattr(collectors, 'load_leaders_file', lambda: dict(cached))
    monkeypatch.setattr(
        collectors, '_canonical_producer_poller_state', lambda: producer_state,
    )
    monkeypatch.setattr(
        collectors,
        'fetch_leaders_kis',
        lambda: calls.append(True) or dict(recovered),
    )

    result = collectors.fetch_leaders('auto')

    assert calls == [True]
    assert result['source'] == 'kis' and result['error'] is None
    assert result['producer_poller_state'] == producer_state
    assert result['auto_failover_attempted'] is True


@pytest.mark.parametrize(
    ('raw', 'expected_error'),
    [
        ({'poller_busy': True}, 'kis_poller_busy_stale_file'),
        ({
            'timestamp': '2026-08-24T10:00:00',
            'market_status': 'open',
            'results': [{'code': '999999', 'grade': 'A', 'score': {'total': 70}}],
            'data_quality': {
                'critical_complete': True,
                'score_reliable': False,
                'safe_to_replace_latest': False,
            },
        }, 'kis_unsafe_scan_stale_file'),
    ],
)
def test_auto_failover_busy_or_unsafe_scan_remains_fail_closed(
        monkeypatch, raw, expected_error):
    from app.services import kis_screener
    from marketflow_claw import collectors

    cached = _snap('2026-08-24T09:00:00', ['A'])
    calls = []
    monkeypatch.setattr(collectors, '_now', lambda: datetime(2026, 8, 24, 10, 0, 0))
    monkeypatch.setattr(collectors, '_file_age_seconds', lambda path: 3_600.0)
    monkeypatch.setattr(collectors, 'load_leaders_file', lambda: dict(cached))
    monkeypatch.setattr(collectors, '_canonical_producer_poller_state', lambda: 'stale')
    monkeypatch.setattr(
        kis_screener,
        'run_screening',
        lambda force=False: calls.append(force) or dict(raw),
    )

    result = collectors.fetch_leaders('auto')

    assert calls == [True]
    assert result['error'] == expected_error
    assert result['data_stale'] is True
    assert result['auto_failover_attempted'] is True
    assert result['producer_poller_state'] == 'stale'


def test_canonical_producer_state_honors_recent_outcome_and_shared_cooldown(
        monkeypatch, tmp_path):
    from app.services import kis_screener
    from marketflow_claw import collectors

    lock_path = tmp_path / 'kis_poller.lock'
    state_path = Path(f'{lock_path}.state.json')
    monkeypatch.setattr(kis_screener, 'SCREENER_POLLER_LOCK', str(lock_path))
    monkeypatch.setattr(kis_screener, '_token_namespace', lambda: 'real:test')

    def write_state(completed_at, retry_not_before):
        state_path.write_text(json.dumps({
            'version': 1,
            'accounts': {
                'real:test': {
                    'completed_at': completed_at,
                    'retry_not_before': retry_not_before,
                    'reason': 'unsafe_result',
                },
            },
        }), encoding='utf-8')

    write_state(completed_at=900.0, retry_not_before=930.0)
    assert collectors._canonical_producer_poller_state(now=1_000.0) == 'active'
    assert collectors._canonical_producer_poller_state(now=1_100.0) == 'stale'

    write_state(completed_at=700.0, retry_not_before=1_200.0)
    assert collectors._canonical_producer_poller_state(now=1_100.0) == 'active'

    state_path.unlink()
    assert collectors._canonical_producer_poller_state(now=1_100.0) == 'unavailable'


def test_auto_missing_file_fails_closed_without_direct_kis_scan(monkeypatch):
    from marketflow_claw import collectors

    monkeypatch.setattr(collectors, '_now', lambda: datetime(2026, 8, 24, 10, 0, 0))
    monkeypatch.setattr(collectors, '_file_age_seconds', lambda path: None)
    monkeypatch.setattr(collectors, 'load_leaders_file', lambda: None)
    monkeypatch.setattr(
        collectors, 'fetch_leaders_kis',
        lambda: (_ for _ in ()).throw(AssertionError('auto must never become a KIS poller')),
    )

    result = collectors.fetch_leaders('auto')

    assert result['source'] == 'file(auto)'
    assert result['error'] == 'leaders_file_missing'
    assert result['rows'] == [] and result['data_ts'] is None


def test_auto_unsafe_file_fails_closed_without_direct_kis_scan(monkeypatch):
    from marketflow_claw import collectors

    cached = _snap('2026-08-24T10:00:00', ['A'])
    cached['data_quality'] = {'critical_complete': False, 'safe_to_replace_latest': False}
    monkeypatch.setattr(collectors, '_now', lambda: datetime(2026, 8, 24, 10, 0, 5))
    monkeypatch.setattr(collectors, '_file_age_seconds', lambda path: 5.0)
    monkeypatch.setattr(collectors, 'load_leaders_file', lambda: dict(cached))
    monkeypatch.setattr(
        collectors, 'fetch_leaders_kis',
        lambda: (_ for _ in ()).throw(AssertionError('auto must never become a KIS poller')),
    )

    result = collectors.fetch_leaders('auto')

    assert result['source'] == 'file(unsafe)'
    assert result['error'] == 'leaders_file_unsafe'
    assert result['data_stale'] is False
    assert result['rows'] == cached['rows']


def test_repeated_collection_error_backs_off_db_writes_but_keeps_heartbeat(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    observed = [
        '2026-08-24T10:00:00',
        '2026-08-24T10:00:05',
        '2026-08-24T10:00:30',
        '2026-08-24T10:00:31',
        '2026-08-24T10:01:30',
    ]

    def stale(ts, data_ts):
        return {
            **_snap(ts, ['A']),
            'observed_at': ts,
            'data_ts': data_ts,
            'source': 'file(stale)',
            'error': 'leaders_file_stale',
            'data_stale': True,
        }

    # A broken producer may rewrite the same unusable state with changing
    # timestamps. That must not reset the persistence backoff every five seconds.
    data_ts = [
        '2026-08-24T09:00:00',
        '2026-08-24T09:00:05',
        '2026-08-24T09:00:10',
        '2026-08-24T09:00:15',
        '2026-08-24T09:00:20',
    ]
    snapshots = iter(stale(ts, payload_ts) for ts, payload_ts in zip(observed, data_ts))
    monkeypatch.setattr(gw.collectors, 'fetch_leaders', lambda source: next(snapshots))
    monkeypatch.setattr(
        gw.rg, 'evaluate',
        lambda snap, gate, market_open: {
            'regime': 'RISK_OFF', 'halt': True, 'reasons': [snap['error']], 'breadth_pct': 50,
        },
    )
    clocks = iter([0.0, 5.0, 30.0, 31.0, 90.0])
    monkeypatch.setattr(gw, '_collection_monotonic', lambda: next(clocks))
    monkeypatch.setattr(
        gw.delivery, 'deliver',
        lambda kind, text, send=False, delivery_id=None: {
            'kind': kind, 'sent': True, 'mode': 'test', 'error': None,
        },
    )
    heartbeats = []
    monkeypatch.setattr(gw, 'write_heartbeat', lambda extra=None: heartbeats.append(extra))

    outputs = [gw.run_tick(send=True) for _ in observed]

    assert [out['snapshot_persisted'] for out in outputs] == [True, False, True, False, True]
    assert [out['snapshot_id'] for out in outputs] == [1, None, 2, None, 3]
    assert [out['collection_backoff_s'] for out in outputs] == [30.0, 25.0, 60.0, 59.0, 120.0]
    assert [out['collection_error_streak'] for out in outputs] == [1, 1, 2, 2, 3]
    assert len(heartbeats) == len(observed)
    assert [hb['last_tick'] for hb in heartbeats] == observed
    assert [hb['snapshot_persisted'] for hb in heartbeats] == [True, False, True, False, True]
    with mem.connect() as con:
        assert con.execute('SELECT COUNT(*) FROM snapshots').fetchone()[0] == 3
        assert con.execute('SELECT COUNT(*) FROM regimes').fetchone()[0] == 3


def test_fresh_recovery_persists_immediately_and_resets_collection_backoff(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)

    def stale(ts):
        return {
            **_snap(ts, ['A']),
            'observed_at': ts,
            'data_ts': '2026-08-24T09:00:00',
            'source': 'file(stale)',
            'error': 'leaders_file_stale',
            'data_stale': True,
        }

    snapshots = iter([
        stale('2026-08-24T10:00:00'),
        stale('2026-08-24T10:00:05'),
        _snap('2026-08-24T10:00:06', ['A']),
        stale('2026-08-24T10:00:07'),
    ])
    monkeypatch.setattr(gw.collectors, 'fetch_leaders', lambda source: next(snapshots))
    monkeypatch.setattr(
        gw.rg, 'evaluate',
        lambda snap, gate, market_open: {
            'regime': 'RISK_OFF' if snap.get('error') else 'NEUTRAL',
            'halt': bool(snap.get('error')),
            'reasons': [snap['error']] if snap.get('error') else [],
            'breadth_pct': 50,
        },
    )
    clocks = iter([0.0, 5.0, 7.0])
    monkeypatch.setattr(gw, '_collection_monotonic', lambda: next(clocks))
    monkeypatch.setattr(
        gw.delivery, 'deliver',
        lambda kind, text, send=False, delivery_id=None: {
            'kind': kind, 'sent': True, 'mode': 'test', 'error': None,
        },
    )

    outputs = [gw.run_tick(send=True) for _ in range(4)]

    assert [out['snapshot_persisted'] for out in outputs] == [True, False, True, True]
    assert [out['collection_backoff_s'] for out in outputs] == [30.0, 25.0, 0.0, 30.0]
    assert [out['collection_error_streak'] for out in outputs] == [1, 1, 0, 1]
    with mem.connect() as con:
        assert con.execute('SELECT COUNT(*) FROM snapshots').fetchone()[0] == 3
        assert con.execute('SELECT COUNT(*) FROM regimes').fetchone()[0] == 3


def test_repeated_probe_of_same_source_scan_does_not_advance_drop_confirmation(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    monkeypatch.setenv('CLAW_DROP_CONFIRM_TICKS', '3')
    _save_snapshot(_snap('2026-08-24T10:00:00', ['A']))
    lower = _snap('2026-08-24T10:00:30', ['B'])
    snapshots = iter([
        lower,
        dict(lower),
        dict(lower),
        _snap('2026-08-24T10:01:00', ['B']),
        _snap('2026-08-24T10:01:30', ['B']),
    ])
    monkeypatch.setattr(gw.collectors, 'fetch_leaders', lambda source: next(snapshots))
    monkeypatch.setattr(
        gw.delivery, 'deliver',
        lambda kind, text, send=False, delivery_id=None: {
            'kind': kind, 'sent': True, 'mode': 'test', 'error': None,
        },
    )

    outputs = [gw.run_tick(send=True) for _ in range(5)]

    assert [out['snapshot_persisted'] for out in outputs] == [True, False, False, True, True]
    assert [out['duplicate_source_snapshot'] for out in outputs] == [False, True, True, False, False]
    assert [out['events_new'] for out in outputs] == [0, 0, 0, 0, 1]
    with mem.connect() as con:
        assert con.execute('SELECT COUNT(*) FROM snapshots').fetchone()[0] == 4
        events = mem.list_events(con, '20260824')
    assert [(event['type'], event['code']) for event in events] == [('LEADER_DROP', '001')]


def test_same_source_revision_becomes_baseline_without_transition_events(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    previous = _snap('2026-08-24T10:00:00', ['A'])
    _save_snapshot(previous)
    revised = _snap('2026-08-24T10:00:00', ['B'])
    monkeypatch.setattr(gw.collectors, 'fetch_leaders', lambda source: revised)
    monkeypatch.setattr(
        gw.delivery, 'deliver',
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError('same-source scoring revision must not deliver')
        ),
    )

    out = gw.run_tick(send=True)

    assert out['source_revision_baseline'] is True
    assert out['duplicate_source_snapshot'] is False
    assert out['snapshot_persisted'] is True
    assert out['baseline'] is True
    assert out['events_found'] == out['events_new'] == 0
    with mem.connect() as con:
        assert con.execute('SELECT COUNT(*) FROM snapshots').fetchone()[0] == 2
        assert mem.list_events(con, '20260824') == []

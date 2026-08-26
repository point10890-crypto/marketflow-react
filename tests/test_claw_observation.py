"""Shadow Claw ledger: migration, point-in-time context and outcome contracts."""
from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime

from marketflow_claw import memory
from marketflow_claw import observation as obs


def _snap(ts: str, *, code: str = '005930', price: float = 100.0) -> dict:
    return {
        'ts': ts, 'data_ts': ts, 'observed_at': ts, 'source': 'file',
        'market_status': 'open', 'error': None, 'by_grade': {'A': 1},
        'data_quality': {'critical_complete': True, 'score_reliable': True},
        'rows': [{
            'code': code, 'name': '삼성전자', 'grade': 'A', 'score': 70,
            'price': price, 'chg': 2.0, 'score_complete': True,
        }],
    }


def _event(ts: str, kind: str, *, code: str = '005930') -> dict:
    return {
        'ts': ts, 'type': kind, 'code': code, 'name': '삼성전자',
        'grade': 'A', 'grade_from': 'B' if kind != 'LEADER_NEW' else '',
        'grade_to': 'A' if kind != 'LEADER_DROP' else 'B', 'score': 70, 'chg': 2.0,
    }


def _gate(status: str = 'RED') -> dict:
    return {
        'available': True, 'status': status, 'label': status, 'score': 40,
        'updated_at': '2026-08-24T08:50:00', 'age_hours': 1.0,
    }


def _reg(halt: bool = False) -> dict:
    return {
        'regime': 'RISK_OFF', 'halt': halt, 'reasons': ['test'] if halt else [],
        'breadth_pct': 45, 'leader_count': 1,
    }


def _setup(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(memory, 'DB_PATH', str(tmp_path / 'claw.db'))
    timeline = tmp_path / 'regime_timeline.json'
    timeline.write_text(json.dumps({
        'schema_version': 'mirofish.regime_timeline.v1',
        'generated_at': '2026-08-21T15:30:00+09:00',
        'lookahead_safe': True,
        'by_date': {
            '2026-08-14': {'breadth': 0.45, 'regime': 'NEUTRAL'},
            '2026-08-17': {'breadth': 0.47, 'regime': 'NEUTRAL'},
            '2026-08-18': {'breadth': 0.50, 'regime': 'NEUTRAL'},
            '2026-08-19': {'breadth': 0.55, 'regime': 'NEUTRAL'},
            '2026-08-20': {'breadth': 0.58, 'regime': 'NEUTRAL'},
            '2026-08-21': {'breadth': 0.62, 'regime': 'RISK_ON'},
        },
    }), encoding='utf-8')
    monkeypatch.setattr(obs, 'REGIME_TIMELINE_PATH', str(timeline))


def _persist_core(snap: dict, event: dict | None = None) -> int:
    with memory.connect() as con:
        snap_id = memory.save_snapshot(con, snap)
        if event:
            memory.save_events(con, [event])
    return snap_id


def test_additive_schema_keeps_multiple_same_day_signal_instances(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    first_ts = '2026-08-24T10:00:00'
    first_event = _event(first_ts, 'LEADER_NEW')
    first_snap = _snap(first_ts)
    first_id = _persist_core(first_snap, first_event)
    assert obs.record_tick(
        snapshot_id=first_id, snapshot=first_snap, gate=_gate(), regime=_reg(),
        events=[first_event],
    )['instances_opened'] == 1

    second_ts = '2026-08-24T11:00:00'
    second_event = _event(second_ts, 'LEADER_UPGRADE')
    second_snap = _snap(second_ts, price=101.0)
    second_id = _persist_core(second_snap, second_event)
    obs.record_tick(
        snapshot_id=second_id, snapshot=second_snap, gate=_gate(), regime=_reg(),
        events=[second_event],
    )

    with obs.connect(write=False) as con:
        assert con.execute('PRAGMA foreign_keys').fetchone()[0] == 1
        assert obs._meta_get(con, 'schema_version') == str(obs.SCHEMA_VERSION)
        rows = con.execute(
            'SELECT day,code,trigger_type FROM signal_instances ORDER BY id'
        ).fetchall()
        assert [(r['day'], r['code'], r['trigger_type']) for r in rows] == [
            ('20260824', '005930', 'LEADER_NEW'),
            ('20260824', '005930', 'LEADER_UPGRADE'),
        ]
        assert con.execute('PRAGMA foreign_key_check').fetchall() == []


def test_context_is_immutable_and_keeps_structural_and_live_axes(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    snap = _snap('2026-08-24T10:00:00')
    snap_id = _persist_core(snap)
    result = obs.record_tick(
        snapshot_id=snap_id, snapshot=snap, gate=_gate('RED'), regime=_reg(), events=[],
    )
    with obs.connect(write=False) as con:
        row = con.execute(
            'SELECT structural_phase,structural_as_of_date,live_gate_status,payload_json '
            'FROM regime_contexts WHERE context_hash=?', (result['context_hash'],),
        ).fetchone()
        payload = json.loads(row['payload_json'])
        assert row['structural_phase'] == 'uptrend_broadening'
        assert row['structural_as_of_date'] == '2026-08-21'
        assert row['live_gate_status'] == 'RED'
        assert payload['resolution_rule'] == 'preserve_structural_and_live_axes'
        assert payload['conflicts'] == ['structural_positive_live_gate_red']
    with obs.connect(write=True) as con:
        try:
            con.execute('UPDATE regime_contexts SET structural_phase=?', ('downtrend',))
        except sqlite3.IntegrityError as exc:
            assert 'immutable' in str(exc)
        else:  # pragma: no cover - protects the immutable contract
            raise AssertionError('regime context update unexpectedly succeeded')


def test_stale_structural_phase_is_unknown_but_keeps_raw_metadata(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    context = obs.build_regime_context(
        observed_at='2026-09-01T10:00:00', snapshot=_snap('2026-09-01T10:00:00'),
        gate=_gate(), regime=_reg(),
    )
    structural = context['structural']
    assert structural['status'] == 'stale'
    assert structural['phase'] == 'unknown'
    assert structural['raw_phase'] == 'uptrend_broadening'
    assert structural['as_of_date'] == '2026-08-21'
    assert structural['stale_calendar_days'] == 11


def test_first_post_stabilization_scan_opens_daily_baseline_once(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    early = _snap('2026-08-24T09:00:30')
    early_id = _persist_core(early)
    suppressed = obs.record_tick(
        snapshot_id=early_id, snapshot=early, gate=_gate(), regime=_reg(), events=[],
        allow_baseline_open=False,
    )
    assert suppressed['instances_opened'] == 0

    eligible = _snap('2026-08-24T09:05:00')
    eligible_id = _persist_core(eligible)
    first = obs.record_tick(
        snapshot_id=eligible_id, snapshot=eligible, gate=_gate(), regime=_reg(), events=[],
        allow_baseline_open=True,
    )
    later = _snap('2026-08-24T10:00:00', price=103.0)
    later_id = _persist_core(later)
    repeated = obs.record_tick(
        snapshot_id=later_id, snapshot=later, gate=_gate(), regime=_reg(), events=[],
        allow_baseline_open=True,
    )
    assert first['instances_opened'] == 1
    assert repeated['instances_opened'] == 0
    with memory.connect() as con:
        assert memory.list_events(con, '20260824') == []
    with obs.connect(write=False) as con:
        instances = con.execute(
            'SELECT trigger_type,opened_at,code FROM signal_instances'
        ).fetchall()
        markers = con.execute(
            "SELECT COUNT(*) FROM observation_daily_markers WHERE marker_type='BASELINE_OPEN'"
        ).fetchone()[0]
    assert [(row['trigger_type'], row['opened_at'], row['code']) for row in instances] == [
        ('BASELINE_OPEN', '2026-08-24T09:05:00', '005930'),
    ]
    assert markers == 1


def test_empty_daily_baseline_is_marked_and_later_core_entry_still_opens(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    empty = _snap('2026-08-24T09:05:00')
    empty['rows'][0].update({'grade': 'B', 'score': 50})
    empty['by_grade'] = {'B': 1}
    empty_id = _persist_core(empty)
    baseline = obs.record_tick(
        snapshot_id=empty_id, snapshot=empty, gate=_gate(), regime=_reg(), events=[],
        allow_baseline_open=True,
    )
    assert baseline['instances_opened'] == 0

    entry_ts = '2026-08-24T09:06:00'
    entry = _event(entry_ts, 'LEADER_UPGRADE')
    current = _snap(entry_ts, price=101.0)
    current_id = _persist_core(current, entry)
    later = obs.record_tick(
        snapshot_id=current_id, snapshot=current, gate=_gate(), regime=_reg(), events=[entry],
        allow_baseline_open=True,
    )
    assert later['instances_opened'] == 1
    with obs.connect(write=False) as con:
        marker_n = con.execute('SELECT COUNT(*) FROM observation_daily_markers').fetchone()[0]
        instance = con.execute('SELECT trigger_type FROM signal_instances').fetchone()[0]
    assert marker_n == 1
    assert instance == 'LEADER_UPGRADE'


def test_leader_drop_is_shadow_state_only_without_duplicate_alert_event(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    opened_ts = '2026-08-24T10:00:00'
    opened = _event(opened_ts, 'LEADER_NEW')
    opened_snap = _snap(opened_ts)
    opened_id = _persist_core(opened_snap, opened)
    obs.record_tick(
        snapshot_id=opened_id, snapshot=opened_snap, gate=_gate(), regime=_reg(), events=[opened],
    )

    drop_ts = '2026-08-24T10:03:00'
    dropped = _event(drop_ts, 'LEADER_DROP')
    dropped_snap = _snap(drop_ts, price=96.0)
    dropped_id = _persist_core(dropped_snap, dropped)
    result = obs.record_tick(
        snapshot_id=dropped_id, snapshot=dropped_snap, gate=_gate(), regime=_reg(),
        events=[dropped],
    )
    assert result['instances_invalidated'] == 1

    with memory.connect() as con:
        core_types = [row['type'] for row in memory.list_events(con, '20260824')]
    with obs.connect(write=False) as con:
        instance = con.execute(
            'SELECT status,close_reason FROM signal_instances'
        ).fetchone()
        state_types = [r[0] for r in con.execute(
            'SELECT event_type FROM signal_state_events ORDER BY id'
        ).fetchall()]
    assert core_types == ['LEADER_NEW', 'LEADER_DROP']
    assert 'INVALIDATED' not in core_types
    assert (instance['status'], instance['close_reason']) == ('INVALIDATED', 'drop_confirmed')
    assert state_types == ['SIGNAL_OPEN', 'LEADER_DROP']


def test_fail_open_boundary_returns_diagnostic(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(
        obs, 'record_tick',
        lambda **kwargs: (_ for _ in ()).throw(sqlite3.OperationalError('database is locked')),
    )
    result = obs.record_tick_fail_open(
        snapshot_id=None, snapshot=_snap('2026-08-24T10:00:00'),
        gate=_gate(), regime=_reg(), events=[],
    )
    assert result['ok'] is False and result['mode'] == 'shadow'
    assert result['error'].startswith('OperationalError:')


def test_outcome_updater_uses_future_sessions_and_is_idempotent(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    opened_ts = '2026-08-24T10:00:00'
    event = _event(opened_ts, 'LEADER_NEW')
    snap = _snap(opened_ts, price=100.0)
    snap_id = _persist_core(snap, event)
    obs.record_tick(
        snapshot_id=snap_id, snapshot=snap, gate=_gate(), regime=_reg(), events=[event],
    )

    prices = tmp_path / 'daily_prices.csv'
    with prices.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['ticker', 'date', 'current_price'])
        writer.writeheader()
        for day, price in (
            ('2026-08-24', 100), ('2026-08-25', 102), ('2026-08-26', 101),
            ('2026-08-27', 103), ('2026-08-28', 104), ('2026-08-31', 110),
        ):
            writer.writerow({'ticker': '005930', 'date': day, 'current_price': price})

    first = obs.update_mature_outcomes(
        now=datetime(2026, 8, 31, 17, 15), price_path=str(prices),
    )
    second = obs.update_mature_outcomes(
        now=datetime(2026, 8, 31, 17, 16), price_path=str(prices),
    )
    assert first['completed'] == 2 and first['missing'] == first['still_pending'] == 0
    assert second['pending_before'] == second['completed'] == 0
    with obs.connect(write=False) as con:
        outcomes = con.execute(
            'SELECT horizon_sessions,target_session_date,return_pct,status FROM signal_outcomes '
            'ORDER BY horizon_sessions'
        ).fetchall()
    assert [(r['horizon_sessions'], r['target_session_date'], r['return_pct'], r['status']) for r in outcomes] == [
        (1, '2026-08-25', 2.0, 'complete'),
        (5, '2026-08-31', 10.0, 'complete'),
    ]

    scorecards = obs.build_scorecards(now=datetime(2026, 8, 31, 17, 20))
    quality = obs.build_quality(now=datetime(2026, 8, 31, 17, 20))
    assert scorecards['outcome_method_version'] == obs.OUTCOME_METHOD_VERSION
    assert scorecards['coverage']['complete_n'] == 2
    assert 0.0 <= scorecards['coverage']['ratio'] <= 1.0
    assert 'opened_at' in scorecards['recent_instances'][0]
    assert 0.0 <= scorecards['horizons'][0]['coverage'] <= 1.0
    assert scorecards['recent_instances'][0]['outcomes'][0]['horizon_sessions'] == 1
    assert quality['status'] == 'ok'
    assert quality['database']['foreign_keys'] is True
    assert quality['outcomes']['complete'] == 2


def test_read_only_quality_does_not_create_missing_database(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    db_path = tmp_path / 'claw.db'
    assert not db_path.exists()
    quality = obs.build_quality(now=datetime(2026, 8, 24, 10, 0))
    scorecards = obs.build_scorecards(now=datetime(2026, 8, 24, 10, 0))
    assert quality['status'] == 'unavailable'
    assert scorecards['insufficient_reason'] == 'ledger_unavailable'
    assert not db_path.exists()

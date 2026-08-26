"""marketflow_claw.overview.build_overview — 격리 DB/파일로 집계 계약 검증."""
import json
from datetime import datetime

import marketflow_claw.collectors as col
import marketflow_claw.memory as mem
import marketflow_claw.overview as ov


def _row(code, name, grade, score=60, chg=3.0):
    return {'code': code, 'name': name, 'grade': grade, 'score': score, 'chg': chg, 'trval_eok': 100.0,
            'volx': 100.0, 'price': None, 'high_52w': None, 'rank': 1}


def _setup(monkeypatch, tmp_path, *, hb_age_s=5, market_open=True, halt=False):
    monkeypatch.setattr(mem, 'DB_PATH', str(tmp_path / 'claw.db'))
    monkeypatch.setattr(ov, 'DB_PATH', str(tmp_path / 'claw.db'))
    hb = tmp_path / 'heartbeat.json'
    now = datetime(2026, 8, 24, 10, 0, 0)
    hb.write_text(json.dumps({'ts': (now.replace(second=0)).isoformat(timespec='seconds'), 'pid': 1, 'halt': halt}), encoding='utf-8')
    monkeypatch.setattr(ov, 'HEARTBEAT_PATH', str(hb))
    monkeypatch.setattr(ov, '_market_open', lambda: market_open)
    snap = {'ts': '2026-08-24T09:59:55', 'market_status': 'open', 'source': 'file', 'error': None,
            'by_grade': {'S': 1, 'A': 1, 'B': 1}, 'file_age_s': 4.0,
            'rows': [_row('001', '에이사', 'S', 80, 5.0), _row('002', '비사', 'A', 70, 2.0), _row('003', '씨사', 'B', 50, -1.0)]}
    monkeypatch.setattr(col, 'fetch_leaders', lambda mode='file': dict(snap))
    monkeypatch.setattr(col, 'load_regime_inputs', lambda: {'available': True, 'status': 'YELLOW', 'score': 50, 'age_hours': 3})
    monkeypatch.delenv('CLAW_TELEGRAM_CHAT_ID', raising=False)
    return now + __import__('datetime').timedelta(seconds=hb_age_s)


def test_overview_contract_running(monkeypatch, tmp_path):
    now = _setup(monkeypatch, tmp_path)
    with mem.connect() as con:
        mem.save_snapshot(con, {'ts': '2026-08-24T09:59:55', 'source': 'kis', 'market_status': 'open', 'by_grade': {}, 'rows': []})
        mem.save_events(con, [{'ts': '2026-08-24T09:41:05', 'type': 'LEADER_NEW', 'code': '001', 'name': '에이사',
                               'grade_from': '', 'grade_to': 'S', 'score': 80, 'chg': 5.0}])
    o = ov.build_overview(now=now)
    assert o['loop']['state'] == 'running' and o['loop']['heartbeat_age_s'] == 5
    assert o['regime']['regime'] == 'NEUTRAL' and o['regime']['halt'] is False
    rows = o['leaders']['rows']
    assert [r['grade'] for r in rows] == ['S', 'A', 'B']
    assert rows[0]['since_ts'] == '2026-08-24T09:41:05' and rows[0]['today_event']['type'] == 'LEADER_NEW'
    assert rows[1]['since_ts'] is None
    assert o['events']['counts'] == {'LEADER_NEW': 1}
    assert o['system']['kis_calls_today'] == 1 and o['system']['drop_confirm_ticks'] >= 1
    assert o['errors'] == {}
    # 비밀값/토큰/채팅ID 는 어떤 필드에도 없다
    dumped = json.dumps(o, ensure_ascii=False)
    assert 'TOKEN=' not in dumped and 'chat_id' not in dumped.lower()


def test_overview_dead_and_idle_states(monkeypatch, tmp_path):
    now = _setup(monkeypatch, tmp_path, hb_age_s=600)
    assert ov.build_overview(now=now)['loop']['state'] == 'dead'
    now = _setup(monkeypatch, tmp_path, hb_age_s=20, market_open=False)
    assert ov.build_overview(now=now)['loop']['state'] == 'idle'
    now = _setup(monkeypatch, tmp_path, hb_age_s=20, market_open=True, halt=True)
    assert ov.build_overview(now=now)['loop']['state'] == 'halt'


def test_overview_survives_missing_db_dir(monkeypatch, tmp_path):
    now = _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(mem, 'DB_PATH', str(tmp_path / 'nope' / 'sub' / 'claw.db'))
    monkeypatch.setattr(mem, 'ensure_dirs', lambda: (_ for _ in ()).throw(OSError('ro')))
    o = ov.build_overview(now=now)
    assert 'db' in o['errors'] and o['leaders']['rows'] and o['events']['items'] == []


def test_overview_hides_detection_unknown_guard_rows(monkeypatch, tmp_path):
    now = _setup(monkeypatch, tmp_path)
    visible = _row('001', '에이사', 'A')
    guard = dict(_row('002', '', 'C'), score_complete=False, detection_unknown=True,
                 incomplete_reasons=['price_detail_52w_high'])
    monkeypatch.setattr(
        col, 'fetch_leaders',
        lambda mode='file': {
            'ts': '2026-08-24T09:59:55', 'market_status': 'open', 'source': 'file',
            'error': None, 'by_grade': {'A': 1}, 'rows': [visible, guard],
        },
    )

    o = ov.build_overview(now=now)

    assert [row['code'] for row in o['leaders']['rows']] == ['001']

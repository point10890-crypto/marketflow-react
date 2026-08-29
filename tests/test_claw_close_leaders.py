# -*- coding: utf-8 -*-
"""마감 기준 주도주 — GET /api/kr/claw/close-leaders 본체 (마스터 플랜 P3 첫 슬라이스).

마감 기준 = 해당 세션 날짜의 마지막 정상(오류 없는) 스냅샷. 이벤트는 종목별
타임라인으로 부착하고, 그날 close 브리핑 발송 여부를 함께 반환한다.
"""
import json

import pytest

from marketflow_claw import memory


@pytest.fixture()
def claw_db(tmp_path, monkeypatch):
    db = str(tmp_path / 'claw_test.db')
    monkeypatch.setattr(memory, 'DB_PATH', db)
    return db


def _snap(ts, rows, error=None):
    return {'ts': ts, 'source': 'file', 'market_status': 'OPEN',
            'by_grade': {}, 'rows': rows, 'error': error}


ROW_A = {'code': '047040', 'name': '대우건설', 'grade': 'A', 'score': 66, 'chg': 8.4,
         'trval_eok': 3844, 'price': 5000}
ROW_B = {'code': '317400', 'name': '자이에스앤디', 'grade': 'S', 'score': 71, 'chg': 7.9,
         'trval_eok': 134, 'price': 9000}
ROW_C = {'code': '000001', 'name': '비주도', 'grade': 'B', 'score': 40, 'chg': 1.0,
         'trval_eok': 20, 'price': 100}


def _seed_two_days(con):
    # day1: 스냅샷 1개
    memory.save_snapshot(con, _snap('2026-08-25T15:20:00', [ROW_A]))
    # day2: 정상 2개 + 마지막에 오류 스냅샷 1개 (마감 기준은 마지막 '정상' 스냅샷이어야 함)
    memory.save_snapshot(con, _snap('2026-08-26T10:00:00', [ROW_A]))
    memory.save_snapshot(con, _snap('2026-08-26T15:29:00', [ROW_A, ROW_B, ROW_C]))
    memory.save_snapshot(con, _snap('2026-08-26T15:30:00', [], error='timeout'))
    memory.save_events(con, [
        {'ts': '2026-08-26T09:16:00', 'type': 'LEADER_UPGRADE', 'code': '047040',
         'name': '대우건설', 'grade_from': 'B', 'grade_to': 'A', 'score': 66, 'chg': 8.4},
        {'ts': '2026-08-26T10:57:00', 'type': 'LEADER_UPGRADE', 'code': '317400',
         'name': '자이에스앤디', 'grade_from': 'A', 'grade_to': 'S', 'score': 71, 'chg': 7.9},
    ])
    memory.save_brief(con, 'close', 'digest-close-1', '/tmp/x.md', True, None)
    # save_brief 는 ts 에 현재 시각을 쓴다. 이 테스트는 "그 세션의 마감 브리핑을
    # 찾는가"를 검증하므로 벽시계 날짜에 의존하지 않도록 세션 날짜로 고정한다.
    con.execute("UPDATE briefs SET ts='2026-08-26T15:45:00' WHERE digest='digest-close-1'")


def test_close_leaders_latest_session(claw_db):
    from marketflow_claw.overview import build_close_leaders
    with memory.connect() as con:
        _seed_two_days(con)
    out = build_close_leaders()
    assert out['day'] == '20260826'
    assert out['snapshot_ts'] == '2026-08-26T15:29:00'  # 오류 스냅샷(15:30) 무시
    # 정렬: S > A > B
    assert [r['code'] for r in out['rows']] == ['317400', '047040', '000001']
    # 종목별 이벤트 타임라인 부착
    ev = out['rows'][1]['events']
    assert ev and ev[0]['type'] == 'LEADER_UPGRADE' and ev[0]['ts'].startswith('2026-08-26T09:16')
    # close 브리핑 발송 여부
    assert out['close_brief'] and out['close_brief']['delivered'] is True
    assert out['events_count'] == 2
    assert out['error'] is None


def test_close_leaders_specific_day(claw_db):
    from marketflow_claw.overview import build_close_leaders
    with memory.connect() as con:
        _seed_two_days(con)
    out = build_close_leaders(day='20260825')
    assert out['day'] == '20260825'
    assert out['snapshot_ts'] == '2026-08-25T15:20:00'
    assert [r['code'] for r in out['rows']] == ['047040']
    assert out['rows'][0]['events'] == []
    assert out['close_brief'] is None


def test_close_leaders_empty_db(claw_db):
    from marketflow_claw.overview import build_close_leaders
    with memory.connect() as con:  # 스키마만 생성
        pass
    out = build_close_leaders()
    assert out['error'] == 'no_snapshot'
    assert out['rows'] == []

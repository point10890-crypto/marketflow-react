"""marketflow_claw.events.diff — 상태 전이 검출 단위 테스트."""
from marketflow_claw import events as ev


def _row(code, name, grade, score=60, chg=3.0, volx=1.0, price=None, high=None):
    return {'code': code, 'name': name, 'grade': grade, 'score': score, 'chg': chg,
            'trval_eok': 100.0, 'volx': volx, 'price': price, 'high_52w': high, 'rank': 1}


def _snap(ts, rows):
    return {'ts': ts, 'market_status': 'open', 'source': 'test', 'error': None, 'by_grade': {}, 'rows': rows}


def test_baseline_has_no_events():
    cur = _snap('2026-08-21T09:05:00', [_row('001', 'A사', 'S')])
    assert ev.diff(None, cur) == []


def test_new_upgrade_drop():
    prev = _snap('2026-08-21T09:40:55', [_row('001', 'A사', 'B'), _row('002', 'B사', 'A')])
    cur = _snap('2026-08-21T09:41:00', [_row('001', 'A사', 'A'), _row('003', 'C사', 'S')])
    types = {(e['type'], e['code']) for e in ev.diff(prev, cur)}
    assert ('LEADER_UPGRADE', '001') in types   # B→A
    assert ('LEADER_NEW', '003') in types       # 목록 밖→S
    assert ('LEADER_DROP', '002') in types      # A→목록 밖


def test_already_emitted_is_suppressed():
    prev = _snap('t0', [])
    cur = _snap('t1', [_row('003', 'C사', 'S')])
    assert ev.diff(prev, cur, already={('LEADER_NEW', '003')}) == []


def test_error_snapshot_emits_nothing():
    prev = _snap('t0', [_row('001', 'A사', 'S')])
    cur = dict(_snap('t1', []), error='kis_upstream_empty')
    assert ev.diff(prev, cur) == []


def test_volume_surge_and_new_high():
    prev = _snap('t0', [_row('001', 'A사', 'A', volx=120, price=900, high=1000)])
    cur = _snap('t1', [_row('001', 'A사', 'A', volx=350, price=1010, high=1000)])
    types = {e['type'] for e in ev.diff(prev, cur)}
    assert types == {'VOLUME_SURGE', 'NEW_HIGH_BREAK'}


def test_regime_halt_rules():
    from marketflow_claw import regime as rg
    gate_ok = {'available': True, 'status': 'YELLOW', 'age_hours': 5, 'score': 50}
    snap_ok = {'rows': [_row('001', 'A사', 'S', chg=1.0)], 'error': None, 'file_age_s': 3}
    r = rg.evaluate(snap_ok, gate_ok, market_open=True)
    assert r['regime'] == 'NEUTRAL' and r['halt'] is False and r['breadth_pct'] == 100
    r2 = rg.evaluate(dict(snap_ok, error='token'), gate_ok, market_open=True)
    assert r2['halt'] is True
    stale = dict(snap_ok, file_age_s=999)
    assert rg.evaluate(stale, gate_ok, market_open=True)['halt'] is False          # 레짐 입력 있으면 보류 아님
    assert rg.evaluate(stale, {'available': False}, market_open=True)['halt'] is True  # 둘 다 죽으면 HALT


def test_reporter_halt_has_no_symbols():
    from marketflow_claw import reporter
    reg = {'halt': True, 'reasons': ['leaders source error: token'], 'regime': 'NEUTRAL'}
    evs = [dict(_row('001', '금호건설', 'S'), type='LEADER_NEW', ts='t', grade_from='', grade_to='S')]
    msg = reporter.event_message(evs, reg)
    assert '검출 보류' in msg and '금호건설' not in msg and '001' not in msg


def test_confirmed_drops_requires_n_consecutive_ticks():
    lead = _snap('t0', [_row('001', 'A사', 'S')])
    gone = lambda t: _snap(t, [])
    # 창 길이 부족 → 판단 안 함
    assert ev.confirmed_drops([lead, gone('t1')], 3) == []
    # 2틱만 빠짐 → 아직 아님
    assert ev.confirmed_drops([lead, gone('t1'), gone('t2')], 3) == []
    # 3틱 연속 빠짐 → 확정
    out = ev.confirmed_drops([lead, gone('t1'), gone('t2'), gone('t3')], 3)
    assert [(e['type'], e['code'], e['confirmed_ticks']) for e in out] == [('LEADER_DROP', '001', 3)]
    # 중간에 복귀하면 확정 안 됨 (KIS 타임아웃으로 한 틱 빠진 경우)
    back = _snap('t2', [_row('001', 'A사', 'A')])
    assert ev.confirmed_drops([lead, gone('t1'), back, gone('t3')], 3) == []
    # 창 안에 오류 스냅샷이 있으면 확정 안 됨
    err = dict(gone('t2'), error='kis_upstream_empty')
    assert ev.confirmed_drops([lead, gone('t1'), err, gone('t3')], 3) == []


def test_diff_can_exclude_drops():
    prev = _snap('t0', [_row('001', 'A사', 'S')])
    cur = _snap('t1', [])
    assert ev.diff(prev, cur, include_drops=False) == []
    assert [e['type'] for e in ev.diff(prev, cur)] == ['LEADER_DROP']

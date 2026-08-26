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


def test_error_previous_snapshot_is_not_a_transition_baseline():
    prev = dict(_snap('t0', [_row('001', 'A사', 'B')]), error='stale_fallback')
    cur = _snap('t1', [_row('001', 'A사', 'A')])
    assert ev.diff(prev, cur) == []


def test_late_session_can_suppress_new_without_hiding_other_transitions():
    prev = _snap('2026-08-24T15:19:55', [_row('001', 'A사', 'B')])
    cur = _snap('2026-08-24T15:20:00', [
        _row('001', 'A사', 'A'),
        _row('002', 'B사', 'S'),
    ])

    types = {(event['type'], event['code']) for event in ev.diff(prev, cur, include_new=False)}

    assert ('LEADER_UPGRADE', '001') in types
    assert ('LEADER_NEW', '002') not in types


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


def test_incomplete_scores_cannot_drive_grade_transitions():
    complete_leader = _row('001', 'A사', 'A')
    incomplete_leader = dict(complete_leader, score_complete=False, incomplete_reasons=['investor'])
    complete_b = _row('001', 'A사', 'B')
    incomplete_b = dict(complete_b, score_complete=False, incomplete_reasons=['sector'])

    # An incomplete current score cannot create NEW/UP or confirm a DROP.
    assert ev.diff(_snap('t0', [complete_b]), _snap('t1', [incomplete_leader])) == []
    assert ev.diff(_snap('t0', [complete_leader]), _snap('t1', [incomplete_b])) == []
    # An incomplete prior grade is not a reliable transition baseline either.
    assert ev.diff(_snap('t0', [incomplete_b]), _snap('t1', [complete_leader])) == []
    assert ev.diff(_snap('t0', [incomplete_leader]), _snap('t1', [])) == []


def test_incomplete_row_breaks_confirmed_drop_window():
    complete_leader = _row('001', 'A사', 'A')
    incomplete_b = dict(_row('001', 'A사', 'B'), score_complete=False,
                        incomplete_reasons=['price_detail_52w_high'])
    window = [
        _snap('t0', [complete_leader]),
        _snap('t1', []),
        _snap('t2', [incomplete_b]),
        _snap('t3', []),
    ]
    assert ev.confirmed_drops(window, 3) == []


def test_collector_preserves_quality_and_halts_critical_partial():
    from marketflow_claw.collectors import normalize_snapshot

    raw = {
        'timestamp': '2026-08-24T10:00:00',
        'market_status': 'open',
        'data_quality': {
            'status': 'partial', 'partial': True, 'critical_complete': False,
            'score_reliable': False, 'missing_sources': ['fluctuation'],
        },
        'results': [{
            'code': '001', 'name': 'A사', 'grade': 'A', 'score': {'total': 70},
            'score_complete': False, 'incomplete_reasons': ['investor'],
            'data_quality': {'status': 'partial', 'score_complete': False},
        }],
    }
    snap = normalize_snapshot(raw, source='kis')

    assert snap['error'] == 'kis_critical_sources_incomplete'
    assert snap['data_quality']['missing_sources'] == ['fluctuation']
    assert snap['rows'][0]['score_complete'] is False
    assert snap['rows'][0]['incomplete_reasons'] == ['investor']
    assert snap['rows'][0]['data_quality']['status'] == 'partial'


def test_collector_uses_base_score_grade_not_async_enrichment_grade():
    from marketflow_claw.collectors import normalize_snapshot

    raw = {
        'timestamp': '2026-08-24T10:00:00',
        'market_status': 'open',
        'data_quality': {'critical_complete': True, 'safe_to_replace_latest': True},
        'results': [{
            'code': '001', 'name': 'A사', 'grade': 'S',
            'score': {'total': 72, 'total_enriched': 80},
            'score_complete': True,
        }],
    }

    snap = normalize_snapshot(raw, source='file')

    assert snap['rows'][0]['grade'] == 'A'
    assert snap['rows'][0]['score'] == 72
    assert snap['by_grade'] == {'A': 1}


def test_incomplete_input_recovery_does_not_create_volume_or_high_event():
    prev = _row('001', '삼성E&A', 'B', volx=0, price=900, high=None)
    prev.update({
        'score_complete': False,
        'incomplete_reasons': ['prdy_vol', 'price_detail_52w_high'],
        'data_quality': {'inputs': {'prdy_vol': 'missing', 'price_detail': 'missing'}},
    })
    cur = _row('001', '삼성E&A', 'B', volx=350, price=1010, high=1000)
    cur.update({
        'score_complete': True,
        'incomplete_reasons': [],
        'data_quality': {'inputs': {'prdy_vol': 'available', 'price_detail': 'available'}},
    })

    assert ev.diff(_snap('t0', [prev]), _snap('t1', [cur])) == []
    assert ev.diff(_snap('t0', []), _snap('t1', [cur])) == []
    unknown_inputs = dict(prev, incomplete_reasons=[])
    unknown_inputs.pop('data_quality')
    assert ev.diff(_snap('t0', [unknown_inputs]), _snap('t1', [cur])) == []


def test_reporter_escapes_dynamic_telegram_html():
    from marketflow_claw import reporter

    row = _row('001&002', '삼성E&A <우>', 'A', price=1000, high=1200)
    event = dict(row, type='LEADER_NEW', ts='2026-08-24T10:00:00', grade_from='', grade_to='A')
    snap = _snap('2026-08-24T10:00:00', [row])
    snap['source'] = 'file&kis'
    reg = {'regime': 'NEUTRAL&SAFE', 'halt': False, 'reasons': [], 'breadth_pct': 50}

    messages = [
        reporter.event_message([event], reg),
        reporter.morning_message(snap, reg, []),
        reporter.close_message(snap, reg, [event], {'snapshots': 1}),
    ]
    for message in messages:
        assert '삼성E&amp;A &lt;우&gt;' in message
        assert '001&amp;002' in message
        assert 'NEUTRAL&amp;SAFE' in message
        assert '삼성E&A <우>' not in message
        assert '<b>' in message  # template markup remains active

    assert '08-24 10:00' in messages[0]

    halt = reporter.halt_message(
        {'halt': True, 'reasons': ['token <expired> & unavailable'], 'regime': 'NEUTRAL'},
        '2026-08-24T13:00:00',
    )
    assert 'token &lt;expired&gt; &amp; unavailable' in halt


def test_uncertain_missing_codes_survive_memory_and_break_drop_confirmation(monkeypatch, tmp_path):
    from marketflow_claw.collectors import normalize_snapshot
    from marketflow_claw import memory as mem

    raw = {
        'timestamp': '2026-08-24T10:00:05',
        'market_status': 'open',
        'results': [],
        'data_quality': {
            'critical_complete': True,
            'incomplete_score_codes': ['001'],
            # 002 models a fluctuation-only candidate that failed before it
            # could enter candidate_pool.
            'detail': {'missing_codes': ['002']},
            'investor': {'missing_codes': []},
            'volume_baseline': {'missing_codes': []},
        },
        'candidate_pool': [{
            'code': '001', 'name': 'A사', 'grade': 'C', 'eligible': False,
            'score': {'total': 35}, 'score_complete': False,
            'incomplete_reasons': ['prdy_vol'],
            'data_quality': {
                'score_complete': False,
                'inputs': {'prdy_vol': 'missing', 'price_detail': 'available'},
            },
        }],
    }
    unknown = normalize_snapshot(raw, source='kis')
    lead = _snap('2026-08-24T10:00:00', [
        _row('001', 'A사', 'A'), _row('002', 'B사', 'A'),
    ])
    absent2 = _snap('2026-08-24T10:00:10', [])
    absent3 = _snap('2026-08-24T10:00:15', [])

    assert unknown['by_grade'] == {}
    assert unknown['uncertain_codes'] == ['001', '002']
    assert {row['code'] for row in unknown['rows']} == {'001', '002'}
    assert all(row['detection_unknown'] for row in unknown['rows'])
    assert ev.diff(lead, unknown) == []
    from marketflow_claw import regime as rg
    unknown_regime = rg.evaluate(
        unknown, {'available': True, 'status': 'GREEN', 'age_hours': 1}, market_open=True,
    )
    assert unknown_regime['leader_count'] == 0 and unknown_regime['breadth_pct'] is None

    monkeypatch.setattr(mem, 'DB_PATH', str(tmp_path / 'claw.db'))
    with mem.connect() as con:
        for snap in (lead, unknown, absent2, absent3):
            mem.save_snapshot(con, snap)
        restored = mem.last_n_snapshots(con, 4, day='20260824')
    assert {row['code'] for row in restored[1]['rows']} == {'001', '002'}
    assert all(row['detection_unknown'] for row in restored[1]['rows'])
    assert ev.confirmed_drops(restored, 3) == []

    # A genuinely complete disappearance still confirms after three ticks.
    absent1 = _snap('2026-08-24T10:00:05', [])
    confirmed = ev.confirmed_drops([lead, absent1, absent2, absent3], 3)
    assert [(event['type'], event['code']) for event in confirmed] == [
        ('LEADER_DROP', '001'), ('LEADER_DROP', '002'),
    ]

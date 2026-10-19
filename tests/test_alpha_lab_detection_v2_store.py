from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services.mirofish.alpha_lab import store


def module():
    from app.services.mirofish.alpha_lab import detection_v2_store
    return detection_v2_store


def fixture(day='2026-10-20'):
    clock = day + 'T11:31:00Z'
    board = dict(decision_id='d'*64, input_fingerprint='a'*64, source_audit_hash='b'*64)
    report = dict(decision_at=clock, latest_session=day, input_fingerprint='a'*64,
                  as_of=day+'T00:00:00Z', provenance=dict(price_basis='provider_reported_unverified'),
                  opportunity_board=board, buy_candidates=[])
    inputs = dict(latest_session=day, input_fingerprint='a'*64,
        prices_by_symbol={'005930': [dict(symbol='005930',date=day,open=100.,high=101.,low=99.,close=100.,volume=1.)]},
        names={'005930':'Samsung'},
        capture_audit={'005930':dict(first=day+'T11:30:01Z',last=day+'T11:30:02Z')})
    return inputs, report, deepcopy(report)


def test_declaration_is_immutable_and_uses_next_kst_day(tmp_path, monkeypatch):
    m = module()
    monkeypatch.setattr(m, '_code_hash', lambda: 'c'*64)
    first = m.ensure_protocol(tmp_path, now='2026-10-19T12:00:00Z')
    before = (tmp_path/'detection-v2/protocol.json').read_bytes()
    second = m.ensure_protocol(tmp_path, now='2026-10-20T12:00:00Z')
    assert first == second and first['earliest_session'] == '2026-10-20'
    assert first['decision_sessions'] == 60 and first['maturation_sessions'] == 10
    assert before == (tmp_path/'detection-v2/protocol.json').read_bytes()
    assert m.active_for(first, '2026-10-19') and not m.active_for(first, '2026-10-18')


def test_same_day_and_stale_inputs_do_not_backfill_cohorts(tmp_path, monkeypatch):
    m = module(); monkeypatch.setattr(m, '_code_hash', lambda: 'c'*64)
    data, report, control = fixture('2026-10-19')
    result = m.refresh(tmp_path, data, report, control, now=report['decision_at'])
    assert result['status'] == 'waiting' and result['enrolled_sessions'] == 0
    assert not (tmp_path/'detection-v2/challenger/forward.json').exists()
    data, report, control = fixture('2026-10-19')
    result = m.refresh(tmp_path, data, report, control, now='2026-10-20T11:31:00Z')
    assert result['enrolled_sessions'] == 0


def test_future_cohort_includes_empty_slots_once_without_touching_old_files(tmp_path, monkeypatch):
    m = module(); monkeypatch.setattr(m, '_code_hash', lambda: 'c'*64)
    m.ensure_protocol(tmp_path, now='2026-10-19T12:00:00Z')
    old = tmp_path/'forward.json'; old.write_text('old-first-decision', encoding='utf-8')
    data, report, control = fixture()
    result = m.refresh(tmp_path, data, report, control, now=report['decision_at'])
    assert result['status'] == 'collecting' and result['enrolled_sessions'] == 1
    raw = (tmp_path/'detection-v2/cohorts.json').read_bytes()
    changed = deepcopy(report); changed['opportunity_board']['decision_id'] = 'e'*64
    again = m.refresh(tmp_path, data, changed, control, now=report['decision_at'])
    assert again['enrolled_sessions'] == 1
    assert raw == (tmp_path/'detection-v2/cohorts.json').read_bytes()
    assert old.read_text(encoding='utf-8') == 'old-first-decision'
    assert result['approved_exposure'] == 0 and result['live_orders'] is False


def test_policy_drift_and_corruption_fail_without_replacing_declaration(tmp_path, monkeypatch):
    m = module(); monkeypatch.setattr(m, '_code_hash', lambda: 'c'*64)
    m.ensure_protocol(tmp_path, now='2026-10-19T12:00:00Z')
    path = tmp_path/'detection-v2/protocol.json'; before = path.read_bytes()
    monkeypatch.setattr(m, '_code_hash', lambda: 'e'*64)
    with pytest.raises(ValueError, match='detection_v2_policy_changed'):
        m.ensure_protocol(tmp_path, now='2026-10-20T12:00:00Z')
    assert path.read_bytes() == before
    path.write_text('{}', encoding='utf-8'); before = path.read_bytes()
    with pytest.raises(ValueError):
        m.ensure_protocol(tmp_path, now='2026-10-20T12:00:00Z')
    assert path.read_bytes() == before


def test_fixed_window_does_not_extend_when_empty_or_losing(tmp_path, monkeypatch):
    m = module(); monkeypatch.setattr(m, '_code_hash', lambda: 'c'*64)
    m.ensure_protocol(tmp_path, now='2026-10-19T12:00:00Z')
    start = datetime(2026, 10, 20, tzinfo=timezone.utc)
    # Cohorts count actual supplied session dates, not assumed weekday calendars.
    for n in range(62):
        data, report, control = fixture((start+timedelta(days=n)).date().isoformat())
        result = m.refresh(tmp_path, data, report, control, now=report['decision_at'])
    assert result['enrolled_sessions'] == 60 and result['status'] == 'window_complete'
    assert result['approved_exposure'] == 0


def test_unsettled_symbol_capture_and_identity_mismatch_reject_enrollment(tmp_path, monkeypatch):
    m = module(); monkeypatch.setattr(m, '_code_hash', lambda: 'c'*64)
    m.ensure_protocol(tmp_path, now='2026-10-19T12:00:00Z')
    data, report, control = fixture()
    data['prices_by_symbol'] = {'005930': []}
    data['capture_audit'] = {'005930': {'first':'2026-10-20T11:29:59Z','last':'2026-10-20T11:30:10Z'}}
    with pytest.raises(ValueError, match='detection_v2_capture'):
        m.refresh(tmp_path, data, report, control, now=report['decision_at'])
    data['capture_audit']['005930']['first'] = '2026-10-20T11:30:01Z'
    control['input_fingerprint'] = 'f'*64
    with pytest.raises(ValueError, match='detection_v2_binding'):
        m.refresh(tmp_path, data, report, control, now=report['decision_at'])


def selected_fixture(day='2026-10-20', *, first='2026-10-20'):
    data, report, control = fixture(day)
    first_day = datetime.fromisoformat(first)
    end = datetime.fromisoformat(day)
    rows = [dict(symbol='005930', date=(first_day+timedelta(days=i)).date().isoformat(),
                 open=100., high=101., low=99., close=100., volume=1000.)
            for i in range(-14, (end-first_day).days+1)]
    data['prices_by_symbol']['005930'] = rows
    for source in (report, control):
        source['buy_candidates'] = [dict(symbol='005930', name='Samsung',
            plan=dict(entry_price=100., stop_price=96., target_price=108.))]
    return data, report, control


def fail_control_write_once(monkeypatch):
    original = store._write
    failed = []
    def write(path, value):
        if Path(path).name == 'forward.json' and Path(path).parent.name == 'control' and not failed:
            failed.append(True)
            raise OSError('fixture_control_write_interrupted')
        return original(path, value)
    monkeypatch.setattr(store, '_write', write)


def test_next_day_retry_recovers_original_arm_clock_plan_and_snapshot(tmp_path, monkeypatch):
    m = module(); monkeypatch.setattr(m, '_code_hash', lambda: 'c'*64)
    m.ensure_protocol(tmp_path, now='2026-10-19T12:00:00Z')
    data, report, control = selected_fixture()
    fail_control_write_once(monkeypatch)
    with pytest.raises(OSError, match='interrupted'):
        m.refresh(tmp_path, data, report, control, now=report['decision_at'])
    original = store.read_journal(tmp_path/'detection-v2/challenger')['decisions'][0]
    newer, new_report, new_control = selected_fixture('2026-10-21')
    new_control['buy_candidates'][0]['plan']['entry_price'] = 999.
    result = m.refresh(tmp_path, newer, new_report, new_control, now=new_report['decision_at'])
    recovered = store.read_journal(tmp_path/'detection-v2/control')['decisions'][0]
    assert recovered['decision_date'] == '2026-10-20'
    assert recovered['created_at'] == '2026-10-20T11:31:00Z'
    assert recovered['price_as_of'] == report['as_of']
    assert recovered['candidates'] == control['buy_candidates']
    assert recovered['snapshots'] == original['snapshots']
    assert recovered['outcomes'][0]['entry_date'] == '2026-10-21'
    assert recovered['outcomes'][0]['status'] == 'open'
    assert result['enrolled_sessions'] == 2


def test_sixtieth_cohort_same_day_retry_fills_missing_arm_without_extending_window(tmp_path, monkeypatch):
    m = module(); monkeypatch.setattr(m, '_code_hash', lambda: 'c'*64)
    m.ensure_protocol(tmp_path, now='2026-10-19T12:00:00Z')
    start = datetime(2026, 10, 20)
    for index in range(59):
        data, report, control = fixture((start+timedelta(days=index)).date().isoformat())
        m.refresh(tmp_path, data, report, control, now=report['decision_at'])
    last_day = (start+timedelta(days=59)).date().isoformat()
    data, report, control = selected_fixture(last_day, first=last_day)
    fail_control_write_once(monkeypatch)
    with pytest.raises(OSError):
        m.refresh(tmp_path, data, report, control, now=report['decision_at'])
    challenger_path = tmp_path/'detection-v2/challenger/forward.json'
    before = challenger_path.read_bytes()
    result = m.refresh(tmp_path, data, report, control, now=report['decision_at'])
    assert result['enrolled_sessions'] == 60 and result['status'] == 'window_complete'
    assert len(store.read_journal(tmp_path/'detection-v2/control')['decisions']) == 1
    assert challenger_path.read_bytes() == before


def test_freeze_recovery_never_reobserves_existing_open_arm_with_a_seed_snapshot(tmp_path, monkeypatch):
    m = module(); monkeypatch.setattr(m, '_code_hash', lambda: 'c'*64)
    m.ensure_protocol(tmp_path, now='2026-10-19T12:00:00Z')
    data, report, control = selected_fixture()
    m.refresh(tmp_path, data, report, control, now=report['decision_at'])
    newer, report2, control2 = selected_fixture('2026-10-21')
    m.refresh(tmp_path, newer, report2, control2, now=report2['decision_at'])
    cohort = m._read(tmp_path/'detection-v2/cohorts.json')['sessions'][0]
    arm_root = tmp_path/'detection-v2/challenger'
    path = arm_root/'forward.json'; before = path.read_bytes()
    assert store.read_journal(arm_root)['decisions'][0]['outcomes'][0]['status'] == 'open'
    m._freeze_arm(arm_root, cohort, 'challenger')
    assert path.read_bytes() == before


def test_gap_behind_a_later_arm_fails_closed(tmp_path, monkeypatch):
    m = module(); monkeypatch.setattr(m, '_code_hash', lambda: 'c'*64)
    m.ensure_protocol(tmp_path, now='2026-10-19T12:00:00Z')
    for day in ('2026-10-20', '2026-10-21'):
        data, report, control = selected_fixture(day)
        m.refresh(tmp_path, data, report, control, now=report['decision_at'])
    base = tmp_path/'detection-v2'
    cohort = m._read(base/'cohorts.json')['sessions'][0]
    journal = store.read_journal(base/'control')
    journal['decisions'] = journal['decisions'][1:]
    journal['sha256'] = store._hash({k:v for k,v in journal.items() if k != 'sha256'})
    store._write(base/'control/forward.json', journal)
    before = (base/'control/forward.json').read_bytes()
    with pytest.raises(ValueError, match='detection_v2_arm_gap'):
        m._freeze_arm(base/'control', cohort, 'control')
    assert before == (base/'control/forward.json').read_bytes()


def test_code_dependency_drift_and_line_endings_are_real_file_checked(tmp_path, monkeypatch):
    m = module(); source = tmp_path/'alpha_lab'; source.mkdir()
    monkeypatch.setattr(m, 'SOURCE_ROOT', source)
    required = {'features.py', 'store.py', 'risk.py', 'service.py', 'data.py', '../kelly_position.py'}
    assert required.issubset(m._CODE_FILES)
    for name in m._CODE_FILES:
        path = source/name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'first = 1\nsecond = 2\n')
    original = m._code_hash()
    (source/'features.py').write_bytes(b'first = 1\r\nsecond = 2\r\n')
    assert m._code_hash() == original
    m.ensure_protocol(tmp_path/'run', now='2026-10-19T12:00:00Z')
    before = (tmp_path/'run/detection-v2/protocol.json').read_bytes()
    (source/'store.py').write_bytes(b'first = 999\nsecond = 2\n')
    with pytest.raises(ValueError, match='detection_v2_policy_changed'):
        m.ensure_protocol(tmp_path/'run', now='2026-10-20T12:00:00Z')
    assert before == (tmp_path/'run/detection-v2/protocol.json').read_bytes()


def test_already_closed_arm_and_original_ids_are_byte_preserved_by_freeze_recovery(tmp_path, monkeypatch):
    m = module(); monkeypatch.setattr(m, '_code_hash', lambda: 'c'*64)
    m.ensure_protocol(tmp_path, now='2026-10-19T12:00:00Z')
    data, report, control = selected_fixture()
    m.refresh(tmp_path, data, report, control, now=report['decision_at'])
    complete, later, later_control = selected_fixture('2026-10-30')
    later['buy_candidates'] = later_control['buy_candidates'] = []
    m.refresh(tmp_path, complete, later, later_control, now=later['decision_at'])
    arm_root = tmp_path/'detection-v2/challenger'
    decision = store.read_journal(arm_root)['decisions'][0]
    assert decision['outcomes'][0]['status'] == 'closed'
    assert decision['first_identity'] == report['opportunity_board']
    assert decision['snapshots']['005930'] == data['prices_by_symbol']['005930']
    path = arm_root/'forward.json'; before = path.read_bytes()
    cohort = m._read(tmp_path/'detection-v2/cohorts.json')['sessions'][0]
    m._freeze_arm(arm_root, cohort, 'challenger')
    assert path.read_bytes() == before

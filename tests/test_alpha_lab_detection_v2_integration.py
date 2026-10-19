from copy import deepcopy

import pytest

from app.services.mirofish.alpha_lab import service, store, evolution_store, detection_v2_store
from tests.test_alpha_lab_service import _context_scan


def test_old_source_keeps_legacy_detector_without_new_history(tmp_path):
    report = dict(decision_at='2026-10-04T03:00:00Z', latest_session='2026-10-02')
    assert service._activate_detection_v2(tmp_path, report, {}) is report
    assert not (tmp_path/'detection-v2').exists()


def test_activation_preserves_control_and_selects_exact_board_order(tmp_path, monkeypatch):
    original = dict(decision_at='2026-10-19T12:00:00Z',latest_session='2026-10-19',
        input_fingerprint='a'*64, buy_candidates=[dict(symbol='000001'),dict(symbol='000002')],
        opportunity_board=dict(decision_id='b'*64,input_fingerprint='a'*64,source_audit_hash='c'*64,
            candidates=[dict(symbol='000002')]))
    before = deepcopy(original)
    monkeypatch.setattr(detection_v2_store,'ensure_protocol',lambda *a,**k:{'activation_session':'2026-10-19'})
    calls=[]
    def add(root, report, inputs, *, version='v1'):
        calls.append(version)
        report['opportunity_board']=dict(candidates=[dict(symbol='000003'),dict(symbol='000001')])
        report['buy_candidates']=[dict(symbol='000001'),dict(symbol='000003'),dict(symbol='000004')]
        report['opportunity_scan']={}
        return {'candidates':report['buy_candidates']}
    monkeypatch.setattr(service,'_add_opportunities',add)
    def refresh(root, inputs, report, control, **kwargs):
        assert [r['symbol'] for r in control['buy_candidates']]==['000002']
        assert [r['symbol'] for r in report['buy_candidates']]==['000003','000001']
        return dict(status='waiting',forward={'matured':0})
    monkeypatch.setattr(detection_v2_store,'refresh',refresh)
    result=service._activate_detection_v2(tmp_path,original,{})
    assert original==before and calls==['v2']
    assert result['evolution_control_binding']=={k:before['opportunity_board'][k] for k in ('decision_id','input_fingerprint','source_audit_hash')}
    assert result['opportunity_scan']['forward']=={'matured':0}
    assert 'forward' not in result['detection_validation']


def test_evolution_keeps_legacy_control_after_v2_publication(tmp_path, monkeypatch):
    data, _ = _context_scan(tmp_path,monkeypatch)
    called=[]
    def activate(root, report, inputs, **kwargs):
        assert kwargs['control_discovery']['candidates']
        result=deepcopy(report);result['v2_marker']=True
        return result
    monkeypatch.setattr(service,'_activate_detection_v2',activate)
    def refresh(root,inputs,report,discovery):
        called.append(True)
        assert inputs==data and not report.get('v2_marker')
        assert store.read_status(root)['report']['v2_marker'] is True
        return {'status':'ready'}
    monkeypatch.setattr(evolution_store,'refresh',refresh)
    result=service.scan_once(tmp_path)
    assert result['state']!='failed' and called==[True]


def test_required_v2_failure_preserves_previous_public_report(tmp_path,monkeypatch):
    _context_scan(tmp_path,monkeypatch)
    before=service.scan_once(tmp_path)['report']
    def fail(*args,**kwargs):raise ValueError('untrusted raw provider details')
    monkeypatch.setattr(service,'_activate_detection_v2',fail)
    result=service.scan_once(tmp_path)
    assert result['state']=='failed' and result['report']==before
    assert 'raw provider' not in str(result)


def test_control_uses_full_discovery_when_board_selects_beyond_legacy_top_three(tmp_path, monkeypatch):
    report = dict(decision_at='2026-10-19T12:00:00Z', latest_session='2026-10-19',
        buy_candidates=[dict(symbol=f'{i:06d}') for i in (1, 2, 3)],
        opportunity_board=dict(decision_id='b'*64, input_fingerprint='a'*64, source_audit_hash='c'*64,
            candidates=[dict(symbol='000004'), dict(symbol='000001')]))
    full = dict(candidates=[dict(symbol=f'{i:06d}', original=i) for i in (1, 2, 3, 4)])
    before = deepcopy((report, full))
    monkeypatch.setattr(detection_v2_store, 'ensure_protocol', lambda *a, **k: {'activation_session':'2026-10-19'})
    def add(root, active, inputs, **kwargs):
        active.update(buy_candidates=[], opportunity_board=dict(candidates=[]), opportunity_scan={})
    monkeypatch.setattr(service, '_add_opportunities', add)
    def refresh(root, inputs, active, control, **kwargs):
        assert control['buy_candidates'] == [full['candidates'][3], full['candidates'][0]]
        return dict(status='waiting')
    monkeypatch.setattr(detection_v2_store, 'refresh', refresh)
    service._activate_detection_v2(tmp_path, report, {}, control_discovery=full)
    assert (report, full) == before
    with pytest.raises(ValueError, match='control_candidate_missing'):
        service._activate_detection_v2(tmp_path, report, {}, control_discovery={'candidates':full['candidates'][:3]})

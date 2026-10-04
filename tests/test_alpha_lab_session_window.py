"""Certified next-session proposal windows remain bound to first source decisions."""
from copy import deepcopy
import pytest
from tests.test_alpha_lab_opportunities import status
from app.services.mirofish.alpha_lab.proposals import present_status

NOW = '2026-10-05T00:05:00Z'

def snapshot():
    source = status()
    report = source['report']
    report['input_fingerprint'] = 'a'*64
    report['opportunity_scan']['audit_hash'] = 'b'*64
    report['decision_at'] = '2026-10-04T05:00:00Z'
    report['provenance']['captured_at'] = '2026-10-02T07:00:00Z'
    report['proposal_window'] = dict(policy_version='next-session-proposal-v1',
        input_fingerprint='a'*64, opportunity_audit_hash='b'*64,
        origin_at='2026-10-02T09:45:00Z', entry_session='2026-10-05',
        valid_until='2026-10-05T06:30:00Z', calendar_source='KIS:CTCA0903R')
    return source

def opinion(source, now=NOW):
    return present_status(source, now=now)['report']['buy_candidates'][0]['proposal']

def test_certified_weekend_rollover_uses_first_origin_next_session_close():
    source = snapshot()
    original = deepcopy(source)
    row = opinion(source)
    assert row['action'] == 'buy'
    assert row['valid_until'] == '2026-10-05T06:30:00Z'
    assert row['order_allowed'] is False
    assert source == original

def test_rescan_cannot_extend_fixed_session_window():
    source = snapshot()
    source['report']['decision_at'] = '2026-10-05T06:29:00Z'
    assert opinion(source, '2026-10-05T06:30:00Z')['action'] == 'wait'
    assert opinion(source, '2026-10-05T06:30:00Z')['valid_until'] == '2026-10-05T06:30:00Z'

@pytest.mark.parametrize('field,value', [
    ('policy_version','unknown'), ('input_fingerprint','c'*64),
    ('opportunity_audit_hash','c'*64), ('origin_at','2026-10-04T06:00:00Z'),
    ('origin_at','2026-10-02T09:45:00'), ('entry_session','2026-10-02'),
    ('entry_session','2026-10-14'), ('valid_until','2026-10-05T06:31:00Z'),
    ('calendar_source','local_weekdays'), ('entry_session',None), ('valid_until',None),
])
def test_unverified_or_mismatched_optional_window_holds_instead_of_renewing(field,value):
    source = snapshot()
    source['report']['proposal_window'][field] = value
    assert opinion(source)['action'] == 'wait'

def test_origin_before_capture_is_not_a_source_bound_decision():
    source=snapshot()
    source['report']['provenance']['captured_at']='2026-10-03T00:00:00Z'
    assert opinion(source)['action']=='wait'

def test_legacy_without_window_preserves_24hour_rule():
    source=snapshot()
    del source['report']['proposal_window']
    assert opinion(source)['action']=='buy'
    assert opinion(source)['valid_until']=='2026-10-05T05:00:00Z'

def test_valid_window_does_not_bypass_failed_scan_or_old_price():
    for state in ('running','failed'):
        source=snapshot(); source['state']=state
        assert opinion(source)['action']=='wait'
    source=snapshot();source['report']['latest_session']='2026-09-01'
    assert opinion(source)['action']=='wait'



def test_saved_get_attaches_monitor_without_running_sources_or_writing(tmp_path, monkeypatch):
    from app.services.mirofish.alpha_lab import service, store, monitor
    source=snapshot()
    source['report'].pop('proposal_window')
    store.publish(tmp_path, source['report'], held=True)
    monkeypatch.setattr(service,'ROOT',tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError('saved GET must not fetch, research or mutate')
    monkeypatch.setattr(service,'load_inputs',forbidden)
    monkeypatch.setattr(service,'run_research',forbidden)
    monkeypatch.setattr(store,'_write',forbidden)
    seen=[]
    def attach(saved, root, now=None):
        seen.append(root)
        result=deepcopy(saved)
        result['operations']={'sentinel':'saved'}
        return result
    monkeypatch.setattr(monitor,'attach_operations',attach)
    actual=service.read_status()
    assert actual['operations']=={'sentinel':'saved'}
    assert seen==[tmp_path]
    assert actual['report']==source['report']

def test_successful_scan_registers_completed_source_report_once(tmp_path, monkeypatch):
    from app.services.mirofish.alpha_lab import service, monitor
    from tests.test_alpha_lab_service import _context_scan
    _context_scan(tmp_path, monkeypatch)
    seen=[]
    def register(root, report, now=None):
        assert 'experiment_hash' in report
        assert 'forward' in report
        assert 'analyst_context_audit_hash' in report['opportunity_scan']
        assert now==report['decision_at']
        seen.append((root, deepcopy(report)))
        return None
    monkeypatch.setattr(monitor,'register_report',register)
    result=service.scan_once(tmp_path)
    assert result['state']!='failed'
    assert len(seen)==1
    assert seen[0][0]==tmp_path
    assert seen[0][1]['input_fingerprint']==result['report']['input_fingerprint']

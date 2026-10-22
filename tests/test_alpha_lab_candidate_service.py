"""Composition is additive, saved-only on GET and failure preserving."""
import importlib
from copy import deepcopy

import pytest

from tests.test_alpha_lab_candidate_store import data, desk


def module():
    try:return importlib.import_module('app.services.mirofish.alpha_lab.candidate_service')
    except ModuleNotFoundError:pytest.fail('candidate service composition is not implemented')


class Calendar:
    def fetch_calendar(self, base_date, now=None):
        return dict(source='KIS:CTCA0903R',captured_at='2026-10-22T00:01:30Z',days=[
            dict(date='2026-10-22',is_open=True),dict(date='2026-10-23',is_open=True),
            dict(date='2026-10-24',is_open=False)])


def test_refresh_uses_own_source_own_actual_clock_and_next_official_session(tmp_path,monkeypatch):
    mod=module();inputs=data();result=desk()
    monkeypatch.setattr(mod,'_acquire',lambda *a,**k:inputs)
    monkeypatch.setattr(mod,'_detect',lambda *a,**k:result)
    old=tmp_path/'detection-v2'/'protocol.json';old.parent.mkdir();old.write_text('original')
    value=mod.refresh_desk(tmp_path,now='2026-10-22T00:02:00Z',calendar_provider=Calendar())
    assert value['state']=='ready'
    assert value['entry_session']=='2026-10-23'
    assert value['generated_at']=='2026-10-22T00:02:00Z'
    assert value['source']['venue']=='KRX'
    assert value['candidates'][0]['symbol']=='005930'
    assert old.read_text()=='original'


def test_missing_calendar_or_source_downgrades_without_replacing_first_result(tmp_path,monkeypatch):
    mod=module();inputs=data();result=desk()
    monkeypatch.setattr(mod,'_acquire',lambda *a,**k:inputs)
    monkeypatch.setattr(mod,'_detect',lambda *a,**k:result)
    first=mod.refresh_desk(tmp_path,now='2026-10-22T00:02:00Z',calendar_provider=Calendar())
    def failure(*a,**k):raise OSError('private environment path must not be returned')
    monkeypatch.setattr(mod,'_acquire',failure)
    value=mod.refresh_desk(tmp_path,now='2026-10-22T00:03:00Z',calendar_provider=Calendar())
    assert value['state']=='failed'
    assert value['decision_id']==first['decision_id']
    assert 'private' not in str(value)
    from app.services.mirofish.alpha_lab import candidate_store
    saved=candidate_store.read_decisions(tmp_path/'candidate-desk')['records'][0]['desk']
    assert saved=={k:v for k,v in first.items() if k!='forward'}


def test_read_status_does_not_fetch_fit_or_write(tmp_path,monkeypatch):
    mod=module();inputs=data();result=desk()
    monkeypatch.setattr(mod,'_acquire',lambda *a,**k:inputs)
    monkeypatch.setattr(mod,'_detect',lambda *a,**k:result)
    mod.refresh_desk(tmp_path,now='2026-10-22T00:02:00Z',calendar_provider=Calendar())
    monkeypatch.setattr(mod,'ROOT',tmp_path)
    monkeypatch.setattr(mod,'_legacy_read',lambda *a,**k:dict(state='held',report=None))
    monkeypatch.setattr(mod,'_acquire',lambda *a,**k:pytest.fail('GET attempted acquisition'))
    monkeypatch.setattr(mod,'_detect',lambda *a,**k:pytest.fail('GET attempted fitting'))
    before={p:p.read_bytes() for p in tmp_path.rglob('*.json')}
    actual=mod.read_status(now='2026-10-22T00:03:00Z')
    assert actual['candidate_desk']['candidates'][0]['symbol']=='005930'
    assert {p:p.read_bytes() for p in tmp_path.rglob('*.json')}==before


def test_calendar_failure_recovers_completed_analysis_without_freezing_broken_window(tmp_path,monkeypatch):
    mod=module();calls=[]
    monkeypatch.setattr(mod,'_acquire',lambda *a,**k:data())
    def detector(*a,**k):calls.append(1);return desk()
    monkeypatch.setattr(mod,'_detect',detector)
    class Missing:
        def fetch_calendar(self,*a,**k):raise OSError('unavailable')
    assert mod.refresh_desk(tmp_path,now='2026-10-22T00:02:00Z',calendar_provider=Missing()) is None
    assert not (tmp_path/'candidate-desk'/'decisions.json').exists()
    result=mod.refresh_desk(tmp_path,now='2026-10-22T00:03:00Z',calendar_provider=Calendar())
    assert result['state']=='ready'
    assert result['entry_session']=='2026-10-23'
    assert calls==[1]


def test_async_completion_releases_cross_thread_lock(tmp_path,monkeypatch):
    import threading
    from filelock import FileLock
    mod=module();threads=[];real_thread=threading.Thread;gate=threading.Event()
    monkeypatch.setattr(mod,'ROOT',tmp_path)
    def legacy(*a,**k):gate.wait(timeout=3);return dict(state='held',report=None)
    monkeypatch.setattr(mod.legacy,'scan_once',legacy)
    monkeypatch.setattr(mod,'refresh_desk',lambda *a,**k:None)
    def thread(*a,**k):
        value=real_thread(*a,**k);threads.append(value);return value
    monkeypatch.setattr(mod.threading,'Thread',thread)
    mod.start_scan()
    gate.set()
    threads[0].join(timeout=3)
    assert not threads[0].is_alive()
    with FileLock(str(tmp_path/'candidate-compose.lock')).acquire(timeout=0):pass


@pytest.mark.parametrize('patch', [
    dict(captured_at='2026-10-22T00:03:00Z'),
    dict(captured_at='2026-10-21T00:00:00Z'),
    dict(days=[dict(date='20261023',is_open=True)]),
    dict(days=[dict(date='2026-10-23',is_open=True),dict(date='2026-10-23',is_open=False)]),
    dict(days=[dict(date='2027-10-23',is_open=True)]),
    dict(days=[dict(date='2026-10-22',is_open=True),dict(date='2026-10-26',is_open=True)]),
])
def test_entry_rejects_invalid_or_stale_calendar(patch):
    mod=module(); calendar=Calendar().fetch_calendar('2026-10-22');calendar.update(patch)
    assert mod._entry(calendar,mod.candidate_store._clock('2026-10-22T00:02:00Z'))==(None,None)


@pytest.mark.parametrize('attempt', [None,dict(status='failed',snapshot_id='old'),
    dict(status='complete',snapshot_id='other')])
def test_failed_or_unbound_canonical_refresh_cannot_reuse_scope_as_ready(tmp_path,monkeypatch,attempt):
    import json
    from app.services.mirofish.alpha_lab import candidate_inputs
    mod=module(); original=dict(data(),status='ready')
    original['provenance']['scope_hash']='c'*64
    inputs=tmp_path/'inputs';inputs.mkdir()
    (inputs/'current.json').write_text(json.dumps(dict(snapshot_id='old',latest_session='2026-10-21')))
    if attempt is not None:(inputs/'last_attempt.json').write_text(json.dumps(attempt))
    monkeypatch.setattr(mod.legacy,'resolve_inputs',lambda *a:())
    monkeypatch.setattr(mod.legacy,'load_inputs',lambda *a:original)
    monkeypatch.setattr(candidate_inputs,'collect_inputs',lambda *a,**k:pytest.fail('failed source reached candidate acquisition'))
    with pytest.raises(ValueError,match='candidate_scope_unavailable'):
        mod._acquire(tmp_path)


def test_complete_matching_canonical_refresh_can_resume_candidate_acquisition(tmp_path,monkeypatch):
    import json
    from app.services.mirofish.alpha_lab import candidate_inputs
    mod=module();original=dict(data(),status='ready');original['provenance']['scope_hash']='c'*64
    directory=tmp_path/'inputs';directory.mkdir()
    (directory/'current.json').write_text(json.dumps(dict(snapshot_id='current',latest_session='2026-10-21',hashes=dict(universe_report='c'*64))))
    (directory/'last_attempt.json').write_text(json.dumps(dict(status='complete',snapshot_id='current')))
    monkeypatch.setattr(mod.legacy,'resolve_inputs',lambda *a:())
    monkeypatch.setattr(mod.legacy,'load_inputs',lambda *a:original)
    monkeypatch.setattr(candidate_inputs,'collect_inputs',lambda *a,**k:dict(resumed=True))
    assert mod._acquire(tmp_path)==dict(resumed=True)


@pytest.mark.parametrize('with_desk',[False,True])
def test_read_status_keeps_polling_during_candidate_stage(tmp_path,monkeypatch,with_desk):
    mod=module();monkeypatch.setattr(mod,'ROOT',tmp_path)
    monkeypatch.setattr(mod,'_legacy_read',lambda *a,**k:dict(state='held',report=None))
    directory=tmp_path/'candidate-desk'
    if with_desk:mod.candidate_store.publish(directory,desk(),data(),now='2026-10-22T00:02:00Z')
    mod.candidate_store.set_attempt(directory,'running',now='2026-10-22T00:03:00Z')
    assert mod.read_status(now='2026-10-22T00:04:00Z')['state']=='running'
    assert mod.read_status(now='2026-10-22T00:24:00Z')['state']!='running'


@pytest.mark.parametrize('raises',[False,True])
def test_finished_failed_worker_never_leaves_polling_running(tmp_path,monkeypatch,raises):
    import threading
    mod=module();monkeypatch.setattr(mod,'ROOT',tmp_path)
    def failure(*a,**k):
        if raises:raise RuntimeError('private diagnostic')
        return dict(state='failed',error='scan_unavailable')
    monkeypatch.setattr(mod.legacy,'scan_once',failure)
    monkeypatch.setattr(mod,'_legacy_read',lambda *a,**k:dict(state='failed',error='scan_unavailable'))
    class InlineThread:
        def __init__(self,*,target,**kwargs):self.target=target
        def start(self):self.target()
    monkeypatch.setattr(threading,'Thread',InlineThread)
    mod.start_scan()
    assert mod.read_status()['state']=='failed'
    attempt=mod.candidate_store._load(tmp_path/'candidate-desk'/'attempt.json')
    assert attempt['state']=='failed'
    assert 'private' not in str(attempt)

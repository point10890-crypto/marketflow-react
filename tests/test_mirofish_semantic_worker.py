import importlib
from datetime import datetime, timezone


def test_worker_resume_and_completed_job_do_not_reenrich(monkeypatch, tmp_path):
    from app.services.mirofish import semantic_decisions as s
    w=importlib.import_module('app.services.mirofish.semantic_worker')
    monkeypatch.setenv('MIROFISH_SEMANTIC_PROVIDER','deepseek')
    monkeypatch.setenv('MIROFISH_SEMANTIC_LIVE_ENABLED','true')
    monkeypatch.setenv('DEEPSEEK_API_KEY','test')
    run={'id':'scanner-test','generated_at':datetime.now(timezone.utc).isoformat(),'candidates':[]}
    enrichments=[]
    def enrich(sid, **kwargs):
        enrichments.append(sid)
        return {'id':sid,'added_headlines':0,'source_errors':0}
    monkeypatch.setattr(w,'enrich_snapshot',enrich)
    attempts=[]
    def evaluate(sid, **kwargs):
        attempts.append(sid)
        return {'validated_count':len(attempts)-1,'results':[{'status':'deferred' if len(attempts)==1 else 'validated'}]}
    monkeypatch.setattr(s,'evaluate_snapshot',evaluate)
    a=w.run_once(root=tmp_path, scanner_reader=lambda:run)
    b=w.run_once(root=tmp_path, scanner_reader=lambda:run)
    c=w.run_once(root=tmp_path, scanner_reader=lambda:run)
    assert a['status']=='pending' and b['status']=='completed' and c['status']=='idle'
    assert len(enrichments)==1 and len(attempts)==2


def test_disabled_worker_does_not_scan_or_spend(tmp_path):
    w=importlib.import_module('app.services.mirofish.semantic_worker')
    def fail(): raise AssertionError('must not scan')
    assert w.run_once(root=tmp_path,scanner_reader=fail)['status']=='disabled'


def test_worker_lock_and_stale_scanner(monkeypatch,tmp_path):
    import sqlite3
    w=importlib.import_module('app.services.mirofish.semantic_worker')
    monkeypatch.setenv('MIROFISH_SEMANTIC_PROVIDER','deepseek')
    monkeypatch.setenv('MIROFISH_SEMANTIC_LIVE_ENABLED','true')
    monkeypatch.setenv('DEEPSEEK_API_KEY','test')
    db=sqlite3.connect(tmp_path/'worker_lock.sqlite3')
    db.execute('BEGIN IMMEDIATE')
    try:
        assert w.run_once(root=tmp_path,scanner_reader=lambda:None)['status']=='busy'
    finally: db.close()
    old={'id':'old','generated_at':'2020-01-01T00:00:00Z','candidates':[]}
    assert w.run_once(root=tmp_path,scanner_reader=lambda:old)['status']=='stale_scanner'
    assert not (tmp_path/'snapshots').exists()


def test_idle_worker_refreshes_repaired_result_without_inference(monkeypatch,tmp_path):
    from app.services.mirofish import semantic_decisions as s
    from app.utils.atomic_json import write_json_atomic
    w=importlib.import_module('app.services.mirofish.semantic_worker')
    monkeypatch.setenv('MIROFISH_SEMANTIC_PROVIDER','deepseek')
    monkeypatch.setenv('MIROFISH_SEMANTIC_LIVE_ENABLED','true')
    monkeypatch.setenv('DEEPSEEK_API_KEY','test')
    write_json_atomic(str(tmp_path/'worker_job.deepseek.json'),{'scanner_run_id':'same','snapshot_id':'test','status':'completed_with_errors'})
    monkeypatch.setattr(s,'read_evaluation',lambda *a,**k:{'validated_count':1,'results':[{'status':'validated'}]})
    monkeypatch.setattr(s,'evaluate_snapshot',lambda *a,**k:(_ for _ in ()).throw(AssertionError('must not infer')))
    r=w.run_once(root=tmp_path,scanner_reader=lambda:{'id':'same'})
    assert r['last_job']['status']=='completed' and r['last_job']['validated_count']==1

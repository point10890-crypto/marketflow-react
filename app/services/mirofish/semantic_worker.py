"""Resumable single-batch worker for the latest scanner pool. No live ranking."""
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from app.services.mirofish import semantic_decisions as s
from app.services.mirofish.semantic_sources import enrich_snapshot
from app.utils.atomic_json import write_json_atomic


def read_status(*, root=None):
    path=s._root(root)/'worker_status.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'status':'not_started'}


def run_once(*, root=None, scanner_reader=None):
    if not s._enabled(): return {'status':'disabled'}
    if not s._key(): return {'status':'unconfigured'}
    directory=s._root(root)
    directory.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(str(directory/'worker_lock.sqlite3'),timeout=.1)
    try:
        try: db.execute('BEGIN IMMEDIATE')
        except sqlite3.OperationalError: return {'status':'busy'}
        result=_run(directory,scanner_reader)
        result['checked_at']=datetime.now(timezone.utc).isoformat()
        result['provider']=s.provider()
        write_json_atomic(str(directory/'worker_status.json'),result)
        return result
    finally:
        db.close()


def _run(directory,scanner_reader):
    if scanner_reader is None:
        from app.services.mirofish.alpha_scanner import read_latest_scanner_run
        scanner_reader=read_latest_scanner_run
    jobpath=directory/('worker_job.'+s.provider()+'.json')
    job=json.loads(jobpath.read_text(encoding='utf-8')) if jobpath.exists() else {}
    if job.get('status') != 'pending':
        run=scanner_reader()
        if not run: return {'status':'no_scanner_run'}
        if job.get('scanner_run_id')==run['id']:
            # Offline revalidation may have repaired a saved response since completion.
            result=s.read_evaluation(job['snapshot_id'],root=directory)
            if result.get('results'):
                job=_summary(job,result)
                write_json_atomic(str(jobpath),job)
            return {'status':'idle','last_job':job}
        at=run.get('generated_at') or run.get('created_at')
        age=datetime.now(timezone.utc)-s._instant(at)
        if not timedelta(0)<=age<=timedelta(hours=36):
            return {'status':'stale_scanner','scanner_run_id':run['id']}
        snap=s.record_snapshot(run.get('candidates') or [],workflow_id='scanner:'+run['id'],decision_at=at,root=directory)
        enriched=enrich_snapshot(snap['id'],root=directory)
        job={'scanner_run_id':run['id'],'snapshot_id':enriched['id'],'status':'pending',
             'added_headlines':enriched['added_headlines'],'source_errors':enriched['source_errors']}
        # Persist the selected immutable input before making a paid call.
        write_json_atomic(str(jobpath),job)
    result=s.evaluate_snapshot(job['snapshot_id'],root=directory)
    job=_summary(job,result)
    write_json_atomic(str(jobpath),job)
    return job


def _summary(job,result):
    counts={}
    for item in result.get('results',[]): counts[item['status']]=counts.get(item['status'],0)+1
    pending=any(counts.get(k) for k in ('deferred','budget_exhausted','in_progress'))
    terminal_errors=any(counts.get(k) for k in ('failed','uncertain'))
    job.update({'status':'pending' if pending else 'completed_with_errors' if terminal_errors else
                'completed_with_exclusions' if counts.get('ineligible') else 'completed',
                'counts':counts,'validated_count':result.get('validated_count',0)})
    if result.get('status') in {'disabled','unconfigured'}: job['status']='pending'
    return job

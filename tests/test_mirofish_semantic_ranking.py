import copy
from datetime import datetime, timezone, timedelta
from app.services.mirofish import semantic_ranking as m

NOW = datetime(2026,9,28,6,tzinfo=timezone.utc)
def rows():
    return [dict(symbol=str(i),market='KR',ranking_score=90-i,action='BUY_CANDIDATE') for i in range(4)]
def evidence(**kw):
    return dict(available_at=NOW.isoformat(),answers={'relevance':{'label':'direct'},'evidence_sufficiency':{'label':'sufficient'},'audit_concern':{'label':'yes','quote':'감사의견 거절'}},**kw)
def test_risk_changes_actual_top3_without_boosting_uncovered_candidates():
    original=rows(); saved=copy.deepcopy(original)
    out,report=m.apply(original,now=NOW,decisions={('KR','0'):evidence()},enabled=True)
    assert [r['symbol'] for r in out[:3]]==['1','2','3']
    assert original==saved
    assert out[-1]['action']=='REJECT'
    assert report['changed_count']==1
    assert out[0]['ranking_score']==89

def test_stale_future_unrelated_and_missing_evidence_do_not_change_ranking():
    for delta in (-25,1):
        item=evidence(); item['available_at']=(NOW+timedelta(hours=delta)).isoformat()
        out,report=m.apply(rows(),now=NOW,decisions={('KR','0'):item},enabled=True)
        assert out[0]['symbol']=='0' and report['changed_count']==0
    item=evidence(); item['answers']['relevance']['label']='unrelated'
    assert m.apply(rows(),now=NOW,decisions={('KR','0'):item},enabled=True)[1]['changed_count']==0

def test_idempotent_disabled_and_market_identity():
    out,_=m.apply(rows(),now=NOW,decisions={('KR','0'):evidence()},enabled=True)
    again,_=m.apply(out,now=NOW,decisions={('KR','0'):evidence()},enabled=True)
    assert again[-1]['ranking_score']==out[-1]['ranking_score']
    assert m.apply(rows(),now=NOW,decisions={('US','0'):evidence()},enabled=True)[1]['changed_count']==0
    assert m.apply(rows(),now=NOW,decisions={},enabled=False)[0]==rows()

def test_loader_rechecks_grounding_and_observation_cutoff(tmp_path,monkeypatch):
    import json,os
    from app.services.mirofish import semantic_decisions as s, semantic_deepseek as d
    from tests.test_mirofish_semantic_decisions import candidate
    from tests.test_mirofish_semantic_deepseek import answer
    c=candidate(); snap=s.record_snapshot([c],workflow_id='test',decision_at=c['source_cutoff'],root=tmp_path)
    a=answer(d)['answers']
    for key,label in [('relevance','direct'),('evidence_sufficiency','sufficient'),('contract_termination','yes')]:
        a[key]={'label':label,'quote':'가상기업A는 계약 해지를 확정했다.'}
    p=tmp_path/'evaluations'/f"{snap['id']}.deepseek.json";p.parent.mkdir()
    payload={'snapshot_id':snap['id'],'results':[{'symbol':c['symbol'],'market':c['market'],'status':'validated','answers':a}]}
    p.write_text(json.dumps(payload),encoding='utf-8');os.utime(p,(NOW.timestamp(),NOW.timestamp()))
    decisions=m.load_decisions(root=tmp_path)
    sample=[dict(symbol=c['symbol'],market=c['market'],ranking_score=90,action='BUY_CANDIDATE')]
    out,report=m.apply(sample,now=NOW,decisions=decisions,enabled=True)
    assert report['changed_count']==1 and out[0]['ranking_score']==82
    assert m.apply(sample,now=NOW-timedelta(seconds=1),decisions=decisions,enabled=True)[1]['changed_count']==0
    payload['results'][0]['answers']['contract_termination']['quote']='fabricated claim'
    p.write_text(json.dumps(payload),encoding='utf-8');os.utime(p,(NOW.timestamp(),NOW.timestamp()))
    assert m.apply(sample,now=NOW,decisions=m.load_decisions(root=tmp_path),enabled=True)[1]['changed_count']==0

def test_scanner_applies_overlay_before_truncating_candidates(monkeypatch,tmp_path):
    from app.services.mirofish import alpha_scanner as scanner
    monkeypatch.setenv('MIROFISH_SEMANTIC_RANKING_ENABLED','true')
    monkeypatch.setattr(m,'load_decisions',lambda **kw:{('KR','0'):{**evidence(),'available_at':(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()}})
    monkeypatch.setattr(scanner,'_load_artifacts',lambda:{'candidate_symbols':set('0123')})
    monkeypatch.setattr(scanner,'_collect_requested_kis_live',lambda *a:None)
    monkeypatch.setattr(scanner,'_performance_advisory',lambda:{})
    monkeypatch.setattr(scanner,'_build_candidate_pool',lambda *a,**kw:rows())
    monkeypatch.setattr(scanner,'_maybe_deepseek_rerank_candidates',lambda *a,**kw:{'enabled':False})
    monkeypatch.setattr(scanner,'_source_files',lambda *a,**kw:[])
    monkeypatch.setattr(scanner,'_run_path',lambda rid:str(tmp_path/(rid+'.json')))
    monkeypatch.setattr(scanner,'_run_artifact_path',lambda rid,name:str(tmp_path/name))
    run=scanner.create_scanner_run({'limit':3})
    assert [r['symbol'] for r in run['candidates']]==['1','2','3']
    assert run['semantic_ranking']['changed_count']==1

def test_final_top3_score_preserves_risk_penalty(monkeypatch):
    from app.services.mirofish import workflow
    monkeypatch.setenv('MIROFISH_SEMANTIC_RANKING_ENABLED','true')
    c=rows()[0]; c.update(alpha_score=80,risk_score=20)
    run={'verdict':{'action':'BUY','confidence_pct':80}}
    baseline=workflow._final_score(c,run)
    c['semantic_ranking']={'policy':m.POLICY,'status':'applied','penalty':8,'reasons':['contract_termination']}
    assert workflow._final_score(c,run)==baseline-8
    assert workflow._candidate_summary(c)['semantic_ranking']['penalty']==8

def test_disabling_overlay_restores_baseline_and_expiry_restores_order():
    out,_=m.apply(rows(),now=NOW,decisions={('KR','0'):evidence()},enabled=True)
    restored,_=m.apply(out,now=NOW,decisions={},enabled=False)
    assert [r['symbol'] for r in restored]==['0','1','2','3']
    assert restored[0]['action']=='BUY_CANDIDATE' and restored[0]['ranking_score']==90
    assert not restored[0].get('semantic_ranking',{}).get('reasons')
    expired,_=m.apply(out,now=NOW+timedelta(days=2),decisions={('KR','0'):evidence()},enabled=True)
    assert expired[0]['symbol']=='0'

def test_nested_old_publication_cannot_be_refreshed_by_fetch(tmp_path):
    import json,os
    from app.services.mirofish import semantic_decisions as s, semantic_deepseek as d
    from tests.test_mirofish_semantic_decisions import candidate
    from tests.test_mirofish_semantic_deepseek import answer
    c=candidate(); c['source_packets'][0]['content']['published_at']='2026-09-20T00:00:00+00:00'
    snap=s.record_snapshot([c],workflow_id='test',decision_at=c['source_cutoff'],root=tmp_path)
    a=answer(d)['answers']
    for key,label in [('relevance','direct'),('evidence_sufficiency','sufficient'),('contract_termination','yes')]:
        a[key]={'label':label,'quote':'가상기업A는 계약 해지를 확정했다.'}
    p=tmp_path/'evaluations'/f"{snap['id']}.deepseek.json";p.parent.mkdir()
    p.write_text(json.dumps({'snapshot_id':snap['id'],'results':[{'symbol':c['symbol'],'market':c['market'],'status':'validated','answers':a}]}),encoding='utf-8')
    os.utime(p,(NOW.timestamp(),NOW.timestamp()))
    sample=[dict(symbol=c['symbol'],market=c['market'],ranking_score=90,action='BUY_CANDIDATE')]
    assert m.apply(sample,now=NOW,decisions=m.load_decisions(root=tmp_path),enabled=True)[1]['changed_count']==0

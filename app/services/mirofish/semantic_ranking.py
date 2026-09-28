"""Grounded semantic risk overlay on real scanner/admission ranking; no inference."""
import copy
import json
import math
import os
from datetime import datetime, timezone, timedelta
from app.services.mirofish import semantic_decisions as s, semantic_deepseek

POLICY = 'semantic-risk-v1'
# Explicit conservative policy weights, not predicted returns or probabilities.
PENALTIES = {'audit_concern': 12, 'contract_termination': 8, 'equity_dilution': 4}

def enabled():
    return os.getenv('MIROFISH_SEMANTIC_RANKING_ENABLED','').lower() in {'1','true'}

def load_decisions(*, root=None):
    directory=s._root(root)
    result={}
    paths=sorted((directory/'evaluations').glob('*.deepseek.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:100]
    for path in paths:
        try:
            evaluation=json.loads(path.read_text(encoding='utf-8'))
            snapshot=s.read_snapshot(evaluation['snapshot_id'],root=directory)
            observed=datetime.fromtimestamp(path.stat().st_mtime,timezone.utc)
            at=max(observed,s._instant(snapshot['decision_at']))
            candidates={(c['market'],c['symbol']):c for c in snapshot['candidates']}
            for item in evaluation.get('results',[]):
                key=(item.get('market'),item.get('symbol'))
                if key in result: continue
                # Newer incomplete evidence supersedes an older risk claim.
                result[key]={'available_at':at.isoformat(),'answers':{},'status':item.get('status')}
                if item.get('status')!='validated' or key not in candidates: continue
                payload=s.build_request(candidates[key],decision_at=snapshot['decision_at'])
                checked=semantic_deepseek.validate({'answers':item['answers']},payload)
                published=[s._instant(e['available_at']) for e in payload['state']['evidence']]
                published += [s._instant(container['published_at'])
                              for packet in candidates[key].get('source_packets',[])
                              for container in (packet, packet.get('content') or {})
                              if container.get('published_at')]
                result[key].update(answers=checked['answers'],snapshot_id=snapshot['id'],
                    evidence_at=min(published).isoformat(),fingerprint=item.get('fingerprint'),
                    sources=[{'source':e['source'],'evidence_id':e['evidence_id']} for e in payload['state']['evidence']])
        except (OSError,ValueError,KeyError,TypeError,AttributeError):
            continue
    return result

def apply(rows, *, now=None, decisions=None, enabled=None, root=None):
    active=globals()['enabled']() if enabled is None else enabled
    report={'policy':POLICY,'status':'enabled' if active else 'disabled','changed_count':0,'covered_count':0,
            'before_top3':[r.get('symbol') for r in rows[:3]],'after_top3':[]}
    if not active:
        if any((r.get('semantic_ranking') or {}).get('policy') == POLICY for r in rows):
            restored=copy.deepcopy(rows)
            for row in restored:
                previous=row.pop('semantic_ranking',{})
                if previous.get('policy') == POLICY:
                    row['ranking_score']=previous.get('base_score',row.get('ranking_score'))
                    row['action']=previous.get('base_action',row.get('action'))
            restored.sort(key=lambda r:r.get('ranking_score') or 0,reverse=True)
            for i,row in enumerate(restored,1): row['rank']=i
            report['after_top3']=[r.get('symbol') for r in restored[:3]]
            return restored,report
        report['after_top3']=report['before_top3']
        return rows,report
    now=now or datetime.now(timezone.utc)
    decisions=load_decisions(root=root) if decisions is None else decisions
    output=copy.deepcopy(rows)
    for row in output:
        prior=row.get('semantic_ranking') or {}
        base=prior.get('base_score',row.get('ranking_score'))
        action=prior.get('base_action',row.get('action'))
        if not isinstance(base,(int,float)) or not math.isfinite(base): continue
        row.update(ranking_score=base,action=action)
        record={'policy':POLICY,'status':'no_fresh_evidence','base_score':base,'base_action':action,'penalty':0,'reasons':[]}
        row['semantic_ranking']=record
        item=decisions.get((row.get('market'),row.get('symbol')))
        if not item: continue
        try:
            times=[s._instant(item['available_at'])]
            if item.get('evidence_at'): times.append(s._instant(item['evidence_at']))
            if any(not timedelta(0)<=now-at<=timedelta(hours=24) for at in times): continue
            answers=item['answers']
            if answers.get('relevance',{}).get('label')!='direct': continue
            if answers.get('evidence_sufficiency',{}).get('label')!='sufficient': continue
            risks=[k for k in PENALTIES if answers.get(k,{}).get('label')=='yes' and answers[k].get('quote')]
        except (ValueError,KeyError,TypeError): continue
        penalty=min(12,sum(PENALTIES[k] for k in risks))
        record.update(status='applied' if risks else 'validated_no_risk',penalty=penalty,reasons=risks,
                      snapshot_id=item.get('snapshot_id'),fingerprint=item.get('fingerprint'),
                      available_at=item['available_at'],sources=item.get('sources',[]),
                      quotes={k:answers[k]['quote'] for k in risks})
        report['covered_count']+=1
        if risks:
            row['ranking_score']=round(base-penalty,4)
            if 'audit_concern' in risks: row['action']='REJECT'
            report['changed_count']+=1
    # Retain baseline order on ties, preserving existing numerical/convergence gates.
    if report['changed_count'] or any((r.get('semantic_ranking') or {}).get('penalty') for r in rows):
        output.sort(key=lambda r:('audit_concern' not in (r.get('semantic_ranking') or {}).get('reasons',[]),r.get('ranking_score',0)),reverse=True)
    for i,row in enumerate(output,1): row['rank']=i
    report['after_top3']=[r.get('symbol') for r in output[:3]]
    return output,report

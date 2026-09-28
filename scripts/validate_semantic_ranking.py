"""Verify real scanner integration and a deterministic risky-Top3 counterfactual.

Runs the scanner once without the paid reranker. Does not send alerts or orders.
"""
import argparse
import json
import sys
from pathlib import Path
from datetime import datetime, timezone
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(ROOT/'.env')
    from app.services.mirofish import alpha_scanner, semantic_ranking as m, workflow
    from app.utils.atomic_json import write_json_atomic
    if not m.enabled(): raise RuntimeError('semantic_ranking_disabled')
    run=alpha_scanner.create_scanner_run({'limit':20,'deepseek_rerank':False})
    assert run['semantic_ranking']['status']=='enabled'
    now=datetime.now(timezone.utc)
    # Separate in-memory fixture; never persisted as an actual candidate/run.
    pool=[{'symbol':f'SYN{i}','market':'TEST','ranking_score':90-i,
           'alpha_score':80,'risk_score':20,'action':'BUY_CANDIDATE'} for i in range(4)]
    risk={'available_at':now.isoformat(),'answers':{'relevance':{'label':'direct'},
          'evidence_sufficiency':{'label':'sufficient'},'audit_concern':{'label':'yes','quote':'synthetic audit concern'}}}
    checked,comparison=m.apply(pool,now=now,decisions={('TEST','SYN0'):risk},enabled=True)
    assert comparison['before_top3']==['SYN0','SYN1','SYN2']
    assert comparison['after_top3']==['SYN1','SYN2','SYN3']
    base=workflow._final_score(pool[0],{'verdict':{'action':'BUY'}})
    changed=workflow._final_score(checked[-1],{'verdict':{'action':'BUY'}})
    assert abs(base-changed-12)<.001
    restored,_=m.apply(checked,enabled=False)
    assert restored[0]['symbol']=='SYN0' and restored[0]['action']=='BUY_CANDIDATE'
    result={'status':'passed','checked_at':now.isoformat(),'scanner_run_id':run['id'],
            'actual_scanner':run['semantic_ranking'],'candidate_count':run['candidate_count'],
            'counterfactual_fixture':comparison,'fixture_final_score_penalty':base-changed,
            'paid_reranker_enabled':False,'profit_uplift_measured':False}
    write_json_atomic(args.output,result)
    print(json.dumps(result,ensure_ascii=True))

if __name__=='__main__': main()

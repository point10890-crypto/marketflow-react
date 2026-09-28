"""Explicit paid smoke validation on six synthetic, labeled Korean examples."""
import argparse,json,os,sys
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
CASES=[
 ('cancel','가상기업A는 공급 계약 해지를 확정했다고 공시했다.',{'contract_termination':'yes','event_status':'cancelled'}),
 ('dilution','가상기업A는 신주 100만 주를 발행하는 유상증자를 결정했다고 공시했다.',{'equity_dilution':'yes','relevance':'direct'}),
 ('audit','가상기업A의 감사인은 계속기업 존속 능력에 중대한 불확실성이 있다고 명시했다.',{'audit_concern':'yes','relevance':'direct'}),
 ('conditional','가상기업A는 규제 승인이 이루어질 경우에만 내년 매출이 증가할 것으로 전망했다. 승인은 아직 받지 못했다.',{'guidance_conditional':'yes','event_status':'conditional'}),
 ('unrelated','이 기사는 가상기업B의 계약만 다루며 가상기업A와는 아무 관련이 없다고 명시한다.',{'relevance':'unrelated','contract_termination':'not_stated'}),
 ('correction','가상기업A는 이전 공급계약 공시의 금액을 잘못 기재하여 정정 공시를 제출했다.',{'correction':'yes','relevance':'direct'}),
]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file',required=True)
    parser.add_argument('--output-dir',required=True)
    args=parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(args.env_file)
    os.environ['MIROFISH_SEMANTIC_PROVIDER']='deepseek'
    os.environ['MIROFISH_SEMANTIC_LIVE_ENABLED']='true'
    from app.services.mirofish import semantic_decisions as s
    from app.utils.atomic_json import write_json_atomic
    root=Path(args.output_dir)
    # Fixed observation time makes repeated validation idempotent.
    at='2026-09-28T00:00:00+00:00'
    checks=[]
    for name,text,expected in CASES:
        candidate={'symbol':'SYN-'+name,'name':'가상기업A','market':'TEST',
            'source_packets':[{'source':'synthetic_gold_v1','evidence_id':name,'fetched_at':at,'content':{'text':text}}]}
        snapshot=s.record_snapshot([candidate],workflow_id='synthetic_gold_v1',decision_at=at,root=root)
        result=s.evaluate_snapshot(snapshot['id'],root=root)
        item=(result.get('results') or [{}])[0]
        answers=item.get('answers') or {}
        actual={k:answers.get(k,{}).get('label') for k in expected}
        checks.append({'case':name,'expected':expected,'actual':actual,
                       'pass':item.get('status')=='validated' and expected==actual,
                       'status':item.get('status'),'usage':item.get('usage')})
    report={'dataset':'synthetic_gold_v1','cases':checks,'passed':sum(c['pass'] for c in checks),
            'total':len(checks),'scope':'synthetic classification correctness, not investment performance',
            'model':s.status(root=root)['model'],'checked_at':datetime.now(timezone.utc).isoformat()}
    write_json_atomic(str(root/'report.json'),report)
    print(json.dumps(report,ensure_ascii=True))
    return 0 if report['passed']==report['total'] else 1

if __name__=='__main__': raise SystemExit(main())

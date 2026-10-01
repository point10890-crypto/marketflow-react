"""Refresh cached prospective comparison reports without network or LLM calls."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',help='Local evaluation artifact directory')
    parser.add_argument('--index-root',help='Local prepared chart index directory')
    parser.add_argument('--as-of',help='Timezone-explicit cutoff for evaluation only')
    ingestion=parser.add_mutually_exclusive_group()
    ingestion.add_argument('--ingest-latest',action='store_true',help='Capture the latest completed workflow from this KST day')
    ingestion.add_argument('--workflow-id',help='Capture a completed workflow from this KST day')
    args=parser.parse_args(argv)
    if args.as_of and (args.ingest_latest or args.workflow_id):
        parser.error('ingest cannot be combined with a backdated --as-of cutoff')
    from app.services.mirofish import chart_analogue_evaluation as service
    captured=None
    try:
        if args.ingest_latest or args.workflow_id:
            from app.services.mirofish import workflow
            current=(workflow.read_workflow(args.workflow_id) if args.workflow_id
                     else workflow.read_latest_workflow())
            if current and current.get('status')=='completed':
                captured=service.record_workflow(current,root=args.root)
        report=service.evaluate(root=args.root,as_of=args.as_of,index_root=args.index_root)
    except (OSError,ValueError,RuntimeError,KeyError,TypeError):
        print(json.dumps({'status':'unavailable','error':'chart_evaluation_failed'}))
        return 1
    print(json.dumps({'status':report['status'],'evaluated_at':report['evaluated_at'],
                      'counts':report['counts'],'horizons':report['horizons'],
                      'capture_status':captured.get('status') if isinstance(captured,dict) else None},
                     ensure_ascii=True,allow_nan=False))
    return 1 if report['status']=='unavailable' else 0


if __name__=='__main__':
    raise SystemExit(main())

"""Operational CLI for snapshots, explicit Jev evaluation and offline research."""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['status', 'worker', 'snapshot', 'enrich', 'evaluate', 'export', 'train-evaluate'])
    parser.add_argument('--provider', choices=['jev', 'deepseek'])
    parser.add_argument('--input', help='JSON scanner run or labeled research rows')
    parser.add_argument('--snapshot-id')
    parser.add_argument('--output')
    parser.add_argument('--train-before')
    parser.add_argument('--test-from')
    parser.add_argument('--as-of')
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    if args.provider:
        os.environ['MIROFISH_SEMANTIC_PROVIDER'] = args.provider
    from app.services.mirofish import semantic_decisions as service
    from app.utils.atomic_json import write_json_atomic
    if args.command == 'status':
        result = service.status()
    elif args.command == 'worker':
        from app.services.mirofish.semantic_worker import run_once
        result = run_once()
    elif args.command == 'snapshot':
        if not args.input:
            parser.error('--input is required')
        run = json.loads(Path(args.input).read_text(encoding='utf-8-sig'))
        result = service.record_snapshot(run['candidates'], workflow_id='import:' + str(run['id']),
                                         decision_at=run.get('generated_at') or run.get('created_at'))
    elif args.command == 'enrich':
        if not args.snapshot_id:
            parser.error('--snapshot-id is required')
        from app.services.mirofish.semantic_sources import enrich_snapshot
        result = enrich_snapshot(args.snapshot_id)
    elif args.command == 'evaluate':
        if not args.snapshot_id:
            parser.error('--snapshot-id is required')
        result = service.evaluate_snapshot(args.snapshot_id)
    elif args.command == 'export':
        if not args.snapshot_id or not args.output:
            parser.error('--snapshot-id and --output are required')
        snapshot = service.read_snapshot(args.snapshot_id)
        evaluation = service.read_evaluation(args.snapshot_id)
        result = {'snapshot_id': args.snapshot_id, 'rows': []}
        candidates = {(c['market'], c['symbol']): c for c in snapshot['candidates']}
        for item in evaluation.get('results', []):
            c = candidates[(item['market'], item['symbol'])]
            result['rows'].append({'symbol': c['symbol'], 'market': c['market'],
                'decision_at': snapshot['decision_at'], 'available_at': snapshot['decision_at'],
                'event_id': service._hash(service.evidence_event_ids(c)),
                'event_ids': service.evidence_event_ids(c), 'features': {
                    'alpha': c.get('alpha_score'), 'risk': c.get('risk_score'), **(item.get('features') or {})},
                'semantic_status': item['status'], 'baseline_score': c.get('ranking_score'),
                'label_end_at': None, 'gross_return': None, 'benchmark_return': None,
                'cost_bps': None, 'execution_status': 'unlabeled'})
    else:
        if not all((args.input, args.output, args.train_before, args.test_from, args.as_of)):
            parser.error('input/output/train-before/test-from/as-of are required')
        from app.services.mirofish.semantic_research import train_evaluate
        data = json.loads(Path(args.input).read_text(encoding='utf-8-sig'))
        result = train_evaluate(data['rows'], train_before=args.train_before,
                                test_from=args.test_from, as_of=args.as_of)
    if args.output:
        write_json_atomic(args.output, result)
        print(json.dumps({'output': args.output, 'status': result.get('status', 'written')}, ensure_ascii=False))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

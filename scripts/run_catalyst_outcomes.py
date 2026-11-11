"""Refresh the latest due 10:00/15:00 KST historical-catalyst research slot."""
import argparse
import json
from pathlib import Path
import time


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path)
    parser.add_argument('--project-root',type=Path)
    args=parser.parse_args(argv)
    project=args.project_root or Path(__file__).resolve().parents[1]
    try:
        from dotenv import load_dotenv
        load_dotenv(project/'.env',override=False)
        from app.services.catalyst_outcomes import service
        result=service.run_once(root=args.root or service.ROOT,project_root=project,deadline=time.monotonic()+180)
        print(json.dumps(dict(status=result['status'],generated_at=result['generated_at'],
                              coverage=result['coverage'],candidate_count=len(result['candidates']),
                              operation=result['operation']),ensure_ascii=True))
        return 1 if result['status']=='failed' else 0
    except Exception:
        print('{"status":"failed","error":"catalyst_outcomes_unavailable"}')
        return 1


if __name__=='__main__':
    raise SystemExit(main())

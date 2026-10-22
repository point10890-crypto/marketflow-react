"""Run the fixed, costed research tournament and freeze prospective watchlists."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

from filelock import FileLock, Timeout

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.mirofish.alpha_lab import candidate_service

ROOT = candidate_service.ROOT


def scan_once(root, *, desk_only=False):
    """Own the complete CLI lifecycle, including failures before candidate work."""
    root = Path(root)
    lock = FileLock(str(root/'candidate-compose.lock'), thread_local=False)
    try:
        lock.acquire(timeout=0)
    except Timeout:
        return dict(candidate_service.store.read_status(root), state='running')
    try:
        candidates = candidate_service.candidate_store
        directory = root/'candidate-desk'
        candidates.set_attempt(directory, 'running')
        owned_attempt = candidates._load(directory/'attempt.json')
        try:
            previous = (candidate_service.store.read_status(root) if desk_only
                        else candidate_service.legacy.scan_once(root))
            if previous.get('state') in ('ready', 'held'):
                desk = candidate_service.refresh_desk(root)
                return (dict(previous, candidate_desk=desk) if desk is not None
                        else dict(previous, candidate_desk_unavailable=True))
        except Exception:
            previous = dict(state='failed', error='analysis_unavailable', report=None)
        if candidates._load(directory/'attempt.json') == owned_attempt:
            candidates.set_attempt(directory, 'failed', error='analysis_unavailable')
        return previous
    finally:
        lock.release()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT, help='Private AlphaLab artifacts and canonical input pointer')
    parser.add_argument('--desk-only', action='store_true', help='Recover only the new candidate stage after completed legacy research')
    args = parser.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1]/'.env', override=False)
    status = scan_once(args.root, desk_only=args.desk_only)
    report = status.get('report') or {}
    print(json.dumps(dict(state=status['state'], error=status['error'],
        inspected=(report.get('universe') or {}).get('inspected_count', 0),
        latest_session=report.get('latest_session'), champion=(report.get('champion') or {}).get('strategy_id'),
        candidates=[dict(symbol=row['symbol'], name=row['name'], weight=row['risk']['weight'])
                    for row in report.get('candidates', [])], forward=report.get('forward'),
        candidate_desk={key:(status.get('candidate_desk') or {}).get(key) for key in
                        ('state','decision_id','latest_session')},
        candidate_symbols=[row['symbol'] for row in (status.get('candidate_desk') or {}).get('candidates',[])]), ensure_ascii=False))
    desk = status.get('candidate_desk') or {}
    return (1 if status['state'] == 'failed' or desk.get('state') == 'failed' or status.get('candidate_desk_unavailable')
            else 2 if status['state'] == 'running' else 0)


if __name__ == '__main__':
    raise SystemExit(main())

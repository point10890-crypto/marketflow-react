"""Run the fixed, costed research tournament and freeze prospective watchlists."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import time

from filelock import FileLock, Timeout

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.mirofish.alpha_lab import candidate_service, regular_inputs, regular_service

ROOT = candidate_service.ROOT
REGULAR_RETRYABLE_FAILURES = {
    'kis_http_failure', 'kis_transport_failure', 'kis_api_failure',
    'kis_token_unavailable', 'regular_inputs_provider', 'regular_inputs_busy',
}


def scan_once(root, *, desk_only=False, regular_only=False, candidate_attempts=1):
    """Own the complete CLI lifecycle, including failures before candidate work."""
    if type(candidate_attempts) is not int or candidate_attempts not in (1, 2, 3):
        raise ValueError('candidate_attempts must be 1, 2 or 3')
    root = Path(root)
    compose = FileLock(str(root/'regular-compose.lock'), thread_local=False)
    lock = FileLock(str(root/'candidate-compose.lock'), thread_local=False)
    try:
        compose.acquire(timeout=0)
        lock.acquire(timeout=0)
    except Timeout:
        if compose.is_locked:
            compose.release()
        return dict(candidate_service.store.read_status(root), state='running')
    try:
        candidates = candidate_service.candidate_store
        directory = root/'candidate-desk'
        if regular_only:
            previous = candidate_service.store.read_status(root)
        else:
            candidates.set_attempt(directory, 'running')
            owned_attempt = candidates._load(directory/'attempt.json')
            try:
                previous = (candidate_service.store.read_status(root) if desk_only
                            else candidate_service.legacy.scan_once(root))
            except Exception:
                previous = dict(state='failed', error='analysis_unavailable', report=None)
            if previous.get('state') not in ('ready', 'held'):
                if candidates._load(directory/'attempt.json') == owned_attempt:
                    candidates.set_attempt(directory, 'failed', error='analysis_unavailable')
                candidates.set_attempt(root/'candidate-regular-v1', 'failed', error='source_unavailable')
                return previous

        daily_complete = regular_only
        result = dict(previous, candidate_desk_unavailable=True)
        for attempt in range(candidate_attempts):
            if not daily_complete:
                try:
                    desk = candidate_service.refresh_desk(root)
                except Exception:
                    candidates.set_attempt(directory, 'failed', error='analysis_unavailable')
                    desk = None
                if desk is not None and desk.get('state') == 'running':
                    return dict(previous, state='running', candidate_desk=desk)
                daily_complete = desk is not None and desk.get('state') in ('ready', 'held')
                if not daily_complete:
                    candidates.set_attempt(root/'candidate-regular-v1', 'failed', error='source_unavailable')
            if daily_complete:
                try:
                    regular = regular_service.refresh_desk(root)
                except Exception:
                    candidates.set_attempt(root/'candidate-regular-v1', 'failed', error='analysis_unavailable')
                    regular = None
                result = (dict(previous, candidate_desk=regular) if regular is not None
                          else dict(previous, candidate_desk_unavailable=True))
                if regular is not None and regular.get('state') in ('ready', 'held'):
                    return result
                if regular is not None and regular.get('state') == 'running':
                    return dict(result, state='running')
            if attempt + 1 < candidate_attempts:
                if daily_complete:
                    try:
                        pointer = candidate_service.store._read(root/'inputs'/'current.json')
                        if pointer is not None:
                            session = regular_inputs._session(pointer['latest_session'])
                            contract = candidate_service.store._hash(regular_inputs.source_contract())
                            receipt_path = root/'candidate-regular-v1'/'inputs'/'epochs'/contract/session/'attempt.json'
                            if receipt_path.exists():
                                receipt = regular_inputs._read(receipt_path)
                                failures = receipt.get('failures')
                                if (not isinstance(failures, dict) or not isinstance(receipt.get('objects'), dict)
                                        or any(code not in REGULAR_RETRYABLE_FAILURES for code in failures.values())):
                                    return result
                    except (OSError, ValueError, TypeError, KeyError):
                        return result
                time.sleep(15)
        return result
    finally:
        lock.release()
        compose.release()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT, help='Private AlphaLab artifacts and canonical input pointer')
    parser.add_argument('--desk-only', action='store_true', help='Recover only the new candidate stage after completed legacy research')
    parser.add_argument('--regular-only', action='store_true', help='Recover regular-session collection/analysis only; preserve completed upstream stages')
    parser.add_argument('--candidate-attempts', type=int, choices=(1, 2, 3), default=1,
                        help='Maximum candidate/regular stage attempts, with 15 seconds between failures')
    args = parser.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1]/'.env', override=False)
    status = scan_once(args.root, desk_only=args.desk_only, regular_only=args.regular_only,
                       candidate_attempts=args.candidate_attempts)
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

"""예측 리그 워커 CLI.

  drain              대기 중인 잡을 순서대로 실행하고 종료
  enqueue <slot>     morning / evening 잡을 큐에 넣기 (수동 실행용)
  status             잡 상태별 개수
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime

from app.services.forecast_league import clock, db
from app.services.league_worker import handlers, jobs, schedule

logger = logging.getLogger('league_worker')
MAX_JOBS_PER_RUN = 50


def _alert(message: str) -> None:
    """시스템 메시지 — 개인봇으로만 보낸다."""
    try:
        from app.utils.scheduler import _send_telegram
        _send_telegram(message, channel=False)
    except Exception:
        logger.exception('alert failed')


def drain() -> int:
    """실행한 잡 수를 반환한다."""
    ran = 0
    with db.connect() as conn:
        jobs.recover_running(conn)
        conn.commit()
        while ran < MAX_JOBS_PER_RUN:
            job = jobs.claim_next(conn)
            conn.commit()
            if job is None:
                break
            ran += 1
            try:
                result = handlers.HANDLERS[job['kind']](conn, json.loads(job['args']))
                conn.commit()
                jobs.complete(conn, job['job_id'], result)
                logger.info('job %s %s done: %s', job['job_id'], job['kind'], result)
            except Exception as error:
                conn.rollback()
                reason = f'{type(error).__name__}: {error}'
                logger.exception('job %s %s failed', job['job_id'], job['kind'])
                if jobs.fail(conn, job['job_id'], reason):
                    _alert(f"[예측 리그] 잡 실패(재시도 종료): {job['kind']} #{job['job_id']} — {reason[:200]}")
            conn.commit()
    return ran


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='python -m app.services.league_worker')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('drain')
    commands.add_parser('status')
    commands.add_parser('enqueue').add_argument('slot', choices=['morning', 'evening'])
    options = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')
    if options.command == 'drain':
        print(json.dumps({'ran': drain()}))
    elif options.command == 'enqueue':
        with db.connect() as conn:
            added = schedule.enqueue_slot(conn, options.slot, datetime.now(clock.KST).date())
        print(json.dumps({'enqueued': added}))
    else:
        with db.connect() as conn:
            print(json.dumps(jobs.counts(conn), sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())

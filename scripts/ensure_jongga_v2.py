"""오늘자 종가베팅 V2 결과가 없으면 직접 만든다 — 데몬 독립 안전망.

왜 필요한가
-----------
스케줄러 데몬은 단일 스레드 루프에서 `schedule.run_pending()` 을 **동기 실행**한다.
앞선 작업이 길어지면 14:50 슬롯이 통째로 밀리고, 밀린 것을 되찾아야 할
'놓친 스케줄 점검' 마저 같은 루프에 있어서 함께 멈춘다.

실측 2026-08-06: 점검 간격이 5분 -> 6 -> 10 -> 24 -> 36분으로 벌어지다가
14:26 이후 52분간 완전히 멈췄고, 그날 V2 는 생성되지 않았다. 하트비트는 계속
갱신되고 있었으므로 워치독도 이를 장애로 보지 않는다 — 데몬은 살아 있는데
일만 안 하는 상태였다.

기존 `MarketFlow-Jongga-Telegram-1510` 태스크는 안전망이 되지 못한다.
`scheduler.py` 를 호출하는데 데몬이 파일 락을 쥐고 있어 매번
"스케줄러 이미 실행 중" 으로 즉시 실패한다.

이 스크립트는 데몬과 락을 공유하지 않고 엔진을 직접 부른다. 이미 오늘자 결과가
있으면 아무것도 하지 않으므로 정상 동작한 날의 비용은 0 이다.

사용:
  python scripts/ensure_jongga_v2.py           # 없으면 생성
  python scripts/ensure_jongga_v2.py --force   # 있어도 다시 생성
  python scripts/ensure_jongga_v2.py --check   # 판정만 (생성 안 함)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import date, datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

DATA_DIR = os.path.join(BASE_DIR, 'data')
# 결과가 이 시각 이전 것이면 '오늘 것' 이어도 낡은 것으로 본다. 장 마감(15:30)
# 전에 만들어진 결과는 종가 기준이 아니다.
MIN_SIGNALS = 1


def artifact_path(target: date) -> str:
    return os.path.join(DATA_DIR, f'jongga_v2_results_{target:%Y%m%d}.json')


def is_trading_day(target: date) -> bool:
    """주말·휴장일이면 False. 스케줄러의 판정기를 그대로 쓴다."""
    if target.weekday() >= 5:
        return False
    try:
        from scheduler import _is_kr_trading_day_for_scheduler
        return bool(_is_kr_trading_day_for_scheduler(datetime.combine(target, datetime.min.time())))
    except Exception:
        return True   # 판정기를 못 부르면 평일은 거래일로 본다 (누락보다 중복이 낫다)


def existing_result(target: date) -> dict | None:
    """오늘자 결과가 '쓸 수 있는 상태로' 있으면 반환. 없거나 비었으면 None."""
    path = artifact_path(target)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    signals = payload.get('signals')
    if not isinstance(signals, list) or len(signals) < MIN_SIGNALS:
        return None      # 빈 껍데기 파일은 '있음' 으로 치지 않는다
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description='종가베팅 V2 안전망')
    parser.add_argument('--force', action='store_true', help='결과가 있어도 다시 생성')
    parser.add_argument('--check', action='store_true', help='판정만 하고 생성하지 않음')
    parser.add_argument('--date', help='기준일 YYYY-MM-DD (기본: 오늘)')
    args = parser.parse_args()

    target = date.fromisoformat(args.date) if args.date else date.today()
    stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    if not is_trading_day(target):
        print(f'[{stamp}] {target} 은 거래일이 아님 — 종료')
        return 0

    existing = existing_result(target)
    if existing and not args.force:
        print(f'[{stamp}] {target} 결과 이미 있음 '
              f'(시그널 {len(existing.get("signals") or [])}개) — 실행 안 함')
        return 0

    reason = '강제 재생성' if args.force else '결과 없음'
    print(f'[{stamp}] {target} {reason} — V2 엔진 직접 실행')
    if args.check:
        print('  --check 모드이므로 실행하지 않음')
        return 1        # 누락 상태임을 종료코드로 알린다

    from engine.generator import run_screener
    try:
        asyncio.run(run_screener(capital=50_000_000, markets=['KOSPI', 'KOSDAQ'],
                                 target_date=target))
    except Exception as exc:
        import traceback
        print(f'[FAIL] {type(exc).__name__}: {exc}')
        traceback.print_exc()
        return 1

    produced = existing_result(target)
    if not produced:
        print('[FAIL] 엔진은 끝났는데 결과 파일이 없다')
        return 1

    signals = produced.get('signals') or []
    grades = {}
    for s in signals:
        grades[s.get('grade')] = grades.get(s.get('grade'), 0) + 1
    print(f'[OK] 시그널 {len(signals)}개  '
          f'{" ".join(f"{g}:{n}" for g, n in sorted(grades.items()) if g)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

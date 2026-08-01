"""Goodrich 랭커 비교 실행.

사용:
  python scripts/run_goodrich_backtest.py --horizon 3
  python scripts/run_goodrich_backtest.py --horizon 3 --segment holdout
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from app.services.mirofish.goodrich_backtest import engine, prices, rankers  # noqa: E402
from app.services.mirofish.intelligence import regime  # noqa: E402

HOLDOUT_START = '2025-09-04'  # 사용 가능 545세션의 75% 지점


def main() -> int:
    parser = argparse.ArgumentParser(description='Goodrich 랭커 비교')
    parser.add_argument('--horizon', type=int, default=3, help='보유 세션 수 (기본 3)')
    parser.add_argument('--top-k', type=int, default=3, help='진입일당 픽 수 (기본 3)')
    parser.add_argument('--segment', choices=('train', 'holdout', 'all'), default='all')
    parser.add_argument('--regime', choices=('any', 'RISK_ON', 'NEUTRAL', 'RISK_OFF'),
                        default='any', help='해당 레짐의 진입일만 (기본 any)')
    parser.add_argument('--out', default=os.path.join(BASE_DIR, 'data', 'goodrich_backtest_result.json'))
    args = parser.parse_args()

    started = time.time()
    book = prices.load_prices()
    if not book.sessions:
        print('daily_prices.csv 를 읽지 못했습니다.')
        return 1

    usable = book.usable_sessions()
    train, holdout = engine.split_dates(usable, holdout_start=HOLDOUT_START)
    # 'all' 도 usable 기준이다. 원시 book.sessions 를 쓰면 장중수집 과반 세션이
    # 다시 섞여 들어와 train/holdout 과 다른 데이터로 판정하게 된다.
    dates = {'train': train, 'holdout': holdout, 'all': usable}[args.segment]

    # 레짐 필터는 구간을 자른 뒤 적용한다 — holdout 은 어떤 경우에도 후보 선정에
    # 쓰이지 않아야 하므로 레짐 분해도 구간 안에서만 이뤄진다.
    if args.regime != 'any':
        timeline = regime.read_regime_timeline()
        if not timeline:
            print('레짐 타임라인이 없습니다. regime.build_regime_timeline() 을 먼저 실행하세요.')
            return 1
        before = len(dates)
        dates = [d for d in dates if regime.classify_regime(d, timeline) == args.regime]
        print(f'레짐 필터 {args.regime}: {before}일 -> {len(dates)}일')
        if not dates:
            print('해당 레짐의 진입일이 없습니다.')
            return 1

    print(f'세션 {len(book.sessions)}일 중 사용가능 {len(usable)}일 '
          f'| 대상 구간 {args.segment} {len(dates)}일 '
          f'| 레짐 {args.regime} | horizon T+{args.horizon} | top{args.top_k}')

    # baseline 은 구간·horizon 이 같으면 challenger 마다 동일하다. 한 번만 돌린다.
    baseline = engine.run_ranker(
        'baseline_current', dates, book, top_k=args.top_k, horizon=args.horizon,
    )

    results = []
    for name in rankers.RANKERS:
        if name == 'baseline_current':
            continue
        result = engine.compare(
            name, dates, book,
            top_k=args.top_k, horizon=args.horizon, baseline=baseline,
        )
        results.append(result)
        ci = result['diff_ci95']
        ci_text = f"[{ci[0]:+.3f}, {ci[1]:+.3f}]" if ci else 'n/a'
        print(f"  {name:18} 진입일 {result['entry_days']:>4}  "
              f"신규 {result['challenger_mean_excess_pct']}%  "
              f"baseline {result['baseline_mean_excess_pct']}%  "
              f"차이95%CI {ci_text}  -> {result['verdict']}")

    payload = {
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'segment': args.segment,
        'regime': args.regime,
        'horizon_days': args.horizon,
        'top_k': args.top_k,
        'session_count': len(dates),
        'results': results,
        'elapsed_sec': round(time.time() - started, 1),
    }
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f'저장: {args.out}  ({payload["elapsed_sec"]}s)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

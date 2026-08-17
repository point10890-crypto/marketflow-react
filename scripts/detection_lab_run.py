# -*- coding: utf-8 -*-
"""Detection Alpha Lab 실측 러너 — miniPC(실데이터)에서 실행.

과거 워크플로우의 CIO BUY 검출 전체를 리플레이해 현행 규칙(baseline)과
변형(레짐 게이트 / Stage2 필터 / ATR 청산 / 조합)의 실측 성과를 비교한다.

    python scripts/detection_lab_run.py
    → data/admin_mirofish/detection_lab/report_<ts>.json + 콘솔 요약표

읽기 전용 — 라이브 원장/검출에 영향 없음.
"""
from __future__ import annotations

import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.services.mirofish import detection_lab as dl  # noqa: E402

DAILY_PRICES_CSV = BASE_DIR / 'data' / 'daily_prices.csv'
OUT_DIR = BASE_DIR / 'data' / 'admin_mirofish' / 'detection_lab'


def load_series(symbols: set[str]) -> dict[str, list[dict]]:
    series: dict[str, list[dict]] = {s: [] for s in symbols}
    with open(DAILY_PRICES_CSV, 'r', encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            ticker = (row.get('ticker') or '').strip()
            if ticker not in series:
                continue
            try:
                series[ticker].append({
                    'date': (row.get('date') or '').strip(),
                    'open': float(row.get('open') or 0),
                    'high': float(row.get('high') or 0),
                    'low': float(row.get('low') or 0),
                    'close': float(row.get('current_price') or 0),
                })
            except (TypeError, ValueError):
                continue
    for rows in series.values():
        rows.sort(key=lambda r: r['date'])
    return series


RULESETS = [
    dl.RuleSet(name='baseline'),
    dl.RuleSet(name='V1_regime_gate', regime_gate=True),
    dl.RuleSet(name='V2_stage2', stage2_filter=True),
    dl.RuleSet(name='V3_atr_exit', exit_mode='atr'),
    dl.RuleSet(name='V1+V2', regime_gate=True, stage2_filter=True),
    dl.RuleSet(name='V1+V2+V3', regime_gate=True, stage2_filter=True, exit_mode='atr'),
]


def main() -> int:
    detections = dl.collect_historical_detections()
    print(f'과거 검출: {len(detections)}건 '
          f'({detections[0]["date"] if detections else "-"} ~ {detections[-1]["date"] if detections else "-"})')
    if not detections:
        return 1

    symbols = {d['symbol'] for d in detections}
    print(f'심볼 {len(symbols)}종 가격 로드 중...')
    series = load_series(symbols)
    covered = sum(1 for s in symbols if series.get(s))
    print(f'가격 커버리지: {covered}/{len(symbols)}')

    phases = dl.phase_timeline()
    print(f'국면 타임라인: {len(phases)}일')

    results = {}
    rows = []
    for rules in RULESETS:
        out = dl.replay(detections, series, rules, phase_by_date=phases)
        m = out['metrics']
        results[rules.name] = out
        rows.append((rules.name, m))
        print(f"\n=== {rules.name} ===")
        print(f"  trades={m['trades']}  win={m['win_rate_pct']}%  "
              f"expectancy={m['expectancy_pct']:+.2f}%  median={m['median_pct']:+.2f}%")
        print(f"  PF={m['profit_factor']}  cumulative={m['cumulative_pct']:+.1f}%  "
              f"MDD={m['max_drawdown_pct']:.1f}%  hold={m['avg_holding_days']}d")
        print(f"  exits={m['by_exit_reason']}  skipped: filter={m['skipped_by_filter']} "
              f"no_data={m['skipped_no_data']}")
        for phase, stats in sorted(m.get('by_phase', {}).items()):
            print(f"    [{phase}] n={stats['trades']} win={stats['win_rate_pct']}% "
                  f"exp={stats['expectancy_pct']:+.2f}%")

    # 요약 비교표
    print('\n' + '=' * 76)
    print(f"{'ruleset':<16}{'n':>5}{'win%':>7}{'exp%':>8}{'PF':>6}{'cum%':>9}{'MDD%':>8}")
    for name, m in rows:
        pf = m['profit_factor'] if m['profit_factor'] is not None else '-'
        print(f"{name:<16}{m['trades']:>5}{m['win_rate_pct']:>7.1f}{m['expectancy_pct']:>8.2f}"
              f"{pf:>6}{m['cumulative_pct']:>9.1f}{m['max_drawdown_pct']:>8.1f}")

    # 육안 검증용 샘플 — baseline 최고/최악 10건
    base_trades = sorted(results['baseline']['trades'], key=lambda t: t['return_pct'])
    print('\n--- baseline 최악 10 (육안 검증) ---')
    for t in base_trades[:10]:
        print(f"  {t['detected_date']} {t['name']:<14} {t['return_pct']:+7.2f}% "
              f"{t['exit_reason']:<7} phase={t.get('phase')}")
    print('--- baseline 최고 10 ---')
    for t in base_trades[-10:]:
        print(f"  {t['detected_date']} {t['name']:<14} {t['return_pct']:+7.2f}% "
              f"{t['exit_reason']:<7} phase={t.get('phase')}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    out_path = OUT_DIR / f'report_{ts}.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump({
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'detections': len(detections),
            'results': {name: out for name, out in results.items()},
        }, f, ensure_ascii=False, indent=1)
    print(f'\n리포트 저장: {out_path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

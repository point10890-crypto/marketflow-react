# -*- coding: utf-8 -*-
"""Detection Alpha Lab 실측 러너 — miniPC(실데이터)에서 실행.

과거 워크플로우의 CIO BUY 검출 전체를 리플레이해 현행 규칙(baseline)과
변형(레짐 게이트 / Stage2 필터 / ATR 청산 / 조합)의 실측 성과를 비교한다.

    python scripts/detection_lab_run.py
    → data/admin_mirofish/detection_lab/report_<ts>.json + 콘솔 요약표

읽기 전용 — 라이브 원장/검출에 영향 없음.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
# The harness contract permits exactly one filesystem mutation: its report.
# Imported modules therefore must not create/update bytecode caches.
sys.dont_write_bytecode = True

from app.services.mirofish import detection_lab as dl  # noqa: E402
from app.services.mirofish.intelligence import regime  # noqa: E402
from app.utils.atomic_json import write_json_atomic  # noqa: E402

DAILY_PRICES_CSV = BASE_DIR / 'data' / 'daily_prices.csv'
REGIME_TIMELINE_JSON = Path(regime.REGIME_TIMELINE_PATH)
OUT_DIR = BASE_DIR / 'data' / 'admin_mirofish' / 'detection_lab'
REPORT_SCHEMA_VERSION = 'mirofish.detection_lab.report.v2'
MIN_PHASE_COVERAGE = 0.95
MIN_PRICE_COVERAGE = 0.95


def load_series(symbols: set[str], *, path=DAILY_PRICES_CSV,
                return_quality: bool = False):
    """Load deduplicated OHLC series for the validation universe.

    The source file is scanned once and rows are selected through the same
    deterministic latest-valid policy used by the regime builder.
    """
    series: dict[str, list[dict]] = {s: [] for s in symbols}
    rows, quality = regime.load_deduplicated_daily_rows(
        path,
        symbols=symbols,
        required_price_fields=('open', 'high', 'low', 'current_price'),
    )
    for row in rows:
        ticker = row['ticker']
        series[ticker].append({
            'date': row['date'],
            'open': float(row['open']),
            'high': float(row['high']),
            'low': float(row['low']),
            'close': float(row['current_price']),
        })
    return (series, quality) if return_quality else series


RULESETS = [
    dl.RuleSet(name='baseline'),
    dl.RuleSet(name='V1_regime_gate', regime_gate=True),
    dl.RuleSet(name='V2_stage2', stage2_filter=True),
    dl.RuleSet(name='V3_atr_exit', exit_mode='atr'),
    dl.RuleSet(name='V1+V2', regime_gate=True, stage2_filter=True),
    dl.RuleSet(name='V1+V2+V3', regime_gate=True, stage2_filter=True, exit_mode='atr'),
]


def _sha256_file(path: Path) -> dict:
    result = {'path': _relative_path(path), 'exists': path.is_file(), 'sha256': None, 'bytes': None}
    if not path.is_file():
        return result
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    result['sha256'] = digest.hexdigest()
    result['bytes'] = path.stat().st_size
    return result


def _relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(BASE_DIR.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _canonical_hash(value) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def _git_metadata() -> dict:
    metadata = {'revision': None, 'tracked_worktree_dirty': None}
    try:
        revision = subprocess.run(
            ['git', 'rev-parse', 'HEAD'], cwd=BASE_DIR, capture_output=True,
            text=True, check=True, timeout=10,
        )
        metadata['revision'] = revision.stdout.strip() or None
        status = subprocess.run(
            ['git', 'status', '--porcelain', '--untracked-files=no'], cwd=BASE_DIR,
            capture_output=True, text=True, check=True, timeout=20,
        )
        metadata['tracked_worktree_dirty'] = bool(status.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return metadata


def _regime_input_metadata(path: Path = REGIME_TIMELINE_JSON) -> dict:
    metadata = _sha256_file(path)
    metadata.update({'schema_version': None, 'method_version': None,
                     'max_data_date': None, 'data_quality': None})
    if not path.is_file():
        return metadata
    try:
        timeline = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError, UnicodeError):
        metadata['read_error'] = 'invalid_json'
        return metadata
    by_date = timeline.get('by_date') if isinstance(timeline, dict) else {}
    by_date = by_date if isinstance(by_date, dict) else {}
    metadata.update({
        'schema_version': timeline.get('schema_version'),
        'method_version': timeline.get('method_version'),
        'max_data_date': max(by_date) if by_date else None,
        'data_quality': timeline.get('data_quality'),
    })
    return metadata


def coverage_summary(detections: list[dict], symbols: set[str],
                     series: dict[str, list[dict]], phases: dict[str, str]) -> dict:
    symbol_total = len(symbols)
    covered_symbols = sum(1 for symbol in symbols if series.get(symbol))
    detection_total = len(detections)
    entry_covered = 0
    for detection in detections:
        detection_date = str(detection.get('date') or '')
        bars = series.get(str(detection.get('symbol') or '')) or []
        if any(str(bar.get('date') or '') > detection_date for bar in bars):
            entry_covered += 1
    return {
        'price_symbols': {
            'total': symbol_total,
            'covered': covered_symbols,
            'coverage_ratio': round(covered_symbols / symbol_total, 6) if symbol_total else 0.0,
        },
        'price_detections_with_future_bar': {
            'total': detection_total,
            'covered': entry_covered,
            'coverage_ratio': round(entry_covered / detection_total, 6) if detection_total else 0.0,
        },
        'phase': dl.phase_coverage(detections, phases),
    }


def validate_coverage(coverage: dict, *, min_phase=MIN_PHASE_COVERAGE,
                      min_price=MIN_PRICE_COVERAGE) -> dict:
    checks = {
        'phase_coverage': {
            'value': float((coverage.get('phase') or {}).get('coverage_ratio') or 0),
            'minimum': float(min_phase),
        },
        'price_detection_coverage': {
            'value': float((coverage.get('price_detections_with_future_bar') or {}).get('coverage_ratio') or 0),
            'minimum': float(min_price),
        },
    }
    failed = []
    for name, check in checks.items():
        check['passed'] = check['value'] >= check['minimum']
        if not check['passed']:
            failed.append(name)
    return {
        'status': 'passed' if not failed else 'failed',
        'eligible_for_policy_decision': not failed,
        'fail_closed': True,
        'failed_checks': failed,
        'checks': checks,
    }


def build_manifest(*, detections: list[dict], symbols: set[str],
                   series: dict[str, list[dict]], phases: dict[str, str],
                   price_quality: dict, rulesets=None,
                   daily_prices_path: Path = DAILY_PRICES_CSV,
                   regime_timeline_path: Path = REGIME_TIMELINE_JSON) -> dict:
    coverage = coverage_summary(detections, symbols, series, phases)
    validation = validate_coverage(coverage)
    selected_rulesets = rulesets or RULESETS
    return {
        'method_version': dl.DETECTION_LAB_METHOD_VERSION,
        'git': _git_metadata(),
        'inputs': {
            'daily_prices': _sha256_file(Path(daily_prices_path)),
            'regime_timeline': _regime_input_metadata(Path(regime_timeline_path)),
            'detections': {
                'records': len(detections),
                'sha256': _canonical_hash(detections),
                'min_date': min((str(item.get('date') or '') for item in detections), default=None),
                'max_date': max((str(item.get('date') or '') for item in detections), default=None),
            },
        },
        'max_data_date': price_quality.get('max_data_date'),
        'coverage': coverage,
        'duplicate_stats': price_quality,
        'rulesets': [asdict(rules) for rules in selected_rulesets],
        'live_phase_gate_blocked': sorted(dl.live_phase_gate_blocked()),
        'validation': validation,
    }


def main() -> int:
    detections = dl.collect_historical_detections()
    print(f'과거 검출: {len(detections)}건 '
          f'({detections[0]["date"] if detections else "-"} ~ {detections[-1]["date"] if detections else "-"})')
    if not detections:
        return 1

    symbols = {d['symbol'] for d in detections}
    print(f'심볼 {len(symbols)}종 가격 로드 중...')
    series, price_quality = load_series(symbols, return_quality=True)
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
        net = m.get('net') or {}
        print(f"\n=== {rules.name} ===")
        print(f"  trades={m['trades']}  win={m['win_rate_pct']}%  "
              f"expectancy={m['expectancy_pct']:+.2f}%  median={m['median_pct']:+.2f}%")
        print(f"  PF={m['profit_factor']}  cumulative={m['cumulative_pct']:+.1f}%  "
              f"MDD={m['max_drawdown_pct']:.1f}%  hold={m['avg_holding_days']}d")
        if net:
            print(f"  [net -{net['round_trip_cost_pct']}%] win={net['win_rate_pct']}%  "
                  f"expectancy={net['expectancy_pct']:+.2f}%  PF={net['profit_factor']}  "
                  f"cumulative={net['cumulative_pct']:+.1f}%")
        print(f"  exits={m['by_exit_reason']}  skipped: filter={m['skipped_by_filter']} "
              f"no_data={m['skipped_no_data']}")
        for phase, stats in sorted(m.get('by_phase', {}).items()):
            print(f"    [{phase}] n={stats['trades']} win={stats['win_rate_pct']}% "
                  f"exp={stats['expectancy_pct']:+.2f}% PF={stats['profit_factor']}")

    # 요약 비교표 (gross | net)
    print('\n' + '=' * 96)
    print(f"{'ruleset':<16}{'n':>5}{'win%':>7}{'exp%':>8}{'PF':>6}{'cum%':>9}{'MDD%':>8}"
          f"{'n.win%':>8}{'n.exp%':>8}{'n.PF':>7}")
    for name, m in rows:
        pf = m['profit_factor'] if m['profit_factor'] is not None else '-'
        net = m.get('net') or {}
        npf = net.get('profit_factor') if net.get('profit_factor') is not None else '-'
        print(f"{name:<16}{m['trades']:>5}{m['win_rate_pct']:>7.1f}{m['expectancy_pct']:>8.2f}"
              f"{pf:>6}{m['cumulative_pct']:>9.1f}{m['max_drawdown_pct']:>8.1f}"
              f"{net.get('win_rate_pct', 0):>8.1f}{net.get('expectancy_pct', 0):>8.2f}{npf:>7}")

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

    manifest = build_manifest(
        detections=detections,
        symbols=symbols,
        series=series,
        phases=phases,
        price_quality=price_quality,
    )
    validation = manifest['validation']
    phase_coverage = manifest['coverage']['phase']['coverage_ratio']
    price_coverage = manifest['coverage']['price_detections_with_future_bar']['coverage_ratio']
    print(f'검증 커버리지: phase={phase_coverage:.1%} price={price_coverage:.1%}')
    print(f"검증 판정: {validation['status']} (fail_closed=true)")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc)
    ts = generated_at.strftime('%Y%m%d_%H%M%S_%f')
    out_path = OUT_DIR / f'report_{ts}.json'
    write_json_atomic(out_path, {
        'schema_version': REPORT_SCHEMA_VERSION,
        'method_version': dl.DETECTION_LAB_METHOD_VERSION,
        'generated_at': generated_at.isoformat(),
        'detections': len(detections),
        'manifest': manifest,
        'validation': validation,
        'results': {name: out for name, out in results.items()},
    }, sort_keys=False)
    print(f'\n리포트 저장: {out_path}')
    if not validation['eligible_for_policy_decision']:
        print('커버리지 기준 미달: 결과를 정책 근거로 사용할 수 없습니다.')
        return 2
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# 확장 그리드 — 1차 실측에서 드러난 가설 검증용
#   (승률 37% × (+8/-7) 은 수학적으로 음수 기대값 — 비대칭/필터가 레버)
# ─────────────────────────────────────────────────────────────────────────────

def extended_rulesets():
    import copy
    out = []
    # 손익 비대칭 그리드
    for tgt, stp in [(12, 7), (16, 8), (10, 10), (20, 10), (8, 10), (15, 12)]:
        out.append(dl.RuleSet(name=f'T{tgt}/S{stp}', target_pct=tgt, stop_pct=stp))
    # 손절 없음 (만료-only) — 손절이 알파를 죽이는지 분리 검증
    out.append(dl.RuleSet(name='no_stop_hold8', stop_pct=99.0))
    out.append(dl.RuleSet(name='no_stop_hold15', stop_pct=99.0, max_hold_days=15))
    # 점수 컷 (extra['min_score'] 는 main2 에서 검출 필터로 적용)
    for cut in (65, 70, 75):
        rs = dl.RuleSet(name=f'score>={cut}')
        rs.extra['min_score'] = cut
        out.append(rs)
    # 레짐 게이트 (타임라인 생성 후 유효)
    out.append(dl.RuleSet(name='V1_regime_gate', regime_gate=True))
    out.append(dl.RuleSet(name='V1+T16/S8', regime_gate=True, target_pct=16, stop_pct=8))
    out.append(dl.RuleSet(name='V1+no_stop', regime_gate=True, stop_pct=99.0))
    return out


def main2() -> int:
    """확장 그리드 실행 (main 과 동일 데이터, 변형만 확대)."""
    detections = dl.collect_historical_detections()
    symbols = {d['symbol'] for d in detections}
    series = load_series(symbols)
    phases = dl.phase_timeline()
    print(f'검출 {len(detections)} · 국면 타임라인 {len(phases)}일')

    rows = []
    for rules in extended_rulesets():
        dets = detections
        if rules.extra.get('min_score'):
            dets = [d for d in detections
                    if isinstance(d.get('score'), (int, float))
                    and d['score'] >= rules.extra['min_score']]
        out = dl.replay(dets, series, rules, phase_by_date=phases)
        m = out['metrics']
        rows.append((rules.name, m))

    print(f"{'ruleset':<16}{'n':>5}{'win%':>7}{'exp%':>8}{'PF':>6}{'cum%':>9}{'MDD%':>8}{'hold':>6}")
    for name, m in rows:
        pf = m['profit_factor'] if m['profit_factor'] is not None else 0
        print(f"{name:<16}{m['trades']:>5}{m['win_rate_pct']:>7.1f}{m['expectancy_pct']:>8.2f}"
              f"{pf:>6.2f}{m['cumulative_pct']:>9.1f}{m['max_drawdown_pct']:>8.1f}"
              f"{m['avg_holding_days']:>6.1f}")
    # 국면별 분해 (baseline 재계산)
    base = dl.replay(detections, series, dl.RuleSet(), phase_by_date=phases)
    print('\nbaseline 국면별:')
    for phase, stats in sorted(base['metrics'].get('by_phase', {}).items()):
        print(f"  [{phase}] n={stats['trades']} win={stats['win_rate_pct']}% exp={stats['expectancy_pct']:+.2f}%")
    return 0


if __name__ == '__main__':
    sys.exit(main2() if '--grid' in sys.argv else main())

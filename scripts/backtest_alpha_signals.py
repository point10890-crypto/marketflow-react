#!/usr/bin/env python3
"""Backtest MiroFish alpha scanner candidates without look-ahead bias."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from datetime import datetime, timezone
from typing import Any


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
DEFAULT_SCANNER_ROOT = os.path.join(REPO_ROOT, 'data', 'admin_mirofish', 'scanner_runs')
DEFAULT_PRICES = os.path.join(REPO_ROOT, 'data', 'daily_prices.csv')
DEFAULT_OUTPUT = os.path.join(REPO_ROOT, 'data', 'admin_mirofish', 'alpha_backtest_daily.json')
DEFAULT_ROLLING_OUTPUT = os.path.join(REPO_ROOT, 'data', 'admin_mirofish', 'alpha_backtest_rolling_7d.json')
SUCCESS_THRESHOLDS = {
    'expectancy_r_min': 0.30,
    'information_coefficient_min': 0.08,
    'profit_factor_min': 1.50,
    'sample_count_min': 100,
    'delta_expectancy_r_min': 0.10,
    'delta_information_coefficient_min': 0.03,
}


def evaluate_runs(
    *,
    scanner_root: str = DEFAULT_SCANNER_ROOT,
    prices_path: str = DEFAULT_PRICES,
    horizon_days: int = 5,
    limit_runs: int | None = None,
) -> dict[str, Any]:
    price_dates = _load_price_dates(prices_path)
    mature_cutoff_date = _mature_cutoff_date(price_dates, horizon_days)
    runs = _load_runs(
        scanner_root,
        limit_runs=limit_runs,
        mature_cutoff_date=mature_cutoff_date,
    )
    candidates = []
    needed_symbols: set[str] = set()
    for run in runs:
        for candidate in run.get('candidates') or []:
            if not isinstance(candidate, dict):
                continue
            if candidate.get('action') not in {'BUY_CANDIDATE', 'WATCH'}:
                continue
            symbol = _symbol(candidate.get('symbol'))
            if not symbol:
                continue
            candidates.append((run, candidate))
            needed_symbols.add(symbol)

    prices = _load_prices(prices_path, symbols=needed_symbols)
    baseline = []
    plan_a = []
    skipped = 0
    seen_signals: set[tuple[str, str, str]] = set()
    for run, candidate in candidates:
        sample = _sample(candidate, prices, horizon_days)
        if not sample:
            skipped += 1
            continue
        signal_key = (
            str(sample.get('symbol') or ''),
            str(sample.get('entry_date') or ''),
            str(candidate.get('action') or ''),
        )
        if signal_key in seen_signals:
            continue
        seen_signals.add(signal_key)
        sample['run_id'] = run.get('id')
        sample['generated_at'] = run.get('generated_at') or run.get('created_at')
        baseline.append(sample)
        if _passes_plan_a(candidate):
            plan_a.append(sample)

    baseline_metrics = _metrics(baseline)
    plan_a_metrics = _metrics(plan_a)
    delta = _metric_delta(baseline_metrics, plan_a_metrics)
    plan_a_success = (
        plan_a_metrics['thresholds_met']['expectancy_r']
        and plan_a_metrics['thresholds_met']['information_coefficient']
        and plan_a_metrics['thresholds_met']['sample_count']
        and delta['expectancy_r'] >= SUCCESS_THRESHOLDS['delta_expectancy_r_min']
        and delta['information_coefficient'] >= SUCCESS_THRESHOLDS['delta_information_coefficient_min']
    )
    return {
        'schema_version': 'mirofish.alpha_backtest.v1',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'horizon_days': int(horizon_days),
        'mature_cutoff_date': mature_cutoff_date,
        'price_date_count': len(price_dates),
        'run_count': len(runs),
        'skipped_pending_or_missing': skipped,
        'baseline': baseline_metrics,
        'enhanced': plan_a_metrics,
        'plan_a_false_signal_filter': plan_a_metrics,
        'delta': delta,
        'plan_a_success': bool(plan_a_success),
        'success_thresholds': SUCCESS_THRESHOLDS,
        'lookahead_safe': True,
        'notes': [
            'Entry date is the scanner candidate price date.',
            'Forward return uses only later daily_prices rows by ticker/date order.',
            'Plan A excludes candidates that fail stored false-signal gates when those gates exist.',
            'Duplicate scanner repeats are counted once per symbol, entry date, and action.',
        ],
    }


def write_report(report: dict[str, Any], output_path: str = DEFAULT_OUTPUT) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


def write_rolling_report(
    *,
    current_report: dict[str, Any] | None = None,
    output_path: str = DEFAULT_ROLLING_OUTPUT,
    daily_report_dir: str | None = None,
    window: int = 7,
) -> dict[str, Any]:
    root = daily_report_dir or os.path.dirname(os.path.abspath(output_path))
    reports = []
    for path in sorted(_daily_report_paths(root))[-max(1, int(window)):]:
        try:
            with open(path, 'r', encoding='utf-8-sig') as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if isinstance(payload, dict):
            reports.append(payload)
    if current_report:
        reports.append(current_report)
    reports = reports[-max(1, int(window)):]
    enhanced = [report.get('enhanced') or report.get('plan_a_false_signal_filter') or {} for report in reports]
    rolling = {
        'schema_version': 'mirofish.alpha_backtest_rolling.v1',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'window': max(1, int(window)),
        'sample_count': len(enhanced),
        'avg_expectancy_r': round(_average([item.get('expectancy_r') for item in enhanced]), 4),
        'avg_information_coefficient': round(_average([item.get('information_coefficient') for item in enhanced]), 4),
        'avg_win_rate': round(_average([item.get('win_rate') for item in enhanced]), 4),
        'avg_profit_factor': round(_average([item.get('profit_factor') for item in enhanced]), 4),
        'lookahead_safe': True,
    }
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(rolling, f, ensure_ascii=False, indent=2)
    return rolling


def _daily_report_paths(root: str) -> list[str]:
    if not os.path.isdir(root):
        return []
    return [
        os.path.join(root, name)
        for name in os.listdir(root)
        if name.startswith('alpha_backtest') and name.endswith('.json') and 'rolling' not in name
    ]


def _load_price_dates(path: str) -> list[str]:
    dates = set()
    if not os.path.isfile(path):
        return []
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            date = str(row.get('date') or '').strip()
            if date:
                dates.add(date)
    return sorted(dates)


def _mature_cutoff_date(price_dates: list[str], horizon_days: int) -> str | None:
    if not price_dates:
        return None
    forward = max(1, int(horizon_days))
    if len(price_dates) <= forward:
        return None
    return price_dates[-(forward + 1)]


def _load_prices(path: str, symbols: set[str] | None = None) -> dict[str, list[dict[str, Any]]]:
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    if not os.path.isfile(path):
        return by_symbol
    symbol_filter = set(symbols or [])
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            symbol = _symbol(row.get('ticker') or row.get('symbol') or row.get('code'))
            if symbol_filter and symbol not in symbol_filter:
                continue
            date = str(row.get('date') or '').strip()
            price = _float(row.get('current_price') or row.get('close'))
            if not symbol or not date or price <= 0:
                continue
            by_symbol.setdefault(symbol, []).append({
                'symbol': symbol,
                'date': date,
                'price': price,
            })
    for rows in by_symbol.values():
        rows.sort(key=lambda item: item['date'])
    return by_symbol


def _load_runs(
    root: str,
    *,
    limit_runs: int | None,
    mature_cutoff_date: str | None = None,
) -> list[dict[str, Any]]:
    if not os.path.isdir(root):
        return []
    paths: list[tuple[str, float, str]] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        if 'run.json' not in filenames:
            continue
        path = os.path.join(dirpath, 'run.json')
        run_date = _run_path_date(path)
        if mature_cutoff_date and run_date and run_date > mature_cutoff_date:
            continue
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        paths.append((run_date or '', mtime, path))
    paths.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    if limit_runs:
        paths = paths[:max(0, int(limit_runs))]

    records = []
    for _run_date, _mtime, path in paths:
        try:
            with open(path, 'r', encoding='utf-8-sig') as f:
                run = json.load(f)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if not isinstance(run, dict):
            continue
        ts = str(run.get('generated_at') or run.get('created_at') or '')
        records.append((ts, path, run))
    records.sort(key=lambda item: (item[0], item[1]), reverse=True)
    runs = [item[2] for item in records]
    return runs[:limit_runs] if limit_runs else runs


def _run_path_date(path: str) -> str | None:
    name = os.path.basename(os.path.dirname(path))
    parts = name.split('_')
    if len(parts) < 2 or len(parts[1]) < 8:
        return None
    stamp = parts[1][:8]
    if not stamp.isdigit():
        return None
    return f'{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}'


def _sample(candidate: dict[str, Any], prices: dict[str, list[dict[str, Any]]], horizon_days: int) -> dict[str, Any] | None:
    symbol = _symbol(candidate.get('symbol'))
    rows = prices.get(symbol) or []
    if not rows:
        return None
    replay = candidate.get('replay_context') if isinstance(candidate.get('replay_context'), dict) else {}
    price = candidate.get('price') if isinstance(candidate.get('price'), dict) else {}
    entry_date = str(replay.get('price_date') or price.get('date') or '').strip()
    index = next((idx for idx, row in enumerate(rows) if row.get('date') == entry_date), -1)
    if index < 0:
        return None
    forward_index = index + max(1, int(horizon_days))
    if forward_index >= len(rows):
        return None
    entry_price = _float(rows[index].get('price'))
    exit_price = _float(rows[forward_index].get('price'))
    if entry_price <= 0 or exit_price <= 0:
        return None
    return_pct = ((exit_price / entry_price) - 1) * 100
    stop_pct = _float((candidate.get('entry_plan') or {}).get('stop_pct'))
    r_multiple = return_pct / stop_pct if stop_pct > 0 else None
    return {
        'symbol': symbol,
        'name': candidate.get('display_name') or candidate.get('name'),
        'action': candidate.get('action'),
        'alpha_score': _float(candidate.get('alpha_score')),
        'risk_score': _float(candidate.get('risk_score')),
        'ranking_score': _float(candidate.get('ranking_score')),
        'entry_date': entry_date,
        'exit_date': rows[forward_index].get('date'),
        'entry_price': entry_price,
        'exit_price': exit_price,
        'return_pct': round(return_pct, 4),
        'r_multiple': round(r_multiple, 4) if r_multiple is not None else None,
    }


def _passes_plan_a(candidate: dict[str, Any]) -> bool:
    profile = candidate.get('analysis_profile') if isinstance(candidate.get('analysis_profile'), dict) else {}
    gates = profile.get('false_signal_gates') if isinstance(profile.get('false_signal_gates'), dict) else {}
    if gates.get('hard_blockers'):
        return False
    for gate in gates.get('gates') or []:
        if not isinstance(gate, dict):
            continue
        if gate.get('status') == 'fail':
            return False
    tags = set(candidate.get('strategy_tags') or [])
    return not {'kind_blacklist', 'credit_pressure', 'thin_liquidity_spike'} & tags


def _metrics(samples: list[dict[str, Any]]) -> dict[str, Any]:
    returns = [_float(item.get('return_pct')) for item in samples]
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value < 0]
    scores = [_float(item.get('ranking_score')) for item in samples]
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
    win_rate = len(wins) / len(samples) if samples else 0.0
    expectancy_r = ((win_rate * avg_win) - ((1 - win_rate) * avg_loss)) / avg_loss if avg_loss > 0 else (avg_win if wins else 0.0)
    information_coefficient = _correlation(scores, returns) if len(samples) >= 3 else None
    profit_factor = (sum(wins) / abs(sum(losses))) if losses else (sum(wins) if wins else 0.0)
    thresholds_met = {
        'expectancy_r': expectancy_r >= SUCCESS_THRESHOLDS['expectancy_r_min'],
        'information_coefficient': (information_coefficient or 0.0) >= SUCCESS_THRESHOLDS['information_coefficient_min'],
        'profit_factor': profit_factor >= SUCCESS_THRESHOLDS['profit_factor_min'],
        'sample_count': len(samples) >= SUCCESS_THRESHOLDS['sample_count_min'],
    }
    return {
        'sample_count': len(samples),
        'win_rate': round(win_rate, 4) if samples else 0.0,
        'average_return_pct': round(sum(returns) / len(returns), 4) if returns else 0.0,
        'median_return_pct': round(_median(returns), 4) if returns else 0.0,
        'expectancy_r': round(expectancy_r, 4),
        'profit_factor': round(profit_factor, 4),
        'max_loss_pct': round(min(returns), 4) if returns else 0.0,
        'information_coefficient': round(information_coefficient, 4) if information_coefficient is not None else None,
        'IC': round(information_coefficient, 4) if information_coefficient is not None else None,
        'thresholds_met': thresholds_met,
        'top_symbols': [item['symbol'] for item in sorted(samples, key=lambda row: row['return_pct'], reverse=True)[:5]],
    }


def _metric_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    return {
        'sample_count': _float(after.get('sample_count')) - _float(before.get('sample_count')),
        'win_rate': round(_float(after.get('win_rate')) - _float(before.get('win_rate')), 4),
        'average_return_pct': round(_float(after.get('average_return_pct')) - _float(before.get('average_return_pct')), 4),
        'expectancy_r': round(_float(after.get('expectancy_r')) - _float(before.get('expectancy_r')), 4),
        'information_coefficient': round(_float(after.get('information_coefficient')) - _float(before.get('information_coefficient')), 4),
        'IC': round(_float(after.get('IC')) - _float(before.get('IC')), 4),
        'profit_factor': round(_float(after.get('profit_factor')) - _float(before.get('profit_factor')), 4),
    }


def _average(values: list[Any]) -> float:
    clean = [_float(value) for value in values if value not in (None, '')]
    return sum(clean) / len(clean) if clean else 0.0


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _correlation(xs: list[float], ys: list[float]) -> float:
    if len(xs) != len(ys) or len(xs) < 2:
        return 0.0
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    denom = math.sqrt(var_x * var_y)
    return cov / denom if denom else 0.0


def _symbol(value: Any) -> str:
    digits = ''.join(ch for ch in str(value or '') if ch.isdigit())
    return digits.zfill(6)[-6:] if digits else ''


def _float(value: Any) -> float:
    try:
        if value in (None, ''):
            return 0.0
        return float(str(value).replace(',', ''))
    except (TypeError, ValueError):
        return 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description='Backtest MiroFish alpha scanner signals.')
    parser.add_argument('--scanner-root', default=DEFAULT_SCANNER_ROOT)
    parser.add_argument('--prices', default=DEFAULT_PRICES)
    parser.add_argument('--output', default=DEFAULT_OUTPUT)
    parser.add_argument('--rolling-output', default=DEFAULT_ROLLING_OUTPUT)
    parser.add_argument('--horizon-days', type=int, default=5)
    parser.add_argument('--limit-runs', type=int, default=None)
    parser.add_argument('--json', action='store_true', help='Print JSON report to stdout.')
    args = parser.parse_args()

    report = evaluate_runs(
        scanner_root=args.scanner_root,
        prices_path=args.prices,
        horizon_days=args.horizon_days,
        limit_runs=args.limit_runs,
    )
    write_report(report, args.output)
    write_rolling_report(current_report=report, output_path=args.rolling_output)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            f"Alpha backtest: baseline n={report['baseline']['sample_count']} "
            f"plan_a n={report['plan_a_false_signal_filter']['sample_count']} "
            f"output={args.output}"
        )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

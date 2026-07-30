"""Append-only ledger and forward-return maths for published Goodrich picks.

The live Goodrich service replaces its TOP 3 every cycle, so a pick's outcome is
only ever visible if it happens to hit target or stop before the next cycle. In
practice almost every pick disappears as ``replaced`` and the service reports a
hit rate built on a handful of survivors.

This module keeps detection quality measurable instead:

- ``record_snapshot`` writes every published pick to an append-only ledger, so
  replacement never destroys the record.
- ``evaluate_pick`` computes forward returns from daily closes using only
  sessions strictly after the entry date, against a date-aligned benchmark, net
  of round-trip trading costs.
- ``summarize`` aggregates per horizon, counting pending picks as pending rather
  than as zero-return outcomes.

Numeric authority stays with the deterministic price files; nothing here infers
a price it was not given.
"""

from __future__ import annotations

import json
import os
from typing import Any, Iterable


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
DATA_ROOT = os.path.join(REPO_ROOT, 'data')
LEDGER_PATH = os.path.join(DATA_ROOT, 'admin_mirofish', 'goodrich_ledger.jsonl')

DEFAULT_HORIZONS = (1, 3, 5, 20)

# Index proxies collected alongside ordinary listings in daily_prices.csv, so a
# benchmark close exists on exactly the sessions the picks traded. Excess return
# is only claimed when both legs have a close on the same date.
BENCHMARK_TICKERS = {
    '069500': 'KODEX 200',
    '229200': 'KODEX 코스닥150',
}
KOSPI_BENCHMARK = '069500'
KOSDAQ_BENCHMARK = '229200'

# Korean round-trip friction: securities transaction tax plus both brokerage
# legs. Treat this as an assumption to confirm against the live brokerage
# schedule, not as a fact - it is reported back in every evaluation so a wrong
# value is visible rather than silently baked into the win rate.
DEFAULT_ROUND_TRIP_COST_PCT = 0.23


def record_snapshot(
    snapshot: dict[str, Any],
    *,
    ledger_path: str | None = None,
) -> int:
    """Append each published pick once. Returns the number of new rows written."""
    path = ledger_path or LEDGER_PATH
    picks = snapshot.get('picks')
    if not isinstance(picks, list) or not picks:
        return 0

    cycle_id = str(snapshot.get('cycle_id') or '').strip()
    detected_at = str(snapshot.get('detected_at') or '').strip()
    entry_date = _date_part(detected_at)
    known = _existing_keys(path)

    rows = []
    for pick in picks:
        if not isinstance(pick, dict):
            continue
        symbol = _symbol(pick.get('symbol'))
        entry_price = _number(pick.get('entry_price') or pick.get('current_price'))
        if not symbol or entry_price <= 0:
            continue
        key = (cycle_id, symbol)
        if key in known:
            continue
        known.add(key)
        rows.append({
            'cycle_id': cycle_id,
            'symbol': symbol,
            'name': pick.get('name'),
            'market': pick.get('market'),
            'rank': pick.get('rank'),
            'detected_at': detected_at,
            'entry_date': entry_date,
            'entry_price': entry_price,
            'target_price': _number(pick.get('target_price')) or None,
            'stop_price': _number(pick.get('stop_price')) or None,
            'score': pick.get('score'),
            'ai_verdict': pick.get('ai_verdict'),
            'ai_conviction': pick.get('ai_conviction'),
        })

    if not rows:
        return 0

    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'a', encoding='utf-8') as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')
    return len(rows)


def backfill_from_history(
    history: dict[str, Any],
    *,
    ledger_path: str | None = None,
) -> int:
    """Ingest a Goodrich ``/v1/fund-manager/history`` payload into the ledger."""
    items = history.get('items') if isinstance(history, dict) else None
    if not isinstance(items, list):
        return 0
    written = 0
    for item in items:
        if isinstance(item, dict):
            written += record_snapshot(item, ledger_path=ledger_path)
    return written


def read_ledger(*, ledger_path: str | None = None) -> list[dict[str, Any]]:
    path = ledger_path or LEDGER_PATH
    if not os.path.exists(path):
        return []
    entries = []
    with open(path, encoding='utf-8') as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict):
                entries.append(entry)
    return entries


def benchmark_ticker(entry: dict[str, Any]) -> str:
    """Index proxy for one pick. Unknown market falls back to the broad KR index."""
    market = str((entry or {}).get('market') or '').strip().upper()
    if market.startswith('KOSDAQ') or market in {'KQ', 'KOSDAQ_GLOBAL'}:
        return KOSDAQ_BENCHMARK
    return KOSPI_BENCHMARK


def evaluate_ledger(
    entries: Iterable[dict[str, Any]],
    price_history: dict[str, list[dict[str, Any]]],
    *,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    round_trip_cost_pct: float = DEFAULT_ROUND_TRIP_COST_PCT,
) -> list[dict[str, Any]]:
    """Evaluate every ledger entry against its own market's benchmark series."""
    evaluations = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        ticker = benchmark_ticker(entry)
        evaluation = evaluate_pick(
            entry,
            price_history.get(_symbol(entry.get('symbol'))) or [],
            price_history.get(ticker) or [],
            horizons=horizons,
            round_trip_cost_pct=round_trip_cost_pct,
        )
        evaluation['benchmark_ticker'] = ticker
        for row in evaluation['horizons'].values():
            row['benchmark_ticker'] = ticker
        evaluations.append(evaluation)
    return evaluations


def evaluate_pick(
    entry: dict[str, Any],
    price_rows: Iterable[dict[str, Any]] | None,
    benchmark_rows: Iterable[dict[str, Any]] | None,
    *,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    round_trip_cost_pct: float = DEFAULT_ROUND_TRIP_COST_PCT,
) -> dict[str, Any]:
    """Forward returns for one pick, using only sessions after ``entry_date``."""
    wanted = _clean_horizons(horizons)
    entry_date = str(entry.get('entry_date') or '').strip()
    entry_price = _number(entry.get('entry_price'))
    base = {
        'symbol': _symbol(entry.get('symbol')),
        'cycle_id': entry.get('cycle_id'),
        'name': entry.get('name'),
        'entry_date': entry_date,
        'entry_price': entry_price,
        'round_trip_cost_pct': round_trip_cost_pct,
        'lookahead_rule': 'exit sessions must satisfy date > entry_date',
        'horizons': {},
        'pending_horizons': list(wanted),
    }
    if not base['symbol'] or not entry_date or entry_price <= 0:
        return {**base, 'status': 'missing_entry'}

    future = _future_sessions(price_rows, entry_date)
    if not future:
        return {**base, 'status': 'pending', 'available_sessions': 0}

    benchmark_by_date = _closes_by_date(benchmark_rows)
    benchmark_entry = _benchmark_close_on_or_before(benchmark_by_date, entry_date)

    horizon_results: dict[str, Any] = {}
    for horizon in wanted:
        if horizon > len(future):
            continue
        row = future[horizon - 1]
        exit_date = str(row.get('date') or '')
        exit_price = _number(row.get('current_price'))
        return_pct = _pct(exit_price, entry_price)
        net_return_pct = round(return_pct - round_trip_cost_pct, 2)

        benchmark_return_pct = None
        excess_return_pct = None
        net_excess_return_pct = None
        benchmark_exit = benchmark_by_date.get(exit_date)
        if benchmark_entry and benchmark_exit:
            benchmark_return_pct = _pct(benchmark_exit, benchmark_entry)
            excess_return_pct = round(return_pct - benchmark_return_pct, 2)
            net_excess_return_pct = round(excess_return_pct - round_trip_cost_pct, 2)

        horizon_results[str(horizon)] = {
            'horizon_days': horizon,
            'exit_date': exit_date,
            'exit_price': exit_price,
            'return_pct': return_pct,
            'net_return_pct': net_return_pct,
            'benchmark_return_pct': benchmark_return_pct,
            'excess_return_pct': excess_return_pct,
            'net_excess_return_pct': net_excess_return_pct,
        }

    evaluated = sorted(int(key) for key in horizon_results)
    pending = [horizon for horizon in wanted if horizon not in evaluated]
    if not evaluated:
        status = 'pending'
    elif pending:
        status = 'partial'
    else:
        status = 'evaluated'

    return {
        **base,
        'status': status,
        'available_sessions': len(future),
        'horizons': horizon_results,
        'pending_horizons': pending,
    }


def summarize(
    evaluations: Iterable[dict[str, Any]],
    *,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
) -> dict[str, Any]:
    """Aggregate per horizon. Picks without an outcome stay pending, not zero."""
    items = [item for item in evaluations if isinstance(item, dict)]
    wanted = _clean_horizons(horizons)

    per_horizon: dict[str, Any] = {}
    for horizon in wanted:
        key = str(horizon)
        rows = [
            item['horizons'][key]
            for item in items
            if isinstance(item.get('horizons'), dict) and key in item['horizons']
        ]
        returns = [_number(row.get('return_pct')) for row in rows]
        net_returns = [_number(row.get('net_return_pct')) for row in rows]
        excess = [
            _number(row.get('excess_return_pct')) for row in rows
            if row.get('excess_return_pct') is not None
        ]
        net_excess = [
            _number(row.get('net_excess_return_pct')) for row in rows
            if row.get('net_excess_return_pct') is not None
        ]
        per_horizon[key] = {
            'horizon_days': horizon,
            'evaluated_count': len(rows),
            'win_rate_pct': _mean([100.0 if value > 0 else 0.0 for value in returns]),
            'mean_return_pct': _mean(returns),
            'median_return_pct': _median(returns),
            'mean_net_return_pct': _mean(net_returns),
            'benchmarked_count': len(excess),
            'mean_excess_return_pct': _mean(excess),
            'mean_net_excess_return_pct': _mean(net_excess),
            'worst_return_pct': round(min(returns), 2) if returns else None,
            'best_return_pct': round(max(returns), 2) if returns else None,
        }

    return {
        'total_picks': len(items),
        'pending_count': sum(1 for item in items if not (item.get('horizons') or {})),
        'horizons': per_horizon,
    }


def _future_sessions(
    price_rows: Iterable[dict[str, Any]] | None,
    entry_date: str,
) -> list[dict[str, Any]]:
    rows = [
        row for row in (price_rows or [])
        if isinstance(row, dict)
        and str(row.get('date') or '') > entry_date
        and _number(row.get('current_price')) > 0
    ]
    rows.sort(key=lambda row: str(row.get('date') or ''))
    return rows


def _closes_by_date(rows: Iterable[dict[str, Any]] | None) -> dict[str, float]:
    closes: dict[str, float] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        date = str(row.get('date') or '').strip()
        close = _number(row.get('current_price') or row.get('close'))
        if date and close > 0:
            closes[date] = close
    return closes


def _benchmark_close_on_or_before(closes: dict[str, float], entry_date: str) -> float | None:
    if not closes:
        return None
    candidates = [date for date in closes if date <= entry_date]
    if not candidates:
        return None
    return closes[max(candidates)]


def _existing_keys(path: str) -> set[tuple[str, str]]:
    return {
        (str(entry.get('cycle_id') or ''), _symbol(entry.get('symbol')))
        for entry in read_ledger(ledger_path=path)
    }


def _clean_horizons(horizons: tuple[int, ...] | list[int] | None) -> tuple[int, ...]:
    values = sorted({int(value) for value in (horizons or ()) if int(value) > 0})
    return tuple(values) or DEFAULT_HORIZONS


def _date_part(value: str) -> str:
    text = str(value or '').strip()
    return text[:10] if len(text) >= 10 else ''


def _symbol(value: Any) -> str:
    return str(value or '').strip()


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _pct(exit_price: float, entry_price: float) -> float:
    if entry_price <= 0:
        return 0.0
    return round((exit_price / entry_price - 1) * 100, 2)


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[middle], 2)
    return round((ordered[middle - 1] + ordered[middle]) / 2, 2)

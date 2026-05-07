"""Forward outcome tracking for MiroFish scanner and MCP workflows.

The tracker evaluates recommendations only with rows after the scanner entry
date. It is intentionally deterministic so MiroFish Top 3 decisions can be
replayed and backtested without look-ahead bias.
"""

from __future__ import annotations

import csv
import json
import os
import re
from datetime import datetime, timezone
from typing import Any

from app.utils.atomic_json import write_json_atomic


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
DATA_ROOT = os.path.join(REPO_ROOT, 'data')
WORKFLOWS_ROOT = os.path.join(DATA_ROOT, 'admin_mirofish', 'workflows')
PRICE_HISTORY_PATH = os.path.join(DATA_ROOT, 'daily_prices.csv')

DEFAULT_HORIZONS = (5, 10, 20)
DEFAULT_TARGET_RETURN_PCT = 5.0
DEFAULT_STOP_LOSS_PCT = -7.0


def read_workflow_outcomes(workflow_id: str) -> dict[str, Any] | None:
    """Read a persisted workflow outcome artifact."""
    path = _outcome_path(workflow_id)
    if not os.path.isfile(path):
        return None
    return _read_json(path)


def refresh_workflow_outcomes(
    workflow_id: str,
    *,
    workflow: dict[str, Any] | None = None,
    horizons: tuple[int, ...] | list[int] | None = None,
    price_history_path: str | None = None,
    workflows_root: str | None = None,
    target_return_pct: float = DEFAULT_TARGET_RETURN_PCT,
    stop_loss_pct: float = DEFAULT_STOP_LOSS_PCT,
) -> dict[str, Any]:
    """Recompute forward outcomes for a workflow and persist outcomes.json."""
    record = workflow if isinstance(workflow, dict) else _read_workflow(workflow_id, workflows_root=workflows_root)
    if not isinstance(record, dict):
        raise ValueError('workflow not found')

    clean_horizons = _clean_horizons(horizons)
    results = _workflow_results(record)
    symbols = [str(item.get('symbol') or (item.get('candidate') or {}).get('symbol') or '') for item in results]
    price_path = price_history_path or PRICE_HISTORY_PATH
    history = _load_price_history(price_path, symbols)
    items = [
        evaluate_result_outcome(
            item,
            history.get(_symbol(item.get('symbol') or (item.get('candidate') or {}).get('symbol'))),
            horizons=clean_horizons,
            target_return_pct=target_return_pct,
            stop_loss_pct=stop_loss_pct,
        )
        for item in results
    ]
    outcomes = {
        'workflow_id': record.get('id') or workflow_id,
        'status': _aggregate_status(items),
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'lookahead_safe': True,
        'method': 'entry_date_strict_forward_price_replay',
        'horizons': list(clean_horizons),
        'target_return_pct': target_return_pct,
        'stop_loss_pct': stop_loss_pct,
        'price_history': _price_history_meta(price_path, history),
        'items': items,
        'summary': summarize_outcomes(items),
    }
    write_json_atomic(_outcome_path(workflow_id, workflows_root=workflows_root), outcomes, sort_keys=False)
    return outcomes


def attach_outcomes_to_results(
    results: list[dict[str, Any]],
    outcomes: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Return copies of analysis results with matching outcome fields attached."""
    outcome_map = {
        _symbol(item.get('symbol')): item
        for item in (outcomes or {}).get('items') or []
        if isinstance(item, dict)
    }
    attached: list[dict[str, Any]] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        item = dict(result)
        symbol = _symbol(item.get('symbol') or (item.get('candidate') or {}).get('symbol'))
        outcome = outcome_map.get(symbol)
        if outcome:
            item['outcome'] = outcome
            item['forward_return_pct'] = outcome.get('forward_return_pct')
            item['outcome_status'] = outcome.get('status')
            item['hit'] = outcome.get('hit')
        attached.append(item)
    return attached


def workflow_outcome_summary(outcomes: dict[str, Any] | None) -> dict[str, Any]:
    """Return the compact outcome summary used by workflow.json and UI cards."""
    if not isinstance(outcomes, dict):
        return {}
    summary = outcomes.get('summary')
    return summary if isinstance(summary, dict) else {}


def evaluate_result_outcome(
    result: dict[str, Any],
    price_rows: list[dict[str, Any]] | None,
    *,
    horizons: tuple[int, ...],
    target_return_pct: float,
    stop_loss_pct: float,
) -> dict[str, Any]:
    """Evaluate one recommendation with future rows only."""
    candidate = result.get('candidate') if isinstance(result.get('candidate'), dict) else {}
    symbol = _symbol(result.get('symbol') or candidate.get('symbol'))
    name = result.get('target') or candidate.get('display_name') or candidate.get('name') or symbol
    entry_date = _entry_date(candidate, result)
    entry_price = _number(
        (candidate.get('price') or {}).get('current_price')
        if isinstance(candidate.get('price'), dict)
        else candidate.get('price')
    )

    base = {
        'symbol': symbol,
        'name': name,
        'rank': candidate.get('rank'),
        'entry_date': entry_date,
        'entry_price': entry_price,
        'lookahead_safe': True,
        'rule': 'use rows where price.date > entry_date only',
        'target_return_pct': target_return_pct,
        'stop_loss_pct': stop_loss_pct,
        'horizons': {},
    }
    if not symbol or not entry_date or entry_price <= 0:
        return {
            **base,
            'status': 'missing_entry',
            'reason': 'symbol, entry_date, or entry_price is missing',
            'available_future_days': 0,
            'hit': None,
        }
    future_rows = [
        row for row in (price_rows or [])
        if str(row.get('date') or '') > entry_date and _number(row.get('current_price')) > 0
    ]
    future_rows.sort(key=lambda row: str(row.get('date') or ''))
    if not future_rows:
        return {
            **base,
            'status': 'pending',
            'reason': 'no future price rows after entry_date',
            'available_future_days': 0,
            'hit': None,
        }

    max_return = None
    max_drawdown = None
    horizon_results: dict[str, Any] = {}
    for index, row in enumerate(future_rows, start=1):
        close = _number(row.get('current_price'))
        if close <= 0:
            continue
        return_pct = _pct(close, entry_price)
        max_return = return_pct if max_return is None else max(max_return, return_pct)
        max_drawdown = return_pct if max_drawdown is None else min(max_drawdown, return_pct)
        if index in horizons:
            horizon_results[str(index)] = {
                'horizon_days': index,
                'exit_date': row.get('date'),
                'exit_price': close,
                'return_pct': return_pct,
            }

    evaluated_horizons = sorted(int(key) for key in horizon_results)
    if evaluated_horizons:
        primary_horizon = max(evaluated_horizons)
        primary = horizon_results[str(primary_horizon)]
        forward_return = primary['return_pct']
        hit = forward_return >= target_return_pct
        status = 'evaluated' if len(evaluated_horizons) == len(horizons) else 'partial'
        reason = f'T{primary_horizon} return {forward_return:+.2f}%'
    else:
        primary_horizon = None
        primary = None
        forward_return = None
        hit = None
        status = 'pending'
        reason = 'not enough future rows for requested horizons'

    stopped = max_drawdown is not None and max_drawdown <= stop_loss_pct
    return {
        **base,
        'status': status,
        'reason': reason,
        'available_future_days': len(future_rows),
        'primary_horizon_days': primary_horizon,
        'forward_return_pct': forward_return,
        'max_forward_return_pct': round(max_return or 0.0, 2),
        'max_drawdown_pct': round(max_drawdown or 0.0, 2),
        'hit': hit,
        'stopped': stopped,
        'primary': primary,
        'horizons': horizon_results,
    }


def summarize_outcomes(items: list[dict[str, Any]]) -> dict[str, Any]:
    evaluable = [item for item in items if item.get('status') in {'partial', 'evaluated'}]
    hits = [item for item in evaluable if item.get('hit') is True]
    misses = [item for item in evaluable if item.get('hit') is False]
    returns = [_number(item.get('forward_return_pct')) for item in evaluable if item.get('forward_return_pct') is not None]
    top3 = items[:3]
    top3_evaluable = [item for item in top3 if item.get('status') in {'partial', 'evaluated'}]
    top3_hits = [item for item in top3_evaluable if item.get('hit') is True]
    best = max(evaluable, key=lambda item: _number(item.get('forward_return_pct')), default=None)
    worst = min(evaluable, key=lambda item: _number(item.get('forward_return_pct')), default=None)
    return {
        'evaluated_count': len(evaluable),
        'pending_count': len(items) - len(evaluable),
        'hit_count': len(hits),
        'miss_count': len(misses),
        'hit_rate_pct': round((len(hits) / len(evaluable)) * 100, 1) if evaluable else None,
        'top3_evaluated_count': len(top3_evaluable),
        'top3_hit_count': len(top3_hits),
        'top3_hit_rate_pct': round((len(top3_hits) / len(top3_evaluable)) * 100, 1) if top3_evaluable else None,
        'average_forward_return_pct': round(sum(returns) / len(returns), 2) if returns else None,
        'best_symbol': best.get('symbol') if best else None,
        'best_return_pct': best.get('forward_return_pct') if best else None,
        'worst_symbol': worst.get('symbol') if worst else None,
        'worst_return_pct': worst.get('forward_return_pct') if worst else None,
        'lookahead_safe': True,
    }


def _workflow_results(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    top3 = workflow.get('top3') if isinstance(workflow.get('top3'), list) else []
    analysis_runs = workflow.get('analysis_runs') if isinstance(workflow.get('analysis_runs'), list) else []
    results = top3 or analysis_runs
    return [item for item in results if isinstance(item, dict)]


def _load_price_history(path: str, symbols: list[str]) -> dict[str, list[dict[str, Any]]]:
    clean_symbols = {_symbol(symbol) for symbol in symbols if _symbol(symbol)}
    if not clean_symbols or not os.path.isfile(path):
        return {}
    rows: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in clean_symbols}
    try:
        with open(path, 'r', encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                symbol = _symbol(row.get('ticker') or row.get('symbol') or row.get('code'))
                if symbol in clean_symbols:
                    rows[symbol].append({
                        'date': row.get('date'),
                        'current_price': _number(row.get('current_price') or row.get('close') or row.get('price')),
                        'high': _number(row.get('high')),
                        'low': _number(row.get('low')),
                        'volume': _number(row.get('volume')),
                    })
    except (OSError, csv.Error, UnicodeDecodeError):
        return {}
    for symbol_rows in rows.values():
        symbol_rows.sort(key=lambda item: str(item.get('date') or ''))
    return rows


def _price_history_meta(path: str, history: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    exists = os.path.isfile(path)
    modified_at = None
    if exists:
        modified_at = datetime.fromtimestamp(os.path.getmtime(path), timezone.utc).isoformat()
    return {
        'path': os.path.relpath(path, REPO_ROOT).replace('\\', '/') if exists else path,
        'exists': exists,
        'modified_at': modified_at,
        'symbols_loaded': len(history),
        'rows_loaded': sum(len(rows) for rows in history.values()),
    }


def _aggregate_status(items: list[dict[str, Any]]) -> str:
    if not items:
        return 'empty'
    statuses = {item.get('status') for item in items}
    if statuses <= {'evaluated'}:
        return 'evaluated'
    if statuses & {'partial', 'evaluated'}:
        return 'partial'
    return 'pending'


def _clean_horizons(horizons: tuple[int, ...] | list[int] | None) -> tuple[int, ...]:
    raw = horizons or DEFAULT_HORIZONS
    clean = sorted({int(item) for item in raw if 1 <= int(item) <= 120})
    return tuple(clean or DEFAULT_HORIZONS)


def _entry_date(candidate: dict[str, Any], result: dict[str, Any]) -> str:
    replay = candidate.get('replay_context') if isinstance(candidate.get('replay_context'), dict) else {}
    price = candidate.get('price') if isinstance(candidate.get('price'), dict) else {}
    return str(
        replay.get('price_date')
        or price.get('date')
        or result.get('entry_date')
        or ''
    )[:10]


def _read_workflow(workflow_id: str, *, workflows_root: str | None = None) -> dict[str, Any] | None:
    path = os.path.join(_workflow_dir(workflow_id, workflows_root=workflows_root), 'workflow.json')
    if not os.path.isfile(path):
        return None
    return _read_json(path)


def _read_json(path: str) -> dict[str, Any]:
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError('json root must be object')
    return data


def _outcome_path(workflow_id: str, *, workflows_root: str | None = None) -> str:
    return os.path.join(_workflow_dir(workflow_id, workflows_root=workflows_root), 'outcomes.json')


def _workflow_dir(workflow_id: str, *, workflows_root: str | None = None) -> str:
    safe_id = _safe_workflow_id(workflow_id)
    root = os.path.abspath(workflows_root or WORKFLOWS_ROOT)
    path = os.path.abspath(os.path.join(root, safe_id))
    if not path.startswith(root):
        raise ValueError('invalid workflow_id')
    os.makedirs(path, exist_ok=True)
    return path


def _safe_workflow_id(workflow_id: str) -> str:
    safe_id = str(workflow_id or '').strip()
    if not re.fullmatch(r'[A-Za-z0-9_.-]{8,80}', safe_id):
        raise ValueError('invalid workflow_id')
    return safe_id


def _symbol(value: Any) -> str:
    symbol = str(value or '').strip()
    digits = ''.join(ch for ch in symbol if ch.isdigit())
    if len(digits) == 6:
        return digits
    return symbol.upper()


def _number(value: Any) -> float:
    try:
        if value in (None, ''):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _pct(exit_price: float, entry_price: float) -> float:
    if entry_price <= 0:
        return 0.0
    return round(((exit_price - entry_price) / entry_price) * 100.0, 2)

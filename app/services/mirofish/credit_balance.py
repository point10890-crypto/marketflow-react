"""Credit-balance cache for Plan A false-signal gating.

The credit gate is a hard risk control, but missing KRX credit data should not
break the scanner.  This module reads a local cache first and exposes a parser
that can be wired to a live fetcher later without changing scanner semantics.
"""

from __future__ import annotations

import csv
import json
import os
import re
import time
from datetime import datetime, timezone
from io import StringIO
from typing import Any

from app.utils.atomic_json import write_json_atomic


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
DATA_ROOT = os.path.join(REPO_ROOT, 'data')
CACHE_FILENAME = 'credit_balance_latest.json'
DEFAULT_TTL_SECONDS = 6 * 3600


def get_credit_balance_snapshot(
    *,
    data_root: str | None = None,
    allow_fetch: bool = False,
    now: float | None = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> dict[str, Any]:
    root = data_root or DATA_ROOT
    path = os.path.join(root, CACHE_FILENAME)
    current = now if now is not None else time.time()
    cached = _read_json(path)
    if cached and _is_fresh(cached, path, current, ttl_seconds):
        cached.setdefault('status', 'fresh')
        return cached
    if allow_fetch:
        try:
            refreshed = refresh_credit_balance(data_root=root)
            if refreshed.get('status') == 'error' and cached:
                cached['status'] = 'stale'
                return cached
            return refreshed
        except Exception as exc:
            if cached:
                cached['status'] = 'stale'
                cached['fetch_error'] = f'{type(exc).__name__}: {exc}'
                return cached
            return _empty('error', f'{type(exc).__name__}: {exc}')
    if cached:
        cached['status'] = 'stale'
        return cached
    return _empty('missing')


def refresh_credit_balance(*, data_root: str | None = None) -> dict[str, Any]:
    """Refresh the cache from a live source hook.

    The live hook intentionally returns an error by default because KRX endpoints
    vary by session/cookie.  Operators can later replace `_fetch_credit_payload`
    in one place while tests keep the scanner deterministic.
    """

    root = data_root or DATA_ROOT
    try:
        payload = _fetch_credit_payload()
        entries = _parse_credit_payload(payload)
    except Exception as exc:
        return _empty('error', f'{type(exc).__name__}: {exc}')
    snapshot = {
        'schema_version': 'mirofish.credit_balance.v1',
        'source': 'KRX credit balance cache',
        'status': 'fresh' if entries else 'empty',
        'fetched_at': datetime.now(timezone.utc).isoformat(),
        'entry_count': len(entries),
        'entries': entries,
        'lookahead_safe': True,
    }
    write_json_atomic(os.path.join(root, CACHE_FILENAME), snapshot, sort_keys=True)
    return snapshot


def get_credit_entry(ticker: Any, *, data_root: str | None = None, allow_fetch: bool = False) -> dict[str, Any] | None:
    symbol = _symbol(ticker)
    if not symbol:
        return None
    snapshot = get_credit_balance_snapshot(data_root=data_root, allow_fetch=allow_fetch)
    entry = (snapshot.get('entries') or {}).get(symbol)
    return entry if isinstance(entry, dict) else None


def _parse_credit_payload(payload: str | bytes) -> dict[str, dict[str, Any]]:
    text = payload.decode('utf-8', errors='ignore') if isinstance(payload, bytes) else str(payload or '')
    entries: dict[str, dict[str, Any]] = {}
    for row in _iter_rows(text):
        symbol = _symbol(row.get('ticker') or row.get('code') or row.get('종목코드'))
        if not symbol:
            continue
        balance_shares = _float(row.get('balance_shares') or row.get('신용잔고수량') or row.get('잔고수량'))
        listed_shares = _float(row.get('listed_shares') or row.get('상장주식수'))
        ratio = _float(row.get('credit_ratio') or row.get('credit_balance_ratio') or row.get('신용잔고율'))
        if ratio and ratio <= 1:
            ratio *= 100
        if not ratio and listed_shares > 0:
            ratio = balance_shares / listed_shares * 100
        entries[symbol] = {
            'symbol': symbol,
            'balance_shares': balance_shares,
            'listed_shares': listed_shares,
            'credit_ratio_pct': round(ratio, 4) if ratio else 0.0,
            'date': row.get('date') or row.get('일자') or row.get('scrape_date'),
        }
    return entries


def _iter_rows(text: str) -> list[dict[str, Any]]:
    if not text.strip():
        return []
    cleaned = re.sub(r'<[^>]+>', '\n', text)
    if ',' in cleaned.splitlines()[0] or '\t' in cleaned.splitlines()[0]:
        dialect = csv.excel_tab if '\t' in cleaned.splitlines()[0] else csv.excel
        return [dict(row) for row in csv.DictReader(StringIO(cleaned), dialect=dialect)]
    return []


def _fetch_credit_payload() -> str:
    raise RuntimeError('live KRX credit balance fetcher is not configured')


def _read_json(path: str) -> dict[str, Any] | None:
    if not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _is_fresh(cache: dict[str, Any], path: str, now: float, ttl_seconds: int) -> bool:
    ts = _parse_ts(cache.get('fetched_at'))
    if ts:
        return now - ts <= max(60, int(ttl_seconds))
    try:
        return now - os.path.getmtime(path) <= max(60, int(ttl_seconds))
    except OSError:
        return False


def _parse_ts(value: Any) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    except ValueError:
        return None


def _empty(status: str, error: str | None = None) -> dict[str, Any]:
    payload = {
        'schema_version': 'mirofish.credit_balance.v1',
        'source': 'KRX credit balance cache',
        'status': status,
        'fetched_at': None,
        'entry_count': 0,
        'entries': {},
        'lookahead_safe': True,
    }
    if error:
        payload['fetch_error'] = error
    return payload


def _symbol(value: Any) -> str:
    digits = re.sub(r'\D', '', str(value or ''))
    return digits.zfill(6)[-6:] if digits else ''


def _float(value: Any) -> float:
    try:
        if value in (None, ''):
            return 0.0
        return float(str(value).replace(',', '').replace('%', ''))
    except (TypeError, ValueError):
        return 0.0

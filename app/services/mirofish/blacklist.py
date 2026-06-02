"""KIND/KRX risk blacklist cache for MiroFish alpha screening.

The scanner must fail open when external disclosure feeds are unavailable, but a
confirmed risk flag should block an alpha candidate before it reaches Telegram or
GraphRAG.  This module keeps that behavior deterministic and testable by using a
local cache first and live fetching only when explicitly requested.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from app.utils.atomic_json import write_json_atomic


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
DATA_ROOT = os.path.join(REPO_ROOT, 'data')
KIND_CACHE_FILENAME = 'kind_blacklist_latest.json'
DEFAULT_TTL_SECONDS = 3600
DEFAULT_KIND_URLS = (
    # Public KIND pages can change shape; the parser intentionally accepts
    # text/XML/HTML so the cache remains useful across minor response changes.
    'https://kind.krx.co.kr/corpgeneral/corpList.do?method=download',
)
RISK_KEYWORDS = (
    '관리종목',
    '투자주의',
    '투자경고',
    '투자위험',
    '거래정지',
    '불성실공시',
    '상장폐지',
    '횡령',
    '배임',
)


def get_kind_blacklist(
    *,
    data_root: str | None = None,
    allow_fetch: bool = False,
    now: float | None = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> dict[str, Any]:
    """Return a cached KIND risk blacklist, optionally refreshing it.

    Missing or failed live data never blocks the scanner by itself.  A stale
    cache is still returned with status metadata so downstream code can show the
    freshness without fabricating confidence.
    """

    root = data_root or DATA_ROOT
    path = _cache_path(root)
    current = now if now is not None else time.time()
    cached = _read_cache(path)
    if cached and _cache_is_fresh(cached, path, current, ttl_seconds):
        cached.setdefault('status', 'fresh')
        return cached

    if allow_fetch:
        try:
            refreshed = refresh_kind_blacklist(data_root=root)
            if refreshed.get('status') == 'error' and cached:
                cached['status'] = 'stale'
                cached['fetch_error'] = '; '.join(refreshed.get('fetch_errors') or []) or refreshed.get('fetch_error')
                return cached
            return refreshed
        except Exception as exc:
            if cached:
                cached['status'] = 'stale'
                cached['fetch_error'] = f'{type(exc).__name__}: {exc}'
                return cached
            return _empty_cache(status='error', error=f'{type(exc).__name__}: {exc}')

    if cached:
        cached['status'] = 'stale'
        return cached
    return _empty_cache(status='missing')


def refresh_kind_blacklist(*, data_root: str | None = None) -> dict[str, Any]:
    root = data_root or DATA_ROOT
    payloads = []
    errors = []
    for url in DEFAULT_KIND_URLS:
        try:
            payloads.append(_fetch_kind_payload(url))
        except Exception as exc:
            errors.append(f'{type(exc).__name__}: {exc}')
    entries: dict[str, dict[str, Any]] = {}
    for payload in payloads:
        entries.update(_parse_kind_payload(payload))

    snapshot = {
        'schema_version': 'mirofish.kind_blacklist.v1',
        'source': 'KIND/KRX public disclosure risk cache',
        'status': 'fresh' if entries else ('error' if errors and not payloads else 'empty'),
        'fetched_at': datetime.now(timezone.utc).isoformat(),
        'entry_count': len(entries),
        'entries': entries,
        'fetch_errors': errors,
        'lookahead_safe': True,
    }
    if snapshot['status'] != 'error':
        write_json_atomic(_cache_path(root), snapshot, sort_keys=True)
    return snapshot


def is_blacklisted(
    ticker: Any,
    *,
    data_root: str | None = None,
    allow_fetch: bool = False,
) -> dict[str, Any]:
    symbol = _symbol(ticker)
    snapshot = get_kind_blacklist(data_root=data_root, allow_fetch=allow_fetch)
    entry = (snapshot.get('entries') or {}).get(symbol) if symbol else None
    return {
        'symbol': symbol,
        'listed': bool(entry),
        'categories': (entry or {}).get('categories') or [],
        'risk_level': (entry or {}).get('risk_level') or ('hard_block' if entry else 'none'),
        'source': snapshot.get('source'),
        'status': snapshot.get('status'),
        'fetched_at': snapshot.get('fetched_at'),
    }


def _parse_kind_payload(payload: str | bytes) -> dict[str, dict[str, Any]]:
    text = payload.decode('utf-8', errors='ignore') if isinstance(payload, bytes) else str(payload or '')
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    entries: dict[str, dict[str, Any]] = {}
    for match in re.finditer(r'\b(\d{6})\b', text):
        symbol = _symbol(match.group(1))
        window = text[max(0, match.start() - 90):match.end() + 120]
        categories = [keyword for keyword in RISK_KEYWORDS if keyword in window]
        if not categories:
            continue
        entries[symbol] = {
            'symbol': symbol,
            'categories': sorted(set(categories)),
            'risk_level': 'hard_block',
            'raw_context': window.strip()[:240],
        }
    return entries


def _fetch_kind_payload(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            'User-Agent': 'MarketFlow-MiroFish/1.0',
            'Accept': 'text/html,application/xml,text/plain,*/*',
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f'KIND fetch failed: {exc}') from exc
    for encoding in ('utf-8', 'euc-kr', 'cp949'):
        try:
            return body.decode(encoding)
        except UnicodeDecodeError:
            continue
    return body.decode('utf-8', errors='ignore')


def _read_cache(path: str) -> dict[str, Any] | None:
    if not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _cache_is_fresh(cache: dict[str, Any], path: str, now: float, ttl_seconds: int) -> bool:
    fetched_at = _parse_ts(cache.get('fetched_at'))
    if fetched_at:
        return (now - fetched_at) <= max(60, int(ttl_seconds))
    try:
        return (now - os.path.getmtime(path)) <= max(60, int(ttl_seconds))
    except OSError:
        return False


def _parse_ts(value: Any) -> float | None:
    if not value:
        return None
    try:
        text = str(value).replace('Z', '+00:00')
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def _empty_cache(*, status: str, error: str | None = None) -> dict[str, Any]:
    payload = {
        'schema_version': 'mirofish.kind_blacklist.v1',
        'source': 'KIND/KRX public disclosure risk cache',
        'status': status,
        'fetched_at': None,
        'entry_count': 0,
        'entries': {},
        'lookahead_safe': True,
    }
    if error:
        payload['fetch_error'] = error
    return payload


def _cache_path(data_root: str) -> str:
    return os.path.join(data_root, KIND_CACHE_FILENAME)


def _symbol(value: Any) -> str:
    digits = re.sub(r'\D', '', str(value or ''))
    return digits.zfill(6)[-6:] if digits else ''

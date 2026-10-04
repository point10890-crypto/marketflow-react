"""Audited current-quality-cohort input, without inventing historical vintages."""
from collections import Counter
import csv
from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _day(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError('Invalid canonical session date')
    return value


def _symbol(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{6}', value):
        raise ValueError('Invalid six-digit symbol')
    return value


def load_inputs(price_csv, price_manifest, universe_report, *, as_of=None):
    """Read immutable source files; bad bars are excluded and explicitly counted.

    A missing financial-quality report is an error. Zero-volume valid OHLC bars
    are retained for source lineage but may not trade. Retrospective current
    cohort research never establishes point-in-time universe or vintage truth.
    """
    today = _day(as_of or date.today().isoformat())
    prices_path, manifest_path, scope_path = map(Path, (price_csv, price_manifest, universe_report))
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    scope = json.loads(scope_path.read_text(encoding='utf-8-sig'))
    source_hash = file_hash(prices_path)
    expected = manifest.get('prices_sha256')
    if not isinstance(expected, str) or source_hash != expected:
        raise ValueError('Price source hash differs from acquisition manifest')
    scope_date = _day(scope.get('as_of'))
    if scope_date > today:
        raise ValueError('Scope is from a future date')
    ranked = scope.get('ranking', {}).get('ranked')
    quality = scope.get('quality', {}).get('results')
    if not isinstance(ranked, list) or not 1 <= len(ranked) <= 100:
        raise ValueError('Dated TOP100 ranking is required')
    if not isinstance(quality, list):
        raise ValueError('Explicit quality results are required; no all-price fallback')
    ranked_map = {}
    for row in ranked:
        symbol = _symbol(row.get('symbol'))
        if symbol in ranked_map:
            raise ValueError('duplicate ranking symbol')
        ranked_map[symbol] = row
    selected = set()
    checked = set()
    for row in quality:
        symbol = _symbol(row.get('symbol'))
        if symbol not in ranked_map or symbol in checked:
            raise ValueError('duplicate or out-of-scope quality identity')
        checked.add(symbol)
        if row.get('quality_pass') is True:
            selected.add(symbol)
    if not selected:
        raise ValueError('No symbols passed the explicit quality cohort')
    names = {symbol: str(ranked_map[symbol].get('name') or symbol) for symbol in selected}
    groups = {symbol: [] for symbol in sorted(selected)}
    excluded, flags, seen = Counter(), Counter(), set()
    captures, bases, sources = set(), set(), set()
    observed_at = datetime.now(timezone.utc)
    total = 0
    with prices_path.open('r', encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        if not set(('date', 'open', 'high', 'low', 'volume')).issubset(reader.fieldnames or []):
            raise ValueError('Historical OHLCV columns are required')
        for raw in reader:
            total += 1
            symbol = raw.get('symbol') or raw.get('code') or raw.get('ticker')
            if symbol not in selected:
                excluded['outside_quality_scope'] += 1
                continue
            day = _day(raw.get('date'))
            if day > today:
                excluded['future_rows'] += 1
                continue
            identity = (symbol, day)
            if identity in seen:
                raise ValueError('duplicate price identity; revisions are not arbitrarily selected')
            seen.add(identity)
            try:
                row = {'symbol': symbol, 'date': day}
                for key in ('open', 'high', 'low', 'close', 'volume'):
                    value = raw.get(key) if key != 'close' else raw.get('close') or raw.get('current_price')
                    row[key] = float(value)
                    if not math.isfinite(row[key]) or row[key] < 0 or key != 'volume' and row[key] == 0:
                        raise ValueError('invalid value')
                if not (row['low'] <= row['open'] <= row['high'] and row['low'] <= row['close'] <= row['high']):
                    raise ValueError('invalid extrema')
            except (ValueError, TypeError):
                excluded['invalid_ohlcv'] += 1
                continue
            if row['volume'] == 0:
                flags['zero_volume_nontradable'] += 1
            if raw.get('quality_flags'):
                source_flags = re.split(r'[;|]', raw['quality_flags'])
                flags.update(source_flags)
                if any(value.strip().lower() in {'invalid_ohlcv', 'invalid_bar', 'corrupt_price', 'invalid_extrema'}
                       for value in source_flags):
                    excluded['fatal_source_flag'] += 1
                    continue
            if raw.get('price_basis'):
                bases.add(raw['price_basis'])
            if raw.get('source'):
                sources.add(raw['source'])
            if raw.get('captured_at'):
                try:
                    captured = datetime.fromisoformat(raw['captured_at'].replace('Z', '+00:00'))
                    if captured.utcoffset() is None:
                        raise ValueError('capture timezone unknown')
                    captured = captured.astimezone(timezone.utc)
                    if captured > observed_at:
                        flags['future_source_capture'] += 1
                    captures.add(captured.isoformat())
                except ValueError:
                    flags['capture_timezone_unverified'] += 1
            groups[symbol].append(row)
    if len(bases) > 1:
        raise ValueError('Mixed historical price bases are not silently joined')
    if bases and manifest.get('price_basis') not in bases:
        raise ValueError('Manifest price basis differs from source rows')
    for rows in groups.values():
        rows.sort(key=lambda row: row['date'])
    groups = {symbol: rows for symbol, rows in groups.items() if rows}
    if not groups:
        raise ValueError('No valid price observations within scope and cutoff')
    latest = max(rows[-1]['date'] for rows in groups.values())
    reasons = []
    if flags['future_source_capture']:
        reasons.append('future_source_capture')
    if (date.fromisoformat(today) - date.fromisoformat(scope_date)).days > 7:
        reasons.append('stale_scope')
    if (date.fromisoformat(today) - date.fromisoformat(latest)).days > 7:
        reasons.append('stale_prices')
    fingerprint = hashlib.sha256(json.dumps(dict(prices=source_hash,
        manifest=file_hash(manifest_path), scope=file_hash(scope_path)), sort_keys=True).encode()).hexdigest()
    provenance = dict(price_basis=manifest.get('price_basis', 'unknown'),
        price_adjustment_verified=manifest.get('corporate_action_adjustment_verified') is True,
        historical_vintage_verified=manifest.get('historical_vintage_verified') is True,
        point_in_time_universe_verified=False, current_cohort_bias=True, analysis_ready=False,
        price_source=manifest.get('source', 'unknown'), captured_at=max(captures) if captures else None,
        source_hash=source_hash, manifest_hash=file_hash(manifest_path), scope_hash=file_hash(scope_path))
    return dict(status='held' if reasons else 'ready', reasons=reasons, as_of=today,
        latest_session=latest, prices_by_symbol=groups, names=names,
        universe=dict(ranked_count=len(ranked), quality_count=len(selected),
                      inspected_count=len(groups), scope_date=scope_date),
        provenance=provenance, input_fingerprint=fingerprint,
        diagnostics=dict(input_rows=total, loaded_rows=sum(map(len, groups.values())),
                         excluded_rows=dict(excluded), source_flags=dict(flags)),
        warnings=['current_cohort_survivorship_bias', 'historical_vintage_unverified',
                  'corporate_action_adjustment_unverified', 'research_allocations_not_investment_approval'])

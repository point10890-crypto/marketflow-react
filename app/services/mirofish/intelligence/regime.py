"""L1 market-regime classifier — lookahead-safe market-breadth (MA-based).

Deterministic, no LLM, no network. For each date D, breadth is the fraction
of tickers whose current_price on D is above the simple moving average of
the prior `ma_window` days (i.e. days strictly before D). Regime label is
derived from breadth thresholds.
"""

import os
import csv
import json
from datetime import datetime, timezone

from app.utils.atomic_json import write_json_atomic

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
PRICE_HISTORY_PATH = os.path.join(REPO_ROOT, 'data', 'daily_prices.csv')
REGIME_TIMELINE_PATH = os.path.join(REPO_ROOT, 'data', 'admin_mirofish', 'intelligence', 'regime_timeline.json')

MA_WINDOW = 20
RISK_ON_BREADTH = 0.60
RISK_OFF_BREADTH = 0.40


def _safe_float(value):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f


def load_universe_prices(path=PRICE_HISTORY_PATH):
    """Load per-ticker price series from CSV, sorted by date ascending.

    Returns {ticker: [{'date': ..., 'current_price': float}, ...]}.
    Missing file -> {}. Rows with bad/missing/non-positive price are skipped.
    """
    if not os.path.isfile(path):
        return {}

    by_ticker = {}
    try:
        with open(path, 'r', encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                ticker = (row.get('ticker') or '').strip()
                date = (row.get('date') or '').strip()
                if not ticker or not date:
                    continue
                price = _safe_float(row.get('current_price'))
                if price is None or price <= 0:
                    continue
                by_ticker.setdefault(ticker, []).append({'date': date, 'current_price': price})
    except Exception:
        return {}

    for ticker, rows in by_ticker.items():
        rows.sort(key=lambda r: r['date'])

    return by_ticker


def build_regime_timeline(prices=None, *, ma_window=MA_WINDOW, write=True):
    """Build the lookahead-safe regime timeline from per-ticker price series."""
    if prices is None:
        prices = load_universe_prices()

    counts = {}  # date -> {'above': int, 'total': int}

    try:
        for ticker, rows in (prices or {}).items():
            n = len(rows)
            for i in range(n):
                if i < ma_window:
                    continue
                window = rows[i - ma_window:i]
                if len(window) < ma_window:
                    continue
                ma = sum(r['current_price'] for r in window) / ma_window
                date = rows[i]['date']
                bucket = counts.setdefault(date, {'above': 0, 'total': 0})
                bucket['total'] += 1
                if rows[i]['current_price'] > ma:
                    bucket['above'] += 1
    except Exception:
        counts = {}

    by_date = {}
    for date, c in counts.items():
        total = c['total']
        above = c['above']
        breadth = (above / total) if total > 0 else 0.0
        if breadth >= RISK_ON_BREADTH:
            label = 'RISK_ON'
        elif breadth <= RISK_OFF_BREADTH:
            label = 'RISK_OFF'
        else:
            label = 'NEUTRAL'
        by_date[date] = {
            'breadth': round(breadth, 4),
            'regime': label,
            'above': above,
            'total': total,
        }

    envelope = {
        'schema_version': 'mirofish.regime_timeline.v1',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'lookahead_safe': True,
        'ma_window': ma_window,
        'by_date': by_date,
    }

    if write:
        try:
            os.makedirs(os.path.dirname(REGIME_TIMELINE_PATH), exist_ok=True)
            write_json_atomic(REGIME_TIMELINE_PATH, envelope, sort_keys=False)
        except Exception:
            pass

    return envelope


def classify_regime(entry_date, timeline):
    """Return the regime label for entry_date, falling back to the most
    recent prior date in the timeline. Defaults to 'NEUTRAL'."""
    if not timeline or not isinstance(timeline, dict):
        return 'NEUTRAL'

    by_date = timeline.get('by_date') or {}
    if not by_date:
        return 'NEUTRAL'

    entry = by_date.get(entry_date)
    if entry:
        return entry.get('regime', 'NEUTRAL')

    candidates = [d for d in by_date.keys() if d <= entry_date]
    if not candidates:
        return 'NEUTRAL'

    latest = max(candidates)
    return by_date.get(latest, {}).get('regime', 'NEUTRAL')


def read_regime_timeline():
    """Read the regime timeline JSON file. Missing/corrupt -> None."""
    if not os.path.isfile(REGIME_TIMELINE_PATH):
        return None
    try:
        with open(REGIME_TIMELINE_PATH, 'r', encoding='utf-8-sig') as f:
            return json.load(f)
    except Exception:
        return None

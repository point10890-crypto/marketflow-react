"""예측자별 성적표. 매번 전체를 다시 계산해 같은 키에 덮어쓴다 (멱등)."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.services.forecast_league import clock, metrics

MIN_RESOLVED = 100
WINDOW_ALL = 'all'
BASELINE_ID = 'baseline_base_rate'
TOP_K = 3


def _rows(conn: sqlite3.Connection, forecaster_id: str, version: str, event_id: str) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(
        'SELECT f.stock_code, f.asof_ts, f.probability, r.status, r.outcome, r.entry_date, r.net_return '
        'FROM forecasts f LEFT JOIN resolutions r ON r.forecast_id = f.forecast_id '
        'WHERE f.forecaster_id = ? AND f.version = ? AND f.event_id = ? AND f.official = 1',
        (forecaster_id, version, event_id))]


def _brier(rows: list[dict[str, Any]]) -> float:
    return metrics.brier([(row['probability'], row['outcome']) for row in rows])


def _mean_net(rows: list[dict[str, Any]]) -> float:
    return sum(row['net_return'] for row in rows) / len(rows)


def _baseline(conn: sqlite3.Connection, forecaster_id: str, event_id: str,
              resolved: list[dict[str, Any]]) -> dict[str, Any] | None:
    if forecaster_id == BASELINE_ID:
        return None
    reference = {(row['stock_code'], row['asof_ts']): row['probability'] for row in conn.execute(
        'SELECT f.stock_code, f.asof_ts, f.probability FROM forecasts f '
        'JOIN resolutions r ON r.forecast_id = f.forecast_id '
        "WHERE f.forecaster_id = ? AND f.event_id = ? AND f.official = 1 AND r.status = 'resolved'",
        (BASELINE_ID, event_id))}
    matched = [(row, reference[(row['stock_code'], row['asof_ts'])]) for row in resolved
               if (row['stock_code'], row['asof_ts']) in reference]
    if not matched:
        return None
    own = metrics.brier([(row['probability'], row['outcome']) for row, _ in matched])
    base = metrics.brier([(probability, row['outcome']) for row, probability in matched])
    return {'forecaster_id': BASELINE_ID, 'n_matched': len(matched), 'brier_diff': own - base}


def compute_scorecards(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cards = []
    keys = conn.execute('SELECT DISTINCT forecaster_id, version, event_id FROM forecasts WHERE official = 1 '
                        'ORDER BY forecaster_id, version, event_id').fetchall()
    for key in keys:
        rows = _rows(conn, key['forecaster_id'], key['version'], key['event_id'])
        resolved = [row for row in rows if row['status'] == 'resolved']
        counts = {'n_resolved': len(resolved),
                  'n_void': sum(1 for row in rows if row['status'] == 'void'),
                  'n_pending': sum(1 for row in rows if row['status'] is None)}
        if len(resolved) < MIN_RESOLVED:
            status, body = 'insufficient', counts
        else:
            pairs = [(row['probability'], row['outcome']) for row in resolved]
            status = 'scored'
            body = {**counts,
                    'hit_rate': sum(outcome for _, outcome in pairs) / len(pairs),
                    'brier': metrics.brier(pairs),
                    'brier_ci95': list(metrics.block_bootstrap_ci(resolved, _brier)),
                    'log_loss': metrics.log_loss(pairs),
                    'calibration': metrics.calibration(pairs),
                    'top3_precision': metrics.top_k_precision(resolved, k=TOP_K),
                    'mean_net_return_pct': _mean_net(resolved),
                    'mean_net_return_ci95': list(metrics.block_bootstrap_ci(resolved, _mean_net)),
                    'baseline': _baseline(conn, key['forecaster_id'], key['event_id'], resolved)}
        conn.execute('INSERT OR REPLACE INTO scorecards VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                     (key['forecaster_id'], key['version'], key['event_id'], WINDOW_ALL, status, len(resolved),
                      json.dumps(body, sort_keys=True), clock.iso(clock.now_utc())))
        cards.append({'forecaster_id': key['forecaster_id'], 'version': key['version'],
                      'event_id': key['event_id'], 'status': status, **body})
    return cards

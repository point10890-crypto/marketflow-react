"""예측자별 성적표. 매번 전체를 다시 계산해 같은 키에 덮어쓴다 (멱등).

채점 대상은 **마감된 코호트**의 resolved 행뿐이다. 코호트 = 한 예측자·버전·이벤트에서 asof_ts 의 KST 날짜가
같은 공식 예측 묶음이고, 미청산 예측이 하나도 없을 때 마감된 것으로 본다 (void 는 코호트를 열어 두지 않고
채점도 하지 않는다). 8거래일이 안 된 날은 목표·손절 조기 청산만 먼저 resolved 되므로, 그대로 세면 적중률이
부풀기 때문이다.

- metrics_json 의 n_resolved / n_void / n_pending: 상태별 전체 건수 (코호트 마감 여부와 무관).
- metrics_json 의 n_scored: 실제 채점에 쓴 행 수. 100건 관문은 이 값에 건다.
- scorecards.n_resolved 컬럼: 이름은 그대로지만 **n_scored** (채점에 쓴 행 수)를 저장한다.
- 신뢰 구간은 진입일이 metrics.MIN_BLOCKS 개보다 적으면 null 이다 (n_entry_dates 참고).
- 기준선 비교는 가장 최근에 등록된 기준선 버전 하나에 고정하고, (종목, 같은 이벤트의 실제 진입일)로 짝을 맞춘다.
"""
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
    """공식 예측 전체. day 는 asof_ts 의 KST 날짜. 기준 시각 순으로 정렬해 재계산 결과를 고정한다."""
    rows = [dict(row) for row in conn.execute(
        'SELECT f.forecast_id, f.stock_code, f.asof_ts, f.probability, f.raw_score, '
        'r.status, r.outcome, r.entry_date, r.net_return '
        'FROM forecasts f LEFT JOIN resolutions r ON r.forecast_id = f.forecast_id '
        'WHERE f.forecaster_id = ? AND f.version = ? AND f.event_id = ? AND f.official = 1',
        (forecaster_id, version, event_id))]
    for row in rows:
        row['asof'] = clock.parse_ts(row['asof_ts'])
        row['day'] = clock.kst_date(row['asof'])
    rows.sort(key=lambda row: (row['asof'], row['forecast_id']))
    return rows


def _scored(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """마감된 코호트의 resolved 행."""
    return [row for members in metrics.closed_cohorts(rows, lambda row: row['day'])
            for row in members if row['status'] == 'resolved']


def _brier(rows: list[dict[str, Any]]) -> float:
    return metrics.brier([(row['probability'], row['outcome']) for row in rows])


def _mean_net(rows: list[dict[str, Any]]) -> float:
    return sum(row['net_return'] for row in rows) / len(rows)


def _ci(rows: list[dict[str, Any]], stat: Any) -> list[float] | None:
    interval = metrics.block_bootstrap_ci(rows, stat)
    return None if interval is None else list(interval)


def _baseline(conn: sqlite3.Connection, forecaster_id: str, event_id: str,
              scored: list[dict[str, Any]]) -> dict[str, Any] | None:
    """같은 (종목, 실제 진입일)에 기준선도 채점된 행만 놓고 본 Brier 차이. 음수면 기준선보다 낫다."""
    if forecaster_id == BASELINE_ID:
        return None
    latest = conn.execute('SELECT version FROM forecasters WHERE forecaster_id = ? '
                          'ORDER BY registered_at DESC, version DESC LIMIT 1', (BASELINE_ID,)).fetchone()
    if latest is None:
        return None
    # Compare the identical event instance, not merely the same display day.
    reference = {(row['stock_code'], row['entry_date']): row
                 for row in _scored(_rows(conn, BASELINE_ID, latest['version'], event_id))}
    matched = []
    for row in scored:
        other = reference.get((row['stock_code'], row['entry_date']))
        if other is not None and row['entry_date'] and other['outcome'] == row['outcome']:
            matched.append((row, other['probability']))
    if not matched:
        return None
    own = metrics.brier([(row['probability'], row['outcome']) for row, _ in matched])
    base = metrics.brier([(probability, row['outcome']) for row, probability in matched])
    return {'forecaster_id': BASELINE_ID, 'version': latest['version'], 'n_matched': len(matched),
            'brier_diff': own - base}


def compute_scorecards(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cards = []
    keys = conn.execute('SELECT DISTINCT forecaster_id, version, event_id FROM forecasts WHERE official = 1 '
                        'ORDER BY forecaster_id, version, event_id').fetchall()
    for key in keys:
        rows = _rows(conn, key['forecaster_id'], key['version'], key['event_id'])
        scored = _scored(rows)
        counts = {'n_resolved': sum(1 for row in rows if row['status'] == 'resolved'),
                  'n_void': sum(1 for row in rows if row['status'] == 'void'),
                  'n_pending': sum(1 for row in rows if row['status'] is None),
                  'n_scored': len(scored)}
        if len(scored) < MIN_RESOLVED:
            status, body = 'insufficient', counts
        else:
            pairs = [(row['probability'], row['outcome']) for row in scored]
            status = 'scored'
            body = {**counts,
                    'n_entry_dates': len({row['entry_date'] for row in scored}),
                    'hit_rate': sum(outcome for _, outcome in pairs) / len(pairs),
                    'brier': metrics.brier(pairs),
                    'brier_ci95': _ci(scored, _brier),
                    'log_loss': metrics.log_loss(pairs),
                    'calibration': metrics.calibration(pairs),
                    'top3_precision': metrics.top_k_precision(scored, k=TOP_K),
                    'mean_net_return_pct': _mean_net(scored),
                    'mean_net_return_ci95': _ci(scored, _mean_net),
                    'baseline': _baseline(conn, key['forecaster_id'], key['event_id'], scored)}
        conn.execute('INSERT OR REPLACE INTO scorecards VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                     (key['forecaster_id'], key['version'], key['event_id'], WINDOW_ALL, status, len(scored),
                      json.dumps(body, sort_keys=True), clock.iso(clock.now_utc())))
        cards.append({'forecaster_id': key['forecaster_id'], 'version': key['version'],
                      'event_id': key['event_id'], 'status': status, **body})
    return cards

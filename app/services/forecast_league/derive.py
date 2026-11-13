"""점수만 내는 예측자의 확률 환산 (설계서 §5.5).

표본은 코호트(예측자·버전·이벤트·asof_ts 의 KST 날짜) 단위로만 쓴다. 미청산 예측이 남아 있지 않고, 코호트의
마지막 청산일이 기준일보다 앞선 코호트만 통째로 쓴다. 조기 청산분만 먼저 세면 적중률이 부풀고, 기준일 이후에
마감된 코호트를 일부라도 쓰면 미래 정보가 섞이기 때문이다.
"""
from __future__ import annotations

import sqlite3
from bisect import bisect_right
from typing import Any, Sequence

from app.services.forecast_league import clock, metrics
from app.services.forecast_league.ledger import clamp_probability

MIN_SAMPLES = 30


def _usable(rows: Sequence[sqlite3.Row], asof_ts: str) -> list[dict[str, Any]]:
    """기준일 전에 전원 청산이 끝난 코호트의 resolved 행."""
    def cohort(row: dict[str, Any]) -> tuple[str, str, str]:
        return row['forecaster_id'], row['version'], clock.kst_date(clock.parse_ts(row['asof_ts']))

    cutoff = clock.parse_ts(asof_ts)
    asof_date = clock.kst_date(cutoff)
    known = []
    for original in rows:
        row = dict(original)
        try:
            available = clock.parse_ts(row['resolved_at']) < cutoff
        except (ValueError, TypeError, AttributeError):
            available = False
        if not available:
            row['status'] = None  # A later resolution/void cannot close an earlier cohort.
        known.append(row)
    samples: list[dict[str, Any]] = []
    for members in metrics.closed_cohorts(known, cohort):
        resolved = [row for row in members if row['status'] == 'resolved']
        if all(row['exit_date'] is not None and row['exit_date'] < asof_date for row in resolved):
            samples.extend(resolved)
    return samples


def derived_probability(conn: sqlite3.Connection, *, forecaster_id: str, version: str, event_id: str,
                        raw_score: float, asof_ts: str, bin_edges: Sequence[float],
                        fallback: float) -> tuple[float, str]:
    """(확률, 근거) 를 반환한다. 근거: score_bin / forecaster_overall / league_base_rate / fallback."""
    columns = ('SELECT f.forecaster_id, f.version, f.asof_ts, f.raw_score, r.status, r.outcome, r.exit_date, r.resolved_at '
               'FROM forecasts f LEFT JOIN resolutions r ON r.forecast_id = f.forecast_id ')
    own = [row for row in _usable(conn.execute(
        columns + 'WHERE f.forecaster_id = ? AND f.version = ? AND f.event_id = ? AND f.official = 1',
        (forecaster_id, version, event_id)).fetchall(), asof_ts) if row['raw_score'] is not None]
    target = bisect_right(bin_edges, raw_score)
    same_bin = [row['outcome'] for row in own if bisect_right(bin_edges, row['raw_score']) == target]
    if len(same_bin) >= MIN_SAMPLES:
        return clamp_probability(sum(same_bin) / len(same_bin)), 'score_bin'
    if len(own) >= MIN_SAMPLES:
        return clamp_probability(sum(row['outcome'] for row in own) / len(own)), 'forecaster_overall'
    league = _usable(conn.execute(columns + 'WHERE f.event_id = ? AND f.official = 1', (event_id,)).fetchall(),
                     asof_ts)
    if len(league) >= MIN_SAMPLES:
        return clamp_probability(sum(row['outcome'] for row in league) / len(league)), 'league_base_rate'
    return clamp_probability(fallback), 'fallback'

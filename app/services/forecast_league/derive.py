"""점수만 내는 예측자의 확률 환산 (설계서 §5.5). 기준일 이전에 청산된 표본만 쓴다."""
from __future__ import annotations

import sqlite3
from bisect import bisect_right
from typing import Sequence

from app.services.forecast_league import clock
from app.services.forecast_league.ledger import clamp_probability

MIN_SAMPLES = 30


def derived_probability(conn: sqlite3.Connection, *, forecaster_id: str, version: str, event_id: str,
                        raw_score: float, asof_ts: str, bin_edges: Sequence[float],
                        fallback: float) -> tuple[float, str]:
    """(확률, 근거) 를 반환한다. 근거: score_bin / forecaster_overall / league_base_rate / fallback."""
    asof_date = clock.kst_date(clock.parse_ts(asof_ts))
    own = conn.execute(
        'SELECT f.raw_score, r.outcome FROM forecasts f JOIN resolutions r ON r.forecast_id = f.forecast_id '
        "WHERE f.forecaster_id = ? AND f.version = ? AND f.event_id = ? AND r.status = 'resolved' "
        'AND r.exit_date < ? AND f.raw_score IS NOT NULL',
        (forecaster_id, version, event_id, asof_date)).fetchall()
    target = bisect_right(bin_edges, raw_score)
    same_bin = [row['outcome'] for row in own if bisect_right(bin_edges, row['raw_score']) == target]
    if len(same_bin) >= MIN_SAMPLES:
        return clamp_probability(sum(same_bin) / len(same_bin)), 'score_bin'
    if len(own) >= MIN_SAMPLES:
        return clamp_probability(sum(row['outcome'] for row in own) / len(own)), 'forecaster_overall'
    league = conn.execute(
        'SELECT COUNT(*) AS n, COALESCE(SUM(r.outcome), 0) AS hits FROM forecasts f '
        'JOIN resolutions r ON r.forecast_id = f.forecast_id '
        "WHERE f.event_id = ? AND f.official = 1 AND r.status = 'resolved' AND r.exit_date < ?",
        (event_id, asof_date)).fetchone()
    if league['n'] >= MIN_SAMPLES:
        return clamp_probability(league['hits'] / league['n']), 'league_base_rate'
    return clamp_probability(fallback), 'fallback'

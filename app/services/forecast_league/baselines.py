"""기준선 예측자 (설계서 §5.6). 우위는 이 둘을 이기는 것으로 정의한다.

입력은 provider_daily 봉이다. 정규장 보증이 없는 추정치이며 채점에는 쓰이지 않는다.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import Any, Iterable

from app.services.forecast_league import bars, capsules, clock, derive, events, ledger

BASE_RATE_ID = 'baseline_base_rate'
MOMENTUM_ID = 'baseline_momentum'
VERSION = '1'
EVENT_ID = 'E1'
LOOKBACK_SESSIONS = 250
MOMENTUM_SESSIONS = 20
MIN_BASE_SAMPLES = 30
MOMENTUM_BIN_EDGES = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
MIN_UNIVERSE_COVERAGE = 0.9           # 기준일 봉 수가 직전 거래일의 이 비율에 못 미치면 수집이 덜 끝난 것으로 본다


class UniverseBarsMissing(RuntimeError):
    """기준일의 유니버스 봉이 아직 없거나 일부만 있다. 수집 뒤에 다시 실행한다."""


def _bar_count(conn: sqlite3.Connection, session_date: str) -> int:
    return conn.execute('SELECT COUNT(*) FROM bars WHERE basis = ? AND session_date = ?',
                        (bars.BASIS_UNIVERSE, session_date)).fetchone()[0]


def _recent_sessions(conn: sqlite3.Connection, asof_date: str, count: int) -> list[str]:
    rows = conn.execute('SELECT DISTINCT session_date FROM bars WHERE basis = ? AND session_date <= ? '
                        'ORDER BY session_date DESC LIMIT ?', (bars.BASIS_UNIVERSE, asof_date, count)).fetchall()
    return [row[0] for row in reversed(rows)]


def _series(conn: sqlite3.Connection, start: str, end: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in conn.execute(
            'SELECT stock_code, session_date AS date, open, high, low, close FROM bars '
            'WHERE basis = ? AND session_date >= ? AND session_date <= ? ORDER BY stock_code, session_date',
            (bars.BASIS_UNIVERSE, start, end)):
        grouped[row['stock_code']].append(dict(row))
    return grouped


def universe_base_rate(conn: sqlite3.Connection, asof_date: str, *,
                       lookback: int = LOOKBACK_SESSIONS) -> dict[str, Any]:
    """직전 lookback 거래일의 전 종목 E1 적중률.

    기준일까지 뒤따르는 8거래일 봉이 모두 있는 신호일만 센다. 일찍 끝난 경로만 세면
    최근 신호일에서 만기 실패가 빠져 적중률이 부풀려진다.
    """
    sessions = _recent_sessions(conn, asof_date, lookback + events.E1_MAX_SESSIONS + 1)
    if not sessions:
        return {'rate': None, 'n': 0, 'hits': 0}
    n = hits = 0
    for series in _series(conn, sessions[0], asof_date).values():
        for signal in range(len(series) - events.E1_MAX_SESSIONS):
            result = events.evaluate_e1(series[signal + 1:signal + 1 + events.E1_MAX_SESSIONS], cost_pct=0.0)
            if result is not None:
                n += 1
                hits += result['outcome']
    return {'rate': hits / n if n else None, 'n': n, 'hits': hits}


def momentum_ranks(conn: sqlite3.Connection, asof_date: str, *,
                   sessions: int = MOMENTUM_SESSIONS) -> dict[str, float]:
    """20거래일 수익률의 유니버스 내 순위. 0 이 가장 낮고 1 이 가장 높다."""
    window = _recent_sessions(conn, asof_date, sessions + 1)
    if len(window) < sessions + 1 or window[-1] != asof_date:
        return {}
    returns = {}
    for code, series in _series(conn, window[0], asof_date).items():
        if len(series) == sessions + 1 and series[-1]['date'] == asof_date:
            returns[code] = series[-1]['close'] / series[0]['close'] - 1
    ordered = sorted(returns, key=lambda code: (returns[code], code))
    if len(ordered) < 2:
        return {}
    return {code: index / (len(ordered) - 1) for index, code in enumerate(ordered)}


def submit_baselines(conn: sqlite3.Connection, *, asof_date: str, stock_codes: Iterable[str]) -> dict[str, int]:
    n_asof = _bar_count(conn, asof_date)
    if n_asof == 0:
        raise UniverseBarsMissing(asof_date)
    previous = conn.execute('SELECT MAX(session_date) FROM bars WHERE basis = ? AND session_date < ?',
                            (bars.BASIS_UNIVERSE, asof_date)).fetchone()[0]
    n_prev = _bar_count(conn, previous) if previous else 0
    if n_prev > 0 and n_asof < MIN_UNIVERSE_COVERAGE * n_prev:
        raise UniverseBarsMissing(f'{asof_date}: {n_asof} bars, previous session {previous} has {n_prev}')
    ledger.register_forecaster(conn, BASE_RATE_ID, VERSION, 'baseline', 'native')
    ledger.register_forecaster(conn, MOMENTUM_ID, VERSION, 'baseline', 'derived')
    asof_ts = clock.close_ts(asof_date)
    asof_key = clock.iso(clock.parse_ts(asof_ts))
    base = universe_base_rate(conn, asof_date)
    ranks = momentum_ranks(conn, asof_date)
    summary = {'submitted': 0, 'abstained': 0, 'duplicate': 0}

    def already_forecast(forecaster_id: str, code: str) -> bool:
        """이미 예측이 있는 키는 시각과 무관하게 중복으로만 센다. 기권도 남기지 않는다."""
        if conn.execute('SELECT 1 FROM forecasts WHERE forecaster_id = ? AND version = ? AND stock_code = ? '
                        'AND asof_ts = ? AND event_id = ?',
                        (forecaster_id, VERSION, code, asof_key, EVENT_ID)).fetchone() is None:
            return False
        summary['duplicate'] += 1
        return True

    def abstain(forecaster_id: str, code: str, reason: str) -> None:
        if already_forecast(forecaster_id, code):
            return
        if ledger.record_abstention(conn, forecaster_id=forecaster_id, version=VERSION, stock_code=code,
                                    asof_ts=asof_ts, event_id=EVENT_ID, reason=reason):
            summary['abstained'] += 1

    def submit(forecaster_id: str, code: str, probability: float, raw_score: float | None,
               capsule: dict[str, Any]) -> None:
        if already_forecast(forecaster_id, code):
            return
        try:
            ledger.submit_forecast(conn, forecaster_id=forecaster_id, version=VERSION, stock_code=code,
                                   asof_ts=asof_ts, event_id=EVENT_ID, probability=probability,
                                   raw_score=raw_score, capsule_hash=capsules.put_capsule(conn, capsule),
                                   source_ref=f'baseline:{asof_date}')
            summary['submitted'] += 1
        except ledger.SubmissionRejected as rejected:
            if rejected.code == 'duplicate':
                summary['duplicate'] += 1
            elif rejected.code == 'late_submission':
                if ledger.record_abstention(conn, forecaster_id=forecaster_id, version=VERSION, stock_code=code,
                                            asof_ts=asof_ts, event_id=EVENT_ID, reason='late_submission'):
                    summary['abstained'] += 1
            else:
                raise

    for code in sorted(set(stock_codes)):
        if base['n'] < MIN_BASE_SAMPLES:
            abstain(BASE_RATE_ID, code, 'base_rate_insufficient')
            abstain(MOMENTUM_ID, code, 'base_rate_insufficient')
            continue
        inputs = {'asof_date': asof_date, 'price_basis': bars.BASIS_UNIVERSE,
                  'lookback_sessions': LOOKBACK_SESSIONS, 'base_rate': base}
        submit(BASE_RATE_ID, code, ledger.clamp_probability(base['rate']), None,
               {'forecaster': BASE_RATE_ID, **inputs})
        rank = ranks.get(code)
        if rank is None:
            abstain(MOMENTUM_ID, code, 'momentum_history_short')
            continue
        probability, basis = derive.derived_probability(
            conn, forecaster_id=MOMENTUM_ID, version=VERSION, event_id=EVENT_ID, raw_score=rank,
            asof_ts=asof_ts, bin_edges=MOMENTUM_BIN_EDGES, fallback=base['rate'])
        submit(MOMENTUM_ID, code, probability, rank,
               {'forecaster': MOMENTUM_ID, **inputs, 'momentum_sessions': MOMENTUM_SESSIONS,
                'rank': rank, 'universe_size': len(ranks), 'derived_from': basis})
    return summary

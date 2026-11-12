"""예측 제출과 기권 기록. 추가만 가능하고 제출 시각은 서버가 찍는다 (설계서 §5.3)."""
from __future__ import annotations

import hashlib
import math
import re
import sqlite3

from app.services.forecast_league import clock

EVENT_IDS = frozenset({'E1'})
PROBABILITY_MIN = 0.02
PROBABILITY_MAX = 0.98
_KINDS = frozenset({'engine', 'agent', 'baseline'})
_SOURCES = frozenset({'native', 'derived'})
_STOCK_CODE = re.compile(r'[0-9]{6}')


class SubmissionRejected(ValueError):
    """제출 거부. code 가 사유다."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _now():
    return clock.now_utc()


def clamp_probability(value: float) -> float:
    """환산·보정으로 계산한 확률을 제출 가능 범위로 옮긴다. 제출 함수는 범위 밖 값을 거부한다."""
    return min(PROBABILITY_MAX, max(PROBABILITY_MIN, float(value)))


def register_forecaster(conn: sqlite3.Connection, forecaster_id: str, version: str,
                        kind: str, probability_source: str) -> None:
    if kind not in _KINDS or probability_source not in _SOURCES:
        raise ValueError('unknown forecaster kind or probability source')
    row = conn.execute('SELECT kind, probability_source FROM forecasters WHERE forecaster_id = ? AND version = ?',
                       (forecaster_id, version)).fetchone()
    if row is None:
        conn.execute('INSERT INTO forecasters VALUES (?, ?, ?, ?, ?)',
                     (forecaster_id, version, kind, probability_source, clock.iso(_now())))
    elif (row['kind'], row['probability_source']) != (kind, probability_source):
        raise ValueError('a registered forecaster version cannot change; register a new version')


def _asof(asof_ts: str):
    try:
        return clock.parse_ts(asof_ts)
    except (ValueError, TypeError):
        raise SubmissionRejected('invalid_asof') from None


def submit_forecast(conn: sqlite3.Connection, *, forecaster_id: str, version: str, stock_code: str,
                    asof_ts: str, event_id: str, probability: float, capsule_hash: str,
                    raw_score: float | None = None, source_ref: str = '', official: bool = True,
                    trading_day: clock.TradingDay | None = None) -> str:
    if not isinstance(stock_code, str) or _STOCK_CODE.fullmatch(stock_code) is None:
        raise SubmissionRejected('invalid_stock_code')
    if event_id not in EVENT_IDS:
        raise SubmissionRejected('unknown_event')
    if isinstance(probability, bool) or not isinstance(probability, (int, float)) or not math.isfinite(probability):
        raise SubmissionRejected('invalid_probability')
    if not PROBABILITY_MIN <= probability <= PROBABILITY_MAX:
        raise SubmissionRejected('probability_out_of_range')
    asof = _asof(asof_ts)
    created = _now()
    if asof > created:
        raise SubmissionRejected('asof_in_future')
    if created >= clock.next_session_open_after(asof, trading_day):
        raise SubmissionRejected('late_submission')
    if conn.execute('SELECT 1 FROM forecasters WHERE forecaster_id = ? AND version = ?',
                    (forecaster_id, version)).fetchone() is None:
        raise SubmissionRejected('unknown_forecaster')
    if conn.execute('SELECT 1 FROM capsules WHERE capsule_hash = ?', (capsule_hash,)).fetchone() is None:
        raise SubmissionRejected('capsule_missing')
    asof_text = clock.iso(asof)
    key = '|'.join((forecaster_id, version, stock_code, asof_text, event_id))
    forecast_id = 'f_' + hashlib.sha256(key.encode('utf-8')).hexdigest()[:24]
    try:
        conn.execute(
            'INSERT INTO forecasts (forecast_id, forecaster_id, version, stock_code, asof_ts, event_id, '
            'probability, raw_score, capsule_hash, source_ref, official, created_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (forecast_id, forecaster_id, version, stock_code, asof_text, event_id, float(probability),
             None if raw_score is None else float(raw_score), capsule_hash, str(source_ref),
             1 if official else 0, clock.iso(created)))
    except sqlite3.IntegrityError:
        raise SubmissionRejected('duplicate') from None
    return forecast_id


def record_abstention(conn: sqlite3.Connection, *, forecaster_id: str, version: str, stock_code: str,
                      asof_ts: str, event_id: str, reason: str) -> None:
    conn.execute('INSERT OR IGNORE INTO abstentions VALUES (?, ?, ?, ?, ?, ?, ?)',
                 (forecaster_id, version, stock_code, clock.iso(_asof(asof_ts)), event_id,
                  str(reason)[:200], clock.iso(_now())))

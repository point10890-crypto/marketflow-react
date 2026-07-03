"""O'Neil 가중 상대강도 (RS Rating) — 알파 스캐너 Plan B.

시장 전체 유니버스 대비 상대강도 백분위(1~99)를 계산해
'시장 후행 반등/섹터 동조' 와 '진짜 주도주' 를 구분한다.

공식 (William O'Neil / IBD):
    weighted_return = 0.4·R_3m + 0.2·R_6m + 0.2·R_9m + 0.2·R_12m
    (상장 1년 미만 종목은 가용 구간으로 가중치 renormalize, 최소 63거래일)

설계 원칙 (intelligence 계층과 동일):
- 결정론적 · lookahead-safe · 읽기전용 (daily_prices.csv 만 사용)
- stdlib-only — pandas 불필요
- 일 1회 계산 후 data/alpha_rs_ratings.json 캐시 (스캔 5회/일 이 재사용)
- 킬스위치: MIROFISH_RS_RATING_DISABLED=1 → 점수 보정 중립화
"""

from __future__ import annotations

import csv
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

ARTIFACT_FILENAME = 'alpha_rs_ratings.json'
MIN_HISTORY_DAYS = 63  # 3개월 미만 상장 종목은 RS 산출 제외

# (lookback 거래일, O'Neil 가중치) — chronological closes 의 뒤에서 N일 전 대비 수익률
HORIZONS: tuple[tuple[int, float], ...] = (
    (63, 0.4),   # 3m
    (126, 0.2),  # 6m
    (189, 0.2),  # 9m
    (252, 0.2),  # 12m
)


def _rs_disabled() -> bool:
    return str(os.getenv('MIROFISH_RS_RATING_DISABLED', 'false')).strip().lower() in {'1', 'true', 'yes', 'y'}


def compute_weighted_return(closes: list[float]) -> float | None:
    """O'Neil 가중 수익률. closes 는 chronological (과거→현재).

    가용 구간이 3m 뿐인 신규 상장은 가중치를 renormalize.
    63거래일 미만 또는 기준가 0 이면 None.
    """
    n = len(closes)
    if n < MIN_HISTORY_DAYS + 1:
        # +1: N일 전 대비 수익률에는 N+1 개 종가 필요
        if n < MIN_HISTORY_DAYS:
            return None
    last = closes[-1]
    if not last or last <= 0:
        return None

    weighted = 0.0
    weight_sum = 0.0
    for lookback, weight in HORIZONS:
        idx = n - 1 - lookback
        if idx < 0:
            continue
        base = closes[idx]
        if not base or base <= 0:
            continue
        weighted += weight * (last / base - 1.0)
        weight_sum += weight
    if weight_sum <= 0:
        return None
    return weighted / weight_sum


def build_rs_ratings(closes_by_symbol: dict[str, list[float]]) -> dict[str, Any]:
    """유니버스 전체 가중 수익률 → 백분위 1~99 등급.

    Returns:
        {'generated_at', 'universe_size', 'rated_count', 'entries':
            {symbol: {'rs_rating': int, 'weighted_return': float, 'history_days': int}}}
    """
    weighted: dict[str, tuple[float, int]] = {}
    for symbol, closes in closes_by_symbol.items():
        wr = compute_weighted_return(closes)
        if wr is not None:
            weighted[symbol] = (wr, len(closes))

    entries: dict[str, dict[str, Any]] = {}
    rated = sorted(weighted.items(), key=lambda item: item[1][0])
    total = len(rated)
    for rank, (symbol, (wr, days)) in enumerate(rated):
        # 백분위 1~99 (IBD 방식): 최하위 1, 최상위 99
        if total > 1:
            pct = 1 + round(rank / (total - 1) * 98)
        else:
            pct = 50
        entries[symbol] = {
            'rs_rating': int(pct),
            'weighted_return': round(wr, 6),
            'history_days': days,
        }

    return {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'universe_size': len(closes_by_symbol),
        'rated_count': total,
        'entries': entries,
    }


def load_universe_closes(path: str) -> dict[str, list[float]]:
    """daily_prices.csv 전체 스캔 → 심볼별 chronological 종가 리스트.

    regime.py 의 load_universe_prices 와 동일한 접근 (stdlib csv, 단일 패스).
    """
    rows: dict[str, list[tuple[str, float]]] = {}
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                symbol = str(row.get('ticker') or '').strip().zfill(6)
                if not symbol or symbol == '000000':
                    continue
                date = str(row.get('date') or '')
                try:
                    close = float(row.get('current_price') or 0)
                except (TypeError, ValueError):
                    continue
                if close <= 0:
                    continue
                rows.setdefault(symbol, []).append((date, close))
    except (OSError, csv.Error, UnicodeDecodeError) as exc:
        logger.warning('[sector_rs] daily_prices.csv 로드 실패: %s', exc)
        return {}

    closes_by_symbol: dict[str, list[float]] = {}
    for symbol, pairs in rows.items():
        pairs.sort(key=lambda item: item[0])
        closes_by_symbol[symbol] = [close for _, close in pairs]
    return closes_by_symbol


def write_rs_artifact(path: str, payload: dict[str, Any]) -> None:
    """원자적 쓰기 (temp + replace) — 스캐너가 동시에 읽어도 부분쓰기 노출 없음."""
    directory = os.path.dirname(path) or '.'
    os.makedirs(directory, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=directory, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(temp, path)
    except OSError:
        if os.path.exists(temp):
            os.remove(temp)
        raise


def is_artifact_stale(path: str, *, max_age_hours: float = 20.0) -> bool:
    """generated_at 기준 신선도 판정. 파일 없음/파싱 실패도 stale."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            payload = json.load(f)
        generated_at = str(payload.get('generated_at') or '')
        ts = datetime.fromisoformat(generated_at)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
        return age_hours > max_age_hours
    except (OSError, ValueError, json.JSONDecodeError):
        return True


def get_rs_ratings(*, data_root: str, allow_compute: bool = True,
                   max_age_hours: float = 20.0) -> dict[str, Any]:
    """캐시 우선 RS 등급 조회. stale/누락 시 allow_compute=True 면 재계산.

    스캐너 조립부에서 호출 — 하루 첫 스캔만 CSV 전체 패스 비용(~40s)을 지불하고
    이후 4회 스캔은 캐시 재사용.
    """
    empty = {'generated_at': None, 'universe_size': 0, 'rated_count': 0, 'entries': {}}
    if _rs_disabled():
        return empty

    artifact_path = os.path.join(data_root, ARTIFACT_FILENAME)

    if not is_artifact_stale(artifact_path, max_age_hours=max_age_hours):
        try:
            with open(artifact_path, 'r', encoding='utf-8') as f:
                payload = json.load(f)
            if isinstance(payload.get('entries'), dict):
                return payload
        except (OSError, json.JSONDecodeError):
            pass

    if not allow_compute:
        return empty

    csv_path = os.path.join(data_root, 'daily_prices.csv')
    closes = load_universe_closes(csv_path)
    if not closes:
        logger.warning('[sector_rs] 유니버스 종가 없음 — RS 미산출')
        return empty
    payload = build_rs_ratings(closes)
    try:
        write_rs_artifact(artifact_path, payload)
    except OSError as exc:
        logger.warning('[sector_rs] 캐시 쓰기 실패 (메모리 결과 사용): %s', exc)
    logger.info('[sector_rs] RS 등급 재계산: universe=%d rated=%d',
                payload['universe_size'], payload['rated_count'])
    return payload


def score_rs_adjustment(entry: dict[str, Any] | None) -> dict[str, Any]:
    """스캐너 점수 보정 (pure function).

    rs>=85 → +4 (시장 주도주) / rs>=70 → +2 / rs<=30 → -4 (후행 반등 위험) / 그 외 0.
    킬스위치 활성 시 중립.
    """
    neutral = {'alpha_delta': 0.0, 'tag': None, 'rs_rating': None}
    if _rs_disabled() or not isinstance(entry, dict):
        return neutral
    try:
        rating = int(entry.get('rs_rating'))
    except (TypeError, ValueError):
        return neutral

    if rating >= 85:
        return {'alpha_delta': 4.0, 'tag': 'rs_market_leader', 'rs_rating': rating}
    if rating >= 70:
        return {'alpha_delta': 2.0, 'tag': 'rs_strong', 'rs_rating': rating}
    if rating <= 30:
        return {'alpha_delta': -4.0, 'tag': 'rs_laggard', 'rs_rating': rating}
    return {'alpha_delta': 0.0, 'tag': None, 'rs_rating': rating}

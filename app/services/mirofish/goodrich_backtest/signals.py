"""look-ahead safe 신호.

모든 함수는 순수 함수이며, 진입일 `date` 시점까지의 데이터만 읽는다.
미래 세션을 주입해도 값이 바뀌지 않는다 (테스트로 강제).
"""

from __future__ import annotations

import json
import math
import os
from typing import Any

from app.services.mirofish.goodrich_backtest.prices import PriceBook

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
RS_RATINGS_PATH = os.path.join(REPO_ROOT, 'data', 'alpha_rs_ratings.json')

NEUTRAL_RS = 50


def pullback_depth(ticker: str, date: str, book: PriceBook, *, window: int = 20) -> float:
    """최근 window 세션(당일 포함) 고점 대비 하락률(%). 고점이면 0."""
    bars = book.prior_bars(ticker, date, window)
    bar = book.bar(ticker, date)
    if bar is None:
        return 0.0
    highest = max([b.close for b in bars] + [bar.close])
    if highest <= 0:
        return 0.0
    return round((highest - bar.close) / highest * 100, 4)


def volatility_norm(ticker: str, date: str, book: PriceBook, *, window: int = 14) -> float:
    """당일 포함 최근 window+1 세션의 일간수익률 표준편차(%). 이력이 없으면 0.

    pullback_depth / overheat 와 마찬가지로 진입일 종가를 포함한다. 진입일
    종가는 랭킹 시점에 이미 알려진 값이므로 look-ahead 가 아니다.
    """
    bars = book.prior_bars(ticker, date, window)
    bar = book.bar(ticker, date)
    if bar is None:
        return 0.0
    closes = [b.close for b in bars] + [bar.close]
    rets = []
    for prev, cur in zip(closes, closes[1:]):
        if prev > 0:
            rets.append((cur / prev - 1) * 100)
    if len(rets) < 2:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return round(math.sqrt(var), 4)


def overheat(ticker: str, date: str, book: PriceBook, *, window: int = 3) -> float:
    """최근 window 세션 누적 상승률(%). 현 _score 의 문제항을 페널티로 쓰기 위한 값."""
    bars = book.prior_bars(ticker, date, window)
    bar = book.bar(ticker, date)
    if bar is None or not bars:
        return 0.0
    base = bars[0].close
    if base <= 0:
        return 0.0
    return round((bar.close / base - 1) * 100, 4)


def liquidity(ticker: str, date: str, book: PriceBook) -> float:
    """거래대금 로그 스케일 (0~1 근방). 체결 가능성 대리변수."""
    bar = book.bar(ticker, date)
    if bar is None or bar.turnover <= 0:
        return 0.0
    return round(min(math.log10(max(bar.turnover, 1)) / 14, 1.0), 4)


def load_rs_ratings(path: str | None = None) -> dict[str, Any]:
    """alpha_rs_ratings.json 로드. 없으면 빈 entries."""
    target = path or RS_RATINGS_PATH
    if not os.path.isfile(target):
        return {'entries': {}}
    try:
        with open(target, 'r', encoding='utf-8') as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {'entries': {}}
    return payload if isinstance(payload.get('entries'), dict) else {'entries': {}}


def rs_rating(ticker: str, ratings: dict[str, Any]) -> int:
    """O'Neil 상대강도 백분위(1~99). 미상은 중립 50.

    주의: alpha_rs_ratings.json 은 오늘자 스냅샷 한 장이다. 과거 세션에 그대로
    적용하면 look-ahead 이므로, 백테스트는 Task 4 에서 추가되는
    `rs_from_book()` 으로 시점별 RS 를 재계산한다. 이 함수는 라이브 경로 전용이다.
    """
    entry = (ratings or {}).get('entries', {}).get(ticker)
    if not isinstance(entry, dict):
        return NEUTRAL_RS
    try:
        return int(entry.get('rs_rating'))
    except (TypeError, ValueError):
        return NEUTRAL_RS

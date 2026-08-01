"""daily_prices.csv 로더.

`change_rate` 컬럼은 전체 1,736,800행 중 18.2% 에서만 0 이 아니다. 과거 구간은
대부분 0 이라 그대로 쓰면 유니버스가 비어버리므로, 등락률은 항상 연속 종가로
계산한다 (close_t / close_{t-1} - 1).
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from typing import Any

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
DEFAULT_PRICE_PATH = os.path.join(REPO_ROOT, 'data', 'daily_prices.csv')


@dataclass(frozen=True)
class Bar:
    date: str
    close: float
    volume: float

    @property
    def turnover(self) -> float:
        return self.close * self.volume


class PriceBook:
    """티커별 일봉 시계열. 모든 조회는 사전 계산된 인덱스를 쓴다."""

    def __init__(self, series: dict[str, list[Bar]]):
        self._series = series
        self._index: dict[str, dict[str, int]] = {
            ticker: {bar.date: i for i, bar in enumerate(bars)}
            for ticker, bars in series.items()
        }
        self.sessions: list[str] = sorted({bar.date for bars in series.values() for bar in bars})

    def tickers(self) -> list[str]:
        return sorted(self._series)

    def series(self, ticker: str) -> list[Bar]:
        return self._series.get(ticker, [])

    def bar(self, ticker: str, date: str) -> Bar | None:
        i = self._index.get(ticker, {}).get(date)
        return None if i is None else self._series[ticker][i]

    def prior_bars(self, ticker: str, date: str, count: int) -> list[Bar]:
        """date 직전 세션부터 과거로 count 개. date 자신은 포함하지 않는다."""
        i = self._index.get(ticker, {}).get(date)
        if i is None or i == 0:
            return []
        start = max(0, i - count)
        return self._series[ticker][start:i]

    def change_pct(self, ticker: str, date: str) -> float | None:
        """직전 세션 종가 대비 등락률(%). 이전 세션이 없으면 None."""
        i = self._index.get(ticker, {}).get(date)
        if i is None or i == 0:
            return None
        prev = self._series[ticker][i - 1].close
        if prev <= 0:
            return None
        return round((self._series[ticker][i].close / prev - 1) * 100, 4)

    def ledger_rows(self, ticker: str) -> list[dict[str, Any]]:
        """goodrich_ledger.evaluate_pick 이 기대하는 형태로 변환."""
        return [{'date': bar.date, 'current_price': bar.close} for bar in self._series.get(ticker, [])]


def load_prices(path: str | None = None) -> PriceBook:
    """CSV 를 1회 전체 순회해 PriceBook 을 만든다. 파일이 없으면 빈 book."""
    target = path or DEFAULT_PRICE_PATH
    raw: dict[str, list[Bar]] = {}
    if not os.path.isfile(target):
        return PriceBook({})
    with open(target, 'r', encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            ticker = str(row.get('ticker') or '').strip().zfill(6)
            date = str(row.get('date') or '').strip()
            if not ticker or not date:
                continue
            try:
                close = float(row.get('current_price') or 0)
                volume = float(row.get('volume') or 0)
            except (TypeError, ValueError):
                continue
            if close <= 0:
                continue
            raw.setdefault(ticker, []).append(Bar(date=date, close=close, volume=volume))
    for ticker in raw:
        raw[ticker].sort(key=lambda bar: bar.date)
    return PriceBook(raw)

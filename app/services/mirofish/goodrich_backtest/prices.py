"""daily_prices.csv 로더.

이 스크래퍼 출력은 신뢰할 수 없다. 실측된 결함 세 가지를 로더에서 흡수한다.

1. `change_rate` 컬럼이 1,736,800행 중 18.2% 에서만 0 이 아니다. 값이 있으면
   그것이 권위 있는 값(벤더가 공식 전일종가 대비 계산)이므로 우선 쓰고,
   없으면 연속 종가로 유도한다. 단위는 **퍼센트**다.
2. 같은 `(ticker, date)` 가 25,900건 중복된다(9개 세션, 장중 재스크랩).
   합치지 않으면 `prior_bars` 가 조회일을 과거로 돌려주고, `change_pct` 가
   같은 날을 자기와 비교하며, `evaluate_pick` 의 위치 인덱싱이 어긋난다.
   가장 늦은 `update_time` 을 남긴다.
3. 33.0% 의 행이 15:00 이전에 수집됐다 — 저장된 "종가" 가 장중 스냅샷이다.
   장중수집이 과반인 세션은 `usable_sessions()` 에서 제외한다.
"""

from __future__ import annotations

import csv
import math
import os
from dataclasses import dataclass
from typing import Any

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
DEFAULT_PRICE_PATH = os.path.join(REPO_ROOT, 'data', 'daily_prices.csv')

# 한국 정규장 종료는 15:30 이지만, 스크래퍼는 15:00 이후 배치로 돈다.
# 이보다 이른 수집은 장중 스냅샷으로 본다.
CLOSE_CAPTURE_TIME = '15:00'
MAX_INTRADAY_SHARE = 0.5


@dataclass(frozen=True, slots=True)
class Bar:
    date: str
    close: float
    volume: float
    change_rate: float | None = None

    @property
    def turnover(self) -> float:
        return self.close * self.volume


class PriceBook:
    """티커별 일봉 시계열. 모든 조회는 사전 계산된 인덱스를 쓴다."""

    def __init__(self, series: dict[str, list[Bar]], *, intraday_share: dict[str, float] | None = None):
        self._series = series
        self._index: dict[str, dict[str, int]] = {
            ticker: {bar.date: i for i, bar in enumerate(bars)}
            for ticker, bars in series.items()
        }
        self._intraday_share = intraday_share or {}
        self.sessions: list[str] = sorted({bar.date for bars in series.values() for bar in bars})

    def tickers(self) -> list[str]:
        return sorted(self._series)

    def series(self, ticker: str) -> list[Bar]:
        return list(self._series.get(ticker, ()))

    def bar(self, ticker: str, date: str) -> Bar | None:
        idx = self._index.get(ticker)
        if idx is None:
            return None
        i = idx.get(date)
        return None if i is None else self._series[ticker][i]

    def prior_bars(self, ticker: str, date: str, count: int) -> list[Bar]:
        """date 직전 세션부터 과거로 count 개. date 자신은 절대 포함하지 않는다."""
        idx = self._index.get(ticker)
        if idx is None:
            return []
        i = idx.get(date)
        if i is None:
            return []
        return self._series[ticker][max(0, i - count):i]

    def change_pct(self, ticker: str, date: str) -> float | None:
        """등락률(%). change_rate 컬럼이 있으면 그것을, 없으면 연속 종가로 유도."""
        idx = self._index.get(ticker)
        if idx is None:
            return None
        i = idx.get(date)
        if i is None:
            return None
        bar = self._series[ticker][i]
        if bar.change_rate is not None:
            return bar.change_rate
        if i == 0:
            return None
        prev = self._series[ticker][i - 1].close
        if prev <= 0:
            return None
        return round((bar.close / prev - 1) * 100, 4)

    def ledger_rows(self, ticker: str) -> list[dict[str, Any]]:
        """goodrich_ledger.evaluate_pick 이 기대하는 형태. 날짜당 정확히 한 행."""
        return [{'date': bar.date, 'current_price': bar.close} for bar in self._series.get(ticker, ())]

    def usable_sessions(self, *, max_intraday_share: float = MAX_INTRADAY_SHARE) -> list[str]:
        """장중 수집이 과반이 아닌 세션만. 저장된 종가를 믿을 수 있는 날들이다."""
        return [
            date for date in self.sessions
            if self._intraday_share.get(date, 0.0) <= max_intraday_share
        ]


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def load_prices(path: str | None = None) -> PriceBook:
    """CSV 를 1회 전체 순회해 PriceBook 을 만든다. 파일이 없으면 빈 book."""
    target = path or DEFAULT_PRICE_PATH
    if not os.path.isfile(target):
        return PriceBook({})

    # (ticker, date) -> (update_time, Bar). 가장 늦은 update_time 만 남긴다.
    latest: dict[tuple[str, str], tuple[str, Bar]] = {}
    capture: dict[str, list[int]] = {}   # date -> [장중 수집 수, 전체]

    with open(target, 'r', encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            ticker = str(row.get('ticker') or '').strip()
            date = str(row.get('date') or '').strip()
            if not ticker or not date:
                continue
            ticker = ticker.zfill(6)

            close = _finite(row.get('current_price'))
            if close is None or close <= 0:
                continue
            volume = _finite(row.get('volume')) or 0.0
            change_rate = _finite(row.get('change_rate'))
            if change_rate == 0:
                change_rate = None   # 0 은 '미기록' 과 구분되지 않는다

            update_time = str(row.get('update_time') or '')
            counts = capture.setdefault(date, [0, 0])
            counts[1] += 1
            if len(update_time) >= 16 and update_time[11:16] < CLOSE_CAPTURE_TIME:
                counts[0] += 1

            key = (ticker, date)
            previous = latest.get(key)
            if previous is None or update_time >= previous[0]:
                latest[key] = (update_time, Bar(
                    date=date, close=close, volume=volume, change_rate=change_rate,
                ))

    by_ticker: dict[str, list[Bar]] = {}
    for (ticker, _date), (_update_time, bar) in latest.items():
        by_ticker.setdefault(ticker, []).append(bar)
    for ticker in by_ticker:
        by_ticker[ticker].sort(key=lambda bar: bar.date)

    intraday_share = {
        date: (intraday / total if total else 0.0)
        for date, (intraday, total) in capture.items()
    }
    return PriceBook(by_ticker, intraday_share=intraday_share)

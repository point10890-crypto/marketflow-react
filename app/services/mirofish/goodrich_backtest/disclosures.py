"""시점 정확 공시 신호.

`engine/dart_collector.py` 는 종목코드로 **최근** 공시를 조회하는 라이브 경로다.
과거 세션에 그대로 쓰면 그 시점에 없던 공시를 보게 되므로 백테스트에 못 쓴다.
여기서는 `scripts/collect_dart_disclosures.py` 가 적재한 월별 아카이브를 읽고,
접수일자(`rcept_dt`)로 잘라 진입일 이전 공시만 노출한다.

**진입일 당일은 통째로 제외한다.** DART `list.json` 에는 시각이 없어서 16시 공시와
10시 공시를 구분할 수 없는데, 검출은 15:27 경에 일어난다. 당일을 포함하면 장 마감
후 공시가 섞여 들어온다 — 애매하면 배제가 안전하다.

키워드 사전은 운영(`engine.dart_collector`)에서 직접 import 한다. 복사해두면
운영이 키워드를 추가할 때 재현물만 조용히 뒤처진다.
"""

from __future__ import annotations

import datetime
import glob
import json
import os

from engine.dart_collector import (
    TITLE_MODERATE_KEYWORDS as MODERATE_KEYWORDS,
    TITLE_NEGATIVE_KEYWORDS as NEGATIVE_KEYWORDS,
    TITLE_STRONG_KEYWORDS as STRONG_KEYWORDS,
)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
DEFAULT_DISCLOSURE_DIR = os.path.join(REPO_ROOT, 'data', 'dart_disclosures')

STRONG_POSITIVE_SCORE = 2.0
MODERATE_POSITIVE_SCORE = 1.0
NEGATIVE_SCORE = -2.0

# 공시를 많이 낸 종목이 점수를 독식하면 랭킹이 사실상 '공시 건수 순' 이 된다.
MAX_SCORE = 3.0
MIN_SCORE = -3.0

DEFAULT_LOOKBACK_DAYS = 5


def classify(report_nm: str) -> float:
    """공시 제목 -> 방향 점수. 악재 키워드가 우선한다.

    정정공시 제목에는 여러 키워드가 섞이는데, 호재를 먼저 보면
    '유상증자결정' 이 '배당' 때문에 호재로 집계되어 부호가 뒤집힌다.
    """
    title = report_nm or ''
    if any(keyword in title for keyword in NEGATIVE_KEYWORDS):
        return NEGATIVE_SCORE
    if any(keyword in title for keyword in STRONG_KEYWORDS):
        return STRONG_POSITIVE_SCORE
    if any(keyword in title for keyword in MODERATE_KEYWORDS):
        return MODERATE_POSITIVE_SCORE
    return 0.0


class DisclosureBook:
    """티커별 (접수일자, 보고서명) 시계열. 조회는 항상 진입일 이전으로 잘린다."""

    def __init__(self, by_ticker: dict[str, list[tuple[str, str]]]):
        self._by_ticker = {
            ticker: sorted(items) for ticker, items in by_ticker.items()
        }

    def tickers(self) -> list[str]:
        return sorted(self._by_ticker)

    def prior(self, ticker: str, date: str, *,
              days: int = DEFAULT_LOOKBACK_DAYS) -> list[tuple[str, str]]:
        """[date-days, date) 구간의 공시. date 당일은 포함하지 않는다."""
        items = self._by_ticker.get(ticker)
        if not items:
            return []
        try:
            end = datetime.date.fromisoformat(date)
        except ValueError:
            return []
        begin = (end - datetime.timedelta(days=days)).strftime('%Y%m%d')
        limit = end.strftime('%Y%m%d')
        return [item for item in items if begin <= item[0] < limit]

    def score(self, ticker: str, date: str, *,
              days: int = DEFAULT_LOOKBACK_DAYS) -> float:
        """진입일 이전 공시의 방향 점수 합 (상하한 적용)."""
        total = sum(classify(name) for _, name in self.prior(ticker, date, days=days))
        return round(max(MIN_SCORE, min(MAX_SCORE, total)), 4)

    def has_negative(self, ticker: str, date: str, *,
                     days: int = DEFAULT_LOOKBACK_DAYS) -> bool:
        """악재 공시가 하나라도 있었는가 — 회피 규칙용."""
        return any(classify(name) < 0 for _, name in self.prior(ticker, date, days=days))


def load_disclosures(directory: str | None = None) -> DisclosureBook:
    """월별 JSONL 아카이브를 읽어 DisclosureBook 을 만든다. 없으면 빈 book."""
    target = directory or DEFAULT_DISCLOSURE_DIR
    by_ticker: dict[str, list[tuple[str, str]]] = {}
    if not os.path.isdir(target):
        return DisclosureBook({})

    for path in sorted(glob.glob(os.path.join(target, '*.jsonl'))):
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ticker = str(row.get('stock_code') or '').strip()
                rcept_dt = str(row.get('rcept_dt') or '').strip()
                if len(ticker) != 6 or len(rcept_dt) != 8:
                    continue
                by_ticker.setdefault(ticker, []).append(
                    (rcept_dt, str(row.get('report_nm') or ''))
                )
    return DisclosureBook(by_ticker)

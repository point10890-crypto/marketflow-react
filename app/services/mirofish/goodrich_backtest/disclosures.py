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


# ── 개선 분류기 (classify_v2) ────────────────────────────────
#
# 평면 키워드 목록(`classify`)은 반대말을 구분하지 못한다. 전체 아카이브
# 327,640건에서 호재로 분류된 51,006건 중 **27.9% 가 오분류**였다:
#
#   6,320건  매출액또는손익구조30%(대규모법인은15%)이상변동
#            -> 괄호 속 '대규모' 에 걸림. 증가인지 감소인지 제목에 없다.
#   2,995건  대규모기업집단현황공시  -> 대기업 의무 분기공시
#   2,703건  전환사채권발행결정      -> 희석인데 호재
#   2,701건  주식매수선택권부여      -> 희석인데 호재
#   2,535건  자기주식처분결정/결과   -> 매각인데 '자기주식' 으로 호재
#
# 그 결과 삼성전자가 '대규모기업집단현황공시' 때문에 강한 호재로 top3 에 올랐다.
# 여기서는 (1) 중립 목록을 먼저 걸러내고 (2) 반대말 쌍을 명시 순서로 판정한다.
# 순서가 규칙의 일부이므로 튜플로 고정한다.

# 제목만으로 방향을 알 수 없거나 의무 공시인 것들. 무엇보다 먼저 걸러낸다.
NEUTRAL_MARKERS: tuple[str, ...] = (
    '대규모기업집단현황',
    '매출액또는손익구조',
    '임원ㆍ주요주주',
    '대량보유상황보고서',
    '최대주주등소유주식변동',
    '기업설명회',
    '주주총회소집',
    '주주명부폐쇄',
    '증권발행실적보고서',
    '투자설명서',
    '일괄신고',
    '결산실적공시예고',
)

# (키워드, 점수). 앞에서 맞으면 뒤는 보지 않는다 — 반대말 쌍은 부정형을 먼저 둔다.
CLASSIFY_RULES: tuple[tuple[str, float], ...] = (
    # 계약: 해지가 체결보다 먼저
    ('공급계약해지', -2.0),
    ('계약해지', -2.0),
    ('공급계약체결', 2.0),
    ('단일판매', 2.0),
    ('수주', 2.0),
    ('납품계약', 2.0),
    # 자기주식: 처분(매각)이 취득보다 먼저
    ('자기주식처분', -1.0),
    ('자사주처분', -1.0),
    ('자기주식취득', 2.0),
    ('자사주취득', 2.0),
    ('주식소각', 2.0),
    # 지분: 양도(매각)가 취득보다 먼저
    ('출자증권양도', -1.0),
    ('타법인주식및출자증권양도', -1.0),
    ('영업양도', -1.0),
    ('출자증권취득', 1.0),
    ('타법인주식', 1.0),
    ('영업양수', 1.0),
    # 희석: 전부 악재
    ('유상증자', -2.0),
    ('전환사채', -2.0),
    ('신주인수권', -2.0),
    ('교환사채', -1.0),
    ('주식매수선택권', -1.0),
    # 파탄
    ('상장폐지', -2.0),
    ('감자', -2.0),
    ('자본감소', -2.0),
    ('부도', -2.0),
    ('파산', -2.0),
    ('회생절차', -2.0),
    ('워크아웃', -2.0),
    ('영업정지', -2.0),
    ('횡령', -2.0),
    ('배임', -2.0),
    # 주주환원
    ('무상증자', 2.0),
    ('주식배당', 2.0),
    ('배당결정', 1.0),
    ('현금ㆍ현물배당', 1.0),
    ('합병결정', 1.0),
)


def classify_v2(report_nm: str) -> float:
    """공시 제목 -> 방향 점수 (개선판).

    중립 표식을 먼저 제거한 뒤, 순서 있는 규칙으로 판정한다.
    '[기재정정]' 접두는 판정에 영향을 주지 않는다 — 정정이어도 사건은 같다.
    """
    title = (report_nm or '').strip()
    if not title:
        return 0.0
    if any(marker in title for marker in NEUTRAL_MARKERS):
        return 0.0
    for keyword, score in CLASSIFY_RULES:
        if keyword in title:
            return score
    return 0.0


class DisclosureBook:
    """티커별 (접수일자, 보고서명) 시계열. 조회는 항상 진입일 이전으로 잘린다."""

    def __init__(self, by_ticker: dict[str, list[tuple[str, str]]], *, classifier=None):
        self._by_ticker = {
            ticker: sorted(items) for ticker, items in by_ticker.items()
        }
        self._classify = classifier or classify

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
        total = sum(self._classify(name) for _, name in self.prior(ticker, date, days=days))
        return round(max(MIN_SCORE, min(MAX_SCORE, total)), 4)

    def has_negative(self, ticker: str, date: str, *,
                     days: int = DEFAULT_LOOKBACK_DAYS) -> bool:
        """악재 공시가 하나라도 있었는가 — 회피 규칙용."""
        return any(self._classify(name) < 0 for _, name in self.prior(ticker, date, days=days))


def load_disclosures(directory: str | None = None, *, classifier=None) -> DisclosureBook:
    """월별 JSONL 아카이브를 읽어 DisclosureBook 을 만든다. 없으면 빈 book."""
    target = directory or DEFAULT_DISCLOSURE_DIR
    by_ticker: dict[str, list[tuple[str, str]]] = {}
    if not os.path.isdir(target):
        return DisclosureBook({}, classifier=classifier)

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
    return DisclosureBook(by_ticker, classifier=classifier)

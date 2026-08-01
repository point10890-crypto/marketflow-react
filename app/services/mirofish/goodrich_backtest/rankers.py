"""비교 대상 랭킹 함수들.

baseline_current 는 현행 GoodrichTradingOS `_score` 의 재현이며, 개선 주장의
기준선이다. 반드시 함께 돌린다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.services.mirofish.goodrich_backtest import signals as S
from app.services.mirofish.goodrich_backtest.disclosures import DisclosureBook
from app.services.mirofish.goodrich_backtest.financials import FinancialBook
from app.services.mirofish.goodrich_backtest.prices import PriceBook
from app.services.mirofish.goodrich_backtest.universe import Candidate

# 새 항의 가중치는 기존 momentum 항(+-12점)과 사거리를 맞춘 값이다.
# 공시 -3~+3 -> +-9점, 재무 -3~+2 -> -9~+6점. 임의로 크게 잡아 신호를
# 지배하게 만들면 백테스트가 '가중치를 튜닝했는가' 를 재게 된다.
DISCLOSURE_WEIGHT = 3.0
FINANCIAL_WEIGHT = 3.0


@dataclass(frozen=True)
class RankContext:
    date: str
    book: PriceBook
    rs_ratings: dict[str, int]
    # 공시·재무는 선택 주입이다. 아카이브가 없으면 None 이고, 이를 쓰는 랭커는
    # 중립(0)으로 떨어져 baseline 과 같아진다 — 데이터 부재가 감점이 되면 안 된다.
    disclosures: DisclosureBook | None = None
    financials: FinancialBook | None = None

    def disclosure_score(self, symbol: str) -> float:
        return 0.0 if self.disclosures is None else self.disclosures.score(symbol, self.date)

    def financial_score(self, symbol: str) -> float:
        return 0.0 if self.financials is None else self.financials.health_score(symbol, self.date)


Ranker = Callable[[Candidate, RankContext], float]


def baseline_current(candidate: Candidate, ctx: RankContext) -> float:
    """현행 _score 재현.

    원본 (2026-08-01 miniPC 에서 대조 확인,
    `C:\\GoodrichTradingOS\\services\\api\\src\\goodrich\\fund_manager.py::_score`):

        day_range      = max(high - low, 1)
        range_position = (price - low) / day_range
        momentum       = max(min(change_rate, 15), -15)
        liquidity      = min(log10(max(trading_value, 1)) / 14, 1)
        return round(50 + range_position*25 + momentum*0.8 + liquidity*20, 2)

    네 항 모두 원본과 동일하다. range_position 은 CSV 의 high/low 로 복원한다
    (충전율 97.4%). 고저가 없는 봉만 1.0 으로 대체한다.

    이전 버전은 range_position 을 항상 1.0 으로 고정했는데, 원장 대조 결과
    그 항의 실측 산포가 8.58점이었다 — 상수로 바꾸면 순위를 가르는 항 하나를
    잃는다. 실제로 그때는 운영 top3 와 단 한 종목도 겹치지 않았다.
    """
    momentum = max(min(candidate.change_pct, 15), -15)
    liquidity = S.liquidity(candidate.symbol, ctx.date, ctx.book)
    bar = ctx.book.bar(candidate.symbol, ctx.date)
    position = None if bar is None else bar.range_position
    if position is None:
        position = 1.0
    return round(50 + position * 25 + momentum * 0.8 + liquidity * 20, 2)


def rs_led(candidate: Candidate, ctx: RankContext) -> float:
    """상대강도 주도 + 유동성 가산."""
    rs = ctx.rs_ratings.get(candidate.symbol, S.NEUTRAL_RS)
    liquidity = S.liquidity(candidate.symbol, ctx.date, ctx.book)
    return round(rs + liquidity * 10, 4)


def pullback(candidate: Candidate, ctx: RankContext) -> float:
    """눌림목 선호 — 과열도를 감점한다."""
    depth = S.pullback_depth(candidate.symbol, ctx.date, ctx.book, window=20)
    heat = S.overheat(candidate.symbol, ctx.date, ctx.book, window=3)
    rs = ctx.rs_ratings.get(candidate.symbol, S.NEUTRAL_RS)
    return round(rs * 0.5 + depth * 1.5 - heat * 1.0, 4)


def low_volatility(candidate: Candidate, ctx: RankContext) -> float:
    """변동성 대비 유동성 — 폭탄 회피형.

    spec §5.3 은 수급 연속성(flow_persistence)도 신호로 열거하지만,
    `all_institutional_trend_data.csv` 는 티커당 1행 스냅샷이라 과거 시점 값을
    복원할 수 없다. 스냅샷을 과거 세션에 적용하면 look-ahead 이므로 이 랭커는
    수급을 쓰지 않는다. 수급 신호는 시계열 적재가 생긴 뒤에 다룬다.
    """
    volatility = S.volatility_norm(candidate.symbol, ctx.date, ctx.book, window=14)
    liquidity = S.liquidity(candidate.symbol, ctx.date, ctx.book)
    penalty = min(volatility, 20.0)
    return round(liquidity * 50 - penalty * 2.0, 4)


def composite(candidate: Candidate, ctx: RankContext) -> float:
    """위 신호들의 단순 결합. 파라미터를 늘리지 않는다."""
    rs = ctx.rs_ratings.get(candidate.symbol, S.NEUTRAL_RS)
    depth = S.pullback_depth(candidate.symbol, ctx.date, ctx.book, window=20)
    heat = S.overheat(candidate.symbol, ctx.date, ctx.book, window=3)
    volatility = S.volatility_norm(candidate.symbol, ctx.date, ctx.book, window=14)
    liquidity = S.liquidity(candidate.symbol, ctx.date, ctx.book)
    return round(
        rs * 0.4 + depth * 0.8 - heat * 0.8 - min(volatility, 20.0) * 1.0 + liquidity * 20,
        4,
    )


def disclosure_led(candidate: Candidate, ctx: RankContext) -> float:
    """현행 점수 + 공시 근거.

    가설: 같은 급등이라도 공급계약·자사주 같은 공시가 뒤를 받치는 상승은
    근거 없는 상승보다 되돌림이 덜하다. 현 점수의 문제는 '왜 올랐는지' 를
    전혀 보지 않는 것이므로, 그 축을 하나 더한다.
    """
    return round(
        baseline_current(candidate, ctx)
        + ctx.disclosure_score(candidate.symbol) * DISCLOSURE_WEIGHT,
        2,
    )


def fundamental_guard(candidate: Candidate, ctx: RankContext) -> float:
    """현행 점수 + 재무 건전성.

    알파를 더하는 항이 아니라 **회피** 항이다. 자본잠식·고레버리지·영업적자
    종목은 같은 급등이어도 되돌림이 급하다.
    """
    return round(
        baseline_current(candidate, ctx)
        + ctx.financial_score(candidate.symbol) * FINANCIAL_WEIGHT,
        2,
    )


def fusion(candidate: Candidate, ctx: RankContext) -> float:
    """현행 점수 + 공시 + 재무. 파라미터를 더 늘리지 않는다."""
    return round(
        baseline_current(candidate, ctx)
        + ctx.disclosure_score(candidate.symbol) * DISCLOSURE_WEIGHT
        + ctx.financial_score(candidate.symbol) * FINANCIAL_WEIGHT,
        2,
    )


RANKERS: dict[str, Ranker] = {
    'baseline_current': baseline_current,
    'rs_led': rs_led,
    'pullback': pullback,
    'low_volatility': low_volatility,
    'composite': composite,
    'disclosure_led': disclosure_led,
    'fundamental_guard': fundamental_guard,
    'fusion': fusion,
}


def rank_candidates(
    candidates: list[Candidate],
    ranker: Ranker,
    ctx: RankContext,
) -> list[tuple[Candidate, float]]:
    """점수 내림차순. 동점은 symbol 오름차순으로 깨서 결정적으로 만든다."""
    scored = [(candidate, ranker(candidate, ctx)) for candidate in candidates]
    return sorted(scored, key=lambda pair: (-pair[1], pair[0].symbol))

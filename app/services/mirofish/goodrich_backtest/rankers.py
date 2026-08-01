"""비교 대상 랭킹 함수들.

baseline_current 는 현행 GoodrichTradingOS `_score` 의 재현이며, 개선 주장의
기준선이다. 반드시 함께 돌린다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.services.mirofish.goodrich_backtest import signals as S
from app.services.mirofish.goodrich_backtest.prices import PriceBook
from app.services.mirofish.goodrich_backtest.universe import Candidate


@dataclass(frozen=True)
class RankContext:
    date: str
    book: PriceBook
    rs_ratings: dict[str, int]


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

    momentum 클램프(±15)와 liquidity 변환은 원본과 **문자 그대로 동일**하다.
    유일한 차이는 range_position 이다 — 일봉에는 장중 고저가 없어 1.0 으로
    고정한다. 이는 종가=당일 고가를 가정하는 것이라 baseline 을 최대로
    유리하게 잡는 방향이며, 따라서 개선 주장이 과대평가되지 않는다.
    """
    momentum = max(min(candidate.change_pct, 15), -15)
    liquidity = S.liquidity(candidate.symbol, ctx.date, ctx.book)
    return round(50 + 1.0 * 25 + momentum * 0.8 + liquidity * 20, 2)


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


RANKERS: dict[str, Ranker] = {
    'baseline_current': baseline_current,
    'rs_led': rs_led,
    'pullback': pullback,
    'low_volatility': low_volatility,
    'composite': composite,
}


def rank_candidates(
    candidates: list[Candidate],
    ranker: Ranker,
    ctx: RankContext,
) -> list[tuple[Candidate, float]]:
    """점수 내림차순. 동점은 symbol 오름차순으로 깨서 결정적으로 만든다."""
    scored = [(candidate, ranker(candidate, ctx)) for candidate in candidates]
    return sorted(scored, key=lambda pair: (-pair[1], pair[0].symbol))

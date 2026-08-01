"""과거 세션의 Goodrich 후보 유니버스를 일봉으로 재현.

라이브 kis_screener 는 세 개 순위 API 를 합집합으로 쓴다:
  - fetch_volume_rank(token, "3")  거래대금 순위   -> close * volume
  - fetch_fluctuation_rank(token)  등락률 순위     -> 연속 종가 등락률
  - fetch_volume_rank(token, "1")  거래량 급증     -> volume / 20일 평균거래량

goodrich_client 는 여기에 change_pct > 0 필터를 적용한다. 재현도 동일하게 맞춘다.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass

from app.services.mirofish.goodrich_backtest.prices import PriceBook

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
DEFAULT_TICKER_MAP_PATH = os.path.join(REPO_ROOT, 'data', 'ticker_to_yahoo_map.csv')

VOLUME_SURGE_WINDOW = 20

# 한국 가격제한폭은 ±30%. 이를 넘는 일간 변동은 체결로 발생할 수 없으므로
# 데이터 오류다 (실측 616건 / 466종목). 1%p 여유를 둔다.
MAX_DAILY_MOVE_PCT = 31.0

# 상한가로 잠긴 종목은 종가에 매수할 수 없다 — 매도 호가가 없다.
# 실측: 등락률 >= 29% 인 후보 200건 중 199건이 종가 == 고가 였고,
# 등락률은 29.8~30.0% 에 몰려 있다(제한폭 서명).
#
# 이 종목들을 남겨두면 랭킹 함수가 그쪽으로 쏠린다. 종가가 고가와 같으면
# range_position 이 정확히 1.0 이 되어 최대 배점(25점)을 받기 때문이다.
# 실제로 baseline 픽의 81.8% 가 상한가였고 초과수익 +4.18% 를 기록했는데,
# 이는 살 수 없는 가격으로 계산된 수익이다. 체결 가능성은 랭커의 성질이
# 아니라 시장의 성질이므로 유니버스 단계에서 모두에게 동일하게 적용한다.
LIMIT_LOCK_PCT = 29.0


@dataclass(frozen=True)
class Candidate:
    symbol: str
    date: str
    close: float
    volume: float
    change_pct: float
    turnover: float
    volume_surge: float
    market: str = ''


def load_markets(path: str | None = None) -> dict[str, str]:
    """티커 -> 시장(KOSPI/KOSDAQ). 벤치마크 지수를 고르는 데 쓴다.

    원장이 `market` 을 기록하지 않아 코스닥 종목까지 KOSPI 지수와 비교되던 결함이
    있었다. 백테스트에서는 같은 실수를 반복하지 않는다.
    """
    target = path or DEFAULT_TICKER_MAP_PATH
    if not os.path.isfile(target):
        return {}
    out: dict[str, str] = {}
    with open(target, 'r', encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            ticker = str(row.get('ticker') or '').strip().zfill(6)
            market = str(row.get('market') or '').strip().upper()
            if ticker and market:
                out[ticker] = market
    return out


def is_limit_locked(bar, change_pct: float) -> bool:
    """상한가로 잠겨 종가 매수가 불가능한 봉인가.

    서명은 '제한폭 근처 상승 + 종가 == 고가' 다. 고저가 없으면 판단 근거가
    없으므로 배제하지 않는다(과잉 제거 방지).
    """
    if change_pct < LIMIT_LOCK_PCT:
        return False
    if bar.high is None:
        return False
    return bar.close >= bar.high


def reconstruct_universe(
    date: str,
    book: PriceBook,
    *,
    per_source_top_n: int = 30,
    markets: dict[str, str] | None = None,
) -> list[Candidate]:
    """date 세션의 후보 유니버스. per_source_top_n 은 소스별 상위 N (합집합)."""
    market_by_ticker = markets if markets is not None else load_markets()
    rows: list[Candidate] = []
    for ticker in book.tickers():
        bar = book.bar(ticker, date)
        if bar is None:
            continue
        change = book.change_pct(ticker, date)
        if change is None:
            continue
        if abs(change) > MAX_DAILY_MOVE_PCT:
            continue  # 가격제한폭 초과 = 데이터 오류
        if is_limit_locked(bar, change):
            continue  # 상한가 잠김 = 종가 매수 불가
        prior = book.prior_bars(ticker, date, VOLUME_SURGE_WINDOW)
        avg_volume = sum(b.volume for b in prior) / len(prior) if prior else 0.0
        surge = bar.volume / avg_volume if avg_volume > 0 else 0.0
        rows.append(Candidate(
            symbol=ticker,
            date=date,
            close=bar.close,
            volume=bar.volume,
            change_pct=change,
            turnover=bar.turnover,
            volume_surge=surge,
            market=market_by_ticker.get(ticker, ''),
        ))

    if not rows:
        return []

    def top(key, n):
        # 동점은 symbol 오름차순으로 깨서 결정적으로 만든다.
        return sorted(rows, key=lambda c: (-key(c), c.symbol))[:n]

    selected = {}
    for candidate in (
        top(lambda c: c.turnover, per_source_top_n)
        + top(lambda c: c.change_pct, per_source_top_n)
        + top(lambda c: c.volume_surge, per_source_top_n)
    ):
        if candidate.change_pct > 0:
            selected[candidate.symbol] = candidate

    return [selected[symbol] for symbol in sorted(selected)]

"""백테스트 실행 + 유의성 판정.

평가는 goodrich_ledger.evaluate_pick 을 재사용한다 — look-ahead 차단,
날짜 정렬 벤치마크, 왕복 비용 로직이 이미 검증돼 있으므로 중복 구현하지 않는다.

유효 표본은 픽 수가 아니라 **진입일 수**다. 같은 날 픽들은 같은 시장 충격을
공유하므로, 부트스트랩은 진입일 단위로 블록 재표집한다.
"""

from __future__ import annotations

import random
import statistics
from typing import Any

from app.services.mirofish import goodrich_ledger as ledger
from app.services.mirofish.goodrich_backtest import rankers as R
from app.services.mirofish.goodrich_backtest import signals as S
from app.services.mirofish.goodrich_backtest.disclosures import classify_v2, load_disclosures
from app.services.mirofish.goodrich_backtest.financials import load_financials
from app.services.mirofish.goodrich_backtest.prices import PriceBook
from app.services.mirofish.goodrich_backtest.universe import (
    MAX_DAILY_MOVE_PCT,
    Candidate,
    load_markets,
    reconstruct_universe,
)


def split_dates(dates: list[str], *, holdout_start: str) -> tuple[list[str], list[str]]:
    """holdout_start 이상은 holdout. 후보 선정에 쓰지 않는다."""
    train = [d for d in dates if d < holdout_start]
    holdout = [d for d in dates if d >= holdout_start]
    return train, holdout


def benchmark_for(candidate: Candidate) -> str:
    """후보의 시장에 맞는 지수 프록시. ledger 의 해석기를 그대로 쓴다."""
    return ledger.benchmark_ticker({'market': candidate.market})


def has_clean_path(book: PriceBook, ticker: str, entry_date: str, exit_date: str) -> bool:
    """보유 구간 [entry_date, exit_date] 안에 가격제한폭 초과가 없는지.

    universe 필터는 진입일 등락률만 본다. 출구 가격이 오염된 경우
    (예: 2,080 -> 610,000) 가짜 수익이 평균을 지배하므로 여기서 한 번 더 막는다.
    """
    window = [
        bar for bar in book.series(ticker)
        if entry_date <= bar.date <= exit_date
    ]
    for prev, cur in zip(window, window[1:]):
        if prev.close <= 0:
            return False
        if abs(cur.close / prev.close - 1) * 100 > MAX_DAILY_MOVE_PCT:
            return False
    return True


def run_ranker(
    ranker_name: str,
    dates: list[str],
    book: PriceBook,
    *,
    top_k: int = 3,
    horizon: int = 3,
    per_source_top_n: int = 30,
) -> dict[str, list[float]]:
    """진입일별 TOP-k 픽의 초과수익(%) 목록.

    반환: {진입일: [초과수익, ...]}  — 평가 불가한 픽은 제외한다.
    """
    ranker = R.RANKERS[ranker_name]
    markets = load_markets()
    # 공시·재무 아카이브는 한 번만 읽는다. 없으면 빈 book 이 되고, 이를 쓰는
    # 랭커는 중립으로 떨어져 baseline 과 같아진다.
    # v1(운영 사전)은 호재 판정의 27.9% 가 오분류였다 — '대규모기업집단현황공시'
    # 같은 의무 공시와 전환사채 발행 같은 희석 이벤트가 호재로 잡혔다.
    # v2 로 바꾸면 호재 픽이 절반으로 줄면서 평균 초과수익은 +1.29% -> +2.96% 가 된다.
    disclosure_book = load_disclosures(classifier=classify_v2)
    financial_book = load_financials()
    benchmark_cache: dict[str, list[dict[str, Any]]] = {}
    out: dict[str, list[float]] = {}

    for date in dates:
        candidates = reconstruct_universe(
            date, book, per_source_top_n=per_source_top_n, markets=markets,
        )
        if len(candidates) < top_k:
            continue
        ctx = R.RankContext(
            date=date, book=book, rs_ratings=S.rs_from_book(date, book),
            disclosures=disclosure_book, financials=financial_book,
        )
        picks = R.rank_candidates(candidates, ranker, ctx)[:top_k]

        values = []
        for candidate, _score in picks:
            ticker = benchmark_for(candidate)
            if ticker not in benchmark_cache:
                benchmark_cache[ticker] = book.ledger_rows(ticker)
            evaluation = ledger.evaluate_pick(
                {
                    'symbol': candidate.symbol,
                    'entry_date': date,
                    'entry_price': candidate.close,
                    'cycle_id': f'bt_{date}',
                    'market': candidate.market,
                },
                book.ledger_rows(candidate.symbol),
                benchmark_cache[ticker],
                horizons=(horizon,),
            )
            row = (evaluation.get('horizons') or {}).get(str(horizon)) or {}
            excess = row.get('net_excess_return_pct')
            exit_date = str(row.get('exit_date') or '')
            if excess is None or not exit_date:
                continue
            if not has_clean_path(book, candidate.symbol, date, exit_date):
                continue  # 보유 구간에 데이터 오류 -> 수익률을 신뢰할 수 없다
            values.append(float(excess))
        if values:
            out[date] = values
    return out


def paired_daily_diff(
    challenger: dict[str, list[float]],
    baseline: dict[str, list[float]],
) -> dict[str, list[float]]:
    """같은 진입일에서 (신규 평균 - baseline 평균). 양쪽에 있는 날만 쓴다."""
    diffs: dict[str, list[float]] = {}
    for date in sorted(set(challenger) & set(baseline)):
        a, b = challenger[date], baseline[date]
        if a and b:
            diffs[date] = [statistics.mean(a) - statistics.mean(b)]
    return diffs


def bootstrap_interval(
    diffs_by_day: dict[str, list[float]],
    *,
    iterations: int = 2000,
    seed: int = 20260731,
    confidence: float = 0.95,
) -> tuple[float, float] | None:
    """진입일 블록 부트스트랩 신뢰구간. 입력이 비면 None."""
    days = sorted(diffs_by_day)
    if not days:
        return None
    rng = random.Random(seed)
    n = len(days)
    means = []
    for _ in range(iterations):
        sample = []
        for _ in range(n):
            sample.extend(diffs_by_day[days[rng.randrange(n)]])
        if sample:
            means.append(statistics.mean(sample))
    if not means:
        return None
    means.sort()
    tail = (1 - confidence) / 2
    lo = means[int(tail * (len(means) - 1))]
    hi = means[int((1 - tail) * (len(means) - 1))]
    return round(lo, 4), round(hi, 4)


def verdict(interval: tuple[float, float] | None) -> str:
    """구간이 0 을 배제할 때만 판정한다."""
    if interval is None:
        return 'inconclusive'
    lo, hi = interval
    if lo > 0:
        return 'improved'
    if hi < 0:
        return 'worse'
    return 'inconclusive'


def compare(
    challenger_name: str,
    dates: list[str],
    book: PriceBook,
    *,
    top_k: int = 3,
    horizon: int = 3,
    baseline: dict[str, list[float]] | None = None,
) -> dict[str, Any]:
    """challenger 를 baseline_current 와 같은 조건에서 비교한다.

    baseline 을 넘기면 재사용한다. 같은 (구간, horizon) 에서 challenger 4종을
    비교할 때 baseline 을 4번 다시 돌릴 이유가 없다 — 결과도 동일하다.
    """
    challenger = run_ranker(challenger_name, dates, book, top_k=top_k, horizon=horizon)
    if baseline is None:
        baseline = run_ranker('baseline_current', dates, book, top_k=top_k, horizon=horizon)
    diffs = paired_daily_diff(challenger, baseline)
    interval = bootstrap_interval(diffs)

    def mean_of(bucket: dict[str, list[float]]) -> float | None:
        flat = [v for values in bucket.values() for v in values]
        return round(statistics.mean(flat), 4) if flat else None

    return {
        'ranker': challenger_name,
        'horizon_days': horizon,
        'entry_days': len(diffs),
        'challenger_mean_excess_pct': mean_of(challenger),
        'baseline_mean_excess_pct': mean_of(baseline),
        'diff_ci95': interval,
        'verdict': verdict(interval),
    }

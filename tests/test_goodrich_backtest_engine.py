"""engine.py — 백테스트 실행 + 유의성 판정 단위 테스트."""
from app.services.mirofish.goodrich_backtest import engine as E


def test_block_bootstrap_interval_excludes_zero_for_clear_shift():
    # 매 진입일 신규가 baseline 을 앞서되 폭은 날마다 다르다.
    # 값이 전부 같으면 어떤 재표집도 같은 평균을 내므로 구간이 한 점으로
    # 붕괴해 hi > lo 를 만족할 수 없다.
    diffs_by_day = {
        f'2024-01-{d:02d}': [1.0 + (d % 3) * 0.5]
        for d in range(1, 29)
    }

    lo, hi = E.bootstrap_interval(diffs_by_day, iterations=500, seed=7)

    assert lo > 0
    assert hi > lo


def test_block_bootstrap_interval_includes_zero_for_noise():
    diffs_by_day = {
        f'2024-01-{d:02d}': [5.0 if d % 2 else -5.0]
        for d in range(1, 29)
    }

    lo, hi = E.bootstrap_interval(diffs_by_day, iterations=500, seed=7)

    assert lo < 0 < hi


def test_bootstrap_is_reproducible_with_same_seed():
    diffs_by_day = {f'2024-01-{d:02d}': [float(d % 5) - 2] for d in range(1, 29)}

    first = E.bootstrap_interval(diffs_by_day, iterations=300, seed=11)
    second = E.bootstrap_interval(diffs_by_day, iterations=300, seed=11)

    assert first == second


def test_bootstrap_returns_none_for_empty_input():
    assert E.bootstrap_interval({}, iterations=100, seed=1) is None


def test_verdict_requires_interval_to_exclude_zero():
    assert E.verdict((0.4, 1.2)) == 'improved'
    assert E.verdict((-1.2, -0.4)) == 'worse'
    assert E.verdict((-0.3, 0.9)) == 'inconclusive'
    assert E.verdict(None) == 'inconclusive'


def test_split_dates_reserves_holdout():
    """holdout_start 당일은 holdout 쪽이다 (경계 포함)."""
    dates = ['2025-08-29', '2025-09-04', '2026-07-31']

    train, holdout = E.split_dates(dates, holdout_start='2025-09-04')

    assert train == ['2025-08-29']
    assert holdout == ['2025-09-04', '2026-07-31']


def test_corrupt_price_path_is_rejected_so_fake_returns_never_enter():
    """진입은 정상이어도 보유 구간에 가격제한폭 초과가 있으면 그 픽을 버린다.

    예) 2,080 -> 610,000 같은 오류가 출구가 되면 +29,000% 수익이 평균을 지배한다.
    """
    from app.services.mirofish.goodrich_backtest.prices import Bar, PriceBook

    clean = PriceBook({'000001': [
        Bar(date='2024-01-02', close=100, volume=10),
        Bar(date='2024-01-03', close=105, volume=10),
        Bar(date='2024-01-04', close=110, volume=10),
    ]})
    dirty = PriceBook({'000001': [
        Bar(date='2024-01-02', close=100, volume=10),
        Bar(date='2024-01-03', close=105, volume=10),
        Bar(date='2024-01-04', close=99999, volume=10),
    ]})

    assert E.has_clean_path(clean, '000001', '2024-01-02', '2024-01-04') is True
    assert E.has_clean_path(dirty, '000001', '2024-01-02', '2024-01-04') is False


def test_clean_path_ignores_sessions_outside_the_holding_window():
    from app.services.mirofish.goodrich_backtest.prices import Bar, PriceBook

    book = PriceBook({'000001': [
        Bar(date='2024-01-02', close=100, volume=10),
        Bar(date='2024-01-03', close=105, volume=10),
        Bar(date='2024-01-04', close=99999, volume=10),  # 보유 구간 밖
    ]})

    assert E.has_clean_path(book, '000001', '2024-01-02', '2024-01-03') is True


def test_benchmark_follows_the_candidate_market():
    """코스닥 종목을 KOSPI 지수와 비교하던 원장 결함을 백테스트가 반복하지 않는다."""
    from app.services.mirofish.goodrich_backtest.universe import Candidate

    def _c(symbol, market):
        return Candidate(symbol=symbol, date='2024-01-03', close=100.0, volume=10,
                         change_pct=1.0, turnover=1000.0, volume_surge=1.0, market=market)

    assert E.benchmark_for(_c('000001', 'KOSPI')) == '069500'
    assert E.benchmark_for(_c('000002', 'KOSDAQ')) == '229200'
    assert E.benchmark_for(_c('000003', '')) == '069500'  # 미상은 대표지수

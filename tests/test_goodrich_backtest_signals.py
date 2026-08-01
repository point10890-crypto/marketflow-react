"""signals.py — look-ahead safe 신호 단위 테스트."""
from app.services.mirofish.goodrich_backtest.prices import Bar, PriceBook
from app.services.mirofish.goodrich_backtest import signals as S


def _book(bars, ticker='000001'):
    return PriceBook({ticker: [Bar(date=d, close=c, volume=v) for d, c, v in bars]})


def test_pullback_depth_is_zero_at_the_high():
    bars = [(f'2024-01-{d:02d}', 100 + d, 10) for d in range(2, 12)]
    book = _book(bars)

    # 마지막 세션이 구간 최고가이므로 눌림 깊이 0
    assert S.pullback_depth('000001', '2024-01-11', book, window=10) == 0.0


def test_pullback_depth_measures_drop_from_prior_high():
    bars = [('2024-01-02', 100, 10), ('2024-01-03', 200, 10), ('2024-01-04', 150, 10)]
    book = _book(bars)

    # 직전 고점 200 대비 150 -> 25% 하락
    assert S.pullback_depth('000001', '2024-01-04', book, window=10) == 25.0


def test_volatility_norm_uses_prior_sessions_only():
    bars = [('2024-01-02', 100, 10), ('2024-01-03', 110, 10), ('2024-01-04', 100, 10)]
    book = _book(bars)

    value = S.volatility_norm('000001', '2024-01-04', book, window=10)

    assert value > 0


def test_overheat_sums_recent_gains():
    bars = [('2024-01-02', 100, 10), ('2024-01-03', 110, 10), ('2024-01-04', 121, 10)]
    book = _book(bars)

    # 2일간 +10%, +10% => 약 20%
    assert 19.0 <= S.overheat('000001', '2024-01-04', book, window=2) <= 21.0


def test_liquidity_grows_with_turnover():
    small = _book([('2024-01-02', 100, 10), ('2024-01-03', 100, 10)])
    large = _book([('2024-01-02', 100, 10), ('2024-01-03', 100, 1_000_000)])

    assert S.liquidity('000001', '2024-01-03', large) > S.liquidity('000001', '2024-01-03', small)


def test_signals_ignore_future_sessions():
    """look-ahead 회귀 — 미래 세션을 덧붙여도 값이 변하면 안 된다."""
    base = [('2024-01-02', 100, 10), ('2024-01-03', 110, 10), ('2024-01-04', 120, 10)]
    future = base + [('2024-01-05', 500, 999), ('2024-01-08', 900, 999)]

    book_a = _book(base)
    book_b = _book(future)

    for fn in (S.pullback_depth, S.volatility_norm, S.overheat):
        assert fn('000001', '2024-01-04', book_a) == fn('000001', '2024-01-04', book_b), fn.__name__
    assert S.liquidity('000001', '2024-01-04', book_a) == S.liquidity('000001', '2024-01-04', book_b)


def test_missing_history_returns_neutral_defaults():
    book = _book([('2024-01-02', 100, 10)])

    assert S.pullback_depth('000001', '2024-01-02', book) == 0.0
    assert S.volatility_norm('000001', '2024-01-02', book) == 0.0
    assert S.overheat('000001', '2024-01-02', book) == 0.0


def test_rs_rating_reads_artifact_and_defaults_when_absent():
    ratings = {'entries': {'000001': {'rs_rating': 88}}}

    assert S.rs_rating('000001', ratings) == 88
    assert S.rs_rating('999999', ratings) == 50  # 미상은 중립


def test_rs_from_book_ranks_stronger_performer_higher():
    from app.services.mirofish.goodrich_backtest.prices import Bar, PriceBook

    # 3개월(63세션) 이상 필요하므로 70세션을 만든다.
    dates = [f'2024-{(i // 20) + 1:02d}-{(i % 20) + 1:02d}' for i in range(70)]
    strong = [Bar(date=d, close=100 + i * 2, volume=10) for i, d in enumerate(dates)]
    weak = [Bar(date=d, close=100 - i * 0.5, volume=10) for i, d in enumerate(dates)]
    book = PriceBook({'000001': strong, '000002': weak})

    ratings = S.rs_from_book(dates[-1], book)

    assert ratings['000001'] > ratings['000002']
    assert 1 <= ratings['000002'] <= 99


def test_rs_from_book_excludes_short_history():
    from app.services.mirofish.goodrich_backtest.prices import Bar, PriceBook

    dates = [f'2024-01-{i + 1:02d}' for i in range(10)]
    book = PriceBook({'000001': [Bar(date=d, close=100 + i, volume=10) for i, d in enumerate(dates)]})

    assert S.rs_from_book(dates[-1], book) == {}


def test_rs_from_book_ignores_future_sessions():
    from app.services.mirofish.goodrich_backtest.prices import Bar, PriceBook

    dates = [f'2024-{(i // 20) + 1:02d}-{(i % 20) + 1:02d}' for i in range(70)]
    base = [Bar(date=d, close=100 + i, volume=10) for i, d in enumerate(dates)]
    future = base + [Bar(date='2025-01-01', close=99999, volume=10)]

    a = S.rs_from_book(dates[-1], PriceBook({'000001': base, '000002': base}))
    b = S.rs_from_book(dates[-1], PriceBook({'000001': future, '000002': future}))

    assert a == b

"""rankers.py — 랭킹 함수 단위 테스트."""
from app.services.mirofish.goodrich_backtest.prices import Bar, PriceBook
from app.services.mirofish.goodrich_backtest.universe import Candidate
from app.services.mirofish.goodrich_backtest import rankers as R


def _candidate(symbol, change_pct=1.0, turnover=1e9, close=100.0, surge=1.0, market='KOSPI'):
    return Candidate(
        symbol=symbol, date='2024-01-03', close=close, volume=turnover / close,
        change_pct=change_pct, turnover=turnover, volume_surge=surge, market=market,
    )


def _ctx(book=None, rs=None):
    return R.RankContext(
        date='2024-01-03',
        book=book or PriceBook({}),
        rs_ratings=rs or {},
    )


def test_all_rankers_are_registered():
    assert set(R.RANKERS) == {
        'baseline_current', 'rs_led', 'pullback', 'low_volatility', 'composite',
    }


def test_baseline_reproduces_goodrich_score_shape():
    """현행 _score: 50 + range_position*25 + momentum*0.8 + liquidity*20.

    일봉에는 장중 고저가 없으므로 range_position 은 1.0 으로 고정한다
    (종가 = 당일 고가 가정). 등락률이 클수록 점수가 커지는 성질이 핵심이다.
    """
    ctx = _ctx()
    low = R.RANKERS['baseline_current'](_candidate('000001', change_pct=1.0), ctx)
    high = R.RANKERS['baseline_current'](_candidate('000002', change_pct=12.0), ctx)

    assert high > low


def test_baseline_caps_momentum_at_15_like_production():
    ctx = _ctx()
    at_cap = R.RANKERS['baseline_current'](_candidate('000001', change_pct=15.0), ctx)
    beyond = R.RANKERS['baseline_current'](_candidate('000002', change_pct=40.0), ctx)

    assert at_cap == beyond


def test_rs_led_prefers_higher_rs():
    ctx = _ctx(rs={'000001': 95, '000002': 20})

    assert R.RANKERS['rs_led'](_candidate('000001'), ctx) > R.RANKERS['rs_led'](_candidate('000002'), ctx)


def test_pullback_penalises_overheated_names():
    bars = [Bar(date=f'2024-01-{d:02d}', close=100.0, volume=10) for d in range(1, 3)]
    hot = bars + [Bar(date='2024-01-03', close=150.0, volume=10)]
    calm = bars + [Bar(date='2024-01-03', close=101.0, volume=10)]
    ctx_hot = _ctx(book=PriceBook({'000001': hot}))
    ctx_calm = _ctx(book=PriceBook({'000001': calm}))

    hot_score = R.RANKERS['pullback'](_candidate('000001', change_pct=50.0), ctx_hot)
    calm_score = R.RANKERS['pullback'](_candidate('000001', change_pct=1.0), ctx_calm)

    assert calm_score > hot_score


def test_rankers_are_deterministic():
    ctx = _ctx(rs={'000001': 70})
    candidate = _candidate('000001')

    for name, fn in R.RANKERS.items():
        assert fn(candidate, ctx) == fn(candidate, ctx), name


def test_rank_candidates_sorts_descending_and_breaks_ties_by_symbol():
    ctx = _ctx()
    rows = [_candidate('000002', change_pct=5.0), _candidate('000001', change_pct=5.0)]

    ordered = R.rank_candidates(rows, R.RANKERS['baseline_current'], ctx)

    assert [c.symbol for c, _ in ordered] == ['000001', '000002']

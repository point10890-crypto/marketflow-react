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
        'disclosure_led', 'fundamental_guard', 'fusion',
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


def test_baseline_uses_real_range_position_not_a_constant():
    """운영 _score 는 종가가 당일 고가 근처일수록 높은 점수를 준다.

    이 항을 1.0 상수로 고정했던 이전 버전은 운영 top3 와 한 종목도 겹치지 않았다.
    같은 등락률·같은 거래대금이면 고가 마감이 저가 마감을 이겨야 한다.
    """
    book = PriceBook({
        '000001': [Bar(date='2024-01-03', close=119.0, volume=10, high=120.0, low=100.0)],
        '000002': [Bar(date='2024-01-03', close=101.0, volume=10, high=120.0, low=100.0)],
    })
    ctx = _ctx(book=book)

    near_high = R.RANKERS['baseline_current'](_candidate('000001'), ctx)
    near_low = R.RANKERS['baseline_current'](_candidate('000002'), ctx)

    assert near_high > near_low


def test_baseline_falls_back_to_one_when_the_bar_has_no_range():
    """고저 결측 봉(실측 2.6%)에서도 점수가 나와야 한다.

    거래대금이 0 이면 liquidity 도 0 이므로 50 + 1.0*25 + 0 + 0 = 75 로 확정된다.
    """
    book = PriceBook({'000001': [Bar(date='2024-01-03', close=100.0, volume=0.0)]})

    score = R.RANKERS['baseline_current'](_candidate('000001', change_pct=0.0), _ctx(book=book))

    assert score == 75.0


class _FakeDisclosures:
    def __init__(self, scores):
        self._scores = scores

    def score(self, symbol, date, **_):
        return self._scores.get(symbol, 0.0)


class _FakeFinancials:
    def __init__(self, scores):
        self._scores = scores

    def health_score(self, symbol, date, **_):
        return self._scores.get(symbol, 0.0)


def test_new_rankers_are_registered():
    assert {'disclosure_led', 'fundamental_guard', 'fusion'} <= set(R.RANKERS)


def test_disclosure_led_prefers_a_surge_backed_by_a_positive_filing():
    ctx = R.RankContext(
        date='2024-01-03', book=PriceBook({}), rs_ratings={},
        disclosures=_FakeDisclosures({'000001': 2.0, '000002': -2.0}),
    )

    backed = R.RANKERS['disclosure_led'](_candidate('000001'), ctx)
    unbacked = R.RANKERS['disclosure_led'](_candidate('000002'), ctx)

    assert backed > unbacked


def test_fundamental_guard_penalises_capital_impairment():
    ctx = R.RankContext(
        date='2024-01-03', book=PriceBook({}), rs_ratings={},
        financials=_FakeFinancials({'000001': -3.0, '000002': 1.0}),
    )

    weak = R.RANKERS['fundamental_guard'](_candidate('000001'), ctx)
    sound = R.RANKERS['fundamental_guard'](_candidate('000002'), ctx)

    assert sound > weak


def test_missing_archives_make_the_new_rankers_equal_the_baseline():
    """아카이브가 없다고 감점하면 데이터 부재가 신호로 둔갑한다."""
    ctx = _ctx()
    candidate = _candidate('000001', change_pct=7.0)
    base = R.RANKERS['baseline_current'](candidate, ctx)

    for name in ('disclosure_led', 'fundamental_guard', 'fusion'):
        assert R.RANKERS[name](candidate, ctx) == base, name


def test_fusion_combines_both_axes():
    ctx = R.RankContext(
        date='2024-01-03', book=PriceBook({}), rs_ratings={},
        disclosures=_FakeDisclosures({'000001': 2.0}),
        financials=_FakeFinancials({'000001': 1.0}),
    )
    candidate = _candidate('000001')

    expected = round(
        R.RANKERS['baseline_current'](candidate, ctx)
        + 2.0 * R.DISCLOSURE_WEIGHT + 1.0 * R.FINANCIAL_WEIGHT, 2)

    assert R.RANKERS['fusion'](candidate, ctx) == expected

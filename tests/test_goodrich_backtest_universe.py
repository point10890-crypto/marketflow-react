"""universe.py — KIS 3소스 유니버스 재현 단위 테스트."""
from app.services.mirofish.goodrich_backtest.prices import Bar, PriceBook
from app.services.mirofish.goodrich_backtest import universe as U


# 유니버스는 운영과 같은 거래대금 하한(20억)을 적용한다. 픽스처의 거래량을
# 일괄 배율로 키워 하한을 넘기되, 소스별 순위 관계는 그대로 유지한다.
_VOLUME_SCALE = 10_000_000


def _book(spec):
    """spec: {ticker: [(date, close, volume), ...]} — volume 은 _VOLUME_SCALE 배."""
    return PriceBook({
        ticker: [Bar(date=d, close=c, volume=v * _VOLUME_SCALE) for d, c, v in bars]
        for ticker, bars in spec.items()
    })


def test_only_positive_change_names_enter_universe():
    book = _book({
        '000001': [('2024-01-02', 100, 1000), ('2024-01-03', 110, 1000)],  # +10%
        '000002': [('2024-01-02', 100, 1000), ('2024-01-03', 90, 1000)],   # -10%
    })

    got = U.reconstruct_universe('2024-01-03', book, per_source_top_n=10)

    assert [c.symbol for c in got] == ['000001']


def test_union_of_three_sources():
    """소스마다 승자가 달라야 합집합이 3종목이 된다.

    000001 등락률 1위(+29%, 가격제한폭 안) / 000002 거래대금 1위 / 000003 거래량급증 1위.
    셋 다 ±31% 안에 있어야 corrupt-data 필터에 걸리지 않는다.
    """
    book = _book({
        # change +29%, turnover 129,000, surge 1.0
        '000001': [('2024-01-02', 100, 1000), ('2024-01-03', 129, 1000)],
        # change +0.1%, turnover 100,100,000, surge 1.0
        '000002': [('2024-01-02', 100000, 1000), ('2024-01-03', 100100, 1000)],
        # change +1%, turnover 50,500, surge 500.0
        '000003': [('2024-01-02', 100, 1), ('2024-01-03', 101, 500)],
    })

    got = U.reconstruct_universe('2024-01-03', book, per_source_top_n=1)

    assert {c.symbol for c in got} == {'000001', '000002', '000003'}


def test_first_session_yields_nothing_because_change_is_unknown():
    book = _book({'000001': [('2024-01-02', 100, 1000)]})

    assert U.reconstruct_universe('2024-01-02', book, per_source_top_n=10) == []


def test_candidate_carries_fields_ranking_needs():
    book = _book({'000001': [('2024-01-02', 100, 10), ('2024-01-03', 110, 20)]})

    got = U.reconstruct_universe('2024-01-03', book, per_source_top_n=10)

    c = got[0]
    assert c.symbol == '000001'
    assert c.date == '2024-01-03'
    assert c.close == 110.0
    assert c.change_pct == 10.0
    assert c.turnover == 110.0 * 20 * _VOLUME_SCALE


def test_market_is_attached_so_benchmark_can_be_chosen():
    book = _book({
        '000001': [('2024-01-02', 100, 10), ('2024-01-03', 110, 10)],
        '000002': [('2024-01-02', 100, 10), ('2024-01-03', 110, 10)],
    })
    markets = {'000001': 'KOSPI', '000002': 'KOSDAQ'}

    got = U.reconstruct_universe('2024-01-03', book, per_source_top_n=10, markets=markets)

    assert {c.symbol: c.market for c in got} == {'000001': 'KOSPI', '000002': 'KOSDAQ'}


def test_unknown_market_is_empty_string_not_a_guess():
    book = _book({'000001': [('2024-01-02', 100, 10), ('2024-01-03', 110, 10)]})

    got = U.reconstruct_universe('2024-01-03', book, per_source_top_n=10, markets={})

    assert got[0].market == ''


def test_impossible_daily_move_is_rejected_as_corrupt_data():
    """한국 가격제한폭은 ±30%. 초과분은 물리적으로 불가능하므로 데이터 오류다.

    실측: daily_prices.csv 에 616건(466종목)이 이 범위를 넘는다. 예) 052670 이
    2,080 -> 610,000 (+29,227%). 하나라도 랭킹에 들어오면 평균 초과수익이 통째로
    오염되므로 후보 단계에서 배제한다.
    """
    book = _book({
        '000001': [('2024-01-02', 100, 10), ('2024-01-03', 110, 10)],      # +10% 정상
        '000002': [('2024-01-02', 100, 10), ('2024-01-03', 30000, 10)],    # +29,900% 오류
    })

    got = U.reconstruct_universe('2024-01-03', book, per_source_top_n=10)

    assert [c.symbol for c in got] == ['000001']


def test_limit_up_at_the_boundary_is_kept():
    """정상 상한가(+29.9%)는 버리지 않는다."""
    book = _book({'000001': [('2024-01-02', 100, 10), ('2024-01-03', 129.9, 10)]})

    got = U.reconstruct_universe('2024-01-03', book, per_source_top_n=10)

    assert [c.symbol for c in got] == ['000001']


def test_universe_is_deterministic():
    book = _book({
        f'{i:06d}': [('2024-01-02', 100, 10), ('2024-01-03', 100 + i, 10)]
        for i in range(1, 6)
    })

    first = [c.symbol for c in U.reconstruct_universe('2024-01-03', book, per_source_top_n=3)]
    second = [c.symbol for c in U.reconstruct_universe('2024-01-03', book, per_source_top_n=3)]

    assert first == second


def test_load_markets_reads_ticker_map(tmp_path):
    path = tmp_path / 'ticker_to_yahoo_map.csv'
    path.write_text(
        'ticker,market,yahoo_ticker,name\n'
        '005930,KOSPI,005930.KS,삼성전자\n'
        '247540,KOSDAQ,247540.KQ,에코프로비엠\n',
        encoding='utf-8',
    )

    assert U.load_markets(str(path)) == {'005930': 'KOSPI', '247540': 'KOSDAQ'}


def test_limit_locked_names_are_excluded_because_they_cannot_be_bought():
    """상한가로 잠긴 종목은 매도 호가가 없어 종가에 살 수 없다.

    남겨두면 종가==고가 -> range_position 1.0 -> 최대 배점이라 랭커가 그쪽으로
    쏠린다. 실측에서 baseline 픽의 81.8% 가 상한가였고, 살 수 없는 가격으로
    계산된 초과수익 +4.18% 가 나왔다.
    """
    from app.services.mirofish.goodrich_backtest.prices import Bar, PriceBook

    book = PriceBook({
        '000001': [
            Bar(date='2024-01-02', close=1000, volume=10_000_000),
            Bar(date='2024-01-03', close=1300, volume=10_000_000, high=1300, low=1100),  # 잠김
        ],
        '000002': [
            Bar(date='2024-01-02', close=1000, volume=10_000_000),
            Bar(date='2024-01-03', close=1290, volume=10_000_000, high=1300, low=1100),  # 고가 미달
        ],
    })

    symbols = {c.symbol for c in U.reconstruct_universe('2024-01-03', book, markets={})}

    assert '000001' not in symbols
    assert '000002' in symbols


def test_a_big_gain_that_did_not_close_at_the_high_is_still_tradable():
    """+29% 여도 고가에서 밀렸으면 매수 가능하다. 과잉 제거하지 않는다."""
    from app.services.mirofish.goodrich_backtest.prices import Bar, PriceBook

    book = PriceBook({'000001': [
        Bar(date='2024-01-02', close=1000, volume=10_000_000),
        Bar(date='2024-01-03', close=1290, volume=10_000_000, high=1300, low=1050),
    ]})

    assert {c.symbol for c in U.reconstruct_universe('2024-01-03', book, markets={})} == {'000001'}


def test_missing_high_low_does_not_trigger_exclusion():
    """고저 결측(실측 2.6%)은 판단 근거가 없다 — 배제 사유가 아니다."""
    from app.services.mirofish.goodrich_backtest.prices import Bar, PriceBook

    book = PriceBook({'000001': [
        Bar(date='2024-01-02', close=1000, volume=10_000_000),
        Bar(date='2024-01-03', close=1300, volume=10_000_000),
    ]})

    assert {c.symbol for c in U.reconstruct_universe('2024-01-03', book, markets={})} == {'000001'}


def test_benchmark_etfs_are_excluded_so_the_ranker_cannot_buy_the_yardstick():
    """069500 / 229200 은 초과수익을 재는 기준 지수다.

    유니버스에 남겨두면 랭커가 그것을 매수해 초과수익을 구조적으로 -왕복비용
    으로 만든다. 실제로 low_volatility 가 이 경로로 '개선'을 냈다.
    """
    from app.services.mirofish.goodrich_backtest.prices import Bar, PriceBook

    bars = [Bar(date='2024-01-02', close=1000, volume=10_000_000),
            Bar(date='2024-01-03', close=1050, volume=10_000_000)]
    book = PriceBook(
        {'069500': list(bars), '229200': list(bars), '005930': list(bars)},
        names={'069500': 'KODEX 200', '229200': 'KODEX 코스닥150', '005930': '삼성전자'},
    )

    symbols = {c.symbol for c in U.reconstruct_universe('2024-01-03', book, markets={})}

    assert symbols == {'005930'}


def test_preferred_shares_are_excluded_like_production():
    from app.services.mirofish.goodrich_backtest.prices import Bar, PriceBook

    bars = [Bar(date='2024-01-02', close=1000, volume=10_000_000),
            Bar(date='2024-01-03', close=1050, volume=10_000_000)]
    book = PriceBook(
        {'005930': list(bars), '005935': list(bars)},
        names={'005930': '삼성전자', '005935': '삼성전자우'},
    )

    symbols = {c.symbol for c in U.reconstruct_universe('2024-01-03', book, markets={})}

    assert symbols == {'005930'}


def test_thin_names_below_the_production_liquidity_floor_are_excluded():
    """운영은 거래대금 20억 미만을 후보로 받지 않는다."""
    from app.services.mirofish.goodrich_backtest.prices import Bar, PriceBook

    book = PriceBook(
        {
            '000001': [Bar(date='2024-01-02', close=1000, volume=10_000_000),
                       Bar(date='2024-01-03', close=1050, volume=100)],        # 1.05억
            '000002': [Bar(date='2024-01-02', close=1000, volume=10_000_000),
                       Bar(date='2024-01-03', close=1050, volume=10_000_000)],  # 105억
        },
        names={'000001': '소형주', '000002': '대형주'},
    )

    symbols = {c.symbol for c in U.reconstruct_universe('2024-01-03', book, markets={})}

    assert symbols == {'000002'}


def test_etf_keywords_stay_in_sync_with_the_live_screener():
    """키워드를 복사해두면 운영이 추가할 때 재현물만 뒤처진다."""
    from app.services.kis_screener import ETF_KEYWORDS as live

    assert U.ETF_KEYWORDS is live

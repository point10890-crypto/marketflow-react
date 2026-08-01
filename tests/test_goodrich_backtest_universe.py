"""universe.py — KIS 3소스 유니버스 재현 단위 테스트."""
from app.services.mirofish.goodrich_backtest.prices import Bar, PriceBook
from app.services.mirofish.goodrich_backtest import universe as U


def _book(spec):
    """spec: {ticker: [(date, close, volume), ...]}"""
    return PriceBook({
        ticker: [Bar(date=d, close=c, volume=v) for d, c, v in bars]
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
    assert c.turnover == 110.0 * 20


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

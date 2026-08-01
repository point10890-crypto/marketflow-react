"""prices.py — daily_prices.csv 로더 단위 테스트."""
import csv

from app.services.mirofish.goodrich_backtest import prices as P


def _write_csv(path, rows):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=[
            'ticker', 'date', 'name', 'current_price', 'change', 'change_rate',
            'high', 'low', 'open', 'volume', 'update_time',
        ])
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _row(ticker, date, close, volume, *, change_rate=0, high=None, low=None):
    return {
        'ticker': ticker, 'date': date, 'name': f'N{ticker}',
        'current_price': close, 'change': 0, 'change_rate': change_rate,
        'high': high if high is not None else close,
        'low': low if low is not None else close,
        'open': close, 'volume': volume, 'update_time': '',
    }


def test_load_builds_sorted_series_per_ticker(tmp_path):
    csv_path = tmp_path / 'daily_prices.csv'
    _write_csv(csv_path, [
        _row('000660', '2024-01-03', 200, 10),
        _row('000660', '2024-01-02', 100, 20),
    ])

    book = P.load_prices(str(csv_path))

    assert book.sessions == ['2024-01-02', '2024-01-03']
    assert [bar.close for bar in book.series('000660')] == [100.0, 200.0]


def test_change_rate_is_computed_from_consecutive_closes(tmp_path):
    # change_rate 컬럼은 0 이지만 종가는 100 -> 110 이므로 +10% 여야 한다.
    csv_path = tmp_path / 'daily_prices.csv'
    _write_csv(csv_path, [
        _row('000660', '2024-01-02', 100, 10, change_rate=0),
        _row('000660', '2024-01-03', 110, 10, change_rate=0),
    ])

    book = P.load_prices(str(csv_path))

    assert book.change_pct('000660', '2024-01-03') == 10.0
    assert book.change_pct('000660', '2024-01-02') is None  # 이전 세션 없음


def test_rows_with_nonpositive_close_are_dropped(tmp_path):
    csv_path = tmp_path / 'daily_prices.csv'
    _write_csv(csv_path, [
        _row('000660', '2024-01-02', 0, 10),
        _row('000660', '2024-01-03', 110, 10),
    ])

    book = P.load_prices(str(csv_path))

    assert [bar.date for bar in book.series('000660')] == ['2024-01-03']


def test_ledger_rows_exposes_shape_evaluate_pick_expects(tmp_path):
    csv_path = tmp_path / 'daily_prices.csv'
    _write_csv(csv_path, [_row('000660', '2024-01-02', 100, 10)])

    book = P.load_prices(str(csv_path))

    assert book.ledger_rows('000660') == [{'date': '2024-01-02', 'current_price': 100.0}]


def test_missing_file_returns_empty_book(tmp_path):
    book = P.load_prices(str(tmp_path / 'nope.csv'))

    assert book.sessions == []
    assert book.series('000660') == []


def test_duplicate_ticker_date_rows_are_collapsed(tmp_path):
    """실데이터에 25,900개의 중복 (ticker, date) 가 있다. 재스크랩 결과이며
    별개의 봉이 아니다. 마지막 update_time 을 남기고 하나로 합쳐야 한다."""
    csv_path = tmp_path / 'daily_prices.csv'
    rows = [
        _row('000660', '2024-01-02', 100, 10),
        _row('000660', '2024-01-03', 105, 10),
        _row('000660', '2024-01-03', 110, 20),   # 같은 날 재스크랩 (뒤가 최신)
    ]
    rows[1]['update_time'] = '2024-01-03 12:00:00'
    rows[2]['update_time'] = '2024-01-03 15:40:00'
    _write_csv(csv_path, rows)

    book = P.load_prices(str(csv_path))

    assert [bar.date for bar in book.series('000660')] == ['2024-01-02', '2024-01-03']
    assert book.bar('000660', '2024-01-03').close == 110.0   # 최신 스크랩


def test_prior_bars_never_returns_the_queried_date_even_with_duplicates(tmp_path):
    """중복이 있어도 진입일이 '과거'로 새어나오면 안 된다 — 하네스의 핵심 성질."""
    csv_path = tmp_path / 'daily_prices.csv'
    rows = [
        _row('000660', '2024-01-02', 100, 10),
        _row('000660', '2024-01-03', 105, 10),
        _row('000660', '2024-01-03', 110, 20),
    ]
    rows[1]['update_time'] = '2024-01-03 12:00:00'
    rows[2]['update_time'] = '2024-01-03 15:40:00'
    _write_csv(csv_path, rows)

    book = P.load_prices(str(csv_path))

    assert [b.date for b in book.prior_bars('000660', '2024-01-03', 5)] == ['2024-01-02']


def test_change_pct_uses_the_previous_calendar_session_not_a_duplicate(tmp_path):
    csv_path = tmp_path / 'daily_prices.csv'
    rows = [
        _row('000660', '2024-01-02', 100, 10),
        _row('000660', '2024-01-03', 105, 10),
        _row('000660', '2024-01-03', 110, 20),
    ]
    rows[1]['update_time'] = '2024-01-03 12:00:00'
    rows[2]['update_time'] = '2024-01-03 15:40:00'
    _write_csv(csv_path, rows)

    book = P.load_prices(str(csv_path))

    # 110/100-1 = +10%. 110/105-1 = +4.76% (중복 비교) 가 나오면 실패.
    assert book.change_pct('000660', '2024-01-03') == 10.0


def test_ledger_rows_emit_one_row_per_date(tmp_path):
    """evaluate_pick 은 future[horizon-1] 로 위치 인덱싱하므로 중복이 있으면
    T+1 과 T+2 가 같은 날로 해석된다."""
    csv_path = tmp_path / 'daily_prices.csv'
    rows = [
        _row('000660', '2024-01-02', 100, 10),
        _row('000660', '2024-01-03', 105, 10),
        _row('000660', '2024-01-03', 110, 20),
    ]
    rows[1]['update_time'] = '2024-01-03 12:00:00'
    rows[2]['update_time'] = '2024-01-03 15:40:00'
    _write_csv(csv_path, rows)

    book = P.load_prices(str(csv_path))

    dates = [r['date'] for r in book.ledger_rows('000660')]
    assert dates == sorted(set(dates))


def test_blank_ticker_is_skipped_not_filed_under_000000(tmp_path):
    """zfill 이 먼저 돌면 ''.zfill(6) == '000000' 이라 빈 티커 가드가 죽는다."""
    csv_path = tmp_path / 'daily_prices.csv'
    _write_csv(csv_path, [
        _row('', '2024-01-02', 100, 10),
        _row('000660', '2024-01-02', 200, 10),
    ])

    book = P.load_prices(str(csv_path))

    assert book.tickers() == ['000660']


def test_unparseable_volume_keeps_the_price_bar(tmp_path):
    """거래량 파싱 실패로 봉을 버리면 계열에 구멍이 생겨 change_pct 가
    1일 수익률을 2일 수익률로 바꿔버린다."""
    csv_path = tmp_path / 'daily_prices.csv'
    rows = [_row('000660', '2024-01-02', 100, 10), _row('000660', '2024-01-03', 110, 10)]
    rows[1]['volume'] = 'N/A'
    _write_csv(csv_path, rows)

    book = P.load_prices(str(csv_path))

    assert [b.date for b in book.series('000660')] == ['2024-01-02', '2024-01-03']
    assert book.bar('000660', '2024-01-03').volume == 0.0


def test_nan_and_inf_closes_are_rejected(tmp_path):
    """float('nan') <= 0 은 False 라 양수 가드를 통과한다."""
    csv_path = tmp_path / 'daily_prices.csv'
    rows = [_row('000660', '2024-01-02', 100, 10), _row('000660', '2024-01-03', 110, 10)]
    rows[0]['current_price'] = 'nan'
    rows[1]['current_price'] = 'inf'
    _write_csv(csv_path, rows)

    book = P.load_prices(str(csv_path))

    assert book.series('000660') == []


def test_series_does_not_expose_the_internal_list(tmp_path):
    """호출부가 정렬/추가하면 인덱스가 어긋나 bar() 가 조용히 틀린 값을 준다."""
    csv_path = tmp_path / 'daily_prices.csv'
    _write_csv(csv_path, [_row('000660', '2024-01-02', 100, 10)])

    book = P.load_prices(str(csv_path))
    got = book.series('000660')
    got.clear()

    assert len(book.series('000660')) == 1


def test_usable_sessions_drops_intraday_captured_days(tmp_path):
    """저장된 '종가' 가 장중 스냅샷인 세션은 수익률 계산의 근거가 못 된다.
    실데이터에서 110세션(전부 2026년)이 장중수집 과반이다."""
    csv_path = tmp_path / 'daily_prices.csv'
    rows = [
        _row('000660', '2024-01-02', 100, 10),
        _row('000661', '2024-01-02', 100, 10),
        _row('000660', '2024-01-03', 110, 10),
        _row('000661', '2024-01-03', 110, 10),
    ]
    rows[0]['update_time'] = '2024-01-02 15:40:00'
    rows[1]['update_time'] = '2024-01-02 15:41:00'
    rows[2]['update_time'] = '2024-01-03 12:00:00'   # 장중
    rows[3]['update_time'] = '2024-01-03 11:00:00'   # 장중
    _write_csv(csv_path, rows)

    book = P.load_prices(str(csv_path))

    assert book.sessions == ['2024-01-02', '2024-01-03']
    assert book.usable_sessions() == ['2024-01-02']

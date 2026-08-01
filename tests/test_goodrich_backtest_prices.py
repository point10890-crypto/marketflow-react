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

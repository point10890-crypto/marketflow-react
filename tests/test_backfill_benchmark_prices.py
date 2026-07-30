"""The benchmark ETFs entered daily_prices.csv only from the day they were added
to the collection universe. Excess return for picks recorded before that needs a
one-off historical backfill, which must not disturb rows already present."""

from __future__ import annotations

import csv

from scripts import backfill_benchmark_prices as backfill


HEADER = [
    'ticker', 'date', 'name', 'current_price', 'change', 'change_rate',
    'high', 'low', 'open', 'volume', 'update_time',
]


def _write_csv(path, rows):
    with open(path, 'w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADER)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _row(ticker, date, close):
    return {
        'ticker': ticker, 'date': date, 'name': 'x', 'current_price': close,
        'change': 0, 'change_rate': 0, 'high': close, 'low': close,
        'open': close, 'volume': 1, 'update_time': '2026-07-30 00:00:00',
    }


def test_existing_dates_are_read_back_per_ticker(tmp_path):
    csv_path = tmp_path / 'daily_prices.csv'
    _write_csv(csv_path, [
        _row('005930', '2026-07-28', 70000),
        _row('069500', '2026-07-28', 40000),
        _row('069500', '2026-07-29', 40500),
    ])

    existing = backfill.existing_dates(str(csv_path), {'069500', '229200'})

    assert existing['069500'] == {'2026-07-28', '2026-07-29'}
    assert existing['229200'] == set()


def test_backfill_appends_only_missing_sessions_and_keeps_the_schema(tmp_path):
    csv_path = tmp_path / 'daily_prices.csv'
    _write_csv(csv_path, [
        _row('005930', '2026-07-28', 70000),
        _row('069500', '2026-07-28', 40000),
    ])
    fetched = {
        '069500': [
            {'date': '2026-07-28', 'close': 40000.0, 'open': 39900.0,
             'high': 40100.0, 'low': 39800.0, 'volume': 10},
            {'date': '2026-07-29', 'close': 40500.0, 'open': 40050.0,
             'high': 40600.0, 'low': 40000.0, 'volume': 12},
        ],
    }

    written = backfill.append_missing_rows(
        str(csv_path), fetched, names={'069500': 'KODEX 200'},
        now_str='2026-07-30 18:00:00',
    )

    assert written == 1
    with open(csv_path, encoding='utf-8-sig') as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 3
    added = rows[-1]
    assert added['ticker'] == '069500'
    assert added['date'] == '2026-07-29'
    assert added['name'] == 'KODEX 200'
    assert float(added['current_price']) == 40500.0
    assert float(added['open']) == 40050.0
    assert added['update_time'] == '2026-07-30 18:00:00'
    assert list(rows[0].keys()) == HEADER


def test_backfill_is_idempotent(tmp_path):
    csv_path = tmp_path / 'daily_prices.csv'
    _write_csv(csv_path, [_row('069500', '2026-07-28', 40000)])
    fetched = {'069500': [{'date': '2026-07-28', 'close': 40000.0, 'open': 40000.0,
                           'high': 40000.0, 'low': 40000.0, 'volume': 1}]}

    assert backfill.append_missing_rows(str(csv_path), fetched, names={}, now_str='t') == 0

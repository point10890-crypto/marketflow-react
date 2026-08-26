"""Regime classifier tests — deterministic, lookahead-safe, no network."""
import csv

from app.services.mirofish.intelligence import regime


def _series(start_price, deltas, start_idx=1):
    rows, price = [], start_price
    for i, d in enumerate(deltas):
        price += d
        rows.append({'date': f'2026-02-{start_idx + i:02d}', 'current_price': float(price)})
    return rows


def test_breadth_risk_on_when_most_above_ma(monkeypatch):
    prices = {}
    for t in range(10):
        prices[f'{t:06d}'] = _series(1000, [10] * 22)
    tl = regime.build_regime_timeline(prices, write=False)
    last_date = max(tl['by_date'])
    assert tl['by_date'][last_date]['regime'] == 'RISK_ON'
    assert tl['by_date'][last_date]['breadth'] >= 0.60


def test_breadth_risk_off_when_most_below_ma(monkeypatch):
    prices = {}
    for t in range(10):
        prices[f'{t:06d}'] = _series(1000, [-10] * 22)
    tl = regime.build_regime_timeline(prices, write=False)
    last_date = max(tl['by_date'])
    assert tl['by_date'][last_date]['regime'] == 'RISK_OFF'


def test_classify_regime_uses_past_date_fallback():
    timeline = {'by_date': {
        '2026-02-10': {'breadth': 0.7, 'regime': 'RISK_ON', 'above': 7, 'total': 10},
        '2026-02-12': {'breadth': 0.3, 'regime': 'RISK_OFF', 'above': 3, 'total': 10},
    }}
    assert regime.classify_regime('2026-02-12', timeline) == 'RISK_OFF'
    assert regime.classify_regime('2026-02-11', timeline) == 'RISK_ON'
    assert regime.classify_regime('2026-02-01', timeline) == 'NEUTRAL'


def test_empty_prices_safe():
    tl = regime.build_regime_timeline({}, write=False)
    assert tl['by_date'] == {}
    assert regime.classify_regime('2026-02-10', tl) == 'NEUTRAL'


def test_csv_loader_keeps_latest_valid_duplicate_and_reports_quality(tmp_path):
    path = tmp_path / 'prices.csv'
    fieldnames = ['ticker', 'date', 'current_price', 'update_time']
    with path.open('w', encoding='utf-8', newline='') as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows([
            {'ticker': 'AAA', 'date': '2026-02-01', 'current_price': '100',
             'update_time': '2026-02-01 15:00:00'},
            {'ticker': 'AAA', 'date': '2026-02-01', 'current_price': '101',
             'update_time': '2026-02-01 15:10:00'},
            # Latest source row is invalid, so it cannot replace the latest valid row.
            {'ticker': 'AAA', 'date': '2026-02-01', 'current_price': '0',
             'update_time': '2026-02-01 15:20:00'},
            {'ticker': 'BBB', 'date': 'not-a-date', 'current_price': '50',
             'update_time': '2026-02-01 15:00:00'},
        ])

    prices, quality = regime.load_universe_prices(path, return_quality=True)

    assert prices == {'AAA': [{'date': '2026-02-01', 'current_price': 101.0}]}
    assert quality['dedupe_policy'] == regime.PRICE_DEDUPE_POLICY
    assert quality['duplicate_keys'] == 1
    assert quality['duplicate_rows_removed'] == 1
    assert quality['conflicting_duplicate_keys'] == 1
    assert quality['invalid_price_rows'] == 1
    assert quality['invalid_key_rows'] == 1
    assert quality['max_data_date'] == '2026-02-01'


def test_regime_builder_deduplicates_provided_ticker_dates():
    rows = _series(100, [1] * 20)
    rows += [
        {'date': '2026-02-21', 'current_price': 50,
         'update_time': '2026-02-21 15:00:00'},
        {'date': '2026-02-21', 'current_price': 200,
         'update_time': '2026-02-21 15:10:00'},
    ]

    timeline = regime.build_regime_timeline({'AAA': rows}, ma_window=20, write=False)

    assert timeline['schema_version'] == 'mirofish.regime_timeline.v2'
    assert timeline['by_date']['2026-02-21']['total'] == 1
    assert timeline['by_date']['2026-02-21']['above'] == 1
    assert timeline['data_quality']['duplicate_keys'] == 1

"""Regime classifier tests — deterministic, lookahead-safe, no network."""
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

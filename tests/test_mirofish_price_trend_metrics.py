from app.services.mirofish import alpha_scanner


def test_price_analysis_replaces_stale_same_day_snapshot_with_live_quote():
    history = [
        {
            'date': f'2026-07-{day:02d}',
            'current_price': 100 + day,
            'volume': 1000,
        }
        for day in range(1, 30)
    ]
    history.append({
        'date': '2026-07-30',
        'current_price': 110,
        'volume': 1000,
        'update_time': '09:00:00',
    })
    latest = {
        'date': '2026-07-30',
        'current_price': 150,
        'change_rate': 8.0,
        'volume': 5000,
    }

    result = alpha_scanner._price_analysis(history, latest)

    assert result['sample_days'] == 30
    assert result['trend_5d_pct'] > 0
    assert result['over_ma20_pct'] > 0
    assert result['drawdown_20d_pct'] == 0


def test_price_analysis_appends_live_quote_for_new_trading_day():
    history = [
        {
            'date': f'2026-07-{day:02d}',
            'current_price': 100 + day,
            'volume': 1000,
        }
        for day in range(1, 30)
    ]
    latest = {
        'date': '2026-07-30',
        'current_price': 150,
        'change_rate': 8.0,
        'volume': 5000,
    }

    result = alpha_scanner._price_analysis(history, latest)

    assert result['sample_days'] == 30
    assert result['trend_5d_pct'] > 0

from app import _build_screener_alert_message, _build_screener_hourly_message


def _stock(**overrides):
    base = {
        "grade": "S",
        "rank": 1,
        "code": "439960",
        "name": "코스모로보틱스",
        "price": 39700,
        "change_pct": 27.24,
        "trading_value_eok": 1200,
        "score": {
            "total": 82,
            "total_enriched": 91,
            "trading_value": 30,
            "momentum": 25,
            "smart_money": 8,
            "volume_surge": 10,
            "sector": 3,
            "new_high": 12,
        },
        "high_52w": {"distance_pct": 1.2},
        "enrichment": {
            "ai_reason": "로봇 테마 강세",
            "themes": ["로봇", "AI"],
            "consecutive_days": 2,
            "market_cap_tier": "중형",
        },
    }
    base.update(overrides)
    return base


def _result(**overrides):
    base = {
        "timestamp": "2026-05-13T09:08:31.274245",
        "market_status": "open",
        "quote_mode": "paper",
        "served_from": "fresh_file",
        "by_grade": {"S": 1, "A": 1, "B": 1},
        "results": [
            _stock(),
            _stock(grade="A", name="PS일렉트로닉스", code="332570", price=14100, change_pct=16.34),
            _stock(grade="B", name="모베이스전자", code="012860", price=6500, change_pct=7.79),
        ],
    }
    base.update(overrides)
    return base


def test_screener_alert_message_identifies_quote_mode_and_price():
    msg = _build_screener_alert_message(_stock(), _result())

    assert "주도주 S등급 발견" in msg
    assert "코스모로보틱스" in msg
    assert "39,700원" in msg
    assert "KIS 모의" in msg
    assert "모의투자 시세 기준" in msg
    assert "fresh_file" in msg
    assert "91/100" in msg


def test_screener_hourly_message_includes_quote_mode_prices_and_grades():
    msg = _build_screener_hourly_message(_result())

    assert "주도주LIVE 현황" in msg
    assert "KIS 모의" in msg
    assert "39,700원" in msg
    assert "14,100원" in msg
    assert "B등급: 모베이스전자" in msg

def test_fund_manager_selects_top3_and_sets_monitoring_levels(clean_db, monkeypatch):
    from goodrich import main

    class FakeKIS:
        def current_price(self, symbol):
            universe = ["005930", "000660", "035420"]
            index = universe.index(symbol)
            price = 100_000 + index * 10_000
            return {
                "symbol": symbol,
                "price": price,
                "change": 1_000,
                "change_rate": index,
                "open": price - 2_000,
                "high": price + 3_000,
                "low": price - 4_000,
                "volume": 1_000_000,
                "trading_value": 100_000_000_000 + index * 10_000_000_000,
                "market_status": None,
                "source": "KIS",
                "observed_at": "2026-07-28T07:00:00+00:00",
            }

    class FakeResearcher:
        def analyze(self, candidates):
            return {
                "provider": "deepseek",
                "model": "deepseek-v4-pro",
                "response_id": "resp_test",
                "market_summary": "테스트 시장 요약",
                "analyses": [
                    {
                        "symbol": candidate["symbol"],
                        "thesis": "검증된 강점",
                        "risk": "검증된 위험",
                        "verdict": "WATCH",
                        "conviction_score": 60,
                        "monitoring_focus": "KIS 가격과 거래대금",
                    }
                    for candidate in candidates
                ],
            }

    monkeypatch.setattr(main, "kis_client", FakeKIS())
    monkeypatch.setattr(main, "openai_researcher", FakeResearcher())
    order = ["005930", "000660", "035420"]
    response = clean_db.post(
        "/v1/fund-manager/research",
        json={
            "candidates": [
                {"symbol": "005930", "name": "삼성전자"},
                {"symbol": "000660", "name": "SK하이닉스"},
                {"symbol": "035420", "name": "NAVER"},
            ],
            "ranked_candidates": [
                {
                    "symbol": symbol,
                    "name": {"005930": "삼성전자", "000660": "SK하이닉스", "035420": "NAVER"}[symbol],
                    "rank": rank,
                    "score": 100 - rank,
                }
                for rank, symbol in enumerate(order, start=1)
            ],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "monitoring"
    assert len(payload["picks"]) == 3
    assert payload["ai"]["status"] == "completed"
    assert payload["ai"]["provider"] == "deepseek"
    assert payload["ai"]["model"] == "deepseek-v4-pro"
    assert [pick["rank"] for pick in payload["picks"]] == [1, 2, 3]
    assert [pick["symbol"] for pick in payload["picks"]] == order
    assert all(
        pick["stop_price"] < pick["entry_price"] < pick["target_price"]
        for pick in payload["picks"]
    )


def test_fund_manager_research_requires_ranked_candidates(clean_db):
    response = clean_db.post("/v1/fund-manager/research")
    assert response.status_code == 422

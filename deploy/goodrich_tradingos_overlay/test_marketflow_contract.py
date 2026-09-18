def _quote(symbol: str, index: int) -> dict:
    price = 100_000 + index * 10_000
    return {
        "symbol": symbol,
        "price": price,
        "change": 1_000,
        "change_rate": index + 1,
        "open": price - 2_000,
        "high": price + 3_000,
        "low": price - 4_000,
        "volume": 1_000_000,
        "trading_value": 100_000_000_000 + index * 10_000_000_000,
        "market_status": "open",
        "source": "KIS",
        "observed_at": "2026-09-04T04:00:00+00:00",
    }


class FakeKIS:
    def __init__(self, order: list[str]):
        self.order = order

    def current_price(self, symbol: str) -> dict:
        return _quote(symbol, self.order.index(symbol))


class FakeResearcher:
    def __init__(self, *, fallback: bool = False):
        self.fallback = fallback

    def analyze(self, candidates: list[dict]) -> dict:
        result = {
            "provider": "openai" if self.fallback else "deepseek",
            "model": "gpt-5.5" if self.fallback else "deepseek-v4-pro",
            "response_id": "test-response",
            "market_summary": "검증된 후보 요약",
            "analyses": [
                {
                    "symbol": candidate["symbol"],
                    "thesis": "검증된 강점",
                    "risk": "검증된 위험",
                    "verdict": "REJECT" if index == 1 else "WATCH",
                    "conviction_score": 40 + index,
                    "monitoring_focus": "KIS 가격과 거래대금",
                }
                for index, candidate in enumerate(candidates)
            ],
        }
        if self.fallback:
            result.update(
                {
                    "fallback_from": "deepseek",
                    "storage_provider": "openai_fallback_from_deepseek",
                }
            )
        return result


def test_marketflow_candidate_order_is_preserved_even_for_reject(clean_db, monkeypatch):
    from goodrich import main

    order = ["035420", "005930", "000660"]
    monkeypatch.setattr(main, "kis_client", FakeKIS(order))
    monkeypatch.setattr(main, "openai_researcher", FakeResearcher())
    response = clean_db.post(
        "/v1/fund-manager/research",
        json={
            "candidates": [
                {"symbol": "035420", "name": "NAVER"},
                {"symbol": "005930", "name": "삼성전자"},
                {"symbol": "000660", "name": "SK하이닉스"},
            ],
            "ranked_candidates": [
                {
                    "symbol": symbol,
                    "name": {"035420": "NAVER", "005930": "삼성전자", "000660": "SK하이닉스"}[symbol],
                    "rank": rank,
                    "score": 100 - rank,
                }
                for rank, symbol in enumerate(order, start=1)
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert [pick["symbol"] for pick in payload["picks"]] == order
    assert [pick["rank"] for pick in payload["picks"]] == [1, 2, 3]
    assert [pick["score"] for pick in payload["picks"]] == [99, 98, 97]
    assert payload["ai"]["provider"] == "deepseek"
    assert payload["ai"]["fallback_from"] is None


def test_one_verified_candidate_is_allowed_and_fallback_is_labeled(clean_db, monkeypatch):
    from goodrich import main

    order = ["005930"]
    monkeypatch.setattr(main, "kis_client", FakeKIS(order))
    monkeypatch.setattr(main, "openai_researcher", FakeResearcher(fallback=True))
    response = clean_db.post(
        "/v1/fund-manager/research",
        json={
            "candidates": [{"symbol": "005930", "name": "삼성전자"}],
            "ranked_candidates": [
                {
                    "symbol": "005930",
                    "name": "삼성전자",
                    "rank": 1,
                    "score": 55.125,
                }
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert [pick["symbol"] for pick in payload["picks"]] == order
    assert [pick["score"] for pick in payload["picks"]] == [55.125]
    assert payload["ai"]["provider"] == "openai"
    assert payload["ai"]["fallback_from"] == "deepseek"


def test_two_verified_candidates_are_returned_in_ranked_order(clean_db, monkeypatch):
    from goodrich import main

    order = ["000660", "005930"]
    monkeypatch.setattr(main, "kis_client", FakeKIS(order))
    monkeypatch.setattr(main, "openai_researcher", FakeResearcher())
    response = clean_db.post(
        "/v1/fund-manager/research",
        json={
            "candidates": [
                {"symbol": "005930", "name": "삼성전자"},
                {"symbol": "000660", "name": "SK하이닉스"},
            ],
            "ranked_candidates": [
                {
                    "symbol": "000660",
                    "name": "SK하이닉스",
                    "rank": 1,
                    "score": 80.123456,
                },
                {"symbol": "005930", "name": "삼성전자", "rank": 2, "score": 70},
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert [pick["symbol"] for pick in payload["picks"]] == order
    assert [pick["score"] for pick in payload["picks"]] == [80.123456, 70]


def test_invalid_ranked_candidate_contracts_fail_before_provider_calls(clean_db):
    valid_candidates = [
        {"symbol": "005930", "name": "삼성전자"},
        {"symbol": "000660", "name": "SK하이닉스"},
    ]
    invalid_payloads = [
        {"candidates": valid_candidates * 2, "ranked_candidates": []},
        {
            "candidates": [valid_candidates[0], valid_candidates[0]],
            "ranked_candidates": [
                {"symbol": "005930", "name": "삼성전자", "rank": 1, "score": 10},
                {"symbol": "005930", "name": "삼성전자", "rank": 2, "score": 9},
            ],
        },
        {
            "candidates": valid_candidates,
            "ranked_candidates": [
                {"symbol": "005930", "name": "삼성전자", "rank": 1, "score": 10},
                {"symbol": "000660", "name": "SK하이닉스", "rank": 1, "score": 9},
            ],
        },
        {
            "candidates": valid_candidates,
            "ranked_candidates": [
                {"symbol": "005930", "name": "다른이름", "rank": 1, "score": 10},
                {"symbol": "000660", "name": "SK하이닉스", "rank": 2, "score": 9},
            ],
        },
        {
            "candidates": valid_candidates,
            "ranked_candidates": [
                {"symbol": "005930", "name": "삼성전자", "rank": 2, "score": 10},
                {"symbol": "000660", "name": "SK하이닉스", "rank": 1, "score": 9},
            ],
        },
        {
            "candidates": valid_candidates,
            "ranked_candidates": [
                {"symbol": "005930", "name": "삼성전자", "rank": "1", "score": 10},
                {"symbol": "000660", "name": "SK하이닉스", "rank": 2, "score": 9},
            ],
        },
        {
            "candidates": valid_candidates,
            "ranked_candidates": [
                {"symbol": "005930", "name": "삼성전자", "rank": True, "score": 10},
                {"symbol": "000660", "name": "SK하이닉스", "rank": 2, "score": 9},
            ],
        },
        {
            "candidates": valid_candidates,
            "ranked_candidates": [
                {"symbol": "005930", "name": "삼성전자", "rank": 1},
                {"symbol": "000660", "name": "SK하이닉스", "rank": 2, "score": 9},
            ],
        },
        {
            "candidates": valid_candidates,
            "ranked_candidates": [
                {"symbol": "005930", "name": "삼성전자", "rank": 1, "score": None},
                {"symbol": "000660", "name": "SK하이닉스", "rank": 2, "score": 9},
            ],
        },
        {
            "candidates": valid_candidates,
            "ranked_candidates": [
                {"symbol": "005930", "name": "삼성전자", "rank": 1, "score": True},
                {"symbol": "000660", "name": "SK하이닉스", "rank": 2, "score": 9},
            ],
        },
        {
            "candidates": valid_candidates,
            "ranked_candidates": [
                {
                    "symbol": "005930",
                    "name": "삼성전자",
                    "rank": 1,
                    "score": "NaN",
                },
                {"symbol": "000660", "name": "SK하이닉스", "rank": 2, "score": 9},
            ],
        },
        {
            "candidates": valid_candidates,
            "ranked_candidates": [
                {"symbol": "005930", "name": "삼성전자", "rank": 1, "score": -1},
                {"symbol": "000660", "name": "SK하이닉스", "rank": 2, "score": 9},
            ],
        },
        {
            "candidates": valid_candidates,
            "ranked_candidates": [
                {"symbol": "005930", "name": "삼성전자", "rank": 1, "score": 101},
                {"symbol": "000660", "name": "SK하이닉스", "rank": 2, "score": 9},
            ],
        },
    ]

    for payload in invalid_payloads:
        response = clean_db.post("/v1/fund-manager/research", json=payload)
        assert response.status_code == 422

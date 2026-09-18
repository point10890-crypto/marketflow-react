from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
import asyncio

from engine import generator as generator_module
from engine.generator import SignalGenerator
from engine import llm_analyzer as analyzer_module
from engine.llm_analyzer import LLMAnalyzer
from app.services.ai_routing.contracts import AnalysisStatus, RoutingResult, TokenUsage


def test_generator_preserves_news_provenance_for_llm_evidence():
    published = datetime(2026, 9, 2, 8, 30, tzinfo=timezone.utc)
    news = SimpleNamespace(
        title="수주 공시",
        summary="계약 체결",
        source="연합뉴스",
        url="https://example.test/article",
        published_at=published,
    )

    payload = SignalGenerator._news_payload([news])

    assert payload == [{
        "title": "수주 공시",
        "summary": "계약 체결",
        "source": "연합뉴스",
        "url": "https://example.test/article",
        "published_at": "2026-09-02T08:30:00+00:00",
    }]


def test_generator_does_not_present_synthetic_search_time_as_publication_time():
    news = SimpleNamespace(
        code="",
        title="검색 기사",
        summary="날짜 파싱 안 됨",
        source="연합뉴스",
        url="https://example.test/article",
        published_at=datetime(2026, 9, 2, 8, 30, tzinfo=timezone.utc),
    )

    payload = SignalGenerator._news_payload([news])

    assert payload[0]["published_at"] == ""


def test_generator_normalizes_naive_naver_finance_time_from_kst_to_utc():
    news = SimpleNamespace(
        code="005930",
        title="금융 기사",
        summary="본문",
        source="연합뉴스",
        url="https://example.test/article",
        published_at=datetime(2026, 9, 3, 9, 0, 0),
    )

    payload = SignalGenerator._news_payload([news])

    assert payload[0]["published_at"] == "2026-09-03T00:00:00+00:00"


def test_generator_never_passes_ineligible_llm_text_into_buy_scoring():
    ineligible = {
        "score": 3,
        "reason": "비검증 요약",
        "buy_evidence_eligible": False,
    }
    eligible = {
        "score": 2,
        "reason": "검증 근거",
        "buy_evidence_eligible": True,
    }

    assert SignalGenerator._llm_result_for_scoring(ineligible) is None
    assert SignalGenerator._llm_result_for_scoring(eligible) is eligible


def test_generator_uses_one_generation_run_and_symbol_specific_news_request():
    generator = SignalGenerator.__new__(SignalGenerator)
    generator._generation_run_id = "jongga:2026-09-02:fixed"

    run_id, first = generator._news_request_identity("005930")
    second_run_id, second = generator._news_request_identity("000660")

    assert run_id == second_run_id == "jongga:2026-09-02:fixed"
    assert first == "jongga:2026-09-02:fixed:005930:news"
    assert second == "jongga:2026-09-02:fixed:000660:news"


def test_run_screener_passes_generation_run_id_to_multi_ai(monkeypatch):
    captured = {}

    class FakeSignal:
        def to_dict(self):
            return {"stock_code": "005930"}

    class FakeGenerator:
        _generation_run_id = None

        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def generate(self, **_kwargs):
            self._generation_run_id = "jongga:2026-09-02:fixed"
            return [FakeSignal()]

        def get_summary(self, _signals):
            return {
                "total": 1,
                "by_grade": {},
                "by_market": {},
            }

    class FakeMultiAI:
        def __init__(self):
            self.screeners = {"deepseek": SimpleNamespace(client=True)}

        async def screen_candidates(self, _signals, *, run_id=None):
            captured["run_id"] = run_id
            return {"picks": []}

    monkeypatch.setattr(generator_module, "SignalGenerator", FakeGenerator)
    monkeypatch.setattr(generator_module, "MultiAIConsensusScreener", FakeMultiAI)
    monkeypatch.setattr(
        generator_module,
        "save_result_to_json",
        lambda *_a, **kwargs: captured.update(saved_run_id=kwargs.get("run_id")),
    )

    asyncio.run(
        generator_module.run_screener(
            target_date=datetime(2026, 9, 2, tzinfo=timezone.utc).date()
        )
    )

    assert captured["run_id"] == "jongga:2026-09-02:fixed"
    assert captured["saved_run_id"] == "jongga:2026-09-02:fixed"


def test_save_result_persists_run_identity_for_ledger_join(monkeypatch):
    written = []
    result = SimpleNamespace(
        date=date(2026, 9, 2),
        total_candidates=1,
        filtered_count=0,
        signals=[],
        by_grade={},
        by_market={},
        processing_time_ms=10,
    )
    picks = {
        "picks": [],
        "routing": {
            "run_id": "jongga:2026-09-02:fixed",
            "request_id": "jongga:2026-09-02:fixed:multi-ai-primary",
        },
    }
    monkeypatch.setattr(
        generator_module,
        "_write_json_atomic",
        lambda path, payload, **_kwargs: written.append((path, payload)),
    )

    generator_module.save_result_to_json(
        result,
        claude_picks=picks,
        run_id="jongga:2026-09-02:fixed",
    )

    assert len(written) == 3
    assert any("jongga_v2_runs" in str(path) for path, _payload in written)
    assert all(
        payload["run_id"] == "jongga:2026-09-02:fixed"
        for _path, payload in written
    )
    assert all(
        payload["claude_picks"]["routing"]["request_id"].endswith(
            ":multi-ai-primary"
        )
        for _path, payload in written
    )


def test_routed_news_metadata_keeps_request_identity_without_attempts(monkeypatch):
    captured = []

    def fake_route(request):
        captured.append(request)
        return RoutingResult(
            text='{"score":2,"reason":"verified","themes":[]}',
            analysis_status=AnalysisStatus.SUCCESS_PRIMARY,
            primary_provider="deepseek",
            actual_provider="deepseek",
            model="deepseek-v4-flash",
            usage=TokenUsage(input_tokens=10, output_tokens=5),
        )

    monkeypatch.setattr(analyzer_module, "route_text", fake_route)
    analyzer = LLMAnalyzer.__new__(LLMAnalyzer)
    result = asyncio.run(
        analyzer.analyze_news_sentiment(
            "삼성전자",
            [{
                "title": "공시",
                "summary": "계약",
                "source": "연합뉴스",
                "url": "https://example.test/news",
                "published_at": datetime.now(timezone.utc).isoformat(),
            }],
            run_id="jongga:2026-09-02:fixed",
            request_id="jongga:2026-09-02:fixed:005930:news",
        )
    )

    assert captured[0].run_id == result["routing"]["run_id"]
    assert captured[0].request_id == result["routing"]["request_id"]


def test_single_stock_reanalysis_replaces_run_identity_and_writes_replay_artifact(
    monkeypatch, tmp_path
):
    engine_dir = tmp_path / "engine"
    data_dir = tmp_path / "data"
    engine_dir.mkdir()
    data_dir.mkdir()
    monkeypatch.setattr(generator_module, "__file__", str(engine_dir / "generator.py"))
    today = date.today()
    latest = data_dir / "jongga_v2_latest.json"
    original = {
        "run_id": "jongga:source-run",
        "signals": [{
            "stock_code": "005930",
            "stock_name": "삼성전자",
            "market": "KOSPI",
            "sector": "반도체",
            "current_price": 70000,
            "entry_price": 70000,
            "change_pct": 1.0,
            "trading_value": 1000000,
        }],
    }
    latest.write_text(__import__("json").dumps(original), encoding="utf-8")
    daily = data_dir / f"jongga_v2_results_{today:%Y%m%d}.json"
    daily.write_text(__import__("json").dumps(original), encoding="utf-8")
    captured = {}

    class FakeSignal:
        grade = SimpleNamespace(value="A")
        score = SimpleNamespace(total=10)

        def to_dict(self):
            return {"stock_code": "005930", "stock_name": "삼성전자", "score": 10}

    class FakeCollector:
        async def get_stock_detail(self, _code):
            return {"name": "삼성전자"}

    class FakeGenerator:
        _generation_run_id = None

        def __init__(self, **_kwargs):
            self._collector = FakeCollector()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def _analyze_stock(self, _stock, _target_date):
            captured["run_id"] = self._generation_run_id
            return FakeSignal()

    monkeypatch.setattr(generator_module, "SignalGenerator", FakeGenerator)

    result = asyncio.run(generator_module.analyze_single_stock_by_code("005930"))

    assert result is not None
    updated = __import__("json").loads(latest.read_text(encoding="utf-8"))
    assert captured["run_id"].startswith("jongga:reanalysis:")
    assert updated["run_id"] == captured["run_id"]
    assert updated["source_run_id"] == "jongga:source-run"
    run_artifacts = list((data_dir / "jongga_v2_runs").glob("*.json"))
    assert len(run_artifacts) == 1
    replay = __import__("json").loads(run_artifacts[0].read_text(encoding="utf-8"))
    assert replay["run_id"] == captured["run_id"]
    assert replay["signals"][0]["score"] == 10

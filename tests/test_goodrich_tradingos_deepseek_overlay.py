from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "deploy"
    / "goodrich_tradingos_overlay"
    / "openai_research.py"
)
ROOT = Path(__file__).resolve().parents[1]
APPLY_SCRIPT = ROOT / "deploy" / "apply_goodrich_tradingos_overlay.ps1"
ROLLBACK_SCRIPT = ROOT / "deploy" / "rollback_goodrich_tradingos_overlay.ps1"
START_SCRIPT = ROOT / "deploy" / "start_goodrich_tradingos.ps1"
OVERLAY_ROOT = ROOT / "deploy" / "goodrich_tradingos_overlay"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "goodrich_tradingos_overlay_openai_research", MODULE_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _analysis_payload(symbols: list[str]) -> str:
    return json.dumps(
        {
            "market_summary": "검증된 후보 요약",
            "analyses": [
                {
                    "symbol": symbol,
                    "thesis": "검증된 강점",
                    "risk": "검증된 위험",
                    "verdict": "WATCH",
                    "conviction_score": 70,
                    "monitoring_focus": "KIS 가격과 거래대금",
                }
                for symbol in symbols
            ],
        },
        ensure_ascii=False,
    )


def test_deepseek_v4_pro_is_primary_with_max_reasoning(monkeypatch):
    module = _load_module()
    calls: list[dict] = []

    class FakeOpenAI:
        def __init__(self, **kwargs):
            calls.append({"kind": "client", **kwargs})
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._create_chat)
            )
            self.responses = SimpleNamespace(create=self._unexpected_openai)

        def _create_chat(self, **kwargs):
            calls.append({"kind": "deepseek", **kwargs})
            message = SimpleNamespace(content=_analysis_payload(["005930", "000660"]))
            return SimpleNamespace(id="ds-response", choices=[SimpleNamespace(message=message)])

        @staticmethod
        def _unexpected_openai(**_kwargs):
            raise AssertionError("OpenAI fallback must not run after DeepSeek succeeds")

    monkeypatch.setattr(module, "OpenAI", FakeOpenAI)
    agent = module.DeepSeekFirstResearchAgent(
        deepseek_api_key="test-deepseek-key-1234567890",
        deepseek_model="deepseek-v4-pro",
        openai_credentials_file="unused.txt",
        openai_model="gpt-5.5",
    )

    result = agent.analyze(
        [{"symbol": "005930", "name": "삼성전자"}, {"symbol": "000660", "name": "SK하이닉스"}]
    )

    assert result["provider"] == "deepseek"
    assert result["model"] == "deepseek-v4-pro"
    assert result.get("fallback_from") is None
    deepseek_call = next(call for call in calls if call["kind"] == "deepseek")
    assert deepseek_call["model"] == "deepseek-v4-pro"
    assert deepseek_call["reasoning_effort"] == "max"
    assert deepseek_call["extra_body"] == {"thinking": {"type": "enabled"}}
    assert deepseek_call["response_format"] == {"type": "json_object"}
    client_call = next(call for call in calls if call["kind"] == "client")
    assert client_call["base_url"] == "https://api.deepseek.com"
    assert client_call["timeout"] == 30
    assert client_call["max_retries"] == 0


def test_openai_runs_only_after_deepseek_failure(monkeypatch, tmp_path: Path):
    module = _load_module()
    openai_key_file = tmp_path / "openai.txt"
    openai_key_file.write_text("test-only-fallback-key", encoding="utf-8")
    calls: list[str] = []

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.is_deepseek = "base_url" in kwargs
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._create_chat)
            )
            self.responses = SimpleNamespace(create=self._create_response)

        def _create_chat(self, **_kwargs):
            calls.append("deepseek")
            raise RuntimeError("simulated DeepSeek outage")

        def _create_response(self, **_kwargs):
            calls.append("openai")
            return SimpleNamespace(
                id="oa-response",
                output_text=_analysis_payload(["005930"]),
            )

    monkeypatch.setattr(module, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(module, "load_openai_api_key", lambda _path: "test-api-key")
    agent = module.DeepSeekFirstResearchAgent(
        deepseek_api_key="test-deepseek-key-1234567890",
        deepseek_model="deepseek-v4-pro",
        openai_credentials_file=str(openai_key_file),
        openai_model="gpt-5.5",
    )

    result = agent.analyze([{"symbol": "005930", "name": "삼성전자"}])

    assert calls == ["deepseek", "openai"]
    assert result["provider"] == "openai"
    assert result["fallback_from"] == "deepseek"
    assert result["storage_provider"] == "openai_fallback_from_deepseek"


def test_both_provider_failures_raise_safe_pipeline_error(monkeypatch, tmp_path: Path):
    module = _load_module()
    openai_key_file = tmp_path / "openai.txt"
    openai_key_file.write_text("test-only-fallback-key", encoding="utf-8")

    class FakeOpenAI:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._fail)
            )
            self.responses = SimpleNamespace(create=self._fail)

        @staticmethod
        def _fail(**_kwargs):
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(module, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(module, "load_openai_api_key", lambda _path: "test-api-key")
    agent = module.DeepSeekFirstResearchAgent(
        deepseek_api_key="test-deepseek-key-1234567890",
        deepseek_model="deepseek-v4-pro",
        openai_credentials_file=str(openai_key_file),
        openai_model="gpt-5.5",
    )

    with pytest.raises(module.ResearchPipelineError, match="백업"):
        agent.analyze([{"symbol": "005930", "name": "삼성전자"}])


def test_overlay_manifest_matches_directly_copied_inputs():
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "deploy/goodrich_tradingos_overlay/** text eol=lf" in attributes
    manifest = json.loads((OVERLAY_ROOT / "manifest.json").read_text(encoding="utf-8"))
    entries = {entry["target"]: entry for entry in manifest["files"]}
    direct_inputs = {
        "services/api/src/goodrich/openai_research.py": "openai_research.py",
        "services/api/tests/test_fund_manager.py": "test_fund_manager.py",
        "services/api/tests/test_marketflow_contract.py": "test_marketflow_contract.py",
    }

    for target, filename in direct_inputs.items():
        digest = hashlib.sha256((OVERLAY_ROOT / filename).read_bytes()).hexdigest()
        assert entries[target]["patched_sha256"] == digest


def test_deploy_scripts_enforce_atomic_backup_and_fresh_process_contract():
    apply_text = APPLY_SCRIPT.read_text(encoding="utf-8")
    rollback_text = ROLLBACK_SCRIPT.read_text(encoding="utf-8")
    start_text = START_SCRIPT.read_text(encoding="utf-8")

    assert apply_text.index("Get-FileHash -LiteralPath $backupFile") < apply_text.index(
        "[IO.File]::WriteAllText($backupManifestTemp"
    ) < apply_text.index(
        "Move-Item -LiteralPath $backupManifestTemp"
    )
    assert apply_text.index("Goodrich patched hash mismatch") < apply_text.index(
        "& $python -m pytest tests -q"
    )
    assert rollback_text.index("Backup file hash mismatch") < rollback_text.rindex(
        "$previousPids = @(Stop-GoodrichTaskAndWait)"
    )

    for text in (apply_text, rollback_text):
        assert "Get-GoodrichListenerPids" in text
        assert "taskkill.exe /PID $processId /T /F" in text
        assert "Get-ScheduledTaskInfo" in text
        assert "$previousStartTicks" in text
        assert "$process.StartTime.ToUniversalTime().Ticks -eq $expectedTicks" in text
        assert "$PreviousPids -contains $processId" in text
        assert "$process.StartTime -ge $startedAfter" in text
        assert "$response.status -eq 'ok'" in text
        assert "$response.environment -eq 'production'" in text
        assert "[void](Wait-GoodrichHealth)" not in text

    assert "Goodrich automatic rollback hash mismatch" in apply_text
    assert "Goodrich TradingOS remains stopped" in rollback_text
    assert "$nativeExitCode = $LASTEXITCODE" in start_text
    assert "Test-Path -LiteralPath $python -PathType Leaf" in start_text
    assert "$global:LASTEXITCODE = $null" in start_text
    assert "$null -eq $nativeExitCode" in start_text
    assert start_text.rstrip().endswith("exit $exitCode")


def test_generated_contract_requires_exact_rank_and_numeric_score():
    apply_text = APPLY_SCRIPT.read_text(encoding="utf-8")

    assert "not isinstance(rank, int) or isinstance(rank, bool)" in apply_text
    assert "not isinstance(raw_score, (int, float))" in apply_text
    assert "isinstance(raw_score, bool)" in apply_text
    assert "not math.isfinite(score) or not 0 <= score <= 100" in apply_text
    assert 'upstream_score = float(ranking_by_symbol[symbol]["score"])' in apply_text
    assert "ranked_candidates.sort" not in apply_text

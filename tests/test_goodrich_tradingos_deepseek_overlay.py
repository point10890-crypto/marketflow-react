from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import venv
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


def _fake_goodrich_python(
    root: Path,
    *,
    supports_responses: bool,
    responses_callable: bool = True,
    uvicorn_exit_code: int | None = None,
) -> Path:
    venv_root = root / ".venv"
    venv.EnvBuilder(with_pip=False).create(venv_root)
    python = venv_root / "Scripts" / "python.exe"
    site_packages = venv_root / "Lib" / "site-packages"
    openai_package = site_packages / "openai"
    openai_package.mkdir(parents=True)
    responses_class = (
        "class _Responses:\n"
        "    def create(\n"
        "        self, *, text=None, reasoning=None, max_output_tokens=None,\n"
        "        store=None, **_kwargs\n"
        "    ):\n"
        "        return None\n\n"
        if supports_responses and responses_callable
        else ""
    )
    responses_assignment = (
        "self.responses = _Responses()"
        if supports_responses and responses_callable
        else "self.responses = object()"
        if supports_responses
        else ""
    )
    (openai_package / "__init__.py").write_text(
        "from pathlib import Path\n"
        "import os\n\n"
        f"{responses_class}"
        "class OpenAI:\n"
        "    def __init__(self, **_kwargs):\n"
        "        marker = os.environ.get('GOODRICH_SDK_CHECK_MARKER')\n"
        "        if marker:\n"
        "            Path(marker).write_text('checked', encoding='utf-8')\n"
        f"        {responses_assignment or 'pass'}\n",
        encoding="utf-8",
    )
    if uvicorn_exit_code is not None:
        uvicorn_package = site_packages / "uvicorn"
        uvicorn_package.mkdir()
        (uvicorn_package / "__init__.py").write_text("", encoding="utf-8")
        (uvicorn_package / "__main__.py").write_text(
            "from pathlib import Path\n"
            "import os\n"
            "marker = os.environ.get('GOODRICH_UVICORN_MARKER')\n"
            "if marker:\n"
            "    Path(marker).write_text(\n"
            "        os.environ.get('GOODRICH_DATABASE_URL', ''), encoding='utf-8'\n"
            "    )\n"
            f"raise SystemExit({uvicorn_exit_code})\n",
            encoding="utf-8",
        )
    return python


def _powershell_result(command: list[str], *, env: dict[str, str] | None = None):
    return subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def test_deepseek_v4_pro_is_primary_with_max_reasoning(monkeypatch):
    module = _load_module()
    calls: list[dict] = []

    class FakeOpenAI:
        def __init__(self, **kwargs):
            calls.append({"kind": "client", **kwargs})
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._unexpected_chat)
            )
            self.responses = SimpleNamespace(create=self._create_response)

        def _create_response(self, **kwargs):
            calls.append({"kind": "deepseek", **kwargs})
            return SimpleNamespace(
                id="ds-response",
                status="completed",
                output_text=_analysis_payload(["005930", "000660"]),
            )

        @staticmethod
        def _unexpected_chat(**_kwargs):
            raise AssertionError("DeepSeek must use Responses structured output")

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
    assert deepseek_call["reasoning"] == {"effort": "max"}
    assert deepseek_call["text"]["format"]["type"] == "json_schema"
    assert deepseek_call["text"]["format"]["name"] == "fund_manager_research"
    assert deepseek_call["text"]["format"]["schema"]["required"] == [
        "market_summary",
        "analyses",
    ]
    assert deepseek_call["store"] is False
    client_call = next(call for call in calls if call["kind"] == "client")
    assert client_call["base_url"] == "https://api.deepseek.com"
    assert client_call["timeout"] == 60
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
                completions=SimpleNamespace(create=self._unexpected_chat)
            )
            self.responses = SimpleNamespace(create=self._create_response)

        @staticmethod
        def _unexpected_chat(**_kwargs):
            raise AssertionError("DeepSeek must use Responses structured output")

        def _create_response(self, **_kwargs):
            if self.is_deepseek:
                calls.append("deepseek")
                raise RuntimeError("simulated DeepSeek outage")
            calls.append("openai")
            return SimpleNamespace(
                id="oa-response",
                status="completed",
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


def test_incomplete_deepseek_response_uses_openai_backup(monkeypatch, tmp_path: Path):
    module = _load_module()
    openai_key_file = tmp_path / "openai.txt"
    openai_key_file.write_text("test-only-fallback-key", encoding="utf-8")
    calls: list[str] = []

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.is_deepseek = "base_url" in kwargs
            self.responses = SimpleNamespace(create=self._create_response)

        def _create_response(self, **_kwargs):
            if self.is_deepseek:
                calls.append("deepseek")
                return SimpleNamespace(
                    id="ds-incomplete",
                    status="incomplete",
                    incomplete_details=SimpleNamespace(reason="max_output_tokens"),
                    output_text=_analysis_payload(["005930"]),
                )
            calls.append("openai")
            return SimpleNamespace(
                id="oa-response",
                status="completed",
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


@pytest.mark.parametrize(
    "invalid_payload",
    [
        {
            "market_summary": "검증된 후보 요약",
            "analyses": [
                {
                    "symbol": "005930",
                    "thesis": "검증된 강점",
                    "risk": "검증된 위험",
                    "verdict": "watch",
                    "conviction_score": 70,
                    "monitoring_focus": "KIS 가격과 거래대금",
                }
            ],
        },
        {
            "market_summary": "검증된 후보 요약",
            "analyses": [
                {
                    "symbol": "005930",
                    "thesis": "검증된 강점",
                    "risk": "검증된 위험",
                    "verdict": "WATCH",
                    "conviction_score": True,
                    "monitoring_focus": "KIS 가격과 거래대금",
                }
            ],
        },
        {
            "market_summary": "검증된 후보 요약",
            "analyses": [
                {
                    "symbol": "005930",
                    "thesis": "검증된 강점",
                    "risk": "검증된 위험",
                    "verdict": "WATCH",
                    "conviction_score": 70.5,
                    "monitoring_focus": "KIS 가격과 거래대금",
                }
            ],
        },
        {
            "market_summary": "검증된 후보 요약",
            "analyses": [
                {
                    "symbol": "005930",
                    "thesis": "검증된 강점",
                    "risk": "검증된 위험",
                    "verdict": "WATCH",
                    "conviction_score": 70,
                    "monitoring_focus": "KIS 가격과 거래대금",
                    "unexpected": "must be rejected",
                }
            ],
        },
        {
            "market_summary": "검증된 후보 요약",
            "analyses": [
                {
                    "symbol": "005930",
                    "thesis": "검증된 강점",
                    "risk": "검증된 위험",
                    "verdict": "WATCH",
                    "conviction_score": 70,
                    "monitoring_focus": "KIS 가격과 거래대금",
                }
            ],
            "unexpected": "must be rejected",
        },
    ],
    ids=[
        "lowercase-verdict",
        "boolean-conviction",
        "float-conviction",
        "unexpected-analysis-field",
        "unexpected-top-level-field",
    ],
)
def test_result_validation_rejects_noncanonical_schema(invalid_payload):
    module = _load_module()

    with pytest.raises(ValueError):
        module._validate_result(
            invalid_payload,
            [{"symbol": "005930", "name": "삼성전자"}],
        )


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


def test_incomplete_openai_backup_raises_safe_pipeline_error(
    monkeypatch, tmp_path: Path
):
    module = _load_module()
    openai_key_file = tmp_path / "openai.txt"
    openai_key_file.write_text("test-only-fallback-key", encoding="utf-8")

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.is_deepseek = "base_url" in kwargs
            self.responses = SimpleNamespace(create=self._create_response)

        def _create_response(self, **_kwargs):
            if self.is_deepseek:
                raise RuntimeError("simulated DeepSeek outage")
            return SimpleNamespace(
                id="oa-incomplete",
                status="incomplete",
                incomplete_details=SimpleNamespace(reason="max_output_tokens"),
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

    with pytest.raises(module.ResearchPipelineError, match="모두 실패"):
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


@pytest.mark.skipif(shutil.which("powershell") is None, reason="PowerShell is required")
@pytest.mark.parametrize(
    ("supports_responses", "responses_callable"),
    [(False, False), (True, False)],
    ids=["missing-responses", "noncallable-create"],
)
def test_apply_refuses_sdk_without_responses_before_backup_or_source_mutation(
    tmp_path: Path, supports_responses: bool, responses_callable: bool
):
    goodrich_root = tmp_path / "GoodrichTradingOS"
    source_root = goodrich_root / "services" / "api" / "src" / "goodrich"
    tests_root = goodrich_root / "services" / "api" / "tests"
    source_root.mkdir(parents=True)
    tests_root.mkdir(parents=True)
    original: dict[Path, bytes] = {}
    for filename in ("openai_research.py", "fund_manager.py", "main.py"):
        path = source_root / filename
        path.write_text(f"original {filename}\n", encoding="utf-8")
        original[path] = path.read_bytes()

    python = _fake_goodrich_python(
        goodrich_root,
        supports_responses=supports_responses,
        responses_callable=responses_callable,
    )
    marker = tmp_path / "sdk-check.txt"
    env = dict(os.environ)
    env["GOODRICH_SDK_CHECK_MARKER"] = str(marker)
    result = _powershell_result(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(APPLY_SCRIPT),
            "-GoodrichRoot",
            str(goodrich_root),
            "-PythonPath",
            str(python),
            "-SkipServiceRestart",
        ],
        env=env,
    )

    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "Responses API support" in combined
    assert marker.exists(), combined
    assert marker.read_text(encoding="utf-8") == "checked"
    assert not (goodrich_root / "backups").exists()
    for path, expected in original.items():
        assert path.read_bytes() == expected


@pytest.mark.skipif(shutil.which("powershell") is None, reason="PowerShell is required")
def test_start_script_exposes_isolated_runtime_parameters():
    result = _powershell_result(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            (
                f"$parameters = (Get-Command -Name '{START_SCRIPT}').Parameters; "
                "[bool]($parameters.ContainsKey('Root') -and "
                "$parameters.ContainsKey('MarketFlowEnv'))"
            ),
        ]
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().lower() == "true"


@pytest.mark.skipif(shutil.which("powershell") is None, reason="PowerShell is required")
@pytest.mark.parametrize(
    ("supports_responses", "responses_callable"),
    [(False, False), (True, False)],
    ids=["missing-responses", "noncallable-create"],
)
def test_start_refuses_sdk_without_responses_before_log_or_uvicorn(
    tmp_path: Path, supports_responses: bool, responses_callable: bool
):
    goodrich_root = tmp_path / "GoodrichTradingOS"
    (goodrich_root / "services" / "api").mkdir(parents=True)
    _fake_goodrich_python(
        goodrich_root,
        supports_responses=supports_responses,
        responses_callable=responses_callable,
    )
    marketflow_env = tmp_path / "marketflow.env"
    marketflow_env.write_text("DEEPSEEK_API_KEY=test-only\n", encoding="utf-8")
    sdk_marker = tmp_path / "sdk-check.txt"
    uvicorn_marker = tmp_path / "uvicorn-launch.txt"
    env = dict(os.environ)
    env["GOODRICH_SDK_CHECK_MARKER"] = str(sdk_marker)
    env["GOODRICH_UVICORN_MARKER"] = str(uvicorn_marker)

    result = _powershell_result(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(START_SCRIPT),
            "-Root",
            str(goodrich_root),
            "-MarketFlowEnv",
            str(marketflow_env),
        ],
        env=env,
    )

    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "Responses API support" in combined
    assert sdk_marker.read_text(encoding="utf-8") == "checked"
    assert not (goodrich_root / "logs").exists()
    assert not uvicorn_marker.exists()


@pytest.mark.skipif(shutil.which("powershell") is None, reason="PowerShell is required")
def test_start_launches_only_after_responses_sdk_preflight_passes(tmp_path: Path):
    goodrich_root = tmp_path / "GoodrichTradingOS"
    (goodrich_root / "services" / "api").mkdir(parents=True)
    _fake_goodrich_python(
        goodrich_root,
        supports_responses=True,
        uvicorn_exit_code=23,
    )
    marketflow_env = tmp_path / "marketflow.env"
    marketflow_env.write_text("DEEPSEEK_API_KEY=test-only\n", encoding="utf-8")
    sdk_marker = tmp_path / "sdk-check.txt"
    uvicorn_marker = tmp_path / "uvicorn-launch.txt"
    env = dict(os.environ)
    env["GOODRICH_SDK_CHECK_MARKER"] = str(sdk_marker)
    env["GOODRICH_UVICORN_MARKER"] = str(uvicorn_marker)

    result = _powershell_result(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(START_SCRIPT),
            "-Root",
            str(goodrich_root),
            "-MarketFlowEnv",
            str(marketflow_env),
        ],
        env=env,
    )

    assert result.returncode == 23, result.stdout + result.stderr
    assert sdk_marker.read_text(encoding="utf-8") == "checked"
    expected_database_url = (
        "sqlite:///" + (goodrich_root / "data" / "goodrich.db").as_posix()
    )
    assert uvicorn_marker.read_text(encoding="utf-8") == expected_database_url


def test_generated_contract_requires_exact_rank_and_numeric_score():
    apply_text = APPLY_SCRIPT.read_text(encoding="utf-8")

    assert "not isinstance(rank, int) or isinstance(rank, bool)" in apply_text
    assert "not isinstance(raw_score, (int, float))" in apply_text
    assert "isinstance(raw_score, bool)" in apply_text
    assert "not math.isfinite(score) or not 0 <= score <= 100" in apply_text
    assert 'upstream_score = float(ranking_by_symbol[symbol]["score"])' in apply_text
    assert "ranked_candidates.sort" not in apply_text

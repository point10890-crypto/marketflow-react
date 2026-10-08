"""Scanner persistence safety; no providers or delivery are exercised.

Fixtures disable semantic/live/DeepSeek modes and isolate deterministic inputs.
The actual atomic writer, run reader, and latest-history lookup remain exercised.
"""
import copy
import errno
import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services.mirofish import alpha_scanner
from app.utils import storage_guard


@pytest.fixture
def scanner(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_guard.shutil, "disk_usage", lambda path: type("Usage", (), {"free": 20 * 1024**3})())
    data = tmp_path / "data"
    data.mkdir()
    runs = data / "admin_mirofish" / "scanner_runs"
    monkeypatch.setattr(alpha_scanner, "DATA_ROOT", str(data))
    monkeypatch.setattr(alpha_scanner, "SCANNER_RUNS_ROOT", str(runs))
    for name, value in {
        "MIROFISH_SEMANTIC_RANKING_ENABLED": "false",
        "MIROFISH_DEEPSEEK_RERANK_ENABLED": "0",
        "MIROFISH_ALPHA_SCANNER_LIVE_KIS": "0",
        "KIND_BLACKLIST_LIVE_FETCH": "false",
        "CREDIT_BALANCE_LIVE_FETCH": "false",
        "TRADINGVIEW_LIVE_IN_SCANNER": "false",
    }.items():
        monkeypatch.setenv(name, value)

    (data / "daily_prices.csv").write_text("ticker,date,current_price\n005930,2026-10-07,70000\n", encoding="utf-8")
    (data / "screener_leading_latest.json").write_text(
        json.dumps({"generated_at": "2026-10-08T01:00:00+00:00"}), encoding="utf-8"
    )

    current = {"time": datetime(2026, 10, 8, 1, tzinfo=timezone.utc), "ticks": 0}
    time_lock = threading.Lock()

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            with time_lock:
                current["ticks"] += 1
                value = current["time"] + timedelta(microseconds=current["ticks"])
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)

    monkeypatch.setattr(alpha_scanner, "datetime", Clock)
    state = {"freshness": "fresh", "idle": False, "adaptive": False}
    candidate = {
        "symbol": "005930", "name": "삼성전자", "display_name": "삼성전자",
        "market": "KOSPI", "action": "BUY_CANDIDATE", "rank": 1,
        "alpha_score": 85, "risk_score": 20, "ranking_score": 75,
        "signal_quality": "actionable", "analysis_profile": {"source_count": 3},
        "strategy_tags": [], "price": {"date": "2026-10-08", "current_price": 70000},
        "freshness": {"status": "fresh"}, "replay_context": {"lookahead_safe": True},
    }
    monkeypatch.setattr(alpha_scanner, "_load_artifacts", lambda: {"candidate_symbols": {"005930"}})
    monkeypatch.setattr(
        alpha_scanner, "_performance_advisory",
        lambda: {"available": False, "applied_to_scoring": state["adaptive"]},
    )
    monkeypatch.setattr(
        alpha_scanner, "_build_candidate_pool",
        lambda *args, **kwargs: [] if state["idle"] else [copy.deepcopy(candidate)],
    )
    monkeypatch.setattr(
        alpha_scanner, "_source_files",
        lambda *args, **kwargs: [{
            "file": "data/daily_prices.csv", "available": True, "exists": True,
            "required": True, "alert_required": True, "freshness": state["freshness"],
        }],
    )
    monkeypatch.setattr(alpha_scanner, "_maybe_deepseek_rerank_candidates", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        alpha_scanner, "_attach_chart_analogue_shadow",
        lambda *args, **kwargs: {"status": "disabled", "items": []},
    )

    def poll(payload=None):
        return alpha_scanner.run_scanner_alert_check(
            payload or {"limit": 20}, state_path=str(data / "private_events.json"),
            commit_state=False,
        )

    def advance(seconds):
        current["time"] += timedelta(seconds=seconds)

    return {"data": data, "runs": runs, "state": state, "poll": poll, "advance": advance}



def run_ids(scanner):
    return sorted(p.name for p in scanner["runs"].iterdir() if p.is_dir()) if scanner["runs"].exists() else []



@pytest.mark.parametrize("free_bytes", [0, 1024**3 - 1])
def test_low_storage_blocks_collection_and_preserves_prior_report(scanner, monkeypatch, free_bytes):
    first = alpha_scanner.create_scanner_run({"limit": 20})
    previous = scanner["runs"] / first["id"] / "run.json"
    previous_bytes = previous.read_bytes()
    before = run_ids(scanner)
    calls = []
    monkeypatch.setattr(storage_guard.shutil, "disk_usage", lambda path: type("Usage", (), {"free": free_bytes})())

    def forbidden_collection():
        calls.append("provider")
        raise AssertionError("storage must be checked before collection")

    monkeypatch.setattr(alpha_scanner, "_load_artifacts", forbidden_collection)
    with pytest.raises(OSError) as raised:
        alpha_scanner.create_scanner_run({"limit": 20})
    assert raised.value.errno == errno.ENOSPC
    assert "scanner_storage:low_space" in str(raised.value)
    assert calls == []
    assert run_ids(scanner) == before
    assert previous.read_bytes() == previous_bytes



@pytest.mark.parametrize("status,code", [("unavailable", errno.EIO), ("invalid_config", errno.EINVAL)])
def test_unavailable_storage_fails_before_collection_or_any_directory(scanner, monkeypatch, status, code):
    monkeypatch.setattr(storage_guard, "check_storage", lambda *args, **kwargs: {"status": status})
    monkeypatch.setattr(alpha_scanner, "_load_artifacts", lambda: pytest.fail("unexpected provider collection"))
    with pytest.raises(OSError) as raised:
        alpha_scanner.create_scanner_run({"limit": 20})
    assert raised.value.errno == code
    assert "scanner_storage:" + status in str(raised.value)
    assert not (scanner["data"] / "admin_mirofish").exists()



def test_completed_header_is_published_only_after_all_artifacts(scanner, monkeypatch):
    prior = alpha_scanner.create_scanner_run({"limit": 20})
    prior_header = scanner["runs"] / prior["id"] / "run.json"
    prior_bytes = prior_header.read_bytes()
    writer = alpha_scanner.write_json_atomic

    def full_disk(path, body, **kwargs):
        if Path(path).name == "chart_analogue.json":
            raise OSError(errno.ENOSPC, "No space left on device")
        return writer(path, body, **kwargs)

    monkeypatch.setattr(alpha_scanner, "write_json_atomic", full_disk)
    with pytest.raises(OSError):
        alpha_scanner.create_scanner_run({"limit": 20})
    assert [path.parent.name for path in scanner["runs"].glob("*/run.json")] == [prior["id"]]
    assert prior_header.read_bytes() == prior_bytes
    assert alpha_scanner.read_latest_scanner_run()["id"] == prior["id"]



def test_manual_and_explicit_fresh_scans_keep_distinct_complete_runs(scanner):
    first = alpha_scanner.create_scanner_run({"limit": 20})
    second = alpha_scanner.create_scanner_run({"limit": 20, "force_fresh": True})
    assert first["id"] != second["id"]
    assert len(run_ids(scanner)) == 2
    for run in (first, second):
        assert alpha_scanner.read_scanner_run(run["id"])["status"] == "completed"
        for filename in alpha_scanner.SCANNER_ARTIFACT_FILENAMES:
            assert alpha_scanner.read_scanner_run_artifact(run["id"], filename)["run_id"] == run["id"]

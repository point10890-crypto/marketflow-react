from importlib import import_module

import pytest

from tests.test_alpha_lab_candidate_service import Calendar
from tests.test_alpha_lab_candidate_store import data, desk


def module():
    return import_module("app.services.mirofish.alpha_lab.regular_service")


def test_cash_bootstrap_uses_fresh_protocol_and_saved_only_projection(tmp_path, monkeypatch):
    mod = module()
    inputs = data()
    inputs["provenance"]["source_contract_hash"] = "f" * 64
    monkeypatch.setattr(mod, "_acquire", lambda *a, **k: inputs)
    calls = []

    def detect(*args):
        calls.append(1)
        return dict(desk(), candidates=[])

    monkeypatch.setattr(mod.candidate_service, "_detect", detect)
    old = tmp_path / "candidate-desk" / "protocol.json"
    old.parent.mkdir()
    old.write_text("legacy", encoding="utf-8")
    now = "2026-10-22T00:02:00Z"
    first = mod.refresh_desk(tmp_path, now=now, calendar_provider=Calendar())
    assert first["state"] == "held" and first["candidates"] == []
    assert first["entry_session"] == "2026-10-23"
    assert first["source"]["regular_session_verified"] is True
    assert first["source"]["volume_basis"] == "KIS_published_daily"
    assert first["protocol"]["earliest_session"] == "2026-10-23"
    assert first["protocol"]["decision_sessions"] == 60
    assert first["protocol"]["maturation_sessions"] == 10

    current = mod.select_directory(tmp_path)
    assert current.name == "candidate-regular-v1"
    record, = mod.candidate_store.read_decisions(current)["records"]
    assert record["in_fixed_window"] is False
    assert record["source_contract_hash"] == "f" * 64
    replay = mod.refresh_desk(tmp_path, now=now, calendar_provider=Calendar())
    assert first["decision_id"] == replay["decision_id"]
    assert calls == [1]
    assert old.read_text(encoding="utf-8") == "legacy"

    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod.candidate_service, "_legacy_read", lambda *a, **k: dict(state="ready"))
    before = {p: p.read_bytes() for p in tmp_path.rglob("*.json")}
    assert mod.read_status(now=now)["candidate_desk"]["decision_id"] == first["decision_id"]
    assert {p: p.read_bytes() for p in tmp_path.rglob("*.json")} == before
    assert calls == [1]

    def fail(*a, **k):
        raise ValueError("provider secret")

    monkeypatch.setattr(mod, "_acquire", fail)
    failed = mod.refresh_desk(tmp_path, now=now, calendar_provider=Calendar())
    assert failed["state"] == "failed" and failed["decision_id"] == first["decision_id"]
    assert "provider secret" not in (current / "attempt.json").read_text(encoding="utf-8")
    assert mod.read_status(now=now)["candidate_desk"]["state"] == "failed"


def test_failed_canonical_attempt_cannot_republish_stale_candidate_baseline(tmp_path, monkeypatch):
    mod = module()
    directory = tmp_path / "inputs"
    mod.store._write(directory / "current.json", dict(
        snapshot_id="old", latest_session="2026-10-21", hashes=dict(universe_report="a" * 64)))
    mod.store._write(directory / "last_attempt.json", dict(status="failed", snapshot_id="new"))
    monkeypatch.setattr(mod.regular_inputs, "collect_inputs",
                        lambda *a, **k: pytest.fail("stale canonical scope reached collection"))
    assert mod.select_directory(tmp_path).name == "candidate-desk"
    assert mod.refresh_desk(tmp_path, now="2026-10-22T00:02:00Z", calendar_provider=Calendar()) is None
    assert mod.select_directory(tmp_path).name == "candidate-regular-v1"


def test_same_session_revision_does_not_reseal_first_decision(tmp_path, monkeypatch):
    mod = module()
    baseline = data()
    monkeypatch.setattr(mod, "_acquire", lambda *a, **k: baseline)
    monkeypatch.setattr(mod.candidate_service, "_detect", lambda *_: desk())
    now = "2026-10-22T00:02:00Z"
    first = mod.refresh_desk(tmp_path, now=now, calendar_provider=Calendar())
    assert first["state"] == "ready"
    baseline["input_fingerprint"] = "c" * 64
    baseline["prices_by_symbol"]["005930"][-1]["close"] = 100.
    revised = mod.refresh_desk(tmp_path, now=now, calendar_provider=Calendar())
    assert revised["state"] == "held" and "source_revision" in revised["reasons"]
    assert revised["decision_id"] == first["decision_id"]
    directory = mod.select_directory(tmp_path)
    record, = mod.candidate_store.read_decisions(directory)["records"]
    assert record["desk"]["candidates"][0]["plan"]["entry_price"] == 101.
    observation = mod.candidate_store._load(directory / "observations.json")["records"][first["decision_id"]]
    assert observation["revisions"][0]["fingerprint"] == "c" * 64

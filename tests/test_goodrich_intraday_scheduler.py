from __future__ import annotations

import json

from scripts import run_goodrich_intraday_cycle as scheduler


def _use_temp_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(scheduler, "LOCK_PATH", tmp_path / "cycle.lock")
    monkeypatch.setattr(scheduler, "STATUS_PATH", tmp_path / "status.json")


def test_cycle_skips_when_market_is_closed(monkeypatch, tmp_path):
    _use_temp_paths(monkeypatch, tmp_path)
    monkeypatch.setattr("app.services.kis_screener.is_market_open", lambda: False)

    def unexpected_call():
        raise AssertionError("external pipeline must not run while the market is closed")

    monkeypatch.setattr(
        "app.services.mirofish.goodrich_client.monitor_fund_manager",
        unexpected_call,
    )
    monkeypatch.setattr(
        "app.services.mirofish.goodrich_client.run_research",
        unexpected_call,
    )

    result = scheduler.run_cycle()

    assert result["status"] == "skipped"
    assert result["reason"] == "market_closed"
    assert json.loads(scheduler.STATUS_PATH.read_text(encoding="utf-8"))["reason"] == "market_closed"


def test_forced_cycle_monitors_before_detecting_new_candidates(monkeypatch, tmp_path):
    _use_temp_paths(monkeypatch, tmp_path)
    calls = []

    def monitor():
        calls.append("monitor")
        return {"active_count": 3}

    def research():
        calls.append("research")
        return {
            "integration": {
                "market_status": "open",
                "candidate_count": 9,
                "universe_size": 3,
            },
            "picks": [
                {
                    "symbol": "005930",
                    "name": "삼성전자",
                    "status": "monitoring",
                    "current_price": 100,
                    "target_price": 110,
                    "stop_price": 95,
                }
            ],
        }

    monkeypatch.setattr(
        "app.services.mirofish.goodrich_client.monitor_fund_manager",
        monitor,
    )
    monkeypatch.setattr(
        "app.services.mirofish.goodrich_client.run_research",
        research,
    )

    result = scheduler.run_cycle(force=True)

    assert calls == ["monitor", "research"]
    assert result["status"] == "completed"
    assert result["detected_candidates"] == 9
    assert result["monitored_active_count"] == 3
    assert result["top3"][0]["symbol"] == "005930"
    assert not scheduler.LOCK_PATH.exists()


def test_cycle_skips_when_another_cycle_holds_the_lock(monkeypatch, tmp_path):
    _use_temp_paths(monkeypatch, tmp_path)
    scheduler.LOCK_PATH.write_text("active", encoding="utf-8")

    result = scheduler.run_cycle(force=True)

    assert result["status"] == "skipped"
    assert result["reason"] == "cycle_already_running"

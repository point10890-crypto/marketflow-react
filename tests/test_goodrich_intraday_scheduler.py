from __future__ import annotations

import json

from scripts import run_goodrich_intraday_cycle as scheduler


def _use_temp_paths(monkeypatch, tmp_path):
    """Redirect every artifact the cycle writes. Missing one pollutes real data."""
    monkeypatch.setattr(scheduler, "LOCK_PATH", tmp_path / "cycle.lock")
    monkeypatch.setattr(scheduler, "STATUS_PATH", tmp_path / "status.json")
    monkeypatch.setattr(scheduler, "LEDGER_PATH", tmp_path / "ledger.jsonl")


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
    sent_results = []

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
    monkeypatch.setattr(
        scheduler,
        "_send_top3_telegram",
        lambda result: sent_results.append(result.copy()) or True,
    )

    result = scheduler.run_cycle(force=True)

    assert calls == ["monitor", "research"]
    assert result["status"] == "completed"
    assert result["detected_candidates"] == 9
    assert result["monitored_active_count"] == 3
    assert result["top3"][0]["symbol"] == "005930"
    assert result["telegram_sent"] is True
    assert sent_results[0]["top3"][0]["current_price"] == 100
    assert not scheduler.LOCK_PATH.exists()


def test_cycle_records_published_picks_into_the_measurement_ledger(monkeypatch, tmp_path):
    """Every cycle must leave an evaluable record, even though picks get replaced."""
    _use_temp_paths(monkeypatch, tmp_path)
    ledger = scheduler.LEDGER_PATH
    monkeypatch.setattr(
        "app.services.mirofish.goodrich_client.monitor_fund_manager",
        lambda: {"active_count": 1},
    )
    monkeypatch.setattr(
        "app.services.mirofish.goodrich_client.run_research",
        lambda: {
            "integration": {"market_status": "open"},
            "cycle_id": "cycle-42",
            "picks": [
                {
                    "symbol": "005930", "name": "삼성전자", "rank": 1,
                    "current_price": 70000, "target_price": 77000, "stop_price": 65000,
                    "observed_at": "2026-07-30T10:30:00+09:00",
                },
            ],
        },
    )
    monkeypatch.setattr(scheduler, "_send_top3_telegram", lambda result: True)

    result = scheduler.run_cycle(force=True)

    assert result["ledger_recorded"] == 1
    from app.services.mirofish import goodrich_ledger

    entries = goodrich_ledger.read_ledger(ledger_path=str(ledger))
    assert len(entries) == 1
    assert entries[0]["symbol"] == "005930"
    assert entries[0]["entry_date"] == "2026-07-30"
    assert entries[0]["entry_price"] == 70000


def test_ledger_failure_never_breaks_the_cycle(monkeypatch, tmp_path):
    _use_temp_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "app.services.mirofish.goodrich_client.monitor_fund_manager",
        lambda: {"active_count": 0},
    )
    monkeypatch.setattr(
        "app.services.mirofish.goodrich_client.run_research",
        lambda: {
            "integration": {"market_status": "open"},
            "picks": [{
                "symbol": "005930", "name": "삼성전자", "current_price": 70000,
                "observed_at": "2026-07-30T10:30:00+09:00",
            }],
        },
    )
    monkeypatch.setattr(scheduler, "_send_top3_telegram", lambda result: True)

    def explode(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(
        "app.services.mirofish.goodrich_ledger.record_snapshot", explode,
    )

    result = scheduler.run_cycle(force=True)

    assert result["status"] == "completed"
    assert result["ledger_recorded"] == 0
    assert result["ledger_error"] == "OSError"


def test_cycle_skips_when_another_cycle_holds_the_lock(monkeypatch, tmp_path):
    _use_temp_paths(monkeypatch, tmp_path)
    scheduler.LOCK_PATH.write_text("active", encoding="utf-8")

    result = scheduler.run_cycle(force=True)

    assert result["status"] == "skipped"
    assert result["reason"] == "cycle_already_running"


def test_top3_message_escapes_names_and_formats_api_prices():
    message = scheduler._build_top3_telegram_message(
        {
            "completed_at": scheduler.datetime(2026, 7, 29, 1, 30, tzinfo=scheduler.UTC),
            "market_status": "open",
            "detected_candidates": 12,
            "qualified_candidates": 3,
            "top3": [
                {
                    "symbol": "005930",
                    "name": "삼성전자 <우>",
                    "current_price": 100000,
                    "target_price": 110000,
                    "stop_price": 95000,
                }
            ],
        }
    )

    assert "2026-07-29 10:30 KST" in message
    assert "삼성전자 &lt;우&gt;" in message
    assert "현재가 100,000원" in message
    assert "목표가 110,000원 | 손절가 95,000원" in message
    assert "12개 검출 → 3개 선정" in message


def test_telegram_failure_is_visible_in_status(monkeypatch, tmp_path):
    _use_temp_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "app.services.mirofish.goodrich_client.monitor_fund_manager",
        lambda: {"active_count": 0},
    )
    monkeypatch.setattr(
        "app.services.mirofish.goodrich_client.run_research",
        lambda: {"integration": {}, "picks": []},
    )
    monkeypatch.setattr(scheduler, "_send_top3_telegram", lambda result: False)

    result = scheduler.run_cycle(force=True)

    assert result["status"] == "completed_with_telegram_error"
    assert result["telegram_sent"] is False
    saved = json.loads(scheduler.STATUS_PATH.read_text(encoding="utf-8"))
    assert saved["telegram_error"] == "telegram_send_failed"

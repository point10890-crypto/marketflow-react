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


# ── 2026-09-04: "28개 검출 → 0개 선정 / 선정된 종목이 없습니다" 재발 방지 ─────────

def test_top3_message_never_goes_silent_when_nothing_is_selected():
    message = scheduler._build_top3_telegram_message(
        {
            "completed_at": scheduler.datetime(2026, 9, 4, 4, 30, tzinfo=scheduler.UTC),
            "market_status": "open",
            "detected_candidates": 28,
            "qualified_candidates": 0,
            "gates": {"scanned": 28, "positive_session": 11, "trend_gate_passed": 4,
                      "profit_gate_passed": 11, "cio_approved": 0},
            "stand_aside_reason": "에이전트 CIO 승인(BUY·신뢰도≥60) 통과 후보가 없음",
            "watchlist": [
                {"rank": 1, "symbol": "005930", "name": "삼성전자", "price": 71000,
                 "change_pct": 2.4, "score_total": 88, "risk_flags": ["drawdown"]},
                {"rank": 2, "symbol": "000660", "name": "SK하이닉스", "price": 250000,
                 "change_pct": -0.5, "score_total": 81, "risk_flags": ["negative_session"]},
            ],
            "top3": [],
        }
    )

    assert "선정된 종목이 없습니다" not in message
    assert "게이트: 스캔 28 → 등락>0 11 → 추세 4 → 신선도 11 → CIO승인 0" in message
    assert "CIO 승인(BUY·신뢰도≥60) 통과 후보가 없음" in message
    assert "관찰 후보 TOP 3" in message
    assert "삼성전자" in message and "71,000원" in message and "+2.4%" in message and "점수 88" in message
    assert "미달: negative_session" in message


def test_top3_message_flags_pipeline_fault_when_even_watchlist_is_empty():
    message = scheduler._build_top3_telegram_message(
        {"market_status": "open", "detected_candidates": 0, "qualified_candidates": 0,
         "gates": {"scanned": 0}, "watchlist": [], "top3": []}
    )
    assert "파이프라인 점검 필요" in message


def test_cycle_carries_watchlist_and_gates_into_status_and_message(monkeypatch, tmp_path):
    _use_temp_paths(monkeypatch, tmp_path)
    sent = []
    monkeypatch.setattr(
        "app.services.mirofish.goodrich_client.monitor_fund_manager", lambda: {"active_count": 0}
    )
    monkeypatch.setattr(
        "app.services.mirofish.goodrich_client.run_research",
        lambda: {
            "picks": [],
            "integration": {
                "market_status": "open", "candidate_count": 28, "universe_size": 0,
                "stand_aside_reason": "multi_mcp_cio_approved_below_minimum",
                "gates": {"scanned": 28, "positive_session": 9, "trend_gate_passed": 3,
                          "profit_gate_passed": 9, "cio_approved": 0},
                "watchlist": [{"rank": 1, "symbol": "005930", "name": "삼성전자", "price": 70000,
                               "change_pct": 1.0, "score_total": 90, "risk_flags": []}],
            },
        },
    )
    monkeypatch.setattr(scheduler, "_send_top3_telegram", lambda result: sent.append(result) or True)

    result = scheduler.run_cycle(force=True)

    assert result["status"] == "completed"
    assert result["top3"] == []
    assert result["watchlist"][0]["symbol"] == "005930"
    assert result["gates"]["cio_approved"] == 0
    assert "CIO 승인" in result["stand_aside_reason"]
    status = json.loads(scheduler.STATUS_PATH.read_text(encoding="utf-8"))
    assert status["watchlist"][0]["name"] == "삼성전자"
    message = scheduler._build_top3_telegram_message(sent[0])
    assert "관찰 후보 TOP 3" in message and "선정된 종목이 없습니다" not in message

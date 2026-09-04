"""Run one guarded Goodrich intraday monitoring and leader-detection cycle."""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env", override=False)

LOCK_PATH = ROOT / "data" / "admin_mirofish" / "goodrich_intraday.lock"
STATUS_PATH = ROOT / "data" / "admin_mirofish" / "goodrich_intraday_status.json"
LEDGER_PATH = ROOT / "data" / "admin_mirofish" / "goodrich_ledger.jsonl"
LOCK_STALE_SECONDS = 25 * 60


def _format_price(value: object) -> str:
    try:
        return f"{int(float(value)):,}원"
    except (TypeError, ValueError):
        return "확인 중"


def _build_top3_telegram_message(result: dict) -> str:
    completed_at = result.get("completed_at")
    if isinstance(completed_at, datetime):
        reference_time = completed_at.astimezone(ZoneInfo("Asia/Seoul"))
    else:
        reference_time = datetime.now(ZoneInfo("Asia/Seoul"))

    lines = [
        "🏆 <b>Goodrich AI TOP 3</b>",
        "<i>KIS 실데이터 · 30분 자동 분석</i>",
        "",
        f"기준: {reference_time:%Y-%m-%d %H:%M} KST",
        f"시장: {html.escape(str(result.get('market_status') or '확인 중'))}",
        (
            f"후보: {result.get('detected_candidates') or 0}개 검출 → "
            f"{result.get('qualified_candidates') or 0}개 선정"
        ),
    ]
    if result.get("selection_mode"):
        lines.append(
            f"분석: AI 검증 {int(result.get('ai_selected_count') or 0)}개 · "
            f"KIS 복구 {int(result.get('deterministic_fallback_count') or 0)}개"
        )
    if int(result.get("top3_shortfall") or 0) > 0:
        lines.append(
            f"⚠️ 검증 데이터 부족: TOP3 중 "
            f"{int(result.get('top3_shortfall') or 0)}개 미달"
        )
    lines.append("")
    top3 = list(result.get("top3") or [])[:3]
    if not top3:
        lines.append("선정된 종목이 없습니다.")
    for index, pick in enumerate(top3, start=1):
        name = html.escape(str(pick.get("name") or "종목명 확인 중"))
        symbol = html.escape(str(pick.get("symbol") or "-"))
        lines.extend(
            [
                f"{index}. <b>{name}</b> ({symbol})",
                f"   현재가 {_format_price(pick.get('current_price'))}",
                (
                    f"   목표가 {_format_price(pick.get('target_price'))} | "
                    f"손절가 {_format_price(pick.get('stop_price'))}"
                ),
            ]
        )
        selection_source = str(pick.get("selection_source") or "")
        if selection_source == "ai_verified":
            lines.append("   선정 근거: AI 검증")
        elif selection_source == "deterministic_kis_fallback":
            lines.append("   선정 근거: KIS 결정론 복구")
    lines.extend(["", "⚠️ 투자 판단 참고용 · 자동주문 없음"])
    return "\n".join(lines)


def _send_top3_telegram(result: dict) -> bool:
    from app.utils.scheduler import _send_telegram_long

    return _send_telegram_long(
        _build_top3_telegram_message(result),
        channel=False,
    )


def _record_ledger(research: dict, started_at: datetime) -> tuple[int, str | None]:
    """Persist this cycle's published picks so replacement cannot erase them.

    Measurement must never be able to break detection, so any failure here is
    reported in the cycle status instead of propagating.
    """
    try:
        from app.services.mirofish import goodrich_ledger

        picks = research.get("picks") or []
        if not picks:
            return 0, None
        cycle_id = str(
            research.get("cycle_id")
            or (picks[0] or {}).get("cycle_id")
            or f"cycle_{started_at:%Y%m%d_%H%M%S}"
        )
        detected_at = str(
            (picks[0] or {}).get("observed_at")
            or research.get("detected_at")
            or started_at.isoformat()
        )
        written = goodrich_ledger.record_snapshot(
            {
                "cycle_id": cycle_id,
                "detected_at": detected_at,
                "picks": picks,
            },
            ledger_path=str(LEDGER_PATH),
        )
        return written, None
    except Exception as error:  # measurement must not break the cycle
        return 0, type(error).__name__


def _write_status(payload: dict) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = STATUS_PATH.with_suffix(".tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    os.replace(temp_path, STATUS_PATH)


def _acquire_lock(now: datetime) -> bool:
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    if LOCK_PATH.exists():
        age = now.timestamp() - LOCK_PATH.stat().st_mtime
        if age < LOCK_STALE_SECONDS:
            return False
        LOCK_PATH.unlink(missing_ok=True)
    try:
        descriptor = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(f"{os.getpid()} {now.isoformat()}")
    return True


def run_cycle(*, force: bool = False) -> dict:
    from app.services.kis_screener import is_market_open
    from app.services.mirofish.goodrich_client import (
        monitor_fund_manager,
        run_research,
    )

    started_at = datetime.now(UTC)
    if not force and not is_market_open():
        result = {
            "status": "skipped",
            "reason": "market_closed",
            "started_at": started_at,
            "completed_at": datetime.now(UTC),
        }
        _write_status(result)
        return result

    if not _acquire_lock(started_at):
        return {
            "status": "skipped",
            "reason": "cycle_already_running",
            "started_at": started_at,
        }

    try:
        monitored = monitor_fund_manager()
        research = run_research()
        integration = research.get("integration", {})
        multi_mcp = (
            integration.get("multi_mcp")
            if isinstance(integration.get("multi_mcp"), dict)
            else research.get("multi_mcp")
            if isinstance(research.get("multi_mcp"), dict)
            else {}
        )
        selection_by_symbol = {
            str(row.get("symbol") or ""): str(row.get("selection_source") or "")
            for row in multi_mcp.get("selected") or []
            if isinstance(row, dict)
        }
        result = {
            "status": "completed",
            "started_at": started_at,
            "completed_at": datetime.now(UTC),
            "market_status": integration.get("market_status"),
            "detected_candidates": integration.get("candidate_count"),
            "qualified_candidates": integration.get("universe_size"),
            "selection_mode": multi_mcp.get("selection_mode"),
            "ai_selected_count": multi_mcp.get("ai_selected_count"),
            "deterministic_fallback_count": multi_mcp.get("deterministic_fallback_count"),
            "top3_shortfall": multi_mcp.get("top3_shortfall"),
            "monitored_active_count": monitored.get("active_count"),
            "top3": [
                {
                    "symbol": pick.get("symbol"),
                    "name": pick.get("name"),
                    "status": pick.get("status"),
                    "current_price": pick.get("current_price"),
                    "target_price": pick.get("target_price"),
                    "stop_price": pick.get("stop_price"),
                    "selection_source": (
                        pick.get("selection_source")
                        or selection_by_symbol.get(str(pick.get("symbol") or ""))
                    ),
                }
                for pick in research.get("picks", [])[:3]
            ],
        }
        recorded, ledger_error = _record_ledger(research, started_at)
        result["ledger_recorded"] = recorded
        if ledger_error:
            result["ledger_error"] = ledger_error
        result["telegram_sent"] = _send_top3_telegram(result)
        if not result["telegram_sent"]:
            result["status"] = "completed_with_telegram_error"
            result["telegram_error"] = "telegram_send_failed"
        _write_status(result)
        return result
    except Exception as error:
        result = {
            "status": "error",
            "started_at": started_at,
            "completed_at": datetime.now(UTC),
            "error_type": type(error).__name__,
            "error": str(error)[:300],
        }
        _write_status(result)
        raise
    finally:
        LOCK_PATH.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Run outside market hours for an operator smoke test.")
    args = parser.parse_args()
    result = run_cycle(force=args.force)
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 2 if result.get("telegram_sent") is False else 0


if __name__ == "__main__":
    raise SystemExit(main())

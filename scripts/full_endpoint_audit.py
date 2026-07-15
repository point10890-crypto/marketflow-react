"""Read-only authenticated smoke audit for the MiniPC MarketFlow API."""

from __future__ import annotations

import os
import sys
import time
import argparse
from pathlib import Path
from typing import Iterable

import requests


os.environ["MARKETFLOW_BACKGROUND_WORKERS"] = "false"
os.environ["WORKER_ALPHA_MONITOR_ENABLED"] = "0"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from flask_app import app  # noqa: E402
from app.auth.decorators import generate_token  # noqa: E402
from app.models.user import User  # noqa: E402


BASE_URL = os.getenv("MARKETFLOW_AUDIT_BASE_URL", "http://127.0.0.1:5001")


ENDPOINTS: list[tuple[str, str]] = [
    ("health", "/healthz"),
    ("api_health", "/api/health"),
    ("data_version", "/api/data-version"),
    ("last_update", "/api/system/last-update"),
    ("kr_gate", "/api/kr/market-gate"),
    ("kr_signals", "/api/kr/signals"),
    ("kr_jongga", "/api/kr/jongga-v2/latest"),
    ("kr_jongga_summary", "/api/kr/jongga-v2/today-summary"),
    ("kr_jongga_perf", "/api/kr/jongga-v2/performance"),
    ("kr_vcp", "/api/kr/vcp-enhanced"),
    ("kr_vcp_dates", "/api/kr/vcp-enhanced/dates"),
    ("kr_leading", "/api/kr/screener/leading"),
    ("kr_ai_theme", "/api/kr/screener/leading/ai-theme"),
    ("kr_ai_chart", "/api/kr/ai-chart-analysis"),
    ("brief_latest", "/api/briefing/latest"),
    ("brief_morning", "/api/briefing/morning"),
    ("brief_closing", "/api/briefing/closing"),
    ("brief_dates", "/api/briefing/dates"),
    ("us_gate", "/api/us/market-gate"),
    ("us_brief", "/api/us/market-briefing"),
    ("us_portfolio", "/api/us/portfolio"),
    ("us_decision", "/api/us/decision-signal"),
    ("us_vcp", "/api/us/vcp-enhanced"),
    ("us_vcp_dates", "/api/us/vcp-enhanced/dates"),
    ("us_top", "/api/us/top-picks-report"),
    ("us_regime", "/api/us/market-regime"),
    ("crypto_overview", "/api/crypto/overview"),
    ("crypto_brief", "/api/crypto/briefing"),
    ("crypto_vcp", "/api/crypto/vcp-enhanced"),
    ("crypto_signals", "/api/crypto/vcp-signals?limit=10"),
    ("crypto_risk", "/api/crypto/risk"),
    ("crypto_prediction", "/api/crypto/prediction"),
    ("crypto_status", "/api/crypto/data-status"),
    ("wave_dashboard", "/api/wave/dashboard"),
    ("wave_latest", "/api/wave/screener/latest"),
    ("wave_types", "/api/wave/pattern-types"),
    ("wave_signals", "/api/wave/signals"),
    ("wave_stats", "/api/wave/stats"),
    ("wave_jubjub", "/api/wave/jubjub?min_score=60&limit=10"),
    ("community_summary", "/api/community/summary"),
    ("community_boards", "/api/community/boards"),
    ("community_search", "/api/community/search?q=%EC%A3%BC%EC%8B%9D&page=1"),
    ("community_purchases", "/api/community/purchases/summary"),
    ("stock_search", "/api/stock-analyzer/search?q=%EC%82%BC%EC%84%B1%EC%A0%84%EC%9E%90"),
    ("manual_runs", "/api/manual-stock-analysis/runs"),
    ("aibain_overview", "/api/admin/mirofish/aibain/overview"),
    ("mirofish_status", "/api/admin/mirofish/status"),
    ("mirofish_sources", "/api/admin/mirofish/data-sources"),
    ("mirofish_pipeline", "/api/admin/mirofish/pipeline/today"),
    ("mirofish_workflow", "/api/admin/mirofish/workflow/status"),
    ("mirofish_scanner", "/api/admin/mirofish/scanner/status"),
    ("mirofish_monitor", "/api/admin/mirofish/scanner/monitor/status"),
    ("mirofish_learning", "/api/admin/mirofish/learning/readiness"),
    ("mirofish_autonomous", "/api/admin/mirofish/autonomous/status"),
    ("mirofish_runner", "/api/admin/mirofish/auto-runner/status"),
    ("mirofish_deepseek", "/api/admin/mirofish/deepseek/status"),
    ("mirofish_graphrag", "/api/admin/mirofish/graphrag/status"),
    ("mirofish_tradingview", "/api/admin/mirofish/tradingview/status"),
]


def _token() -> str:
    with app.app_context():
        admin = User.query.filter_by(role="admin").first()
        if admin is None:
            raise RuntimeError("No admin account is available for the audit")
        return generate_token(admin.id)


def _describe(response: requests.Response) -> str:
    content_type = response.headers.get("content-type", "")
    if "json" not in content_type:
        return f"content_type={content_type}"
    try:
        payload = response.json()
    except ValueError:
        return "invalid_json"
    if isinstance(payload, dict):
        return "keys=" + ",".join(list(payload)[:12])
    if isinstance(payload, list):
        return f"list={len(payload)}"
    return f"json_type={type(payload).__name__}"


def _audit_endpoints(headers: dict[str, str], endpoints: Iterable[tuple[str, str]]) -> None:
    for name, path in endpoints:
        try:
            started = time.perf_counter()
            response = requests.get(BASE_URL + path, headers=headers, timeout=12)
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            print(
                f"RESULT|{name}|{response.status_code}|ms={elapsed_ms}|bytes={len(response.content)}|"
                f"{_describe(response)}",
                flush=True,
            )
        except Exception as exc:
            print(f"RESULT|{name}|EXC|{type(exc).__name__}:{str(exc)[:120]}", flush=True)


def _audit_boards(headers: dict[str, str]) -> None:
    response = requests.get(BASE_URL + "/api/community/boards", headers=headers, timeout=15)
    payload = response.json()
    boards = payload.get("boards", []) if isinstance(payload, dict) else payload
    for board in boards or []:
        slug = board.get("slug")
        if not slug:
            continue
        result = requests.get(
            BASE_URL + f"/api/community/boards/{slug}/posts?page=1&per_page=3",
            headers=headers,
            timeout=20,
        )
        try:
            data = result.json()
            count = len(data.get("posts", [])) if isinstance(data, dict) else len(data)
        except (ValueError, TypeError):
            count = "?"
        print(
            f"BOARD|{slug}|{result.status_code}|posts={count}|bytes={len(result.content)}",
            flush=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", default="all")
    args = parser.parse_args()
    headers = {"Authorization": "Bearer " + _token()}
    prefixes = {
        "health": ("health", "api_health", "data_version", "last_update"),
        "kr": ("kr_",),
        "briefing": ("brief_",),
        "us": ("us_",),
        "crypto": ("crypto_",),
        "wave": ("wave_",),
        "community": ("community_",),
        "stock": ("stock_", "manual_"),
        "mirofish": ("aibain_", "mirofish_"),
    }
    selected = ENDPOINTS
    if args.group != "all":
        wanted = prefixes.get(args.group)
        if wanted is None:
            raise SystemExit(f"Unknown group: {args.group}")
        selected = [(name, path) for name, path in ENDPOINTS if name.startswith(wanted)]
    _audit_endpoints(headers, selected)
    if args.group in {"all", "community"}:
        _audit_boards(headers)


if __name__ == "__main__":
    main()

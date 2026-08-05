"""Manual stock-analysis result service.

This module turns the legacy ``stock_info.py`` Excel workflow into a small,
explicit service surface.  It intentionally stores manual runs outside the
MiroFish alpha scanner artifacts so imported/scraped analyst labels do not
silently affect automated Top3 ranking.
"""

from __future__ import annotations

import csv
import hashlib
import logging
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from app.utils.atomic_json import write_json_atomic
from app.utils.paths import DATA_DIR, TICKER_MAP_PATH
from app.utils.safety import safe_int


SERVICE_ROOT = Path(DATA_DIR) / "manual_stock_analysis"
RUNS_DIR = SERVICE_ROOT / "runs"
UPLOADS_DIR = SERVICE_ROOT / "uploads"
STOCK_ANALYZER_CACHE_DIR = Path(DATA_DIR) / "stock_analyzer_cache"
MAX_SOURCE_ROWS = 5000


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default))))
    except Exception:
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


DEFAULT_SCRAPE_DELAY_SEC = _env_float("MANUAL_STOCK_ANALYSIS_DELAY_SEC", 1.2)
AUTO_LOOP_ENABLED = _env_bool("MANUAL_STOCK_ANALYSIS_AUTO_LOOP", True)
AUTO_IMPORT_KNOWN_RESULTS = _env_bool("MANUAL_STOCK_ANALYSIS_AUTO_IMPORT", True)
AUTO_LOOP_MAX_ROWS = max(0, min(_env_int("MANUAL_STOCK_ANALYSIS_LOOP_MAX_ROWS", 0), MAX_SOURCE_ROWS))
# Cooldown between full cycles. Default 600s (was 0 = immediate re-loop) so a single
# residential IP is not hammering the Cloudflare-protected target 24/7. env-overridable.
AUTO_LOOP_INTERVAL_SEC = max(0, min(_env_int("MANUAL_STOCK_ANALYSIS_LOOP_INTERVAL_SEC", 600), 86400))
# Random extra seconds (0..N) added to each cycle wait so the cadence is not perfectly periodic.
AUTO_LOOP_JITTER_SEC = max(0, min(_env_int("MANUAL_STOCK_ANALYSIS_LOOP_JITTER_SEC", 300), 3600))
AUTO_LOOP_TIMEOUT_SEC = max(3, min(_env_int("MANUAL_STOCK_ANALYSIS_LOOP_TIMEOUT_SEC", 10), 30))
AUTO_LOOP_ERROR_BACKOFF_SEC = max(5, min(_env_int("MANUAL_STOCK_ANALYSIS_LOOP_ERROR_BACKOFF_SEC", 30), 3600))

# --- Deliberate per-process loop start (2026-07-25) ---
# AUTO_LOOP_ENABLED only governs the *request-triggered* start. Production keeps it
# off so a status GET can never launch thousands of Selenium scrapes -- but that left
# the loop with no trigger at all, freezing the dashboard at the last run for 10 days.
# This flag is the replacement trigger: one deliberate start per Flask process.
_log = logging.getLogger(__name__)

# 스크래퍼가 띄우는 Chrome 의 --user-data-dir 접두어. 강제 종료로 남은
# 고아 브라우저를 이 표식으로만 골라 죽인다 (사용자의 실제 Chrome 제외).
SCRAPE_PROFILE_PREFIX = "marketflow_manual_scrape_"

LOOP_BOOT_AUTOSTART = _env_bool("MANUAL_STOCK_ANALYSIS_LOOP_AUTOSTART", False)
# Delay before the boot start so app startup (port bind, blueprint warmup) finishes first.
LOOP_BOOT_DELAY_SEC = max(0, min(_env_int("MANUAL_STOCK_ANALYSIS_LOOP_AUTOSTART_DELAY_SEC", 45), 3600))

# --- Cloudflare block resilience (2026-07-08) ---
# Consecutive block responses that trip the circuit breaker and abort the current
# cycle (0 disables). Prevents the loop from hammering an already-blocked IP for a
# whole 2,300-row cycle, which sustains the block and stops reputation recovery.
BLOCK_CIRCUIT_THRESHOLD = max(0, min(_env_int("MANUAL_STOCK_ANALYSIS_BLOCK_CIRCUIT", 5), 500))
# Long cool-off applied after the circuit opens, letting the IP reputation recover.
# 2026-07-26 measurement: retrying 21-23min after a block failed 3 times out of 3
# (every request blocked, cycle dead again in ~2.6min) while 44-49min succeeded 3
# out of 3. The old 1200s default produced 20-25min with jitter -- squarely in the
# failing band, so every cool-off was wasted and recovery only happened when a
# second backoff happened to land near 45min. 2700s gives 45-56min.
BLOCK_BACKOFF_SEC = max(60, min(_env_int("MANUAL_STOCK_ANALYSIS_BLOCK_BACKOFF_SEC", 2700), 7200))
# Per-row retry attempts on retryable (block/timeout) errors, with exponential backoff.
RETRY_MAX = max(0, min(_env_int("MANUAL_STOCK_ANALYSIS_RETRY_MAX", 2), 5))
# Investing.com serves one page per browser session and 403s the rest, so reusing a
# driver made every row fail once and pay a backoff + relaunch (17s/row vs 5s).
# Recycle up front instead. 0 disables recycling; raise it if the site relaxes.
PAGES_PER_SESSION = max(0, min(_env_int("MANUAL_STOCK_ANALYSIS_PAGES_PER_SESSION", 1), 500))
RETRY_BASE_SEC = max(0.5, min(_env_float("MANUAL_STOCK_ANALYSIS_RETRY_BASE_SEC", 5.0), 60.0))
# On a collection gap, carry the most recent successful verdict forward (marked stale)
# instead of overwriting a blue-chip's real verdict with "오류".
CARRY_LAST_GOOD = _env_bool("MANUAL_STOCK_ANALYSIS_CARRY_LAST_GOOD", True)

# --- Resume after a block cool-off (2026-07-26) ---
# Investing.com cuts us off after roughly 1,400 successful page loads, so the
# circuit breaker above trips around 60% of the 2,341-row universe (production:
# 1,445 and 1,409 rows). The loop used to cool off and then start a *new* run from
# rank 1, which at ~9s/row can never clear the same ceiling: the first ~1,400
# stocks were re-scraped forever and the last ~900 never refreshed at all.
# Resuming the same run instead lets one cycle walk the whole universe across
# several block windows. Set to 0/false to restore the old start-from-scratch.
RESUME_AFTER_BLOCK = _env_bool("MANUAL_STOCK_ANALYSIS_RESUME_AFTER_BLOCK", True)
# How stale a half-finished run may be before the loop treats it as history rather
# than work to pick up. Covers a cycle (~6.6h) plus a cool-off with margin.
RESUME_ADOPT_MAX_AGE_HOURS = max(1, min(_env_int("MANUAL_STOCK_ANALYSIS_RESUME_MAX_AGE_HOURS", 12), 168))
# Rows in these states are finished for this cycle and are never re-scraped on
# resume. "scraping" is deliberately absent: that is the row the circuit died on.
_TERMINAL_SCRAPE_STATES = {"completed", "error"}

_SUCCESS_LABELS = {"적극 매수", "매수", "중립", "매도", "적극 매도"}


class ScraperCircuitOpen(RuntimeError):
    """Raised when consecutive Cloudflare blocks trip the circuit breaker mid-cycle."""


def _is_block_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(
        marker in text
        for marker in ("target page blocked", "cloudflare", "captcha", "verify you are human", "just a moment")
    )


def _jittered(base: float, jitter: float) -> float:
    if jitter <= 0:
        return max(0.0, float(base))
    return max(0.0, float(base) + random.uniform(0, float(jitter)))

DEFAULT_SOURCE_PATHS = [
    Path(os.getenv("MANUAL_STOCK_ANALYSIS_SOURCE_FILE", "")),
    Path("E:/다운로드/stock_data_final.xlsx"),
    SERVICE_ROOT / "stock_data_final.xlsx",
    Path("E:/다운로드/stock_data.xlsx"),
    SERVICE_ROOT / "stock_data.xlsx",
]
DEFAULT_RESULT_PATHS = [
    SERVICE_ROOT / "results",
    Path("E:/다운로드"),
]

RESULT_ORDER = ["적극 매수", "매수", "중립", "매도", "적극 매도", "분석중", "오류", "미분류"]
STRONG_BUY_LABEL = "적극 매수"
# A virtual filter, not a verdict: stocks that held a different opinion in the last
# cycle that had one, and are 적극 매수 now. Kept out of RESULT_ORDER so summaries
# and the distribution bar keep counting real verdicts only.
UPGRADE_FILTER = "적극매수 전환"
# Measured on production (2026-07-26 6회차, 1,409 overlapping stocks): 0 verdict
# changes against the same day's earlier cycle, 1 against the previous day, ~43
# against two weeks back. Verdicts simply do not move within a day, so comparing
# against the previous *cycle* would report zero forever -- the baseline is the
# newest run from an earlier date. Scanning stops once a full day's worth is in
# hand, since one complete run covers the whole universe.
_PRIOR_VERDICT_SCAN_DEPTH = 6
_PRIOR_VERDICT_ENOUGH = 1000
DEFAULT_INVESTING_XPATH = "//*[@id='pro-score-mobile']/div/div[2]/div[3]/div/div/div[1]/div"

_LOOP_LOCK = threading.RLock()
_LOOP_STOP = threading.Event()
_LOOP_THREAD: threading.Thread | None = None
_LOOP_STATE: dict[str, Any] = {
    "running": False,
    "state": "stopped",
    "mode": "auto",
    "auto_start": AUTO_LOOP_ENABLED,
    "max_rows": 0,
    "interval_sec": 60,
    "timeout_sec": 10,
    "source_path": "",
    "source_record_count": 0,
    "cycle": 0,
    "iterations": 0,
    "processed": 0,
    "total": 0,
    "current_rank": None,
    "current_stock": "",
    "current_industry": "",
    "current_result": "",
    "last_run_id": "",
    "last_record_count": 0,
    "last_started_at": "",
    "last_finished_at": "",
    "next_run_at": "",
    "current_cycle_label": "",
    "cycle_started_at": "",
    "last_error": "",
}


def ensure_storage() -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _clean_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z가-힣_.-]+", "_", name).strip("._")
    return cleaned or "manual_stock_analysis.xlsx"


def _file_fingerprint(path: Path) -> str:
    stat = path.stat()
    raw = f"{path.resolve()}:{stat.st_size}:{int(stat.st_mtime)}".encode("utf-8", "ignore")
    return hashlib.sha1(raw).hexdigest()[:16]


def _normalise_label(raw: str) -> str:
    text = _clean_text(raw).replace(" ", "")
    if not text:
        return "미분류"
    if "오류" in text:
        return "오류"
    if "대기" in text or "분석중" in text:
        return "분석중"
    if "적극매수" in text or text.upper() in {"STRONGBUY", "STRONG_BUY"}:
        return "적극 매수"
    if "적극매도" in text or text.upper() in {"STRONGSELL", "STRONG_SELL"}:
        return "적극 매도"
    if "매수" in text or text.upper() == "BUY":
        return "매수"
    if "매도" in text or text.upper() == "SELL":
        return "매도"
    if "중립" in text or text.upper() in {"HOLD", "NEUTRAL"}:
        return "중립"
    return _clean_text(raw) or "미분류"


_RECOMMENDATION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"적극\s*매수|STRONG\s*_?\s*BUY", re.IGNORECASE), "적극 매수"),
    (re.compile(r"적극\s*매도|STRONG\s*_?\s*SELL", re.IGNORECASE), "적극 매도"),
    (re.compile(r"\bBUY\b|매수", re.IGNORECASE), "매수"),
    (re.compile(r"\bSELL\b|매도", re.IGNORECASE), "매도"),
    (re.compile(r"\bHOLD\b|\bNEUTRAL\b|중립", re.IGNORECASE), "중립"),
]

_RECOMMENDATION_ANCHORS = (
    "pro score",
    "pro-score",
    "technical",
    "technical analysis",
    "summary",
    "recommendation",
    "signal",
    "consensus",
    "analysis",
    "기술적",
    "요약",
    "분석",
    "추천",
    "판정",
    "기술적 분석",
    "기술 분석",
    "애널리스트 센티멘트",
    "애널리스트 센티먼트",
)

_INVESTING_SIGNAL_LABELS = {"적극 매수", "매수", "중립", "매도", "적극 매도"}

_INVESTING_READY_MARKERS = (
    "애널리스트 센티멘트",
    "애널리스트 센티먼트",
    "Analyst Sentiment",
    "목표 주가",
    "Target Price",
    "기술적 분석",
    "Technical Analysis",
)

_INVESTING_VALUE_LABELS = {
    "산업",
    "업종",
    "부문",
    "직원",
    "시장",
    "industry",
    "sector",
    "employees",
    "market",
}

_COUNTRY_ONLY_VALUES = {
    "한국",
    "대한민국",
    "미국",
    "중국",
    "일본",
    "korea",
    "south korea",
    "usa",
    "united states",
    "china",
    "japan",
}


def _is_country_value(value: Any) -> bool:
    return _clean_text(value).strip().lower() in _COUNTRY_ONLY_VALUES


def _extract_recommendation_from_text(text: str) -> str:
    raw_text = _clean_text(text)
    visible_text = re.sub(r"\s+", " ", raw_text)
    if not visible_text:
        return ""

    lower = visible_text.lower()
    windows: list[str] = []
    for anchor in _RECOMMENDATION_ANCHORS:
        start = lower.find(anchor.lower())
        if start >= 0:
            windows.append(visible_text[max(0, start - 160): start + 420])

    for window in windows:
        for pattern, label in _RECOMMENDATION_PATTERNS:
            if pattern.search(window):
                return label
    for line in re.split(r"[\n\r\t|•]+", raw_text):
        candidate = _clean_text(line)
        if not candidate or len(candidate) > 80:
            continue
        compact = re.sub(r"\s+", " ", candidate).strip()
        if re.search(r"^(적극\s*매수|적극\s*매도|매수|매도|중립|STRONG\s+BUY|STRONG\s+SELL|BUY|SELL|HOLD|NEUTRAL)$", compact, re.IGNORECASE):
            return _normalise_label(compact)
    return ""


def _visible_lines(text: str) -> list[str]:
    return [
        _clean_text(line)
        for line in re.split(r"[\n\r\t]+", _clean_text(text))
        if _clean_text(line)
    ]


def _strip_anchor_value(line: str, anchor: str) -> str:
    if anchor not in line:
        return ""
    return line.split(anchor, 1)[1].strip(" :：›>.-")


def _extract_signal_after_anchor(lines: list[str], anchors: tuple[str, ...], *, scan_ahead: int = 10) -> str:
    for index, line in enumerate(lines):
        if not any(anchor in line for anchor in anchors):
            continue
        candidates = []
        for anchor in anchors:
            after = _strip_anchor_value(line, anchor)
            if after:
                candidates.append(after)
        candidates.extend(lines[index + 1: index + 1 + scan_ahead])
        for candidate in candidates:
            if "잠금" in candidate or "확인" in candidate:
                continue
            label = _normalise_label(candidate)
            if label in _INVESTING_SIGNAL_LABELS:
                return label
    return ""


def _extract_text_after_anchor(
    lines: list[str],
    anchors: tuple[str, ...],
    *,
    scan_ahead: int = 4,
    allow_numeric: bool = True,
) -> str:
    for index, line in enumerate(lines):
        if not any(anchor in line for anchor in anchors):
            continue
        candidates = []
        for anchor in anchors:
            after = _strip_anchor_value(line, anchor)
            if after:
                candidates.append(after)
        candidates.extend(lines[index + 1: index + 1 + scan_ahead])
        for candidate in candidates:
            value = _clean_text(candidate)
            if not value or "잠금" in value or "확인" in value:
                continue
            if value.strip().lower() in _INVESTING_VALUE_LABELS:
                continue
            if not allow_numeric and re.fullmatch(r"[-+.,%0-9]+", value):
                continue
            return value[:80]
    return ""


def _extract_numeric_after_anchor(lines: list[str], anchors: tuple[str, ...], *, scan_ahead: int = 5) -> str:
    for index, line in enumerate(lines):
        if not any(anchor in line for anchor in anchors):
            continue
        candidates = []
        for anchor in anchors:
            after = _strip_anchor_value(line, anchor)
            if after:
                candidates.append(after)
        candidates.extend(lines[index + 1: index + 1 + scan_ahead])
        for candidate in candidates:
            value = _clean_text(candidate)
            if re.search(r"[-+]?\d[\d,.]*(?:\.\d+)?%?", value):
                return value[:80]
    return ""


def _extract_text_after_exact_label(
    lines: list[str],
    labels: tuple[str, ...],
    *,
    scan_ahead: int = 4,
    allow_numeric: bool = True,
    reverse: bool = False,
) -> str:
    label_set = {label.lower() for label in labels}
    indexed_lines = list(enumerate(lines))
    if reverse:
        indexed_lines.reverse()
    for index, line in indexed_lines:
        if line.strip().lower() not in label_set:
            continue
        for candidate in lines[index + 1: index + 1 + scan_ahead]:
            value = _clean_text(candidate)
            if not value or "잠금" in value or "확인" in value:
                continue
            if value.strip().lower() in _INVESTING_VALUE_LABELS:
                continue
            if not allow_numeric and re.fullmatch(r"[-+.,%0-9]+", value):
                continue
            return value[:80]
    return ""


def _extract_numeric_after_exact_label(lines: list[str], labels: tuple[str, ...], *, scan_ahead: int = 5) -> str:
    label_set = {label.lower() for label in labels}
    for index, line in enumerate(lines):
        if line.strip().lower() not in label_set:
            continue
        for candidate in lines[index + 1: index + 1 + scan_ahead]:
            value = _clean_text(candidate)
            if re.fullmatch(r"[-+]?\d[\d,.]*(?:\.\d+)?%?", value):
                return value[:80]
    return ""


def _extract_profile_market_country(lines: list[str]) -> str:
    for index, line in enumerate(lines):
        if line.strip().lower() not in {"시장", "market"}:
            continue
        previous = {item.strip().lower() for item in lines[max(0, index - 8):index]}
        if not ({"직원", "employees"} & previous):
            continue
        for candidate in lines[index + 1:index + 5]:
            value = _clean_text(candidate)
            if value and _is_country_value(value) and not re.fullmatch(r"[-+.,%0-9]+", value):
                return value[:80]
    return ""


def _extract_investing_snapshot_fields(text: str) -> dict[str, str]:
    lines = _visible_lines(text)
    if not lines:
        return {}

    technical_result = _extract_signal_after_anchor(lines, ("기술적 분석", "기술 분석", "Technical Analysis"))
    analyst_sentiment = _extract_signal_after_anchor(
        lines,
        ("애널리스트 센티멘트", "애널리스트 센티먼트", "Analyst Sentiment"),
    )
    industry = (
        _extract_text_after_exact_label(lines, ("산업", "Industry"), allow_numeric=False, reverse=True)
        or _extract_text_after_anchor(lines, ("산업", "Industry"), allow_numeric=False)
    )
    sector = _extract_text_after_exact_label(lines, ("부문", "Sector"), allow_numeric=False, reverse=True)
    employees = _extract_text_after_exact_label(lines, ("직원", "Employees"), reverse=True)
    market_country = (
        _extract_profile_market_country(lines)
        or _extract_text_after_exact_label(lines, ("시장", "Market"), allow_numeric=False, reverse=True)
    )
    if market_country and not _is_country_value(market_country):
        market_country = ""
    target_price = _extract_text_after_exact_label(lines, ("목표 주가", "Target Price"))
    upside_potential = _extract_numeric_after_exact_label(lines, ("상승 여력 있음", "Upside"))

    result = analyst_sentiment or technical_result
    return {
        key: value
        for key, value in {
            "result": result,
            "technical_result": technical_result,
            "analyst_sentiment": analyst_sentiment,
            "industry": industry,
            "sector": sector,
            "employees": employees,
            "market_country": market_country,
            "target_price": target_price,
            "upside_potential": upside_potential,
        }.items()
        if value
    }


""" Bodies that are nothing but an HTTP status code — Investing.com's rate-limit
response. Matched exactly, so a status code inside real content is not a block. """
_STATUS_ONLY_BLOCK_CODES = {"403", "429", "502", "503", "504"}


def _blocked_page_reason(text: str) -> str:
    visible_text = _clean_text(text).lower()
    if not visible_text:
        return ""
    # Investing.com throttles with a body that is *only* the status code ("403").
    # Missing it made the row look like an empty verdict: retryable, so the loop
    # kept hammering a blocked IP and the circuit breaker never opened, which is
    # how full cycles fell from 100% to 0.2% on 2026-07-15.
    if re.sub(r"\s+", "", visible_text) in _STATUS_ONLY_BLOCK_CODES:
        return f"http {re.sub(r'[^0-9]', '', visible_text)}"
    blocked_markers = (
        "access denied",
        "403 forbidden",
        "too many requests",
        "rate limit",
        "verify you are human",
        "are you a robot",
        "just a moment",
        "checking your browser",
        "cloudflare",
        "unusual traffic",
        "captcha",
    )
    return next((marker for marker in blocked_markers if marker in visible_text), "")


def _read_body_text(driver: Any) -> str:
    try:
        return driver.execute_script("return document.body ? document.body.innerText : '';") or ""
    except Exception:
        return ""


def _wait_for_investing_text(driver: Any, timeout_sec: int) -> str:
    """Wait until Investing's dynamic body contains an actionable verdict.

    The body element appears much earlier than the Pro/technical panels.  Reading
    it immediately often captures only menus and leaves rows stuck as "분석중".
    This loop waits for either a parsed signal, a block page, or the best text we
    can collect before timeout.
    """
    deadline = time.time() + max(2.0, float(timeout_sec or 8))
    best_text = ""
    while time.time() < deadline:
        text = _read_body_text(driver)
        if len(text) > len(best_text):
            best_text = text
        if _blocked_page_reason(text):
            return text
        snapshot = _extract_investing_snapshot_fields(text)
        if snapshot.get("result") or _extract_recommendation_from_text(text):
            return text
        if any(marker in text for marker in _INVESTING_READY_MARKERS) and len(text) > 2500:
            # Give the analyst/technical cards one more short paint cycle before
            # accepting that the visible page has no usable signal yet.
            time.sleep(0.35)
            text = _read_body_text(driver)
            if len(text) > len(best_text):
                best_text = text
            snapshot = _extract_investing_snapshot_fields(text)
            if snapshot.get("result") or _extract_recommendation_from_text(text):
                return text
        time.sleep(0.25)
    return best_text


def _is_retryable_scrape_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    retry_markers = (
        "target page blocked",
        "cloudflare",
        "captcha",
        "empty investing verdict",
        "timeout",
        "page load failed",
    )
    return any(marker in text for marker in retry_markers)


def _ticker_lookup() -> dict[str, dict[str, str]]:
    """Load the small name-to-ticker map without constructing pandas Series.

    Status polling can overlap the scraper's Excel work in another thread.
    Keeping the static CSV lookup on Python's thread-safe parser avoids a native
    pandas access violation observed when both paths were active in tests.
    """
    lookup: dict[str, dict[str, str]] = {}
    try:
        with Path(TICKER_MAP_PATH).open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                name = _clean_text(row.get("name"))
                ticker = _clean_text(row.get("ticker")).zfill(6)
                market = _clean_text(row.get("market"))
                if name:
                    lookup[name] = {"ticker": ticker, "market": market}
    except (OSError, UnicodeError, csv.Error):
        return {}
    return lookup


def _split_stock_name(raw_name: str, lookup: dict[str, dict[str, str]]) -> tuple[str, str, str]:
    name = _clean_text(raw_name)
    match = re.search(r"\((\d{6})\)", name)
    if match:
        ticker = match.group(1)
        clean_name = re.sub(r"\s*\(\d{6}\)\s*$", "", name).strip() or name
        meta = lookup.get(clean_name, {})
        return clean_name, ticker, meta.get("market", "")

    meta = lookup.get(name, {})
    return name, meta.get("ticker", ""), meta.get("market", "")


def _coalesce(row: pd.Series, names: list[str], default: str = "") -> str:
    for name in names:
        if name in row and _clean_text(row[name]):
            return _clean_text(row[name])
    return default


def _is_missing_industry(value: Any) -> bool:
    text = _clean_text(value)
    lowered = text.strip().lower()
    return (
        not text
        or text in {"미분류", "-", "N/A", "na", "None"}
        or lowered in _INVESTING_VALUE_LABELS
        or _is_country_value(text)
    )


def _cached_industry_for(ticker: str, market: str = "") -> str:
    code = _clean_text(ticker).replace(".KS", "").replace(".KQ", "").zfill(6)
    if not code or code == "000000":
        return ""
    suffixes = []
    market_text = _clean_text(market).upper()
    if market_text == "KOSPI":
        suffixes.append("KS")
    elif market_text == "KOSDAQ":
        suffixes.append("KQ")
    suffixes.extend(["KS", "KQ", ""])
    seen: set[str] = set()
    for suffix in suffixes:
        cache_name = f"{code}_{suffix}.json" if suffix else f"{code}.json"
        if cache_name in seen:
            continue
        seen.add(cache_name)
        path = STOCK_ANALYZER_CACHE_DIR / cache_name
        if not path.is_file():
            continue
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        key_stats = data.get("key_stats") if isinstance(data.get("key_stats"), dict) else {}
        for candidate in (
            data.get("industry"),
            key_stats.get("industry"),
            data.get("sector"),
            key_stats.get("sector"),
        ):
            if not _is_missing_industry(candidate):
                return _clean_text(candidate)
    return ""


def _resolve_industry(row: pd.Series, ticker: str, market: str) -> str:
    direct = _coalesce(row, ["산업", "업종", "industry", "sector"], "")
    if not _is_missing_industry(direct):
        return direct
    return _cached_industry_for(ticker, market) or "미분류"


def _read_excel_records(path: Path, *, pending: bool = False) -> list[dict[str, Any]]:
    df = pd.read_excel(path)
    lookup = _ticker_lookup()
    records: list[dict[str, Any]] = []
    for idx, row in df.iterrows():
        raw_name = _coalesce(row, ["종목", "종목명", "name", "stock"], f"row-{idx + 1}")
        stock_name, ticker, market = _split_stock_name(raw_name, lookup)
        industry = _resolve_industry(row, ticker, market)
        raw_result = "분석중" if pending else _coalesce(row, ["분석 결과", "분석결과", "result", "recommendation"], "미분류")
        analyzed_at = _coalesce(row, ["분석일시", "오늘 날짜", "date", "created_at"], "")
        records.append({
            "rank": int(float(_coalesce(row, ["순번", "rank", "no"], str(idx + 1)) or idx + 1)),
            "stock_name": stock_name,
            "ticker": ticker,
            "market": market,
            "industry": industry,
            "source_url": _coalesce(row, ["url", "URL", "source_url"], ""),
            "raw_result": raw_result,
            "result": _normalise_label(raw_result),
            "analyzed_at": analyzed_at or _now(),
        })
    return records


def _summary(records: list[dict[str, Any]]) -> dict[str, int]:
    summary = {key: 0 for key in RESULT_ORDER}
    for record in records:
        label = record.get("result") or "미분류"
        summary[label] = summary.get(label, 0) + 1
    return {key: value for key, value in summary.items() if value}


def _run_path(run_id: str) -> Path:
    clean_run_id = _clean_text(run_id)
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", clean_run_id):
        raise ValueError("invalid run_id")
    path = (RUNS_DIR / f"{clean_run_id}.json").resolve()
    root = RUNS_DIR.resolve()
    if path.parent != root:
        raise ValueError("invalid run_id")
    return path


def _write_run(run: dict[str, Any]) -> dict[str, Any]:
    ensure_storage()
    write_json_atomic(str(_run_path(run["run_id"])), run, sort_keys=True)
    return run


def _loop_set(**updates: Any) -> dict[str, Any]:
    with _LOOP_LOCK:
        _LOOP_STATE.update(updates)
        return dict(_LOOP_STATE)


def _loop_snapshot() -> dict[str, Any]:
    with _LOOP_LOCK:
        thread_alive = _LOOP_THREAD is not None and _LOOP_THREAD.is_alive()
        _LOOP_STATE["running"] = bool(thread_alive and not _LOOP_STOP.is_set())
        if not _LOOP_STATE["running"] and _LOOP_STATE.get("state") not in {"stopped", "error"}:
            _LOOP_STATE["state"] = "stopped"
        return dict(_LOOP_STATE)


def _active_loop_run_id() -> str:
    snapshot = _loop_snapshot()
    if snapshot.get("running"):
        return _clean_text(snapshot.get("last_run_id"))
    return ""


def _public_run_status(run: dict[str, Any], active_loop_run_id: str | None = None) -> str:
    status = _clean_text(run.get("status")) or "completed"
    if status != "running":
        return status
    run_id = _clean_text(run.get("run_id"))
    active_run_id = active_loop_run_id if active_loop_run_id is not None else _active_loop_run_id()
    if active_run_id and active_run_id == run_id:
        return "running"
    # Cut short by a Cloudflare block and queued to continue -- not abandoned. This
    # must not be "stale": the dashboard filters stale runs out of every selection
    # path, which would hide the run holding the freshest data.
    return "blocked" if run.get("resume_pending") else "stale"


def _read_run(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _build_last_good_lookup(exclude_run_id: str = "", depth: int = 2) -> dict[str, dict[str, str]]:
    """Map source_url/ticker -> most recent successful verdict from prior runs.

    Used to carry a blue-chip's last real verdict forward when the current cycle
    hits a transient Cloudflare collection gap, instead of showing "오류".
    Scans only the newest ``depth`` completed runs so this stays cheap.
    """
    if not CARRY_LAST_GOOD:
        return {}
    ensure_storage()
    try:
        paths = sorted(RUNS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception:
        return {}
    lookup: dict[str, dict[str, str]] = {}
    scanned = 0
    for path in paths:
        if scanned >= max(1, depth):
            break
        run = _read_run(path)
        if not run or _clean_text(run.get("run_id")) == _clean_text(exclude_run_id):
            continue
        scanned += 1
        for rec in run.get("records", []) or []:
            if rec.get("result") not in _SUCCESS_LABELS:
                continue
            key = _clean_text(rec.get("source_url")) or _clean_text(rec.get("ticker"))
            if key and key not in lookup:
                lookup[key] = {
                    "result": _clean_text(rec.get("result")),
                    "raw_result": _clean_text(rec.get("raw_result")) or _clean_text(rec.get("result")),
                    "analyzed_at": _clean_text(rec.get("analyzed_at")),
                    "cycle_label": _clean_text(run.get("cycle_label")) or _clean_text(run.get("title")),
                }
    return lookup


def mark_run_resume_pending(run_id: str) -> bool:
    """Record on disk that ``run_id`` was cut short and should be continued.

    The in-memory intent alone is not enough: a resumed cycle stays open for 7h+,
    and restarting Flask is how we deploy, so an intent that lives only in the
    worker's locals would routinely be lost mid-cool-off. Returns False (never
    raises) when there is nothing to mark -- bookkeeping must not kill the loop.
    """
    try:
        run = _load_resumable_run(run_id)
        if run is None:
            return False
        run["resume_pending"] = True
        run["blocked_at"] = _now()
        _write_run(run)
        return True
    except Exception:
        return False


def _has_unfinished_rows(run: dict[str, Any]) -> bool:
    return any(
        _clean_text(record.get("scrape_state")) not in _TERMINAL_SCRAPE_STATES
        for record in (run.get("records") or [])
    )


def _run_is_recent(run: dict[str, Any]) -> bool:
    stamp = _clean_text(run.get("updated_at")) or _clean_text(run.get("created_at"))
    try:
        updated = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return False
    return (datetime.now() - updated) <= timedelta(hours=RESUME_ADOPT_MAX_AGE_HOURS)


def find_resume_pending_run() -> dict[str, Any] | None:
    """Newest interrupted run awaiting continuation, or None.

    Consulted at loop start. Two ways in: the run was explicitly marked when the
    Cloudflare circuit opened, or it was simply left mid-scrape when the process
    died. Restarting is how we deploy and a cycle now spans ~6.6h, so most
    interruptions land while scraping rather than during the 45min cool-off --
    both must be picked up or every deploy discards hours of collection.
    Anything older than RESUME_ADOPT_MAX_AGE_HOURS is history, not work in flight.
    """
    if not RESUME_AFTER_BLOCK:
        return None
    try:
        for path in _run_files_newest_first():
            run = _read_run(path)
            if not run:
                continue
            if _clean_text(run.get("status")) != "running":
                continue
            if not run.get("resume_pending"):
                if not _run_is_recent(run) or not _has_unfinished_rows(run):
                    continue
            return {
                "run_id": _clean_text(run.get("run_id")),
                "cycle_date": _clean_text(run.get("cycle_date")),
                "cycle_number": run.get("cycle_number"),
                "cycle_label": _clean_text(run.get("cycle_label")),
                "cycle_started_at": _clean_text(run.get("created_at")),
            }
    except Exception:
        return None
    return None


def _load_resumable_run(run_id: str) -> dict[str, Any] | None:
    """Return the persisted run for ``run_id`` when it can be continued in place.

    Used after a Cloudflare cool-off so the next pass picks up the rows the block
    interrupted instead of restarting the cycle from rank 1. Returns None (caller
    falls back to a fresh build) whenever the run is missing or has no records.
    """
    clean_run_id = _clean_text(run_id)
    if not clean_run_id:
        return None
    ensure_storage()
    try:
        path = _run_path(clean_run_id)
    except Exception:
        return None
    if not path.is_file():
        return None
    run = _read_run(path)
    if not run:
        return None
    records = run.get("records")
    if not isinstance(records, list) or not records:
        return None
    return run


def _next_cycle_number_for_date(cycle_date: str) -> int:
    ensure_storage()
    highest = 0
    for path in RUNS_DIR.glob("*.json"):
        run = _read_run(path)
        if not run:
            continue
        if run.get("cycle_date") != cycle_date:
            continue
        try:
            highest = max(highest, int(run.get("cycle_number") or 0))
        except Exception:
            continue
    return highest + 1


def import_result_file(path: str | os.PathLike[str], *, original_name: str | None = None) -> dict[str, Any]:
    """Import a legacy result workbook into a durable manual run JSON."""
    ensure_storage()
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(str(source))
    records = _read_excel_records(source, pending=False)
    fingerprint = _file_fingerprint(source)
    run_id = f"manual_{fingerprint}"
    existing = _read_run(_run_path(run_id))
    if existing:
        return existing
    run = {
        "run_id": run_id,
        "title": original_name or source.name,
        "source_kind": "result_excel",
        "source_path": str(source),
        "source_fingerprint": fingerprint,
        "created_at": _now(),
        "record_count": len(records),
        "summary": _summary(records),
        "records": records,
    }
    return _write_run(run)


def save_uploaded_result(file_storage: Any) -> dict[str, Any]:
    ensure_storage()
    filename = _safe_filename(getattr(file_storage, "filename", "") or "manual_result.xlsx")
    if not filename.lower().endswith((".xlsx", ".xls")):
        raise ValueError("Excel 파일(.xlsx/.xls)만 업로드할 수 있습니다.")
    target = UPLOADS_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
    file_storage.save(str(target))
    return import_result_file(target, original_name=filename)


def create_pending_run_from_source(*, max_rows: int = 2500) -> dict[str, Any]:
    """Create a pending manual run from the configured stock source workbook."""
    source = _find_source_workbook()
    if source is None:
        raise FileNotFoundError("stock_data_final.xlsx 원본을 찾을 수 없습니다.")
    records = _read_excel_records(source, pending=True)[: max(1, min(max_rows, MAX_SOURCE_ROWS))]
    fingerprint = hashlib.sha1(f"{source.resolve()}:{_now()}:{len(records)}".encode("utf-8", "ignore")).hexdigest()[:16]
    run = {
        "run_id": f"manual_pending_{fingerprint}",
        "title": f"{datetime.now().strftime('%Y년%m월%d일')} - 기본 자동 목록",
        "source_kind": "source_excel",
        "source_path": str(source),
        "source_fingerprint": fingerprint,
        "created_at": _now(),
        "record_count": len(records),
        "summary": _summary(records),
        "records": records,
    }
    return _write_run(run)


def _find_source_workbook() -> Path:
    source = next((p for p in DEFAULT_SOURCE_PATHS if str(p) and p.is_file()), None)
    if source is None:
        raise FileNotFoundError("E:\\다운로드\\stock_data_final.xlsx 원본을 찾을 수 없습니다.")
    return source


def _read_source_records(*, pending: bool = True) -> tuple[Path, list[dict[str, Any]]]:
    source = _find_source_workbook()
    records = _read_excel_records(source, pending=pending)[:MAX_SOURCE_ROWS]
    return source, records


def _requested_record_count(max_rows: int, source_count: int) -> int:
    requested = int(max_rows or 0)
    if requested <= 0:
        return min(source_count, MAX_SOURCE_ROWS)
    return max(1, min(requested, source_count, MAX_SOURCE_ROWS))


def _create_selenium_driver():
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager
    except ImportError as exc:
        raise RuntimeError("Selenium 스크래퍼 실행에는 selenium, webdriver-manager 패키지가 필요합니다.") from exc

    user_data_dir = tempfile.mkdtemp(prefix=SCRAPE_PROFILE_PREFIX)
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--window-size=1365,1400")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-background-networking")
    chrome_options.add_argument("--disable-software-rasterizer")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--lang=ko-KR")
    chrome_options.add_argument("--no-first-run")
    chrome_options.add_argument("--remote-debugging-port=0")
    chrome_options.add_argument(f"--user-data-dir={user_data_dir}")
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/149.0.0.0 Safari/537.36"
    )
    chrome_options.add_experimental_option("useAutomationExtension", False)
    chrome_options.add_experimental_option("excludeSwitches", ["enable-logging"])
    chrome_options.add_experimental_option("prefs", {"intl.accept_languages": "ko-KR,ko,en-US,en"})
    chrome_options.page_load_strategy = "eager"
    service = Service(ChromeDriverManager().install())
    try:
        driver = webdriver.Chrome(service=service, options=chrome_options)
    except Exception:
        shutil.rmtree(user_data_dir, ignore_errors=True)
        raise
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": """
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    Object.defineProperty(navigator, 'languages', {get: () => ['ko-KR', 'ko', 'en-US', 'en']});
                    Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});
                """
            },
        )
    except Exception:
        pass
    setattr(driver, "_marketflow_user_data_dir", user_data_dir)
    return driver


def _close_selenium_driver(driver: Any) -> None:
    user_data_dir = getattr(driver, "_marketflow_user_data_dir", "")
    try:
        driver.quit()
    except Exception:
        pass
    if user_data_dir:
        shutil.rmtree(user_data_dir, ignore_errors=True)


def _extract_industry_from_text(text: str) -> str:
    visible_text = _clean_text(text)
    if not visible_text:
        return ""
    patterns = [
        r"(?:산업|업종)\s*[:：]?\s*([^\n\r]{2,50})",
        r"(?:Industry|Sector)\s*[:：]?\s*([^\n\r]{2,70})",
    ]
    for pattern in patterns:
        match = re.search(pattern, visible_text, flags=re.IGNORECASE)
        if not match:
            continue
        candidate = re.split(r"\s{2,}|\t|[|]", match.group(1).strip())[0].strip()
        if not _is_missing_industry(candidate):
            return candidate[:70]
    return ""


def _scrape_page_fields(driver: Any, url: str, xpath: str, *, timeout_sec: int) -> dict[str, str]:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    load_error: Exception | None = None
    try:
        driver.set_page_load_timeout(max(3, int(timeout_sec or 10)))
    except Exception:
        pass
    try:
        driver.get(url)
    except Exception as exc:
        # Investing.com often leaves enough DOM/text behind after a slow page
        # load. Stop pending assets and still try the deterministic fallback
        # parser before marking the row as a real scrape error.
        load_error = exc
        try:
            driver.execute_script("window.stop();")
        except Exception:
            pass
    visible_text = ""
    try:
        WebDriverWait(driver, timeout_sec).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        visible_text = _wait_for_investing_text(driver, timeout_sec)
    except Exception:
        visible_text = _read_body_text(driver)

    block_reason = _blocked_page_reason(visible_text)
    if block_reason:
        raise RuntimeError(f"target page blocked: {block_reason}")

    snapshot_fields = _extract_investing_snapshot_fields(visible_text)
    result_text = ""
    if xpath:
        try:
            element = WebDriverWait(driver, min(timeout_sec, 4)).until(
                EC.presence_of_element_located((By.XPATH, xpath))
            )
            result_text = _clean_text(element.text)
        except Exception:
            result_text = ""
    result_text = snapshot_fields.get("result") or result_text
    if not result_text:
        result_text = _extract_recommendation_from_text(visible_text)
    if load_error is not None and not visible_text and not result_text:
        raise RuntimeError(f"page load failed: {type(load_error).__name__}: {str(load_error)[:120]}")
    return {
        "result": result_text,
        "industry": snapshot_fields.get("industry") or _extract_industry_from_text(visible_text),
        "technical_result": snapshot_fields.get("technical_result", ""),
        "analyst_sentiment": snapshot_fields.get("analyst_sentiment", ""),
        "sector": snapshot_fields.get("sector", ""),
        "employees": snapshot_fields.get("employees", ""),
        "market_country": snapshot_fields.get("market_country", ""),
        "target_price": snapshot_fields.get("target_price", ""),
        "upside_potential": snapshot_fields.get("upside_potential", ""),
    }


def _build_scrape_run(
    *,
    run_id: str,
    source: Path,
    records: list[dict[str, Any]],
    source_record_count: int,
    xpath: str,
    max_rows: int,
    timeout_sec: int,
    status: str,
    created_at: str,
    cycle_date: str = "",
    cycle_number: int | None = None,
    cycle_label: str = "",
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "title": cycle_label or f"{datetime.now().strftime('%Y년%m월%d일 %H:%M:%S')} - 실시간 스크래퍼 {max_rows}건",
        "cycle_date": cycle_date,
        "cycle_number": cycle_number,
        "cycle_label": cycle_label,
        "source_kind": "selenium_scrape",
        "source_path": str(source),
        "source_fingerprint": _file_fingerprint(source),
        "created_at": created_at,
        "updated_at": _now(),
        "status": status,
        "record_count": len(records),
        "source_record_count": source_record_count,
        "summary": _summary(records),
        "records": records,
        "scraper": {
            "xpath": xpath,
            "max_rows": max_rows,
            "source_record_count": source_record_count,
            "timeout_sec": timeout_sec,
        },
    }


def _persist_scrape_run(run: dict[str, Any], *, records: list[dict[str, Any]], status: str) -> dict[str, Any]:
    run["records"] = records
    run["record_count"] = len(records)
    run["summary"] = _summary(records)
    run["updated_at"] = _now()
    run["status"] = status
    if status == "completed":
        # The cycle is finished, so nothing should adopt it again on the next boot.
        run.pop("resume_pending", None)
        run.pop("blocked_at", None)
    return _write_run(run)


def scrape_source_run(
    *,
    max_rows: int = 0,
    xpath: str = DEFAULT_INVESTING_XPATH,
    timeout_sec: int = 10,
    delay_sec: float = DEFAULT_SCRAPE_DELAY_SEC,
    progress_callback: Callable[[int, int, dict[str, Any]], None] | None = None,
    run_id: str | None = None,
    persist_progress: bool = False,
    cycle_date: str = "",
    cycle_number: int | None = None,
    cycle_label: str = "",
    resume: bool = False,
) -> dict[str, Any]:
    """Run the legacy Investing.com-style scraper and persist a manual run.

    This is synchronous and intentionally capped because it opens a browser and
    talks to a third-party web page.  Large all-market batches should be moved
    to a background worker before production use.

    ``resume=True`` continues the run already persisted under ``run_id`` instead
    of rebuilding it from the source workbook: rows already in a terminal state
    are kept as-is and skipped, and only the unfinished tail is scraped. This is
    how the loop survives the site's ~1,400-page-per-IP ceiling without losing
    the ~60% of the universe it already collected.
    """
    timeout_sec = max(3, min(int(timeout_sec or 10), 30))
    resumed_run = _load_resumable_run(run_id or "") if (resume and RESUME_AFTER_BLOCK) else None

    if resumed_run is not None:
        run = resumed_run
        # The persisted list is the WHOLE universe, terminal rows included, so
        # progress/record_count/summary stay whole-universe (1450/2341, not 50/900).
        records = list(run.get("records") or [])
        current_run_id = _clean_text(run.get("run_id")) or str(run_id)
        created_at = _clean_text(run.get("created_at")) or _now()
        source_record_count = safe_int(run.get("source_record_count"), len(records))
        run["status"] = "running"
        run["updated_at"] = _now()
    else:
        source, source_records = _read_source_records(pending=True)
        source_record_count = len(source_records)
        safe_max_rows = _requested_record_count(int(max_rows or 0), source_record_count)
        created_at = _now()
        fingerprint = hashlib.sha1(f"{source.resolve()}:{created_at}:{safe_max_rows}".encode("utf-8", "ignore")).hexdigest()[:16]
        current_run_id = run_id or f"manual_scrape_{fingerprint}"
        records = source_records[:safe_max_rows]
        for record in records:
            record["scrape_state"] = "pending"
            record["analyzed_at"] = ""
        run = _build_scrape_run(
            run_id=current_run_id,
            source=source,
            records=records,
            source_record_count=source_record_count,
            xpath=xpath,
            max_rows=safe_max_rows,
            timeout_sec=timeout_sec,
            status="running",
            created_at=created_at,
            cycle_date=cycle_date,
            cycle_number=cycle_number,
            cycle_label=cycle_label,
        )
    if persist_progress:
        _write_run(run)

    if not records:
        return _persist_scrape_run(run, records=records, status="completed")

    driver = None
    last_good_lookup = _build_last_good_lookup(exclude_run_id=current_run_id)
    consecutive_blocks = 0
    try:
        driver = _create_selenium_driver()
        pages_on_driver = 0
        total = len(records)
        for index, record in enumerate(records, start=1):
            # Resumed cycle: rows already settled before the block are not touched
            # again. ``index`` still counts over the full list, so the dashboard
            # keeps showing whole-universe position rather than restarting at 1.
            if resumed_run is not None and _clean_text(record.get("scrape_state")) in _TERMINAL_SCRAPE_STATES:
                continue
            # Recycle before the request, not after a failure: the site 403s every
            # navigation after the first in a session, so a reused driver would burn
            # an attempt and a retry backoff to reach the same place.
            if driver is not None and PAGES_PER_SESSION and pages_on_driver >= PAGES_PER_SESSION:
                _close_selenium_driver(driver)
                driver = None
            if driver is None:
                driver = _create_selenium_driver()
                pages_on_driver = 0
            record["scrape_state"] = "scraping"
            record["analyzed_at"] = _now()
            if persist_progress:
                _persist_scrape_run(run, records=records, status="running")
            if progress_callback:
                progress_callback(index, total, dict(record))

            url = _clean_text(record.get("source_url"))
            if not url:
                record["raw_result"] = "오류"
                record["result"] = "오류"
                record["scrape_state"] = "error"
                record["error"] = "missing source_url"
                record["analyzed_at"] = _now()
                if progress_callback:
                    progress_callback(index, total, dict(record))
                if persist_progress:
                    _persist_scrape_run(run, records=records, status="running")
                if delay_sec > 0:
                    time.sleep(min(delay_sec, 2.0))
                continue
            try:
                retry_fallback = ""
                attempt = 0
                while True:
                    try:
                        pages_on_driver += 1
                        scraped_fields = _scrape_page_fields(driver, url, xpath, timeout_sec=timeout_sec)
                        break
                    except Exception as scrape_exc:
                        if attempt >= RETRY_MAX or not _is_retryable_scrape_error(scrape_exc):
                            raise
                        attempt += 1
                        # Fresh session + exponential backoff with jitter. A same-fingerprint
                        # retry ~1s later almost always hits the same Cloudflare challenge;
                        # backing off (5s, 15s, ...) gives the block a chance to lift.
                        if driver is not None:
                            _close_selenium_driver(driver)
                            driver = None
                        backoff = _jittered(RETRY_BASE_SEC * (3 ** (attempt - 1)), RETRY_BASE_SEC)
                        time.sleep(min(backoff, 45.0))
                        driver = _create_selenium_driver()
                        pages_on_driver = 0
                        retry_fallback = "retry_fresh_session"
                scraped = scraped_fields.get("result", "")
                if not scraped:
                    raise RuntimeError("empty investing verdict after render wait")
                record["raw_result"] = scraped
                record["result"] = _normalise_label(scraped)
                scraped_industry = scraped_fields.get("industry", "")
                if not _is_missing_industry(scraped_industry):
                    record["industry"] = scraped_industry
                for field in (
                    "technical_result",
                    "analyst_sentiment",
                    "sector",
                    "employees",
                    "market_country",
                    "target_price",
                    "upside_potential",
                ):
                    value = _clean_text(scraped_fields.get(field))
                    if value:
                        record[field] = value
                record["scrape_state"] = "completed"
                record.pop("stale_from", None)
                consecutive_blocks = 0
                if retry_fallback:
                    record["scrape_fallback"] = retry_fallback
            except ScraperCircuitOpen:
                raise
            except Exception as exc:
                # A third-party page timeout/block is a data-collection gap, not an
                # analyst verdict. Carry the last known-good verdict forward (marked
                # stale) when available so a Cloudflare burst does not overwrite a
                # blue-chip's real verdict with "오류"; otherwise record the gap.
                is_block = _is_block_error(exc)
                key = _clean_text(record.get("source_url")) or _clean_text(record.get("ticker"))
                carried = last_good_lookup.get(key) if key else None
                if carried:
                    record["result"] = carried.get("result") or "오류"
                    record["raw_result"] = carried.get("raw_result") or record["result"]
                    record["scrape_state"] = "completed"
                    record["scrape_fallback"] = "stale_cache"
                    record["stale_from"] = carried.get("cycle_label") or carried.get("analyzed_at") or ""
                    record["error"] = ""
                else:
                    record["raw_result"] = "오류"
                    record["result"] = "오류"
                    record["scrape_state"] = "error"
                    record["scrape_fallback"] = "collection_gap"
                    record["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
                    record.pop("stale_from", None)
                # Circuit breaker: a run of consecutive blocks means the IP is being
                # challenged. Abort the cycle so the loop enters a long cool-off instead
                # of hammering ~2,300 more rows and sustaining the block.
                consecutive_blocks = consecutive_blocks + 1 if is_block else 0
                if BLOCK_CIRCUIT_THRESHOLD > 0 and consecutive_blocks >= BLOCK_CIRCUIT_THRESHOLD:
                    record["analyzed_at"] = _now()
                    if progress_callback:
                        progress_callback(index, total, dict(record))
                    if persist_progress:
                        _persist_scrape_run(run, records=records, status="running")
                    raise ScraperCircuitOpen(
                        f"{consecutive_blocks} consecutive blocks; aborting cycle at rank {record.get('rank')}"
                    )
            if _is_missing_industry(record.get("industry")):
                record["industry"] = _cached_industry_for(record.get("ticker", ""), record.get("market", "")) or "미분류"
            record["analyzed_at"] = _now()
            if progress_callback:
                progress_callback(index, total, dict(record))
            if persist_progress:
                _persist_scrape_run(run, records=records, status="running")
            if delay_sec > 0:
                time.sleep(min(delay_sec, 2.0))
    except Exception:
        if persist_progress:
            _persist_scrape_run(run, records=records, status="error")
        raise
    finally:
        if driver is not None:
            _close_selenium_driver(driver)

    return _persist_scrape_run(run, records=records, status="completed")


def _scraper_loop_worker(
    *,
    max_rows: int,
    interval_sec: int,
    timeout_sec: int,
    xpath: str,
) -> None:
    # Set when a cycle was cut short by the Cloudflare circuit. The next iteration
    # then continues THAT run (same run_id/회차) instead of starting over at rank 1,
    # which is the only way to get past the site's ~1,400-page-per-IP ceiling.
    # Seeded from disk so a restart during a cool-off (which is how we deploy)
    # continues the interrupted cycle instead of abandoning its ~1,400 rows.
    pending_resume: dict[str, Any] | None = find_resume_pending_run()
    while not _LOOP_STOP.is_set():
        started_at = _now()
        if pending_resume is not None:
            cycle_date = str(pending_resume.get("cycle_date") or "")
            cycle_number = pending_resume.get("cycle_number")
            cycle_label = str(pending_resume.get("cycle_label") or "")
            live_run_id = str(pending_resume.get("run_id") or "")
            cycle_started_at = str(pending_resume.get("cycle_started_at") or started_at)
        else:
            cycle_date = datetime.now().strftime("%Y-%m-%d")
            cycle_number = _next_cycle_number_for_date(cycle_date)
            cycle_label = f"{cycle_date} - {cycle_number}회차"
            live_run_hash = hashlib.sha1(f"{started_at}:{max_rows}:{time.time()}".encode("utf-8", "ignore")).hexdigest()[:12]
            live_run_id = f"manual_scrape_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{live_run_hash}"
            cycle_started_at = started_at
        try:
            source, source_records = _read_source_records(pending=True)
            source_record_count = len(source_records)
            loop_total = _requested_record_count(max_rows, source_record_count)
            source_path = str(source)
        except Exception as exc:
            source_record_count = 0
            loop_total = max_rows if max_rows > 0 else 0
            source_path = ""
            if max_rows <= 0:
                _loop_set(
                    running=True,
                    state="error_waiting",
                    source_path=source_path,
                    source_record_count=source_record_count,
                    processed=0,
                    total=0,
                    last_started_at=started_at,
                    last_finished_at=_now(),
                    last_error=f"{type(exc).__name__}: {str(exc)[:220]}",
                    next_run_at=(datetime.now() + timedelta(seconds=AUTO_LOOP_ERROR_BACKOFF_SEC)).strftime("%Y-%m-%d %H:%M:%S"),
                )
                if _LOOP_STOP.wait(AUTO_LOOP_ERROR_BACKOFF_SEC):
                    break
                continue

        _loop_set(
            running=True,
            state="scraping",
            mode="auto",
            auto_start=AUTO_LOOP_ENABLED,
            max_rows=max_rows,
            interval_sec=interval_sec,
            timeout_sec=timeout_sec,
            source_path=source_path,
            source_record_count=source_record_count,
            cycle=cycle_number,
            processed=0,
            total=loop_total,
            current_rank=None,
            current_stock="",
            current_industry="",
            current_result="",
            last_run_id=live_run_id,
            last_record_count=0,
            last_started_at=started_at,
            cycle_started_at=cycle_started_at,
            current_cycle_label=cycle_label,
            next_run_at="",
            last_error="",
        )

        def on_progress(processed: int, total: int, record: dict[str, Any]) -> None:
            _loop_set(
                state="scraping",
                processed=processed,
                total=total,
                current_rank=record.get("rank"),
                current_stock=record.get("stock_name") or "",
                current_industry=record.get("industry") or "",
                current_result=record.get("result") or record.get("raw_result") or "",
            )

        resume_this_cycle = pending_resume is not None
        # Consumed here (not at loop top) so a source-read failure that `continue`s
        # above does not silently drop the pending resume.
        pending_resume = None
        try:
            run = scrape_source_run(
                max_rows=max_rows,
                xpath=xpath,
                timeout_sec=timeout_sec,
                progress_callback=on_progress,
                run_id=live_run_id,
                persist_progress=True,
                cycle_date=cycle_date,
                cycle_number=cycle_number,
                cycle_label=cycle_label,
                resume=resume_this_cycle,
            )
            with _LOOP_LOCK:
                iterations = int(_LOOP_STATE.get("iterations") or 0) + 1
            _loop_set(
                state="waiting",
                iterations=iterations,
                processed=run.get("record_count", 0),
                total=run.get("record_count", loop_total),
                last_run_id=run.get("run_id") or "",
                last_record_count=run.get("record_count", 0),
                last_finished_at=_now(),
                last_error="",
            )
        except ScraperCircuitOpen as exc:
            # Consecutive-block circuit tripped mid-cycle. Keep the partial run's good
            # rows and enter a long cool-off so the IP reputation can recover.
            with _LOOP_LOCK:
                iterations = int(_LOOP_STATE.get("iterations") or 0) + 1
            _loop_set(
                state="blocked_waiting",
                iterations=iterations,
                last_run_id=live_run_id,
                last_finished_at=_now(),
                last_error=f"circuit open (Cloudflare): {str(exc)[:200]}",
            )
            # Queue the SAME run for the post-cool-off pass. Without this the next
            # cycle re-scraped rank 1 onward and never reached the last ~900 rows.
            if RESUME_AFTER_BLOCK:
                pending_resume = {
                    "run_id": live_run_id,
                    "cycle_date": cycle_date,
                    "cycle_number": cycle_number,
                    "cycle_label": cycle_label,
                    "cycle_started_at": cycle_started_at,
                }
                # Mirror the intent onto the run file: the cool-off is 45-56min and
                # a restart in that window would otherwise lose the whole cycle.
                mark_run_resume_pending(live_run_id)
        except Exception as exc:
            with _LOOP_LOCK:
                iterations = int(_LOOP_STATE.get("iterations") or 0) + 1
            _loop_set(
                state="error_waiting",
                iterations=iterations,
                last_finished_at=_now(),
                last_error=f"{type(exc).__name__}: {str(exc)[:220]}",
            )

        if _LOOP_STOP.is_set():
            break
        with _LOOP_LOCK:
            last_state = str(_LOOP_STATE.get("state") or "")
        if last_state == "blocked_waiting":
            wait_sec = _jittered(BLOCK_BACKOFF_SEC, BLOCK_BACKOFF_SEC * 0.25)
        elif last_state == "error_waiting":
            wait_sec = AUTO_LOOP_ERROR_BACKOFF_SEC if interval_sec <= 0 else interval_sec
        elif interval_sec > 0:
            wait_sec = _jittered(interval_sec, AUTO_LOOP_JITTER_SEC)
        else:
            wait_sec = 0
        next_run_at = "immediate" if wait_sec <= 0 else (datetime.now() + timedelta(seconds=wait_sec)).strftime("%Y-%m-%d %H:%M:%S")
        _loop_set(next_run_at=next_run_at)
        _LOOP_STOP.wait(wait_sec)

    _loop_set(running=False, state="stopped", next_run_at="")


def ensure_scraper_loop_started() -> dict[str, Any]:
    snapshot = _loop_snapshot()
    if snapshot.get("running") or not AUTO_LOOP_ENABLED:
        return snapshot
    return start_scraper_loop(
        max_rows=AUTO_LOOP_MAX_ROWS,
        interval_sec=AUTO_LOOP_INTERVAL_SEC,
        timeout_sec=AUTO_LOOP_TIMEOUT_SEC,
        xpath=DEFAULT_INVESTING_XPATH,
    )


def sweep_orphan_browsers(timeout_sec: int = 30) -> int:
    """이전 프로세스가 남긴 스크래퍼 브라우저를 정리한다. 종료한 개수를 돌려준다.

    `_close_selenium_driver` 는 정상 종료와 예외를 모두 덮지만, **프로세스가
    강제 종료되면 finally 가 돌지 않는다.** 워치독이 Flask 를 재시작하거나
    재부팅할 때마다 그 안에서 돌던 브라우저가 통째로 고아가 된다.

    2026-08-05 실측: 07-31·08-02 자 고아가 chrome 581 프로세스 9.72GB 를 점유해
    15.4GB 머신의 가용 메모리가 1.16GB(92.5% 사용)까지 떨어졌다. 스왑 때문에
    파일 하나 읽는 /api/health 가 10.7초까지 걸려 앱이 죽은 것처럼 보였다.
    우리 파이썬 프로세스 10개는 합쳐서 0.09GB 였다 — 코드가 아니라 잔해가 문제였다.

    user-data-dir 접두어로 우리가 띄운 것만 식별한다. 사용자의 실제 Chrome 은
    이 접두어를 갖지 않으므로 건드리지 않는다.
    """
    if not sys.platform.startswith('win'):
        return 0

    script = (
        "$p = Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
        f"Where-Object {{ $_.CommandLine -like '*{SCRAPE_PROFILE_PREFIX}*' }}; "
        "$n = ($p | Measure-Object).Count; "
        "$p | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; "
        "Write-Output $n"
    )
    try:
        done = subprocess.run(
            ['powershell', '-NoProfile', '-Command', script],
            capture_output=True, text=True, timeout=timeout_sec,
        )
        killed = int((done.stdout or '0').strip() or 0)
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0

    # 프로필 디렉토리도 함께 남는다. 브라우저를 죽인 뒤라야 지워진다.
    removed = 0
    try:
        for entry in Path(tempfile.gettempdir()).glob(f'{SCRAPE_PROFILE_PREFIX}*'):
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
    except OSError:
        pass

    if killed or removed:
        _log.warning(
            '고아 스크래퍼 브라우저 정리: 프로세스 %d개, 프로필 디렉토리 %d개',
            killed, removed,
        )
    return killed


def start_scraper_loop_on_boot() -> bool:
    """Start the scraper loop once per process, off the caller's thread.

    Unlike :func:`ensure_scraper_loop_started` (driven by a status GET) this is a
    deliberate operator-level start, so it runs even when request auto-start is
    disabled. Returns True when a starter thread was spawned. Never raises and
    never blocks: a scraper failure must not take the API process down with it.
    """
    # 이전 프로세스가 강제 종료되며 남긴 브라우저를 먼저 걷어낸다.
    # 이 정리는 루프 자동시작 여부와 무관하다 — 잔해는 루프를 켜지 않아도 쌓여 있다.
    try:
        sweep_orphan_browsers()
    except Exception as exc:   # 정리 실패가 앱 기동을 막아서는 안 된다
        _log.warning('고아 브라우저 정리 실패: %s: %s', type(exc).__name__, exc)

    if not LOOP_BOOT_AUTOSTART:
        return False

    def _boot() -> None:
        # Waiting on _LOOP_STOP (not sleep) lets an explicit stop cancel the pending start.
        if _LOOP_STOP.wait(LOOP_BOOT_DELAY_SEC):
            return
        try:
            start_scraper_loop(
                max_rows=AUTO_LOOP_MAX_ROWS,
                interval_sec=AUTO_LOOP_INTERVAL_SEC,
                timeout_sec=AUTO_LOOP_TIMEOUT_SEC,
                xpath=DEFAULT_INVESTING_XPATH,
            )
        except Exception as exc:
            _loop_set(last_error=f"boot autostart failed: {type(exc).__name__}: {str(exc)[:180]}")

    threading.Thread(
        target=_boot,
        name="manual-stock-analysis-boot-start",
        daemon=True,
    ).start()
    return True


_search_index_cache: dict[str, Any] = {}

# Runs scanned newest-first when collecting industry names. A freshly started cycle
# has no scraped rows yet, so we fall back through a few recent runs.
_INDUSTRY_SCAN_LIMIT = 5
# Industries drift slowly, and each scan parses ~1MB run files -- keying the cache on
# run mtime instead would re-scan every few seconds during a live cycle.
_INDUSTRY_CACHE_TTL_SEC = 600
_industry_cache: dict[str, Any] = {}


def _run_files_newest_first() -> list[Path]:
    """Saved run files, newest first, skipping atomic-write temporaries."""
    paths = [path for path in RUNS_DIR.glob("*.json") if not path.name.startswith(".")]
    return sorted(paths, key=lambda path: path.stat().st_mtime, reverse=True)


def _scraped_industries() -> list[dict[str, Any]]:
    """Industry names as they appear on scraped rows, with stock counts.

    Deliberately not from the source workbook: that stores English industries
    ("Semiconductors") while scraping overwrites them with the Korean names the
    run table filters on, so workbook values would suggest terms that match
    nothing. Pending rows still hold the workbook value and are skipped.
    """
    now = time.time()
    if _industry_cache and now - float(_industry_cache.get("at") or 0) < _INDUSTRY_CACHE_TTL_SEC:
        return _industry_cache["data"]

    industries = _scan_scraped_industries()
    _industry_cache.update({"at": now, "data": industries})
    return industries


def _scan_scraped_industries() -> list[dict[str, Any]]:
    for path in _run_files_newest_first()[:_INDUSTRY_SCAN_LIMIT]:
        run = _read_run(path)
        if not run:
            continue
        counts: dict[str, int] = {}
        for record in run.get("records") or []:
            if record.get("scrape_state") != "completed":
                continue
            industry = _clean_text(record.get("industry"))
            if industry:
                counts[industry] = counts.get(industry, 0) + 1
        if counts:
            return [{"name": name, "count": count} for name, count in sorted(counts.items())]
    return []


def build_search_index() -> dict[str, Any]:
    """Stock/industry universe for search autocomplete.

    Built from the scraping source workbook, not from run files: a live cycle
    withholds rows it has not scraped yet, so a run-backed index would offer only
    the handful of stocks already processed. Cached against the workbook
    fingerprint since the file changes at most a few times a year.
    """
    source = _find_source_workbook()
    # Fingerprint before parsing -- checking afterwards would still pay the read.
    fingerprint = _file_fingerprint(source)
    if _search_index_cache.get("fingerprint") == fingerprint:
        # Only the workbook half is cached here: industries come from run files and
        # carry their own (time-based) cache, so they must be re-attached each call.
        return {
            "stocks": _search_index_cache["stocks"],
            "industries": _scraped_industries(),
            "source_path": _search_index_cache["source_path"],
            "count": len(_search_index_cache["stocks"]),
        }
    records = _read_excel_records(source, pending=True)[:MAX_SOURCE_ROWS]

    stocks: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for record in records:
        name = _clean_text(record.get("stock_name"))
        ticker = _clean_text(record.get("ticker"))
        if not name and not ticker:
            continue
        key = (name, ticker)
        if key in seen:
            continue
        seen.add(key)
        stocks.append({
            # Workbook row order approximates market cap; the client ranks ties by it.
            "rank": safe_int(record.get("rank"), 0),
            "name": name,
            "ticker": ticker,
            "industry": _clean_text(record.get("industry")),
        })

    _search_index_cache.update({
        "fingerprint": fingerprint,
        "stocks": stocks,
        "source_path": str(source),
    })
    return {
        "stocks": stocks,
        "industries": _scraped_industries(),
        "source_path": str(source),
        "count": len(stocks),
    }


def latest_run_data_at() -> str:
    """Wall-clock time the newest run file last received data ("" when none).

    Deliberately file mtime (a stat, no JSON parsing): this rides on the 1s status
    poll, while parsing every run JSON would move ~85MB per request. Disk-based on
    purpose too -- in-memory loop flags reset on restart, which is how the
    2026-07-15 freeze stayed invisible for 10 days.
    """
    try:
        newest = max((path.stat().st_mtime for path in RUNS_DIR.glob("*.json")), default=0.0)
    except Exception:
        return ""
    if not newest:
        return ""
    return datetime.fromtimestamp(newest).strftime("%Y-%m-%d %H:%M:%S")


def get_scraper_loop_status(*, auto_start: bool = False) -> dict[str, Any]:
    status = dict(_scraper_loop_status(auto_start=auto_start))
    status["last_data_at"] = latest_run_data_at()
    return status


def _scraper_loop_status(*, auto_start: bool = False) -> dict[str, Any]:
    if auto_start:
        snapshot = ensure_scraper_loop_started()
        if snapshot.get("running"):
            return snapshot
    snapshot = _loop_snapshot()
    if snapshot.get("running") or int(snapshot.get("source_record_count") or 0) > 0:
        return snapshot
    try:
        source, source_records = _read_source_records(pending=True)
    except Exception:
        return snapshot
    source_count = len(source_records)
    total = _requested_record_count(int(snapshot.get("max_rows") or 0), source_count)
    return _loop_set(
        source_path=str(source),
        source_record_count=source_count,
        total=total,
    )


def start_scraper_loop(
    *,
    max_rows: int = 0,
    interval_sec: int = 60,
    timeout_sec: int = 10,
    xpath: str = DEFAULT_INVESTING_XPATH,
) -> dict[str, Any]:
    global _LOOP_THREAD
    requested_rows = int(max_rows or 0)
    safe_max_rows = 0 if requested_rows <= 0 else max(1, min(requested_rows, MAX_SOURCE_ROWS))
    safe_interval = max(0, min(int(interval_sec or 0), 86400))
    safe_timeout = max(3, min(int(timeout_sec or 10), 30))
    source_path = ""
    source_record_count = 0
    initial_total = safe_max_rows
    try:
        source, source_records = _read_source_records(pending=True)
        source_path = str(source)
        source_record_count = len(source_records)
        initial_total = _requested_record_count(safe_max_rows, source_record_count)
    except Exception:
        if safe_max_rows <= 0:
            initial_total = 0
    with _LOOP_LOCK:
        if _LOOP_THREAD is not None and _LOOP_THREAD.is_alive() and not _LOOP_STOP.is_set():
            return dict(_LOOP_STATE)
        _LOOP_STOP.clear()
        _LOOP_STATE.update({
            "running": True,
            "state": "starting",
            "mode": "auto" if AUTO_LOOP_ENABLED and safe_interval == AUTO_LOOP_INTERVAL_SEC else "manual",
            "auto_start": AUTO_LOOP_ENABLED,
            "max_rows": safe_max_rows,
            "interval_sec": safe_interval,
            "timeout_sec": safe_timeout,
            "source_path": source_path,
            "source_record_count": source_record_count,
            "cycle": 0,
            "iterations": 0,
            "processed": 0,
            "total": initial_total,
            "last_error": "",
            "last_run_id": "",
            "last_record_count": 0,
            "next_run_at": "",
            "current_cycle_label": "",
            "cycle_started_at": "",
        })
        _LOOP_THREAD = threading.Thread(
            target=_scraper_loop_worker,
            kwargs={
                "max_rows": safe_max_rows,
                "interval_sec": safe_interval,
                "timeout_sec": safe_timeout,
                "xpath": xpath or DEFAULT_INVESTING_XPATH,
            },
            name="manual-stock-analysis-scraper-loop",
            daemon=True,
        )
        _LOOP_THREAD.start()
        return dict(_LOOP_STATE)


def stop_scraper_loop() -> dict[str, Any]:
    _LOOP_STOP.set()
    _loop_set(running=False, state="stopping", next_run_at="")
    return _loop_snapshot()


def auto_import_known_results() -> None:
    """Import local legacy result workbooks if they exist.

    This is intentionally best-effort. Production hosts without E: drives simply
    skip it, while the developer machine can immediately see the old output.
    """
    if not AUTO_IMPORT_KNOWN_RESULTS:
        return
    ensure_storage()
    for root in DEFAULT_RESULT_PATHS:
        if not root.exists() or not root.is_dir():
            continue
        for path in sorted(root.glob("*result*.xls*")):
            try:
                import_result_file(path)
            except Exception:
                continue


def list_runs() -> list[dict[str, Any]]:
    auto_import_known_results()
    runs: list[dict[str, Any]] = []
    active_run_id = _active_loop_run_id()
    for path in sorted(RUNS_DIR.glob("*.json"), reverse=True):
        run = _read_run(path)
        if not run:
            continue
        runs.append({
            "run_id": run.get("run_id"),
            "title": run.get("title"),
            "created_at": run.get("created_at"),
            "updated_at": run.get("updated_at") or run.get("created_at"),
            "cycle_date": run.get("cycle_date") or "",
            "cycle_number": run.get("cycle_number"),
            "cycle_label": run.get("cycle_label") or "",
            "status": _public_run_status(run, active_run_id),
            "record_count": run.get("record_count", len(run.get("records") or [])),
            "source_record_count": run.get("source_record_count") or run.get("record_count", len(run.get("records") or [])),
            "source_path": run.get("source_path"),
            "summary": run.get("summary") or {},
            "source_kind": run.get("source_kind"),
        })
    runs.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return runs


_prior_verdict_cache: dict[str, Any] = {}


def _record_key(record: dict[str, Any]) -> str:
    return _clean_text(record.get("source_url")) or _clean_text(record.get("ticker"))


_RUN_NAME_DATE = re.compile(r"^manual_scrape_(\d{4})(\d{2})(\d{2})_")


def _run_date_from_name(path: Path) -> str:
    """Cycle date straight from the filename, so same-day runs can be skipped
    without parsing a ~1.3MB JSON just to read one field."""
    match = _RUN_NAME_DATE.match(path.stem)
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}" if match else ""


def _run_cycle_date(run: dict[str, Any]) -> str:
    return _clean_text(run.get("cycle_date")) or _clean_text(run.get("created_at"))[:10]


def _prior_verdict_map(before_run_id: str, before_date: str) -> dict[str, str]:
    """key -> the newest real verdict recorded on a date earlier than ``before_date``.

    Only real verdicts count, so a stock sitting at 분석중 yesterday resolves to
    the last day it actually had an opinion. Cached because /runs/<id> is polled
    every second while a cycle streams; the runs scanned are finished, so the
    cache stays warm.
    """
    target = _clean_text(before_run_id)
    older: list[Path] = []
    for path in _run_files_newest_first():
        if path.stem == target:
            continue
        date = _run_date_from_name(path)
        # An unparseable name is a legacy import; keep it rather than guess.
        if date and before_date and date >= before_date:
            continue
        older.append(path)
        if len(older) >= _PRIOR_VERDICT_SCAN_DEPTH:
            break
    if not older:
        return {}

    signature = (target, before_date, tuple((p.name, int(p.stat().st_mtime)) for p in older))
    if _prior_verdict_cache.get("signature") == signature:
        return _prior_verdict_cache["data"]

    verdicts: dict[str, str] = {}
    for path in older:
        run = _read_run(path)
        if not run:
            continue
        for record in run.get("records") or []:
            label = _clean_text(record.get("result"))
            if label not in _SUCCESS_LABELS:
                continue
            key = _record_key(record)
            if key and key not in verdicts:
                verdicts[key] = label
        if len(verdicts) >= _PRIOR_VERDICT_ENOUGH:
            break
    _prior_verdict_cache.update({"signature": signature, "data": verdicts})
    return verdicts


def _is_upgrade_to_strong_buy(record: dict[str, Any], prior: dict[str, str]) -> bool:
    if _clean_text(record.get("result")) != STRONG_BUY_LABEL:
        return False
    previous = prior.get(_record_key(record))
    # No previous opinion means a new listing, not a switch.
    return bool(previous) and previous != STRONG_BUY_LABEL


def get_run(run_id: str, *, result: str = "all", q: str = "", live_only: bool = False) -> dict[str, Any]:
    run = _read_run(_run_path(run_id))
    if not run:
        raise FileNotFoundError(run_id)
    records = list(run.get("records") or [])
    prior = _prior_verdict_map(_clean_text(run.get("run_id")) or run_id, _run_cycle_date(run))
    # Counted over the whole run, like `summary`, so the chip does not change as
    # the user switches filters or types a query.
    upgraded_count = sum(1 for r in records if _is_upgrade_to_strong_buy(r, prior))
    if live_only:
        records = [
            r for r in records
            if r.get("scrape_state") in {"scraping", "completed", "error"}
        ]
    result = _clean_text(result)
    q = _clean_text(q).lower()
    if result == UPGRADE_FILTER:
        records = [r for r in records if _is_upgrade_to_strong_buy(r, prior)]
    elif result and result != "all":
        records = [r for r in records if r.get("result") == result]
    if q:
        records = [
            r for r in records
            if q in _clean_text(r.get("stock_name")).lower()
            or q in _clean_text(r.get("ticker")).lower()
            or q in _clean_text(r.get("industry")).lower()
        ]
    public_run = {k: v for k, v in run.items() if k != "records"}
    public_run["status"] = _public_run_status(run)
    return {
        **public_run,
        "records": records,
        "filtered_count": len(records),
        "upgraded_count": upgraded_count,
    }


def _compact_search_text(value: Any) -> str:
    return re.sub(r"\s+", "", _clean_text(value).lower())


def _record_matches_history_query(record: dict[str, Any], query: str) -> bool:
    query_text = _clean_text(query).lower()
    query_compact = _compact_search_text(query)
    query_digits = re.sub(r"\D+", "", query_text)
    if not query_compact and not query_digits:
        return False

    stock_name = _clean_text(record.get("stock_name")).lower()
    stock_compact = _compact_search_text(stock_name)
    ticker = _clean_text(record.get("ticker"))

    if query_digits and ticker and query_digits in ticker:
        return True
    if query_compact and stock_compact:
        return query_compact in stock_compact or stock_compact in query_compact
    return False


def _run_cycle_label(run: dict[str, Any]) -> str:
    if run.get("cycle_label"):
        return _clean_text(run.get("cycle_label"))
    if run.get("cycle_date") and run.get("cycle_number"):
        return f"{run.get('cycle_date')} - {run.get('cycle_number')}회차"
    return _clean_text(run.get("title")) or _clean_text(run.get("created_at")) or _clean_text(run.get("run_id"))


def search_stock_history(q: str, *, limit: int = 500) -> dict[str, Any]:
    """Return all saved manual-analysis records for a stock name or ticker.

    This deliberately searches across run files instead of only the selected
    run so users can audit how one ticker's recommendation changed by cycle.
    """
    ensure_storage()
    query = _clean_text(q)
    clean_limit = max(1, min(int(limit or 500), 5000))
    if not query:
        return {"query": "", "target": None, "items": [], "count": 0, "truncated": False}

    items: list[dict[str, Any]] = []
    target: dict[str, Any] | None = None
    active_run_id = _active_loop_run_id()
    for path in sorted(RUNS_DIR.glob("*.json"), reverse=True):
        run = _read_run(path)
        if not run:
            continue
        run_status = _public_run_status(run, active_run_id)
        for record in run.get("records") or []:
            if not _record_matches_history_query(record, query):
                continue
            if target is None:
                target = {
                    "stock_name": record.get("stock_name") or "",
                    "ticker": record.get("ticker") or "",
                    "market": record.get("market") or "",
                    "industry": record.get("industry") or "",
                }
            items.append({
                "run_id": run.get("run_id"),
                "run_title": run.get("title"),
                "cycle_label": _run_cycle_label(run),
                "cycle_date": run.get("cycle_date") or "",
                "cycle_number": run.get("cycle_number"),
                "run_status": run_status,
                "created_at": run.get("created_at") or "",
                "updated_at": run.get("updated_at") or run.get("created_at") or "",
                "rank": record.get("rank"),
                "stock_name": record.get("stock_name") or "",
                "ticker": record.get("ticker") or "",
                "market": record.get("market") or "",
                "industry": record.get("industry") or "",
                "result": record.get("result") or "미분류",
                "raw_result": record.get("raw_result") or "",
                "analyzed_at": record.get("analyzed_at") or run.get("updated_at") or run.get("created_at") or "",
                "scrape_state": record.get("scrape_state") or "",
                "technical_result": record.get("technical_result") or "",
                "analyst_sentiment": record.get("analyst_sentiment") or "",
                "target_price": record.get("target_price") or "",
                "upside_potential": record.get("upside_potential") or "",
                "source_url": record.get("source_url") or "",
            })

    items.sort(key=lambda item: item.get("analyzed_at") or item.get("updated_at") or item.get("created_at") or "", reverse=True)
    total = len(items)
    return {
        "query": query,
        "target": target,
        "items": items[:clean_limit],
        "count": total,
        "truncated": total > clean_limit,
    }


def run_to_excel_bytes(run_id: str, *, result: str = "all", q: str = "") -> tuple[bytes, str]:
    run = get_run(run_id, result=result, q=q)
    records = run.get("records") or []
    rows = [{
        "순번": r.get("rank"),
        "종목명": f"{r.get('stock_name')}{f' ({r.get('ticker')})' if r.get('ticker') else ''}",
        "시장": r.get("market"),
        "산업": r.get("industry"),
        "분석결과": r.get("result"),
        "원문결과": r.get("raw_result"),
        "분석일시": r.get("analyzed_at"),
        "URL": r.get("source_url"),
    } for r in records]
    output = BytesIO()
    pd.DataFrame(rows).to_excel(output, index=False, engine="openpyxl")
    filename = f"{run_id}_manual_stock_analysis.xlsx"
    return output.getvalue(), filename

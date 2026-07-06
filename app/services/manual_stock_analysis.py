"""Manual stock-analysis result service.

This module turns the legacy ``stock_info.py`` Excel workflow into a small,
explicit service surface.  It intentionally stores manual runs outside the
MiroFish alpha scanner artifacts so imported/scraped analyst labels do not
silently affect automated Top3 ranking.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from app.utils.atomic_json import write_json_atomic
from app.utils.paths import DATA_DIR, TICKER_MAP_PATH


SERVICE_ROOT = Path(DATA_DIR) / "manual_stock_analysis"
RUNS_DIR = SERVICE_ROOT / "runs"
UPLOADS_DIR = SERVICE_ROOT / "uploads"
STOCK_ANALYZER_CACHE_DIR = Path(DATA_DIR) / "stock_analyzer_cache"

DEFAULT_SOURCE_PATHS = [
    Path(os.getenv("MANUAL_STOCK_ANALYSIS_SOURCE_FILE", "")),
    SERVICE_ROOT / "stock_data.xlsx",
    Path("E:/다운로드/stock_data.xlsx"),
]
DEFAULT_RESULT_PATHS = [
    SERVICE_ROOT / "results",
    Path("E:/다운로드"),
]

RESULT_ORDER = ["적극 매수", "매수", "중립", "매도", "적극 매도", "분석중", "오류", "미분류"]
DEFAULT_INVESTING_XPATH = "//*[@id='pro-score-mobile']/div/div[2]/div[3]/div/div/div[1]/div"

_LOOP_LOCK = threading.RLock()
_LOOP_STOP = threading.Event()
_LOOP_THREAD: threading.Thread | None = None
_LOOP_STATE: dict[str, Any] = {
    "running": False,
    "state": "stopped",
    "max_rows": 20,
    "interval_sec": 900,
    "timeout_sec": 10,
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


def _ticker_lookup() -> dict[str, dict[str, str]]:
    try:
        df = pd.read_csv(TICKER_MAP_PATH, dtype=str, encoding="utf-8-sig").fillna("")
    except Exception:
        return {}
    lookup: dict[str, dict[str, str]] = {}
    for _, row in df.iterrows():
        name = _clean_text(row.get("name"))
        ticker = _clean_text(row.get("ticker")).zfill(6)
        market = _clean_text(row.get("market"))
        if name:
            lookup[name] = {"ticker": ticker, "market": market}
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
    return not text or text in {"미분류", "-", "N/A", "na", "None"}


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
    return RUNS_DIR / f"{run_id}.json"


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


def _read_run(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


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
        raise FileNotFoundError("stock_data.xlsx 원본을 찾을 수 없습니다.")
    records = _read_excel_records(source, pending=True)[: max(1, min(max_rows, 5000))]
    fingerprint = hashlib.sha1(f"{source.resolve()}:{_now()}:{len(records)}".encode("utf-8", "ignore")).hexdigest()[:16]
    run = {
        "run_id": f"manual_pending_{fingerprint}",
        "title": f"{datetime.now().strftime('%Y년%m월%d일')} - 수동 목록",
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
        raise FileNotFoundError("stock_data.xlsx 원본을 찾을 수 없습니다.")
    return source


def _create_selenium_driver():
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager
    except ImportError as exc:
        raise RuntimeError("Selenium 스크래퍼 실행에는 selenium, webdriver-manager 패키지가 필요합니다.") from exc

    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--window-size=375,812")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 Mobile/15E148 Safari/604.1"
    )
    chrome_options.add_experimental_option("excludeSwitches", ["enable-logging"])
    chrome_options.page_load_strategy = "eager"
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)


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

    driver.get(url)
    element = WebDriverWait(driver, timeout_sec).until(
        EC.presence_of_element_located((By.XPATH, xpath))
    )
    visible_text = ""
    try:
        visible_text = driver.execute_script("return document.body ? document.body.innerText : '';") or ""
    except Exception:
        visible_text = ""
    return {
        "result": _clean_text(element.text),
        "industry": _extract_industry_from_text(visible_text),
    }


def _build_scrape_run(
    *,
    run_id: str,
    source: Path,
    records: list[dict[str, Any]],
    xpath: str,
    max_rows: int,
    timeout_sec: int,
    status: str,
    created_at: str,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "title": f"{datetime.now().strftime('%Y년%m월%d일 %H:%M:%S')} - 실시간 스크래퍼 {max_rows}건",
        "source_kind": "selenium_scrape",
        "source_path": str(source),
        "source_fingerprint": _file_fingerprint(source),
        "created_at": created_at,
        "updated_at": _now(),
        "status": status,
        "record_count": len(records),
        "summary": _summary(records),
        "records": records,
        "scraper": {
            "xpath": xpath,
            "max_rows": max_rows,
            "timeout_sec": timeout_sec,
        },
    }


def _persist_scrape_run(run: dict[str, Any], *, records: list[dict[str, Any]], status: str) -> dict[str, Any]:
    run["records"] = records
    run["record_count"] = len(records)
    run["summary"] = _summary(records)
    run["updated_at"] = _now()
    run["status"] = status
    return _write_run(run)


def scrape_source_run(
    *,
    max_rows: int = 20,
    xpath: str = DEFAULT_INVESTING_XPATH,
    timeout_sec: int = 10,
    delay_sec: float = 0.15,
    progress_callback: Callable[[int, int, dict[str, Any]], None] | None = None,
    run_id: str | None = None,
    persist_progress: bool = False,
) -> dict[str, Any]:
    """Run the legacy Investing.com-style scraper and persist a manual run.

    This is synchronous and intentionally capped because it opens a browser and
    talks to a third-party web page.  Large all-market batches should be moved
    to a background worker before production use.
    """
    source = _find_source_workbook()
    safe_max_rows = max(1, min(int(max_rows or 20), 200))
    timeout_sec = max(3, min(int(timeout_sec or 10), 30))
    created_at = _now()
    fingerprint = hashlib.sha1(f"{source.resolve()}:{created_at}:{safe_max_rows}".encode("utf-8", "ignore")).hexdigest()[:16]
    current_run_id = run_id or f"manual_scrape_{fingerprint}"
    records = _read_excel_records(source, pending=True)[:safe_max_rows]
    run = _build_scrape_run(
        run_id=current_run_id,
        source=source,
        records=records,
        xpath=xpath,
        max_rows=safe_max_rows,
        timeout_sec=timeout_sec,
        status="running",
        created_at=created_at,
    )
    if persist_progress:
        _write_run(run)

    driver = None
    try:
        driver = _create_selenium_driver()
        total = len(records)
        for index, record in enumerate(records, start=1):
            url = _clean_text(record.get("source_url"))
            if not url:
                record["raw_result"] = "오류"
                record["result"] = "오류"
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
                scraped_fields = _scrape_page_fields(driver, url, xpath, timeout_sec=timeout_sec)
                scraped = scraped_fields.get("result", "")
                record["raw_result"] = scraped or "오류"
                record["result"] = _normalise_label(scraped)
                scraped_industry = scraped_fields.get("industry", "")
                if not _is_missing_industry(scraped_industry):
                    record["industry"] = scraped_industry
            except Exception as exc:
                record["raw_result"] = "오류"
                record["result"] = "오류"
                record["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
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
            try:
                driver.quit()
            except Exception:
                pass

    return _persist_scrape_run(run, records=records, status="completed")


def _scraper_loop_worker(
    *,
    max_rows: int,
    interval_sec: int,
    timeout_sec: int,
    xpath: str,
) -> None:
    while not _LOOP_STOP.is_set():
        started_at = _now()
        live_run_hash = hashlib.sha1(f"{started_at}:{max_rows}:{time.time()}".encode("utf-8", "ignore")).hexdigest()[:12]
        live_run_id = f"manual_scrape_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{live_run_hash}"
        _loop_set(
            running=True,
            state="scraping",
            max_rows=max_rows,
            interval_sec=interval_sec,
            timeout_sec=timeout_sec,
            processed=0,
            total=max_rows,
            current_rank=None,
            current_stock="",
            current_industry="",
            current_result="",
            last_run_id=live_run_id,
            last_record_count=0,
            last_started_at=started_at,
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

        try:
            run = scrape_source_run(
                max_rows=max_rows,
                xpath=xpath,
                timeout_sec=timeout_sec,
                progress_callback=on_progress,
                run_id=live_run_id,
                persist_progress=True,
            )
            with _LOOP_LOCK:
                iterations = int(_LOOP_STATE.get("iterations") or 0) + 1
            _loop_set(
                state="waiting",
                iterations=iterations,
                processed=run.get("record_count", 0),
                total=run.get("record_count", max_rows),
                last_run_id=run.get("run_id") or "",
                last_record_count=run.get("record_count", 0),
                last_finished_at=_now(),
                last_error="",
            )
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
        next_run_at = (datetime.now() + timedelta(seconds=interval_sec)).strftime("%Y-%m-%d %H:%M:%S")
        _loop_set(next_run_at=next_run_at)
        _LOOP_STOP.wait(interval_sec)

    _loop_set(running=False, state="stopped", next_run_at="")


def get_scraper_loop_status() -> dict[str, Any]:
    return _loop_snapshot()


def start_scraper_loop(
    *,
    max_rows: int = 20,
    interval_sec: int = 900,
    timeout_sec: int = 10,
    xpath: str = DEFAULT_INVESTING_XPATH,
) -> dict[str, Any]:
    global _LOOP_THREAD
    safe_max_rows = max(1, min(int(max_rows or 20), 200))
    safe_interval = max(60, min(int(interval_sec or 900), 86400))
    safe_timeout = max(3, min(int(timeout_sec or 10), 30))
    with _LOOP_LOCK:
        if _LOOP_THREAD is not None and _LOOP_THREAD.is_alive() and not _LOOP_STOP.is_set():
            return dict(_LOOP_STATE)
        _LOOP_STOP.clear()
        _LOOP_STATE.update({
            "running": True,
            "state": "starting",
            "max_rows": safe_max_rows,
            "interval_sec": safe_interval,
            "timeout_sec": safe_timeout,
            "processed": 0,
            "total": safe_max_rows,
            "last_error": "",
            "next_run_at": "",
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
    for path in sorted(RUNS_DIR.glob("*.json"), reverse=True):
        run = _read_run(path)
        if not run:
            continue
        runs.append({
            "run_id": run.get("run_id"),
            "title": run.get("title"),
            "created_at": run.get("created_at"),
            "record_count": run.get("record_count", len(run.get("records") or [])),
            "summary": run.get("summary") or {},
            "source_kind": run.get("source_kind"),
        })
    runs.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return runs


def get_run(run_id: str, *, result: str = "all", q: str = "") -> dict[str, Any]:
    run = _read_run(_run_path(run_id))
    if not run:
        raise FileNotFoundError(run_id)
    records = list(run.get("records") or [])
    result = _clean_text(result)
    q = _clean_text(q).lower()
    if result and result != "all":
        records = [r for r in records if r.get("result") == result]
    if q:
        records = [
            r for r in records
            if q in _clean_text(r.get("stock_name")).lower()
            or q in _clean_text(r.get("ticker")).lower()
            or q in _clean_text(r.get("industry")).lower()
        ]
    return {
        **{k: v for k, v in run.items() if k != "records"},
        "records": records,
        "filtered_count": len(records),
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

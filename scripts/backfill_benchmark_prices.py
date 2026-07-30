"""One-off historical backfill of the benchmark index proxies.

``update_daily_prices`` only collects forward from the CSV's last date, so the
KODEX proxies enter daily_prices.csv from the day they joined the collection
universe. Picks recorded before that have no same-date index close and their
excess return stays null. This script fills the gap and is safe to re-run: it
appends only (ticker, date) pairs the file does not already contain.

    python scripts/backfill_benchmark_prices.py --start 2024-01-02
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CSV_PATH = ROOT / "data" / "daily_prices.csv"
FIELDNAMES = [
    "ticker", "date", "name", "current_price", "change", "change_rate",
    "high", "low", "open", "volume", "update_time",
]


def existing_dates(csv_path: str, tickers: set[str]) -> dict[str, set[str]]:
    """Dates already present per benchmark ticker."""
    found: dict[str, set[str]] = {ticker: set() for ticker in tickers}
    if not os.path.exists(csv_path):
        return found
    with open(csv_path, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            ticker = (row.get("ticker") or "").strip()
            if ticker in found:
                date = (row.get("date") or "").strip()
                if date:
                    found[ticker].add(date)
    return found


def append_missing_rows(
    csv_path: str,
    fetched: dict[str, list[dict]],
    *,
    names: dict[str, str],
    now_str: str,
) -> int:
    """Append sessions the file lacks. Returns the number of rows written."""
    present = existing_dates(csv_path, set(fetched))
    rows = []
    for ticker, sessions in fetched.items():
        for session in sessions:
            date = str(session.get("date") or "").strip()
            close = _number(session.get("close"))
            if not date or close <= 0 or date in present.get(ticker, set()):
                continue
            open_price = _number(session.get("open")) or close
            rows.append({
                "ticker": ticker,
                "date": date,
                "name": names.get(ticker, ticker),
                "current_price": close,
                "change": 0,
                "change_rate": 0,
                "high": _number(session.get("high")) or close,
                "low": _number(session.get("low")) or close,
                "open": open_price,
                "volume": int(_number(session.get("volume"))),
                "update_time": now_str,
            })

    if not rows:
        return 0

    rows.sort(key=lambda row: (row["ticker"], row["date"]))
    write_header = not os.path.exists(csv_path) or os.path.getsize(csv_path) == 0
    with open(csv_path, "a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def fetch_benchmarks(start: str, end: str) -> dict[str, list[dict]]:
    import FinanceDataReader as fdr

    from app.services.mirofish.goodrich_ledger import BENCHMARK_TICKERS

    fetched: dict[str, list[dict]] = {}
    for ticker in BENCHMARK_TICKERS:
        frame = fdr.DataReader(ticker, start, end)
        sessions = []
        for index, row in frame.iterrows():
            sessions.append({
                "date": index.strftime("%Y-%m-%d"),
                "close": row.get("Close"),
                "open": row.get("Open"),
                "high": row.get("High"),
                "low": row.get("Low"),
                "volume": row.get("Volume"),
            })
        fetched[ticker] = sessions
    return fetched


def _number(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2024-01-02")
    parser.add_argument("--end", default=datetime.now().strftime("%Y-%m-%d"))
    args = parser.parse_args()

    from app.services.mirofish.goodrich_ledger import BENCHMARK_TICKERS

    fetched = fetch_benchmarks(args.start, args.end)
    written = append_missing_rows(
        str(CSV_PATH),
        fetched,
        names=dict(BENCHMARK_TICKERS),
        now_str=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    for ticker, sessions in fetched.items():
        print(f"{ticker}: fetched {len(sessions)} sessions")
    print(f"appended {written} new rows to {CSV_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

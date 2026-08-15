# -*- coding: utf-8 -*-
"""Gemini Vision 차트 분석으로 BUY 후보 N종목을 선별해 텔레그램으로 보낸다.

main_kr.py 는 고정된 100종목을 분석해 BUY/HOLD/SELL 을 집계하는 도구다.
이 스크립트는 목적이 다르다 — **BUY 판정 종목을 목표 개수만큼 채우는 것**이
목표라, 시총 상위부터 배치 단위로 훑으며 목표를 채울 때까지 유니버스를 넓힌다.

가격은 로컬 `data/daily_prices.csv` 를 쓴다. yfinance 로 400종목을 받으려다
16분에 1종목까지 떨어지는 스로틀링을 맞았고(2026-08-15), 로컬 CSV 는 같은
금요일 종가까지 담고 있으면서 네트워크를 전혀 타지 않는다.

    python scripts/screen_buy_candidates.py                  # BUY 100종목 채울 때까지
    python scripts/screen_buy_candidates.py --target 50
    python scripts/screen_buy_candidates.py --no-send        # 발송 없이 결과만 저장
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import datetime
import sys
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import main_kr  # noqa: E402  (경로 삽입 후 임포트)

PRICES_CSV = BASE_DIR / "data" / "daily_prices.csv"
OUT_CSV = BASE_DIR / "data" / "buy_candidates_kr.csv"
MIN_ROWS = 60          # 캔들 60봉 미만은 차트 판독이 무의미
CHART_DAYS = 250       # 약 1년치 거래일


def load_prices() -> pd.DataFrame:
    """로컬 일봉 CSV → ticker 별 OHLCV 프레임."""
    df = pd.read_csv(
        PRICES_CSV,
        dtype={"ticker": str},
        usecols=["ticker", "date", "open", "high", "low", "current_price", "volume"],
    )
    df = df.rename(columns={
        "open": "Open", "high": "High", "low": "Low",
        "current_price": "Close", "volume": "Volume",
    })
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "Close"])
    return df.sort_values("date")


def build_universe(size: int) -> list[tuple[str, str, str]]:
    """시총 상위 보통주 (code, ticker, name). 우선주·스팩 제외."""
    import FinanceDataReader as fdr

    krx = fdr.StockListing("KRX")
    krx = krx[krx["Market"].isin(["KOSPI", "KOSDAQ", "KOSDAQ GLOBAL"])]
    common = krx[
        krx["Code"].str.fullmatch(r"\d{6}")
        & krx["Code"].str.endswith("0")
        & ~krx["Name"].str.contains("스팩")
    ].nlargest(size, "Marcap")
    return [
        (r.Code, f"{r.Code}.{'KS' if r.Market == 'KOSPI' else 'KQ'}", r.Name)
        for r in common.itertuples()
    ]


async def analyze_batch(batch, prices_by_ticker, concurrency: int) -> list[dict]:
    from google import genai

    charts: list[tuple[str, str, str]] = []
    for code, ticker, name in batch:
        frame = prices_by_ticker.get(code)
        if frame is None or len(frame) < MIN_ROWS:
            continue
        frame = frame.tail(CHART_DAYS).set_index("date")[["Open", "High", "Low", "Close", "Volume"]]
        path = main_kr.render_chart(frame, ticker, name)
        if path:
            charts.append((ticker, name, path))
    print(f"  차트 {len(charts)}/{len(batch)}", flush=True)
    if not charts:
        return []

    client = genai.Client(api_key=main_kr.API_KEY)
    semaphore = asyncio.Semaphore(concurrency)
    results = await asyncio.gather(
        *(main_kr.analyze_chart(client, t, n, p, semaphore) for t, n, p in charts),
        return_exceptions=True,
    )
    return [r for r in results if isinstance(r, dict)]


def format_message(picks: list[dict], analyzed: int, scanned: int) -> str:
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    head = (
        f"<b>🟢 AI 차트 매수 후보 {len(picks)}종목</b>\n"
        f"시총 상위 {scanned}종목 중 {analyzed}종목 분석 · {stamp}"
    )
    blocks = [head]
    rows = [
        f"  {i}. <b>{p['종목명']}</b> ({p['종목코드']}) conf={p.get('confidence', '?')}"
        for i, p in enumerate(picks, 1)
    ]
    for i in range(0, len(rows), 20):
        blocks.append("\n".join(rows[i:i + 20]))
    blocks.append("<i>기술적 차트 분석 결과이며 투자 판단의 근거가 아닙니다.</i>")
    return "\n\n".join(blocks)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=100, help="선별할 BUY 종목 수")
    ap.add_argument("--batch", type=int, default=200, help="한 번에 분석할 종목 수")
    ap.add_argument("--max-universe", type=int, default=1200, help="최대 탐색 범위")
    ap.add_argument("--concurrency", type=int, default=10)
    ap.add_argument("--no-send", action="store_true")
    ap.add_argument("--channel", action="store_true", help="채널에도 발송 (기본: 개인 봇만)")
    args = ap.parse_args()

    universe = build_universe(args.max_universe)
    prices = load_prices()
    prices_by_ticker = {code: g for code, g in prices.groupby("ticker")}
    print(f"유니버스 {len(universe)}종목 · 가격데이터 {len(prices_by_ticker)}종목 "
          f"(최신 {prices['date'].max():%Y-%m-%d})", flush=True)

    main_kr.reset_vision_health()
    buys: list[dict] = []
    analyzed = 0
    scanned = 0

    # 목표 개수를 채울 때까지 시총 순으로 배치를 넓혀 간다.
    for start in range(0, len(universe), args.batch):
        batch = universe[start:start + args.batch]
        print(f"[배치 {start + 1}~{start + len(batch)}] 분석 시작", flush=True)
        results = asyncio.run(analyze_batch(batch, prices_by_ticker, args.concurrency))
        analyzed += len(results)
        scanned += len(batch)
        buys += [r for r in results if str(r.get("signal", "")).upper() == "BUY"]
        print(f"  누적: 분석 {analyzed} · BUY {len(buys)}/{args.target}", flush=True)
        if len(buys) >= args.target:
            break

    buys.sort(key=lambda r: int(r.get("confidence") or 0), reverse=True)
    picks = buys[:args.target]
    print(f"선별 완료: BUY {len(buys)}종목 → 상위 {len(picks)}종목", flush=True)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["종목명", "종목코드", "시장", "signal",
                                          "confidence", "ma_status", "rsi_zone",
                                          "volume_trend"], extrasaction="ignore")
        w.writeheader()
        w.writerows(picks)
    print(f"저장: {OUT_CSV}", flush=True)

    if not picks:
        print("BUY 후보가 없어 발송하지 않습니다.", flush=True)
        return 0
    if len(picks) < args.target:
        print(f"경고: 목표 {args.target}종목에 미달 ({len(picks)}종목). "
              f"--max-universe 를 늘려 재실행하세요.", flush=True)

    msg = format_message(picks, analyzed, scanned)
    if args.no_send:
        print(msg)
        return 0

    from scheduler import send_telegram_long
    print("sent:", send_telegram_long(msg, channel=args.channel), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

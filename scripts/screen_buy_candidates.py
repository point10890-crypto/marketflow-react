# -*- coding: utf-8 -*-
"""로컬 OHLCV 사전순위 후 Gemini Vision으로 BUY 후보를 선별한다.

최대 1,200종목은 로컬 가격·거래량으로만 순위화하고, 상위 20종목만 유료
Vision 경로에 보낸다. 결과는 최대 10종목이다. CLI나 환경변수가 더 큰 값을
요청해도 이 비용 경계는 늘어나지 않는다.

가격은 로컬 `data/daily_prices.csv` 를 쓴다. yfinance 로 400종목을 받으려다
16분에 1종목까지 떨어지는 스로틀링을 맞았고(2026-08-15), 로컬 CSV 는 같은
금요일 종가까지 담고 있으면서 네트워크를 전혀 타지 않는다.

    python scripts/screen_buy_candidates.py                  # 상위 20 분석, BUY 최대 10
    python scripts/screen_buy_candidates.py --target 5
    python scripts/screen_buy_candidates.py --no-send        # 발송 없이 결과만 저장
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import datetime
import json
import math
import os
import re
import sys
from collections import Counter
from pathlib import Path
from uuid import uuid4

import pandas as pd
from filelock import FileLock

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import main_kr  # noqa: E402  (경로 삽입 후 임포트)
from app.utils.atomic_json import write_json_atomic  # noqa: E402

PRICES_CSV = BASE_DIR / "data" / "daily_prices.csv"
TICKER_MAP_CSV = BASE_DIR / "data" / "ticker_to_yahoo_map.csv"
OUT_CSV = BASE_DIR / "data" / "buy_candidates_kr.csv"
VISION_BUDGET_STATE = BASE_DIR / "data" / "runtime" / "buy_screen_vision_budget.json"
MIN_ROWS = 60          # 캔들 60봉 미만은 차트 판독이 무의미
CHART_DAYS = 250       # 약 1년치 거래일
MAX_UNIVERSE = 1200
MAX_VISION_CALLS = 20
MAX_OUTPUT_PICKS = 10


def _bounded_positive(value: object, *, default: int, ceiling: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(ceiling, parsed))


def bounded_run_limits(*, target: object, vision_calls: object) -> tuple[int, int]:
    """Return immutable cost/output limits regardless of CLI or env input."""
    bounded_vision = _bounded_positive(
        vision_calls,
        default=MAX_VISION_CALLS,
        ceiling=MAX_VISION_CALLS,
    )
    bounded_target = _bounded_positive(
        target,
        default=MAX_OUTPUT_PICKS,
        ceiling=MAX_OUTPUT_PICKS,
    )
    return min(bounded_target, bounded_vision), bounded_vision


def load_prices() -> pd.DataFrame:
    """로컬 일봉 CSV → ticker 별 OHLCV 프레임."""
    df = pd.read_csv(
        PRICES_CSV,
        dtype={"ticker": str},
        usecols=[
            "ticker", "date", "name", "open", "high", "low",
            "current_price", "volume",
        ],
    )
    df = df.rename(columns={
        "open": "Open", "high": "High", "low": "Low",
        "current_price": "Close", "volume": "Volume",
    })
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "Close"])
    return df.sort_values("date")


def _build_local_universe(
    size: int,
    prices: pd.DataFrame | None,
) -> list[tuple[str, str, str]]:
    """Use the maintained local market map when the live KRX list is unavailable."""
    mapping = pd.read_csv(TICKER_MAP_CSV, dtype={"ticker": str})
    required = {"ticker", "market"}
    if not required.issubset(mapping.columns):
        raise ValueError("local ticker map is missing ticker/market columns")
    names: dict[str, str] = {}
    if prices is not None and {"ticker", "date", "name"}.issubset(prices.columns):
        latest_names = (
            prices.dropna(subset=["ticker", "name"])
            .sort_values("date")
            .drop_duplicates("ticker", keep="last")
        )
        names = dict(zip(latest_names["ticker"].astype(str), latest_names["name"].astype(str)))

    rows: list[tuple[str, str, str]] = []
    for row in mapping.itertuples(index=False):
        code = str(row.ticker)
        market = str(row.market).upper()
        name = names.get(code) or str(getattr(row, "name", code))
        if (
            not re.fullmatch(r"\d{6}", code)
            or not code.endswith("0")
            or market not in {"KOSPI", "KOSDAQ", "KOSDAQ GLOBAL"}
            or "스팩" in name
        ):
            continue
        suffix = "KS" if market == "KOSPI" else "KQ"
        rows.append((code, f"{code}.{suffix}", name))
        if len(rows) >= size:
            break
    return rows


def build_universe(
    size: int,
    *,
    prices: pd.DataFrame | None = None,
) -> list[tuple[str, str, str]]:
    """시총 상위 보통주; live KRX 실패 시 로컬 매핑으로 자동 전환."""
    try:
        import FinanceDataReader as fdr

        krx = fdr.StockListing("KRX")
        required = {"Market", "Code", "Name", "Marcap"}
        if krx is None or krx.empty or not required.issubset(krx.columns):
            raise ValueError("live KRX listing is empty or incomplete")
        krx = krx.copy()
        krx["Code"] = krx["Code"].astype(str)
        krx = krx[krx["Market"].isin(["KOSPI", "KOSDAQ", "KOSDAQ GLOBAL"])]
        common = krx[
            krx["Code"].str.fullmatch(r"\d{6}")
            & krx["Code"].str.endswith("0")
            & ~krx["Name"].astype(str).str.contains("스팩")
        ].nlargest(size, "Marcap")
        if common.empty:
            raise ValueError("live KRX listing has no eligible common stocks")
        return [
            (r.Code, f"{r.Code}.{'KS' if r.Market == 'KOSPI' else 'KQ'}", r.Name)
            for r in common.itertuples()
        ]
    except Exception as exc:
        print(
            f"KRX 실시간 종목목록 실패({type(exc).__name__}) — 로컬 매핑으로 전환",
            flush=True,
        )
        return _build_local_universe(size, prices)


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _pct_change(values: pd.Series, periods: int) -> float:
    if len(values) <= periods:
        return 0.0
    previous = float(values.iloc[-periods - 1])
    latest = float(values.iloc[-1])
    if previous <= 0:
        return 0.0
    return ((latest / previous) - 1.0) * 100.0


def _clean_price_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    required = ["date", "Open", "High", "Low", "Close", "Volume"]
    if frame is None or not set(required).issubset(frame.columns):
        return pd.DataFrame(columns=required)
    data = frame[required].copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    numeric = ["Open", "High", "Low", "Close", "Volume"]
    for column in numeric:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    # mergesort makes duplicate-date keep-last behavior reproducible.
    data = data.sort_values("date", kind="mergesort")
    data = data.drop_duplicates(subset=["date"], keep="last")
    data = data.dropna(subset=required)
    if data.empty:
        return data
    finite = data[numeric].apply(lambda series: series.map(math.isfinite)).all(axis=1)
    return data.loc[
        finite
        & (data[["Open", "High", "Low", "Close"]] > 0).all(axis=1)
        & (data["Volume"] >= 0)
    ]


def prefilter_as_of(
    universe: list[tuple[str, str, str]],
    prices_by_ticker: dict[str, pd.DataFrame],
) -> pd.Timestamp | None:
    """Choose the modal complete latest date so one future row cannot poison all data."""
    latest_days: Counter[pd.Timestamp] = Counter()
    for code, _ticker, _name in universe:
        data = _clean_price_frame(prices_by_ticker.get(code))
        if len(data) < MIN_ROWS:
            continue
        latest_days[pd.Timestamp(data["date"].iloc[-1]).normalize()] += 1
    if not latest_days:
        return None
    # Highest population wins; a tie chooses the latest date deterministically.
    return max(latest_days, key=lambda day: (latest_days[day], day))


def _kst_today() -> datetime.date:
    kst = datetime.timezone(datetime.timedelta(hours=9))
    return datetime.datetime.now(kst).date()


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "y", "on"}


def price_data_is_fresh(
    as_of: pd.Timestamp | None,
    *,
    today: datetime.date | None = None,
) -> bool:
    """Fail closed on stale/future data unless the operator explicitly overrides."""
    if as_of is None:
        return False
    data_day = pd.Timestamp(as_of).date()
    current_day = today or _kst_today()
    if not _truthy_env("ALLOW_KR_NON_TRADING_RUN"):
        return data_day == current_day
    if data_day > current_day:
        return False
    # The override permits a holiday run, not arbitrary stale data. Require the
    # most recent KRX trading day, bounded to the preceding ten calendar days.
    from app.services.kis_screener import _is_kr_trading_day

    expected_day = current_day
    for _ in range(10):
        probe = datetime.datetime.combine(expected_day, datetime.time.min)
        if expected_day.weekday() < 5 and _is_kr_trading_day(probe):
            return data_day == expected_day
        expected_day -= datetime.timedelta(days=1)
    return False


def reserve_daily_vision_calls(
    requested: object,
    *,
    day: datetime.date | None = None,
    state_path: Path = VISION_BUDGET_STATE,
    run_id: str | None = None,
    daily_limit: object = MAX_VISION_CALLS,
) -> int:
    """Atomically reserve from the conservative 20-call KST daily budget.

    Reservations are not refunded. If a process dies after reservation, a later
    catch-up cannot spend the same allowance again.
    """
    requested_calls = _bounded_positive(
        requested,
        default=MAX_VISION_CALLS,
        ceiling=MAX_VISION_CALLS,
    )
    requested_limit = _bounded_positive(
        daily_limit,
        default=MAX_VISION_CALLS,
        ceiling=MAX_VISION_CALLS,
    )
    effective_day = day or _kst_today()
    state_path = Path(state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(state_path) + ".lock", timeout=10)
    with lock:
        state: dict[str, object] = {}
        if state_path.exists():
            try:
                loaded = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError) as exc:
                raise RuntimeError("vision budget state is unreadable") from exc
            if not isinstance(loaded, dict):
                raise RuntimeError("vision budget state is invalid")
            state = loaded

        state_day = str(state.get("date") or "")
        day_text = effective_day.isoformat()
        if state_day > day_text:
            raise RuntimeError("vision budget state date is in the future")
        if state_day == day_text:
            try:
                used = int(state.get("reserved_calls") or 0)
            except (TypeError, ValueError) as exc:
                raise RuntimeError("vision budget reserved_calls is invalid") from exc
            if used < 0 or used > MAX_VISION_CALLS:
                raise RuntimeError("vision budget reserved_calls is out of bounds")
            try:
                stored_limit = int(state.get("hard_cap") or MAX_VISION_CALLS)
            except (TypeError, ValueError) as exc:
                raise RuntimeError("vision budget hard_cap is invalid") from exc
            if stored_limit < 1 or stored_limit > MAX_VISION_CALLS:
                raise RuntimeError("vision budget hard_cap is out of bounds")
            effective_limit = min(requested_limit, stored_limit)
            completed = state.get("completed") is True
        else:
            used = 0
            effective_limit = requested_limit
            completed = False

        granted = (
            0
            if completed
            else min(requested_calls, max(0, effective_limit - used))
        )
        write_json_atomic(
            str(state_path),
            {
                "schema_version": 1,
                "date": day_text,
                "reserved_calls": used + granted,
                "hard_cap": effective_limit,
                "last_run_id": run_id,
                "completed": completed,
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            },
        )
        return granted


def daily_vision_run_completed(
    *,
    day: datetime.date | None = None,
    state_path: Path = VISION_BUDGET_STATE,
) -> bool:
    effective_day = day or _kst_today()
    state_path = Path(state_path)
    lock = FileLock(str(state_path) + ".lock", timeout=10)
    with lock:
        if not state_path.exists():
            return False
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise RuntimeError("vision budget state is unreadable") from exc
        return (
            isinstance(state, dict)
            and state.get("date") == effective_day.isoformat()
            and state.get("completed") is True
        )


def mark_daily_vision_run_completed(
    *,
    run_id: str,
    day: datetime.date | None = None,
    state_path: Path = VISION_BUDGET_STATE,
) -> None:
    effective_day = day or _kst_today()
    state_path = Path(state_path)
    lock = FileLock(str(state_path) + ".lock", timeout=10)
    with lock:
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise RuntimeError("vision budget state is unreadable") from exc
        if not isinstance(state, dict) or state.get("date") != effective_day.isoformat():
            raise RuntimeError("vision budget state does not match the active day")
        state.update({
            "completed": True,
            "completed_run_id": run_id,
            "completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        })
        write_json_atomic(str(state_path), state)


def _prefilter_metrics(
    frame: pd.DataFrame,
    *,
    as_of: pd.Timestamp,
) -> dict[str, float] | None:
    """Score trend/momentum/volume/liquidity locally; never emit a BUY signal."""
    data = _clean_price_frame(frame)
    if len(data) < MIN_ROWS:
        return None
    if pd.Timestamp(data["date"].iloc[-1]).normalize() != pd.Timestamp(as_of).normalize():
        return None

    recent = data.tail(CHART_DAYS)
    closes = recent["Close"].astype(float)
    volumes = recent["Volume"].astype(float)
    current = float(closes.iloc[-1])
    ma5 = float(closes.tail(5).mean())
    ma20 = float(closes.tail(20).mean())
    ma60 = float(closes.tail(60).mean())
    return_5d = _pct_change(closes, 5)
    return_20d = _pct_change(closes, 20)
    daily_returns = closes.pct_change().dropna().tail(20) * 100.0
    volatility = float(daily_returns.std(ddof=0)) if not daily_returns.empty else 0.0
    recent_high = float(closes.tail(20).max())
    drawdown = ((recent_high - current) / recent_high * 100.0) if recent_high else 0.0
    positive_ratio = float((daily_returns > 0).mean()) if not daily_returns.empty else 0.0

    previous_volume = float(volumes.iloc[-25:-5].mean()) if len(volumes) >= 25 else 0.0
    current_volume = float(volumes.tail(5).mean())
    volume_ratio = current_volume / previous_volume if previous_volume > 0 else 0.0
    avg_trading_value = float((closes.tail(20) * volumes.tail(20)).mean())
    liquidity_score = _clip((math.log10(max(avg_trading_value, 1.0)) - 7.0) * 2.5, 0.0, 10.0)

    trend_score = 0.0
    trend_score += 14.0 if current > ma20 else 0.0
    trend_score += 11.0 if ma5 > ma20 else 0.0
    trend_score += 15.0 if ma20 > ma60 else 0.0
    trend_score += _clip((positive_ratio - 0.45) * 20.0, 0.0, 5.0)
    momentum_score = (
        _clip(return_5d, 0.0, 10.0)
        + _clip(return_20d * 0.75, 0.0, 15.0)
    )
    volume_score = _clip((volume_ratio - 0.8) * 12.5, 0.0, 15.0)
    over_ma20 = ((current / ma20) - 1.0) * 100.0 if ma20 else 0.0
    risk_penalty = (
        _clip(volatility - 4.0, 0.0, 10.0) * 1.5
        + _clip(drawdown - 5.0, 0.0, 20.0) * 0.75
        + _clip(over_ma20 - 25.0, 0.0, 20.0)
        + _clip(-return_20d, 0.0, 20.0)
    )
    return {
        "score": round(
            trend_score + momentum_score + volume_score + liquidity_score - risk_penalty,
            6,
        ),
        "trend_score": round(trend_score, 6),
        "momentum_score": round(momentum_score, 6),
        "volume_score": round(volume_score, 6),
        "liquidity_score": round(liquidity_score, 6),
        "risk_penalty": round(risk_penalty, 6),
    }


def rank_prefilter_candidates(
    universe: list[tuple[str, str, str]],
    prices_by_ticker: dict[str, pd.DataFrame],
    *,
    limit: int,
    as_of: pd.Timestamp | None = None,
) -> list[tuple[str, str, str]]:
    """Deterministically rank the local universe before any paid API call."""
    bounded_limit = _bounded_positive(
        limit,
        default=MAX_VISION_CALLS,
        ceiling=MAX_VISION_CALLS,
    )
    if as_of is None:
        as_of = prefilter_as_of(universe, prices_by_ticker)
        if as_of is None:
            return []

    ranked: list[tuple[float, float, int, str, tuple[str, str, str]]] = []
    for market_cap_rank, candidate in enumerate(universe, 1):
        code, _ticker, _name = candidate
        metrics = _prefilter_metrics(prices_by_ticker.get(code), as_of=pd.Timestamp(as_of))
        if metrics is None:
            continue
        ranked.append((
            -metrics["score"],
            -metrics["liquidity_score"],
            market_cap_rank,
            code,
            candidate,
        ))
    ranked.sort(key=lambda item: item[:4])
    return [item[-1] for item in ranked[:bounded_limit]]


async def analyze_batch(
    batch,
    prices_by_ticker,
    concurrency: int,
    *,
    run_id: str,
    rank_offset: int = 0,
    vision_limit: int = MAX_VISION_CALLS,
) -> list[dict]:
    effective_limit = _bounded_positive(
        vision_limit,
        default=MAX_VISION_CALLS,
        ceiling=MAX_VISION_CALLS,
    )
    remaining = max(0, effective_limit - max(0, rank_offset))
    batch = list(batch)[:remaining]
    charts: list[tuple[int, str, str, str]] = []
    for candidate_rank, (code, ticker, name) in enumerate(
        batch,
        start=rank_offset + 1,
    ):
        frame = _clean_price_frame(prices_by_ticker.get(code))
        if len(frame) < MIN_ROWS:
            continue
        frame = frame.tail(CHART_DAYS).set_index("date")[["Open", "High", "Low", "Close", "Volume"]]
        path = main_kr.render_chart(frame, ticker, name)
        if path:
            charts.append((candidate_rank, ticker, name, path))
    print(f"  차트 {len(charts)}/{len(batch)}", flush=True)
    if not charts:
        return []

    semaphore = asyncio.Semaphore(concurrency)
    results = await asyncio.gather(
        *(
            main_kr.analyze_chart(
                None,
                ticker,
                name,
                path,
                semaphore,
                run_id=run_id,
                candidate_rank=candidate_rank,
                # Count provider HTTP attempts, not merely logical symbols:
                # one failed Gemini request falls through to the top-five
                # OpenAI backup without spending another Gemini call.
                max_primary_attempts=1,
            )
            for candidate_rank, ticker, name, path in charts
        ),
        return_exceptions=True,
    )
    return [r for r in results if isinstance(r, dict)]


def format_message(picks: list[dict], analyzed: int, scanned: int) -> str:
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    head = (
        f"<b>🟢 AI 차트 매수 후보 {len(picks)}종목</b>\n"
        f"로컬 사전필터 {scanned}종목 → Vision {analyzed}종목 · {stamp}"
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


def _write_picks_csv(picks: list[dict]) -> None:
    """Atomically replace the output only after analysis is technically valid."""
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    temp_path = OUT_CSV.with_name(f".{OUT_CSV.name}.{uuid4().hex}.tmp")
    try:
        with temp_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "종목명", "종목코드", "시장", "signal", "confidence",
                    "ma_status", "rsi_zone", "volume_trend",
                ],
                extrasaction="ignore",
            )
            writer.writeheader()
            writer.writerows(picks)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, OUT_CSV)
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=10, help="선별할 BUY 종목 수 (최대 10)")
    ap.add_argument("--batch", type=int, default=20, help="Vision 배치 크기 (최대 20)")
    ap.add_argument("--max-universe", type=int, default=1200, help="로컬 사전탐색 범위 (최대 1200)")
    ap.add_argument("--vision-max-calls", type=int, default=20, help="유료 Vision 호출 상한 (최대 20)")
    ap.add_argument("--concurrency", type=int, default=10)
    ap.add_argument("--no-send", action="store_true")
    ap.add_argument("--channel", action="store_true", help="채널에도 발송 (기본: 개인 봇만)")
    args = ap.parse_args()

    target, vision_limit = bounded_run_limits(
        target=args.target,
        vision_calls=args.vision_max_calls,
    )
    max_universe = _bounded_positive(
        args.max_universe,
        default=MAX_UNIVERSE,
        ceiling=MAX_UNIVERSE,
    )
    batch_size = _bounded_positive(
        args.batch,
        default=MAX_VISION_CALLS,
        ceiling=MAX_VISION_CALLS,
    )
    concurrency = _bounded_positive(args.concurrency, default=10, ceiling=10)

    prices = load_prices()
    universe = build_universe(max_universe, prices=prices)
    prices_by_ticker = {code: g for code, g in prices.groupby("ticker")}
    print(f"유니버스 {len(universe)}종목 · 가격데이터 {len(prices_by_ticker)}종목 "
          f"(최신 {prices['date'].max():%Y-%m-%d})", flush=True)

    main_kr.reset_vision_health()
    buys: list[dict] = []
    all_results: list[dict] = []
    analyzed = 0
    scanned = 0
    vision_run_id = f"kr-buy-screen:{uuid4()}"

    as_of = prefilter_as_of(universe, prices_by_ticker)
    if not price_data_is_fresh(as_of):
        shown = str(as_of.date()) if as_of is not None else "unavailable"
        print(
            f"오류: daily_prices.csv 기준일 {shown}이 오늘({_kst_today()})과 다릅니다. "
            "기존 결과를 보존하고 API 호출을 중단합니다.",
            flush=True,
        )
        return 1

    selected = rank_prefilter_candidates(
        universe,
        prices_by_ticker,
        limit=vision_limit,
        as_of=as_of,
    )
    scanned = len(universe)
    if not selected:
        print("오류: 로컬 사전필터 통과 종목이 없어 기존 결과를 보존합니다.", flush=True)
        return 1
    try:
        granted_calls = reserve_daily_vision_calls(
            len(selected),
            run_id=vision_run_id,
            daily_limit=vision_limit,
        )
    except RuntimeError as exc:
        print(f"오류: 일일 Vision 비용 상태 확인 실패({exc})", flush=True)
        return 1
    if granted_calls <= 0:
        try:
            already_completed = daily_vision_run_completed()
        except RuntimeError as exc:
            print(f"오류: 일일 Vision 완료 상태 확인 실패({exc})", flush=True)
            return 1
        if already_completed:
            print("오늘의 BUY screen은 이미 정상 완료되어 재실행을 건너뜁니다.", flush=True)
            return 0
        print(
            "오류: 오늘의 Gemini 상한은 예약됐지만 정상 완료 기록이 없습니다. "
            "기존 결과를 보존합니다.",
            flush=True,
        )
        return 1
    selected = selected[:granted_calls]
    print(
        f"로컬 OHLCV 사전순위 완료: {scanned}종목 → Vision {len(selected)}종목 "
        f"(호출 상한 {vision_limit}, 결과 상한 {target})",
        flush=True,
    )

    # 선택된 상위 후보만 처리한다. analyze_batch에도 동일 상한이 있어 helper를
    # 직접 호출하거나 배치 값을 잘못 주더라도 Gemini 1차 호출은 20회를 못 넘는다.
    for start in range(0, len(selected), batch_size):
        batch = selected[start:start + batch_size]
        print(f"[Vision {start + 1}~{start + len(batch)}] 분석 시작", flush=True)
        results = asyncio.run(
            analyze_batch(
                batch,
                prices_by_ticker,
                concurrency,
                run_id=vision_run_id,
                rank_offset=start,
                vision_limit=vision_limit,
            )
        )
        analyzed += len(results)
        all_results.extend(results)
        buys += [r for r in results if str(r.get("signal", "")).upper() == "BUY"]
        print(f"  누적: 분석 {analyzed} · BUY {len(buys)}/{target}", flush=True)
        if len(buys) >= target:
            break

    available_results = [
        result
        for result in all_results
        if result.get("image_analysis_status") == "available"
        and str(result.get("signal") or "").upper() in {"BUY", "HOLD", "SELL"}
    ]
    if not available_results:
        print(
            "오류: 사용 가능한 Vision 분석이 0건입니다. 기존 결과를 보존합니다.",
            flush=True,
        )
        return 1
    buys.sort(key=lambda r: int(r.get("confidence") or 0), reverse=True)
    picks = buys[:target]
    print(f"선별 완료: BUY {len(buys)}종목 → 상위 {len(picks)}종목", flush=True)

    _write_picks_csv(picks)
    try:
        mark_daily_vision_run_completed(run_id=vision_run_id)
    except RuntimeError as exc:
        print(f"오류: Vision 완료 상태 저장 실패({exc})", flush=True)
        return 1
    print(f"저장: {OUT_CSV}", flush=True)

    if not picks:
        print("BUY 후보가 없어 발송하지 않습니다.", flush=True)
        return 0
    if len(picks) < target:
        print(
            f"안내: 목표 {target}종목에 미달 ({len(picks)}종목). "
            "비용 상한 안에서 확인된 BUY만 제공합니다.",
            flush=True,
        )

    msg = format_message(picks, analyzed, scanned)
    if args.no_send:
        print(msg)
        return 0

    from scheduler import send_telegram_long
    print("sent:", send_telegram_long(msg, channel=args.channel), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

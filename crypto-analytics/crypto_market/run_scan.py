#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Crypto VCP Scanner - Main Runner
ULTRATHINK Design Notes:
- Async architecture for parallel OHLCV fetching (200+ symbols)
- Multi-timeframe (4H + 1D) for confirmation
- Deduplication + cooldown to prevent alert fatigue
- Can be called from Flask API or run standalone via CLI
"""
import os
import sys
import asyncio
import datetime as dt
import logging
import ccxt

# Add parent directory to path for imports when run standalone
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import ScannerCfg
from universe import build_universe_binance_usdt
from fetch_async import fetch_all_candles
from signals import detect_setups, detect_breakouts, detect_retests
from scoring import score_batch
from storage import make_engine, get_state, upsert_state, insert_signal, get_recent_signals
from vcp_ml_predictor import VCPMLPredictor

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def _pivot_round_dp(pivot: float) -> int:
    if pivot < 1:
        return 5
    if pivot < 100:
        return 3
    return 2


def make_event_id(evt) -> str:
    iso = dt.datetime.utcfromtimestamp(evt.event_ts / 1000).replace(microsecond=0).isoformat() + "Z"
    return f"{evt.exchange}:{evt.symbol}:{evt.timeframe}:{iso}:{evt.signal_type}"


def make_dedupe_key(evt) -> str:
    dp = _pivot_round_dp(evt.pivot_high)
    piv = round(evt.pivot_high, dp)
    return f"{evt.exchange}:{evt.symbol}:{evt.timeframe}:{evt.signal_type}:{piv}"


def build_tags(evt) -> list[str]:
    return ["vcp", evt.signal_type.lower(), evt.timeframe.lower(), 
            f"liq_{evt.liquidity_bucket.lower()}", evt.market_regime.lower()]


def build_summary(evt) -> str:
    t = dt.datetime.utcfromtimestamp(evt.event_ts/1000).strftime("%Y-%m-%d %H:%MZ")
    lines = [
        f"🪙 {evt.symbol} | {evt.timeframe} | {evt.signal_type}",
        f"⏰ {t}",
        f"📊 Score: {evt.score} | Regime: {evt.market_regime} | Liq: {evt.liquidity_bucket}",
        f"📍 Pivot: {evt.pivot_high:.6f} | Breakout: {evt.breakout_close_pct:.2f}%",
        f"📈 Vol Ratio: {evt.vol_ratio:.2f} | Wick: {evt.wick_ratio:.2f}",
        f"🔻 Contraction: {evt.c1_range_pct:.1f}% → {evt.c2_range_pct:.1f}% → {evt.c3_range_pct:.1f}%",
    ]
    if evt.signal_type == "RETEST_OK":
        lines.append(f"♻️ Retest: depth={evt.retest_depth_pct:.2f}%")
    if evt.ml_win_prob is not None:
        lines.append(f"🤖 ML Win Prob: {evt.ml_win_prob:.1f}%")
    return "\n".join(lines)


def should_publish(evt, cfg: ScannerCfg) -> bool:
    """Gate: Score threshold + liquidity filter"""
    min_score = cfg.min_score_1d if evt.timeframe == "1d" else cfg.min_score_4h
    if evt.score < min_score:
        return False
    if evt.liquidity_bucket not in cfg.allow_liquidity and evt.score < cfg.liquidity_exception_score:
        return False
    return True


def cooldown_hours(evt, cfg: ScannerCfg) -> int:
    return cfg.cooldown_hours_retest if evt.signal_type == "RETEST_OK" else cfg.cooldown_hours_breakout


def _symbol_day_key(evt) -> str:
    d = dt.datetime.utcfromtimestamp(evt.event_ts/1000).strftime("%Y-%m-%d")
    return f"{evt.exchange}:{evt.symbol}:{d}"


def passes_cooldown_and_limits(evt, engine, cfg: ScannerCfg) -> bool:
    st = get_state(engine, evt.dedupe_key)
    now_ts = evt.event_ts
    sym_day = _symbol_day_key(evt)
    # Per-symbol-per-day limit
    if st and st.get("last_symbol_day") == sym_day:
        return False
    # Cooldown check
    if st and st.get("cooldown_until_ts") and int(st["cooldown_until_ts"]) > now_ts:
        return False
    return True


def mark_published(evt, cfg: ScannerCfg, engine):
    now_ts = evt.event_ts
    cd = cooldown_hours(evt, cfg)
    cooldown_until = now_ts + cd * 3600 * 1000
    upsert_state(engine, evt.dedupe_key, now_ts, cooldown_until, _symbol_day_key(evt))
    insert_signal(engine, evt)


def process_events(evts: list, cfg: ScannerCfg, engine) -> list:
    """Process and filter events, return published ones"""
    published = []
    
    def prio(e) -> tuple:
        t = 0 if e.signal_type == "RETEST_OK" else 1
        tf = 0 if e.timeframe == "1d" else 1
        return (t, tf, -e.score)

    for e in sorted(evts, key=prio):
        if not should_publish(e, cfg):
            continue

        e.event_id = make_event_id(e)
        e.dedupe_key = make_dedupe_key(e)

        if not passes_cooldown_and_limits(e, engine, cfg):
            continue

        e.tags = build_tags(e)
        e.summary_text = build_summary(e)

        mark_published(e, cfg, engine)
        published.append(e)
    
    return published


async def run_scan_async(
    top_n: int = 200,
    min_qv: float = 5_000_000,
    max_conc: int = 12,
    db_path: str = None
) -> dict:
    """
    Main async scanner entry point.
    Returns dict with scan results for API consumption.
    """
    if db_path is None:
        db_path = os.path.join(os.path.dirname(__file__), "signals.sqlite3")
    
    cfg = ScannerCfg(universe_top_n=top_n, min_quote_volume_usdt=min_qv)
    engine = make_engine(db_path)

    logger.info(f"🚀 Starting Crypto VCP Scan (top_n={top_n}, min_qv={min_qv:,.0f})")

    # Universe (sync tickers)
    ex_sync = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "spot"}})
    symbols_with_qv = build_universe_binance_usdt(ex_sync, top_n=cfg.universe_top_n, min_quote_vol_usdt=cfg.min_quote_volume_usdt)
    # Note: sync ccxt exchange doesn't need close()
    
    
    logger.info(f"📊 Universe: {len(symbols_with_qv)} symbols")

    symbols = [s for s, _ in symbols_with_qv]
    timeframes = [cfg.tf_4h.timeframe, cfg.tf_1d.timeframe]

    # Fetch candles (async)
    logger.info("📥 Fetching OHLCV data...")
    candles_map = await fetch_all_candles(
        symbols=symbols + ["BTC/USDT"],
        timeframes=timeframes,
        limit=max(cfg.tf_4h.limit, cfg.tf_1d.limit),
        max_concurrency=max_conc,
    )
    logger.info(f"📥 Fetched {len(candles_map)} symbol-timeframe pairs")

    btc_4h = candles_map.get(("BTC/USDT", cfg.tf_4h.timeframe), [])
    btc_1d = candles_map.get(("BTC/USDT", cfg.tf_1d.timeframe), [])

    # 4H Analysis
    logger.info("🔍 Analyzing 4H timeframe...")
    setups_4h = detect_setups(cfg.exchange, symbols_with_qv, candles_map, btc_4h, cfg.tf_4h)
    breakouts_4h = detect_breakouts(setups_4h, candles_map, cfg.tf_4h)
    retests_4h = detect_retests(setups_4h, breakouts_4h, candles_map, cfg.tf_4h)
    events_4h = score_batch(breakouts_4h + retests_4h, cfg.tf_4h)
    logger.info(f"  4H: {len(setups_4h)} setups → {len(breakouts_4h)} breakouts, {len(retests_4h)} retests")

    # 1D Analysis
    logger.info("🔍 Analyzing 1D timeframe...")
    setups_1d = detect_setups(cfg.exchange, symbols_with_qv, candles_map, btc_1d, cfg.tf_1d)
    breakouts_1d = detect_breakouts(setups_1d, candles_map, cfg.tf_1d)
    retests_1d = detect_retests(setups_1d, breakouts_1d, candles_map, cfg.tf_1d)
    events_1d = score_batch(breakouts_1d + retests_1d, cfg.tf_1d)
    logger.info(f"  1D: {len(setups_1d)} setups → {len(breakouts_1d)} breakouts, {len(retests_1d)} retests")

    all_events = events_4h + events_1d

    # ML win probability prediction
    try:
        ml_predictor = VCPMLPredictor()
        if ml_predictor.load_model():
            logger.info("🤖 Running ML win probability predictions...")
            for evt in all_events:
                signal_data = {
                    'score': evt.score,
                    'c1_range_pct': evt.c1_range_pct,
                    'c2_range_pct': evt.c2_range_pct,
                    'c3_range_pct': evt.c3_range_pct,
                    'vol_ratio': evt.vol_ratio,
                    'wick_ratio': evt.wick_ratio,
                    'ema_sep_pct': evt.ema_sep_pct,
                    'above_ema50_ratio': evt.above_ema50_ratio,
                    'atrp_pct': evt.atrp_pct,
                    'breakout_close_pct': evt.breakout_close_pct,
                    'entry_type': evt.signal_type,
                    'grade': evt.market_regime.split('|')[1] if '|' in evt.market_regime else 'D',
                    'market_regime': evt.market_regime.split('|')[0] if '|' in evt.market_regime else evt.market_regime,
                    'liquidity_bucket': evt.liquidity_bucket,
                }
                pred = ml_predictor.predict(signal_data)
                evt.ml_win_prob = pred['win_probability']
            logger.info(f"🤖 ML predictions complete for {len(all_events)} signals")
        else:
            logger.warning("⚠️ VCP ML model not found, skipping predictions")
    except Exception as e:
        logger.warning(f"⚠️ ML prediction failed: {e}")

    # Process and publish
    published = process_events(all_events, cfg, engine)
    logger.info(f"✅ Published {len(published)} new signals")

    # Build response
    top_signals = sorted(all_events, key=lambda x: x.score, reverse=True)[:30]
    
    return {
        "scan_time": dt.datetime.utcnow().isoformat() + "Z",
        "universe_size": len(symbols_with_qv),
        "setups_4h": len(setups_4h),
        "setups_1d": len(setups_1d),
        "signals_4h": len(events_4h),
        "signals_1d": len(events_1d),
        "published": len(published),
        "top_signals": [
            {
                "symbol": e.symbol,
                "timeframe": e.timeframe,
                "signal_type": e.signal_type,
                "score": e.score,
                "pivot_high": e.pivot_high,
                "breakout_close_pct": round(e.breakout_close_pct, 2),
                "vol_ratio": round(e.vol_ratio, 2),
                "liquidity_bucket": e.liquidity_bucket,
                "market_regime": e.market_regime,
                "c1": round(e.c1_range_pct, 1),
                "c2": round(e.c2_range_pct, 1),
                "c3": round(e.c3_range_pct, 1),
                "ml_win_prob": round(e.ml_win_prob, 1) if e.ml_win_prob is not None else None,
            }
            for e in top_signals
        ],
    }


def run_scan_sync(**kwargs) -> dict:
    """Synchronous wrapper for Flask integration"""
    return asyncio.run(run_scan_async(**kwargs))


def get_signals_from_db(db_path: str = None, limit: int = 50) -> list:
    """Get recent signals from database for API"""
    if db_path is None:
        db_path = os.path.join(os.path.dirname(__file__), "signals.sqlite3")
    engine = make_engine(db_path)
    return get_recent_signals(engine, limit)


def main():
    """CLI entry point"""
    import argparse
    parser = argparse.ArgumentParser(description='Crypto VCP Scanner')
    parser.add_argument('--top-n', type=int, default=200, help='Top N symbols by volume')
    parser.add_argument('--min-qv', type=float, default=5_000_000, help='Min quote volume USDT')
    parser.add_argument('--max-conc', type=int, default=12, help='Max concurrency')
    parser.add_argument('--test', action='store_true', help='Test mode (top 10 only)')
    args = parser.parse_args()

    if args.test:
        args.top_n = 10
        args.max_conc = 3
        logger.info("🧪 Running in TEST mode (top 10 symbols)")

    result = run_scan_sync(
        top_n=args.top_n,
        min_qv=args.min_qv,
        max_conc=args.max_conc,
    )

    print("\n" + "="*60)
    print("🪙 CRYPTO VCP SCAN RESULTS")
    print("="*60)
    print(f"Universe: {result['universe_size']} symbols")
    print(f"Setups: 4H={result['setups_4h']}, 1D={result['setups_1d']}")
    print(f"Signals: 4H={result['signals_4h']}, 1D={result['signals_1d']}")
    print(f"Published: {result['published']}")
    print("\n📈 Top Signals:")
    for s in result['top_signals'][:10]:
        print(f"  {s['score']:3d} | {s['timeframe']:2s} | {s['signal_type']:9s} | {s['symbol']:12s} | pivot={s['pivot_high']:.6f}")


if __name__ == "__main__":
    main()

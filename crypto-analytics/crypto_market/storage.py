#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Crypto VCP Scanner - SQLite Storage
ULTRATHINK Design Notes:
- signal_state: Deduplication + cooldown tracking per (symbol, timeframe, pivot)
- signals: Historical log of all published signals for backtesting/analysis
"""
from __future__ import annotations
from typing import Optional
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


def make_engine(sqlite_path: str) -> Engine:
    """Create SQLite engine with required tables"""
    eng = create_engine(f"sqlite:///{sqlite_path}", future=True)
    with eng.begin() as conn:
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS signal_state (
          dedupe_key TEXT PRIMARY KEY,
          last_notified_ts INTEGER,
          cooldown_until_ts INTEGER,
          last_symbol_day TEXT
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS signals (
          event_id TEXT PRIMARY KEY,
          exchange TEXT,
          symbol TEXT,
          timeframe TEXT,
          event_ts INTEGER,
          signal_type TEXT,
          score INTEGER,
          pivot_high REAL,
          breakout_close_pct REAL,
          vol_ratio REAL,
          wick_ratio REAL,
          liquidity_bucket TEXT,
          market_regime TEXT,
          summary_text TEXT,
          c1_range_pct REAL,
          c2_range_pct REAL,
          c3_range_pct REAL,
          atrp_pct REAL,
          ema_sep_pct REAL,
          ml_win_prob REAL,
          created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """))
    # Migration: add ml_win_prob column if missing
    with eng.begin() as conn:
        try:
            conn.execute(text("SELECT ml_win_prob FROM signals LIMIT 1"))
        except Exception:
            try:
                conn.execute(text("ALTER TABLE signals ADD COLUMN ml_win_prob REAL"))
            except Exception:
                pass
    return eng


def get_state(engine: Engine, dedupe_key: str) -> Optional[dict]:
    """Get deduplication state for a signal"""
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT dedupe_key, last_notified_ts, cooldown_until_ts, last_symbol_day FROM signal_state WHERE dedupe_key=:k"),
            {"k": dedupe_key}
        ).mappings().first()
        return dict(row) if row else None


def upsert_state(engine: Engine, dedupe_key: str, last_notified_ts: int, cooldown_until_ts: int, last_symbol_day: str):
    """Insert or update deduplication state"""
    with engine.begin() as conn:
        conn.execute(text("""
        INSERT INTO signal_state(dedupe_key, last_notified_ts, cooldown_until_ts, last_symbol_day)
        VALUES (:k,:l,:c,:d)
        ON CONFLICT(dedupe_key) DO UPDATE SET
          last_notified_ts=excluded.last_notified_ts,
          cooldown_until_ts=excluded.cooldown_until_ts,
          last_symbol_day=excluded.last_symbol_day
        """), {"k": dedupe_key, "l": last_notified_ts, "c": cooldown_until_ts, "d": last_symbol_day})


def insert_signal(engine: Engine, evt):
    """Insert signal into historical log"""
    with engine.begin() as conn:
        conn.execute(text("""
        INSERT OR IGNORE INTO signals(
          event_id, exchange, symbol, timeframe, event_ts, signal_type, score,
          pivot_high, breakout_close_pct, vol_ratio, wick_ratio, liquidity_bucket,
          market_regime, summary_text, c1_range_pct, c2_range_pct, c3_range_pct,
          atrp_pct, ema_sep_pct, ml_win_prob
        ) VALUES (
          :event_id, :exchange, :symbol, :timeframe, :event_ts, :signal_type, :score,
          :pivot_high, :breakout_close_pct, :vol_ratio, :wick_ratio, :liquidity_bucket,
          :market_regime, :summary_text, :c1_range_pct, :c2_range_pct, :c3_range_pct,
          :atrp_pct, :ema_sep_pct, :ml_win_prob
        )
        """), {
            "event_id": evt.event_id,
            "exchange": evt.exchange,
            "symbol": evt.symbol,
            "timeframe": evt.timeframe,
            "event_ts": evt.event_ts,
            "signal_type": evt.signal_type,
            "score": evt.score,
            "pivot_high": evt.pivot_high,
            "breakout_close_pct": evt.breakout_close_pct,
            "vol_ratio": evt.vol_ratio,
            "wick_ratio": evt.wick_ratio,
            "liquidity_bucket": evt.liquidity_bucket,
            "market_regime": evt.market_regime,
            "summary_text": evt.summary_text,
            "c1_range_pct": evt.c1_range_pct,
            "c2_range_pct": evt.c2_range_pct,
            "c3_range_pct": evt.c3_range_pct,
            "atrp_pct": evt.atrp_pct,
            "ema_sep_pct": evt.ema_sep_pct,
            "ml_win_prob": evt.ml_win_prob,
        })


def get_recent_signals(engine: Engine, limit: int = 50) -> list:
    """Get recent signals for API response"""
    with engine.begin() as conn:
        rows = conn.execute(text("""
        SELECT event_id, exchange, symbol, timeframe, event_ts, signal_type, score,
               pivot_high, breakout_close_pct, vol_ratio, wick_ratio, liquidity_bucket,
               market_regime, c1_range_pct, c2_range_pct, c3_range_pct, atrp_pct,
               ema_sep_pct, ml_win_prob, created_at
        FROM signals
        ORDER BY event_ts DESC
        LIMIT :limit
        """), {"limit": limit}).mappings().all()
        return [dict(r) for r in rows]

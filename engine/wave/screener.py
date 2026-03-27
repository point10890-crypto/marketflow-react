"""
Wave Pattern Screener — 전 종목 일괄 스캔
daily_prices.csv에서 활성 종목을 추출하여 M&W 패턴을 자동 감지.
결과: data/wave/wave_screener_latest.json
"""
import os
import sys
import json
import logging
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional

# Ensure project root is importable when run as script
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BASE_DIR not in sys.path:
    sys.path.insert(0, _BASE_DIR)

import numpy as np
import pandas as pd

from engine.wave.data_adapter import load_ohlcv, ohlcv_to_chart_data
from engine.wave.zigzag import zigzag, extract_five_point_groups
from engine.wave.classifier import classify_pattern
from engine.wave.pattern_scorer import score_pattern
from engine.wave.models import FivePointPattern

logger = logging.getLogger(__name__)

_DATA_DIR = os.path.join(_BASE_DIR, 'data')
_WAVE_DIR = os.path.join(_DATA_DIR, 'wave')


def _get_active_tickers(min_volume: int = 500_000, min_price: int = 1000, max_tickers: int = 800) -> List[Dict]:
    """
    daily_prices.csv에서 최근 거래량·가격 기준 활성 종목 추출.
    ETF/ETN/스팩/우선주 제외.
    """
    csv_path = os.path.join(_DATA_DIR, 'daily_prices.csv')
    if not os.path.exists(csv_path):
        logger.error(f"daily_prices.csv not found: {csv_path}")
        return []

    df = pd.read_csv(csv_path, dtype={'ticker': str}, low_memory=False)
    df['date'] = pd.to_datetime(df['date'])

    # 최근 20일 데이터만
    cutoff = df['date'].max() - timedelta(days=30)
    recent = df[df['date'] >= cutoff].copy()

    # 종목별 최근 거래량 평균, 최신 가격
    agg = recent.groupby('ticker').agg(
        name=('name', 'last'),
        avg_volume=('volume', 'mean'),
        last_price=('current_price', 'last'),
        last_date=('date', 'max'),
    ).reset_index()

    # 필터: 가격, 거래량
    agg = agg[agg['last_price'] >= min_price]
    agg = agg[agg['avg_volume'] >= min_volume]

    # ETF/ETN/스팩/우선주/리츠 제외
    exclude_keywords = ['ETF', 'ETN', 'SPAC', '스팩', '리츠', 'TIGER', 'KODEX', 'KOSEF',
                        'KBSTAR', 'ARIRANG', 'SOL', 'ACE', 'HANARO', 'PLUS', 'BNK']
    for kw in exclude_keywords:
        agg = agg[~agg['name'].str.contains(kw, case=False, na=False)]

    # 우선주 제외 (코드 끝자리 5, 7, 8, 9 — 보통주는 0)
    agg = agg[agg['ticker'].str[-1].isin(['0', '1', '2', '3'])]

    # 거래량 상위 정렬
    agg = agg.sort_values('avg_volume', ascending=False).head(max_tickers)

    result = []
    for _, row in agg.iterrows():
        result.append({
            'ticker': row['ticker'],
            'name': row['name'],
            'price': float(row['last_price']),
            'avg_volume': float(row['avg_volume']),
        })

    logger.info(f"Active tickers: {len(result)} (min_vol={min_volume:,}, min_price={min_price:,})")
    return result


def detect_for_ticker(ticker: str, market: str = 'KR', lookback: int = 200,
                      min_confidence: int = 40) -> Optional[Dict]:
    """단일 종목 패턴 감지 (스크리너용 경량 버전)."""
    try:
        data = load_ohlcv(ticker, market=market, lookback=lookback)
        if data is None:
            return None

        closes = data['closes']
        volumes = data['volumes']
        turning_points = zigzag(data['dates'], data['highs'], data['lows'], closes)

        groups = extract_five_point_groups(turning_points)
        if not groups:
            return None

        patterns: List[FivePointPattern] = []
        for group in groups:
            pat = classify_pattern(group, closes, volumes=volumes, current_price=float(closes[-1]))
            sc = score_pattern(pat, closes, volumes=volumes)
            if sc >= min_confidence:
                pat.confidence = sc
                patterns.append(pat)

        if not patterns:
            return None

        patterns.sort(key=lambda p: p.confidence, reverse=True)
        best = patterns[0]

        return {
            'ticker': ticker,
            'market': market,
            'best_pattern': best.to_dict(),
            'pattern_count': len(patterns),
            'all_patterns': [p.to_dict() for p in patterns[:3]],
        }
    except Exception as e:
        logger.debug(f"Skip {ticker}: {e}")
        return None


def run_screener(market: str = 'KR', min_confidence: int = 40,
                 max_tickers: int = 800, lookback: int = 200) -> Dict:
    """
    전 종목 Wave 패턴 스캔.
    Returns: screener result dict (also saved to JSON).
    """
    start_time = time.time()
    logger.info(f"{'='*60}")
    logger.info(f"Wave Pattern Screener — {market} ({max_tickers} tickers, min_conf={min_confidence})")
    logger.info(f"{'='*60}")

    # 1. 활성 종목 목록
    tickers = _get_active_tickers(max_tickers=max_tickers)
    if not tickers:
        logger.warning("No active tickers found")
        return {'signals': [], 'scan_count': 0}

    # 2. 각 종목 스캔
    signals = []
    scanned = 0
    for i, t in enumerate(tickers):
        ticker = t['ticker']
        result = detect_for_ticker(ticker, market=market, lookback=lookback,
                                   min_confidence=min_confidence)
        scanned += 1
        if result:
            result['name'] = t['name']
            result['price'] = t['price']
            result['avg_volume'] = t['avg_volume']
            signals.append(result)

        if (i + 1) % 100 == 0:
            logger.info(f"  Progress: {i+1}/{len(tickers)} scanned, {len(signals)} patterns found")

    # 3. 최고 신뢰도 순 정렬
    signals.sort(key=lambda s: s['best_pattern']['confidence'], reverse=True)

    elapsed = time.time() - start_time
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    date_str = datetime.now().strftime('%Y-%m-%d')

    screener_result = {
        'date': date_str,
        'updated_at': now_str,
        'market': market,
        'scan_count': scanned,
        'signal_count': len(signals),
        'processing_time_sec': round(elapsed, 1),
        'min_confidence': min_confidence,
        'signals': signals,
    }

    # 4. JSON 저장
    os.makedirs(_WAVE_DIR, exist_ok=True)
    latest_path = os.path.join(_WAVE_DIR, 'wave_screener_latest.json')
    archive_path = os.path.join(_WAVE_DIR, f'wave_screener_{date_str.replace("-","")}.json')

    for path in [latest_path, archive_path]:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(screener_result, f, ensure_ascii=False, indent=2)

    logger.info(f"{'='*60}")
    logger.info(f"Wave Screener Done: {len(signals)} patterns from {scanned} stocks ({elapsed:.1f}s)")
    logger.info(f"Saved: {latest_path}")
    logger.info(f"{'='*60}")

    return screener_result


def run_wave_scan():
    """scheduler.py에서 호출하는 래퍼."""
    return run_screener(market='KR', min_confidence=40, max_tickers=800)


# ── CLI 진입점 ──
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

    market = sys.argv[1] if len(sys.argv) > 1 else 'KR'
    result = run_screener(market=market)
    print(f"\nTotal: {result['signal_count']} patterns detected from {result['scan_count']} stocks")

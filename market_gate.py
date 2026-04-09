#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KR Market Gate - Enhanced Scoring v2.0
🧠 ULTRATHINK: RSI, MACD, Volume, and Relative Strength vs KOSPI
"""

import yfinance as yf
import pandas as pd
import numpy as np
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime
from typing import Dict, List, Any, Tuple
from dataclasses import dataclass

from config import KOSPI_TICKER, KOSDAQ_TICKER, USD_KRW_TICKER, MarketGateConfig

# 모듈 레벨 basicConfig 금지 — Flask logger 설정을 덮어쓴다.
# CLI 실행 시에는 main 또는 진입점에서 핸들러를 부착할 것.
logger = logging.getLogger(__name__)

# yfinance 는 자체 타임아웃 파라미터가 없어 네트워크 hang 시 Flask worker 가
# 수 분 동안 블로킹된다. ThreadPoolExecutor 로 감싸서 상한을 강제한다.
_YF_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix='mg_yf')
_YF_TIMEOUT_SEC = 15


def _yf_download_with_timeout(tickers, period="1y", progress=False, timeout=_YF_TIMEOUT_SEC):
    """yf.download wrapped with a hard timeout.

    Returns an empty DataFrame on timeout or any downstream exception —
    callers already branch on `empty` / missing columns, so no raise.
    """
    def _fetch():
        return yf.download(tickers, period=period, progress=progress)

    future = _YF_EXECUTOR.submit(_fetch)
    try:
        return future.result(timeout=timeout)
    except FuturesTimeoutError:
        logger.warning(f"[market_gate] yfinance timeout (>{timeout}s) for {tickers}")
        future.cancel()
        return pd.DataFrame()
    except Exception as e:
        logger.warning(f"[market_gate] yfinance error for {tickers}: {type(e).__name__}: {e}")
        return pd.DataFrame()

@dataclass
class SectorResult:
    name: str
    ticker: str
    score: int
    signal: str
    price: float
    change_1d: float
    rsi: float
    rs_vs_kospi: float

@dataclass
class KRMarketGateResult:
    gate: str
    score: int
    reasons: List[str]
    sectors: List[SectorResult]
    metrics: Dict[str, Any]

# Representative Sector ETFs for KR (KODEX/TIGER)
KR_SECTORS = {
    "KOSPI200": "069500.KS",  # KODEX 200 (benchmark)
    "반도체": "091160.KS",
    "2차전지": "305720.KS",
    "자동차": "091170.KS",
    "IT": "102780.KS",
    "은행": "102960.KS",
    "철강": "117680.KS",
    "증권": "102970.KS",
}

def calculate_rsi(series: pd.Series, period: int = 14) -> float:
    """Calculate RSI"""
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else 50.0

def calculate_macd_signal(series: pd.Series) -> str:
    """Calculate MACD signal"""
    ema12 = series.ewm(span=12, adjust=False).mean()
    ema26 = series.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    
    curr_macd = macd_line.iloc[-1]
    curr_signal = signal_line.iloc[-1]
    
    if curr_macd > curr_signal:
        return "BULLISH"
    else:
        return "BEARISH"

def calculate_volume_ratio(volume: pd.Series, period: int = 20) -> float:
    """Calculate volume ratio vs average"""
    avg_vol = volume.rolling(period).mean().iloc[-1]
    return float(volume.iloc[-1] / avg_vol) if avg_vol > 0 else 1.0

def calculate_rs_vs_benchmark(sector_close: pd.Series, bench_close: pd.Series, period: int = 20) -> float:
    """Calculate RS vs KOSPI"""
    sector_ret = (sector_close.iloc[-1] - sector_close.iloc[-period]) / sector_close.iloc[-period]
    bench_ret = (bench_close.iloc[-1] - bench_close.iloc[-period]) / bench_close.iloc[-period]
    return float((sector_ret - bench_ret) * 100)

def calculate_enhanced_score(close: pd.Series, volume: pd.Series, kospi_close: pd.Series = None) -> Tuple[int, str, dict]:
    """Enhanced scoring with RSI, MACD, Volume, RS"""
    if len(close) < 60:
        return 50, "NEUTRAL", {}
    
    score = 0
    details = {}
    
    # 1. Trend Alignment (25 pts) - using shorter EMAs for KR
    e20 = close.rolling(20).mean()
    e60 = close.rolling(60).mean()
    curr_price, curr_e20, curr_e60 = close.iloc[-1], e20.iloc[-1], e60.iloc[-1]
    
    if curr_price > curr_e20 > curr_e60:
        score += 25
        details['trend'] = '정배열 강세'
    elif curr_price > curr_e20:
        score += 15
        details['trend'] = '단기 상승'
    elif curr_price > curr_e60:
        score += 10
        details['trend'] = '60MA 지지'
    else:
        details['trend'] = '하락추세'
    
    # 2. RSI (25 pts)
    rsi = calculate_rsi(close)
    details['rsi'] = rsi
    if 50 <= rsi <= 70:
        score += 25
    elif 40 <= rsi < 50:
        score += 15
    elif 30 <= rsi < 40:
        score += 20
    elif rsi < 30:
        score += 10
    
    # 3. MACD Signal (20 pts)
    macd_sig = calculate_macd_signal(close)
    details['macd'] = macd_sig
    if macd_sig == "BULLISH":
        score += 20
    
    # 4. Volume Confirmation (15 pts)
    vol_ratio = calculate_volume_ratio(volume)
    details['vol_ratio'] = vol_ratio
    if vol_ratio > 1.2:
        score += 15
    elif vol_ratio > 0.8:
        score += 10
    
    # 5. Relative Strength vs KOSPI (15 pts)
    if kospi_close is not None and len(kospi_close) >= 20:
        rs = calculate_rs_vs_benchmark(close, kospi_close)
        details['rs_vs_kospi'] = rs
        if rs > 2:
            score += 15
        elif rs > 0:
            score += 10
        elif rs > -2:
            score += 5
    else:
        details['rs_vs_kospi'] = 0
    
    score = int(min(100, max(0, score)))
    signal = "BULLISH" if score >= 70 else ("BEARISH" if score < 40 else "NEUTRAL")
    return score, signal, details

def run_kr_market_gate() -> KRMarketGateResult:
    """Run enhanced KR Market Gate Analysis"""
    logger.info("🇰🇷 Starting Enhanced KR Market Gate Analysis...")
    config = MarketGateConfig()
    
    all_tickers = [KOSPI_TICKER, KOSDAQ_TICKER, USD_KRW_TICKER] + list(KR_SECTORS.values())
    data = None
    
    # Try FinanceDataReader FIRST (Korean API - no rate limiting)
    try:
        import FinanceDataReader as fdr
        from datetime import datetime, timedelta
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365)
        
        # Mapping for FDR
        fdr_mapping = {
            KOSPI_TICKER: 'KS11',  # KOSPI
            KOSDAQ_TICKER: 'KQ11',  # KOSDAQ
            USD_KRW_TICKER: 'USD/KRW'
        }
        
        combined_data = {}
        for yf_ticker, fdr_ticker in fdr_mapping.items():
            try:
                df = fdr.DataReader(fdr_ticker, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
                if not df.empty:
                    combined_data[yf_ticker] = df
            except Exception as e:
                logger.warning(f"FDR failed for {fdr_ticker}: {e}")
        
        # Sector ETFs
        for name, ticker in KR_SECTORS.items():
            try:
                clean_ticker = ticker.replace('.KS', '').replace('.KQ', '')
                df = fdr.DataReader(clean_ticker, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
                if not df.empty:
                    combined_data[ticker] = df
            except Exception as e:
                logger.warning(f"FDR failed for {ticker}: {e}")
        
        if combined_data:
            # Build multi-index DataFrame similar to yfinance
            closes = pd.DataFrame({t: d['Close'] for t, d in combined_data.items()})
            volumes = pd.DataFrame({t: d['Volume'] for t, d in combined_data.items() if 'Volume' in d.columns})
            
            data = pd.concat({'Close': closes, 'Volume': volumes}, axis=1)
            logger.info(f"✅ FinanceDataReader loaded {len(combined_data)} tickers")
            
            # Check if Indices are missing (KOSPI/KOSDAQ)
            missing_indices = []
            if KOSPI_TICKER not in data['Close'].columns:
                missing_indices.append(KOSPI_TICKER)
            if KOSDAQ_TICKER not in data['Close'].columns:
                missing_indices.append(KOSDAQ_TICKER)
                
            if missing_indices:
                logger.warning(f"Indices missing in FDR: {missing_indices}, trying Yahoo for indices...")
                try:
                    yf_data = _yf_download_with_timeout(missing_indices, period="1y")
                    if not yf_data.empty and 'Close' in yf_data.columns:
                        # Merge Yahoo data into existing data
                        for missing in missing_indices:
                            if missing in yf_data['Close'].columns:
                                data.loc[:, ('Close', missing)] = yf_data['Close'][missing]
                                if 'Volume' in yf_data.columns and missing in yf_data['Volume'].columns:
                                    data.loc[:, ('Volume', missing)] = yf_data['Volume'][missing]
                        logger.info(f"✅ Recovered {missing_indices} from Yahoo Finance")
                except Exception as e:
                    logger.error(f"Failed to recover indices from Yahoo: {e}")

        else:
            raise ValueError("FinanceDataReader returned no data")
    except Exception as fdr_error:
        logger.warning(f"FinanceDataReader failed: {fdr_error}, trying Yahoo Finance...")
        
    # Fallback to Yahoo Finance (if FDR failed)
    if data is None or data.empty:
        data = _yf_download_with_timeout(all_tickers, period="1y")
        if data.empty or 'Close' not in data.columns:
            logger.error("Yahoo Finance fallback returned no usable data")
            return KRMarketGateResult(gate="YELLOW", score=50, reasons=["데이터 소스 오류"], sectors=[], metrics={})
        logger.info("✅ Yahoo Finance loaded data as fallback")
    
    if data.empty:
        return KRMarketGateResult(gate="YELLOW", score=50, reasons=["No data"], sectors=[], metrics={})
    
    try:
        # KOSPI Analysis - Try KOSPI index first, fallback to KODEX 200 ETF
        kospi_close = None
        kospi_volume = None
        
        # Try KOSPI index
        if KOSPI_TICKER in data['Close'].columns:
            kospi_close = data['Close'][KOSPI_TICKER].dropna()
            if 'Volume' in data.columns and KOSPI_TICKER in data['Volume'].columns:
                kospi_volume = data['Volume'][KOSPI_TICKER].dropna()
        
        # Fallback to KODEX 200 ETF (069500.KS)
        if kospi_close is None or len(kospi_close) < 60:
            kodex200 = "069500.KS"
            if kodex200 in data['Close'].columns:
                kospi_close = data['Close'][kodex200].dropna()
                if 'Volume' in data.columns and kodex200 in data['Volume'].columns:
                    kospi_volume = data['Volume'][kodex200].dropna()
                logger.info("Using KODEX 200 ETF as KOSPI benchmark")
        
        if kospi_close is None or len(kospi_close) < 60:
            raise ValueError("No suitable KOSPI benchmark found")
        
        if kospi_volume is None or kospi_volume.empty:
            kospi_volume = pd.Series([1000000] * len(kospi_close), index=kospi_close.index)
        
        overall_score, overall_signal, overall_details = calculate_enhanced_score(kospi_close, kospi_volume)
        
        # Sector breakdown
        sectors_results = []
        for name, ticker in KR_SECTORS.items():
            try:
                s_close = data['Close'][ticker].dropna()
                s_volume = data['Volume'][ticker].dropna()
                s_score, s_signal, s_details = calculate_enhanced_score(s_close, s_volume, kospi_close)
                
                price = float(s_close.iloc[-1])
                prev = float(s_close.iloc[-2])
                change_1d = (price - prev) / prev * 100
                
                sectors_results.append(SectorResult(
                    name=name, ticker=ticker, score=s_score, signal=s_signal,
                    price=price, change_1d=change_1d,
                    rsi=s_details.get('rsi', 50),
                    rs_vs_kospi=s_details.get('rs_vs_kospi', 0)
                ))
            except:
                continue
        
        # Sort by score
        sectors_results.sort(key=lambda x: x.score, reverse=True)
        
        # Exchange Rate Gate
        try:
            usd_krw = float(data['Close'][USD_KRW_TICKER].iloc[-1])
        except:
            usd_krw = 1350.0  # Default fallback
        gate_open = usd_krw < config.usd_krw_danger
        
        # Reasons
        reasons = []
        if usd_krw >= config.usd_krw_warning:
            reasons.append(f"⚠️ 환율 경계 ({usd_krw:.0f}원)")
        
        reasons.append(f"RSI({overall_details.get('rsi', 0):.1f}), MACD: {overall_details.get('macd', 'N/A')}")
        
        if overall_score >= 70:
            reasons.append(f"코스피 {overall_details.get('trend', '')}")
        elif overall_score < 40:
            reasons.append("시장 하락추세. 보수적 접근 권장.")
        
        if sectors_results:
            reasons.append(f"🔥 강세: {sectors_results[0].name} ({sectors_results[0].score})")
            reasons.append(f"❄️ 약세: {sectors_results[-1].name} ({sectors_results[-1].score})")
        
        # Gate Decision
        if not gate_open:
            gate = "RED"
        elif overall_score >= 70:
            gate = "GREEN"
        elif overall_score >= 45:
            gate = "YELLOW"
        else:
            gate = "RED"
        
        # KOSPI/KOSDAQ 종가 및 변동률 계산
        kospi_current = float(kospi_close.iloc[-1])
        kospi_prev = float(kospi_close.iloc[-2]) if len(kospi_close) >= 2 else kospi_current
        kospi_change_pct = ((kospi_current - kospi_prev) / kospi_prev) * 100 if kospi_prev > 0 else 0

        # KOSDAQ 데이터 조회
        kosdaq_current = 0.0
        kosdaq_change_pct = 0.0
        try:
            if KOSDAQ_TICKER in data['Close'].columns:
                kosdaq_close = data['Close'][KOSDAQ_TICKER].dropna()
                if len(kosdaq_close) >= 2:
                    kosdaq_current = float(kosdaq_close.iloc[-1])
                    kosdaq_prev = float(kosdaq_close.iloc[-2])
                    kosdaq_change_pct = ((kosdaq_current - kosdaq_prev) / kosdaq_prev) * 100 if kosdaq_prev > 0 else 0
        except Exception as e:
            logger.warning(f"KOSDAQ data fetch error: {e}")

        return KRMarketGateResult(
            gate=gate, score=overall_score, reasons=reasons,
            sectors=sectors_results,
            metrics={
                "usd_krw": usd_krw,
                "kospi": kospi_current,
                "kospi_change_pct": round(kospi_change_pct, 2),
                "kosdaq": kosdaq_current,
                "kosdaq_change_pct": round(kosdaq_change_pct, 2),
                "rsi": overall_details.get('rsi', 50)
            }
        )
        
    except Exception as e:
        logger.error(f"KR Market Gate Error: {e}")
        return KRMarketGateResult(gate="YELLOW", score=50, reasons=[str(e)], sectors=[], metrics={})

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    res = run_kr_market_gate()
    print(f"\n🇰🇷 KR Gate: {res.gate} ({res.score}/100)")
    print(f"Reasons: {res.reasons}")
    for s in res.sectors:
        print(f"  - {s.name}: {s.score} | RSI: {s.rsi:.1f} | RS: {s.rs_vs_kospi:+.1f}%")

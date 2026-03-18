#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VCP Enhanced Scanner — US / KR / Crypto 통합 스캐너
Minervini SEPA 기반 VCP 패턴 감지 + JSON 파일 저장

Usage:
    python vcp_enhanced_scanner.py --market US
    python vcp_enhanced_scanner.py --market KR
    python vcp_enhanced_scanner.py --market CRYPTO
    python vcp_enhanced_scanner.py --all
"""

import os
import sys
import json
import time
import logging
import argparse
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')

logging.basicConfig(level=logging.INFO, format='%(asctime)s [VCP] %(message)s')
logger = logging.getLogger(__name__)


# ── Minervini Stage 2 Trend Template ──────────────────────────────────────

def check_trend_template(closes: np.ndarray) -> Dict:
    """Minervini Trend Template 체크 (Stage 2 확인)"""
    if len(closes) < 200:
        return {'score': 0, 'passed': False, 'stage': 0, 'stage_label': 'Insufficient Data'}

    price = closes[-1]
    ema50 = _ema(closes, 50)[-1]
    ema150 = _ema(closes, 150)[-1]
    ema200 = _ema(closes, 200)[-1]
    high_52w = np.max(closes[-252:]) if len(closes) >= 252 else np.max(closes)
    low_52w = np.min(closes[-252:]) if len(closes) >= 252 else np.min(closes)

    checks = {
        'above_ema50': price > ema50,
        'above_ema150': price > ema150,
        'above_ema200': price > ema200,
        'ema50_above_ema150': ema50 > ema150,
        'ema150_above_ema200': ema150 > ema200,
        'ema200_rising': _ema(closes, 200)[-1] > _ema(closes, 200)[-20] if len(closes) >= 220 else False,
        'within_25pct_of_high': price >= high_52w * 0.75,
        'above_30pct_of_low': price >= low_52w * 1.30,
    }

    passed_count = sum(checks.values())
    score = (passed_count / len(checks)) * 100

    if passed_count >= 7:
        stage, label = 2, 'Stage 2 - Advancing'
    elif passed_count >= 5:
        stage, label = 2, 'Stage 2 - Early'
    elif price < ema200:
        stage, label = 4, 'Stage 4 - Declining'
    else:
        stage, label = 3, 'Stage 3 - Topping'

    return {'score': round(score, 1), 'passed': passed_count >= 5, 'stage': stage, 'stage_label': label}


def detect_vcp_pattern(closes: np.ndarray, volumes: np.ndarray) -> Dict:
    """VCP (Volatility Contraction Pattern) 감지"""
    if len(closes) < 60:
        return {'score': 0, 'valid_vcp': False, 'num_contractions': 0}

    recent = closes[-60:]
    contractions = []
    window = 10

    for i in range(0, len(recent) - window, window):
        segment = recent[i:i + window]
        volatility = (np.max(segment) - np.min(segment)) / np.mean(segment) * 100
        contractions.append(volatility)

    # VCP: 변동성이 줄어드는 패턴
    num_contracting = 0
    for i in range(1, len(contractions)):
        if contractions[i] < contractions[i - 1]:
            num_contracting += 1

    total_pairs = max(len(contractions) - 1, 1)
    contraction_ratio = num_contracting / total_pairs

    # 최근 변동성이 초기 대비 줄었는지
    if len(contractions) >= 2:
        depth_reduction = 1 - (contractions[-1] / max(contractions[0], 0.01))
    else:
        depth_reduction = 0

    score = contraction_ratio * 60 + max(depth_reduction, 0) * 40
    valid = contraction_ratio >= 0.5 and depth_reduction > 0.2

    # 피벗 가격 (최근 고점)
    pivot_price = float(np.max(recent[-20:]))

    return {
        'score': round(min(score, 100)),
        'valid_vcp': valid,
        'num_contractions': num_contracting,
        'pivot_price': round(pivot_price, 2),
    }


def analyze_volume_pattern(volumes: np.ndarray) -> Dict:
    """거래량 패턴 분석 (dry-up 감지)"""
    if len(volumes) < 50:
        return {'score': 0, 'dry_up_ratio': 0}

    avg_50 = np.mean(volumes[-50:])
    recent_10 = np.mean(volumes[-10:])
    recent_5 = np.mean(volumes[-5:])

    # Dry-up: 최근 거래량이 평균 대비 줄어듦
    dry_up_ratio = recent_10 / max(avg_50, 1)

    if dry_up_ratio < 0.5:
        score = 90  # 강한 dry-up
    elif dry_up_ratio < 0.7:
        score = 70
    elif dry_up_ratio < 0.9:
        score = 50
    else:
        score = 30

    return {'score': score, 'dry_up_ratio': round(dry_up_ratio, 2)}


def calc_pivot_proximity(price: float, pivot: float) -> Dict:
    """피벗 근접도"""
    if pivot <= 0:
        return {'score': 0, 'distance_from_pivot_pct': 0, 'trade_status': 'Unknown'}

    distance_pct = ((pivot - price) / pivot) * 100

    if distance_pct <= 0:  # 피벗 돌파
        score, status = 90, 'BREAKOUT'
    elif distance_pct <= 3:
        score, status = 80, 'NEAR PIVOT'
    elif distance_pct <= 7:
        score, status = 60, 'APPROACHING'
    elif distance_pct <= 15:
        score, status = 40, 'BUILDING'
    else:
        score, status = 20, 'FAR'

    return {'score': score, 'distance_from_pivot_pct': round(distance_pct, 1), 'trade_status': status}


def estimate_relative_strength(closes: np.ndarray, benchmark_closes: Optional[np.ndarray] = None) -> Dict:
    """상대강도 추정"""
    if len(closes) < 60:
        return {'score': 0, 'rs_rank_estimate': 0}

    # 63일 수익률 기반 RS
    perf_3m = (closes[-1] / closes[-63] - 1) * 100 if len(closes) >= 63 else 0
    perf_1m = (closes[-1] / closes[-21] - 1) * 100 if len(closes) >= 21 else 0

    # 벤치마크 대비
    if benchmark_closes is not None and len(benchmark_closes) >= 63:
        bench_perf = (benchmark_closes[-1] / benchmark_closes[-63] - 1) * 100
        relative = perf_3m - bench_perf
    else:
        relative = perf_3m

    # 0~100 스코어
    if relative > 30:
        score, rank = 95, 95
    elif relative > 15:
        score, rank = 80, 80
    elif relative > 5:
        score, rank = 65, 65
    elif relative > 0:
        score, rank = 50, 50
    else:
        score, rank = 30, 30

    return {'score': score, 'rs_rank_estimate': rank}


def _ema(data: np.ndarray, period: int) -> np.ndarray:
    """Exponential Moving Average"""
    alpha = 2 / (period + 1)
    ema = np.zeros_like(data, dtype=float)
    ema[0] = data[0]
    for i in range(1, len(data)):
        ema[i] = alpha * data[i] + (1 - alpha) * ema[i - 1]
    return ema


def compute_composite(trend: Dict, vcp: Dict, volume: Dict, pivot: Dict, rs: Dict) -> Dict:
    """5개 컴포넌트 종합 점수"""
    weights = {'trend_template': 0.25, 'contraction_quality': 0.25, 'volume_pattern': 0.20,
               'pivot_proximity': 0.15, 'relative_strength': 0.15}

    weighted_sum = (
        trend['score'] * weights['trend_template'] +
        vcp['score'] * weights['contraction_quality'] +
        volume['score'] * weights['volume_pattern'] +
        pivot['score'] * weights['pivot_proximity'] +
        rs['score'] * weights['relative_strength']
    )

    score = round(weighted_sum, 1)

    if score >= 80:
        rating, desc = 'Textbook VCP', '교과서적 VCP 패턴'
    elif score >= 70:
        rating, desc = 'Strong VCP', '강한 VCP 패턴'
    elif score >= 60:
        rating, desc = 'Good VCP', '양호한 VCP 패턴'
    elif score >= 50:
        rating, desc = 'Developing VCP', '형성 중인 VCP 패턴'
    else:
        rating, desc = 'Weak', '약한 패턴'

    entry_ready = vcp['valid_vcp'] and pivot['score'] >= 80 and trend['passed']

    return {
        'composite_score': score,
        'rating': rating,
        'rating_description': desc,
        'guidance': '피벗 돌파 매수' if entry_ready else '거래량 확인 후 피벗 매수',
        'valid_vcp': vcp['valid_vcp'],
        'entry_ready': entry_ready,
        'weakest_component': min(
            [('Trend Template', trend['score']), ('VCP Pattern', vcp['score']),
             ('Volume Pattern', volume['score']), ('Pivot Proximity', pivot['score']),
             ('Relative Strength', rs['score'])],
            key=lambda x: x[1]
        )[0],
        'strongest_component': max(
            [('Trend Template', trend['score']), ('VCP Pattern', vcp['score']),
             ('Volume Pattern', volume['score']), ('Pivot Proximity', pivot['score']),
             ('Relative Strength', rs['score'])],
            key=lambda x: x[1]
        )[0],
        'component_breakdown': {
            'trend_template': {'score': trend['score'], 'weight': 0.25,
                               'weighted': round(trend['score'] * 0.25, 1), 'label': 'Trend Template (Stage 2)'},
            'contraction_quality': {'score': vcp['score'], 'weight': 0.25,
                                    'weighted': round(vcp['score'] * 0.25, 1), 'label': 'Contraction Quality'},
            'volume_pattern': {'score': volume['score'], 'weight': 0.20,
                               'weighted': round(volume['score'] * 0.20, 1), 'label': 'Volume Pattern'},
            'pivot_proximity': {'score': pivot['score'], 'weight': 0.15,
                                'weighted': round(pivot['score'] * 0.15, 1), 'label': 'Pivot Proximity'},
            'relative_strength': {'score': rs['score'], 'weight': 0.15,
                                  'weighted': round(rs['score'] * 0.15, 1), 'label': 'Relative Strength'},
        }
    }


# ── Market Scanners ───────────────────────────────────────────────────────

def scan_us_market() -> Dict:
    """US 마켓 VCP 스캔 — yfinance 기반"""
    import yfinance as yf

    start_time = time.time()
    logger.info("🇺🇸 US VCP 스캔 시작...")

    # US 시장 gate 정보
    gate, gate_score = _get_us_gate()

    # S&P 500 + 나스닥 주요 종목
    tickers = _get_us_watchlist()
    benchmark = _get_benchmark_closes('SPY')

    signals = []
    stage2_count = 0

    for ticker in tickers:
        try:
            hist = yf.download(ticker, period='1y', progress=False, timeout=10)
            if hist.empty or len(hist) < 100:
                continue

            closes = hist['Close'].values.flatten()
            volumes = hist['Volume'].values.flatten()

            trend = check_trend_template(closes)
            if not trend['passed']:
                continue

            stage2_count += 1

            vcp = detect_vcp_pattern(closes, volumes)
            vol = analyze_volume_pattern(volumes)
            pivot_prox = calc_pivot_proximity(float(closes[-1]), vcp['pivot_price'])
            rs = estimate_relative_strength(closes, benchmark)
            composite = compute_composite(trend, vcp, vol, pivot_prox, rs)

            if composite['composite_score'] >= 50:
                name = _get_ticker_name(ticker)
                signals.append({
                    'symbol': ticker,
                    'name': name,
                    'market': 'US',
                    'sector': '',
                    'price': round(float(closes[-1]), 2),
                    'composite': composite,
                    'trend_template': trend,
                    'vcp_pattern': vcp,
                    'volume_pattern': vol,
                    'pivot_proximity': pivot_prox,
                    'relative_strength': rs,
                    'stage': {'stage': trend['stage'], 'stage_label': trend['stage_label']},
                })
        except Exception as e:
            logger.debug(f"  {ticker} 스킵: {e}")
            continue

    signals.sort(key=lambda s: s['composite']['composite_score'], reverse=True)
    vcp_found = sum(1 for s in signals if s['vcp_pattern']['valid_vcp'])
    entry_ready = sum(1 for s in signals if s['composite']['entry_ready'])

    result = {
        'metadata': {
            'generated_at': datetime.now().isoformat(),
            'market': 'US',
            'gate': gate,
            'gate_score': gate_score,
            'processing_time_sec': round(time.time() - start_time, 1),
        },
        'summary': {
            'total_screened': len(tickers),
            'stage2_passed': stage2_count,
            'trend_passed': stage2_count,
            'vcp_found': vcp_found,
            'entry_ready': entry_ready,
        },
        'signals': signals,
    }

    _save_result(result, 'vcp_us_latest.json')
    logger.info(f"🇺🇸 US VCP 완료: {len(signals)} 시그널 (VCP: {vcp_found}, Entry: {entry_ready})")
    return result


def scan_crypto_market() -> Dict:
    """Crypto 마켓 VCP 스캔 — yfinance 기반"""
    import yfinance as yf

    start_time = time.time()
    logger.info("₿ Crypto VCP 스캔 시작...")

    gate, gate_score = _get_crypto_gate()
    tickers = _get_crypto_watchlist()
    benchmark = _get_benchmark_closes('BTC-USD')

    signals = []
    stage2_count = 0

    for ticker in tickers:
        try:
            hist = yf.download(ticker, period='1y', progress=False, timeout=10)
            if hist.empty or len(hist) < 60:
                continue

            closes = hist['Close'].values.flatten()
            volumes = hist['Volume'].values.flatten()

            trend = check_trend_template(closes)
            if not trend['passed']:
                continue

            stage2_count += 1

            vcp = detect_vcp_pattern(closes, volumes)
            vol = analyze_volume_pattern(volumes)
            pivot_prox = calc_pivot_proximity(float(closes[-1]), vcp['pivot_price'])
            rs = estimate_relative_strength(closes, benchmark)
            composite = compute_composite(trend, vcp, vol, pivot_prox, rs)

            if composite['composite_score'] >= 50:
                name = ticker.replace('-USD', '')
                signals.append({
                    'symbol': ticker.replace('-USD', ''),
                    'name': name,
                    'market': 'CRYPTO',
                    'sector': '',
                    'price': round(float(closes[-1]), 2),
                    'composite': composite,
                    'trend_template': trend,
                    'vcp_pattern': vcp,
                    'volume_pattern': vol,
                    'pivot_proximity': pivot_prox,
                    'relative_strength': rs,
                    'stage': {'stage': trend['stage'], 'stage_label': trend['stage_label']},
                })
        except Exception as e:
            logger.debug(f"  {ticker} 스킵: {e}")
            continue

    signals.sort(key=lambda s: s['composite']['composite_score'], reverse=True)
    vcp_found = sum(1 for s in signals if s['vcp_pattern']['valid_vcp'])
    entry_ready = sum(1 for s in signals if s['composite']['entry_ready'])

    result = {
        'metadata': {
            'generated_at': datetime.now().isoformat(),
            'market': 'CRYPTO',
            'gate': gate,
            'gate_score': gate_score,
            'processing_time_sec': round(time.time() - start_time, 1),
        },
        'summary': {
            'total_screened': len(tickers),
            'stage2_passed': stage2_count,
            'trend_passed': stage2_count,
            'vcp_found': vcp_found,
            'entry_ready': entry_ready,
        },
        'signals': signals,
    }

    _save_result(result, 'vcp_crypto_latest.json')
    logger.info(f"₿ Crypto VCP 완료: {len(signals)} 시그널 (VCP: {vcp_found}, Entry: {entry_ready})")
    return result


def scan_kr_market() -> Dict:
    """KR 마켓 VCP 스캔 — 기존 daily_prices.csv + yfinance 기반"""
    import yfinance as yf

    start_time = time.time()
    logger.info("🇰🇷 KR VCP 스캔 시작...")

    gate, gate_score = _get_kr_gate()
    tickers = _get_kr_watchlist()

    signals = []
    stage2_count = 0

    for code, name in tickers:
        try:
            ticker_yf = f"{code}.KS"
            hist = yf.download(ticker_yf, period='1y', progress=False, timeout=10)
            if hist.empty or len(hist) < 100:
                # KOSDAQ 시도
                ticker_yf = f"{code}.KQ"
                hist = yf.download(ticker_yf, period='1y', progress=False, timeout=10)
                if hist.empty or len(hist) < 100:
                    continue

            closes = hist['Close'].values.flatten()
            volumes = hist['Volume'].values.flatten()

            trend = check_trend_template(closes)
            if not trend['passed']:
                continue

            stage2_count += 1

            vcp = detect_vcp_pattern(closes, volumes)
            vol = analyze_volume_pattern(volumes)
            pivot_prox = calc_pivot_proximity(float(closes[-1]), vcp['pivot_price'])
            rs = estimate_relative_strength(closes)
            composite = compute_composite(trend, vcp, vol, pivot_prox, rs)

            if composite['composite_score'] >= 50:
                signals.append({
                    'symbol': code,
                    'name': name,
                    'market': 'KR',
                    'sector': '',
                    'price': round(float(closes[-1]), 2),
                    'composite': composite,
                    'trend_template': trend,
                    'vcp_pattern': vcp,
                    'volume_pattern': vol,
                    'pivot_proximity': pivot_prox,
                    'relative_strength': rs,
                    'stage': {'stage': trend['stage'], 'stage_label': trend['stage_label']},
                })
        except Exception as e:
            logger.debug(f"  {code} 스킵: {e}")
            continue

    signals.sort(key=lambda s: s['composite']['composite_score'], reverse=True)
    vcp_found = sum(1 for s in signals if s['vcp_pattern']['valid_vcp'])
    entry_ready = sum(1 for s in signals if s['composite']['entry_ready'])

    result = {
        'metadata': {
            'generated_at': datetime.now().isoformat(),
            'market': 'KR',
            'gate': gate,
            'gate_score': gate_score,
            'processing_time_sec': round(time.time() - start_time, 1),
        },
        'summary': {
            'total_screened': len(tickers),
            'stage2_passed': stage2_count,
            'trend_passed': stage2_count,
            'vcp_found': vcp_found,
            'entry_ready': entry_ready,
        },
        'signals': signals,
    }

    _save_result(result, 'vcp_kr_latest.json')
    logger.info(f"🇰🇷 KR VCP 완료: {len(signals)} 시그널 (VCP: {vcp_found}, Entry: {entry_ready})")
    return result


# ── Helpers ───────────────────────────────────────────────────────────────

def _save_result(data: Dict, filename: str):
    path = os.path.join(DATA_DIR, filename)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    logger.info(f"  💾 저장: {path}")


def _get_benchmark_closes(ticker: str) -> Optional[np.ndarray]:
    import yfinance as yf
    try:
        hist = yf.download(ticker, period='1y', progress=False, timeout=10)
        if not hist.empty:
            return hist['Close'].values.flatten()
    except:
        pass
    return None


def _get_ticker_name(ticker: str) -> str:
    """종목명 조회 (간단 매핑)"""
    names = {
        'AAPL': 'Apple', 'MSFT': 'Microsoft', 'GOOGL': 'Alphabet', 'AMZN': 'Amazon',
        'NVDA': 'NVIDIA', 'META': 'Meta', 'TSLA': 'Tesla', 'AMD': 'AMD',
        'NFLX': 'Netflix', 'AVGO': 'Broadcom', 'CRM': 'Salesforce', 'ORCL': 'Oracle',
        'ADBE': 'Adobe', 'INTC': 'Intel', 'QCOM': 'Qualcomm', 'TXN': 'Texas Instruments',
        'AMAT': 'Applied Materials', 'MU': 'Micron', 'LRCX': 'Lam Research', 'KLAC': 'KLA',
        'SNPS': 'Synopsys', 'CDNS': 'Cadence', 'MRVL': 'Marvell', 'ON': 'ON Semi',
        'PANW': 'Palo Alto', 'CRWD': 'CrowdStrike', 'FTNT': 'Fortinet', 'ZS': 'Zscaler',
        'NET': 'Cloudflare', 'DDOG': 'Datadog', 'SNOW': 'Snowflake', 'MDB': 'MongoDB',
        'PLTR': 'Palantir', 'COIN': 'Coinbase', 'SQ': 'Block', 'SHOP': 'Shopify',
        'UBER': 'Uber', 'ABNB': 'Airbnb', 'DASH': 'DoorDash', 'SPOT': 'Spotify',
        'LLY': 'Eli Lilly', 'UNH': 'UnitedHealth', 'JNJ': 'J&J', 'ABBV': 'AbbVie',
        'PFE': 'Pfizer', 'MRK': 'Merck', 'TMO': 'Thermo Fisher', 'ABT': 'Abbott',
        'ISRG': 'Intuitive Surgical', 'DXCM': 'DexCom', 'VEEV': 'Veeva',
        'JPM': 'JPMorgan', 'V': 'Visa', 'MA': 'Mastercard', 'BAC': 'Bank of America',
        'GS': 'Goldman Sachs', 'MS': 'Morgan Stanley', 'BLK': 'BlackRock',
        'XOM': 'Exxon', 'CVX': 'Chevron', 'COP': 'ConocoPhillips',
        'CAT': 'Caterpillar', 'DE': 'Deere', 'GE': 'GE Aerospace', 'HON': 'Honeywell',
        'RTX': 'RTX', 'LMT': 'Lockheed Martin', 'BA': 'Boeing',
        'COST': 'Costco', 'WMT': 'Walmart', 'HD': 'Home Depot', 'LOW': "Lowe's",
        'NKE': 'Nike', 'SBUX': 'Starbucks', 'MCD': "McDonald's",
        'DIS': 'Disney', 'CMCSA': 'Comcast', 'T': 'AT&T', 'VZ': 'Verizon',
        'AKAM': 'Akamai', 'WDAY': 'Workday', 'NOW': 'ServiceNow', 'TEAM': 'Atlassian',
        'TTD': 'Trade Desk', 'RBLX': 'Roblox', 'U': 'Unity',
        'ARM': 'Arm Holdings', 'SMCI': 'Super Micro', 'DELL': 'Dell',
        'APP': 'AppLovin', 'DUOL': 'Duolingo', 'HUBS': 'HubSpot',
    }
    return names.get(ticker, ticker)


def _get_us_watchlist() -> List[str]:
    """US 스캔 대상 — 대형+중형 성장주 100개"""
    return [
        # 반도체
        'NVDA', 'AMD', 'AVGO', 'QCOM', 'TXN', 'AMAT', 'MU', 'LRCX', 'KLAC', 'SNPS',
        'CDNS', 'MRVL', 'ON', 'ARM', 'SMCI',
        # 소프트웨어/클라우드
        'MSFT', 'CRM', 'ORCL', 'ADBE', 'NOW', 'WDAY', 'TEAM', 'SNOW', 'MDB', 'DDOG',
        'PLTR', 'HUBS', 'DUOL', 'APP', 'TTD',
        # 사이버보안
        'PANW', 'CRWD', 'FTNT', 'ZS', 'NET',
        # 빅테크
        'AAPL', 'GOOGL', 'AMZN', 'META', 'TSLA', 'NFLX',
        # 핀테크
        'V', 'MA', 'SQ', 'COIN', 'SHOP',
        # 헬스케어
        'LLY', 'UNH', 'ABBV', 'TMO', 'ISRG', 'DXCM', 'VEEV', 'ABT',
        # 금융
        'JPM', 'GS', 'MS', 'BLK', 'BAC',
        # 산업재
        'CAT', 'DE', 'GE', 'HON', 'RTX', 'LMT',
        # 소비재
        'COST', 'WMT', 'HD', 'LOW', 'NKE', 'MCD', 'SBUX',
        # 에너지
        'XOM', 'CVX', 'COP',
        # 기타
        'UBER', 'ABNB', 'DASH', 'SPOT', 'RBLX', 'DELL', 'AKAM',
        'DIS', 'CMCSA', 'PFE', 'MRK', 'JNJ', 'BA', 'INTC',
    ]


def _get_crypto_watchlist() -> List[str]:
    """Crypto 스캔 대상 — Top 50"""
    return [
        'BTC-USD', 'ETH-USD', 'BNB-USD', 'SOL-USD', 'XRP-USD',
        'ADA-USD', 'DOGE-USD', 'AVAX-USD', 'DOT-USD', 'LINK-USD',
        'MATIC-USD', 'UNI-USD', 'ATOM-USD', 'LTC-USD', 'FIL-USD',
        'NEAR-USD', 'APT-USD', 'ARB-USD', 'OP-USD', 'INJ-USD',
        'SUI-USD', 'SEI-USD', 'TIA-USD', 'RUNE-USD', 'AAVE-USD',
        'MKR-USD', 'SNX-USD', 'CRV-USD', 'COMP-USD', 'LDO-USD',
        'FET-USD', 'RNDR-USD', 'GRT-USD', 'IMX-USD', 'MANA-USD',
        'SAND-USD', 'AXS-USD', 'GALA-USD', 'ENJ-USD', 'CHZ-USD',
        'ALGO-USD', 'EOS-USD', 'XTZ-USD', 'FLOW-USD', 'HBAR-USD',
        'VET-USD', 'EGLD-USD', 'THETA-USD', 'ICP-USD', 'STX-USD',
    ]


def _get_kr_watchlist() -> List[str]:
    """KR 스캔 대상 — daily_prices.csv에서 상위 종목 추출"""
    import pandas as pd

    prices_path = os.path.join(DATA_DIR, 'daily_prices.csv')
    if os.path.exists(prices_path):
        try:
            df = pd.read_csv(prices_path, encoding='utf-8-sig')
            if 'ticker' in df.columns and 'name' in df.columns:
                df['ticker'] = df['ticker'].astype(str).str.zfill(6)
                # 거래대금 상위 또는 전체
                if 'trading_value' in df.columns:
                    df = df.sort_values('trading_value', ascending=False)
                pairs = list(zip(df['ticker'].tolist(), df['name'].tolist()))
                return pairs[:200]  # 상위 200개
        except Exception as e:
            logger.warning(f"daily_prices.csv 읽기 실패: {e}")

    # 폴백: 주요 종목
    return [
        ('005930', '삼성전자'), ('000660', 'SK하이닉스'), ('035420', 'NAVER'),
        ('035720', '카카오'), ('051910', 'LG화학'), ('006400', '삼성SDI'),
        ('068270', '셀트리온'), ('207940', '삼성바이오로직스'), ('005380', '현대차'),
        ('000270', '기아'), ('028260', '삼성물산'), ('012330', '현대모비스'),
        ('003670', '포스코퓨처엠'), ('003490', '대한항공'), ('034730', 'SK'),
        ('036570', 'NCsoft'), ('251270', '넷마블'), ('263750', '펄어비스'),
        ('293490', '카카오게임즈'), ('259960', '크래프톤'), ('377300', '카카오페이'),
        ('352820', '하이브'), ('247540', '에코프로비엠'), ('086520', '에코프로'),
        ('373220', 'LG에너지솔루션'),
    ]


def _get_us_gate() -> tuple:
    """US 마켓 게이트 정보"""
    try:
        gate_path = os.path.join(BASE_DIR, 'us_market', 'output', 'market_data.json')
        if os.path.exists(gate_path):
            with open(gate_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            vix = data.get('volatility', {}).get('^VIX', {}).get('current', 20)
            if vix > 30:
                return 'RED', 25
            elif vix > 20:
                return 'YELLOW', 50
            else:
                return 'GREEN', 75
    except:
        pass
    return 'YELLOW', 50


def _get_crypto_gate() -> tuple:
    """Crypto 마켓 게이트 정보"""
    try:
        gate_path = os.path.join(BASE_DIR, 'crypto-analytics', 'crypto_market', 'output', 'market_gate.json')
        if os.path.exists(gate_path):
            with open(gate_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data.get('gate', 'YELLOW'), data.get('score', 50)
    except:
        pass
    return 'YELLOW', 50


def _get_kr_gate() -> tuple:
    """KR 마켓 게이트 정보"""
    try:
        cache_path = os.path.join(DATA_DIR, 'market_gate_cache.json')
        if os.path.exists(cache_path):
            with open(cache_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            score = data.get('score', data.get('gate_score', 50))
            if score >= 60:
                return 'GREEN', score
            elif score >= 40:
                return 'YELLOW', score
            else:
                return 'RED', score
    except:
        pass
    return 'YELLOW', 50


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='VCP Enhanced Scanner')
    parser.add_argument('--market', choices=['US', 'KR', 'CRYPTO'], help='스캔할 마켓')
    parser.add_argument('--all', action='store_true', help='전체 마켓 스캔')
    args = parser.parse_args()

    os.makedirs(DATA_DIR, exist_ok=True)

    if args.all:
        scan_us_market()
        scan_crypto_market()
        scan_kr_market()
    elif args.market == 'US':
        scan_us_market()
    elif args.market == 'KR':
        scan_kr_market()
    elif args.market == 'CRYPTO':
        scan_crypto_market()
    else:
        print("Usage: python vcp_enhanced_scanner.py --market US|KR|CRYPTO | --all")


if __name__ == '__main__':
    main()

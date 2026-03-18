# app/utils/helpers.py
"""공통 유틸리티 함수들"""

import pandas as pd
import numpy as np


def calculate_rsi(series, period=14):
    """RSI (Relative Strength Index) 계산"""
    delta = series.diff(1)
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def analyze_trend(df):
    """트렌드 분석 - MA 기반 점수 및 시그널 반환"""
    if len(df) < 50:
        return 50, "Neutral", 0
    
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    
    ma20 = curr['MA20']
    ma50 = curr['MA50']
    ma200 = curr['MA200']
    price = curr['Close']
    rsi = curr['RSI']
    
    score = 50
    signal = "Neutral"
    
    # Simple Trend Logic
    if price > ma20 > ma50 > ma200:
        score = 90
        signal = "Strong Buy"
    elif ma20 > ma50 and (prev['MA20'] <= prev['MA50'] or price > ma20):
        score = 80
        signal = "Buy (Golden Cross)"
    elif price < ma20 < ma50:
        score = 30
        signal = "Sell (Downtrend)"
    elif rsi > 75:
        score -= 10
        signal = "Overbought"
        
    return score, signal, rsi


def format_currency(value, currency='KRW'):
    """통화 포맷팅"""
    if currency == 'KRW':
        return f"₩{value:,.0f}"
    elif currency == 'USD':
        return f"${value:,.2f}"
    return f"{value:,.2f}"


def format_percent(value, decimals=2):
    """퍼센트 포맷팅"""
    if value is None or pd.isna(value):
        return "-"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.{decimals}f}%"

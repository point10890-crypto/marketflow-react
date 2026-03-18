#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
US Economic Indicators Data Collector
FRED API + yfinance를 통한 미국 경제 지표 수집
"""

import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import logging

from dotenv import load_dotenv

# Load .env from parent directory
load_dotenv()
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

from .cache_manager import CacheManager
from . import US_INDICATORS

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class USDataCollector:
    """미국 경제 지표 수집기 (FRED + yfinance)"""
    
    def __init__(self):
        self.fred_api_key = os.getenv('FRED_API_KEY')
        self.cache = CacheManager('us_indicators_cache.db')
        
        # FRED API base URL
        self.fred_base_url = "https://api.stlouisfed.org/fred/series/observations"
    
    def get_fred_data(self, series_id: str, start_date: str = None, 
                      end_date: str = None) -> pd.DataFrame:
        """
        FRED API에서 시계열 데이터 조회
        
        Args:
            series_id: FRED 시리즈 ID (예: 'DGS10')
            start_date: 시작일 (YYYY-MM-DD)
            end_date: 종료일 (YYYY-MM-DD)
        """
        import requests
        
        # 기본값 설정
        if not end_date:
            end_date = datetime.now().strftime('%Y-%m-%d')
        if not start_date:
            start_date = (datetime.now() - timedelta(days=365*5)).strftime('%Y-%m-%d')
        
        # 캐시 확인
        cache_key = f"fred_{series_id}_{start_date}_{end_date}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            logger.debug(f"Cache hit: {series_id}")
            return cached
        
        # API 호출
        params = {
            'series_id': series_id,
            'api_key': self.fred_api_key,
            'file_type': 'json',
            'observation_start': start_date,
            'observation_end': end_date,
        }
        
        try:
            response = requests.get(self.fred_base_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if 'observations' not in data:
                logger.warning(f"No observations for {series_id}")
                return pd.DataFrame()
            
            df = pd.DataFrame(data['observations'])
            df['date'] = pd.to_datetime(df['date'])
            df['value'] = pd.to_numeric(df['value'], errors='coerce')
            df = df[['date', 'value']].dropna()
            
            # 캐시 저장 (1시간)
            self.cache.set(cache_key, df, ttl=3600)
            
            return df
            
        except Exception as e:
            logger.error(f"FRED API error for {series_id}: {e}")
            return pd.DataFrame()
    
    def get_yfinance_data(self, ticker: str, period: str = '5y') -> pd.DataFrame:
        """
        yfinance에서 시장 데이터 조회
        
        Args:
            ticker: 티커 심볼
            period: 기간 ('1y', '2y', '5y', 'max')
        """
        import yfinance as yf
        
        # 캐시 확인
        cache_key = f"yf_{ticker}_{period}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            logger.debug(f"Cache hit: {ticker}")
            return cached
        
        try:
            data = yf.download(ticker, period=period, progress=False)
            
            if data.empty:
                return pd.DataFrame()
            
            df = pd.DataFrame({
                'date': data.index,
                'value': data['Close'].values
            })
            df['date'] = pd.to_datetime(df['date'])
            
            # 캐시 저장 (30분 - 시장 데이터는 더 자주 업데이트)
            self.cache.set(cache_key, df, ttl=1800)
            
            return df
            
        except Exception as e:
            logger.error(f"yfinance error for {ticker}: {e}")
            return pd.DataFrame()
    
    def get_indicator_data(self, indicator_id: str) -> Dict:
        """단일 지표 현재 데이터 조회"""
        
        # 지표 정보 찾기
        for category, config in US_INDICATORS.items():
            if indicator_id in config['indicators']:
                source = config['source']
                name = config['indicators'][indicator_id]
                break
        else:
            return {}
        
        # 데이터 조회
        if source == 'FRED':
            df = self.get_fred_data(indicator_id)
        else:  # yfinance
            df = self.get_yfinance_data(indicator_id)
        
        if df.empty:
            return {}
        
        # 현재값 및 변동 계산
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else latest
        
        change = latest['value'] - prev['value']
        change_pct = (change / prev['value'] * 100) if prev['value'] != 0 else 0
        
        return {
            indicator_id: {
                'name': name,
                'value': round(latest['value'], 4),
                'date': latest['date'].strftime('%Y-%m-%d'),
                'change': round(change, 4),
                'change_pct': round(change_pct, 2),
                'source': source,
            }
        }
    
    def get_all_indicators(self, category: str = 'all') -> Dict:
        """모든 미국 지표 현재값 조회"""
        logger.info(f"📊 Fetching US indicators (category: {category})...")
        
        results = {}
        
        for cat_name, config in US_INDICATORS.items():
            if category != 'all' and cat_name != category:
                continue
            
            results[cat_name] = {}
            
            for ind_id, ind_name in config['indicators'].items():
                data = self.get_indicator_data(ind_id)
                if data:
                    results[cat_name].update(data)
        
        return results
    
    def get_chart_data(self, indicator_id: str, period: str = '5y',
                       transform: str = 'raw') -> Dict:
        """
        차트용 시계열 데이터
        
        Args:
            indicator_id: 지표 ID
            period: 기간
            transform: 'raw', 'mom' (전월비), 'yoy' (전년비)
        """
        # 지표 정보 찾기
        source = 'FRED'
        for category, config in US_INDICATORS.items():
            if indicator_id in config['indicators']:
                source = config['source']
                break
        
        # 데이터 조회
        if source == 'FRED':
            df = self.get_fred_data(indicator_id)
        else:
            df = self.get_yfinance_data(indicator_id, period)
        
        if df.empty:
            return {'error': 'No data available'}
        
        # 변환 적용
        if transform == 'mom':
            df['value'] = df['value'].pct_change() * 100
        elif transform == 'yoy':
            df['value'] = df['value'].pct_change(periods=12) * 100
        
        df = df.dropna()
        
        return {
            'dates': df['date'].dt.strftime('%Y-%m-%d').tolist(),
            'values': df['value'].round(4).tolist(),
            'transform': transform,
            'indicator_id': indicator_id,
        }


if __name__ == "__main__":
    # 테스트
    collector = USDataCollector()
    
    print("\n📊 US Data Collector Test\n")
    
    # 단일 지표 테스트
    dgs10 = collector.get_indicator_data('DGS10')
    print(f"DGS10 (10Y Treasury): {dgs10}")
    
    # 시장 데이터 테스트
    vix = collector.get_indicator_data('^VIX')
    print(f"VIX: {vix}")
    
    # 차트 데이터 테스트
    chart = collector.get_chart_data('CPIAUCSL', transform='yoy')
    print(f"\nCPI YoY Chart Data (last 5 points): {chart['values'][-5:]}")
    
    print("\n✅ USDataCollector test passed!")

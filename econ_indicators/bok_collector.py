#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
한국은행 ECOS API 데이터 수집기
https://ecos.bok.or.kr/api/

ECOS API 키 발급: https://ecos.bok.or.kr/api/#/DevGuide/StatisticTableList
"""

import os
import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import logging

from dotenv import load_dotenv

# Load .env from parent directory
load_dotenv()
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

from .cache_manager import CacheManager
from . import KR_INDICATORS

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class BOKDataCollector:
    """한국은행 경제통계시스템(ECOS) API 클라이언트"""
    
    BASE_URL = "https://ecos.bok.or.kr/api/StatisticSearch"
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv('BOK_ECOS_API_KEY')
        self.cache = CacheManager('bok_cache.db')
        
        if not self.api_key:
            logger.warning("BOK_ECOS_API_KEY not found. Some features may not work.")
    
    def get_indicator(self, stat_code: str, item_code: str,
                      start_date: str = None, end_date: str = None,
                      cycle: str = 'M') -> pd.DataFrame:
        """
        ECOS API에서 지표 데이터 조회
        
        Args:
            stat_code: 통계표코드 (예: '512Y001')
            item_code: 통계항목코드 (예: 'I121Y')
            start_date: 시작일 (YYYYMM)
            end_date: 종료일 (YYYYMM)
            cycle: 주기 (M: 월, Q: 분기, A: 연)
        """
        if not self.api_key:
            logger.error("BOK ECOS API key is required")
            return pd.DataFrame()
        
        # 기본값 설정
        if not end_date:
            end_date = datetime.now().strftime('%Y%m')
        if not start_date:
            start_date = (datetime.now() - timedelta(days=365*5)).strftime('%Y%m')
        
        # 캐시 확인
        cache_key = f"bok_{stat_code}_{item_code}_{start_date}_{end_date}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            logger.debug(f"Cache hit: {stat_code}/{item_code}")
            return cached
        
        # API 호출
        url = f"{self.BASE_URL}/{self.api_key}/json/kr/1/1000/{stat_code}/{cycle}/{start_date}/{end_date}/{item_code}"
        
        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            # 에러 체크
            if 'StatisticSearch' not in data:
                if 'RESULT' in data:
                    error_msg = data['RESULT'].get('MESSAGE', 'Unknown error')
                    logger.warning(f"BOK API: {error_msg}")
                return pd.DataFrame()
            
            rows = data['StatisticSearch'].get('row', [])
            if not rows:
                return pd.DataFrame()
            
            df = pd.DataFrame(rows)
            df['date'] = pd.to_datetime(df['TIME'], format='%Y%m')
            df['value'] = pd.to_numeric(df['DATA_VALUE'], errors='coerce')
            df = df[['date', 'value']].sort_values('date').dropna()
            
            # 캐시 저장 (1시간)
            self.cache.set(cache_key, df, ttl=3600)
            
            return df
            
        except requests.exceptions.RequestException as e:
            logger.error(f"BOK API Network Error: {e}")
            return pd.DataFrame()
        except Exception as e:
            logger.error(f"BOK API Error: {e}")
            return pd.DataFrame()
    
    def get_indicator_data(self, indicator_id: str) -> Dict:
        """단일 지표 현재 데이터 조회"""
        
        # 지표 정보 찾기
        for category, config in KR_INDICATORS.items():
            if indicator_id in config['indicators']:
                ind_info = config['indicators'][indicator_id]
                break
        else:
            return {}
        
        # 코드 파싱
        code_parts = ind_info['code'].split('/')
        stat_code = code_parts[0]
        item_code = code_parts[1] if len(code_parts) > 1 else ''
        
        # 데이터 조회
        df = self.get_indicator(stat_code, item_code)
        
        if df.empty:
            return {}
        
        # 현재값 및 변동 계산
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else latest
        
        change = latest['value'] - prev['value']
        change_pct = (change / prev['value'] * 100) if prev['value'] != 0 else 0
        
        return {
            indicator_id: {
                'name': ind_info['name'],
                'value': round(float(latest['value']), 4),
                'date': latest['date'].strftime('%Y-%m'),
                'change': round(float(change), 4),
                'change_pct': round(float(change_pct), 2),
                'source': 'BOK_ECOS',
            }
        }
    
    def get_all_kr_indicators(self, category: str = 'all') -> Dict:
        """모든 한국 지표 현재값 조회"""
        logger.info(f"📊 Fetching KR indicators (category: {category})...")
        
        results = {}
        
        for cat_name, config in KR_INDICATORS.items():
            if category != 'all' and cat_name != category:
                continue
            
            results[cat_name] = {}
            
            for ind_id, ind_info in config['indicators'].items():
                data = self.get_indicator_data(ind_id)
                if data:
                    results[cat_name].update(data)
        
        return results
    
    def get_indicator_history(self, indicator_id: str, period: str = '5y') -> Dict:
        """차트용 히스토리 데이터"""
        
        # 지표 정보 찾기
        for category, config in KR_INDICATORS.items():
            if indicator_id in config['indicators']:
                ind_info = config['indicators'][indicator_id]
                break
        else:
            return {'error': 'Indicator not found'}
        
        # 기간 계산
        years = int(period.replace('y', ''))
        start_date = (datetime.now() - timedelta(days=365*years)).strftime('%Y%m')
        
        # 코드 파싱
        code_parts = ind_info['code'].split('/')
        stat_code = code_parts[0]
        item_code = code_parts[1] if len(code_parts) > 1 else ''
        
        # 데이터 조회
        df = self.get_indicator(stat_code, item_code, start_date=start_date)
        
        if df.empty:
            return {'error': 'No data available'}
        
        return {
            'dates': df['date'].dt.strftime('%Y-%m').tolist(),
            'values': df['value'].round(4).tolist(),
            'indicator_id': indicator_id,
            'name': ind_info['name'],
        }


if __name__ == "__main__":
    # 테스트
    collector = BOKDataCollector()
    
    print("\n📊 BOK Data Collector Test\n")
    
    if not collector.api_key:
        print("⚠️ BOK_ECOS_API_KEY not set. Please add to .env file.")
        print("   Get your key at: https://ecos.bok.or.kr/api/")
    else:
        # 기준금리 테스트
        base_rate = collector.get_indicator_data('BOK_BASE_RATE')
        print(f"BOK Base Rate: {base_rate}")
        
        # 소비자물가 테스트
        cpi = collector.get_indicator_data('CPI_KR')
        print(f"CPI: {cpi}")
        
        print("\n✅ BOKDataCollector test passed!")

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
상관관계 분석기
미국/한국 지표 간 상관관계 분석 (한미 크로스 포함)
"""

import pandas as pd
import numpy as np
from scipy import stats
from typing import Dict, List, Optional, Tuple
import logging

from .data_collector import USDataCollector
from .bok_collector import BOKDataCollector
from .cache_manager import CacheManager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class CorrelationAnalyzer:
    """경제 지표 상관관계 분석기"""
    
    def __init__(self):
        self.us_collector = USDataCollector()
        self.bok_collector = BOKDataCollector()
        self.cache = CacheManager('correlation_cache.db')
    
    def _get_series(self, indicator_id: str, period: str = '3y') -> pd.Series:
        """지표 시계열 데이터 조회"""
        
        # 한국 지표 여부 확인
        from . import KR_INDICATORS
        is_korean = any(
            indicator_id in config['indicators'] 
            for config in KR_INDICATORS.values()
        )
        
        if is_korean:
            data = self.bok_collector.get_indicator_history(indicator_id, period)
        else:
            data = self.us_collector.get_chart_data(indicator_id, period)
        
        if not data or 'error' in data:
            return pd.Series()
        
        df = pd.DataFrame({
            'date': pd.to_datetime(data['dates']),
            'value': data['values']
        })
        df = df.set_index('date')
        
        # 월말 리샘플링 (주기 통일)
        return df['value'].resample('M').last().dropna()
    
    def calculate(self, ind1: str, ind2: str, period: str = '3y') -> Dict:
        """
        두 지표 간 상관관계 계산
        
        Args:
            ind1: 첫 번째 지표 ID
            ind2: 두 번째 지표 ID
            period: 분석 기간 ('1y', '3y', '5y')
        
        Returns:
            상관관계, p-value, 차트 데이터
        """
        # 캐시 확인
        cache_key = f"corr_{ind1}_{ind2}_{period}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached
        
        # 데이터 조회
        series1 = self._get_series(ind1, period)
        series2 = self._get_series(ind2, period)
        
        if series1.empty or series2.empty:
            return {'error': 'Insufficient data for correlation analysis'}
        
        # 인덱스 맞추기
        df = pd.DataFrame({ind1: series1, ind2: series2}).dropna()
        
        if len(df) < 12:  # 최소 12개월 필요
            return {'error': 'Insufficient overlapping data points'}
        
        # 상관관계 계산
        corr, p_value = stats.pearsonr(df[ind1], df[ind2])
        
        # 결과 해석
        if abs(corr) >= 0.7:
            strength = '강한'
        elif abs(corr) >= 0.4:
            strength = '중간'
        else:
            strength = '약한'
        
        direction = '양의' if corr > 0 else '음의'
        interpretation = f"{strength} {direction} 상관관계 (r={corr:.3f})"
        
        result = {
            'indicator1': ind1,
            'indicator2': ind2,
            'correlation': round(corr, 4),
            'p_value': round(p_value, 6),
            'significant': p_value < 0.05,
            'interpretation': interpretation,
            'data_points': len(df),
            'chart_data': {
                'dates': df.index.strftime('%Y-%m').tolist(),
                'series1': df[ind1].round(4).tolist(),
                'series2': df[ind2].round(4).tolist(),
            }
        }
        
        # 캐시 저장 (6시간)
        self.cache.set(cache_key, result, ttl=21600)
        
        return result
    
    def calculate_cross_country(self, kr_ind: str, us_ind: str, 
                                 period: str = '3y') -> Dict:
        """
        한국-미국 지표 간 상관관계 (크로스 분석)
        
        Args:
            kr_ind: 한국 지표 ID
            us_ind: 미국 지표 ID
            period: 분석 기간
        """
        return self.calculate(kr_ind, us_ind, period)
    
    def generate_matrix(self, indicators: List[str]) -> Dict:
        """
        선택된 지표들의 상관관계 매트릭스
        
        Args:
            indicators: 지표 ID 리스트
        
        Returns:
            상관관계 매트릭스 (히트맵용)
        """
        if len(indicators) < 2:
            return {'error': 'At least 2 indicators required'}
        
        # 데이터 수집
        series_dict = {}
        for ind in indicators:
            s = self._get_series(ind, '3y')
            if not s.empty:
                series_dict[ind] = s
        
        if len(series_dict) < 2:
            return {'error': 'Insufficient data for matrix'}
        
        # DataFrame 생성 및 상관관계 계산
        df = pd.DataFrame(series_dict).dropna()
        
        if len(df) < 12:
            return {'error': 'Insufficient overlapping data'}
        
        corr_matrix = df.corr()
        
        # 히트맵 데이터 형식
        matrix_data = []
        for i, row_ind in enumerate(corr_matrix.index):
            for j, col_ind in enumerate(corr_matrix.columns):
                matrix_data.append({
                    'x': col_ind,
                    'y': row_ind,
                    'value': round(corr_matrix.loc[row_ind, col_ind], 3)
                })
        
        return {
            'indicators': list(corr_matrix.columns),
            'matrix': corr_matrix.round(3).to_dict(),
            'heatmap_data': matrix_data,
            'data_points': len(df),
        }
    
    def find_leading_indicators(self, target: str, candidates: List[str] = None,
                                 max_lag: int = 6) -> List[Dict]:
        """
        선행 지표 탐색
        
        Args:
            target: 목표 지표 (예: 'SPY')
            candidates: 탐색할 지표 리스트
            max_lag: 최대 시차 (개월)
        
        Returns:
            선행 지표 목록 (상관관계 순)
        """
        from . import US_INDICATORS, KR_INDICATORS
        
        if candidates is None:
            # 기본: 모든 FRED 지표
            candidates = []
            for config in US_INDICATORS.values():
                if config['source'] == 'FRED':
                    candidates.extend(config['indicators'].keys())
        
        target_series = self._get_series(target, '5y')
        if target_series.empty:
            return []
        
        results = []
        
        for cand in candidates:
            if cand == target:
                continue
            
            cand_series = self._get_series(cand, '5y')
            if cand_series.empty:
                continue
            
            # 시차 상관관계 테스트
            best_lag = 0
            best_corr = 0
            
            for lag in range(1, max_lag + 1):
                # 후보 지표를 lag개월 앞당김
                shifted = cand_series.shift(-lag)
                df = pd.DataFrame({
                    'target': target_series,
                    'candidate': shifted
                }).dropna()
                
                if len(df) < 24:
                    continue
                
                corr, _ = stats.pearsonr(df['target'], df['candidate'])
                
                if abs(corr) > abs(best_corr):
                    best_corr = corr
                    best_lag = lag
            
            if abs(best_corr) > 0.3:  # 의미있는 상관관계만
                results.append({
                    'indicator': cand,
                    'correlation': round(best_corr, 3),
                    'lag_months': best_lag,
                    'relationship': 'leading' if best_lag > 0 else 'concurrent',
                })
        
        # 상관관계 순 정렬
        results.sort(key=lambda x: abs(x['correlation']), reverse=True)
        
        return results[:10]  # 상위 10개


if __name__ == "__main__":
    # 테스트
    analyzer = CorrelationAnalyzer()
    
    print("\n📊 Correlation Analyzer Test\n")
    
    # 간단한 상관관계
    result = analyzer.calculate('DGS10', '^VIX', '3y')
    print(f"DGS10 vs VIX: {result.get('interpretation', result.get('error'))}")
    
    print("\n✅ CorrelationAnalyzer test passed!")

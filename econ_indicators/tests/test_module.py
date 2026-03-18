#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
econ_indicators 모듈 테스트
"""

import unittest
import sys
import os

# 상위 디렉토리 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


class TestCacheManager(unittest.TestCase):
    """CacheManager 테스트"""
    
    def test_set_and_get(self):
        from econ_indicators.cache_manager import CacheManager
        cache = CacheManager('test_cache.db')
        
        cache.set('test_key', {'value': 123}, ttl=60)
        result = cache.get('test_key')
        
        self.assertEqual(result['value'], 123)
        cache.delete('test_key')


class TestSectorTracker(unittest.TestCase):
    """SectorScoreTracker 테스트"""
    
    def test_add_score(self):
        from econ_indicators.bok_sector_tracker import SectorScoreTracker
        tracker = SectorScoreTracker('data/test_sector_scores.db')
        
        tracker.add_score('2024-01', 'SEC', 3, 'Test event')
        scores = tracker.get_cumulative_scores()
        
        self.assertIn('SEC', scores)
        self.assertGreaterEqual(scores['SEC'], 3)
    
    def test_invalid_sector(self):
        from econ_indicators.bok_sector_tracker import SectorScoreTracker
        tracker = SectorScoreTracker('data/test_sector_scores.db')
        
        with self.assertRaises(ValueError):
            tracker.add_score('2024-01', 'INVALID', 3)
    
    def test_invalid_score(self):
        from econ_indicators.bok_sector_tracker import SectorScoreTracker
        tracker = SectorScoreTracker('data/test_sector_scores.db')
        
        with self.assertRaises(ValueError):
            tracker.add_score('2024-01', 'SEC', 10)  # 범위 초과


class TestUSDataCollector(unittest.TestCase):
    """USDataCollector 테스트"""
    
    def test_indicator_lookup(self):
        from econ_indicators import US_INDICATORS
        
        # 지표가 정의되어 있는지 확인
        self.assertIn('Interest Rates', US_INDICATORS)
        self.assertIn('DGS10', US_INDICATORS['Interest Rates']['indicators'])


class TestKRIndicators(unittest.TestCase):
    """KR Indicators 테스트"""
    
    def test_kr_indicator_lookup(self):
        from econ_indicators import KR_INDICATORS
        
        self.assertIn('Interest Rates', KR_INDICATORS)
        self.assertIn('BOK_BASE_RATE', KR_INDICATORS['Interest Rates']['indicators'])
    
    def test_sector_definitions(self):
        from econ_indicators import KR_SECTOR_SCORES
        
        self.assertEqual(len(KR_SECTOR_SCORES), 8)
        self.assertIn('SEC', KR_SECTOR_SCORES)
        self.assertIn('CON', KR_SECTOR_SCORES)


if __name__ == '__main__':
    unittest.main(verbosity=2)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
한국 섹터별 경제 점수 추적 시스템
2019년 1월부터 월별 섹터 점수 (-5 ~ +5) 관리

8개 섹터:
- SEC: 반도체/IT
- CON: 건설/부동산
- FIN: 금융/은행
- MFG: 일반제조
- SVC: 서비스
- EXP: 수출/무역
- EMP: 고용/노동
- CPI: 물가/인플레
"""

import sqlite3
import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path

from . import KR_SECTOR_SCORES


class SectorScoreTracker:
    """섹터별 경제 점수 추적기"""
    
    SECTORS = ['SEC', 'CON', 'FIN', 'MFG', 'SVC', 'EXP', 'EMP', 'CPI']
    
    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = Path(__file__).parent.parent / 'data' / 'sector_scores.db'
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """데이터베이스 초기화"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sector_monthly_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                year_month TEXT NOT NULL,
                sector_code TEXT NOT NULL,
                score INTEGER NOT NULL CHECK(score >= -5 AND score <= 5),
                event TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(year_month, sector_code)
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_year_month 
            ON sector_monthly_scores(year_month)
        """)
        
        conn.commit()
        conn.close()
    
    def add_score(self, year_month: str, sector: str, score: int, event: str = None):
        """
        월별 섹터 점수 추가/업데이트
        
        Args:
            year_month: '2024-12' 형식
            sector: 섹터 코드 (SEC, CON, FIN, MFG, SVC, EXP, EMP, CPI)
            score: -5 ~ +5 사이의 점수
            event: 관련 이벤트 설명
        """
        if sector not in self.SECTORS:
            raise ValueError(f"Invalid sector: {sector}. Must be one of {self.SECTORS}")
        if not -5 <= score <= 5:
            raise ValueError(f"Score must be between -5 and 5, got {score}")
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO sector_monthly_scores 
            (year_month, sector_code, score, event)
            VALUES (?, ?, ?, ?)
        """, (year_month, sector, score, event))
        
        conn.commit()
        conn.close()
    
    def add_bulk_scores(self, data: List[Dict]):
        """
        대량 점수 입력
        
        Args:
            data: [{'year_month': '2024-12', 'sector': 'SEC', 'score': 2, 'event': '...'}]
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        for row in data:
            cursor.execute("""
                INSERT OR REPLACE INTO sector_monthly_scores 
                (year_month, sector_code, score, event)
                VALUES (?, ?, ?, ?)
            """, (row['year_month'], row['sector'], row['score'], row.get('event')))
        
        conn.commit()
        conn.close()
    
    def get_cumulative_scores(self) -> Dict[str, int]:
        """현재 누적 점수 반환"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT sector_code, SUM(score) as cumulative
            FROM sector_monthly_scores
            GROUP BY sector_code
        """)
        
        results = {row[0]: row[1] for row in cursor.fetchall()}
        conn.close()
        
        # 모든 섹터에 대해 결과 반환 (없으면 0)
        return {sector: results.get(sector, 0) for sector in self.SECTORS}
    
    def get_sector_history(self, sector: str = None, 
                           start_date: str = '2019-01') -> pd.DataFrame:
        """섹터별 히스토리 조회"""
        conn = sqlite3.connect(self.db_path)
        
        if sector:
            query = """
                SELECT year_month, sector_code, score, event
                FROM sector_monthly_scores
                WHERE sector_code = ? AND year_month >= ?
                ORDER BY year_month
            """
            df = pd.read_sql_query(query, conn, params=(sector, start_date))
        else:
            query = """
                SELECT year_month, sector_code, score, event
                FROM sector_monthly_scores
                WHERE year_month >= ?
                ORDER BY year_month, sector_code
            """
            df = pd.read_sql_query(query, conn, params=(start_date,))
        
        conn.close()
        return df
    
    def get_cumulative_history(self) -> pd.DataFrame:
        """월별 누적 점수 히스토리 (차트용)"""
        df = self.get_sector_history()
        
        if df.empty:
            return pd.DataFrame()
        
        # 피벗 테이블 생성
        pivot = df.pivot(index='year_month', columns='sector_code', values='score')
        pivot = pivot.fillna(0)
        
        # 누적 합계 계산
        cumulative = pivot.cumsum()
        cumulative['TOTAL'] = cumulative.sum(axis=1)
        
        return cumulative.reset_index()
    
    def get_yearly_summary(self) -> pd.DataFrame:
        """연도별 요약 (히트맵용)"""
        df = self.get_sector_history()
        
        if df.empty:
            return pd.DataFrame()
        
        df['year'] = df['year_month'].str[:4]
        
        yearly = df.groupby(['year', 'sector_code'])['score'].sum().unstack(fill_value=0)
        yearly['TOTAL'] = yearly.sum(axis=1)
        
        return yearly.reset_index()
    
    def get_status(self, score: int) -> Dict:
        """점수에 따른 상태 반환"""
        if score >= 20:
            return {'status': '강세', 'emoji': '🟢', 'color': '#00ff88'}
        elif score >= 10:
            return {'status': '양호', 'emoji': '🔵', 'color': '#00d4ff'}
        elif score >= -10:
            return {'status': '중립', 'emoji': '⚪', 'color': '#888888'}
        elif score >= -20:
            return {'status': '부진', 'emoji': '🟡', 'color': '#ffa502'}
        else:
            return {'status': '위기', 'emoji': '🔴', 'color': '#ff4757'}
    
    def get_dashboard_data(self) -> Dict:
        """대시보드용 종합 데이터"""
        cumulative = self.get_cumulative_scores()
        
        sectors = []
        for code in self.SECTORS:
            info = KR_SECTOR_SCORES.get(code, {})
            score = cumulative.get(code, 0)
            status_info = self.get_status(score)
            
            sectors.append({
                'code': code,
                'name_kr': info.get('name_kr', code),
                'name_en': info.get('name_en', code),
                'cumulative_score': score,
                'status': status_info['status'],
                'emoji': status_info['emoji'],
                'color': status_info['color'],
                'description': info.get('description', ''),
            })
        
        return {
            'sectors': sectors,
            'last_updated': datetime.now().strftime('%Y-%m'),
            'total_score': sum(cumulative.values()),
        }
    
    def load_initial_data(self):
        """2019-2025 초기 데이터 로드 (예시)"""
        # 주요 이벤트 기반 점수 데이터
        initial_data = [
            # 2019년 - 미중무역갈등, 일본수출규제
            {'year_month': '2019-01', 'sector': 'SEC', 'score': 0, 'event': '기준점'},
            {'year_month': '2019-01', 'sector': 'CON', 'score': 0, 'event': '기준점'},
            {'year_month': '2019-01', 'sector': 'FIN', 'score': 0, 'event': '기준점'},
            {'year_month': '2019-01', 'sector': 'MFG', 'score': 0, 'event': '기준점'},
            {'year_month': '2019-01', 'sector': 'SVC', 'score': 0, 'event': '기준점'},
            {'year_month': '2019-01', 'sector': 'EXP', 'score': 0, 'event': '기준점'},
            {'year_month': '2019-01', 'sector': 'EMP', 'score': 0, 'event': '기준점'},
            {'year_month': '2019-01', 'sector': 'CPI', 'score': 0, 'event': '기준점'},
            
            # 2019-07: 일본 수출규제
            {'year_month': '2019-07', 'sector': 'SEC', 'score': -3, 'event': '일본 수출규제 시작'},
            {'year_month': '2019-07', 'sector': 'EXP', 'score': -2, 'event': '무역갈등'},
            
            # 2020-03: 코로나 팬데믹
            {'year_month': '2020-03', 'sector': 'SEC', 'score': -2, 'event': '코로나 충격'},
            {'year_month': '2020-03', 'sector': 'CON', 'score': -1, 'event': '건설 위축'},
            {'year_month': '2020-03', 'sector': 'FIN', 'score': -2, 'event': '금융시장 충격'},
            {'year_month': '2020-03', 'sector': 'MFG', 'score': -3, 'event': '제조업 충격'},
            {'year_month': '2020-03', 'sector': 'SVC', 'score': -5, 'event': '서비스업 급락'},
            {'year_month': '2020-03', 'sector': 'EXP', 'score': -3, 'event': '수출 급감'},
            {'year_month': '2020-03', 'sector': 'EMP', 'score': -3, 'event': '고용 충격'},
            {'year_month': '2020-03', 'sector': 'CPI', 'score': -1, 'event': '디플레 우려'},
            
            # 2020-11: 백신 개발, 반도체 슈퍼사이클
            {'year_month': '2020-11', 'sector': 'SEC', 'score': 4, 'event': '반도체 슈퍼사이클 시작'},
            {'year_month': '2020-11', 'sector': 'EXP', 'score': 3, 'event': '수출 반등'},
            
            # 2021년 - 반도체 호황, 부동산 과열
            {'year_month': '2021-06', 'sector': 'SEC', 'score': 5, 'event': 'D램 가격 최고점'},
            {'year_month': '2021-06', 'sector': 'CON', 'score': 2, 'event': '부동산 과열'},
            {'year_month': '2021-06', 'sector': 'EXP', 'score': 4, 'event': '수출 역대 최고'},
            {'year_month': '2021-06', 'sector': 'CPI', 'score': -2, 'event': '인플레 우려 시작'},
            
            # 2022년 - 금리인상, 반도체 다운턴
            {'year_month': '2022-04', 'sector': 'FIN', 'score': -3, 'event': '금리인상 본격화'},
            {'year_month': '2022-04', 'sector': 'CON', 'score': -3, 'event': 'PF 리스크 부각'},
            {'year_month': '2022-04', 'sector': 'CPI', 'score': -4, 'event': '인플레 6%대'},
            
            {'year_month': '2022-10', 'sector': 'SEC', 'score': -4, 'event': '반도체 다운턴'},
            {'year_month': '2022-10', 'sector': 'CON', 'score': -4, 'event': '레고랜드 사태'},
            {'year_month': '2022-10', 'sector': 'FIN', 'score': -4, 'event': '채권시장 경색'},
            
            # 2023년 - 반도체 회복 시작
            {'year_month': '2023-06', 'sector': 'SEC', 'score': 3, 'event': 'AI반도체 수요 급증'},
            {'year_month': '2023-06', 'sector': 'CON', 'score': -3, 'event': 'PF 부실 지속'},
            
            # 2024년 - HBM 호황, 건설 위기
            {'year_month': '2024-03', 'sector': 'SEC', 'score': 5, 'event': 'HBM 수출 급증'},
            {'year_month': '2024-03', 'sector': 'EXP', 'score': 4, 'event': '반도체 수출 견인'},
            {'year_month': '2024-03', 'sector': 'CON', 'score': -4, 'event': '건설사 워크아웃'},
            {'year_month': '2024-03', 'sector': 'FIN', 'score': -2, 'event': '부동산PF 부실'},
            
            {'year_month': '2024-12', 'sector': 'SEC', 'score': 4, 'event': 'AI반도체 수출 지속'},
            {'year_month': '2024-12', 'sector': 'CON', 'score': -5, 'event': '12.3 비상계엄'},
            {'year_month': '2024-12', 'sector': 'FIN', 'score': -3, 'event': '환율 급등 1480원'},
            {'year_month': '2024-12', 'sector': 'CPI', 'score': -3, 'event': '환율발 물가 우려'},
            {'year_month': '2024-12', 'sector': 'EXP', 'score': 2, 'event': '원화약세 수출유리'},
            
            # 2025년 전망
            {'year_month': '2025-01', 'sector': 'SEC', 'score': 3, 'event': 'HBM3E 양산'},
            {'year_month': '2025-01', 'sector': 'CON', 'score': -3, 'event': '건설투자 역성장'},
            {'year_month': '2025-01', 'sector': 'SVC', 'score': 1, 'event': '내수 회복 기대'},
        ]
        
        self.add_bulk_scores(initial_data)
        print(f"✅ Loaded {len(initial_data)} initial sector scores")


if __name__ == "__main__":
    # 테스트
    tracker = SectorScoreTracker()
    
    print("\n📊 Sector Score Tracker Test\n")
    
    # 초기 데이터 로드
    tracker.load_initial_data()
    
    # 누적 점수 확인
    cumulative = tracker.get_cumulative_scores()
    print("📈 Cumulative Scores:")
    for sector, score in cumulative.items():
        status = tracker.get_status(score)
        print(f"  {status['emoji']} {sector}: {score:+d}")
    
    # 대시보드 데이터
    dashboard = tracker.get_dashboard_data()
    print(f"\n📊 Total Score: {dashboard['total_score']}")
    
    print("\n✅ SectorScoreTracker test passed!")

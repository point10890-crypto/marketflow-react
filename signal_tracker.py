#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KR Market - Signal Tracker
실시간 시그널 기록 및 성과 추적 시스템

기능:
1. 오늘의 시그널 탐지 및 기록
2. 과거 시그널 성과 자동 업데이트
3. 전략 성과 통계 리포트
4. 점진적 전략 개선용 데이터 축적
"""
import pandas as pd
import numpy as np
import os
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import requests
from bs4 import BeautifulSoup
import logging
import yfinance as yf

# 모듈 레벨 basicConfig 금지 — Flask logger 설정을 덮어쓴다.
# CLI 실행 시에는 진입점에서 핸들러를 부착할 것.
logger = logging.getLogger(__name__)

# 파일 동시접근 보호
try:
    from app.utils.file_lock import safe_write, safe_read
except ImportError:
    # 직접 실행 시 fallback
    from contextlib import contextmanager
    @contextmanager
    def safe_write(filepath, timeout=30):
        yield filepath
    @contextmanager
    def safe_read(filepath, timeout=10):
        yield filepath


class SignalTracker:
    """시그널 추적 및 성과 기록"""
    
    def __init__(self, data_dir: str = None):
        self.data_dir = data_dir or os.path.dirname(os.path.abspath(__file__))
        self.signals_log_path = os.path.join(self.data_dir, 'signals_log.csv')
        self.performance_path = os.path.join(self.data_dir, 'strategy_performance.json')
        
        # 전략 파라미터 (검증된 최적값)
        self.strategy_params = {
            'foreign_min': 50000,        # 최소 외인 순매수
            'consecutive_min': 3,         # 최소 연속 매수일
            'contraction_max': 0.8,       # 최대 축소비
            'near_high_pct': 0.92,        # 고점 대비 %
            'hold_days': 5,               # 기본 보유 기간
            'stop_loss_pct': 7.0,         # 손절 %
        }
        
        # 로컬 가격 데이터 로드 (yfinance 대신)
        self.price_df = self._load_price_data()
        
        logger.info("✅ Signal Tracker 초기화 완료")
    
    def _load_price_data(self) -> pd.DataFrame:
        """로컬 가격 데이터 로드"""
        price_path = os.path.join(self.data_dir, 'daily_prices.csv')
        
        if os.path.exists(price_path):
            try:
                df = pd.read_csv(price_path, low_memory=False, encoding='utf-8-sig')
            except UnicodeDecodeError:
                df = pd.read_csv(price_path, low_memory=False, encoding='cp949')

            df['ticker'] = df['ticker'].astype(str).str.zfill(6)
            df['date'] = pd.to_datetime(df['date'])
            logger.info(f"   📊 가격 데이터 로드: {len(df):,}개 레코드")
            return df
        else:
            logger.warning("⚠️ 가격 데이터 파일이 없습니다")
            return pd.DataFrame()
    
    def detect_vcp_forming(self, ticker: str) -> Tuple[bool, Dict]:
        """VCP 형성 초기 감지 (로컬 데이터 사용)"""
        try:
            if self.price_df.empty:
                return False, {}
            
            # 해당 종목 가격 데이터
            ticker_prices = self.price_df[self.price_df['ticker'] == ticker].sort_values('date')
            
            if len(ticker_prices) < 20:
                return False, {}
            
            recent = ticker_prices.tail(20)
            
            # 컬럼명 확인
            price_col = 'current_price' if 'current_price' in recent.columns else 'close'
            high_col = 'high' if 'high' in recent.columns else price_col
            low_col = 'low' if 'low' in recent.columns else price_col
            
            # 전반부/후반부 범위
            first_half = recent.head(10)
            second_half = recent.tail(10)
            
            range_first = first_half[high_col].max() - first_half[low_col].min()
            range_second = second_half[high_col].max() - second_half[low_col].min()
            
            # Volume Contraction Check
            vol_col = 'volume' if 'volume' in recent.columns else None
            volume_contracting = True # Default True if no volume data
            
            if vol_col:
                vol_first = first_half[vol_col].mean()
                vol_second = second_half[vol_col].mean()
                # Volume should decrease or at least be below 50-day average (approx)
                # Here we check if recent volume is lower than previous period
                if vol_first > 0:
                    volume_contracting = vol_second < vol_first * 1.2 # Allow slight increase but prefer lower
            
            if range_first == 0:
                return False, {}
            
            contraction = range_second / range_first
            current_price = recent.iloc[-1][price_col]
            recent_high = recent[price_col].max()
            
            near_high = current_price >= recent_high * self.strategy_params['near_high_pct']
            contracting = contraction <= self.strategy_params['contraction_max']
            
            # VCP Condition: Near High + Price Contraction + Volume Contraction
            is_vcp = near_high and contracting and volume_contracting
            
            return is_vcp, {
                'contraction_ratio': round(contraction, 3),
                'price_from_high_pct': round((recent_high - current_price) / recent_high * 100, 2),
                'current_price': round(current_price, 0),
                'recent_high': round(recent_high, 0),
                'vol_contraction': volume_contracting
            }
            
        except Exception as e:
            logger.warning(f"⚠️ {ticker} VCP 감지 실패: {e}")
            return False, {}
    
    def scan_today_signals(self) -> pd.DataFrame:
        """오늘의 시그널 스캔"""
        logger.info("🔍 오늘의 시그널 스캔 시작...")
        
        # 기존 수급 데이터 로드
        inst_path = os.path.join(self.data_dir, 'all_institutional_trend_data.csv')
        
        if not os.path.exists(inst_path):
            logger.error("❌ 수급 데이터 파일이 없습니다")
            return pd.DataFrame()
        
        df = pd.read_csv(inst_path, encoding='utf-8-sig')
        df['ticker'] = df['ticker'].astype(str).str.zfill(6)
        
        # 기본 필터: 외인 매수 + 연속 매수
        signals = df[
            (df['foreign_net_buy_5d'] >= self.strategy_params['foreign_min']) &
            (df['supply_demand_index'] >= 60)
        ].copy()
        
        logger.info(f"   기본 필터 통과: {len(signals)}개 종목")
        
        # VCP 필터 적용
        vcp_signals = []
        for _, row in signals.iterrows():
            ticker = row['ticker']
            is_vcp, vcp_info = self.detect_vcp_forming(ticker)
            
            if is_vcp:
                signal = {
                    'signal_date': datetime.now().strftime('%Y-%m-%d'),
                    'ticker': ticker,
                    'foreign_5d': row['foreign_net_buy_5d'],
                    'inst_5d': row['institutional_net_buy_5d'],
                    'score': row['supply_demand_index'],
                    'contraction_ratio': vcp_info.get('contraction_ratio'),
                    'entry_price': vcp_info.get('current_price'),
                    'status': 'OPEN',
                    'exit_price': None,
                    'exit_date': None,
                    'return_pct': None,
                    'hold_days': 0
                }
                vcp_signals.append(signal)
                logger.info(f"   🎯 VCP 시그널: {ticker} | 축소비: {vcp_info.get('contraction_ratio'):.2f}")
        
        signals_df = pd.DataFrame(vcp_signals)
        
        if not signals_df.empty:
            # 기존 로그에 추가
            self._append_to_log(signals_df)
        
        logger.info(f"✅ 오늘 VCP 시그널: {len(signals_df)}개")
        return signals_df
    
    def _append_to_log(self, new_signals: pd.DataFrame):
        """시그널 로그에 추가 (OPEN 상태 종목 중복 방지)"""
        if os.path.exists(self.signals_log_path):
            try:
                existing = pd.read_csv(self.signals_log_path, encoding='utf-8-sig')
            except UnicodeDecodeError:
                existing = pd.read_csv(self.signals_log_path, encoding='cp949')

            existing['ticker'] = existing['ticker'].astype(str).str.zfill(6)
            new_signals['ticker'] = new_signals['ticker'].astype(str).str.zfill(6)

            # 1차 중복 제거: 같은 날짜+종목 (기존 로직)
            new_signals['key'] = new_signals['signal_date'] + '_' + new_signals['ticker']
            existing['key'] = existing['signal_date'] + '_' + existing['ticker']
            new_only = new_signals[~new_signals['key'].isin(existing['key'])]
            new_only = new_only.drop(columns=['key'])
            existing = existing.drop(columns=['key'])

            # 2차 중복 제거: 이미 OPEN 상태인 종목은 새로 추가하지 않음
            open_tickers = set(existing[existing['status'] == 'OPEN']['ticker'].unique())
            before_count = len(new_only)
            new_only = new_only[~new_only['ticker'].isin(open_tickers)]
            skipped = before_count - len(new_only)
            if skipped > 0:
                logger.info(f"   ⏭️ 이미 OPEN 상태인 {skipped}개 종목 스킵")

            combined = pd.concat([existing, new_only], ignore_index=True)
        else:
            combined = new_signals

        with safe_write(self.signals_log_path):
            combined.to_csv(self.signals_log_path, index=False, encoding='utf-8-sig')
        logger.info(f"📁 시그널 로그 저장: {self.signals_log_path} ({len(combined)}건)")
    
    def update_open_signals(self):
        """열린 시그널 성과 업데이트 (로컬 데이터 사용)"""
        if not os.path.exists(self.signals_log_path):
            logger.info("⚠️ 시그널 로그가 없습니다")
            return
        
        if self.price_df.empty:
            logger.warning("⚠️ 가격 데이터가 없습니다")
            return
        
        try:
            df = pd.read_csv(self.signals_log_path, encoding='utf-8-sig')
        except UnicodeDecodeError:
            df = pd.read_csv(self.signals_log_path, encoding='cp949')
        df['ticker'] = df['ticker'].astype(str).str.zfill(6)
        
        # Ensure exit_date is object type to handle string dates
        if 'exit_date' in df.columns:
            df['exit_date'] = df['exit_date'].astype('object')
        
        open_signals = df[df['status'] == 'OPEN']
        logger.info(f"🔄 열린 시그널 {len(open_signals)}개 업데이트 중...")
        
        price_col = 'current_price' if 'current_price' in self.price_df.columns else 'close'
        
        updated = 0
        for idx, row in open_signals.iterrows():
            ticker = row['ticker']
            entry_price = row['entry_price']
            signal_date = pd.to_datetime(row['signal_date'])
            hold_days = (datetime.now() - signal_date).days
            
            # 로컬 가격 데이터에서 현재가 조회
            ticker_prices = self.price_df[self.price_df['ticker'] == ticker].sort_values('date')
            
            if len(ticker_prices) > 0:
                current_price = ticker_prices.iloc[-1][price_col]
                return_pct = (current_price - entry_price) / entry_price * 100
                
                # 청산 조건 체크
                should_close = False
                close_reason = ""
                
                if return_pct <= -self.strategy_params['stop_loss_pct']:
                    should_close = True
                    close_reason = "STOP_LOSS"
                elif hold_days >= self.strategy_params['hold_days']:
                    should_close = True
                    close_reason = "TIME_EXIT"
                
                if should_close:
                    df.at[idx, 'status'] = 'CLOSED'
                    df.at[idx, 'exit_price'] = round(current_price, 0)
                    df.at[idx, 'exit_date'] = datetime.now().strftime('%Y-%m-%d')
                    df.at[idx, 'return_pct'] = round(return_pct, 2)
                    df.at[idx, 'hold_days'] = hold_days
                    logger.info(f"   📊 {ticker}: {return_pct:+.2f}% ({close_reason})")
                    updated += 1
                else:
                    df.at[idx, 'hold_days'] = hold_days
        
        with safe_write(self.signals_log_path):
            df.to_csv(self.signals_log_path, index=False, encoding='utf-8-sig')
        logger.info(f"✅ {updated}개 시그널 청산됨")
    
    def get_performance_report(self) -> Dict:
        """전략 성과 리포트"""
        if not os.path.exists(self.signals_log_path):
            return {"error": "시그널 로그가 없습니다"}
        
        try:
            df = pd.read_csv(self.signals_log_path, encoding='utf-8-sig')
        except UnicodeDecodeError:
            df = pd.read_csv(self.signals_log_path, encoding='cp949')
        
        closed = df[df['status'] == 'CLOSED']
        open_signals = df[df['status'] == 'OPEN']
        
        if len(closed) == 0:
            return {
                "message": "아직 청산된 시그널이 없습니다",
                "open_signals": len(open_signals)
            }
        
        # 성과 계산
        wins = len(closed[closed['return_pct'] > 0])
        losses = len(closed[closed['return_pct'] <= 0])
        
        report = {
            "period": f"{closed['signal_date'].min()} ~ {closed['exit_date'].max()}",
            "total_signals": len(df),
            "closed_signals": len(closed),
            "open_signals": len(open_signals),
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / len(closed) * 100, 1),
            "avg_return": round(closed['return_pct'].mean(), 2),
            "total_return": round(closed['return_pct'].sum(), 2),
            "best_trade": round(closed['return_pct'].max(), 2),
            "worst_trade": round(closed['return_pct'].min(), 2),
            "avg_hold_days": round(closed['hold_days'].mean(), 1),
            "strategy_params": self.strategy_params
        }
        
        # 저장
        with safe_write(self.performance_path):
            with open(self.performance_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
        
        return report
    
    def print_report(self):
        """성과 리포트 출력"""
        report = self.get_performance_report()
        
        print("\n" + "=" * 60)
        print("📊 VCP + 외인매집 전략 성과 리포트")
        print("=" * 60)
        
        if "error" in report:
            print(f"   {report['error']}")
            return
        
        if "message" in report:
            print(f"   {report['message']}")
            print(f"   열린 시그널: {report.get('open_signals', 0)}개")
            return
        
        print(f"""
   📅 기간: {report['period']}
   
   📈 거래 현황:
      - 총 시그널: {report['total_signals']}
      - 청산됨: {report['closed_signals']}
      - 진행중: {report['open_signals']}
   
   🎯 성과:
      - 승률: {report['win_rate']}% ({report['wins']}승 {report['losses']}패)
      - 평균 수익률: {report['avg_return']:+.2f}%
      - 누적 수익률: {report['total_return']:+.2f}%
   
   📊 상세:
      - 최대 수익: {report['best_trade']:+.2f}%
      - 최대 손실: {report['worst_trade']:+.2f}%
      - 평균 보유일: {report['avg_hold_days']}일
   
   ⚙️ 현재 전략 파라미터:
      - 외인 최소: {report['strategy_params']['foreign_min']:,}주
      - 연속 매수: {report['strategy_params']['consecutive_min']}일+
      - 축소비 최대: {report['strategy_params']['contraction_max']}
      - 손절: -{report['strategy_params']['stop_loss_pct']}%
""")


def main():
    """메인 실행"""
    tracker = SignalTracker(data_dir=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data'))
    
    # 1. 오늘의 시그널 스캔
    print("\n[1] 오늘의 시그널 스캔")
    today_signals = tracker.scan_today_signals()
    
    if not today_signals.empty:
        print("\n🎯 오늘의 VCP 시그널:")
        print("-" * 60)
        for _, s in today_signals.iterrows():
            print(f"   {s['ticker']} | 외인: {s['foreign_5d']:+,} | "
                  f"축소비: {s['contraction_ratio']:.2f} | "
                  f"진입가: {s['entry_price']:,.0f}")
    
    # 2. 열린 시그널 업데이트
    print("\n[2] 열린 시그널 업데이트")
    tracker.update_open_signals()
    
    # 3. 성과 리포트
    print("\n[3] 성과 리포트")
    tracker.print_report()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    main()

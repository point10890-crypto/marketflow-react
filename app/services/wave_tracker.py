"""
Wave Signal Tracker — DB 적재 + 일별 가격 추적 + 통계 집계

1. save_screener_to_db(): 스크리너 결과 → wave_signals 테이블 (중복 방지)
2. update_active_signals(): 활성 시그널 일별 가격 추적 → status 업데이트
3. refresh_pattern_stats(): 패턴 타입별 통계 재집계
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from app.models import db
from app.models.wave import WaveSignal, WaveTracking, WavePatternStats

logger = logging.getLogger(__name__)


def save_screener_to_db(screener_data: dict) -> int:
    """
    스크리너 결과를 DB에 적재 (같은 날짜+종목 중복 방지).
    Returns: 신규 적재 건수
    """
    signals = screener_data.get('signals', [])
    date_str = screener_data.get('date', datetime.now().strftime('%Y-%m-%d'))
    saved = 0

    for s in signals:
        bp = s.get('best_pattern', {})
        ticker = s.get('ticker', '')

        # 같은 날 같은 종목 같은 패턴 중복 방지
        exists = WaveSignal.query.filter_by(
            ticker=ticker,
            signal_date=date_str,
            wave_type=bp.get('wave_type', ''),
        ).first()
        if exists:
            continue

        # Entry/Stop/Target 계산
        neckline = bp.get('neckline_price', 0)
        price = s.get('price', 0)
        pattern_class = bp.get('pattern_class', '')

        if pattern_class == 'W':  # Bullish
            entry = neckline * 1.005      # 넥라인 +0.5% 돌파
            stop = price * 0.95           # -5% 손절
            target = neckline + (neckline - price)  # 측정 이동
        else:  # M — Bearish
            entry = neckline * 0.995      # 넥라인 -0.5% 이탈
            stop = price * 1.05           # +5% 손절
            target = neckline - (price - neckline)  # 측정 이동

        points = bp.get('points', [])
        sig = WaveSignal(
            ticker=ticker,
            name=s.get('name', ''),
            market=s.get('market', 'KR'),
            pattern_class=pattern_class,
            wave_type=bp.get('wave_type', ''),
            wave_label=bp.get('wave_label', ''),
            confidence=bp.get('confidence', 0),
            completion_pct=bp.get('completion_pct', 0),
            bullish_bias=bp.get('bullish_bias', 0),
            volume_confirmed=bp.get('volume_confirmed', False),
            signal_price=price,
            neckline_price=neckline,
            neckline_distance_pct=bp.get('neckline_distance_pct', 0),
            entry_price=round(entry, 1),
            stop_price=round(stop, 1),
            target_price=round(target, 1),
            signal_date=date_str,
            points_json=json.dumps(points, ensure_ascii=False) if points else None,
        )
        db.session.add(sig)
        saved += 1

    if saved > 0:
        db.session.commit()
        logger.info(f"Wave DB: {saved} new signals saved for {date_str}")

    return saved


def update_active_signals(price_data: Optional[dict] = None) -> dict:
    """
    활성 시그널의 일별 가격 추적 + status 업데이트.
    price_data: {ticker: current_price} — 없으면 daily_prices.csv에서 로드

    Returns: {'updated': n, 'closed': n, 'hit_target': n, 'hit_stop': n, 'expired': n}
    """
    active = WaveSignal.query.filter_by(status='active').all()
    if not active:
        return {'updated': 0, 'closed': 0}

    # 가격 데이터 로드
    if price_data is None:
        price_data = _load_latest_prices()

    today = datetime.now().strftime('%Y-%m-%d')
    result = {'updated': 0, 'closed': 0, 'hit_target': 0, 'hit_stop': 0,
              'expired': 0, 'neckline_break': 0}

    for sig in active:
        price = price_data.get(sig.ticker)
        if price is None:
            continue

        # 경과 일수
        try:
            sig_date = datetime.strptime(sig.signal_date, '%Y-%m-%d')
            days = (datetime.now() - sig_date).days
        except ValueError:
            days = 0

        # 수익률 계산
        if sig.signal_price and sig.signal_price > 0:
            pnl = (price - sig.signal_price) / sig.signal_price * 100
            if sig.pattern_class == 'M':
                pnl = -pnl  # Bearish: 하락이 이익
        else:
            pnl = 0

        # 일별 추적 기록 (중복 방지)
        exists = WaveTracking.query.filter_by(
            signal_id=sig.id, date=today
        ).first()
        if not exists:
            tracking = WaveTracking(
                signal_id=sig.id,
                date=today,
                close_price=price,
                pnl_pct=round(pnl, 2),
                days_since=days,
                neckline_broken=_check_neckline_broken(sig, price),
            )
            db.session.add(tracking)

        # Max gain/loss 업데이트
        if sig.max_gain_pct is None or pnl > (sig.max_gain_pct or 0):
            sig.max_gain_pct = round(pnl, 2)
        if sig.max_loss_pct is None or pnl < (sig.max_loss_pct or 0):
            sig.max_loss_pct = round(pnl, 2)

        # Status 업데이트
        new_status = _evaluate_status(sig, price, days)
        if new_status != 'active':
            sig.status = new_status
            sig.exit_price = price
            sig.return_pct = round(pnl, 2)
            sig.holding_days = days
            sig.closed_at = datetime.now(timezone.utc)
            result['closed'] += 1
            result[new_status] = result.get(new_status, 0) + 1

        result['updated'] += 1

    db.session.commit()
    logger.info(f"Wave Tracker: {result}")
    return result


def refresh_pattern_stats():
    """패턴 타입별 통계 재집계."""
    from sqlalchemy import func

    # 모든 패턴 타입 집계
    stats_query = db.session.query(
        WaveSignal.wave_type,
        WaveSignal.wave_label,
        WaveSignal.pattern_class,
        func.count(WaveSignal.id).label('total'),
        func.sum(db.case((WaveSignal.status == 'hit_target', 1), else_=0)).label('wins'),
        func.sum(db.case((WaveSignal.status == 'hit_stop', 1), else_=0)).label('losses'),
        func.sum(db.case((WaveSignal.status == 'active', 1), else_=0)).label('actives'),
        func.avg(WaveSignal.return_pct).label('avg_return'),
        func.max(WaveSignal.return_pct).label('best_return'),
        func.min(WaveSignal.return_pct).label('worst_return'),
        func.avg(WaveSignal.holding_days).label('avg_days'),
        func.avg(WaveSignal.confidence).label('avg_conf'),
    ).group_by(
        WaveSignal.wave_type
    ).all()

    for row in stats_query:
        stat = WavePatternStats.query.filter_by(wave_type=row.wave_type).first()
        if not stat:
            stat = WavePatternStats(
                wave_type=row.wave_type,
                wave_label=row.wave_label,
                pattern_class=row.pattern_class,
            )
            db.session.add(stat)

        closed = (row.wins or 0) + (row.losses or 0)
        stat.total_count = row.total or 0
        stat.win_count = row.wins or 0
        stat.loss_count = row.losses or 0
        stat.active_count = row.actives or 0
        stat.avg_return_pct = round(row.avg_return or 0, 2)
        stat.best_return_pct = round(row.best_return or 0, 2)
        stat.worst_return_pct = round(row.worst_return or 0, 2)
        stat.avg_holding_days = round(row.avg_days or 0, 1)
        stat.avg_confidence = round(row.avg_conf or 0, 1)
        stat.win_rate = round((row.wins or 0) / closed * 100, 1) if closed > 0 else 0
        stat.updated_at = datetime.now(timezone.utc)

    db.session.commit()
    logger.info(f"Wave Stats: {len(stats_query)} pattern types refreshed")


def _check_neckline_broken(sig: WaveSignal, price: float) -> bool:
    """넥라인 돌파 여부."""
    if sig.pattern_class == 'W':
        return price >= sig.neckline_price
    else:  # M
        return price <= sig.neckline_price


def _evaluate_status(sig: WaveSignal, price: float, days: int) -> str:
    """시그널 상태 평가."""
    # 30일 만료
    if days >= 30:
        return 'expired'

    if sig.pattern_class == 'W':  # Bullish
        if sig.target_price and price >= sig.target_price:
            return 'hit_target'
        if sig.stop_price and price <= sig.stop_price:
            return 'hit_stop'
        if price >= sig.neckline_price and sig.status == 'active':
            return 'neckline_break'
    else:  # M — Bearish
        if sig.target_price and price <= sig.target_price:
            return 'hit_target'
        if sig.stop_price and price >= sig.stop_price:
            return 'hit_stop'
        if price <= sig.neckline_price and sig.status == 'active':
            return 'neckline_break'

    return 'active'


def _load_latest_prices() -> dict:
    """daily_prices.csv에서 최신 종가 로드."""
    import os
    import pandas as pd

    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    csv_path = os.path.join(base_dir, 'data', 'daily_prices.csv')

    if not os.path.exists(csv_path):
        return {}

    df = pd.read_csv(csv_path, dtype={'ticker': str}, low_memory=False)
    df['date'] = pd.to_datetime(df['date'])

    # 각 종목의 최신 종가
    latest = df.sort_values('date').groupby('ticker').last()
    return {str(idx): float(row['current_price'])
            for idx, row in latest.iterrows()
            if row['current_price'] > 0}

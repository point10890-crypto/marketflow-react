"""기술적 추세 분석 + 매수/목표/손절가 자동 제안.

원본 데이터: data/daily_prices.csv (또는 KIS live 보강).

계산 지표:
- SMA5 / SMA20 / SMA60 / SMA120
- ATR(14) — 변동성 기반 손절 거리
- 최근 20일 / 60일 고가 (저항)
- 최근 20일 / 60일 저가 (지지)
- 추세 판정 (강세 / 약세 / 중립)

가격 제안 규칙 (Mark Minervini SEPA + 일반 swing):
- 강세 추세:
    entry  = max(current, SMA20)  ← 눌림 매수 또는 현재가
    target = entry + 2.5 × ATR (1차) / 3.5 × ATR (2차)
    stop   = SMA20 - 1.0 × ATR (or 20일 저가 중 가까운 쪽)
- 중립 추세:
    entry  = current (관망 / 분할 매수)
    target = 20일 고가
    stop   = 20일 저가
- 약세 추세:
    매수 비추천 (관망)
"""

from __future__ import annotations

import csv
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
DAILY_PRICES_CSV = REPO_ROOT / 'data' / 'daily_prices.csv'


# ─── 공개 API ──────────────────────────────────────────────────────

def analyze_target_with_levels(target: str) -> dict[str, Any]:
    """종목명/티커 → 추세 분석 + 매수/목표/손절가 제안 (한국 시장만).

    Args:
        target: 종목명 ('삼성전자') 또는 6자리 코드 ('005930')

    Returns:
        {
            'target': str,
            'symbol': str,
            'name': str,
            'price': {'current', 'open', 'high', 'low', 'date'},
            'indicators': {'sma5','sma20','sma60','sma120','atr14',
                           'high20','low20','high60','low60'},
            'trend': 'bullish'|'neutral'|'bearish',
            'trend_reasoning': str,
            'levels': {'entry','target1','target2','stop',
                       'risk_pct','reward_pct','rr_ratio'},
            'note': str,        # 한국어 종합 코멘트
            'error'?: str,
        }
    """
    # resolve target → symbol
    from app.services.mirofish import live_data
    try:
        resolved = live_data.resolve_target(target)
    except Exception as exc:
        return {'error': f'resolve_target 실패: {exc}', 'target': target}

    symbol = resolved.get('symbol')
    name = resolved.get('display_name') or resolved.get('name') or target

    if not symbol:
        return {
            'error': '심볼 해석 실패 (한국 시장 종목만 지원)',
            'target': target,
            'name': name,
        }

    rows = _load_price_history(symbol)
    if len(rows) < 30:
        return {
            'error': f'가격 데이터 부족 (최소 30일 필요, 현재 {len(rows)}일)',
            'target': target, 'symbol': symbol, 'name': name,
        }

    closes = [r['close'] for r in rows]
    highs = [r['high'] for r in rows]
    lows = [r['low'] for r in rows]
    last = rows[-1]

    # 지표 계산
    sma5 = _sma(closes, 5)
    sma20 = _sma(closes, 20)
    sma60 = _sma(closes, 60)
    sma120 = _sma(closes, 120) if len(closes) >= 120 else None
    atr14 = _atr(highs, lows, closes, 14)
    high20 = max(highs[-20:])
    low20 = min(lows[-20:])
    high60 = max(highs[-60:]) if len(highs) >= 60 else high20
    low60 = min(lows[-60:]) if len(lows) >= 60 else low20

    current = last['close']

    # 추세 판정
    trend, trend_reasoning = _classify_trend(current, sma5, sma20, sma60, sma120)

    # 매수/목표/손절 계산
    levels = _compute_levels(
        current=current,
        sma20=sma20,
        atr14=atr14,
        high20=high20,
        low20=low20,
        trend=trend,
    )

    note = _build_note(name=name, trend=trend, levels=levels, current=current, atr14=atr14)

    return {
        'target': target,
        'symbol': symbol,
        'name': name,
        'price': {
            'current': round(current, 2),
            'open': round(last['open'], 2),
            'high': round(last['high'], 2),
            'low': round(last['low'], 2),
            'date': last['date'],
        },
        'indicators': {
            'sma5': _r(sma5),
            'sma20': _r(sma20),
            'sma60': _r(sma60),
            'sma120': _r(sma120) if sma120 else None,
            'atr14': _r(atr14),
            'high20': _r(high20),
            'low20': _r(low20),
            'high60': _r(high60),
            'low60': _r(low60),
        },
        'trend': trend,
        'trend_reasoning': trend_reasoning,
        'levels': levels,
        'note': note,
    }


# ─── 내부 helpers ──────────────────────────────────────────────────

def _load_price_history(symbol: str, max_rows: int = 250) -> list[dict[str, Any]]:
    """daily_prices.csv 에서 해당 심볼만 최근 N일 OHLC 추출."""
    if not DAILY_PRICES_CSV.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with DAILY_PRICES_CSV.open('r', encoding='utf-8-sig', newline='') as f:
            for r in csv.DictReader(f):
                if str(r.get('ticker', '')).zfill(6) == symbol:
                    try:
                        rows.append({
                            'date': r.get('date', ''),
                            'open': float(r.get('open') or 0),
                            'high': float(r.get('high') or 0),
                            'low': float(r.get('low') or 0),
                            'close': float(r.get('current_price') or 0),
                            'volume': int(float(r.get('volume') or 0)),
                        })
                    except (TypeError, ValueError):
                        continue
    except (OSError, csv.Error) as exc:
        logger.warning(f'[technical] price history read failed: {exc}')
        return []
    rows.sort(key=lambda r: r['date'])
    return rows[-max_rows:]


def _sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _atr(highs: list[float], lows: list[float], closes: list[float], period: int) -> float | None:
    """Wilder's ATR."""
    if len(closes) < period + 1:
        return None
    trs: list[float] = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    if len(trs) < period:
        return None
    # 단순 평균 (간소화 — wilder smoothing 은 후순위)
    return sum(trs[-period:]) / period


def _classify_trend(
    current: float,
    sma5: float | None,
    sma20: float | None,
    sma60: float | None,
    sma120: float | None,
) -> tuple[str, str]:
    """SMA 정배열 / 역배열 + 가격 위치로 추세 판정."""
    if not sma20 or not sma60:
        return 'neutral', '이동평균선 데이터 부족 — 중립'

    # 강세: current > sma5 > sma20 > sma60 (정배열 + 가격 위)
    if sma5 and current > sma5 > sma20 > sma60:
        msg = f'정배열 (가격 > SMA5={sma5:.0f} > SMA20={sma20:.0f} > SMA60={sma60:.0f}) — 강세 추세 지속'
        if sma120 and sma60 > sma120:
            msg += f', SMA120={sma120:.0f} 위'
        return 'bullish', msg

    # 약세: current < sma5 < sma20 < sma60 (역배열)
    if sma5 and current < sma5 < sma20 < sma60:
        return 'bearish', (
            f'역배열 (가격 < SMA5={sma5:.0f} < SMA20={sma20:.0f} < SMA60={sma60:.0f}) — 하락 추세'
        )

    # 가격이 SMA20 위 + SMA20 > SMA60 → 약한 강세
    if current > sma20 and sma20 > sma60:
        return 'bullish', (
            f'SMA20({sma20:.0f}) 상향, SMA20 > SMA60({sma60:.0f}) — 약한 강세 신호'
        )

    # 가격이 SMA20 아래 + SMA20 < SMA60 → 약한 약세
    if current < sma20 and sma20 < sma60:
        return 'bearish', (
            f'가격 < SMA20({sma20:.0f}), SMA20 < SMA60({sma60:.0f}) — 약한 약세 신호'
        )

    return 'neutral', f'SMA20={sma20:.0f}, SMA60={sma60:.0f} — 추세 모호 (관망 권장)'


def _compute_levels(
    current: float,
    sma20: float | None,
    atr14: float | None,
    high20: float,
    low20: float,
    trend: str,
) -> dict[str, Any]:
    """추세에 따른 entry / target / stop 가격 계산."""
    if not atr14:
        atr14 = (high20 - low20) / 5  # fallback

    if trend == 'bullish':
        # 강세: 눌림 매수 or 현재가, 목표 2.5-3.5 ATR, 손절 SMA20 - 1 ATR
        entry = round(max(current, sma20 or current), 0)
        target1 = round(entry + 2.5 * atr14, 0)
        target2 = round(entry + 3.5 * atr14, 0)
        stop_atr = (sma20 or current) - 1.0 * atr14
        stop = round(max(stop_atr, low20 - 0.3 * atr14), 0)  # 더 가까운 쪽
    elif trend == 'neutral':
        # 중립: 분할 매수, 목표 20일 고가, 손절 20일 저가
        entry = round(current, 0)
        target1 = round(high20, 0)
        target2 = round(high20 + 1.5 * atr14, 0)
        stop = round(low20, 0)
    else:  # bearish
        # 약세: 매수 비추천 (참고용 가격만)
        entry = round(current, 0)
        target1 = round(sma20 or current, 0)
        target2 = round(high20, 0)
        stop = round(low20 - 0.5 * atr14, 0)

    risk = entry - stop
    reward1 = target1 - entry
    risk_pct = (risk / entry * 100) if entry else 0
    reward1_pct = (reward1 / entry * 100) if entry else 0
    rr = (reward1 / risk) if risk > 0 else None

    return {
        'entry': entry,
        'target1': target1,
        'target2': target2,
        'stop': stop,
        'risk_pct': round(risk_pct, 2),
        'reward1_pct': round(reward1_pct, 2),
        'rr_ratio': round(rr, 2) if rr else None,
    }


def _build_note(name: str, trend: str, levels: dict, current: float, atr14: float | None) -> str:
    label = {'bullish': '강세', 'neutral': '중립', 'bearish': '약세'}[trend]
    lines = [
        f"{name} 추세: {label}",
        f"현재가 {current:,.0f}원, ATR(14) {atr14:,.0f}원" if atr14 else f"현재가 {current:,.0f}원",
        f"매수 진입가 {levels['entry']:,.0f}원 / 1차 목표 {levels['target1']:,.0f}원 (+{levels['reward1_pct']}%)"
        f" / 2차 목표 {levels['target2']:,.0f}원 / 손절 {levels['stop']:,.0f}원 (-{levels['risk_pct']}%)",
    ]
    if levels.get('rr_ratio'):
        lines.append(f"손익비 1 : {levels['rr_ratio']:.2f}")
    if trend == 'bearish':
        lines.append('⚠ 약세 추세 — 매수 비추천. 추세 반전 확인 후 진입 권장.')
    elif trend == 'neutral':
        lines.append('💡 추세 모호 — 분할 매수 / 돌파 확인 후 진입 권장.')
    return ' / '.join(lines)


def _r(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None

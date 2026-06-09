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
    try:
        kis = live_data.load_kis_snapshot(resolved)
    except Exception as exc:
        logger.warning(f'[technical] KIS live snapshot failed: {type(exc).__name__}: {exc}')
        kis = {
            'source': 'KIS API',
            'enabled': True,
            'found': False,
            'error': f'{type(exc).__name__}: {exc}',
            'sources': [],
        }
    if not _has_quote_price(kis):
        fallback_quote = _fetch_external_quote_snapshot(resolved)
        if fallback_quote:
            kis = _with_fallback_quote(kis, fallback_quote)
    rows, price_quality = _merge_kis_live_price(rows, kis)

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

    result = {
        'target': target,
        'symbol': symbol,
        'name': name,
        'price': {
            'current': round(current, 2),
            'open': round(last['open'], 2),
            'high': round(last['high'], 2),
            'low': round(last['low'], 2),
            'date': last['date'],
            'source': price_quality['price_source'],
            'is_live': price_quality['is_live_price'],
            'fetched_at': price_quality.get('fetched_at'),
            'csv_last_date': price_quality.get('csv_last_date'),
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
        'data_quality': price_quality,
        'sources': price_quality.get('sources') or [],
    }
    result['grounded_summary'] = format_grounded_levels_summary(result)
    return result


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


def _merge_kis_live_price(rows: list[dict[str, Any]], kis: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Overlay the latest KIS quote onto daily history for current-price-sensitive levels."""
    merged = [dict(row) for row in rows]
    csv_last_date = str(merged[-1].get('date') or '') if merged else ''
    price_source = str(kis.get('quote_source') or 'KIS API: inquire-price') if isinstance(kis, dict) else 'KIS API: inquire-price'
    quality: dict[str, Any] = {
        'price_source': 'daily_prices.csv',
        'is_live_price': False,
        'kis_enabled': bool(kis.get('enabled')) if isinstance(kis, dict) else False,
        'kis_found': bool(kis.get('found')) if isinstance(kis, dict) else False,
        'kis_cached': bool(kis.get('cached')) if isinstance(kis, dict) else False,
        'kis_error': kis.get('error') if isinstance(kis, dict) else None,
        'fallback_from_kis_error': kis.get('fallback_from_kis_error') if isinstance(kis, dict) else None,
        'csv_last_date': csv_last_date,
        'analysis_price_date': csv_last_date,
        'stale_days': _days_since(csv_last_date),
        'sources': ['data/daily_prices.csv'],
    }
    if isinstance(kis, dict):
        quality['sources'] = sorted(set(quality['sources'] + list(kis.get('sources') or [])))

    quote = kis.get('quote') if isinstance(kis, dict) else None
    if not isinstance(quote, dict):
        return merged, quality

    live_price = _positive_float(quote.get('price'))
    if live_price is None:
        return merged, quality

    quote_date = str(quote.get('date') or datetime.now().strftime('%Y-%m-%d'))[:10]
    open_price = _positive_float(quote.get('open')) or live_price
    high_price = max(_positive_values([quote.get('high'), open_price, live_price]) or [live_price])
    low_price = min(_positive_values([quote.get('low'), open_price, live_price]) or [live_price])
    live_row = {
        'date': quote_date,
        'open': float(open_price),
        'high': float(high_price),
        'low': float(low_price),
        'close': float(live_price),
        'volume': int(_positive_float(quote.get('volume')) or merged[-1].get('volume') or 0),
    }
    if merged and str(merged[-1].get('date') or '') >= quote_date:
        merged[-1].update(live_row)
    else:
        merged.append(live_row)

    quality.update({
        'price_source': price_source,
        'is_live_price': True,
        'kis_found': True,
        'fetched_at': kis.get('fetched_at'),
        'analysis_price_date': quote_date,
        'stale_days': _days_since(quote_date),
        'live_price': live_price,
    })
    return merged, quality


def _has_quote_price(snapshot: dict[str, Any]) -> bool:
    quote = snapshot.get('quote') if isinstance(snapshot, dict) else None
    return isinstance(quote, dict) and _positive_float(quote.get('price')) is not None


def _with_fallback_quote(kis: dict[str, Any], fallback_quote: dict[str, Any]) -> dict[str, Any]:
    sources = []
    if isinstance(kis, dict):
        sources.extend(kis.get('sources') or [])
    sources.extend(fallback_quote.get('sources') or [])
    out = dict(kis or {})
    out.update({
        'found': True,
        'quote': fallback_quote['quote'],
        'quote_source': fallback_quote['source'],
        'sources': sorted(set(sources)),
        'fallback_from_kis_error': (kis or {}).get('error'),
        'fetched_at': fallback_quote.get('fetched_at') or (kis or {}).get('fetched_at'),
    })
    return out


def _fetch_external_quote_snapshot(resolved: dict[str, Any]) -> dict[str, Any] | None:
    symbol = str(resolved.get('symbol') or '').zfill(6)
    if not symbol or len(symbol) != 6 or not symbol.isdigit():
        return None

    quote = _fetch_kr_ohlcv_quote(symbol)
    if quote:
        return quote

    yahoo_ticker = str(resolved.get('yahoo_ticker') or f'{symbol}.KS')
    return _fetch_yfinance_quote(yahoo_ticker, symbol)


def _fetch_kr_ohlcv_quote(symbol: str) -> dict[str, Any] | None:
    try:
        from app.utils.kr_data_safe import get_ohlcv_safe

        df = get_ohlcv_safe(symbol, lookback_days=10, timeout=4.0)
    except Exception as exc:
        logger.warning(f'[technical] KR OHLCV fallback failed for {symbol}: {type(exc).__name__}: {exc}')
        return None
    if df is None or df.empty or 'Close' not in df.columns:
        return None

    last = df.dropna(subset=['Close']).tail(1)
    if last.empty:
        return None
    row = last.iloc[0]
    index_value = last.index[-1]
    date_text = _date_from_index(index_value)
    close = _positive_float(row.get('Close'))
    if close is None:
        return None
    open_price = _positive_float(row.get('Open')) or close
    high_price = _positive_float(row.get('High')) or max(open_price, close)
    low_price = _positive_float(row.get('Low')) or min(open_price, close)
    return {
        'source': 'KR OHLCV fallback',
        'sources': ['FinanceDataReader/pykrx OHLCV'],
        'fetched_at': datetime.now().isoformat(),
        'quote': {
            'symbol': symbol,
            'price': close,
            'open': open_price,
            'high': high_price,
            'low': low_price,
            'volume': _positive_float(row.get('Volume')) or 0,
            'date': date_text,
        },
    }


def _fetch_yfinance_quote(yahoo_ticker: str, symbol: str) -> dict[str, Any] | None:
    try:
        from app.utils.yf_safe import yf_ticker_history_safe

        df = yf_ticker_history_safe(yahoo_ticker, timeout=4.0, period='5d', interval='1d')
    except Exception as exc:
        logger.warning(f'[technical] yfinance fallback failed for {yahoo_ticker}: {type(exc).__name__}: {exc}')
        return None
    if df is None or df.empty or 'Close' not in df.columns:
        return None

    last = df.dropna(subset=['Close']).tail(1)
    if last.empty:
        return None
    row = last.iloc[0]
    close = _positive_float(row.get('Close'))
    if close is None:
        return None
    open_price = _positive_float(row.get('Open')) or close
    high_price = _positive_float(row.get('High')) or max(open_price, close)
    low_price = _positive_float(row.get('Low')) or min(open_price, close)
    return {
        'source': 'yfinance fallback',
        'sources': [f'yfinance:{yahoo_ticker}'],
        'fetched_at': datetime.now().isoformat(),
        'quote': {
            'symbol': symbol,
            'price': close,
            'open': open_price,
            'high': high_price,
            'low': low_price,
            'volume': _positive_float(row.get('Volume')) or 0,
            'date': _date_from_index(last.index[-1]),
        },
    }


def _date_from_index(value: Any) -> str:
    try:
        return value.date().isoformat()
    except AttributeError:
        return str(value)[:10]


def _positive_values(values: list[Any]) -> list[float]:
    out: list[float] = []
    for value in values:
        number = _positive_float(value)
        if number is not None:
            out.append(number)
    return out


def _positive_float(value: Any) -> float | None:
    try:
        if value in (None, ''):
            return None
        if isinstance(value, str):
            value = value.replace(',', '')
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _days_since(date_text: str) -> int | None:
    try:
        parsed = datetime.strptime(str(date_text)[:10], '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None
    return max(0, (datetime.now().date() - parsed).days)


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


def format_grounded_levels_summary(result: dict[str, Any]) -> str:
    """Return a deterministic Korean summary so LLM replies cannot drift on numbers."""
    if not isinstance(result, dict) or result.get('error'):
        return ''

    name = str(result.get('name') or result.get('target') or '대상')
    symbol = str(result.get('symbol') or '')
    price = result.get('price') or {}
    levels = result.get('levels') or {}
    indicators = result.get('indicators') or {}
    quality = result.get('data_quality') or {}

    current = _format_krw(price.get('current'))
    entry = _format_krw(levels.get('entry'))
    target1 = _format_krw(levels.get('target1'))
    target2 = _format_krw(levels.get('target2'))
    stop = _format_krw(levels.get('stop'))
    sma5 = _format_krw(indicators.get('sma5'))
    sma20 = _format_krw(indicators.get('sma20'))
    sma60 = _format_krw(indicators.get('sma60'))
    atr14 = _format_krw(indicators.get('atr14'))
    source = price.get('source') or quality.get('price_source') or 'unknown'
    date = price.get('date') or quality.get('analysis_price_date') or 'unknown'
    if price.get('is_live') and str(source).startswith('KIS API'):
        live_label = '실시간 KIS 현재가'
    elif price.get('is_live'):
        live_label = '시장 가격 폴백'
    else:
        live_label = 'CSV 종가 기준'
    stale_days = quality.get('stale_days')
    freshness = f'신선도 {stale_days}일' if stale_days is not None else '신선도 확인 필요'

    return '\n'.join([
        '### MCP 가격 기준',
        f'- 대상: {name} ({symbol})',
        f'- 현재가: {current} ({live_label}, {source}, {date}, {freshness})',
        f'- 진입/목표/손절: 진입 {entry} / 1차 {target1} / 2차 {target2} / 손절 {stop}',
        f'- 지표: SMA5 {sma5} / SMA20 {sma20} / SMA60 {sma60} / ATR14 {atr14}',
        '- 주의: 위 가격 수치는 MCP 도구 산출값 기준이며 LLM이 임의 생성한 값이 아닙니다.',
    ])


def _format_krw(value: Any) -> str:
    try:
        if value in (None, ''):
            return 'N/A'
        number = float(str(value).replace(',', ''))
    except (TypeError, ValueError):
        return 'N/A'
    return f'{number:,.0f}원'


def _r(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None

# app/routes/kr_market.py
"""KR 마켓 API 라우트"""

import os
import sys
import json
import time
import logging
import traceback
from datetime import datetime, date
import pandas as pd
from flask import Blueprint, jsonify, request, current_app

logger = logging.getLogger(__name__)

kr_bp = Blueprint('kr', __name__)

# ── 고정 경로 ──────────────────────────────────────────────
from app.utils.paths import BASE_DIR, DATA_DIR
from app.auth.decorators import admin_required
from app.utils.json_cache import load_json_cached

# market_gate 임포트를 위한 경로 등록
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


@kr_bp.route('/market-status')
def get_kr_market_status():
    """한국 시장 상태"""
    try:
        prices_path = os.path.join(DATA_DIR, 'daily_prices.csv')
        if not os.path.exists(prices_path):
            return jsonify({'status': 'UNKNOWN', 'reason': 'No price data'}), 404
            
        df = pd.read_csv(prices_path, dtype={'ticker': str}, encoding='utf-8-sig')
        target_ticker = '069500'
        target_name = 'KODEX 200'
        
        market_df = df[df['ticker'] == target_ticker].copy()
        
        if market_df.empty:
            target_ticker = '005930'
            target_name = 'Samsung Elec'
            market_df = df[df['ticker'] == target_ticker].copy()
            
        if market_df.empty:
            return jsonify({'status': 'UNKNOWN', 'reason': 'Market proxy data not found'}), 404
             
        market_df['date'] = pd.to_datetime(market_df['date'])
        market_df = market_df.sort_values('date')
        
        if len(market_df) < 200:
            return jsonify({'status': 'NEUTRAL', 'reason': 'Insufficient data'}), 200
             
        market_df['MA20'] = market_df['current_price'].rolling(20).mean()
        market_df['MA50'] = market_df['current_price'].rolling(50).mean()
        market_df['MA200'] = market_df['current_price'].rolling(200).mean()
        
        last = market_df.iloc[-1]
        price = last['current_price']
        ma20 = last['MA20']
        ma50 = last['MA50']
        ma200 = last['MA200']
        
        status = "NEUTRAL"
        score = 50
        
        if price > ma200 and ma20 > ma50:
            status = "RISK_ON"
            score = 80
        elif price < ma200 and ma20 < ma50:
            status = "RISK_OFF"
            score = 20
            
        return jsonify({
            'status': status,
            'score': score,
            'current_price': float(price),
            'ma200': float(ma200),
            'date': last['date'].strftime('%Y-%m-%d'),
            'symbol': target_ticker,
            'name': target_name
        })

    except Exception as e:
        logger.error(f"Error checking market status: {e}")
        return jsonify({'error': str(e)}), 500


def _load_ticker_maps():
    """ticker_to_yahoo_map.csv에서 name/market/yahoo 매핑 로드"""
    name_map = {}
    market_map = {}
    yahoo_map = {}
    candidates = [
        os.path.join(BASE_DIR, 'ticker_to_yahoo_map.csv'),
        os.path.join(DATA_DIR, 'ticker_to_yahoo_map.csv'),
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                df = pd.read_csv(p, dtype={'ticker': str}, encoding='utf-8-sig')
                df['ticker'] = df['ticker'].str.zfill(6)
                name_map = dict(zip(df['ticker'], df['name']))
                market_map = dict(zip(df['ticker'], df['market']))
                if 'yahoo_ticker' in df.columns:
                    yahoo_map = dict(zip(df['ticker'], df['yahoo_ticker']))
            except Exception as e:
                logger.warning(f"ticker map load error: {e}")
            break
    return name_map, market_map, yahoo_map


@kr_bp.route('/signals')
def get_kr_signals():
    """오늘의 VCP + 외인매집 시그널"""
    try:
        name_map, market_map, yahoo_map = _load_ticker_maps()

        json_path = os.path.join(DATA_DIR, 'kr_ai_analysis.json')

        data = load_json_cached(json_path, ttl=300)
        if data is not None:
            try:
                signals = data.get('signals', [])

                # ── 종목명 + 마켓 보완 (ticker_to_yahoo_map 기반) ──
                for signal in signals:
                    ticker = str(signal.get('ticker', '')).zfill(6)
                    if not signal.get('name') or signal.get('name') == ticker:
                        signal['name'] = name_map.get(ticker, ticker)
                    if not signal.get('market'):
                        signal['market'] = market_map.get(ticker, '')

                # ── 실시간 가격 주입 (yfinance) ──
                try:
                    import yfinance as yf
                    yf_tickers = []
                    signal_by_yf = {}

                    for s in signals:
                        t = str(s.get('ticker', '')).zfill(6)
                        if not t:
                            continue
                        yf_t = yahoo_map.get(t, f"{t}.KS")
                        yf_tickers.append(yf_t)
                        signal_by_yf[yf_t] = s

                    if yf_tickers:
                        price_data = yf.download(yf_tickers, period='1d', interval='1m', progress=False, threads=True)

                        if not price_data.empty:
                            closes = price_data['Close']

                            if len(yf_tickers) == 1:
                                val = float(closes.iloc[-1])
                                s = signal_by_yf[yf_tickers[0]]
                                s['current_price'] = val
                                entry = float(s.get('entry_price', 0))
                                if entry > 0:
                                    s['return_pct'] = round((val - entry) / entry * 100, 2)
                            else:
                                for yf_t, s in signal_by_yf.items():
                                    try:
                                        if yf_t in closes.columns:
                                            val = closes[yf_t].iloc[-1]
                                            if pd.notna(val) and float(val) > 0:
                                                s['current_price'] = float(val)
                                                entry = float(s.get('entry_price', 0))
                                                if entry > 0:
                                                    s['return_pct'] = round((float(val) - entry) / entry * 100, 2)
                                    except Exception as exc:
                                        logger.warning(f"Price lookup failed for {yf_t}: {exc}")
                except Exception as e:
                    logger.warning(f"Error fetching realtime signal prices: {e}")

                signals.sort(key=lambda x: x.get('score', 0), reverse=True)

                # 중복 제거
                seen = set()
                unique_signals = []
                for s in signals:
                    t = str(s.get('ticker', '')).zfill(6)
                    if t not in seen:
                        seen.add(t)
                        unique_signals.append(s)
                signals = unique_signals

                return jsonify({
                    'signals': signals,
                    'count': len(signals),
                    'generated_at': data.get('generated_at', ''),
                    'source': 'json_live'
                })
            except Exception as e:
                logger.error(f"Error reading kr_ai_analysis.json: {e}")

        # Fallback to CSV
        signals_path = os.path.join(DATA_DIR, 'signals_log.csv')

        if not os.path.exists(signals_path):
            return jsonify({
                'signals': [],
                'count': 0,
                'message': '시그널 로그가 없습니다.'
            })

        df = pd.read_csv(signals_path, encoding='utf-8-sig')
        if 'status' in df.columns:
            df = df[df['status'] == 'OPEN']

        signals = []
        for _, row in df.iterrows():
            ticker = str(row['ticker']).zfill(6)
            signals.append({
                'ticker': ticker,
                'name': row.get('name', '') or name_map.get(ticker, ticker),
                'market': row.get('market', '') or market_map.get(ticker, ''),
                'signal_date': row['signal_date'],
                'foreign_5d': int(row.get('foreign_5d', 0)),
                'inst_5d': int(row.get('inst_5d', 0)),
                'score': float(row.get('score', 0)),
                'contraction_ratio': float(row.get('contraction_ratio', 0)),
                'entry_price': float(row.get('entry_price', 0)),
                'current_price': float(row.get('entry_price', 0)),
                'return_pct': 0,
                'status': row.get('status', 'OPEN')
            })

        return jsonify({
            'signals': signals[:20],
            'count': len(signals),
            'source': 'csv_fallback'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@kr_bp.route('/vcp-history')
def get_vcp_history():
    """VCP 시그널 히스토리 (signals_log.csv 기반)"""
    try:
        name_map, market_map, _ = _load_ticker_maps()
        days = request.args.get('days', 30, type=int)

        signals_path = os.path.join(DATA_DIR, 'signals_log.csv')
        if not os.path.exists(signals_path):
            return jsonify({'signals': [], 'count': 0})

        df = pd.read_csv(signals_path, encoding='utf-8-sig', dtype={'ticker': str})
        df['ticker'] = df['ticker'].str.zfill(6)

        # 날짜 필터
        if 'signal_date' in df.columns:
            df['signal_date'] = pd.to_datetime(df['signal_date'], errors='coerce')
            cutoff = pd.Timestamp.now() - pd.Timedelta(days=days)
            df = df[df['signal_date'] >= cutoff]
            df = df.sort_values('signal_date', ascending=False)

        signals = []
        for idx, row in df.iterrows():
            ticker = str(row.get('ticker', '')).zfill(6)
            entry_price = float(row.get('entry_price', 0))
            exit_price = float(row.get('exit_price', 0)) if pd.notna(row.get('exit_price')) else None
            return_pct = float(row.get('return_pct', 0)) if pd.notna(row.get('return_pct')) else None
            hold_days = int(row.get('hold_days', 0)) if pd.notna(row.get('hold_days')) else None
            status = str(row.get('status', 'OPEN'))

            # CSV에 name/market 컬럼이 없거나 비어있으면 ticker_map에서 조회
            csv_name = str(row.get('name', '')).strip() if pd.notna(row.get('name')) else ''
            csv_market = str(row.get('market', '')).strip() if pd.notna(row.get('market')) else ''

            signals.append({
                'id': int(idx),
                'ticker': ticker,
                'name': csv_name or name_map.get(ticker, ticker),
                'market': csv_market or market_map.get(ticker, ''),
                'signalDate': row['signal_date'].strftime('%m월 %d일') if hasattr(row['signal_date'], 'strftime') else str(row['signal_date']),
                'foreign5d': int(row.get('foreign_5d', 0)) if pd.notna(row.get('foreign_5d')) else 0,
                'inst5d': int(row.get('inst_5d', 0)) if pd.notna(row.get('inst_5d')) else 0,
                'score': float(row.get('score', 0)) if pd.notna(row.get('score')) else 0,
                'contractionRatio': float(row.get('contraction_ratio', 0)) if pd.notna(row.get('contraction_ratio')) else 0,
                'entryPrice': entry_price,
                'status': status,
                'exitPrice': exit_price,
                'exitDate': str(row.get('exit_date', '')) if pd.notna(row.get('exit_date')) else None,
                'returnPct': return_pct,
                'holdDays': hold_days,
            })

        return jsonify({
            'signals': signals,
            'count': len(signals),
            'days': days,
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@kr_bp.route('/vcp-stats')
def get_vcp_stats():
    """VCP 전략 성과 통계"""
    try:
        signals_path = os.path.join(DATA_DIR, 'signals_log.csv')
        if not os.path.exists(signals_path):
            return jsonify({
                'total_signals': 0, 'closed_signals': 0, 'open_signals': 0,
                'win_rate': 0, 'avg_return_pct': 0, 'max_return_pct': 0,
                'min_return_pct': 0, 'avg_hold_days': 0,
                'total_winners': 0, 'total_losers': 0,
            })

        df = pd.read_csv(signals_path, encoding='utf-8-sig')

        total = len(df)
        if total == 0:
            return jsonify({'error': 'Empty signal data'}), 404

        has_status = 'status' in df.columns
        closed = df[df['status'] == 'CLOSED'] if has_status else pd.DataFrame()
        open_count = len(df[df['status'] == 'OPEN']) if has_status else total

        closed_count = len(closed)
        winners = 0
        losers = 0
        returns = []

        if closed_count > 0 and 'return_pct' in closed.columns:
            closed_valid = closed[closed['return_pct'].notna()]
            returns = closed_valid['return_pct'].tolist()
            winners = int((closed_valid['return_pct'] > 0).sum())
            losers = int((closed_valid['return_pct'] <= 0).sum())

        win_rate = round(winners / max(winners + losers, 1) * 100, 1)
        avg_return = round(sum(returns) / max(len(returns), 1), 2) if returns else 0
        max_return = round(max(returns), 2) if returns else 0
        min_return = round(min(returns), 2) if returns else 0

        avg_hold = 0
        if closed_count > 0 and 'hold_days' in closed.columns:
            hold_valid = closed[closed['hold_days'].notna()]
            if len(hold_valid) > 0:
                avg_hold = round(hold_valid['hold_days'].mean(), 1)

        return jsonify({
            'total_signals': total,
            'closed_signals': closed_count,
            'open_signals': open_count,
            'win_rate': win_rate,
            'avg_return_pct': avg_return,
            'max_return_pct': max_return,
            'min_return_pct': min_return,
            'avg_hold_days': avg_hold,
            'total_winners': winners,
            'total_losers': losers,
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ============================================================
# 종가베팅 (Closing Bet) Legacy API - REMOVED
# 현재 engine/ 기반 jongga-v2 API 사용 중
# ============================================================


@kr_bp.route('/stock-chart/<ticker>')
def get_kr_stock_chart(ticker):
    """KR 종목 차트 데이터 (실시간 포함)"""
    try:
        # Load from daily_prices.csv
        prices_path = os.path.join(DATA_DIR, 'daily_prices.csv')
        if not os.path.exists(prices_path):
            return jsonify({'error': 'Price data not found'}), 404
        
        df = pd.read_csv(prices_path, dtype={'ticker': str}, encoding='utf-8-sig')
        ticker_padded = str(ticker).zfill(6)
        stock_df = df[df['ticker'] == ticker_padded].copy()
        
        if stock_df.empty:
            return jsonify({'error': 'Ticker not found'}), 404
        
        stock_df['date'] = pd.to_datetime(stock_df['date'])
        stock_df = stock_df.sort_values('date')
        
        # Prepare chart data from history
        chart_data = []
        # Optimization: Take last 300 rows to ensure we have enough history but not too much payload
        history_df = stock_df.tail(300)
        
        for _, row in history_df.iterrows():
            chart_data.append({
                'date': row['date'].strftime('%Y-%m-%d'),
                'open': float(row.get('open', row['current_price'])),
                'high': float(row.get('high', row['current_price'])),
                'low': float(row.get('low', row['current_price'])),
                'close': float(row['current_price']),
                'volume': int(row.get('volume', 0))
            })

        # Check if we need to append today's real-time data
        if not history_df.empty:
            last_date = history_df.iloc[-1]['date']
            today = datetime.now().date()
            
            # If last data is not from today (and it's a weekday), try to fetch real-time data
            if last_date.date() < today and today.weekday() < 5:
                try:
                    from pykrx import stock
                    today_str = today.strftime('%Y%m%d')
                    
                    # Fetch just today's OHLCV
                    today_ohlcv = stock.get_market_ohlcv(today_str, today_str, ticker_padded)
                    
                    if not today_ohlcv.empty:
                        # pykrx returns DataFrame with columns: 시가, 고가, 저가, 종가, 거래량
                        row = today_ohlcv.iloc[0]
                        
                        # Only append if we have valid price (> 0) to avoid pre-market zeros
                        if row['종가'] > 0:
                            chart_data.append({
                                'date': today.strftime('%Y-%m-%d'),
                                'open': float(row['시가']),
                                'high': float(row['고가']),
                                'low': float(row['저가']),
                                'close': float(row['종가']),
                                'volume': int(row['거래량'])
                            })
                except Exception as rt_error:
                    logger.warning(f"Error fetching real-time data for {ticker_padded}: {rt_error}")
        
        return jsonify({
            'ticker': ticker_padded,
            'data': chart_data
        })
    except Exception as e:
        logger.error(f"Error in get_kr_stock_chart: {e}")
        return jsonify({'error': str(e)}), 500


@kr_bp.route('/ai-summary/<ticker>')
def get_kr_ai_summary(ticker):
    """KR AI 종목 요약"""
    try:
        json_path = os.path.join(DATA_DIR, 'kr_ai_analysis.json')
        if os.path.exists(json_path):
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            signals = data.get('signals', [])
            for signal in signals:
                if signal.get('ticker') == ticker:
                    return jsonify({
                        'ticker': ticker,
                        'summary': signal.get('ai_analysis', ''),
                        'grade': signal.get('grade', ''),
                        'score': signal.get('score', 0)
                    })
        
        return jsonify({'ticker': ticker, 'summary': None})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@kr_bp.route('/ai-analysis')
def get_kr_ai_analysis():
    """KR AI 분석 전체"""
    try:
        json_path = os.path.join(DATA_DIR, 'kr_ai_analysis.json')
        if os.path.exists(json_path):
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify(data)
        return jsonify({'signals': [], 'generated_at': None})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@kr_bp.route('/ai-history-dates')
def get_kr_ai_history_dates():
    """AI 분석 히스토리 날짜"""
    try:
        history_dir = os.path.join(DATA_DIR, 'history')
        if not os.path.exists(history_dir):
            return jsonify({'dates': []})
        
        dates = sorted([
            f.replace('.json', '')
            for f in os.listdir(history_dir)
            if f.endswith('.json')
        ], reverse=True)
        
        return jsonify({'dates': dates[:30]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@kr_bp.route('/ai-history/<date>')
def get_kr_ai_history(date):
    """특정 날짜 AI 분석"""
    try:
        history_file = os.path.join(DATA_DIR, 'history', f'{date}.json')
        if os.path.exists(history_file):
            with open(history_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify(data)
        return jsonify({'error': 'Date not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500



# ── 누적 성과 캐시 ───────────────────────────────────────────
_cumulative_cache: dict = {}       # {'data': ..., 'ts': 0}
_CUMULATIVE_TTL = 1800             # 30분 캐시

_TARGET_PCT = 9.0   # 목표 수익률 %
_STOP_PCT = 5.0     # 손절 %


def _build_yf_ticker(code: str, market: str) -> str:
    """KRX 종목코드 → yfinance 티커"""
    suffix = '.KS' if market.upper() == 'KOSPI' else '.KQ'
    return f"{code}{suffix}"


def _batch_fetch_prices(tickers: list, start_date: str) -> dict:
    """yfinance로 가격 일괄 다운로드 → {ticker: DataFrame}"""
    import yfinance as yf

    result = {}
    chunk_size = 30
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i:i + chunk_size]
        try:
            df = yf.download(
                chunk,
                start=start_date,
                auto_adjust=True,
                progress=False,
                threads=True,
            )
            if df.empty:
                continue

            # 단일 티커일 때 columns가 1-level
            if len(chunk) == 1:
                t = chunk[0]
                if 'High' in df.columns:
                    result[t] = df[['High', 'Low', 'Close']].dropna()
            else:
                # multi-ticker: MultiIndex columns (Price, Ticker)
                for t in chunk:
                    try:
                        sub = df.xs(t, level='Ticker', axis=1) if 'Ticker' in df.columns.names else None
                        if sub is None:
                            # 최신 yfinance: columns = [('Close', ticker), ('High', ticker), ...]
                            cols_h = ('High', t) if ('High', t) in df.columns else None
                            cols_l = ('Low', t) if ('Low', t) in df.columns else None
                            cols_c = ('Close', t) if ('Close', t) in df.columns else None
                            if cols_h and cols_l and cols_c:
                                sub = pd.DataFrame({
                                    'High': df[cols_h],
                                    'Low': df[cols_l],
                                    'Close': df[cols_c],
                                }).dropna()
                                result[t] = sub
                        else:
                            if 'High' in sub.columns:
                                result[t] = sub[['High', 'Low', 'Close']].dropna()
                    except Exception as e:
                        logger.warning(f"yfinance ticker parse failed for {t}: {e}")
                        continue
        except Exception as e:
            logger.warning(f"yfinance batch fetch failed (chunk {i}): {e}")
            continue

    return result


def _evaluate_signal(sig: dict, prices: dict, today_str: str) -> dict:
    """개별 시그널의 승/패/오픈 판정 + ROI 계산"""
    code = sig['stock_code']
    market = sig.get('market', 'KOSPI')
    yf_ticker = _build_yf_ticker(code, market)
    entry = sig.get('entry_price', 0) or sig.get('current_price', 0)
    target = sig.get('target_price', 0)
    stop = sig.get('stop_price', 0)
    sig_date = sig.get('signal_date', '')
    score = sig.get('score', {})

    # 기본값
    outcome = 'OPEN'
    outcome_date = None
    outcome_price = entry
    roi_pct = 0.0
    days_held = 0
    current_price = entry
    max_high = entry
    max_high_pct = 0.0
    price_trail = []

    if not entry or not sig_date:
        return _format_signal(sig, outcome, outcome_date, outcome_price,
                              roi_pct, days_held, current_price,
                              max_high, max_high_pct, price_trail, score)

    # target/stop이 없으면 고정 비율 사용
    if not target:
        target = entry * (1 + _TARGET_PCT / 100)
    if not stop:
        stop = entry * (1 - _STOP_PCT / 100)

    df = prices.get(yf_ticker)
    if df is None or df.empty:
        return _format_signal(sig, outcome, outcome_date, outcome_price,
                              roi_pct, days_held, current_price,
                              max_high, max_high_pct, price_trail, score)

    # 시그널 다음날부터의 가격 데이터
    try:
        mask = df.index > pd.Timestamp(sig_date)
        post_df = df.loc[mask]
    except Exception as e:
        logger.warning(f"Failed to filter post-signal data for {sig_date}: {e}")
        post_df = pd.DataFrame()

    if post_df.empty:
        return _format_signal(sig, outcome, outcome_date, outcome_price,
                              roi_pct, days_held, current_price,
                              max_high, max_high_pct, price_trail, score)

    # 일별 판정
    for i, (dt, row) in enumerate(post_df.iterrows()):
        day_high = float(row.get('High', 0) or 0)
        day_low = float(row.get('Low', 0) or 0)
        day_close = float(row.get('Close', 0) or 0)
        day_str = dt.strftime('%Y-%m-%d')

        if day_high > 0:
            max_high = max(max_high, day_high)

        # price trail 생성
        if entry > 0:
            hp = round((day_high - entry) / entry * 100, 2) if day_high else 0
            cp = round((day_close - entry) / entry * 100, 2) if day_close else 0
            price_trail.append({
                'd': day_str,
                'h': round(day_high),
                'c': round(day_close),
                'hp': hp,
                'cp': cp,
            })

        # 목표/손절 판정 (먼저 발생한 쪽)
        if outcome == 'OPEN':
            hit_target = day_high >= target
            hit_stop = day_low <= stop

            if hit_target and hit_stop:
                # 당일 둘 다 → 시가 기준 판정
                # 보수적: STOP_HIT (실전에서 손절이 먼저 걸릴 확률 높음)
                outcome = 'STOP_HIT'
                outcome_date = day_str
                outcome_price = round(stop)
            elif hit_target:
                outcome = 'TARGET_HIT'
                outcome_date = day_str
                outcome_price = round(target)
            elif hit_stop:
                outcome = 'STOP_HIT'
                outcome_date = day_str
                outcome_price = round(stop)

    # 현재가 / ROI / days 계산
    last_row = post_df.iloc[-1]
    current_price = round(float(last_row.get('Close', 0) or 0))
    last_date = post_df.index[-1]

    if outcome == 'OPEN':
        outcome_price = current_price
        roi_pct = round((current_price - entry) / entry * 100, 2) if entry else 0
        days_held = (last_date - pd.Timestamp(sig_date)).days
    else:
        roi_pct = round((outcome_price - entry) / entry * 100, 2) if entry else 0
        try:
            days_held = (pd.Timestamp(outcome_date) - pd.Timestamp(sig_date)).days
        except Exception as e:
            logger.warning(f"Failed to calculate days_held: {e}")
            days_held = 0

    max_high_pct = round((max_high - entry) / entry * 100, 2) if entry and max_high > entry else 0

    return _format_signal(sig, outcome, outcome_date, outcome_price,
                          roi_pct, days_held, current_price,
                          max_high, max_high_pct, price_trail, score)


def _format_signal(sig, outcome, outcome_date, outcome_price,
                   roi_pct, days_held, current_price,
                   max_high, max_high_pct, price_trail, score) -> dict:
    """프론트엔드 CumulativeSignal 인터페이스에 맞게 포맷"""
    entry = sig.get('entry_price', 0) or sig.get('current_price', 0)
    # hold_roi_pct: 손절/익절 없이 현시점까지 보유했을 때의 수익률
    hold_roi_pct = round((current_price - entry) / entry * 100, 2) if entry and current_price else 0.0
    return {
        'stock_code': sig.get('stock_code', ''),
        'stock_name': sig.get('stock_name', ''),
        'market': sig.get('market', ''),
        'signal_date': sig.get('signal_date', ''),
        'grade': sig.get('grade', ''),
        'score_total': score.get('total', 0) if isinstance(score, dict) else 0,
        'entry_price': entry,
        'target_price': sig.get('target_price', 0),
        'stop_price': sig.get('stop_price', 0),
        'outcome': outcome,
        'outcome_date': outcome_date,
        'outcome_price': round(outcome_price) if outcome_price else 0,
        'roi_pct': roi_pct,
        'hold_roi_pct': hold_roi_pct,
        'days_held': days_held,
        'current_price': current_price,
        'max_high': round(max_high) if max_high else 0,
        'max_high_pct': max_high_pct,
        'price_trail': price_trail,
        'themes': sig.get('themes', []) or [],
        'llm_reason': (score.get('llm_reason', '') if isinstance(score, dict) else ''),
        'change_pct': sig.get('change_pct', 0),
    }


def _calculate_cumulative_stats(signals: list, today_str: str) -> dict:
    """전체 누적 통계 계산"""
    total = len(signals)
    wins = sum(1 for s in signals if s['outcome'] == 'TARGET_HIT')
    losses = sum(1 for s in signals if s['outcome'] == 'STOP_HIT')
    opens = sum(1 for s in signals if s['outcome'] == 'OPEN')

    closed = [s for s in signals if s['outcome'] != 'OPEN']
    all_roi = [s['roi_pct'] for s in closed]
    avg_roi = round(sum(all_roi) / len(all_roi), 2) if all_roi else 0
    total_roi = round(sum(all_roi), 2)

    days_list = [s['days_held'] for s in closed if s['days_held'] > 0]
    avg_days = round(sum(days_list) / len(days_list), 1) if days_list else 0

    win_rate = round(wins / (wins + losses) * 100, 1) if (wins + losses) > 0 else 0

    # ── Hold 전략 통계 (손절/익절 없이 현시점까지 보유) ──
    # 가격 데이터가 있는 시그널만 (hold_roi_pct != 0 또는 current_price != entry)
    hold_signals = [s for s in signals if s.get('current_price', 0) and s.get('entry_price', 0)]
    hold_rois = [s['hold_roi_pct'] for s in hold_signals]
    hold_avg_roi = round(sum(hold_rois) / len(hold_rois), 2) if hold_rois else 0
    hold_total_roi = round(sum(hold_rois), 2)
    hold_wins = sum(1 for r in hold_rois if r > 0)
    hold_losses = sum(1 for r in hold_rois if r <= 0)
    hold_win_rate = round(hold_wins / len(hold_rois) * 100, 1) if hold_rois else 0
    # 중앙값 (평균보다 극단치에 강건)
    sorted_rois = sorted(hold_rois)
    hold_median_roi = sorted_rois[len(sorted_rois) // 2] if sorted_rois else 0

    # 등급별 ROI
    grade_roi = {}
    for grade in ('S', 'A', 'B'):
        grade_sigs = [s for s in signals if s['grade'] == grade]
        grade_closed = [s for s in grade_sigs if s['outcome'] != 'OPEN']
        g_wins = sum(1 for s in grade_sigs if s['outcome'] == 'TARGET_HIT')
        g_losses = sum(1 for s in grade_sigs if s['outcome'] == 'STOP_HIT')
        g_roi = [s['roi_pct'] for s in grade_closed]

        # 등급별 hold 전략
        g_hold = [s['hold_roi_pct'] for s in grade_sigs if s.get('current_price') and s.get('entry_price')]
        g_hold_avg = round(sum(g_hold) / len(g_hold), 2) if g_hold else 0
        g_hold_wins = sum(1 for r in g_hold if r > 0)
        g_hold_wr = round(g_hold_wins / len(g_hold) * 100, 1) if g_hold else 0

        grade_roi[grade] = {
            'count': len(grade_sigs),
            'wins': g_wins,
            'losses': g_losses,
            'avg_roi': round(sum(g_roi) / len(g_roi), 2) if g_roi else 0,
            'total_roi': round(sum(g_roi), 2),
            'win_rate': round(g_wins / (g_wins + g_losses) * 100, 1) if (g_wins + g_losses) > 0 else 0,
            'hold_avg_roi': g_hold_avg,
            'hold_win_rate': g_hold_wr,
        }

    return {
        'total': total,
        'wins': wins,
        'losses': losses,
        'open': opens,
        'win_rate': win_rate,
        'avg_roi': avg_roi,
        'total_roi': total_roi,
        'avg_days_held': avg_days,
        'latest_price_date': today_str,
        'target_pct': _TARGET_PCT,
        'stop_pct': _STOP_PCT,
        'grade_roi': grade_roi,
        # Hold 전략 (현시점까지 보유 시)
        'hold_avg_roi': hold_avg_roi,
        'hold_total_roi': hold_total_roi,
        'hold_median_roi': hold_median_roi,
        'hold_win_rate': hold_win_rate,
        'hold_wins': hold_wins,
        'hold_losses': hold_losses,
    }


@kr_bp.route('/cumulative-return')
def get_kr_cumulative_return():
    """종가베팅 V2 누적 성과 — 아카이브 + yfinance 가격 추적"""
    try:
        import glob as glob_module

        now = time.time()
        # 캐시 확인
        if _cumulative_cache.get('data') and now - _cumulative_cache.get('ts', 0) < _CUMULATIVE_TTL:
            return jsonify(_cumulative_cache['data'])

        # 파일 캐시 확인 (30분 이내 생성된 파일이면 재사용)
        cache_path = os.path.join(DATA_DIR, 'cumulative_performance.json')
        if os.path.exists(cache_path):
            file_age = now - os.path.getmtime(cache_path)
            if file_age < _CUMULATIVE_TTL:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                _cumulative_cache['data'] = data
                _cumulative_cache['ts'] = now
                return jsonify(data)

        # 1. 전체 아카이브 로드
        files = sorted(glob_module.glob(os.path.join(DATA_DIR, 'jongga_v2_results_*.json')))
        all_signals = []
        for fp in files:
            try:
                with open(fp, 'r', encoding='utf-8') as f:
                    d = json.load(f)
                for sig in d.get('signals', []):
                    if sig.get('grade') in ('S', 'A', 'B'):
                        all_signals.append(sig)
            except Exception as e:
                logger.warning(f"Failed to load signal file: {e}")
                continue

        if not all_signals:
            empty = {'signals': [], 'stats': _calculate_cumulative_stats([], datetime.now().strftime('%Y-%m-%d'))}
            return jsonify(empty)

        # 2. 고유 티커 수집 + 최초 날짜
        ticker_set = set()
        earliest = None
        for sig in all_signals:
            code = sig['stock_code']
            market = sig.get('market', 'KOSPI')
            ticker_set.add(_build_yf_ticker(code, market))
            sd = sig.get('signal_date', '')
            if sd and (earliest is None or sd < earliest):
                earliest = sd

        # 3. yfinance 일괄 가격 다운로드
        logger.info(f"[cumulative] Fetching prices for {len(ticker_set)} tickers from {earliest}")
        prices = _batch_fetch_prices(list(ticker_set), earliest)
        logger.info(f"[cumulative] Got prices for {len(prices)} tickers")

        # 4. 시그널별 판정
        today_str = datetime.now().strftime('%Y-%m-%d')
        processed = []
        for sig in all_signals:
            processed.append(_evaluate_signal(sig, prices, today_str))

        # 날짜 내림차순 정렬
        processed.sort(key=lambda x: x['signal_date'], reverse=True)

        # 5. 통계 계산
        stats = _calculate_cumulative_stats(processed, today_str)

        result = {'signals': processed, 'stats': stats}

        # 파일 캐시 저장
        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[cumulative] Cache save failed: {e}")

        _cumulative_cache['data'] = result
        _cumulative_cache['ts'] = now
        return jsonify(result)

    except Exception as e:
        logger.error(f"[cumulative-return] Error: {e}\n{traceback.format_exc()}")
        return jsonify({'error': str(e)}), 500


@kr_bp.route('/performance')
def get_kr_performance():
    """KR 퍼포먼스"""
    try:
        perf_path = os.path.join(DATA_DIR, 'performance.json')
        if os.path.exists(perf_path):
            with open(perf_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify(data)
        return jsonify({'performance': []})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@kr_bp.route('/jongga-v2/performance', methods=['GET'])
def get_jongga_v2_performance():
    """종가베팅 V2 히스토리 성과 — 전체 아카이브 집계"""
    try:
        import glob as glob_module
        data_dir = DATA_DIR
        files = sorted(glob_module.glob(os.path.join(data_dir, 'jongga_v2_results_*.json')))

        history = []
        total_signals = 0
        grade_totals = {'S': 0, 'A': 0, 'B': 0, 'C': 0}

        for fp in files:
            try:
                with open(fp, 'r', encoding='utf-8') as f:
                    d = json.load(f)
                signals = d.get('signals', [])
                by_grade = d.get('by_grade', {})
                top_signal = None
                for sig in signals:
                    if sig.get('grade') in ('S', 'A'):
                        top_signal = {
                            'stock_name': sig.get('stock_name', ''),
                            'stock_code': sig.get('stock_code', ''),
                            'grade': sig.get('grade', ''),
                            'change_pct': sig.get('change_pct', 0),
                            'score': sig.get('score', {}).get('total', 0),
                        }
                        break

                day_entry = {
                    'date': d.get('date', ''),
                    'total_signals': d.get('filtered_count', len(signals)),
                    'by_grade': by_grade,
                    'top_signal': top_signal,
                }
                history.append(day_entry)
                total_signals += d.get('filtered_count', len(signals))
                for grade, cnt in by_grade.items():
                    grade_totals[grade] = grade_totals.get(grade, 0) + cnt
            except Exception as e:
                logger.warning(f"Failed to parse history file: {e}")
                continue

        return jsonify({
            'days_count': len(history),
            'total_signals': total_signals,
            'grade_totals': grade_totals,
            'history': history,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@kr_bp.route('/jongga-v2/today-summary', methods=['GET'])
def get_jongga_v2_today_summary():
    """오늘 종가베팅 요약 — 최신 파일 기반"""
    try:
        data_dir = DATA_DIR
        latest_file = os.path.join(data_dir, 'jongga_v2_latest.json')
        d = load_json_cached(latest_file, ttl=300)
        if d is None:
            return jsonify({'signals': 0, 'top_signal': None, 'by_grade': {}})
        signals = d.get('signals', [])
        by_grade = d.get('by_grade', {})
        top_signal = None
        for sig in signals:
            if sig.get('grade') in ('S', 'A'):
                top_signal = {
                    'stock_name': sig.get('stock_name', ''),
                    'stock_code': sig.get('stock_code', ''),
                    'grade': sig.get('grade', ''),
                    'change_pct': sig.get('change_pct', 0),
                    'entry_price': sig.get('entry_price', 0),
                    'target_price': sig.get('target_price', 0),
                    'score': sig.get('score', {}).get('total', 0),
                }
                break
        return jsonify({
            'date': d.get('date', ''),
            'total_signals': d.get('filtered_count', len(signals)),
            'by_grade': by_grade,
            'top_signal': top_signal,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@kr_bp.route('/vcp-scan', methods=['POST'])
@admin_required
def kr_vcp_scan():
    """VCP 스캔 실행"""
    try:
        from scheduler import run_vcp_signal_scan

        result = run_vcp_signal_scan()
        return jsonify(result)
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@kr_bp.route('/update', methods=['POST'])
@admin_required
def kr_update():
    """KR 데이터 업데이트"""
    try:
        from scheduler import run_full_update
        
        result = run_full_update()
        return jsonify(result)
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500



@kr_bp.route('/market-gate')
def kr_market_gate():
    """KR Market Gate 상태 — 스냅샷 우선, 실패 시 stale 폴백.

    1) 캐시 <10분 → fresh 반환
    2) 라이브 계산 시도 (FinanceDataReader는 종종 30s+ hang/500)
    3) 라이브 실패 시 캐시 (나이 무관) → stale=true 로 반환
    """
    import time as _time
    snap_path = os.path.join(DATA_DIR, 'market_gate_cache.json')

    def _read_cache():
        try:
            if os.path.exists(snap_path):
                with open(snap_path, 'r', encoding='utf-8') as f:
                    return json.load(f), _time.time() - os.path.getmtime(snap_path)
        except (IOError, OSError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to load market gate cache: {e}")
        return None, None

    cached, age = _read_cache()
    if cached is not None and age is not None and age < 600:  # 10분 fresh TTL
        return jsonify(cached)

    # 라이브 시도 — 실패(예외 또는 5xx) 시 stale 폴백
    try:
        live = _compute_kr_market_gate_live()
    except Exception as e:
        logger.warning(f"market-gate live raised: {e}; serving stale")
        live = None

    # _compute_kr_market_gate_live 는 실패 시 (Response, 500) 튜플 반환할 수 있음
    if isinstance(live, tuple) and len(live) >= 2 and isinstance(live[1], int) and live[1] >= 500:
        logger.warning(f"market-gate live returned {live[1]}; serving stale")
        live = None

    if live is not None:
        return live

    if cached is not None:
        cached['stale'] = True
        cached['stale_age_sec'] = int(age) if age else None
        return jsonify(cached)
    return jsonify({'error': 'market gate unavailable', 'sectors': []}), 503


def _compute_kr_market_gate_live():
    """KR Market Gate 실시간 계산 + 스냅샷 저장"""
    try:
        # sys.path may be polluted by crypto routes inserting
        # crypto-analytics/crypto_market at position 0, which shadows the
        # root market_gate.py. Load it by absolute file path to avoid that.
        import importlib.util
        _mg_path = os.path.join(BASE_DIR, 'market_gate.py')
        _spec = importlib.util.spec_from_file_location('_root_market_gate', _mg_path)
        _mg = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mg)
        run_kr_market_gate = _mg.run_kr_market_gate

        # Run enhanced analysis
        res = run_kr_market_gate()
        
        # Helper to safely convert float/NaN
        def safe_float(val):
            if not pd.notna(val):
                return None
            if isinstance(val, float) and (val == float('inf') or val == float('-inf')):
                return None
            return val

        # Map sectors to frontend format
        sectors_data = []
        for s in res.sectors:
            sectors_data.append({
                'name': s.name,
                'signal': s.signal.lower(),  # bullish, bearish, neutral
                'change_pct': round(s.change_1d, 2) if safe_float(s.change_1d) is not None else 0,
                'score': s.score
            })
            
        # Determine label based on gate color
        label = "NEUTRAL"
        if res.gate == "GREEN":
            label = "BULLISH"
        elif res.gate == "RED":
            label = "BEARISH"
            
        # Sanitize metrics
        safe_metrics = {}
        for k, v in res.metrics.items():
            safe_metrics[k] = safe_float(v)
            
        # Extract KOSPI/KOSDAQ data for frontend
        kospi_close = safe_metrics.get('kospi', 0)
        kospi_change_pct = safe_metrics.get('kospi_change_pct', 0)
        kosdaq_close = safe_metrics.get('kosdaq', 0)
        kosdaq_change_pct = safe_metrics.get('kosdaq_change_pct', 0)

        result = {
            'status': res.gate,  # RED, YELLOW, GREEN
            'score': res.score,
            'label': label,
            'reasons': res.reasons,
            'sectors': sectors_data,
            'metrics': safe_metrics,
            # Frontend expects these at top level
            'kospi_close': kospi_close,
            'kospi_change_pct': kospi_change_pct,
            'kosdaq_close': kosdaq_close,
            'kosdaq_change_pct': kosdaq_change_pct,
            'updated_at': datetime.now().isoformat()
        }
        # 스냅샷 저장
        try:
            snap_path = os.path.join(DATA_DIR, 'market_gate_cache.json')
            with open(snap_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save market gate cache: {e}")
        return jsonify(result)

    except Exception as e:
        logger.error(f"Market gate enhanced analysis failed: {e}")
        # Fallback to simple logic if enhanced fails
        try:
            prices_path = os.path.join(DATA_DIR, 'daily_prices.csv')
            if not os.path.exists(prices_path):
                return jsonify({'status': 'NEUTRAL', 'score': 50, 'sectors': []})
            
            df = pd.read_csv(prices_path, dtype={'ticker': str}, encoding='utf-8-sig')
            market_df = df[df['ticker'] == '069500'].copy()
            
            if not market_df.empty and len(market_df) > 200:
                last_price = market_df.iloc[-1]['current_price']
                ma200 = market_df['current_price'].rolling(200).mean().iloc[-1]
                
                score = 80 if last_price > ma200 else 20
                status = "RISK_ON" if last_price > ma200 else "RISK_OFF"
                
                return jsonify({
                    'status': status, 
                    'score': score, 
                    'sectors': [],
                    'error': f"Enhanced failed: {str(e)}"
                })
        except Exception as fallback_err:
            logger.warning(f"Market gate fallback also failed: {fallback_err}")

        return jsonify({'error': str(e), 'sectors': []}), 500



@kr_bp.route('/realtime-prices', methods=['POST'])
def get_kr_realtime_prices():
    """실시간 가격 일괄 조회"""
    try:
        data = request.get_json() or {}
        tickers = data.get('tickers', [])
        
        if not tickers:
            return jsonify({})

        # 1. Load Ticker Map
        yahoo_map = {}
        # Flexible path resolution
        candidates = [
            os.path.join(BASE_DIR, 'ticker_to_yahoo_map.csv'),
            os.path.join(DATA_DIR, 'ticker_to_yahoo_map.csv'),
        ]
        ticker_map_path = 'ticker_to_yahoo_map.csv'
        for p in candidates:
            if os.path.exists(p):
                ticker_map_path = p
                break

        if os.path.exists(ticker_map_path):
            try:
                map_df = pd.read_csv(ticker_map_path, dtype={'ticker': str}, encoding='utf-8-sig')
                yahoo_map = dict(zip(map_df['ticker'].str.zfill(6), map_df['yahoo_ticker']))
            except Exception as e:
                logger.warning(f"Failed to load ticker map from {ticker_map_path}: {e}")
        
        # 2. Prepare Yahoo Tickers
        yf_tickers = []
        req_ticker_map = {}  # yf_ticker -> request_ticker
        
        for t in tickers:
            orig_t = str(t).zfill(6)
            # Use map if available, else try simple heuristic (KS/KQ logic is hard without db, default to KS)
            # Or assume the caller might send .KS/.KQ? No, frontend sends 6 digits.
            # If map missing, we might fail for Kosdaq.
            # Fallback: Try both? No, too expensive.
            # Just default to .KS if not in map, but usually map should cover it.
            yf_t = yahoo_map.get(orig_t, f"{orig_t}.KS") 
            yf_tickers.append(yf_t)
            req_ticker_map[yf_t] = orig_t

        # 3. Fetch Data
        import yfinance as yf
        # Optimize: 1m interval is good for realtime.
        df = yf.download(yf_tickers, period='1d', interval='1m', progress=False, threads=True)
        
        result = {}
        if not df.empty:
            closes = df['Close']
            
            # Handle Single Ticker Result (Series) vs Multi (DataFrame)
            if len(yf_tickers) == 1:
                val = float(closes.iloc[-1])
                t = req_ticker_map[yf_tickers[0]]
                if val > 0:
                    result[t] = val
            else:
                for yf_t in yf_tickers:
                    try:
                        # yfinance output columns might not match input list order strictly or might skip failed ones
                        if yf_t in closes.columns:
                            val = closes[yf_t].iloc[-1]
                            if pd.notna(val) and float(val) > 0:
                                t = req_ticker_map[yf_t]
                                result[t] = float(val)
                    except Exception as exc:
                        logger.warning(f"Realtime price lookup failed for {yf_t}: {exc}")

        return jsonify(result)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@kr_bp.route('/jongga-v2/latest', methods=['GET'])
def get_jongga_v2_latest():
    """종가베팅 v2 최신 결과 조회"""
    try:
        # data 디렉토리 경로 (패키지 루트 기준)
        data_dir = DATA_DIR
        latest_file = os.path.join(data_dir, 'jongga_v2_latest.json')

        data = load_json_cached(latest_file, ttl=300)
        if data is None:
            # 파일이 없으면 혹시 날짜별 파일 중 가장 최신 것이라도 찾음
            import glob
            files = glob.glob(os.path.join(data_dir, 'jongga_v2_results_*.json'))
            if not files:
                return jsonify({
                    "date": date.today().isoformat(),
                    "signals": [],
                    "message": "No data available"
                })
            fallback = max(files, key=os.path.getctime)
            data = load_json_cached(fallback, ttl=300)
            if data is None:
                return jsonify({"error": "Failed to read latest file"}), 500

        return jsonify(data)
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@kr_bp.route('/jongga-v2/dates', methods=['GET'])
def get_jongga_v2_dates():
    """데이터가 존재하는 날짜 목록 조회 (빈 파일 제외)"""
    try:
        data_dir = DATA_DIR
        # jongga_v2_results_YYYYMMDD.json 패턴 검색
        import glob
        files = glob.glob(os.path.join(data_dir, 'jongga_v2_results_*.json'))

        dates = []
        for f in files:
            # 파일명에서 날짜 추출 (jongga_v2_results_20240115.json)
            basename = os.path.basename(f)
            if len(basename) >= 26:  # 최소 길이 체크
                input_date = basename[18:26]  # 20240115

                # 빈 파일(0 시그널 = 휴장일) 제외: 500바이트 미만이면 데이터 없음
                if os.path.getsize(f) < 500:
                    continue

                formatted = f"{input_date[:4]}-{input_date[4:6]}-{input_date[6:]}"
                dates.append(formatted)

        dates.sort(reverse=True)  # 최신순 정렬
        return jsonify(dates)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@kr_bp.route('/jongga-v2/history/<date_str>', methods=['GET'])
def get_jongga_v2_history(date_str):
    """
    특정 날짜의 종가베팅 v2 결과 조회
    date_str: YYYYMMDD 또는 YYYY-MM-DD 둘 다 지원
    """
    try:
        base_dir = DATA_DIR

        # YYYY-MM-DD → YYYYMMDD 변환 (프론트에서 둘 다 올 수 있음)
        clean_date = date_str.replace('-', '')
        filename = f"jongga_v2_results_{clean_date}.json"

        file_path = os.path.join(base_dir, filename)

        if not os.path.exists(file_path):
            return jsonify({"error": f"Data not found for {date_str}"}), 404

        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        return jsonify(data)

    except Exception as e:
        logger.error(f"Error reading historical data: {e}")
        return jsonify({"error": str(e)}), 500

@kr_bp.route('/jongga-v2/analyze', methods=['POST'])
@admin_required
def analyze_single_stock():
    """
    단일 종목 재분석 요청
    """
    try:
        req_data = request.get_json()
        code = req_data.get('code')
        
        if not code:
            return jsonify({"error": "Stock code is required"}), 400
            
        # Async 함수 실행을 위한 처리
        import asyncio
        from engine.generator import analyze_single_stock_by_code
        
        result = asyncio.run(analyze_single_stock_by_code(code))
        
        if result:
            return jsonify({"status": "success", "signal": result.to_dict()})
        else:
            return jsonify({"status": "failed", "message": "Analysis failed or no signal generated"}), 500
            
    except Exception as e:
        logger.error(f"Error re-analyzing stock {code}: {e}")
        return jsonify({"error": str(e)}), 500

@kr_bp.route('/jongga-v2/run', methods=['POST'])
@admin_required
def run_jongga_v2():
    """
    전체 종가베팅 v2 엔진 실행 (배치)
    """
    try:
        from engine.generator import run_screener
        import asyncio
        
        # 5천만원 기본 자본금으로 실행
        result = asyncio.run(run_screener(capital=50_000_000))
        
        return jsonify({
            "status": "success",
            "date": result.date.isoformat(),
            "filtered_count": result.filtered_count,
            "processing_time": result.processing_time_ms
        })
        
    except Exception as e:
        logger.error(f"Error running Jongga V2 engine: {e}")
        return jsonify({"error": str(e)}), 500


# ── VCP Enhanced ──────────────────────────────────────────────────────────────

@kr_bp.route('/vcp-enhanced')
def get_kr_vcp_enhanced():
    """KR VCP 통합 분석 — 캐시 파일 기반 반환."""
    try:
        cached_path = os.path.join(DATA_DIR, 'vcp_kr_latest.json')
        if os.path.exists(cached_path):
            with open(cached_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            resp = jsonify(data)
            resp.headers['Cache-Control'] = 'public, max-age=300'
            return resp
        return jsonify({"metadata": {"market": "KR"}, "summary": {}, "signals": []}), 200
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@kr_bp.route('/vcp-dates')
@kr_bp.route('/vcp-enhanced/dates')
def get_kr_vcp_dates():
    """KR VCP 히스토리 날짜 목록 반환."""
    try:
        import re
        dates = []
        pattern = re.compile(r'vcp_kr_(\d{8})\.json')
        for fname in os.listdir(DATA_DIR):
            m = pattern.match(fname)
            if m:
                d = m.group(1)
                dates.append(f"{d[:4]}-{d[4:6]}-{d[6:]}")
        dates.sort(reverse=True)
        return jsonify(dates)
    except Exception as e:
        return jsonify([]), 200


@kr_bp.route('/vcp-report/<date>')
@kr_bp.route('/vcp-enhanced/history/<date>')
def get_kr_vcp_report(date):
    """KR VCP 특정 날짜 리포트 반환 (date: YYYY-MM-DD)."""
    try:
        date_str = date.replace('-', '')
        path = os.path.join(DATA_DIR, f'vcp_kr_{date_str}.json')
        if not os.path.exists(path):
            return jsonify({"error": f"No report for {date}"}), 404
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        resp = jsonify(data)
        resp.headers['Cache-Control'] = 'public, max-age=3600'
        return resp
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ═══ 주도주LIVE 스크리너 ═══

@kr_bp.route('/screener/leading')
def kr_screener_leading():
    """주도주 실시간 스크리닝 — 장중: 라이브 스캔, 장 마감: 마지막 유효 결과"""
    try:
        from app.services.kis_screener import run_screening, load_latest, is_market_open, _result_cache, _result_lock
        import time as _time

        market_open = is_market_open()

        # 1. 메모리 캐시 (3초 TTL)
        with _result_lock:
            cached_data = _result_cache["data"]
            cached_ts = _result_cache["ts"]
        if cached_data and (_time.time() - cached_ts) < 3:
            resp = jsonify(cached_data)
            resp.headers['Cache-Control'] = 'no-cache, no-store'
            return resp

        # 2. 장 마감 시 → 파일 캐시만 반환 (새 스캔 안 함)
        if not market_open:
            latest = load_latest()
            if latest:
                latest["market_status"] = "closed"
                resp = jsonify(latest)
                resp.headers['Cache-Control'] = 'no-cache, no-store'
                return resp

        # 3. 장중 — 파일 캐시 반환 + 백그라운드 스캔 트리거
        latest = load_latest()
        if latest:
            resp = jsonify(latest)
            resp.headers['Cache-Control'] = 'no-cache, no-store'
            import threading
            threading.Thread(target=run_screening, daemon=True).start()
            return resp

        # 4. 캐시 없음 — 라이브 실행 (첫 호출)
        result = run_screening()
        resp = jsonify(result)
        resp.headers['Cache-Control'] = 'no-cache, no-store'
        return resp
    except Exception as e:
        logger.warning(f"스크리너 에러: {e}")
        return jsonify({"error": str(e), "results": [], "timestamp": "", "market_status": "error",
                        "by_grade": {}, "total_candidates": 0, "time_weight": 1.0,
                        "api_calls": 0, "elapsed_ms": 0}), 500


@kr_bp.route('/screener/leading/history')
def kr_screener_history():
    """주도주 히스토리 — ?date=20260324 또는 ?dates=true"""
    from app.services.kis_screener import load_history, list_dates
    import re
    date = request.args.get('date')
    if request.args.get('dates'):
        return jsonify({"dates": list_dates()})
    if not date:
        return jsonify({"error": "date 파라미터 필요"}), 400
    if not re.match(r'^\d{8}$', date):
        return jsonify({"error": "Invalid date format (YYYYMMDD)"}), 400
    result = load_history(date)
    if not result:
        return jsonify({"error": f"{date} 데이터 없음"}), 404
    return jsonify(result)


@kr_bp.route('/screener/leading/status')
def kr_screener_status():
    """스크리너 상태"""
    try:
        from app.services import kis_screener
        with kis_screener._result_lock:
            cache_ts = kis_screener._result_cache.get("ts", 0)
            cache_data = kis_screener._result_cache.get("data")
        return jsonify({
            "market_open": kis_screener.is_market_open(),
            "market_status": kis_screener.get_market_status(),
            "token_valid": kis_screener.get_token() is not None,
            "cache_age": round(time.time() - cache_ts, 1) if cache_ts > 0 else None,
            "last_results": len(cache_data.get("results", [])) if cache_data else 0,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ════════════════════════════════════════════════════════════
# AI Chart Analysis (Gemini Vision)
# ════════════════════════════════════════════════════════════

@kr_bp.route('/ai-chart-analysis')
def get_ai_chart_analysis():
    """Gemini Vision 차트 분석 결과 CSV → JSON"""
    csv_path = os.path.join(BASE_DIR, 'gemini_chart_analysis_kr.csv')
    if not os.path.exists(csv_path):
        return jsonify({"error": "분석 결과 파일이 없습니다", "signals": [], "summary": {}}), 404

    try:
        df = pd.read_csv(csv_path, encoding='utf-8-sig')
        if df.empty:
            return jsonify({"signals": [], "summary": {}, "updated_at": None})

        # CSV → list[dict]
        signals = []
        for _, row in df.iterrows():
            reasons_raw = row.get('reasons', '')
            reasons = [r.strip() for r in str(reasons_raw).split('|') if r.strip()] if reasons_raw else []
            signals.append({
                "stock_code": str(row.get('종목코드', '')).zfill(6),
                "stock_name": row.get('종목명', ''),
                "market": row.get('시장', ''),
                "signal": row.get('signal', ''),
                "confidence": int(row.get('confidence', 0)),
                "ma_status": row.get('ma_status', ''),
                "rsi_zone": row.get('rsi_zone', ''),
                "volume_trend": row.get('volume_trend', ''),
                "reasons": reasons,
            })

        # Summary stats
        signal_counts = {}
        for s in signals:
            sig = s['signal']
            signal_counts[sig] = signal_counts.get(sig, 0) + 1

        market_counts = {}
        for s in signals:
            m = s['market']
            market_counts[m] = market_counts.get(m, 0) + 1

        avg_confidence = round(sum(s['confidence'] for s in signals) / len(signals), 1) if signals else 0

        # File mod time
        mtime = os.path.getmtime(csv_path)
        updated_at = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M')

        return jsonify({
            "signals": signals,
            "summary": {
                "total": len(signals),
                "by_signal": signal_counts,
                "by_market": market_counts,
                "avg_confidence": avg_confidence,
            },
            "updated_at": updated_at,
        })
    except Exception as e:
        logger.error(f"AI Chart Analysis 로드 실패: {e}")
        return jsonify({"error": str(e)}), 500


@kr_bp.route('/ai-chart-analysis/download')
def download_ai_chart_analysis():
    """AI 차트 분석 결과 Excel 다운로드"""
    import io
    from flask import send_file
    csv_path = os.path.join(BASE_DIR, 'gemini_chart_analysis_kr.csv')
    if not os.path.exists(csv_path):
        return jsonify({"error": "분석 결과 파일이 없습니다"}), 404

    try:
        df = pd.read_csv(csv_path, encoding='utf-8-sig')
        df.rename(columns={
            '종목코드': 'Code', '종목명': 'Name', '시장': 'Market',
            'signal': 'Signal', 'confidence': 'Confidence',
            'ma_status': 'MA Status', 'rsi_zone': 'RSI Zone',
            'volume_trend': 'Volume Trend', 'reasons': 'Reasons',
        }, inplace=True)

        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='AI Chart Analysis')
        buf.seek(0)

        today = datetime.now().strftime('%Y%m%d')
        return send_file(
            buf,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=f'ai_chart_analysis_kr_{today}.xlsx',
        )
    except Exception as e:
        logger.error(f"AI Chart Excel 생성 실패: {e}")
        return jsonify({"error": str(e)}), 500


@kr_bp.route('/ai-chart-image/<stock_code>')
def get_ai_chart_image(stock_code: str):
    """차트 이미지 PNG 서빙"""
    from flask import send_from_directory
    charts_dir = os.path.join(BASE_DIR, 'charts_kr')
    if not os.path.isdir(charts_dir):
        return jsonify({"error": "charts_kr 디렉토리 없음"}), 404

    # stock_code로 시작하는 파일 찾기 (예: 005930_삼성전자.png)
    for fname in os.listdir(charts_dir):
        if fname.startswith(stock_code) and fname.endswith('.png'):
            return send_from_directory(charts_dir, fname, mimetype='image/png')

    return jsonify({"error": f"차트 이미지 없음: {stock_code}"}), 404

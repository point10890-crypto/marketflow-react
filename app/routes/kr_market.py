# app/routes/kr_market.py
"""KR 마켓 API 라우트"""

import os
import sys
import json
import logging
import traceback
from datetime import datetime, date
import pandas as pd
from flask import Blueprint, jsonify, request, current_app

logger = logging.getLogger(__name__)

kr_bp = Blueprint('kr', __name__)

# ── 고정 경로 ──────────────────────────────────────────────
_ROUTES_DIR = os.path.dirname(os.path.abspath(__file__))  # app/routes/
_APP_DIR = os.path.dirname(_ROUTES_DIR)                    # app/
_BASE_DIR = os.path.dirname(_APP_DIR)                      # project root (bitman_marketfloww)
DATA_DIR = os.path.join(_BASE_DIR, 'data')

# market_gate 임포트를 위한 경로 등록
if _BASE_DIR not in sys.path:
    sys.path.insert(0, _BASE_DIR)


@kr_bp.route('/market-status')
def get_kr_market_status():
    """한국 시장 상태"""
    try:
        prices_path = os.path.join(DATA_DIR, 'daily_prices.csv')
        if not os.path.exists(prices_path):
            return jsonify({'status': 'UNKNOWN', 'reason': 'No price data'}), 404
            
        df = pd.read_csv(prices_path, dtype={'ticker': str})
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
        print(f"Error checking market status: {e}")
        return jsonify({'error': str(e)}), 500


def _load_ticker_maps():
    """ticker_to_yahoo_map.csv에서 name/market/yahoo 매핑 로드"""
    name_map = {}
    market_map = {}
    yahoo_map = {}
    candidates = [
        os.path.join(_BASE_DIR, 'ticker_to_yahoo_map.csv'),
        os.path.join(DATA_DIR, 'ticker_to_yahoo_map.csv'),
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                df = pd.read_csv(p, dtype={'ticker': str})
                df['ticker'] = df['ticker'].str.zfill(6)
                name_map = dict(zip(df['ticker'], df['name']))
                market_map = dict(zip(df['ticker'], df['market']))
                if 'yahoo_ticker' in df.columns:
                    yahoo_map = dict(zip(df['ticker'], df['yahoo_ticker']))
            except Exception as e:
                print(f"[WARN] ticker map load error: {e}")
            break
    return name_map, market_map, yahoo_map


@kr_bp.route('/signals')
def get_kr_signals():
    """오늘의 VCP + 외인매집 시그널"""
    try:
        name_map, market_map, yahoo_map = _load_ticker_maps()

        json_path = os.path.join(DATA_DIR, 'kr_ai_analysis.json')

        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

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
                print(f"Error reading JSON: {e}")
                pass

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
        
        df = pd.read_csv(prices_path, dtype={'ticker': str})
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
                    print(f"Error fetching real-time data for {ticker_padded}: {rt_error}")
        
        return jsonify({
            'ticker': ticker_padded,
            'data': chart_data
        })
    except Exception as e:
        print(f"Error in get_kr_stock_chart: {e}")
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


@kr_bp.route('/cumulative-return')
def get_kr_cumulative_return():
    """누적 수익률"""
    try:
        perf_path = os.path.join(DATA_DIR, 'performance.json')
        if os.path.exists(perf_path):
            with open(perf_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify(data)
        return jsonify({'cumulative_return': 0, 'trades': []})
    except Exception as e:
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
            except Exception:
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
        if not os.path.exists(latest_file):
            return jsonify({'signals': 0, 'top_signal': None, 'by_grade': {}})
        with open(latest_file, 'r', encoding='utf-8') as f:
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
def kr_vcp_scan():
    """VCP 스캔 실행"""
    try:
        from scheduler import run_vcp_scan
        
        result = run_vcp_scan()
        return jsonify(result)
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@kr_bp.route('/update', methods=['POST'])
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
    """KR Market Gate 상태 — 스냅샷 우선, 실시간 폴백"""
    # 스냅샷 파일 확인 (5분 이내면 즉시 반환)
    import time as _time
    snap_path = os.path.join(DATA_DIR, 'market_gate_cache.json')
    try:
        if os.path.exists(snap_path):
            age = _time.time() - os.path.getmtime(snap_path)
            if age < 300:  # 5분 TTL
                with open(snap_path, 'r', encoding='utf-8') as f:
                    return jsonify(json.load(f))
    except Exception:
        pass

    return _compute_kr_market_gate_live()


def _compute_kr_market_gate_live():
    """KR Market Gate 실시간 계산 + 스냅샷 저장"""
    try:
        from market_gate import run_kr_market_gate

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
        except Exception:
            pass
        return jsonify(result)

    except Exception as e:
        traceback.print_exc()
        # Fallback to simple logic if enhanced fails
        try:
            prices_path = os.path.join(DATA_DIR, 'daily_prices.csv')
            if not os.path.exists(prices_path):
                return jsonify({'status': 'NEUTRAL', 'score': 50, 'sectors': []})
            
            df = pd.read_csv(prices_path, dtype={'ticker': str})
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
            os.path.join(_BASE_DIR, 'ticker_to_yahoo_map.csv'),
            os.path.join(DATA_DIR, 'ticker_to_yahoo_map.csv'),
        ]
        ticker_map_path = 'ticker_to_yahoo_map.csv'
        for p in candidates:
            if os.path.exists(p):
                ticker_map_path = p
                break

        if os.path.exists(ticker_map_path):
            try:
                map_df = pd.read_csv(ticker_map_path, dtype={'ticker': str})
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
        
        if not os.path.exists(latest_file):
            # 파일이 없으면 혹시 날짜별 파일 중 가장 최신 것이라도 찾음
            import glob
            files = glob.glob(os.path.join(data_dir, 'jongga_v2_results_*.json'))
            if not files:
                return jsonify({
                    "date": date.today().isoformat(),
                    "signals": [],
                    "message": "No data available"
                })
            latest_file = max(files, key=os.path.getctime)
            
        with open(latest_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
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
        print(f"Error reading historical data: {e}")
        return jsonify({"error": str(e)}), 500

@kr_bp.route('/jongga-v2/analyze', methods=['POST'])
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
        print(f"Error re-analyzing stock {code}: {e}")
        return jsonify({"error": str(e)}), 500

@kr_bp.route('/jongga-v2/run', methods=['POST'])
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
        print(f"Error running Jongga V2 engine: {e}")
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
    """주도주 실시간 스크리닝 — 캐시 우선, 없으면 라이브 실행"""
    try:
        from app.services.kis_screener import run_screening, load_latest, _result_cache
        import time as _time
        # 1. 메모리 캐시 (3초 TTL)
        if _result_cache["data"] and (_time.time() - _result_cache["ts"]) < 3:
            resp = jsonify(_result_cache["data"])
            resp.headers['Cache-Control'] = 'no-cache, no-store'
            return resp
        # 2. 파일 캐시 (5분 이내면 즉시 반환)
        latest = load_latest()
        if latest:
            resp = jsonify(latest)
            resp.headers['Cache-Control'] = 'no-cache, no-store'
            # 백그라운드로 새 스캔 트리거 (다음 요청에 반영)
            import threading
            threading.Thread(target=run_screening, daemon=True).start()
            return resp
        # 3. 캐시 없음 — 라이브 실행 (첫 호출)
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
    date = request.args.get('date')
    if request.args.get('dates'):
        return jsonify({"dates": list_dates()})
    if not date:
        return jsonify({"error": "date 파라미터 필요"}), 400
    result = load_history(date)
    if not result:
        return jsonify({"error": f"{date} 데이터 없음"}), 404
    return jsonify(result)


@kr_bp.route('/screener/leading/status')
def kr_screener_status():
    """스크리너 상태"""
    try:
        from app.services import kis_screener
        cache = kis_screener._result_cache
        return jsonify({
            "market_open": kis_screener.is_market_open(),
            "market_status": kis_screener.get_market_status(),
            "token_valid": kis_screener.get_token() is not None,
            "cache_age": round(time.time() - cache["ts"], 1) if cache.get("ts") else None,
            "last_results": len(cache["data"]["results"]) if cache.get("data") else 0,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

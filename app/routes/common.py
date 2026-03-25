# app/routes/common.py
"""공통 API 라우트"""

import os
import json
import logging
import traceback
import pandas as pd
import yfinance as yf
import sys
import subprocess
from flask import Blueprint, jsonify, request, Response, stream_with_context

from app.utils.cache import get_sector, SECTOR_MAP
from app.utils.paths import BASE_DIR, DATA_DIR

logger = logging.getLogger(__name__)

common_bp = Blueprint('common', __name__)

# Ticker 맵 로드
try:
    # Load ticker map (절대경로 사용)
    map_path = os.path.join(BASE_DIR, 'ticker_to_yahoo_map.csv')
    if not os.path.exists(map_path):
        map_path = os.path.join(DATA_DIR, 'ticker_to_yahoo_map.csv')

    try:
        map_df = pd.read_csv(map_path, dtype=str)
    except FileNotFoundError:
        logger.warning("Ticker map not found: %s", map_path)
        map_df = pd.DataFrame()
    TICKER_TO_YAHOO_MAP = dict(zip(map_df['ticker'], map_df['yahoo_ticker']))
    logger.info("Loaded %d verified ticker mappings.", len(TICKER_TO_YAHOO_MAP))
except Exception as e:
    logger.warning("Error loading ticker map: %s", e)
    TICKER_TO_YAHOO_MAP = {}


@common_bp.route('/portfolio')
def get_portfolio_data():
    """포트폴리오 데이터 - KR Market"""
    try:
        target_date = request.args.get('date')
        
        if target_date:
            # --- Historical Data Mode ---
            csv_path = os.path.join(BASE_DIR, 'us_market', 'data', 'recommendation_history.csv')
            if not os.path.exists(csv_path):
                return jsonify({'error': 'History not found'}), 404
                
            df = pd.read_csv(csv_path, dtype={'ticker': str})
            df = df[df['recommendation_date'] == target_date]
            top_holdings_df = df.sort_values(by='final_investment_score', ascending=False).head(10)
            top_picks = top_holdings_df
            
            # Fetch Real-time Prices
            tickers = top_holdings_df['ticker'].tolist()
            current_prices = {}
            
            if tickers:
                yf_tickers = []
                ticker_map = {}
                
                for t in tickers:
                    t_padded = str(t).zfill(6)
                    yf_t = TICKER_TO_YAHOO_MAP.get(t_padded, f"{t_padded}.KS")
                    yf_tickers.append(yf_t)
                    ticker_map[yf_t] = t_padded

                try:
                    price_data = yf.download(yf_tickers, period='1d', interval='1m', progress=False, threads=True)
                    if not price_data.empty:
                        price_data = price_data.ffill()
                        if 'Close' in price_data.columns:
                            closes = price_data['Close']
                            for yf_t, orig_t in ticker_map.items():
                                try:
                                    if isinstance(closes, pd.DataFrame) and yf_t in closes.columns:
                                        val = closes[yf_t].iloc[-1]
                                        current_prices[orig_t] = float(val) if not pd.isna(val) else 0
                                    elif isinstance(closes, pd.Series) and closes.name == yf_t:
                                        val = closes.iloc[-1]
                                        current_prices[orig_t] = float(val) if not pd.isna(val) else 0
                                except Exception:
                                    current_prices[orig_t] = 0
                except Exception as e:
                    logger.warning("Error fetching historical prices: %s", e)

            top_holdings = []
            for _, row in top_holdings_df.iterrows():
                t_str = str(row['ticker']).zfill(6)
                rec_price = float(row['current_price'])
                cur_price = current_prices.get(t_str, 0)
                return_pct = ((cur_price - rec_price) / rec_price * 100) if rec_price > 0 else 0.0
                
                top_holdings.append({
                    'ticker': t_str,
                    'name': row['name'],
                    'price': cur_price,
                    'recommendation_price': rec_price,
                    'return_pct': return_pct,
                    'score': float(row['final_investment_score']),
                    'grade': row['investment_grade'],
                    'wave': row.get('wave_stage', 'N/A'),
                    'sd_stage': 'N/A',
                    'inst_trend': 'N/A',
                    'ytd': 0
                })
                
            key_stats = {
                'qtd_return': f"{top_holdings_df['final_investment_score'].mean():.1f}" if not top_holdings_df.empty else "0.0",
                'ytd_return': str(len(top_holdings_df)),
                'one_year_return': "N/A",
                'div_yield': "N/A",
                'expense_ratio': 'N/A'
            }
            holdings_distribution = []

        else:
            # --- Current Live Data Mode ---
            csv_path = os.path.join(DATA_DIR, 'wave_transition_analysis_results.csv')
            if not os.path.exists(csv_path):
                return jsonify({
                    'data_missing': True,
                    'key_stats': {'qtd_return': 'N/A', 'ytd_return': 'N/A', 'one_year_return': 'N/A', 'div_yield': 'N/A', 'expense_ratio': 'N/A'},
                    'holdings_distribution': [],
                    'top_holdings': [],
                    'style_box': {}
                })
    
            df = pd.read_csv(csv_path, dtype={'ticker': str})
            top_picks = df[df['investment_grade'].isin(['S급 (즉시 매수)', 'A급 (적극 매수)'])]
            
            avg_score = top_picks['final_investment_score'].mean() if not top_picks.empty else 0
            avg_return_potential = top_picks['price_change_6m'].mean() * 100 if not top_picks.empty else 0
            avg_div_yield = top_picks['div_yield'].mean() if not top_picks.empty else 0
            
            key_stats = {
                'qtd_return': f"{avg_score:.1f}",
                'ytd_return': f"{len(top_picks)}",
                'one_year_return': f"{avg_return_potential:.1f}%",
                'div_yield': f"{avg_div_yield:.1f}%",
                'expense_ratio': 'N/A'
            }
    
            market_counts = top_picks['market'].value_counts()
            holdings_distribution = []
            colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6']
            for i, (market, count) in enumerate(market_counts.items()):
                holdings_distribution.append({
                    'label': market,
                    'value': int(count),
                    'color': colors[i % len(colors)]
                })
                
            top_holdings_df = top_picks.sort_values(by='final_investment_score', ascending=False).head(10)
            top_holdings = []
            for _, row in top_holdings_df.iterrows():
                rec_price = float(row['current_price'])
                cur_price = float(row['current_price'])
                
                top_holdings.append({
                    'ticker': str(row['ticker']).zfill(6),
                    'name': row['name'],
                    'price': cur_price,
                    'recommendation_price': rec_price,
                    'return_pct': 0.0,
                    'score': float(row['final_investment_score']),
                    'grade': row['investment_grade'],
                    'wave': row.get('wave_stage', 'N/A'),
                    'sd_stage': row.get('supply_demand_stage', 'N/A'),
                    'inst_trend': row.get('institutional_trend', 'N/A'),
                    'ytd': float(row['price_change_20d']) * 100
                })

        # --- Style Box ---
        style_counts = {
            'large_value': 0, 'large_core': 0, 'large_growth': 0,
            'mid_value': 0, 'mid_core': 0, 'mid_growth': 0,
            'small_value': 0, 'small_core': 0, 'small_growth': 0
        }
        
        total_style_count = 0
        for _, row in top_picks.iterrows():
            market = row.get('market', 'KOSPI')
            is_large = market == 'KOSPI'
            pbr = row.get('pbr', 1.5)
            if pd.isna(pbr): pbr = 1.5
            
            style_suffix = '_core'
            if pbr < 1.0: style_suffix = '_value'
            elif pbr > 2.5: style_suffix = '_growth'
            
            size_prefix = 'large' if is_large else 'small'
            key = f"{size_prefix}{style_suffix}"
            if key in style_counts:
                style_counts[key] += 1
                total_style_count += 1

        style_box = {}
        if total_style_count > 0:
            for k, v in style_counts.items():
                style_box[k] = round((v / total_style_count) * 100, 1)
        else:
            style_box = {k: 0 for k in style_counts}

        latest_date = None
        if 'current_date' in df.columns and not df.empty:
            latest_date = df['current_date'].iloc[0]
        elif 'recommendation_date' in df.columns and not df.empty:
            latest_date = df['recommendation_date'].max()

        # --- Market Indices ---
        market_indices = _fetch_market_indices()

        # --- Performance Data ---
        performance_data = _fetch_performance_data()

        data = {
            'key_stats': key_stats,
            'market_indices': market_indices,
            'holdings_distribution': holdings_distribution,
            'top_holdings': top_holdings,
            'style_box': style_box,
            'performance': performance_data,
            'latest_date': latest_date
        }
        return jsonify(data)
    except Exception as e:
        logger.warning("Error getting portfolio data: %s", e)
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@common_bp.route('/portfolio-summary')
def portfolio_summary():
    """포트폴리오 요약"""
    try:
        summary = {
            'kr_market': {'count': 0, 'top_grade': '-'},
            'us_market': {'count': 0, 'top_grade': '-'},
            'crypto': {'count': 0, 'top_grade': '-'}
        }
        
        # KR Market
        kr_path = os.path.join(DATA_DIR, 'kr_ai_analysis.json')
        if os.path.exists(kr_path):
            with open(kr_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            signals = data.get('signals', [])
            summary['kr_market']['count'] = len(signals)
            if signals:
                summary['kr_market']['top_grade'] = signals[0].get('grade', '-')
        
        return jsonify(summary)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@common_bp.route('/stock/<ticker>')
def get_stock_detail(ticker):
    """개별 종목 상세 정보"""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        
        return jsonify({
            'ticker': ticker,
            'name': info.get('shortName', ticker),
            'sector': get_sector(ticker),
            'price': info.get('regularMarketPrice', 0),
            'change': info.get('regularMarketChange', 0),
            'change_pct': info.get('regularMarketChangePercent', 0),
            'volume': info.get('regularMarketVolume', 0),
            'market_cap': info.get('marketCap', 0),
            'pe_ratio': info.get('trailingPE', 0),
            'dividend_yield': info.get('dividendYield', 0) * 100 if info.get('dividendYield') else 0
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@common_bp.route('/realtime-prices', methods=['POST'])
def get_realtime_prices():
    """실시간 가격 조회"""
    try:
        data = request.get_json()
        tickers = data.get('tickers', [])
        market = data.get('market', 'kr')
        
        if not tickers:
            return jsonify({'prices': {}})
        
        prices = {}
        
        if market == 'kr':
            yf_tickers = []
            ticker_map = {}
            
            for t in tickers:
                t_padded = str(t).zfill(6)
                yf_t = TICKER_TO_YAHOO_MAP.get(t_padded, f"{t_padded}.KS")
                yf_tickers.append(yf_t)
                ticker_map[yf_t] = t_padded
            
            try:
                price_data = yf.download(yf_tickers, period='1d', interval='1m', progress=False, threads=True)
                if not price_data.empty:
                    price_data = price_data.ffill()
                    if 'Close' in price_data.columns:
                        closes = price_data['Close']
                        for yf_t, orig_t in ticker_map.items():
                            try:
                                if isinstance(closes, pd.DataFrame) and yf_t in closes.columns:
                                    val = closes[yf_t].iloc[-1]
                                    prices[orig_t] = float(val) if not pd.isna(val) else 0
                                elif isinstance(closes, pd.Series):
                                    val = closes.iloc[-1]
                                    prices[orig_t] = float(val) if not pd.isna(val) else 0
                            except Exception:
                                prices[orig_t] = 0
            except Exception as e:
                logger.warning("Error fetching realtime prices: %s", e)
        else:
            # US Market
            try:
                price_data = yf.download(tickers, period='1d', interval='1m', progress=False, threads=True)
                if not price_data.empty:
                    price_data = price_data.ffill()
                    if 'Close' in price_data.columns:
                        closes = price_data['Close']
                        for t in tickers:
                            try:
                                if isinstance(closes, pd.DataFrame) and t in closes.columns:
                                    val = closes[t].iloc[-1]
                                    prices[t] = float(val) if not pd.isna(val) else 0
                                elif isinstance(closes, pd.Series):
                                    val = closes.iloc[-1]
                                    prices[t] = float(val) if not pd.isna(val) else 0
                            except Exception:
                                prices[t] = 0
            except Exception as e:
                logger.warning("Error fetching US realtime prices: %s", e)
        
        return jsonify({'prices': prices})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@common_bp.route('/run-analysis', methods=['POST'])
def run_analysis():
    """분석 스크립트 백그라운드 실행"""
    try:
        import subprocess
        import threading
        
        def run_scripts():
            logger.info("Starting Analysis...")
            try:
                # 1. Run Analysis
                subprocess.run([sys.executable, 'analysis2.py'], check=True)
                logger.info("Analysis Complete.")

                # 2. Run Performance Tracking
                subprocess.run([sys.executable, 'track_performance.py'], check=True)
                logger.info("Performance Tracking Complete.")
                
            except Exception as e:
                logger.warning("Error running scripts: %s", e)

        # Start in background thread
        thread = threading.Thread(target=run_scripts)
        thread.start()
        
        return jsonify({'status': 'started', 'message': 'Analysis started in background.'})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def _fetch_market_indices():
    """마켓 인덱스 데이터 조회"""
    market_indices = []
    indices_map = {
        '^DJI': 'Dow Jones',
        '^GSPC': 'S&P 500',
        '^IXIC': 'NASDAQ',
        '^RUT': 'Russell 2000',
        '^VIX': 'VIX',
        'GC=F': 'Gold',
        'CL=F': 'Crude Oil',
        'BTC-USD': 'Bitcoin',
        '^TNX': '10Y Treasury',
        'DX-Y.NYB': 'Dollar Index',
        'KRW=X': 'USD/KRW'
    }
    
    try:
        tickers_list = list(indices_map.keys())
        idx_data = yf.download(tickers_list, period='5d', progress=False, threads=True)
        
        if not idx_data.empty:
            closes = idx_data['Close']
            
            for ticker, name in indices_map.items():
                try:
                    if isinstance(closes, pd.DataFrame) and ticker in closes.columns:
                        series = closes[ticker].dropna()
                    elif isinstance(closes, pd.Series) and closes.name == ticker:
                        series = closes.dropna()
                    else:
                        continue
                        
                    if len(series) >= 2:
                        current_val = series.iloc[-1]
                        prev_val = series.iloc[-2]
                        change = current_val - prev_val
                        change_pct = (change / prev_val) * 100
                        
                        market_indices.append({
                            'name': name,
                            'price': f"{current_val:,.2f}",
                            'change': f"{change:,.2f}",
                            'change_pct': change_pct,
                            'color': 'red' if change >= 0 else 'blue'
                        })
                except Exception as e:
                    logger.warning("Error processing index %s: %s", ticker, e)
                    
    except Exception as e:
        logger.warning("Error fetching market indices: %s", e)
    
    return market_indices


def _fetch_performance_data():
    """성과 데이터 조회"""
    performance_data = []
    perf_csv_path = os.path.join(BASE_DIR, 'us_market', 'data', 'performance_report.csv')
    
    if os.path.exists(perf_csv_path):
        perf_df = pd.read_csv(perf_csv_path)
        recent_perf = perf_df.sort_values('rec_date', ascending=False).head(10)
        for _, row in recent_perf.iterrows():
            performance_data.append({
                'ticker': row['ticker'],
                'name': row['name'],
                'return': f"{row['return']:.1f}%",
                'date': row['rec_date'],
                'days': row['days']
            })
    return performance_data


# common.py loaded successfully


@common_bp.route('/system/data-status')
def get_data_status():
    """데이터 파일 상태 조회"""
    from datetime import datetime
    

    
    # Check these data files
    data_files_to_check = [
        {
            'name': 'Daily Prices',
            'path': os.path.join(DATA_DIR, 'daily_prices.csv'),
            'link': '/dashboard/kr/closing-bet',
            'menu': 'Closing Bet'
        },
        {
            'name': 'Institutional Trend',
            'path': os.path.join(DATA_DIR, 'all_institutional_trend_data.csv'),
            'link': '/dashboard/kr/vcp',
            'menu': 'VCP Signals'
        },
        {
            'name': 'AI Analysis',
            'path': os.path.join(DATA_DIR, 'kr_ai_analysis.json'),
            'link': '/dashboard/kr/vcp',
            'menu': 'VCP Signals'
        },
        {
            'name': 'VCP Signals',
            'path': os.path.join(DATA_DIR, 'signals_log.csv'),
            'link': '/dashboard/kr/vcp',
            'menu': 'VCP Signals'
        },
        {
            'name': 'AI Jongga V2',
            'path': os.path.join(DATA_DIR, 'jongga_v2_latest.json'),
            'link': '/dashboard/kr/closing-bet',
            'menu': 'Closing Bet'
        },
        # ── Crypto Analytics ──
        {
            'name': 'Crypto Market Gate',
            'path': os.path.join(BASE_DIR, 'crypto-analytics', 'crypto_market', 'output', 'market_gate.json'),
            'link': '/dashboard/crypto',
            'menu': 'Crypto Overview'
        },
        {
            'name': 'Crypto Briefing',
            'path': os.path.join(BASE_DIR, 'crypto-analytics', 'crypto_market', 'output', 'crypto_briefing.json'),
            'link': '/dashboard/crypto/briefing',
            'menu': 'Crypto Briefing'
        },
        {
            'name': 'BTC Prediction',
            'path': os.path.join(BASE_DIR, 'crypto-analytics', 'crypto_market', 'output', 'btc_prediction.json'),
            'link': '/dashboard/crypto/prediction',
            'menu': 'Crypto Prediction'
        },
        {
            'name': 'Crypto Risk',
            'path': os.path.join(BASE_DIR, 'crypto-analytics', 'crypto_market', 'output', 'crypto_risk.json'),
            'link': '/dashboard/crypto/risk',
            'menu': 'Crypto Risk'
        },
        {
            'name': 'Lead-Lag Analysis',
            'path': os.path.join(BASE_DIR, 'crypto-analytics', 'crypto_market', 'lead_lag', 'results.json'),
            'link': '/dashboard/crypto/leadlag',
            'menu': 'Crypto Lead-Lag'
        },
        {
            'name': 'Crypto VCP Signals',
            'path': os.path.join(BASE_DIR, 'crypto-analytics', 'crypto_market', 'signals.sqlite3'),
            'link': '/dashboard/crypto/signals',
            'menu': 'Crypto Signals'
        },
        {
            'name': 'Crypto Backtest',
            'path': os.path.join(BASE_DIR, 'crypto-analytics', 'crypto_market', 'output', 'backtest_result.json'),
            'link': '/dashboard/crypto/backtest',
            'menu': 'Crypto Backtest'
        },
    ]
    
    files_status = []
    
    for file_info in data_files_to_check:
        path = file_info['path']
        exists = os.path.exists(path)
        
        if exists:
            stat = os.stat(path)
            size_bytes = stat.st_size
            mtime = datetime.fromtimestamp(stat.st_mtime)
            
            # Format size
            if size_bytes > 1024 * 1024:
                size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
            elif size_bytes > 1024:
                size_str = f"{size_bytes / 1024:.1f} KB"
            else:
                size_str = f"{size_bytes} B"
            
            # Count rows if CSV
            row_count = None
            if path.endswith('.csv'):
                try:
                    df = pd.read_csv(path, nrows=0)
                    row_count = sum(1 for _ in open(path)) - 1  # -1 for header
                except Exception:
                    logger.debug("Failed to read CSV row count: %s", path)
            elif path.endswith('.json'):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    if 'signals' in data:
                        row_count = len(data['signals'])
                except Exception:
                    logger.debug("Failed to read JSON signals count: %s", path)
            
            files_status.append({
                'name': file_info['name'],
                'path': path,
                'exists': True,
                'lastModified': mtime.isoformat(),
                'size': size_str,
                'rowCount': row_count,
                'link': file_info.get('link', ''),
                'menu': file_info.get('menu', '')
            })
        else:
            files_status.append({
                'name': file_info['name'],
                'path': path,
                'exists': False,
                'lastModified': '',
                'size': '-',
                'rowCount': None,
                'link': file_info.get('link', ''),
                'menu': file_info.get('menu', '')
            })
    
    # Check update status (simple implementation)
    update_status = {
        'isRunning': False,
        'lastRun': '',
        'progress': ''
    }
    
    # Check log file for last run info
    log_path = os.path.join(BASE_DIR, 'logs', 'kr_update.log')
    if os.path.exists(log_path):
        stat = os.stat(log_path)
        mtime = datetime.fromtimestamp(stat.st_mtime)
        update_status['lastRun'] = mtime.isoformat()
    
    return jsonify({
        'files': files_status,
        'update_status': update_status
    })


@common_bp.route('/system/update-single')
def update_single_data():
    """개별 데이터 업데이트 (SSE 스트리밍)"""
    data_type = request.args.get('type', '')
    
    # 지원하는 업데이트 타입과 실행할 명령 매핑
    update_commands = {
        'daily_prices': {
            'name': 'Daily Prices',
            'script': 'scheduler.py',
            'args': ['--prices']
        },
        'institutional': {
            'name': 'Institutional Trend',
            'script': 'scheduler.py',
            'args': ['--inst']
        },
        'ai_analysis': {
            'name': 'AI Analysis',
            'script': 'kr_ai_analyzer.py',
            'args': []
        },
        'vcp_signals': {
            'name': 'VCP Signals',
            'script': 'scheduler.py',
            'args': ['--signals']
        },
        'jongga_v2': {
            'name': 'Jongga V2 (Closing Bet)',
            'module': 'engine.generator',
            'function': 'run_screener'
        },
        # ── Crypto Analytics ──
        'crypto_gate': {
            'name': 'Crypto Market Gate',
            'script': os.path.join(BASE_DIR, 'crypto-analytics', 'crypto_market', 'market_gate.py'),
            'args': []
        },
        'crypto_scan': {
            'name': 'Crypto VCP Scan',
            'script': os.path.join(BASE_DIR, 'crypto-analytics', 'crypto_market', 'run_scan.py'),
            'args': []
        },
        'crypto_briefing': {
            'name': 'Crypto Briefing',
            'script': os.path.join(BASE_DIR, 'crypto-analytics', 'crypto_market', 'crypto_briefing.py'),
            'args': []
        },
        'crypto_prediction': {
            'name': 'Crypto Prediction',
            'script': os.path.join(BASE_DIR, 'crypto-analytics', 'crypto_market', 'crypto_prediction.py'),
            'args': []
        },
        'crypto_risk': {
            'name': 'Crypto Risk',
            'script': os.path.join(BASE_DIR, 'crypto-analytics', 'crypto_market', 'crypto_risk.py'),
            'args': []
        },
        'crypto_leadlag': {
            'name': 'Crypto Lead-Lag',
            'script': os.path.join(BASE_DIR, 'crypto-analytics', 'crypto_market', 'lead_lag', 'lead_lag_analysis.py'),
            'args': []
        },
    }
    
    if data_type not in update_commands:
        return jsonify({
            'error': f'Unknown data type: {data_type}',
            'available_types': list(update_commands.keys())
        }), 400
    
    config = update_commands[data_type]
    
    def generate():
        yield f"data: [SYSTEM] Starting {config['name']} update...\n\n"
        
        try:
            # For jongga_v2, use inline script to call run_screener
            if data_type == 'jongga_v2':
                script_code = '''
import asyncio
import sys
sys.path.insert(0, '.')
from engine.generator import run_screener
asyncio.run(run_screener(capital=50_000_000))
'''
                cmd = [sys.executable, '-u', '-c', script_code]
            else:
                script_path = config['script']
                if not os.path.exists(script_path):
                    yield f"data: [ERROR] Script not found: {script_path}\n\n"
                    yield "event: end\ndata: close\n\n"
                    return
                cmd = [sys.executable, '-u', script_path] + config.get('args', [])
            
            env = os.environ.copy()
            # 현재 실행 중인 파이썬의 라이브러리 경로들을 포함
            site_packages = [
                os.getcwd(),
                *sys.path
            ]
            env['PYTHONPATH'] = os.pathsep.join(site_packages)
            env['PYTHONUNBUFFERED'] = '1'  # Force unbuffered output
            env['KR_MARKET_DIR'] = os.getcwd()  # Set scheduler base directory
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=False,  # Binary mode to avoid Windows cp949 issues
                env=env,
                bufsize=0  # Unbuffered
            )
            
            # Read character by character to handle \r properly
            buffer = b""  # Binary buffer
            last_progress_line = ""
            
            while True:
                char = process.stdout.read(1)
                if not char:
                    break
                    
                if char == b'\n':
                    # Normal newline - send the line
                    try:
                        clean_line = buffer.decode('utf-8', errors='replace').strip()
                        if clean_line:
                            yield f"data: {clean_line}\n\n"
                    except Exception:
                        pass
                    buffer = b""
                elif char == b'\r':
                    # Carriage return (progress bar update)
                    try:
                        clean_line = buffer.decode('utf-8', errors='replace').strip()
                        if clean_line and clean_line != last_progress_line:
                            yield f"data: {clean_line}\n\n"
                            last_progress_line = clean_line
                    except Exception:
                        pass
                    buffer = b""
                else:
                    buffer += char
            
            # Flush remaining buffer
            if buffer.strip():
                try:
                    yield f"data: {buffer.decode('utf-8', errors='replace').strip()}\n\n"
                except Exception:
                    pass
            
            process.wait()
            
            if process.returncode == 0:
                yield f"data: [SYSTEM] {config['name']} update completed successfully.\n\n"
            else:
                yield f"data: [SYSTEM] {config['name']} update failed (exit code: {process.returncode})\n\n"
                
        except Exception as e:
            yield f"data: [ERROR] Failed: {str(e)}\n\n"
        
        yield "event: end\ndata: close\n\n"
    
    return Response(stream_with_context(generate()), mimetype='text/event-stream')


@common_bp.route('/system/update-data-stream')
def stream_update_data():
    """데이터 업데이트 프로세스 스트리밍 실행"""
    def generate():
        yield "data: [SYSTEM] Starting data update process...\n\n"
        
        try:
            # scheduler.py --now 실행
            script_path = 'scheduler.py'
            if not os.path.exists(script_path):
                 yield f"data: [ERROR] Script not found at {script_path}\n\n"
                 return

            cmd = [sys.executable, '-u', script_path, '--now']
            
            env = os.environ.copy()
            env['PYTHONPATH'] = os.getcwd() # Ensure module imports work
            env['KR_MARKET_DIR'] = os.getcwd()  # Set scheduler base directory
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=False,  # Binary mode
                env=env,
                bufsize=1
            )
            
            for line in process.stdout:
                # Manual decode to safely handle any encoding
                try:
                    clean_line = line.decode('utf-8', errors='replace').strip()
                    if clean_line:
                        yield f"data: {clean_line}\n\n"
                except Exception as decode_err:
                    yield f"data: [WARN] Decode error: {str(decode_err)}\n\n"
            
            process.wait()
            yield f"data: [SYSTEM] Process finished with exit code {process.returncode}\n\n"
            
            if process.returncode == 0:
                yield "data: [SYSTEM] Update completed successfully.\n\n"
            else:
                yield "data: [SYSTEM] Update failed. Check logs.\n\n"
                
        except Exception as e:
            yield f"data: [ERROR] Failed to start process: {str(e)}\n\n"
        
        yield "event: end\ndata: close\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')


@common_bp.route('/kr/backtest-summary')
def get_backtest_summary():
    """VCP 및 Closing Bet(Jongga V2) 백테스트 요약 반환"""
    import glob
    from datetime import datetime, timedelta
    
    summary = {
        'vcp': {'status': 'No Data', 'win_rate': 0, 'avg_return': 0, 'count': 0},
        'closing_bet': {'status': 'No Data', 'win_rate': 0, 'avg_return': 0, 'count': 0}
    }
    
    debug_info = {}

    # 1. VCP Backtest (기존 로직 유지)
    try:
        # Check potential paths for VCP results
        candidates = [
            os.path.join(DATA_DIR, 'backtest', 'final_backtest_results.csv'),
            os.path.join(DATA_DIR, 'final_backtest_results.csv'),
            os.path.join(BASE_DIR, 'final_backtest_results.csv')
        ]
        csv_path = None
        for p in candidates:
            if os.path.exists(p):
                csv_path = p
                break
             
        if os.path.exists(csv_path):
            df = pd.read_csv(csv_path)
            if not df.empty:
                is_win_col = 'is_winner' if 'is_winner' in df.columns else 'is_win'
                return_col = 'net_return' if 'net_return' in df.columns else 'return_pct'
                if return_col not in df.columns and 'return' in df.columns:
                    return_col = 'return'

                total = len(df)
                wins = 0
                avg_ret = 0

                if is_win_col in df.columns:
                    first_val = df[is_win_col].iloc[0]
                    if df[is_win_col].dtype == object or isinstance(first_val, str):
                        wins = len(df[df[is_win_col].astype(str).str.lower() == 'true'])
                    else:
                        wins = int(df[is_win_col].sum())
                elif return_col in df.columns:
                    wins = len(df[df[return_col] > 0])
                
                if return_col in df.columns:
                    avg_ret = df[return_col].mean()

                win_rate = (wins / total) * 100 if total > 0 else 0
                
                summary['vcp'] = {
                    'status': 'OK',
                    'count': int(total),
                    'win_rate': round(win_rate, 1),
                    'avg_return': round(avg_ret, 2)
                }
    except Exception as e:
        debug_info['vcp_error'] = str(e)
        summary['vcp']['error'] = str(e)

    # 2. Closing Bet (Jongga V2) Backtest
    try:
        data_dir = DATA_DIR
        history_files = glob.glob(os.path.join(data_dir, 'jongga_v2_results_*.json'))
        debug_info['jongga_files_count'] = len(history_files)
        
        if len(history_files) < 2:
            # 데이터 축적 중
            summary['closing_bet'] = {
                'status': 'Accumulating',
                'message': f'{len(history_files)}일 데이터 (최소 2일 필요)',
                'count': 0,
                'win_rate': 0,
                'avg_return': 0
            }
        else:
            # 히스토리 백테스트 수행
            all_signals = []
            today = datetime.now().strftime('%Y%m%d')
            
            for file_path in sorted(history_files):
                # 오늘 파일은 제외 (아직 결과 없음)
                if today in file_path:
                    continue
                    
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    for signal in data.get('signals', []):
                        signal['file_date'] = data.get('date', '')
                        all_signals.append(signal)
                except Exception:
                    continue
            
            debug_info['total_signals'] = len(all_signals)
            
            if all_signals:
                # 현재가 조회하여 수익률 계산
                wins = 0
                total_return = 0
                valid_count = 0
                
                for signal in all_signals:
                    entry_price = signal.get('entry_price', 0)
                    target_price = signal.get('target_price', 0)
                    stop_price = signal.get('stop_price', 0)
                    
                    if entry_price <= 0:
                        continue
                    
                    # 간이 백테스트: target 도달 여부 (실제로는 pykrx로 미래 가격 확인 필요)
                    # 현재는 change_pct 기반으로 추정
                    change_pct = signal.get('change_pct', 0)
                    
                    if change_pct > 0:
                        # 시그널 당일 상승 중이면 target 도달 가정 (5% 수익)
                        est_return = 5.0
                        wins += 1
                    else:
                        # 하락 중이면 손절 가정 (-3% 손실)
                        est_return = -3.0
                    
                    total_return += est_return
                    valid_count += 1
                
                if valid_count > 0:
                    win_rate = (wins / valid_count) * 100
                    avg_return = total_return / valid_count
                    
                    summary['closing_bet'] = {
                        'status': 'OK',
                        'count': valid_count,
                        'win_rate': round(win_rate, 1),
                        'avg_return': round(avg_return, 2)
                    }
                else:
                    summary['closing_bet'] = {
                        'status': 'No Valid Signals',
                        'count': 0,
                        'win_rate': 0,
                        'avg_return': 0
                    }
            else:
                summary['closing_bet'] = {
                    'status': 'Accumulating',
                    'message': '과거 시그널 없음',
                    'count': 0,
                    'win_rate': 0,
                    'avg_return': 0
                }
                
    except Exception as e:
        debug_info['jongga_error'] = str(e)
        summary['closing_bet']['error'] = str(e)

    response = summary.copy()
    response['debug'] = debug_info
    return jsonify(response)


@common_bp.route('/data-version')
def data_version():
    """주요 데이터 파일의 최종 수정 시간 반환 (프론트 변경 감지용)

    모바일·로컬 동시 갱신의 핵심: 프론트엔드가 이 엔드포인트를 polling하여
    파일 변경을 감지하면 실제 데이터를 refetch한다.
    """
    _base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    _data_dir = os.path.join(_base, 'data')

    target_files = [
        'jongga_v2_latest.json',
        'signals_log.csv',
        'daily_prices.csv',
        'kr_ai_analysis.json',
        'daily_report.json',
    ]
    versions = {}
    for fname in target_files:
        fpath = os.path.join(_data_dir, fname)
        if os.path.exists(fpath):
            versions[fname] = os.path.getmtime(fpath)
        else:
            versions[fname] = 0

    import time
    return jsonify({'versions': versions, 'timestamp': time.time()})


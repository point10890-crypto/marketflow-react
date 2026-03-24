# app/routes/us_market.py
"""US 마켓 API 라우트"""

import os
import json
import traceback
from datetime import datetime
import pandas as pd
import yfinance as yf
from flask import Blueprint, jsonify, request

from app.utils.cache import get_sector
from app.utils.paths import BASE_DIR, US_MARKET_DIR, US_OUTPUT_DIR, US_DATA_DIR, US_HISTORY_DIR, US_PREVIEW_DIR
from app.utils.safety import safe_float, safe_str

us_bp = Blueprint('us', __name__)

# 경로 별칭 (기존 코드 호환)
_US_MARKET_DIR = US_MARKET_DIR
_OUTPUT_DIR = US_OUTPUT_DIR
_DATA_DIR = US_DATA_DIR
_HISTORY_DIR = US_HISTORY_DIR
_PREVIEW_DIR = US_PREVIEW_DIR


def _fetch_portfolio_live():
    """yfinance로 실시간 포트폴리오 데이터 수집 + JSON 스냅샷 저장"""
    market_indices = []
    indices_map = {
        '^DJI': 'Dow Jones', '^GSPC': 'S&P 500', '^IXIC': 'NASDAQ',
        '^RUT': 'Russell 2000', '^VIX': 'VIX', 'GC=F': 'Gold',
        'CL=F': 'Crude Oil', 'BTC-USD': 'Bitcoin', '^TNX': '10Y Treasury',
        'DX-Y.NYB': 'Dollar Index', 'KRW=X': 'USD/KRW'
    }
    for ticker, name in indices_map.items():
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period='5d')
            if not hist.empty and len(hist) >= 2:
                current_val = float(hist['Close'].iloc[-1])
                prev_val = float(hist['Close'].iloc[-2])
                change = current_val - prev_val
                change_pct = (change / prev_val) * 100 if prev_val else 0.0
                market_indices.append({
                    'name': name, 'price': f"{current_val:,.2f}",
                    'change': f"{change:+,.2f}", 'change_pct': change_pct,
                    'color': 'green' if change >= 0 else 'red'
                })
        except Exception as e:
            print(f"Error fetching {ticker}: {e}")
    result = {'market_indices': market_indices, 'timestamp': datetime.now().isoformat()}
    # 스냅샷 저장
    try:
        snap_path = os.path.join(_OUTPUT_DIR, 'portfolio_snapshot.json')
        with open(snap_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return result


@us_bp.route('/portfolio')
def get_us_portfolio_data():
    """US Market Portfolio Data — 스냅샷 우선, 실시간 폴백"""
    try:
        # 1) 스냅샷 파일 확인 (5분 이내면 즉시 반환)
        snap_path = os.path.join(_OUTPUT_DIR, 'portfolio_snapshot.json')
        if os.path.exists(snap_path):
            import time as _time
            age = _time.time() - os.path.getmtime(snap_path)
            if age < 300:  # 5분 TTL
                with open(snap_path, 'r', encoding='utf-8') as f:
                    return jsonify(json.load(f))

        # 2) 실시간 수집 (스냅샷 없거나 만료)
        return jsonify(_fetch_portfolio_live())
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@us_bp.route('/smart-money')
def get_us_smart_money():
    """Smart Money Picks with dynamic sorting — 스냅샷 우선, 실시간 폴백"""
    import time as _time
    sort_by = request.args.get('sort_by', 'composite')
    lang = request.args.get('lang', 'ko')

    # 스냅샷 캐시 확인 (5분 이내 + 동일 sort/lang이면 즉시 반환)
    snap_path = os.path.join(_OUTPUT_DIR, 'smart_money_snapshot.json')
    try:
        if os.path.exists(snap_path):
            age = _time.time() - os.path.getmtime(snap_path)
            if age < 300:
                with open(snap_path, 'r', encoding='utf-8') as f:
                    cached = json.load(f)
                if cached.get('sort_by') == sort_by:
                    return jsonify(cached)
    except Exception:
        pass

    return _compute_smart_money_live(sort_by, lang)


def _compute_smart_money_live(sort_by='composite', lang='ko'):
    """Smart Money 실시간 계산 + 스냅샷 저장"""
    try:
        csv_path = os.path.join(_OUTPUT_DIR, 'smart_money_picks_v2.csv')
        if not os.path.exists(csv_path):
            csv_path = os.path.join(_OUTPUT_DIR, 'smart_money_picks.csv')

        if not os.path.exists(csv_path):
            # Fallback: smart_money_current.json
            json_path = os.path.join(_OUTPUT_DIR, 'smart_money_current.json')
            if os.path.exists(json_path):
                with open(json_path, 'r', encoding='utf-8') as f:
                    sm_data = json.load(f)
                picks = sm_data.get('picks', [])
                return jsonify({'picks': picks, 'count': len(picks),
                                'updated_at': sm_data.get('analysis_timestamp', sm_data.get('analysis_date', ''))})
            return jsonify({'picks': [], 'count': 0})

        df = pd.read_csv(csv_path)
        
        # Sort based on criteria
        if sort_by == 'swing' and 'swing_score' in df.columns:
            df = df.sort_values(['swing_score', 'composite_score'], ascending=[False, False])
        elif sort_by == 'trend' and 'trend_score' in df.columns:
            df = df.sort_values(['trend_score', 'composite_score'], ascending=[False, False])
        else:
            df = df.sort_values('composite_score', ascending=False)
        
        top_picks_df = df.head(15)
        
        # Load AI Summaries
        ai_summaries = {}
        summary_path = os.path.join(_OUTPUT_DIR, 'ai_summaries.json')
        if os.path.exists(summary_path):
            with open(summary_path, 'r', encoding='utf-8') as f:
                ai_summaries = json.load(f)
        
        # Fetch Realtime Prices
        tickers = top_picks_df['ticker'].tolist()
        current_prices = {}
        
        try:
            if tickers:
                data = yf.download(tickers, period='1d', interval='1m', progress=False, threads=True)
                if hasattr(data, 'columns') and isinstance(data.columns, pd.MultiIndex):
                    closes = data['Close'].iloc[-1]
                    for t in tickers:
                        if t in closes.index:
                            val = closes[t]
                            if pd.notna(val):
                                current_prices[t] = round(float(val), 2)
                elif not data.empty and 'Close' in data.columns:
                    current_prices[tickers[0]] = round(float(data['Close'].iloc[-1]), 2)
        except Exception as e:
            print(f"Batch price fetch failed: {e}")
        
        # Build Response
        picks = []
        for _, row in top_picks_df.iterrows():
            ticker = row['ticker']
            price_at_rec = row.get('current_price', 0)
            current_price = current_prices.get(ticker, price_at_rec)
            
            change_pct = 0
            if price_at_rec and price_at_rec > 0:
                change_pct = ((current_price - price_at_rec) / price_at_rec) * 100
            
            # Get AI summary
            ai_data = ai_summaries.get(ticker, {})
            summary = ai_data.get('summary_ko' if lang == 'ko' else 'summary_en', '')
            
            picks.append({
                'ticker': ticker,
                'name': row.get('name', ticker),
                'sector': get_sector(ticker),
                'price': current_price,
                'price_at_rec': price_at_rec,
                'change_pct': round(change_pct, 2),
                'composite_score': row.get('composite_score', 0),
                'swing_score': row.get('swing_score', 0),
                'trend_score': row.get('trend_score', 0),
                'ai_summary': summary,
                'recommendation': row.get('recommendation', ''),
                'grade': row.get('grade', '')
            })
        
        result = {
            'picks': picks,
            'count': len(picks),
            'sort_by': sort_by,
            'timestamp': datetime.now().isoformat()
        }
        # 스냅샷 저장
        try:
            snap_path = os.path.join(_OUTPUT_DIR, 'smart_money_snapshot.json')
            with open(snap_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        return jsonify(result)
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@us_bp.route('/etf-flows')
def get_us_etf_flows():
    """ETF 자금 흐름 (etf_flows.json → CSV 폴백)"""
    try:
        # 1차: API JSON (analyze_etf_flows.py가 생성)
        json_path = os.path.join(_OUTPUT_DIR, 'etf_flows.json')
        if os.path.exists(json_path):
            with open(json_path, 'r', encoding='utf-8') as f:
                return jsonify(json.load(f))

        # 2차: CSV 폴백 → JSON 변환
        csv_path = os.path.join(_OUTPUT_DIR, 'us_etf_flows.csv')
        if os.path.exists(csv_path):
            import csv
            flows = []
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    flows.append({
                        'ticker': row.get('ticker', ''),
                        'name': row.get('name', ''),
                        'category': row.get('category', ''),
                        'close': float(row.get('close', 0)),
                        'flow_5d': float(row.get('flow_5d', 0)),
                        'flow_20d': float(row.get('flow_20d', 0)),
                        'flow_score': float(row.get('flow_score', 50)),
                        'flow_status': row.get('flow_status', 'Neutral'),
                        'price_5d': float(row.get('price_5d', 0)),
                        'price_20d': float(row.get('price_20d', 0)),
                        'vol_ratio': float(row.get('vol_ratio', 1)),
                        'dollar_volume': float(row.get('dollar_volume', 0)),
                    })
            # AI 분석 병합
            ai_path = os.path.join(_OUTPUT_DIR, 'etf_flow_analysis.json')
            ai_text = ''
            if os.path.exists(ai_path):
                with open(ai_path, 'r', encoding='utf-8') as f:
                    ai_data = json.load(f)
                ai_text = ai_data.get('ai_analysis', '')
            return jsonify({'flows': flows, 'ai_analysis': ai_text})

        return jsonify({'flows': []})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@us_bp.route('/stock-chart/<ticker>')
def get_us_stock_chart(ticker):
    """US 주식 차트 데이터"""
    try:
        period = request.args.get('period', '1y')
        interval = request.args.get('interval', '1d')
        
        stock = yf.Ticker(ticker)
        hist = stock.history(period=period, interval=interval)
        
        if hist.empty:
            return jsonify({'error': 'No data found'}), 404
        
        chart_data = []
        for date, row in hist.iterrows():
            chart_data.append({
                'date': date.strftime('%Y-%m-%d'),
                'open': round(row['Open'], 2),
                'high': round(row['High'], 2),
                'low': round(row['Low'], 2),
                'close': round(row['Close'], 2),
                'volume': int(row['Volume'])
            })
        
        return jsonify({
            'ticker': ticker,
            'data': chart_data,
            'period': period
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@us_bp.route('/history-dates')
def get_us_history_dates():
    """US 히스토리 날짜 목록"""
    try:
        history_path = os.path.join(_HISTORY_DIR)
        if not os.path.exists(history_path):
            return jsonify({'dates': []})

        # Extract dates from picks_YYYY-MM-DD.json format
        dates = []
        for f in os.listdir(history_path):
            if f.startswith('picks_') and f.endswith('.json'):
                date_str = f[6:-5]  # Remove 'picks_' and '.json'
                dates.append(date_str)

        dates = sorted(dates, reverse=True)
        return jsonify({'dates': dates[:30]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@us_bp.route('/history/<date>')
def get_us_history_by_date(date):
    """특정 날짜 히스토리 (YYYY-MM-DD format)"""
    try:
        # Support both formats: picks_YYYY-MM-DD.json
        history_file = os.path.join(_HISTORY_DIR, f'picks_{date}.json')
        if os.path.exists(history_file):
            with open(history_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify(data)
        return jsonify({'error': 'Date not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@us_bp.route('/history/<date>/performance')
def get_us_history_performance(date):
    """특정 날짜 추천종목의 현재 성과 (CSV 기반)"""
    try:
        import pandas as pd
        import numpy as np

        history_file = os.path.join(_HISTORY_DIR, f'picks_{date}.json')
        if not os.path.exists(history_file):
            return jsonify({'error': 'Date not found'}), 404

        with open(history_file, 'r', encoding='utf-8') as f:
            snapshot = json.load(f)

        # Get current prices from CSV
        csv_path = os.path.join(_DATA_DIR, 'us_daily_prices.csv')
        current_prices = {}
        spy_return = 0.0

        if os.path.exists(csv_path):
            df = pd.read_csv(csv_path)
            latest_date = df['Date'].max()
            latest_df = df[df['Date'] == latest_date]

            tickers = [p['ticker'] for p in snapshot['picks']]
            for ticker in tickers:
                row = latest_df[latest_df['Ticker'] == ticker]
                if not row.empty:
                    current_prices[ticker] = float(row['Close'].iloc[0])

            # Calculate SPY benchmark
            spy_df = df[df['Ticker'] == 'SPY'].copy()
            spy_df = spy_df[spy_df['Date'] >= date].sort_values('Date')
            if len(spy_df) >= 2:
                spy_start = spy_df['Close'].iloc[0]
                spy_end = spy_df['Close'].iloc[-1]
                spy_return = ((spy_end / spy_start) - 1) * 100

        # Calculate performance
        result = {
            'analysis_date': snapshot['analysis_date'],
            'picks': [],
            'statistics': {}
        }

        changes = []
        for pick in snapshot['picks']:
            ticker = pick['ticker']
            price_at_rec = pick.get('price_at_analysis', 0)
            current_price = current_prices.get(ticker, price_at_rec)

            if price_at_rec > 0:
                change_pct = ((current_price / price_at_rec) - 1) * 100
            else:
                change_pct = 0

            changes.append(change_pct)

            result['picks'].append({
                'ticker': ticker,
                'name': pick.get('name', ticker),
                'rank': pick.get('rank', 0),
                'final_score': pick.get('final_score', 0),
                'price_at_rec': round(price_at_rec, 2),
                'current_price': round(current_price, 2),
                'change_pct': round(change_pct, 2)
            })

        # Statistics
        if changes:
            avg_return = float(np.mean(changes))
            win_count = len([c for c in changes if c > 0])

            result['statistics'] = {
                'avg_return': round(avg_return, 2),
                'spy_return': round(spy_return, 2),
                'alpha': round(avg_return - spy_return, 2),
                'win_rate': round(win_count / len(changes) * 100, 1),
                'win_count': win_count,
                'loss_count': len(changes) - win_count,
                'max_gain': round(max(changes), 2),
                'max_loss': round(min(changes), 2)
            }

        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@us_bp.route('/history-summary')
def get_us_history_summary():
    """전체 히스토리 성과 요약"""
    try:
        import pandas as pd
        import numpy as np

        history_path = os.path.join(_HISTORY_DIR)
        csv_path = os.path.join(_DATA_DIR, 'us_daily_prices.csv')

        if not os.path.exists(history_path) or not os.path.exists(csv_path):
            return jsonify({'error': 'Data not found'}), 404

        # Load price data
        df = pd.read_csv(csv_path)
        latest_date = df['Date'].max()
        latest_df = df[df['Date'] == latest_date]

        # Process each history file
        summaries = []
        for f in os.listdir(history_path):
            if f.startswith('picks_') and f.endswith('.json'):
                date_str = f[6:-5]
                history_file = os.path.join(history_path, f)

                with open(history_file, 'r', encoding='utf-8') as hf:
                    snapshot = json.load(hf)

                # Calculate returns for this date's picks
                changes = []
                for pick in snapshot['picks']:
                    ticker = pick['ticker']
                    price_at_rec = pick.get('price_at_analysis', 0)
                    row = latest_df[latest_df['Ticker'] == ticker]
                    if not row.empty and price_at_rec > 0:
                        current = float(row['Close'].iloc[0])
                        change = ((current / price_at_rec) - 1) * 100
                        changes.append(change)

                if changes:
                    # SPY benchmark
                    spy_df = df[df['Ticker'] == 'SPY'].copy()
                    spy_df = spy_df[spy_df['Date'] >= date_str].sort_values('Date')
                    spy_return = 0.0
                    if len(spy_df) >= 2:
                        spy_return = ((spy_df['Close'].iloc[-1] / spy_df['Close'].iloc[0]) - 1) * 100

                    avg_return = float(np.mean(changes))
                    summaries.append({
                        'date': date_str,
                        'avg_return': round(avg_return, 2),
                        'spy_return': round(spy_return, 2),
                        'alpha': round(avg_return - spy_return, 2),
                        'win_rate': round(len([c for c in changes if c > 0]) / len(changes) * 100, 1),
                        'num_picks': len(changes)
                    })

        # Sort by date
        summaries = sorted(summaries, key=lambda x: x['date'], reverse=True)

        # Calculate overall stats
        if summaries:
            overall = {
                'total_recommendations': sum(s['num_picks'] for s in summaries),
                'avg_return_all': round(np.mean([s['avg_return'] for s in summaries]), 2),
                'avg_alpha': round(np.mean([s['alpha'] for s in summaries]), 2),
                'avg_win_rate': round(np.mean([s['win_rate'] for s in summaries]), 1),
                'num_dates': len(summaries)
            }
        else:
            overall = {}

        return jsonify({
            'overall': overall,
            'by_date': summaries
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@us_bp.route('/cumulative-performance')
def get_us_cumulative_performance():
    """누적 성과 — 스냅샷 우선, 실시간 폴백"""
    import time as _time
    snap_path = os.path.join(_OUTPUT_DIR, 'cumulative_perf_snapshot.json')
    try:
        if os.path.exists(snap_path):
            age = _time.time() - os.path.getmtime(snap_path)
            if age < 300:  # 5분 TTL
                with open(snap_path, 'r', encoding='utf-8') as f:
                    return jsonify(json.load(f))
    except Exception:
        pass
    return _compute_cumulative_performance_live()


def _compute_cumulative_performance_live():
    """누적 성과 실시간 계산 + 스냅샷 저장"""
    try:
        import numpy as np

        history_path = os.path.join(_HISTORY_DIR)
        csv_path = os.path.join(_DATA_DIR, 'us_daily_prices.csv')

        if not os.path.exists(history_path) or not os.path.exists(csv_path):
            return jsonify({'error': 'Data not found'}), 404

        # Load price data - get latest price per ticker
        df = pd.read_csv(csv_path)
        latest_date = df['Date'].max()
        latest_df = df[df['Date'] == latest_date]

        # Get all snapshot dates first to determine SPY fetch range
        snap_files = sorted([f for f in os.listdir(history_path)
                             if f.startswith('picks_') and f.endswith('.json')])
        if not snap_files:
            return jsonify({'error': 'No history snapshots found'}), 404

        earliest_date = snap_files[0][6:-5]  # picks_YYYY-MM-DD.json

        # Fetch SPY via yfinance for benchmark
        spy_hist = yf.Ticker('SPY').history(start=earliest_date, auto_adjust=True)
        spy_prices = {}
        if not spy_hist.empty:
            for idx, row in spy_hist.iterrows():
                spy_prices[idx.strftime('%Y-%m-%d')] = float(row['Close'])
        spy_latest = spy_prices.get(max(spy_prices)) if spy_prices else None

        all_picks = []
        by_date = []

        for f in snap_files:
            date_str = f[6:-5]
            with open(os.path.join(history_path, f), 'r', encoding='utf-8') as hf:
                snapshot = json.load(hf)

            date_picks = []
            for pick in snapshot.get('picks', []):
                ticker = pick.get('ticker', '')
                entry_price = pick.get('price_at_analysis', 0)
                row = latest_df[latest_df['Ticker'] == ticker]
                if row.empty or entry_price <= 0:
                    continue
                current_price = safe_float(row['Close'].iloc[0])
                return_pct = ((current_price / entry_price) - 1) * 100

                all_picks.append({
                    'ticker': ticker,
                    'name': pick.get('name', ticker),
                    'rec_date': date_str,
                    'entry_price': round(entry_price, 2),
                    'current_price': round(current_price, 2),
                    'return_pct': round(return_pct, 2),
                    'final_score': safe_float(pick.get('final_score', 0)),
                    'recommendation': pick.get('ai_recommendation', ''),
                })
                date_picks.append(return_pct)

            if not date_picks:
                continue

            # SPY benchmark: find nearest SPY close on or after snapshot date
            spy_return = 0.0
            if spy_prices and spy_latest is not None:
                spy_dates_after = [d for d in sorted(spy_prices) if d >= date_str]
                if spy_dates_after:
                    spy_entry = spy_prices[spy_dates_after[0]]
                    spy_return = ((spy_latest / spy_entry) - 1) * 100

            avg_ret = float(np.mean(date_picks))
            win_count = len([r for r in date_picks if r > 0])
            by_date.append({
                'date': date_str,
                'avg_return': round(avg_ret, 2),
                'spy_return': round(spy_return, 2),
                'alpha': round(avg_ret - spy_return, 2),
                'win_rate': round(win_count / len(date_picks) * 100, 1),
                'num_picks': len(date_picks),
            })

        # Chart data (sorted chronologically)
        chart_data = sorted(
            [{'date': d['date'], 'avg_return': d['avg_return'], 'spy_return': d['spy_return']} for d in by_date],
            key=lambda x: x['date']
        )

        # Sort by_date reverse chronological
        by_date.sort(key=lambda x: x['date'], reverse=True)

        # Summary
        if all_picks:
            returns = [p['return_pct'] for p in all_picks]
            tickers = list({p['ticker'] for p in all_picks})
            alphas = [d['alpha'] for d in by_date]
            summary = {
                'total_picks': len(all_picks),
                'unique_tickers': len(tickers),
                'win_rate': round(len([r for r in returns if r > 0]) / len(returns) * 100, 1),
                'avg_return': round(float(np.mean(returns)), 2),
                'avg_alpha': round(float(np.mean(alphas)), 2) if alphas else 0,
                'max_gain': round(max(returns), 2),
                'max_loss': round(min(returns), 2),
                'best_ticker': max(all_picks, key=lambda p: p['return_pct'])['ticker'],
                'worst_ticker': min(all_picks, key=lambda p: p['return_pct'])['ticker'],
                'num_snapshots': len(by_date),
            }
        else:
            summary = {}

        result = {
            'summary': summary,
            'chart_data': chart_data,
            'picks': all_picks,
            'by_date': by_date,
        }
        # 스냅샷 저장
        try:
            snap_path = os.path.join(_OUTPUT_DIR, 'cumulative_perf_snapshot.json')
            with open(snap_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@us_bp.route('/macro-analysis')
def get_us_macro_analysis():
    """US Macro Analysis"""
    try:
        lang = request.args.get('lang', 'ko')
        
        # Try language-specific file first
        if lang == 'en':
            analysis_path = os.path.join(_OUTPUT_DIR, 'macro_analysis_en.json')
            if not os.path.exists(analysis_path):
                analysis_path = os.path.join(_OUTPUT_DIR, 'macro_analysis.json')
        else:
            analysis_path = os.path.join(_OUTPUT_DIR, 'macro_analysis.json')
        
        if os.path.exists(analysis_path):
            with open(analysis_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify(data)
        return jsonify({'analysis': None})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@us_bp.route('/heatmap-data')
def get_us_sector_heatmap():
    """섹터 히트맵"""
    try:
        heatmap_path = os.path.join(_OUTPUT_DIR, 'sector_heatmap.json')
        if os.path.exists(heatmap_path):
            with open(heatmap_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # sector_groups → series 변환 (프론트엔드 SectorSeries[] 호환)
            if 'sector_groups' in data and 'series' not in data:
                series = []
                for sector_name, stocks in data['sector_groups'].items():
                    items = []
                    for s in stocks:
                        items.append({
                            'x': s.get('ticker', s.get('symbol', '')),
                            'y': s.get('weight', s.get('market_cap', 0)),
                            'price': s.get('price', 0),
                            'change': s.get('change_pct', s.get('change', 0)),
                            'color': ''
                        })
                    series.append({'name': sector_name, 'data': items})
                data['series'] = series

            return jsonify(data)
        return jsonify({'sectors': [], 'series': []})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@us_bp.route('/options-flow')
def get_us_options_flow():
    """옵션 플로우"""
    try:
        flow_path = os.path.join(_OUTPUT_DIR, 'options_flow.json')
        if os.path.exists(flow_path):
            with open(flow_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify(data)
        return jsonify({'flows': []})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@us_bp.route('/sec-filings')
def get_us_sec_filings():
    """SEC 파일링"""
    try:
        filings_path = os.path.join(_OUTPUT_DIR, 'sec_filings.json')
        if os.path.exists(filings_path):
            with open(filings_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify(data)
        return jsonify({'filings': []})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@us_bp.route('/earnings-transcripts')
def get_us_earnings_transcripts():
    """어닝 트랜스크립트"""
    try:
        transcripts_path = os.path.join(_OUTPUT_DIR, 'earnings_transcripts.json')
        if os.path.exists(transcripts_path):
            with open(transcripts_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify(data)
        return jsonify({'transcripts': []})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@us_bp.route('/ai-summary/<ticker>')
def get_us_ai_summary(ticker):
    """AI 종목 요약"""
    try:
        lang = request.args.get('lang', 'ko')
        
        summary_path = os.path.join(_OUTPUT_DIR, 'ai_summaries.json')
        if os.path.exists(summary_path):
            with open(summary_path, 'r', encoding='utf-8') as f:
                summaries = json.load(f)
            
            if ticker in summaries:
                data = summaries[ticker]
                summary = data.get('summary_ko' if lang == 'ko' else 'summary_en', '')
                return jsonify({
                    'ticker': ticker,
                    'summary': summary,
                    'generated_at': data.get('generated_at', '')
                })
        
        return jsonify({'ticker': ticker, 'summary': None})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@us_bp.route('/calendar')
def get_us_calendar():
    """경제 캘린더 (v2 - structured output from economic_calendar.py)"""
    try:
        calendar_path = os.path.join(_OUTPUT_DIR, 'weekly_calendar.json')
        if not os.path.exists(calendar_path):
            return jsonify({'events': []})

        with open(calendar_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        return jsonify({'events': data.get('events', [])})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@us_bp.route('/technical-indicators/<ticker>')
def get_technical_indicators(ticker):
    """기술적 지표"""
    try:
        from app.utils.helpers import calculate_rsi
        
        stock = yf.Ticker(ticker)
        hist = stock.history(period='1y')
        
        if hist.empty:
            return jsonify({'error': 'No data found'}), 404
        
        # Calculate indicators
        hist['MA20'] = hist['Close'].rolling(20).mean()
        hist['MA50'] = hist['Close'].rolling(50).mean()
        hist['MA200'] = hist['Close'].rolling(200).mean()
        hist['RSI'] = calculate_rsi(hist['Close'])
        
        last = hist.iloc[-1]
        
        return jsonify({
            'ticker': ticker,
            'price': round(last['Close'], 2),
            'ma20': round(last['MA20'], 2) if not pd.isna(last['MA20']) else None,
            'ma50': round(last['MA50'], 2) if not pd.isna(last['MA50']) else None,
            'ma200': round(last['MA200'], 2) if not pd.isna(last['MA200']) else None,
            'rsi': round(last['RSI'], 2) if not pd.isna(last['RSI']) else None,
            'volume': int(last['Volume'])
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@us_bp.route('/super-performance')
def us_super_performance():
    """슈퍼 퍼포먼스 종목 — CSV 우선, final_top10_report.json 폴백"""
    try:
        # 1) CSV 소스 (기존)
        csv_path = os.path.join(_OUTPUT_DIR, 'super_performance_picks.csv')
        if os.path.exists(csv_path):
            df = pd.read_csv(csv_path)
            stocks = []
            for _, row in df.iterrows():
                stocks.append({
                    'ticker': str(row.get('ticker', '')),
                    'name': str(row.get('name', '')),
                    'sector': str(row.get('sector', '')),
                    'price': safe_float(row.get('price')),
                    'change_pct': 0,
                    'vcp_score': safe_float(row.get('vcp_score')),
                    'rs_rating': safe_float(row.get('rs_rating')),
                    'fund_score': safe_float(row.get('fund_score')),
                    'stage': str(row.get('setup_phase', '')),
                    'volume_ratio': 0,
                    'pivot_tightness': str(row.get('pivot_tightness', '')),
                    'vol_dry_up': str(row.get('vol_dry_up', '')),
                    'contractions': int(safe_float(row.get('contractions'))),
                    'base_depth': str(row.get('base_depth', '')),
                    'eps_growth': str(row.get('eps_growth', '')),
                    'breakout': str(row.get('breakout', '')),
                    'pivot_price': safe_float(row.get('pivot_price')),
                    'score': safe_float(row.get('score')),
                })
            return jsonify({'stocks': stocks})

        # 2) JSON 폴백 — final_top10_report.json (Smart Money Top Picks)
        json_path = os.path.join(_OUTPUT_DIR, 'final_top10_report.json')
        if os.path.exists(json_path):
            with open(json_path, 'r', encoding='utf-8') as f:
                report = json.load(f)
            picks = report.get('top_picks', [])
            stocks = []
            for p in picks:
                stocks.append({
                    'ticker': p.get('ticker', ''),
                    'name': p.get('name', ''),
                    'sector': '',
                    'price': safe_float(p.get('current_price')),
                    'change_pct': 0,
                    'vcp_score': 0,
                    'rs_rating': 0,
                    'fund_score': safe_float(p.get('quant_score')),
                    'stage': p.get('sd_stage', ''),
                    'volume_ratio': 0,
                    'pivot_tightness': '',
                    'vol_dry_up': '',
                    'contractions': 0,
                    'base_depth': '',
                    'eps_growth': '',
                    'breakout': '',
                    'pivot_price': 0,
                    'score': safe_float(p.get('final_score')),
                    'ai_recommendation': p.get('ai_recommendation', ''),
                    'ai_bonus': safe_float(p.get('ai_bonus')),
                    'target_upside': safe_float(p.get('target_upside')),
                    'inst_pct': safe_float(p.get('inst_pct')),
                    'rsi': safe_float(p.get('rsi')),
                    'grade': p.get('grade', ''),
                    'rank': p.get('rank', 0),
                })
            return jsonify({'stocks': stocks, 'source': 'final_top10_report',
                            'generated_at': report.get('generated_at', ''),
                            'total_analyzed': report.get('total_analyzed', 0)})

        return jsonify({'stocks': []})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@us_bp.route('/portfolio-performance')
def us_portfolio_performance():
    """포트폴리오 성과"""
    try:
        perf_path = os.path.join(_DATA_DIR, 'portfolio_performance.json')
        if os.path.exists(perf_path):
            with open(perf_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify(data)
        return jsonify({'performance': []})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@us_bp.route('/market-gate')
def us_market_gate():
    """US Market Gate 상태 - Enhanced with RSI, MACD, Volume"""
    try:
        try:
            from us_market.market_gate import run_us_market_gate
            result = run_us_market_gate()
            
            # Convert dataclass to dict
            sectors_data = []
            for s in result.sectors[:5]:  # Top 5 sectors
                sectors_data.append({
                    'name': s.name,
                    'ticker': s.ticker,
                    'score': s.score,
                    'signal': s.signal,
                    'change_1d': round(s.change_1d, 2),
                    'rsi': round(s.rsi, 1),
                    'rs_vs_spy': round(s.rs_vs_spy, 2)
                })
            
            return jsonify({
                'gate': result.gate,  # GREEN/YELLOW/RED
                'score': result.score,
                'status': 'RISK_ON' if result.score >= 70 else ('RISK_OFF' if result.score < 40 else 'NEUTRAL'),
                'reasons': result.reasons,
                'sectors': sectors_data,
                'metrics': result.metrics
            })
        except ImportError as e:
            # Fallback to simple logic
            print(f"Enhanced market_gate not available: {e}")
            spy = yf.Ticker('SPY')
            hist = spy.history(period='200d')

            if len(hist) < 200:
                return jsonify({'status': 'NEUTRAL', 'score': 50, 'gate': 'YELLOW', 'metrics': {'rsi': None, 'vix': None, 'spy_price': None}})

            price = float(hist['Close'].iloc[-1])
            ma200 = float(hist['Close'].rolling(200).mean().iloc[-1])
            ma50 = float(hist['Close'].rolling(50).mean().iloc[-1])

            # Calculate RSI for fallback
            delta = hist['Close'].diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss.replace(0, 0.0001)
            rsi = float((100 - (100 / (1 + rs))).iloc[-1])

            # Get VIX
            try:
                vix_data = yf.Ticker('^VIX').history(period='5d')
                vix = float(vix_data['Close'].iloc[-1]) if not vix_data.empty else None
            except Exception:
                vix = None

            status = "NEUTRAL"
            score = 50
            gate = "YELLOW"

            if price > ma200 and ma50 > ma200:
                status = "RISK_ON"
                score = 80
                gate = "GREEN"
            elif price < ma200 and ma50 < ma200:
                status = "RISK_OFF"
                score = 20
                gate = "RED"

            return jsonify({
                'gate': gate,
                'status': status,
                'score': score,
                'price': price,
                'ma200': ma200,
                'symbol': 'SPY',
                'reasons': [f'SPY: ${price:.2f} vs 200MA: ${ma200:.2f}'],
                'metrics': {'rsi': round(rsi, 1), 'vix': round(vix, 1) if vix else None, 'spy_price': price}
            })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e), 'gate': 'YELLOW', 'score': 50, 'metrics': {'rsi': None, 'vix': None, 'spy_price': None}}), 500
@us_bp.route('/data-status')
def get_us_update_status():
    """US Market Data Update Status"""
    try:
        status_data = {
            'timestamp': datetime.now().isoformat(),
            'files': [],
            'log': ''
        }

        # 1. Check Data Files
        base_dir = _US_MARKET_DIR
        files_to_check = [
            {'name': 'US Daily Prices', 'path': os.path.join(base_dir, 'data', 'us_daily_prices.csv')},
            {'name': 'Smart Money Picks', 'path': os.path.join(base_dir, 'output', 'smart_money_picks_v2.csv')},
            {'name': 'Macro Analysis (AI)', 'path': os.path.join(base_dir, 'output', 'macro_analysis.json')},
            {'name': 'AI Summaries', 'path': os.path.join(base_dir, 'output', 'ai_summaries.json')},
            {'name': 'Sector Heatmap', 'path': os.path.join(base_dir, 'output', 'sector_heatmap.json')},
            {'name': 'Options Flow', 'path': os.path.join(base_dir, 'output', 'options_flow.json')},
            {'name': 'Update Log', 'path': os.path.join(base_dir, 'output', 'update_log.txt')}
        ]
        
        for f in files_to_check:
            path = f['path']
            if os.path.exists(path):
                stats = os.stat(path)
                mtime = datetime.fromtimestamp(stats.st_mtime)
                size_mb = stats.st_size / (1024 * 1024)
                
                status_data['files'].append({
                    'name': f['name'],
                    'path': os.path.basename(f['path']),
                    'last_updated': mtime.strftime('%Y-%m-%d %H:%M:%S'),
                    'size': f"{size_mb:.2f} MB",
                    'status': 'OK'
                })
            else:
                status_data['files'].append({
                    'name': f['name'],
                    'last_updated': '-',
                    'size': '-',
                    'status': 'MISSING'
                })
                
        # 2. Read Update Log
        log_path = os.path.join(base_dir, 'output', 'update_log.txt')
        if os.path.exists(log_path):
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                # Read last 100 lines
                lines = f.readlines()
                status_data['log'] = ''.join(lines[-100:])
        else:
            status_data['log'] = 'Log file not found.'

        return jsonify(status_data)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@us_bp.route('/news-analysis')
def get_us_news_analysis():
    """Perplexity 뉴스 분석 결과 — ai_summaries.json으로 보강"""
    try:
        news_path = os.path.join(_OUTPUT_DIR, 'news_analysis.json')
        data = []
        if os.path.exists(news_path):
            with open(news_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

        # ai_summaries.json에서 뉴스 데이터 보강
        summaries_path = os.path.join(_OUTPUT_DIR, 'ai_summaries.json')
        if os.path.exists(summaries_path):
            with open(summaries_path, 'r', encoding='utf-8') as f:
                summaries = json.load(f)

            for ticker, summary in summaries.items():
                if not isinstance(summary, dict):
                    continue
                # 기존 데이터 보강
                for item in data:
                    if item.get('ticker') == ticker:
                        if item.get('news_score', 0) == 0 and summary.get('news_score', 0) > 0:
                            item['news_score'] = summary.get('news_score', 0)
                            item['reason'] = summary.get('summary', item.get('reason', ''))
                            item['sentiment'] = summary.get('sentiment', item.get('sentiment', 'neutral'))
                            if summary.get('catalysts'):
                                item['catalysts'] = summary.get('catalysts', [])
                        break

        return jsonify({'analysis': data})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@us_bp.route('/institutional')
def get_us_institutional():
    """13F 기관 보유 분석"""
    try:
        csv_path = os.path.join(_OUTPUT_DIR, 'us_13f_holdings.csv')
        if os.path.exists(csv_path):
            df = pd.read_csv(csv_path)
            holdings = df.to_dict('records')
            return jsonify({'holdings': holdings})
        return jsonify({'holdings': []})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@us_bp.route('/insider-trading')
def get_us_insider_trading():
    """내부자 거래 현황"""
    try:
        json_path = os.path.join(_OUTPUT_DIR, 'insider_trading.json')
        if os.path.exists(json_path):
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify({'transactions': data.get('transactions', [])})
        return jsonify({'transactions': []})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@us_bp.route('/sector-rotation')
def get_us_sector_rotation():
    """섹터 로테이션 분석"""
    try:
        rotation_path = os.path.join(_OUTPUT_DIR, 'sector_rotation.json')
        if os.path.exists(rotation_path):
            with open(rotation_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify(data)
        return jsonify({'rotation_signals': {}, 'performance_matrix': {}})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@us_bp.route('/risk-alerts')
def get_us_risk_alerts():
    """리스크 알림"""
    try:
        alerts_path = os.path.join(_OUTPUT_DIR, 'risk_alerts.json')
        if os.path.exists(alerts_path):
            with open(alerts_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify(data)
        return jsonify({'alerts': [], 'portfolio_summary': {}})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@us_bp.route('/earnings-impact')
def get_us_earnings_impact():
    """어닝 임팩트 분석 — earnings_impact + earnings_analysis + earnings_transcripts 병합"""
    try:
        # 1) earnings_impact.json — sector_profiles
        data = {'sector_profiles': {}, 'upcoming_earnings': [], 'details': {}}
        impact_path = os.path.join(_OUTPUT_DIR, 'earnings_impact.json')
        if os.path.exists(impact_path):
            with open(impact_path, 'r', encoding='utf-8') as f:
                impact = json.load(f)
            data['sector_profiles'] = impact.get('sector_profiles', {})
            data['timestamp'] = impact.get('timestamp', '')

        # 2) earnings_analysis.json — upcoming_earnings + details (per-ticker)
        analysis_path = os.path.join(_OUTPUT_DIR, 'earnings_analysis.json')
        if not os.path.exists(analysis_path):
            analysis_path = os.path.join(_PREVIEW_DIR, 'earnings_analysis.json')
        if os.path.exists(analysis_path):
            with open(analysis_path, 'r', encoding='utf-8') as f:
                analysis = json.load(f)
            # upcoming_earnings from analysis (has actual entries)
            upcoming = analysis.get('upcoming_earnings', [])
            details = analysis.get('details', {})
            data['details'] = details

            # Enrich upcoming with detail info
            from datetime import datetime, date
            today = date.today()
            enriched = []
            for item in upcoming:
                ticker = item.get('ticker', '')
                detail = details.get(ticker, {})
                earn_date = item.get('date', detail.get('next_earnings_date', ''))
                # Recalculate days_left from today
                days_left = item.get('days_left', 0)
                try:
                    ed = datetime.strptime(earn_date[:10], '%Y-%m-%d').date()
                    days_left = max(0, (ed - today).days)
                except Exception:
                    pass
                enriched.append({
                    'ticker': ticker,
                    'date': earn_date,
                    'days_left': days_left,
                    'revenue_growth': detail.get('revenue_growth', 0),
                    'avg_surprise_pct': detail.get('avg_surprise_pct', 0),
                    'surprises': detail.get('surprises', []),
                })

            # Also add tickers from details that have earnings within 30 days
            seen = {e['ticker'] for e in enriched}
            for ticker, detail in details.items():
                if ticker in seen:
                    continue
                earn_date = detail.get('next_earnings_date', '')
                if not earn_date:
                    continue
                try:
                    ed = datetime.strptime(earn_date[:10], '%Y-%m-%d').date()
                    days_left = (ed - today).days
                    if 0 <= days_left <= 30:
                        enriched.append({
                            'ticker': ticker,
                            'date': earn_date,
                            'days_left': days_left,
                            'revenue_growth': detail.get('revenue_growth', 0),
                            'avg_surprise_pct': detail.get('avg_surprise_pct', 0),
                            'surprises': detail.get('surprises', []),
                        })
                except Exception:
                    pass

            # Sort by days_left
            enriched.sort(key=lambda x: x.get('days_left', 999))
            data['upcoming_earnings'] = enriched

        # 3) earnings_transcripts.json — transcript metadata
        transcripts_path = os.path.join(_OUTPUT_DIR, 'earnings_transcripts.json')
        if os.path.exists(transcripts_path):
            with open(transcripts_path, 'r', encoding='utf-8') as f:
                transcripts = json.load(f)
            data['transcript_metadata'] = transcripts.get('metadata', {})

        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@us_bp.route('/market-regime')
def get_us_market_regime():
    """마켓 레짐 감지 결과 + adaptive config"""
    try:
        config_path = os.path.join(_OUTPUT_DIR, 'regime_config.json')
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify(data)
        return jsonify({'regime': 'neutral', 'confidence': 0, 'signals': {}})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@us_bp.route('/index-prediction')
def get_us_index_prediction():
    """지수 방향 예측"""
    try:
        prediction_path = os.path.join(_OUTPUT_DIR, 'index_prediction.json')
        if os.path.exists(prediction_path):
            with open(prediction_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify(data)
        return jsonify({'predictions': {}, 'model_info': {}})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@us_bp.route('/market-briefing')
def get_us_market_briefing():
    """Perplexity 기반 시황 분석 — briefing.json + market_briefing.json 병합"""
    try:
        json_path = os.path.join(_OUTPUT_DIR, 'market_briefing.json')
        data = {}
        if os.path.exists(json_path):
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

        # ai_analysis.content가 비어있으면 briefing.json에서 보충
        ai = data.get('ai_analysis', {})
        if not ai.get('content'):
            briefing_path = os.path.join(_OUTPUT_DIR, 'briefing.json')
            if not os.path.exists(briefing_path):
                briefing_path = os.path.join(_PREVIEW_DIR, 'briefing.json')
            if os.path.exists(briefing_path):
                with open(briefing_path, 'r', encoding='utf-8') as f:
                    briefing = json.load(f)
                data['ai_analysis'] = {
                    'content': briefing.get('content', ''),
                    'citations': briefing.get('citations', [])
                }

        # vix 데이터 보충 (market_data.json)
        if not data.get('vix', {}).get('value'):
            md_path = os.path.join(_OUTPUT_DIR, 'market_data.json')
            if not os.path.exists(md_path):
                md_path = os.path.join(_PREVIEW_DIR, 'market_data.json')
            if os.path.exists(md_path):
                with open(md_path, 'r', encoding='utf-8') as f:
                    md = json.load(f)
                vol = md.get('volatility', {})
                vix_data = vol.get('^VIX', {})
                val = vix_data.get('current', 0)
                change = vix_data.get('change_pct', 0)
                level = 'Low' if val < 15 else ('High' if val > 25 else 'Neutral')
                color = '#4CAF50' if val < 15 else ('#F44336' if val > 25 else '#FFC107')
                data['vix'] = {'value': val, 'change': change, 'level': level, 'color': color}

        # fear_greed color 보충
        fg = data.get('fear_greed', {})
        if fg and 'color' not in fg:
            score = fg.get('score', 50)
            fg['color'] = 'green' if score >= 60 else ('red' if score <= 40 else 'yellow')
            data['fear_greed'] = fg

        # smart_money.top_picks 키 매핑
        sm = data.get('smart_money', {})
        if sm and 'top_picks' not in sm:
            tp_path = os.path.join(_OUTPUT_DIR, 'top_picks.json')
            if not os.path.exists(tp_path):
                tp_path = os.path.join(_PREVIEW_DIR, 'top_picks.json')
            if os.path.exists(tp_path):
                with open(tp_path, 'r', encoding='utf-8') as f:
                    tp = json.load(f)
                picks = tp.get('top_picks', tp.get('picks', []))
                for p in picks:
                    if 'composite_score' in p and 'final_score' not in p:
                        p['final_score'] = p.pop('composite_score')
                    if 'signal' in p and 'ai_recommendation' not in p:
                        p['ai_recommendation'] = p.pop('signal')
                sm['top_picks'] = {'picks': picks}
                data['smart_money'] = sm

        if not data:
            return jsonify({'ai_analysis': {'content': '', 'citations': []}, 'vix': {}, 'fear_greed': {}})
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@us_bp.route('/backtest')
def get_us_backtest():
    """백테스트 결과"""
    try:
        backtest_path = os.path.join(_OUTPUT_DIR, 'backtest_results.json')
        if os.path.exists(backtest_path):
            with open(backtest_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify(data)
        return jsonify({'returns': {}, 'benchmarks': {}})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@us_bp.route('/top-picks-report')
def get_us_top_picks_report():
    """최종 Top 10 AI 리포트"""
    try:
        report_path = os.path.join(_OUTPUT_DIR, 'final_top10_report.json')
        if os.path.exists(report_path):
            with open(report_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify(data)
        return jsonify({'top_picks': [], 'generated_at': '', 'total_analyzed': 0})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@us_bp.route('/track-record')
def get_us_track_record():
    """Smart Money Top Picks 트랙 레코드"""
    try:
        report_path = os.path.join(_OUTPUT_DIR, 'performance_report.json')
        if os.path.exists(report_path):
            with open(report_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify(data)
        return jsonify({'summary': {}, 'snapshots': [], 'picks': [], 'by_grade': {}, 'by_sector': {}})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@us_bp.route('/decision-signal')
def get_us_decision_signal():
    """통합 투자 신호 — 스냅샷 우선, 실시간 폴백"""
    # 스냅샷 파일 확인 (5분 이내면 즉시 반환)
    snap_path = os.path.join(_OUTPUT_DIR, 'decision_signal_snapshot.json')
    try:
        if os.path.exists(snap_path):
            import time as _time
            age = _time.time() - os.path.getmtime(snap_path)
            if age < 300:  # 5분 TTL
                with open(snap_path, 'r', encoding='utf-8') as f:
                    return jsonify(json.load(f))
    except Exception:
        pass

    return _compute_decision_signal_live()


def _compute_decision_signal_live():
    """decision-signal 실시간 계산 + 스냅샷 저장"""
    try:
        score = 50  # Base score
        components = {}

        # 1. Market Gate
        gate_score = 50
        try:
            from us_market.market_gate import run_us_market_gate
            gate_result = run_us_market_gate()
            gate_score = gate_result.score
        except Exception:
            pass
        gate_contribution = round((gate_score - 50) / 50 * 15, 1)
        score += gate_contribution
        components['market_gate'] = {'score': gate_score, 'contribution': gate_contribution}

        # 2. Regime
        regime_str = 'neutral'
        regime_contribution = 0
        regime_path = os.path.join(_OUTPUT_DIR, 'regime_config.json')
        try:
            if os.path.exists(regime_path):
                with open(regime_path, 'r', encoding='utf-8') as f:
                    regime_data = json.load(f)
                regime_str = regime_data.get('regime', 'neutral')
                regime_map = {'risk_on': 15, 'neutral': 0, 'risk_off': -15, 'crisis': -25}
                regime_contribution = regime_map.get(regime_str, 0)
                score += regime_contribution
        except Exception:
            pass
        components['regime'] = {'regime': regime_str, 'contribution': regime_contribution}

        # 3. Index Prediction (SPY bullish probability)
        spy_bullish = 50.0
        pred_contribution = 0
        pred_path = os.path.join(_OUTPUT_DIR, 'index_prediction.json')
        try:
            if os.path.exists(pred_path):
                with open(pred_path, 'r', encoding='utf-8') as f:
                    pred_data = json.load(f)
                spy_pred = pred_data.get('predictions', {}).get('SPY', {})
                spy_bullish = spy_pred.get('bullish_probability', 50)
                if spy_bullish >= 60:
                    pred_contribution = 10
                elif spy_bullish <= 40:
                    pred_contribution = -10
                score += pred_contribution
        except Exception:
            pass
        components['prediction'] = {'spy_bullish': round(spy_bullish, 1), 'contribution': pred_contribution}

        # 4. Risk Level
        risk_level = 'Moderate'
        risk_contribution = 0
        risk_path = os.path.join(_OUTPUT_DIR, 'risk_alerts.json')
        warnings = []
        try:
            if os.path.exists(risk_path):
                with open(risk_path, 'r', encoding='utf-8') as f:
                    risk_data = json.load(f)
                risk_level = risk_data.get('portfolio_summary', {}).get('risk_level', 'Moderate')
                risk_map = {'Low': 5, 'Moderate': 0, 'High': -10, 'Critical': -20}
                risk_contribution = risk_map.get(risk_level, 0)
                score += risk_contribution
                for alert in risk_data.get('alerts', []):
                    if alert.get('severity') in ('critical', 'warning'):
                        warnings.append(alert.get('message', ''))
        except Exception:
            pass
        components['risk'] = {'level': risk_level, 'contribution': risk_contribution}

        # 5. Sector Phase
        phase = 'Unknown'
        phase_contribution = 0
        rotation_path = os.path.join(_OUTPUT_DIR, 'sector_rotation.json')
        try:
            if os.path.exists(rotation_path):
                with open(rotation_path, 'r', encoding='utf-8') as f:
                    rotation_data = json.load(f)
                phase = rotation_data.get('rotation_signals', {}).get('current_phase', 'Unknown')
                phase_map = {'Early Cycle': 10, 'Mid Cycle': 5, 'Late Cycle': -5, 'Recession': -15}
                phase_contribution = phase_map.get(phase, 0)
                score += phase_contribution
        except Exception:
            pass
        components['sector_phase'] = {'phase': phase, 'contribution': phase_contribution}

        # Clamp score
        score = max(0, min(100, round(score)))

        # Map to action
        if score >= 75:
            action = 'STRONG_BUY'
        elif score >= 60:
            action = 'BUY'
        elif score >= 40:
            action = 'NEUTRAL'
        elif score >= 25:
            action = 'CAUTIOUS'
        else:
            action = 'DEFENSIVE'

        # Timing signal
        timing = 'NOW' if gate_score >= 70 else ('WAIT' if gate_score < 40 else 'SELECTIVE')

        # Top 5 picks from final report
        top_picks = []
        report_path = os.path.join(_OUTPUT_DIR, 'final_top10_report.json')
        try:
            if os.path.exists(report_path):
                with open(report_path, 'r', encoding='utf-8') as f:
                    report = json.load(f)
                for pick in report.get('top_picks', [])[:5]:
                    top_picks.append({
                        'ticker': pick.get('ticker', ''),
                        'name': pick.get('name', ''),
                        'final_score': pick.get('final_score', 0),
                        'grade': pick.get('grade', ''),
                        'ai_recommendation': pick.get('ai_recommendation', ''),
                        'target_upside': pick.get('target_upside', 0),
                    })
        except Exception:
            pass

        result = {
            'action': action,
            'score': score,
            'components': components,
            'top_picks': top_picks,
            'timing': timing,
            'warnings': warnings[:5],
        }
        # 스냅샷 저장
        try:
            snap_path = os.path.join(_OUTPUT_DIR, 'decision_signal_snapshot.json')
            with open(snap_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        return jsonify(result)
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e), 'action': 'NEUTRAL', 'score': 50}), 500


@us_bp.route('/smart-money/<ticker>/detail')
def get_smart_money_detail(ticker):
    """Smart Money 종목 상세 정보 - 차트, 기술적 분석, AI 분석 통합"""
    try:
        import numpy as np
        from app.utils.helpers import calculate_rsi

        lang = request.args.get('lang', 'ko')
        result = {
            'ticker': ticker.upper(),
            'name': '',
            'sector': get_sector(ticker),
            'price': 0,
            'change_pct': 0,
            'chart': [],
            'technicals': {},
            'smart_money': {},
            'ai_analysis': {},
            'why_buy': []
        }

        # 1. Load Smart Money CSV data
        csv_path = os.path.join(_OUTPUT_DIR, 'smart_money_picks_v2.csv')
        if os.path.exists(csv_path):
            df = pd.read_csv(csv_path)
            row = df[df['ticker'] == ticker.upper()]
            if not row.empty:
                r = row.iloc[0]
                result['name'] = safe_str(r.get('name'), ticker)
                result['smart_money'] = {
                    'composite_score': safe_float(r.get('composite_score')),
                    'swing_score': safe_float(r.get('swing_score')),
                    'trend_score': safe_float(r.get('trend_score')),
                    'grade': safe_str(r.get('grade')),
                    'strategy_type': safe_str(r.get('strategy_type')),
                    'setup_type': safe_str(r.get('setup_type')),
                    'sd_stage': safe_str(r.get('sd_stage')),
                    'sd_score': safe_float(r.get('sd_score')),
                    'inst_score': safe_float(r.get('inst_score')),
                    'inst_pct': safe_float(r.get('inst_pct')),
                    'insider': safe_str(r.get('insider')),
                    'tech_score': safe_float(r.get('tech_score')),
                    'fund_score': safe_float(r.get('fund_score')),
                    'pe': safe_float(r.get('pe')) if not pd.isna(r.get('pe')) else None,
                    'revenue_growth': safe_float(r.get('revenue_growth')) if not pd.isna(r.get('revenue_growth')) else None,
                    'target_upside': safe_float(r.get('target_upside')),
                    'rs_score': safe_float(r.get('rs_score')),
                    'rs_vs_spy_20d': safe_float(r.get('rs_vs_spy_20d')),
                    'recommendation': safe_str(r.get('recommendation')),
                    'next_earnings': safe_str(r.get('next_earnings')),
                    'days_to_earnings': int(float(r.get('days_to_earnings'))) if r.get('days_to_earnings') is not None and not pd.isna(r.get('days_to_earnings')) else None
                }

        # 1b. Fallback: Load from super_performance_picks.csv if not in smart money
        if not result['smart_money']:
            vcp_path = os.path.join(_OUTPUT_DIR, 'super_performance_picks.csv')
            if os.path.exists(vcp_path):
                vcp_df = pd.read_csv(vcp_path)
                vcp_row = vcp_df[vcp_df['ticker'] == ticker.upper()]
                if not vcp_row.empty:
                    v = vcp_row.iloc[0]
                    result['name'] = safe_str(v.get('name'), ticker)
                    result['sector'] = safe_str(v.get('sector'), result.get('sector', ''))

                    # Parse eps_growth "99%" -> 99.0
                    rev_growth = None
                    eps_raw = v.get('eps_growth')
                    if eps_raw is not None and not pd.isna(eps_raw):
                        try:
                            rev_growth = float(str(eps_raw).replace('%', ''))
                        except (ValueError, TypeError):
                            pass

                    rs_rating = safe_float(v.get('rs_rating'))
                    result['smart_money'] = {
                        'composite_score': safe_float(v.get('score')),
                        'swing_score': safe_float(v.get('vcp_score')),
                        'trend_score': None,
                        'grade': None,
                        'strategy_type': 'VCP',
                        'setup_type': 'Breakout' if str(v.get('breakout', '')).strip().lower() == 'yes' else 'Building',
                        'sd_stage': safe_str(v.get('setup_phase')),
                        'sd_score': None,
                        'inst_score': None,
                        'inst_pct': None,
                        'insider': None,
                        'tech_score': None,
                        'fund_score': safe_float(v.get('fund_score')),
                        'pe': None,
                        'revenue_growth': rev_growth,
                        'target_upside': None,
                        'rs_score': rs_rating,
                        'rs_vs_spy_20d': rs_rating,
                        'recommendation': None,
                        'next_earnings': None,
                        'days_to_earnings': None
                    }
                    # Store VCP-specific fields for Why Buy generation
                    result['_vcp'] = {
                        'vcp_score': safe_float(v.get('vcp_score')),
                        'rs_rating': rs_rating,
                        'breakout': str(v.get('breakout', '')).strip(),
                        'vol_dry_up': str(v.get('vol_dry_up', '')).strip(),
                        'contractions': safe_float(v.get('contractions')),
                        'pivot_tightness': safe_str(v.get('pivot_tightness')),
                        'base_depth': safe_str(v.get('base_depth')),
                        'pivot_price': safe_float(v.get('pivot_price')),
                    }

        # 2. Get Chart Data (6 months daily)
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period='6mo', interval='1d')

            if not hist.empty:
                # Current price & change
                result['price'] = round(float(hist['Close'].iloc[-1]), 2)
                if len(hist) >= 2:
                    prev = float(hist['Close'].iloc[-2])
                    result['change_pct'] = round(((result['price'] - prev) / prev) * 100, 2)

                # Calculate technical indicators
                hist['MA20'] = hist['Close'].rolling(20).mean()
                hist['MA50'] = hist['Close'].rolling(50).mean()
                hist['MA200'] = hist['Close'].rolling(200).mean()
                hist['RSI'] = calculate_rsi(hist['Close'])

                # MACD
                ema12 = hist['Close'].ewm(span=12, adjust=False).mean()
                ema26 = hist['Close'].ewm(span=26, adjust=False).mean()
                hist['MACD'] = ema12 - ema26
                hist['MACD_Signal'] = hist['MACD'].ewm(span=9, adjust=False).mean()
                hist['MACD_Hist'] = hist['MACD'] - hist['MACD_Signal']

                # Bollinger Bands
                hist['BB_Mid'] = hist['Close'].rolling(20).mean()
                bb_std = hist['Close'].rolling(20).std()
                hist['BB_Upper'] = hist['BB_Mid'] + (bb_std * 2)
                hist['BB_Lower'] = hist['BB_Mid'] - (bb_std * 2)

                # Build chart data
                for date, row in hist.iterrows():
                    # Skip rows with NaN in essential OHLC data
                    if pd.isna(row['Open']) or pd.isna(row['Close']):
                        continue
                    result['chart'].append({
                        'date': date.strftime('%Y-%m-%d'),
                        'open': round(float(row['Open']), 2),
                        'high': round(float(row['High']), 2),
                        'low': round(float(row['Low']), 2),
                        'close': round(float(row['Close']), 2),
                        'volume': int(row['Volume']) if not pd.isna(row['Volume']) else 0,
                        'ma20': round(float(row['MA20']), 2) if not pd.isna(row['MA20']) else None,
                        'ma50': round(float(row['MA50']), 2) if not pd.isna(row['MA50']) else None,
                        'rsi': round(float(row['RSI']), 2) if not pd.isna(row['RSI']) else None,
                        'macd': round(float(row['MACD']), 4) if not pd.isna(row['MACD']) else None,
                        'macd_signal': round(float(row['MACD_Signal']), 4) if not pd.isna(row['MACD_Signal']) else None,
                        'macd_hist': round(float(row['MACD_Hist']), 4) if not pd.isna(row['MACD_Hist']) else None
                    })

                # Latest technicals
                last = hist.iloc[-1]
                avg_vol = hist['Volume'].tail(20).mean()
                result['technicals'] = {
                    'price': result['price'],
                    'ma20': round(float(last['MA20']), 2) if not pd.isna(last['MA20']) else None,
                    'ma50': round(float(last['MA50']), 2) if not pd.isna(last['MA50']) else None,
                    'ma200': round(float(last['MA200']), 2) if not pd.isna(last['MA200']) else None,
                    'rsi': round(float(last['RSI']), 2) if not pd.isna(last['RSI']) else None,
                    'macd': round(float(last['MACD']), 4) if not pd.isna(last['MACD']) else None,
                    'macd_signal': round(float(last['MACD_Signal']), 4) if not pd.isna(last['MACD_Signal']) else None,
                    'macd_hist': round(float(last['MACD_Hist']), 4) if not pd.isna(last['MACD_Hist']) else None,
                    'bb_upper': round(float(last['BB_Upper']), 2) if not pd.isna(last['BB_Upper']) else None,
                    'bb_lower': round(float(last['BB_Lower']), 2) if not pd.isna(last['BB_Lower']) else None,
                    'volume': int(last['Volume']) if not pd.isna(last['Volume']) else 0,
                    'avg_volume_20d': int(avg_vol) if not pd.isna(avg_vol) else 0
                }
        except Exception as e:
            print(f"Chart data error for {ticker}: {e}")

        # 3. AI Summary
        summary_path = os.path.join(_OUTPUT_DIR, 'ai_summaries.json')
        if os.path.exists(summary_path):
            with open(summary_path, 'r', encoding='utf-8') as f:
                summaries = json.load(f)
            if ticker.upper() in summaries:
                ai_data = summaries[ticker.upper()]
                result['ai_analysis'] = {
                    'summary': ai_data.get('summary_ko' if lang == 'ko' else 'summary_en', ''),
                    'generated_at': ai_data.get('generated_at', '')
                }

        # 4. Generate "Why Buy" reasons
        sm = result['smart_money']
        tech = result['technicals']
        why_buy = []

        # Score-based reasons
        if (sm.get('composite_score') or 0) >= 70:
            why_buy.append({
                'type': 'score',
                'icon': 'chart-line',
                'title': '높은 종합 점수',
                'desc': f"Composite Score {sm['composite_score']:.1f}점으로 상위 종목"
            })

        if sm.get('sd_stage') in ['Accumulation', 'Strong Accumulation']:
            why_buy.append({
                'type': 'accumulation',
                'icon': 'building-columns',
                'title': '기관 매집 단계',
                'desc': f"Supply/Demand Stage: {sm['sd_stage']} - 스마트머니 유입 신호"
            })

        if (sm.get('inst_pct') or 0) >= 5:
            why_buy.append({
                'type': 'institutional',
                'icon': 'landmark',
                'title': '기관 보유 증가',
                'desc': f"최근 분기 기관 보유 비중 {sm['inst_pct']:.1f}% 증가"
            })

        if (sm.get('target_upside') or 0) >= 10:
            why_buy.append({
                'type': 'target',
                'icon': 'bullseye',
                'title': '애널리스트 목표가 상향 여력',
                'desc': f"컨센서스 목표가 대비 {sm['target_upside']:.1f}% 상승 여력"
            })

        if (sm.get('rs_vs_spy_20d') or 0) >= 5:
            why_buy.append({
                'type': 'momentum',
                'icon': 'rocket',
                'title': '시장 대비 강한 모멘텀',
                'desc': f"최근 20일 SPY 대비 {sm['rs_vs_spy_20d']:.1f}% 아웃퍼폼"
            })

        # Technical reasons
        if tech.get('rsi') and 30 <= tech['rsi'] <= 70:
            if tech['rsi'] <= 50:
                why_buy.append({
                    'type': 'technical',
                    'icon': 'arrow-trend-up',
                    'title': '과매도 해소 구간',
                    'desc': f"RSI {tech['rsi']:.1f} - 반등 타이밍 포착"
                })

        if tech.get('ma20') and tech.get('ma50') and tech.get('price'):
            if tech['price'] > tech['ma20'] > tech['ma50']:
                why_buy.append({
                    'type': 'technical',
                    'icon': 'chart-area',
                    'title': '이평선 정배열',
                    'desc': f"현재가 > MA20 > MA50 - 상승 추세 확인"
                })

        if tech.get('macd') and tech.get('macd_signal'):
            if tech['macd'] > tech['macd_signal'] and tech.get('macd_hist', 0) > 0:
                why_buy.append({
                    'type': 'technical',
                    'icon': 'wave-square',
                    'title': 'MACD 골든크로스',
                    'desc': 'MACD가 시그널선 상향 돌파 - 매수 신호'
                })

        if sm.get('insider') and 'buy' in str(sm.get('insider', '')).lower():
            why_buy.append({
                'type': 'insider',
                'icon': 'user-tie',
                'title': '내부자 매수',
                'desc': '최근 내부자(임원)의 자사주 매수 발생'
            })

        days_to_earnings = sm.get('days_to_earnings')
        if days_to_earnings is not None and not pd.isna(days_to_earnings):
            try:
                days = int(days_to_earnings)
                if 7 <= days <= 30:
                    why_buy.append({
                        'type': 'earnings',
                        'icon': 'calendar-check',
                        'title': '실적 발표 임박',
                        'desc': f"{days}일 후 실적 발표 - 기대감 선반영 가능"
                    })
            except (ValueError, TypeError):
                pass

        # VCP-specific reasons
        vcp = result.get('_vcp')
        if vcp:
            if (vcp.get('vcp_score') or 0) >= 50:
                why_buy.append({
                    'type': 'vcp',
                    'icon': 'compress',
                    'title': 'VCP 패턴 강도',
                    'desc': f"VCP 패턴 강도 {vcp['vcp_score']:.0f}점 - 변동성 수축 패턴 확인"
                })
            if str(vcp.get('breakout', '')).lower() == 'yes':
                why_buy.append({
                    'type': 'vcp',
                    'icon': 'arrow-up-right-dots',
                    'title': '브레이크아웃 확인',
                    'desc': '브레이크아웃 확인 - 피봇 포인트 돌파'
                })
            if (vcp.get('rs_rating') or 0) >= 80:
                why_buy.append({
                    'type': 'momentum',
                    'icon': 'ranking-star',
                    'title': '강한 상대강도',
                    'desc': f"시장 대비 상대강도 {vcp['rs_rating']:.0f}등급 - 리더 종목"
                })
            if str(vcp.get('vol_dry_up', '')).lower() == 'yes':
                why_buy.append({
                    'type': 'vcp',
                    'icon': 'droplet-slash',
                    'title': '거래량 수축',
                    'desc': '거래량 수축 확인 - 매도 압력 소진'
                })
            if (vcp.get('contractions') or 0) >= 3:
                why_buy.append({
                    'type': 'vcp',
                    'icon': 'layer-group',
                    'title': '다중 수축 패턴',
                    'desc': f"다중 수축 패턴({int(vcp['contractions'])}회) - 변동성 감소 확인"
                })
            # Remove internal _vcp before returning
            del result['_vcp']

        result['why_buy'] = why_buy[:6]  # Max 6 reasons

        return jsonify(result)

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ── VCP Enhanced ──────────────────────────────────────────────────────────────

@us_bp.route('/vcp-enhanced/dates')
def get_us_vcp_dates():
    """US VCP 히스토리 날짜 목록."""
    try:
        import re
        dates = []
        data_dir = os.path.join(BASE_DIR, 'data')
        pattern = re.compile(r'vcp_us_(\d{8})\.json')
        for fname in os.listdir(data_dir):
            m = pattern.match(fname)
            if m:
                d = m.group(1)
                dates.append(f"{d[:4]}-{d[4:6]}-{d[6:]}")
        dates.sort(reverse=True)
        return jsonify(dates)
    except Exception:
        return jsonify([]), 200


@us_bp.route('/vcp-enhanced')
def get_us_vcp_enhanced():
    """US VCP 통합 분석 — 캐시 파일 기반 반환."""
    try:
        cached_path = os.path.join(BASE_DIR, 'data', 'vcp_us_latest.json')
        if os.path.exists(cached_path):
            with open(cached_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            resp = jsonify(data)
            resp.headers['Cache-Control'] = 'public, max-age=300'
            return resp
        return jsonify({"metadata": {"market": "US"}, "summary": {}, "signals": []}), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

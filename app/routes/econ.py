# app/routes/econ.py
"""Economy Indicators API Routes"""

import os
import json
import traceback
from datetime import datetime
from flask import Blueprint, jsonify, request

econ_bp = Blueprint('econ', __name__)

# Lazy init for econ_indicators module
_econ_modules_loaded = False
_us_collector = None
_bok_collector = None
_sector_tracker = None
_ai_summarizer = None


def _init_econ_modules():
    """Lazy load economic indicator modules"""
    global _econ_modules_loaded, _us_collector, _bok_collector
    global _sector_tracker, _ai_summarizer

    if _econ_modules_loaded:
        return True

    try:
        from econ_indicators.bok_sector_tracker import SectorScoreTracker
        _sector_tracker = SectorScoreTracker()

        try:
            from econ_indicators.data_collector import USDataCollector
            from econ_indicators.bok_collector import BOKDataCollector
            _us_collector = USDataCollector()
            _bok_collector = BOKDataCollector()
        except Exception as e:
            print(f"[WARN] Optional collectors not loaded: {e}")

        try:
            from econ_indicators.ai_summarizer import EconAISummarizer
            _ai_summarizer = EconAISummarizer()
        except Exception as e:
            print(f"[WARN] AI Summarizer not loaded: {e}")

        _econ_modules_loaded = True
        print("[OK] Economic indicators modules loaded")
        return True
    except Exception as e:
        print(f"[WARN] econ_indicators module not available: {e}")
        return False


def _safe_float(val, default=0):
    if val is None:
        return default
    try:
        import math
        f = float(val)
        return default if math.isnan(f) else f
    except (ValueError, TypeError):
        return default


@econ_bp.route('/overview')
def get_econ_overview():
    """Key Economic Indicators via yfinance proxies"""
    try:
        import yfinance as yf

        indicators = {
            '^TNX': {'name': 'US 10Y Treasury', 'unit': '%'},
            '^FVX': {'name': 'US 5Y Treasury', 'unit': '%'},
            '^IRX': {'name': 'US 3M T-Bill', 'unit': '%'},
            'DX-Y.NYB': {'name': 'Dollar Index', 'unit': ''},
            'GC=F': {'name': 'Gold', 'unit': '$'},
            'CL=F': {'name': 'Crude Oil (WTI)', 'unit': '$'},
            'SI=F': {'name': 'Silver', 'unit': '$'},
            'NG=F': {'name': 'Natural Gas', 'unit': '$'},
            'KRW=X': {'name': 'USD/KRW', 'unit': 'KRW'},
            'JPY=X': {'name': 'USD/JPY', 'unit': 'JPY'},
            'EURUSD=X': {'name': 'EUR/USD', 'unit': '$'},
        }

        result = []
        for ticker, info in indicators.items():
            try:
                stock = yf.Ticker(ticker)
                hist = stock.history(period='5d')
                if not hist.empty and len(hist) >= 2:
                    price = _safe_float(hist['Close'].iloc[-1])
                    prev = _safe_float(hist['Close'].iloc[-2])
                    change = price - prev
                    change_pct = (change / prev) * 100 if prev else 0
                    result.append({
                        'ticker': ticker,
                        'name': info['name'],
                        'unit': info['unit'],
                        'value': round(price, 4),
                        'change': round(change, 4),
                        'change_pct': round(change_pct, 2),
                    })
            except Exception as e:
                print(f"Error fetching {ticker}: {e}")

        return jsonify({
            'indicators': result,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e), 'indicators': []}), 500


@econ_bp.route('/yield-curve')
def get_yield_curve():
    """US Treasury Yield Curve"""
    try:
        import yfinance as yf

        tenors = {
            '^IRX': {'name': '3M', 'months': 3},
            '^FVX': {'name': '5Y', 'months': 60},
            '^TNX': {'name': '10Y', 'months': 120},
            '^TYX': {'name': '30Y', 'months': 360},
        }

        yields_data = []
        for ticker, info in tenors.items():
            try:
                t = yf.Ticker(ticker)
                hist = t.history(period='5d')
                if not hist.empty:
                    val = _safe_float(hist['Close'].iloc[-1])
                    yields_data.append({
                        'tenor': info['name'],
                        'months': info['months'],
                        'yield_pct': round(val, 3),
                    })
            except Exception:
                pass

        yields_data.sort(key=lambda x: x['months'])

        # Inversion check
        inverted = False
        if len(yields_data) >= 2:
            short = next((y for y in yields_data if y['months'] <= 3), None)
            long = next((y for y in yields_data if y['months'] >= 120), None)
            if short and long and short['yield_pct'] > long['yield_pct']:
                inverted = True

        return jsonify({
            'yields': yields_data,
            'inverted': inverted,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e), 'yields': [], 'inverted': False}), 500


@econ_bp.route('/fear-greed')
def get_fear_greed():
    """Market Fear & Greed proxy (VIX-based)"""
    try:
        import yfinance as yf

        vix = yf.Ticker('^VIX')
        hist = vix.history(period='30d')

        if hist.empty:
            return jsonify({'error': 'No VIX data'}), 500

        vix_val = _safe_float(hist['Close'].iloc[-1])
        vix_prev = _safe_float(hist['Close'].iloc[-2]) if len(hist) >= 2 else vix_val
        vix_change = vix_val - vix_prev
        vix_30d_avg = _safe_float(hist['Close'].mean())

        # VIX to Fear-Greed mapping
        if vix_val > 35:
            sentiment = 'EXTREME_FEAR'
            score = max(0, 25 - (vix_val - 35))
        elif vix_val > 25:
            sentiment = 'FEAR'
            score = 25 + (35 - vix_val)
        elif vix_val > 18:
            sentiment = 'NEUTRAL'
            score = 35 + (25 - vix_val) * 2
        elif vix_val > 12:
            sentiment = 'GREED'
            score = 60 + (18 - vix_val) * 3
        else:
            sentiment = 'EXTREME_GREED'
            score = min(100, 80 + (12 - vix_val) * 5)

        return jsonify({
            'vix': round(vix_val, 2),
            'vix_change': round(vix_change, 2),
            'vix_30d_avg': round(vix_30d_avg, 2),
            'score': round(score),
            'sentiment': sentiment,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e), 'sentiment': 'NEUTRAL', 'score': 50}), 500


# ============================================================
# Advanced Economy Endpoints (econ_indicators module)
# ============================================================

@econ_bp.route('/us/indicators')
def get_econ_us_indicators():
    """US Economic Indicators (FRED/yfinance)"""
    if not _init_econ_modules() or _us_collector is None:
        return jsonify({'error': 'US data collector not available', 'indicators': []}), 500
    try:
        category = request.args.get('category', 'all')
        data = _us_collector.get_all_indicators(category)
        return jsonify({'indicators': data, 'timestamp': datetime.now().isoformat()})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@econ_bp.route('/us/chart-data/<indicator>')
def get_econ_us_chart_data(indicator):
    """US Indicator Chart Data"""
    if not _init_econ_modules() or _us_collector is None:
        return jsonify({'error': 'US data collector not available'}), 500
    try:
        period = request.args.get('period', '5y')
        transform = request.args.get('transform', 'raw')
        data = _us_collector.get_chart_data(indicator, period, transform)
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@econ_bp.route('/kr/indicators')
def get_econ_kr_indicators():
    """Korean Economic Indicators (BOK ECOS)"""
    if not _init_econ_modules() or _bok_collector is None:
        return jsonify({'error': 'BOK collector not available', 'indicators': []}), 500
    try:
        data = _bok_collector.get_all_kr_indicators()
        return jsonify({'indicators': data, 'timestamp': datetime.now().isoformat()})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@econ_bp.route('/kr/chart-data/<indicator>')
def get_econ_kr_chart_data(indicator):
    """Korean Indicator Chart Data"""
    if not _init_econ_modules() or _bok_collector is None:
        return jsonify({'error': 'BOK collector not available'}), 500
    try:
        period = request.args.get('period', '5y')
        data = _bok_collector.get_indicator_history(indicator, period)
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@econ_bp.route('/kr/sectors')
def get_econ_kr_sectors():
    """Korean Sector Scores"""
    if not _init_econ_modules() or _sector_tracker is None:
        return jsonify({'error': 'Sector tracker not available'}), 500
    try:
        data = _sector_tracker.get_dashboard_data()
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@econ_bp.route('/kr/sectors/history')
def get_econ_kr_sectors_history():
    """Korean Sector History"""
    if not _init_econ_modules() or _sector_tracker is None:
        return jsonify({'error': 'Sector tracker not available'}), 500
    try:
        data = _sector_tracker.get_historical_scores()
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@econ_bp.route('/kr/sectors/score', methods=['POST'])
def update_econ_kr_sector_score():
    """Update Korean Sector Score"""
    if not _init_econ_modules() or _sector_tracker is None:
        return jsonify({'error': 'Sector tracker not available'}), 500
    try:
        data = request.get_json() or {}
        result = _sector_tracker.update_scores(data)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@econ_bp.route('/summary', methods=['POST'])
def get_econ_summary():
    """AI Economy Summary"""
    if not _init_econ_modules() or _ai_summarizer is None:
        return jsonify({'error': 'AI Summarizer not available'}), 500
    try:
        data = request.get_json() or {}
        indicators = data.get('indicators', [])
        summary = _ai_summarizer.generate_summary(indicators)
        return jsonify({'summary': summary})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@econ_bp.route('/forecast/saved')
def get_econ_forecast_saved():
    """Saved Forecast Data"""
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        forecast_path = os.path.join(base_dir, 'data', 'ai_forecast.json')
        if os.path.exists(forecast_path):
            with open(forecast_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify(data)
        return jsonify({'forecasts': []})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

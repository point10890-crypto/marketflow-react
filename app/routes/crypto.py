# app/routes/crypto.py
"""Crypto Market API Routes — 통합 버전

기존 overview/dominance/chart + crypto-analytics 전체 기능:
- VCP Signals, Market Gate, Briefing, Prediction, Risk, Lead-Lag
- Signal Analysis (GPT), Gate History, Prediction History
"""

import os
import sys
import json
import math
import threading
import subprocess
import traceback
from datetime import datetime
from flask import Blueprint, jsonify, request, send_from_directory
from app.auth.decorators import pro_required

crypto_bp = Blueprint('crypto', __name__)

# 절대경로 고정
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DATA_DIR = os.path.join(_BASE_DIR, 'data')

# crypto_market 모듈 경로 (crypto-analytics 프로젝트)
CRYPTO_ANALYTICS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'crypto-analytics'
)
CRYPTO_MARKET_DIR = os.path.join(CRYPTO_ANALYTICS_DIR, 'crypto_market')
CRYPTO_OUTPUT_DIR = os.path.join(CRYPTO_MARKET_DIR, 'output')


def _safe_float(val, default=0):
    if val is None:
        return default
    try:
        f = float(val)
        return default if math.isnan(f) else f
    except (ValueError, TypeError):
        return default


def _load_json(path):
    """JSON 파일 로드 헬퍼"""
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return None


# ═══════════════════════════════════════════════════════
# 기존 API (호환성 유지)
# ═══════════════════════════════════════════════════════

def _fetch_crypto_overview_live():
    """yfinance로 실시간 크립토 데이터 수집 + JSON 스냅샷 저장"""
    import yfinance as yf
    cryptos = {
        'BTC-USD': 'Bitcoin', 'ETH-USD': 'Ethereum', 'BNB-USD': 'BNB',
        'SOL-USD': 'Solana', 'XRP-USD': 'XRP', 'ADA-USD': 'Cardano',
        'DOGE-USD': 'Dogecoin', 'AVAX-USD': 'Avalanche',
        'DOT-USD': 'Polkadot', 'MATIC-USD': 'Polygon',
        'LINK-USD': 'Chainlink', 'UNI-USD': 'Uniswap',
    }
    result = []
    for ticker, name in cryptos.items():
        try:
            coin = yf.Ticker(ticker)
            hist = coin.history(period='5d')
            if not hist.empty and len(hist) >= 2:
                price = _safe_float(hist['Close'].iloc[-1])
                prev = _safe_float(hist['Close'].iloc[-2])
                change = price - prev
                change_pct = (change / prev) * 100 if prev else 0
                vol_24h = _safe_float(hist['Volume'].iloc[-1])
                result.append({
                    'name': name, 'ticker': ticker.replace('-USD', ''),
                    'price': round(price, 2), 'change': round(change, 2),
                    'change_pct': round(change_pct, 2), 'volume_24h': int(vol_24h),
                })
        except Exception as e:
            print(f"Error fetching {ticker}: {e}")
    data = {'cryptos': result, 'timestamp': datetime.now().isoformat()}
    # 스냅샷 저장
    try:
        snap_path = os.path.join(CRYPTO_OUTPUT_DIR, 'overview_snapshot.json')
        os.makedirs(CRYPTO_OUTPUT_DIR, exist_ok=True)
        with open(snap_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return data


@crypto_bp.route('/overview')
def get_crypto_overview():
    """Top Crypto — 스냅샷 우선, 실시간 폴백"""
    try:
        # 1) 스냅샷 파일 확인 (5분 이내면 즉시 반환)
        snap_path = os.path.join(CRYPTO_OUTPUT_DIR, 'overview_snapshot.json')
        if os.path.exists(snap_path):
            import time as _time
            age = _time.time() - os.path.getmtime(snap_path)
            if age < 300:  # 5분 TTL
                with open(snap_path, 'r', encoding='utf-8') as f:
                    return jsonify(json.load(f))

        # 2) 실시간 수집 (스냅샷 없거나 만료)
        return jsonify(_fetch_crypto_overview_live())
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e), 'cryptos': []}), 500


@crypto_bp.route('/dominance')
def get_crypto_dominance():
    """BTC Dominance & Market Sentiment — 스냅샷 우선, 실시간 폴백"""
    import time as _time
    snap_path = os.path.join(_DATA_DIR, 'crypto_dominance_cache.json')
    try:
        if os.path.exists(snap_path):
            age = _time.time() - os.path.getmtime(snap_path)
            if age < 300:  # 5분 TTL
                with open(snap_path, 'r', encoding='utf-8') as f:
                    return jsonify(json.load(f))
    except Exception:
        pass

    return _compute_crypto_dominance_live()


def _compute_crypto_dominance_live():
    """Crypto dominance 실시간 계산 + 스냅샷 저장"""
    try:
        import yfinance as yf
        btc = yf.Ticker('BTC-USD')
        eth = yf.Ticker('ETH-USD')
        btc_hist = btc.history(period='30d')
        eth_hist = eth.history(period='30d')

        if btc_hist.empty:
            return jsonify({'error': 'No BTC data'}), 500

        btc_price = _safe_float(btc_hist['Close'].iloc[-1])
        eth_price = _safe_float(eth_hist['Close'].iloc[-1]) if not eth_hist.empty else 0
        btc_30d_start = _safe_float(btc_hist['Close'].iloc[0])
        btc_30d_change = ((btc_price / btc_30d_start) - 1) * 100 if btc_30d_start else 0

        delta = btc_hist['Close'].diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        rsi = _safe_float(100 - (100 / (1 + rs)).iloc[-1], 50)

        if rsi > 70: sentiment = 'EXTREME_GREED'
        elif rsi > 60: sentiment = 'GREED'
        elif rsi > 40: sentiment = 'NEUTRAL'
        elif rsi > 30: sentiment = 'FEAR'
        else: sentiment = 'EXTREME_FEAR'

        result = {
            'btc_price': round(btc_price, 2), 'eth_price': round(eth_price, 2),
            'btc_rsi': round(rsi, 1), 'btc_30d_change': round(btc_30d_change, 2),
            'sentiment': sentiment, 'timestamp': datetime.now().isoformat()
        }

        # 스냅샷 저장
        try:
            os.makedirs(os.path.dirname(snap_path := os.path.join(_DATA_DIR, 'crypto_dominance_cache.json')), exist_ok=True)
            with open(snap_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

        return jsonify(result)
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e), 'sentiment': 'NEUTRAL'}), 500


@crypto_bp.route('/chart/<ticker>')
def get_crypto_chart(ticker):
    """Crypto Price Chart Data"""
    try:
        import yfinance as yf
        period = request.args.get('period', '3mo')
        symbol = f"{ticker.upper()}-USD"
        coin = yf.Ticker(symbol)
        hist = coin.history(period=period)
        if hist.empty:
            return jsonify({'error': f'No data for {ticker}'}), 404
        chart_data = [{
            'date': date.strftime('%Y-%m-%d'),
            'open': round(_safe_float(row['Open']), 2),
            'high': round(_safe_float(row['High']), 2),
            'low': round(_safe_float(row['Low']), 2),
            'close': round(_safe_float(row['Close']), 2),
            'volume': int(_safe_float(row['Volume'])),
        } for date, row in hist.iterrows()]
        return jsonify({'ticker': ticker.upper(), 'data': chart_data, 'period': period})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ═══════════════════════════════════════════════════════
# Market Gate
# ═══════════════════════════════════════════════════════

@crypto_bp.route('/market-gate')
def crypto_market_gate():
    """Crypto Market Gate 상태 (JSON 캐시 → fallback 라이브)"""
    gate_path = os.path.join(CRYPTO_OUTPUT_DIR, 'market_gate.json')
    data = _load_json(gate_path)
    if data:
        return jsonify(data)

    try:
        import yfinance as yf
        btc = yf.Ticker('BTC-USD')
        hist = btc.history(period='200d')
        if len(hist) < 200:
            return jsonify({'status': 'NEUTRAL', 'gate': 'YELLOW', 'score': 50})
        price = float(hist['Close'].iloc[-1])
        ma200 = float(hist['Close'].rolling(200).mean().iloc[-1])
        ma50 = float(hist['Close'].rolling(50).mean().iloc[-1])
        if price > ma200 and price > ma50:
            gate, status, score = 'GREEN', 'RISK_ON', 75
        elif price < ma200 and price < ma50:
            gate, status, score = 'RED', 'RISK_OFF', 25
        else:
            gate, status, score = 'YELLOW', 'NEUTRAL', 50
        return jsonify({
            'gate': gate, 'status': status, 'score': score,
            'price': price, 'ma200': ma200,
            'generated_at': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@crypto_bp.route('/gate-history')
def crypto_gate_history():
    """Gate 히스토리"""
    path = os.path.join(CRYPTO_OUTPUT_DIR, 'gate_history.json')
    data = _load_json(path)
    return jsonify({'history': data or []})


# ═══════════════════════════════════════════════════════
# VCP Signals
# ═══════════════════════════════════════════════════════

@crypto_bp.route('/vcp-signals')
def crypto_vcp_signals():
    """Crypto VCP 시그널 조회"""
    try:
        if CRYPTO_MARKET_DIR not in sys.path:
            sys.path.insert(0, CRYPTO_MARKET_DIR)
        limit = request.args.get('limit', 50, type=int)
        db_path = os.path.join(CRYPTO_MARKET_DIR, 'signals.sqlite3')

        if not os.path.exists(db_path):
            return jsonify({'signals': [], 'count': 0, 'error': 'No signals database found'})

        # Import storage directly (avoids config path conflict with run_scan)
        from storage import make_engine, get_recent_signals
        engine = make_engine(db_path)
        signals = get_recent_signals(engine, limit)
        return jsonify({'signals': signals, 'count': len(signals), 'generated_at': datetime.now().isoformat()})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e), 'signals': []}), 500


# ═══════════════════════════════════════════════════════
# Briefing (실시간 생성 지원)
# ═══════════════════════════════════════════════════════

@crypto_bp.route('/briefing')
def crypto_briefing():
    """Crypto 일일 브리핑 (캐시 → 실시간 생성)"""
    path = os.path.join(CRYPTO_OUTPUT_DIR, 'crypto_briefing.json')
    data = _load_json(path)
    if data:
        return jsonify(data)

    try:
        briefing = _generate_live_briefing()
        os.makedirs(CRYPTO_OUTPUT_DIR, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(briefing, f, ensure_ascii=False, indent=2)
        return jsonify(briefing)
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


def _generate_live_briefing():
    """실시간 브리핑 데이터 생성"""
    import yfinance as yf
    import requests as req

    briefing = {
        'timestamp': datetime.now().isoformat(),
        'market_summary': {
            'total_market_cap': 0, 'total_market_cap_change_24h': 0,
            'btc_dominance': 0, 'btc_dominance_change_24h': 0,
            'total_volume_24h': 0, 'active_cryptocurrencies': 0,
        },
        'major_coins': {},
        'top_movers': {'gainers': [], 'losers': []},
        'fear_greed': {'score': 50, 'level': 'Neutral', 'previous': 50, 'change': 0},
        'funding_rates': {},
        'macro_correlations': {'btc_pairs': {}},
        'market_gate': None,
        'sentiment_summary': {'overall': 'Neutral', 'factors': []},
    }

    # 1. CoinGecko Global
    try:
        r = req.get('https://api.coingecko.com/api/v3/global', timeout=5)
        if r.status_code == 200:
            g = r.json().get('data', {})
            briefing['market_summary'] = {
                'total_market_cap': g.get('total_market_cap', {}).get('usd', 0),
                'total_market_cap_change_24h': g.get('market_cap_change_percentage_24h_usd', 0),
                'btc_dominance': g.get('market_cap_percentage', {}).get('btc', 0),
                'btc_dominance_change_24h': 0,
                'total_volume_24h': g.get('total_volume', {}).get('usd', 0),
                'active_cryptocurrencies': g.get('active_cryptocurrencies', 0),
            }
    except Exception:
        pass

    # 2. Major Coins
    try:
        r = req.get('https://api.coingecko.com/api/v3/coins/markets', params={
            'vs_currency': 'usd', 'ids': 'bitcoin,ethereum,solana,binancecoin,ripple',
            'order': 'market_cap_desc', 'sparkline': 'false',
            'price_change_percentage': '24h,7d'
        }, timeout=5)
        if r.status_code == 200:
            for coin in r.json():
                sym = coin['symbol'].upper()
                briefing['major_coins'][sym] = {
                    'price': coin.get('current_price', 0),
                    'change_24h': coin.get('price_change_percentage_24h', 0) or 0,
                    'change_7d': coin.get('price_change_percentage_7d_in_currency', 0) or 0,
                    'volume_24h': coin.get('total_volume', 0),
                    'market_cap': coin.get('market_cap', 0),
                }
    except Exception:
        pass

    # 3. Top Movers
    try:
        r = req.get('https://api.coingecko.com/api/v3/coins/markets', params={
            'vs_currency': 'usd', 'order': 'market_cap_desc',
            'per_page': 100, 'page': 1, 'sparkline': 'false',
        }, timeout=5)
        if r.status_code == 200:
            coins = r.json()
            up = sorted([c for c in coins if (c.get('price_change_percentage_24h') or 0) > 0],
                        key=lambda x: x.get('price_change_percentage_24h', 0), reverse=True)
            down = sorted([c for c in coins if (c.get('price_change_percentage_24h') or 0) < 0],
                          key=lambda x: x.get('price_change_percentage_24h', 0))
            briefing['top_movers']['gainers'] = [{'symbol': c['symbol'].upper(), 'name': c['name'],
                'change_24h': c.get('price_change_percentage_24h', 0), 'price': c.get('current_price', 0)
            } for c in up[:5]]
            briefing['top_movers']['losers'] = [{'symbol': c['symbol'].upper(), 'name': c['name'],
                'change_24h': c.get('price_change_percentage_24h', 0), 'price': c.get('current_price', 0)
            } for c in down[:5]]
    except Exception:
        pass

    # 4. Fear & Greed
    try:
        r = req.get('https://api.alternative.me/fng/?limit=2', timeout=5)
        if r.status_code == 200:
            fg = r.json().get('data', [])
            if len(fg) >= 1:
                briefing['fear_greed']['score'] = int(fg[0]['value'])
                briefing['fear_greed']['level'] = fg[0]['value_classification']
            if len(fg) >= 2:
                briefing['fear_greed']['previous'] = int(fg[1]['value'])
                briefing['fear_greed']['change'] = briefing['fear_greed']['score'] - briefing['fear_greed']['previous']
    except Exception:
        pass

    # 5. Funding Rates
    try:
        for pair in ['BTCUSDT', 'ETHUSDT']:
            r = req.get(f'https://fapi.binance.com/fapi/v1/premiumIndex?symbol={pair}', timeout=3)
            if r.status_code == 200:
                d = r.json()
                rate = float(d.get('lastFundingRate', 0))
                ann = rate * 3 * 365 * 100
                label = pair.replace('USDT', '')
                briefing['funding_rates'][label] = {
                    'rate': rate, 'rate_pct': rate * 100,
                    'annualized_pct': round(ann, 1),
                    'sentiment': 'Bullish' if rate > 0.0001 else ('Bearish' if rate < -0.0001 else 'Neutral'),
                }
    except Exception:
        pass

    # 6. Cross-asset correlations
    try:
        tickers = ['BTC-USD', 'SPY', 'GLD', 'DX-Y.NYB']
        labels = ['BTC', 'SPY', 'GLD', 'DXY']
        data = yf.download(tickers, period='90d', progress=False)
        if not data.empty and 'Close' in data.columns:
            closes = data['Close']
            returns = closes.pct_change().dropna()
            if 'BTC-USD' in returns.columns:
                for i, t in enumerate(tickers[1:], 1):
                    if t in returns.columns:
                        corr = returns['BTC-USD'].corr(returns[t])
                        briefing['macro_correlations']['btc_pairs'][labels[i]] = round(corr, 3) if not math.isnan(corr) else 0
    except Exception:
        pass

    # 7. BTC price history (90d)
    try:
        btc = yf.Ticker('BTC-USD')
        hist = btc.history(period='90d')
        if not hist.empty:
            briefing['btc_price_history'] = [{'date': d.strftime('%Y-%m-%d'), 'price': round(float(r['Close']), 2)} for d, r in hist.iterrows()]
    except Exception:
        pass

    # 8. Sentiment
    fg = briefing['fear_greed']['score']
    factors = []
    if fg <= 25: briefing['sentiment_summary']['overall'] = 'Bearish'; factors.append('Extreme Fear')
    elif fg <= 45: briefing['sentiment_summary']['overall'] = 'Bearish'; factors.append('Fear')
    elif fg >= 75: briefing['sentiment_summary']['overall'] = 'Bullish'; factors.append('Extreme Greed')
    elif fg >= 55: briefing['sentiment_summary']['overall'] = 'Bullish'; factors.append('Greed')
    else: factors.append('Neutral Sentiment')
    mc = briefing['market_summary'].get('total_market_cap_change_24h', 0)
    if mc > 2: factors.append('Market Cap Rising')
    elif mc < -2: factors.append('Market Cap Falling')
    briefing['sentiment_summary']['factors'] = factors

    return briefing


# ═══════════════════════════════════════════════════════
# BTC Prediction
# ═══════════════════════════════════════════════════════

@crypto_bp.route('/prediction')
@pro_required
def crypto_prediction():
    """BTC 방향 예측 (Pro only)"""
    path = os.path.join(CRYPTO_OUTPUT_DIR, 'btc_prediction.json')
    data = _load_json(path)
    if data:
        return jsonify(data)
    return jsonify({'error': 'No prediction data. Run crypto_prediction.py first.'}), 404


@crypto_bp.route('/prediction-history')
def crypto_prediction_history():
    """BTC 예측 히스토리"""
    path = os.path.join(CRYPTO_OUTPUT_DIR, 'btc_prediction_history.json')
    data = _load_json(path)
    return jsonify({'history': data or []})


# ═══════════════════════════════════════════════════════
# Risk Analysis
# ═══════════════════════════════════════════════════════

@crypto_bp.route('/risk')
@pro_required
def crypto_risk():
    """Crypto 포트폴리오 리스크 (Pro only)"""
    path = os.path.join(CRYPTO_OUTPUT_DIR, 'crypto_risk.json')
    data = _load_json(path)
    if data:
        return jsonify(data)
    return jsonify({'error': 'No risk data. Run crypto_risk.py first.'}), 404


# ═══════════════════════════════════════════════════════
# Lead-Lag Analysis
# ═══════════════════════════════════════════════════════

@crypto_bp.route('/lead-lag')
@pro_required
def crypto_lead_lag():
    """Lead-Lag 분석 (Pro only)"""
    path = os.path.join(CRYPTO_MARKET_DIR, 'lead_lag', 'results.json')
    data = _load_json(path)
    if data:
        return jsonify(data)
    return jsonify({'lead_lag': [], 'granger': []})


@crypto_bp.route('/lead-lag/charts/<path:filename>')
def serve_lead_lag_chart(filename):
    """Lead-Lag 차트 이미지"""
    charts_dir = os.path.join(CRYPTO_MARKET_DIR, 'lead_lag', 'lead_lag_charts')
    try:
        return send_from_directory(charts_dir, filename)
    except Exception as e:
        return jsonify({'error': str(e)}), 404


@crypto_bp.route('/lead-lag/charts/list')
def list_lead_lag_charts():
    """Lead-Lag 차트 목록"""
    charts_dir = os.path.join(CRYPTO_MARKET_DIR, 'lead_lag', 'lead_lag_charts')
    if not os.path.exists(charts_dir):
        return jsonify({'charts': []})
    files = sorted([f for f in os.listdir(charts_dir) if f.endswith('.png')], reverse=True)
    return jsonify({'charts': files})


# ═══════════════════════════════════════════════════════
# Signal Analysis (GPT)
# ═══════════════════════════════════════════════════════

@crypto_bp.route('/signal-analysis', methods=['POST'])
@pro_required
def crypto_signal_analysis():
    """LLM으로 VCP 시그널 분석 (Pro only)"""
    try:
        from openai import OpenAI
        data = request.json
        if not data or 'symbol' not in data:
            return jsonify({'error': 'symbol required'}), 400

        symbol = data['symbol']
        score = data.get('score', 0)
        pivot_high = data.get('pivot_high', 0)
        vol_ratio = data.get('vol_ratio', 0)
        current_price = data.get('current_price', 0)
        signal_type = data.get('signal_type', 'VCP')
        dist = ((current_price / pivot_high - 1) * 100) if pivot_high > 0 and current_price > 0 else 0

        prompt = f"""암호화폐 VCP 분석. {symbol} / {signal_type} / 점수 {score}/100 / 피봇 ${pivot_high} / 현재 ${current_price} ({dist:+.1f}%) / 거래량 {vol_ratio:.2f}x
1. 패턴 해석 2. 피봇 분석 3. 리스크/리워드 4. 주의사항. 한국어 200자 이내."""

        client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        resp = client.chat.completions.create(
            model='gpt-4o-mini',
            messages=[{'role': 'system', 'content': '암호화폐 기술적 분석 전문가.'}, {'role': 'user', 'content': prompt}],
            max_tokens=600, temperature=0.3,
        )
        return jsonify({'analysis': resp.choices[0].message.content, 'symbol': symbol, 'model': 'gpt-4o-mini'})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ═══════════════════════════════════════════════════════
# Timeline & Monthly Report
# ═══════════════════════════════════════════════════════

@crypto_bp.route('/timeline')
def crypto_timeline():
    """Crypto 타임라인"""
    path = os.path.join(CRYPTO_MARKET_DIR, 'timeline_events.json')
    data = _load_json(path)
    return jsonify(data or {'events': []})


@crypto_bp.route('/monthly-report')
def crypto_monthly_report():
    """월간 리포트"""
    reports_dir = os.path.join(CRYPTO_MARKET_DIR, 'crypto_monthly_reports')
    if not os.path.exists(reports_dir):
        return jsonify({'report': None})
    files = sorted([f for f in os.listdir(reports_dir) if f.endswith('.json')], reverse=True)
    if files:
        data = _load_json(os.path.join(reports_dir, files[0]))
        return jsonify({'report': data})
    return jsonify({'report': None})


# ═══════════════════════════════════════════════════════
# Background Task Runner
# ═══════════════════════════════════════════════════════

_running_tasks: dict = {}
_task_lock = threading.Lock()
_PYTHON_EXE = sys.executable


def _run_subprocess_task(task_id: str, script_path: str, cwd: str | None = None):
    """Run a Python script in a subprocess and track status."""
    with _task_lock:
        _running_tasks[task_id] = {'status': 'running', 'started': datetime.now().isoformat()}
    try:
        result = subprocess.run(
            [_PYTHON_EXE, script_path],
            cwd=cwd or CRYPTO_MARKET_DIR,
            capture_output=True, text=True, timeout=600,
            env={**os.environ, 'PYTHONIOENCODING': 'utf-8'}
        )
        with _task_lock:
            _running_tasks[task_id] = {
                'status': 'completed' if result.returncode == 0 else 'failed',
                'returncode': result.returncode,
                'stdout_tail': (result.stdout or '')[-500:],
                'stderr_tail': (result.stderr or '')[-500:],
                'finished': datetime.now().isoformat(),
            }
    except subprocess.TimeoutExpired:
        with _task_lock:
            _running_tasks[task_id] = {'status': 'timeout', 'finished': datetime.now().isoformat()}
    except Exception as e:
        with _task_lock:
            _running_tasks[task_id] = {'status': 'error', 'error': str(e), 'finished': datetime.now().isoformat()}


# ═══════════════════════════════════════════════════════
# Task Trigger APIs
# ═══════════════════════════════════════════════════════

@crypto_bp.route('/run-scan', methods=['POST'])
def run_scan():
    """VCP 스캔 실행 (게이트가 RED이면 스킵 옵션)"""
    # Check gate
    gate_data = _load_json(os.path.join(CRYPTO_OUTPUT_DIR, 'market_gate.json'))
    if gate_data and gate_data.get('gate') == 'RED':
        force = request.json.get('force', False) if request.is_json else False
        if not force:
            return jsonify({'status': 'skipped', 'reason': 'Market gate is RED. Send force=true to override.'})

    script = os.path.join(CRYPTO_MARKET_DIR, 'run_scan.py')
    if not os.path.exists(script):
        return jsonify({'error': f'Script not found: run_scan.py'}), 404

    task_id = f'scan_{datetime.now().strftime("%H%M%S")}'
    t = threading.Thread(target=_run_subprocess_task, args=(task_id, script), daemon=True)
    t.start()
    return jsonify({'status': 'started', 'task_id': task_id})


@crypto_bp.route('/gate-scan', methods=['POST'])
def gate_scan():
    """Market Gate 스캔 실행 (동기 — 결과 직접 반환)"""
    script = os.path.join(CRYPTO_MARKET_DIR, 'market_gate.py')
    if not os.path.exists(script):
        return jsonify({'error': 'market_gate.py not found'}), 404
    try:
        result = subprocess.run(
            [_PYTHON_EXE, script],
            cwd=CRYPTO_MARKET_DIR,
            capture_output=True, text=True, timeout=120,
            env={**os.environ, 'PYTHONIOENCODING': 'utf-8'}
        )
        # Reload fresh gate data
        gate = _load_json(os.path.join(CRYPTO_OUTPUT_DIR, 'market_gate.json'))
        return jsonify({
            'status': 'completed' if result.returncode == 0 else 'failed',
            'gate': gate,
            'returncode': result.returncode,
        })
    except subprocess.TimeoutExpired:
        return jsonify({'status': 'timeout'}), 504
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@crypto_bp.route('/run-prediction', methods=['POST'])
def run_prediction():
    """BTC 예측 모델 재학습/실행"""
    script = os.path.join(CRYPTO_MARKET_DIR, 'crypto_prediction.py')
    if not os.path.exists(script):
        return jsonify({'error': 'crypto_prediction.py not found'}), 404
    task_id = f'prediction_{datetime.now().strftime("%H%M%S")}'
    t = threading.Thread(target=_run_subprocess_task, args=(task_id, script), daemon=True)
    t.start()
    return jsonify({'status': 'started', 'task_id': task_id})


@crypto_bp.route('/run-risk', methods=['POST'])
def run_risk():
    """리스크 분석 실행"""
    script = os.path.join(CRYPTO_MARKET_DIR, 'crypto_risk.py')
    if not os.path.exists(script):
        return jsonify({'error': 'crypto_risk.py not found'}), 404
    task_id = f'risk_{datetime.now().strftime("%H%M%S")}'
    t = threading.Thread(target=_run_subprocess_task, args=(task_id, script), daemon=True)
    t.start()
    return jsonify({'status': 'started', 'task_id': task_id})


@crypto_bp.route('/run-briefing', methods=['POST'])
def run_briefing():
    """브리핑 재생성"""
    # 기존 캐시 삭제
    cache_path = os.path.join(CRYPTO_OUTPUT_DIR, 'crypto_briefing.json')
    if os.path.exists(cache_path):
        try:
            os.remove(cache_path)
        except Exception:
            pass
    # _generate_live_briefing() 호출하여 새로 생성
    try:
        briefing = _generate_live_briefing()
        return jsonify({'status': 'completed', 'briefing': briefing})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@crypto_bp.route('/run-leadlag', methods=['POST'])
def run_leadlag():
    """Lead-Lag 분석 실행"""
    script = os.path.join(CRYPTO_MARKET_DIR, 'lead_lag', 'lead_lag_analysis.py')
    if not os.path.exists(script):
        return jsonify({'error': 'lead_lag_analysis.py not found'}), 404
    task_id = f'leadlag_{datetime.now().strftime("%H%M%S")}'
    t = threading.Thread(target=_run_subprocess_task, args=(task_id, script, os.path.join(CRYPTO_MARKET_DIR, 'lead_lag')), daemon=True)
    t.start()
    return jsonify({'status': 'started', 'task_id': task_id})


@crypto_bp.route('/task-status')
def task_status():
    """실행 중인 태스크 상태 조회"""
    task_id = request.args.get('task_id')
    with _task_lock:
        if task_id:
            info = _running_tasks.get(task_id)
            if not info:
                return jsonify({'error': 'Task not found'}), 404
            return jsonify({'task_id': task_id, **info})
        return jsonify({'tasks': dict(_running_tasks)})


# ═══════════════════════════════════════════════════════
# Data Status & Backtest APIs
# ═══════════════════════════════════════════════════════

@crypto_bp.route('/data-status')
def crypto_data_status():
    """crypto output 파일 상태 반환"""
    files_to_check = {
        'market_gate.json': 'Market Gate',
        'gate_history.json': 'Gate History',
        'crypto_briefing.json': 'Briefing',
        'btc_prediction.json': 'BTC Prediction',
        'btc_prediction_history.json': 'Prediction History',
        'crypto_risk.json': 'Risk Analysis',
        'backtest_result.json': 'Backtest Result',
    }
    result = []
    now = datetime.now()
    for fname, label in files_to_check.items():
        fpath = os.path.join(CRYPTO_OUTPUT_DIR, fname)
        if os.path.exists(fpath):
            stat = os.stat(fpath)
            mtime = datetime.fromtimestamp(stat.st_mtime)
            age_hours = (now - mtime).total_seconds() / 3600
            result.append({
                'file': fname,
                'label': label,
                'exists': True,
                'size_kb': round(stat.st_size / 1024, 1),
                'modified': mtime.strftime('%Y-%m-%d %H:%M:%S'),
                'age_hours': round(age_hours, 1),
                'stale': age_hours > 24,
            })
        else:
            result.append({'file': fname, 'label': label, 'exists': False})

    # Lead-lag results (stored under crypto_market/lead_lag/, not output/)
    ll_path = os.path.join(CRYPTO_MARKET_DIR, 'lead_lag', 'results.json')
    if os.path.exists(ll_path):
        stat = os.stat(ll_path)
        mtime = datetime.fromtimestamp(stat.st_mtime)
        age_hours = (now - mtime).total_seconds() / 3600
        result.append({
            'file': 'lead_lag/results.json', 'label': 'Lead-Lag Analysis',
            'exists': True, 'size_kb': round(stat.st_size / 1024, 1),
            'modified': mtime.strftime('%Y-%m-%d %H:%M:%S'),
            'age_hours': round(age_hours, 1), 'stale': age_hours > 48,
        })
    else:
        result.append({'file': 'lead_lag/results.json', 'label': 'Lead-Lag Analysis', 'exists': False})

    # Signals DB (stored under crypto_market/, not output/)
    db_path = os.path.join(CRYPTO_MARKET_DIR, 'signals.sqlite3')
    if os.path.exists(db_path):
        stat = os.stat(db_path)
        mtime = datetime.fromtimestamp(stat.st_mtime)
        age_hours = (now - mtime).total_seconds() / 3600
        result.append({
            'file': 'signals.sqlite3', 'label': 'VCP Signals DB',
            'exists': True, 'size_kb': round(stat.st_size / 1024, 1),
            'modified': mtime.strftime('%Y-%m-%d %H:%M:%S'),
            'age_hours': round(age_hours, 1), 'stale': age_hours > 24,
        })
    else:
        result.append({'file': 'signals.sqlite3', 'label': 'VCP Signals DB', 'exists': False})

    return jsonify({'files': result})


@crypto_bp.route('/backtest-summary')
@pro_required
def backtest_summary():
    """백테스트 요약 (Pro only)"""
    data = _load_json(os.path.join(CRYPTO_OUTPUT_DIR, 'backtest_result.json'))
    if not data:
        return jsonify({'error': 'No backtest data. Run backtest first.'}), 404
    # trades 배열 제외한 요약만
    summary = {k: v for k, v in data.items() if k != 'trades'}
    return jsonify(summary)


@crypto_bp.route('/backtest-results')
@pro_required
def backtest_results():
    """백테스트 전체 결과 (Pro only)"""
    data = _load_json(os.path.join(CRYPTO_OUTPUT_DIR, 'backtest_result.json'))
    if not data:
        return jsonify({'error': 'No backtest data. Run backtest first.'}), 404
    return jsonify(data)


# ── VCP Enhanced ──────────────────────────────────────────────────────────────

@crypto_bp.route('/vcp-enhanced')
def get_crypto_vcp_enhanced():
    """Crypto VCP 통합 분석 — 캐시 파일 기반 반환."""
    try:
        cached_path = os.path.join(_BASE_DIR, 'data', 'vcp_crypto_latest.json')
        if os.path.exists(cached_path):
            with open(cached_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            resp = jsonify(data)
            resp.headers['Cache-Control'] = 'public, max-age=300'
            return resp
        return jsonify({"metadata": {"market": "CRYPTO"}, "summary": {}, "signals": []}), 200
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

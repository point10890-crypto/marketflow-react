# app/routes/crypto.py
"""Crypto 마켓 API 라우트"""

import os
import sys
import json
import traceback
from datetime import datetime
from flask import Blueprint, jsonify, request, send_from_directory
from openai import OpenAI

crypto_bp = Blueprint('crypto', __name__)


@crypto_bp.route('/vcp-signals')
def crypto_vcp_signals():
    """Crypto VCP 시그널 조회"""
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'crypto_market'))
        from crypto_market.run_scan import get_signals_from_db
        
        limit = request.args.get('limit', 50, type=int)
        db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'crypto_market', 'signals.sqlite3')
        
        signals = get_signals_from_db(db_path=db_path, limit=limit)
        
        return jsonify({
            'signals': signals,
            'count': len(signals),
            'generated_at': datetime.now().isoformat()
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e), 'signals': []}), 500


@crypto_bp.route('/run-scan', methods=['POST'])
def crypto_run_scan():
    """Crypto VCP 스캔 실행"""
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'crypto_market'))
        from crypto_market.run_scan import run_scan_sync
        
        data = request.json or {}
        top_n = data.get('top_n', 200)
        min_qv = data.get('min_quote_volume', 5_000_000)
        max_conc = data.get('max_concurrency', 12)
        
        db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'crypto_market', 'signals.sqlite3')
        
        result = run_scan_sync(
            top_n=top_n,
            min_qv=min_qv,
            max_conc=max_conc,
            db_path=db_path
        )
        
        return jsonify(result)
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@crypto_bp.route('/market-gate')
def crypto_market_gate():
    """Crypto Market Gate 상태 (JSON 캐시 우선, fallback으로 라이브)"""
    # 1) JSON 캐시에서 읽기 (스케줄러가 6시간마다 갱신)
    gate_path = os.path.join('crypto_market', 'output', 'market_gate.json')
    if os.path.exists(gate_path):
        try:
            with open(gate_path, 'r', encoding='utf-8') as f:
                return jsonify(json.load(f))
        except Exception:
            pass

    # 2) Fallback: 간단한 라이브 계산
    try:
        import yfinance as yf
        btc = yf.Ticker('BTC-USD')
        hist = btc.history(period='200d')
        if len(hist) < 200:
            return jsonify({'status': 'NEUTRAL', 'gate': 'YELLOW', 'score': 50})
        price = hist['Close'].iloc[-1]
        ma200 = hist['Close'].rolling(200).mean().iloc[-1]
        ma50 = hist['Close'].rolling(50).mean().iloc[-1]
        gate = 'YELLOW'
        status = 'NEUTRAL'
        score = 50
        if price > ma200 and price > ma50:
            gate, status, score = 'GREEN', 'RISK_ON', 75
        elif price < ma200 and price < ma50:
            gate, status, score = 'RED', 'RISK_OFF', 25
        return jsonify({'gate': gate, 'status': status, 'score': score, 'price': float(price), 'ma200': float(ma200)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@crypto_bp.route('/gate-scan', methods=['POST'])
def crypto_gate_scan():
    """Crypto Gate 스캔 (수동 트리거)"""
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'crypto_market'))
        from crypto_market.market_gate import run_market_gate_sync
        result = run_market_gate_sync()
        return jsonify({
            'gate': result.gate, 'score': result.score,
            'reasons': result.reasons, 'metrics': result.metrics
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@crypto_bp.route('/briefing')
def crypto_briefing():
    """Crypto 일일 브리핑"""
    path = os.path.join('crypto_market', 'output', 'crypto_briefing.json')
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return jsonify(json.load(f))
    return jsonify({'error': 'No briefing data available'}), 404


@crypto_bp.route('/prediction')
def crypto_prediction():
    """BTC 방향 예측"""
    path = os.path.join('crypto_market', 'output', 'btc_prediction.json')
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return jsonify(json.load(f))
    return jsonify({'error': 'No prediction data available'}), 404


@crypto_bp.route('/risk')
def crypto_risk():
    """Crypto 포트폴리오 리스크"""
    path = os.path.join('crypto_market', 'output', 'crypto_risk.json')
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return jsonify(json.load(f))
    return jsonify({'error': 'No risk data available'}), 404


@crypto_bp.route('/timeline')
def crypto_timeline():
    """Crypto 타임라인"""
    try:
        timeline_path = os.path.join('crypto_market', 'timeline.json')
        if os.path.exists(timeline_path):
            with open(timeline_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify(data)
        return jsonify({'events': []})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@crypto_bp.route('/monthly-report')
def crypto_monthly_report():
    """Crypto 월간 리포트"""
    try:
        reports_dir = os.path.join('crypto_market', 'crypto_monthly_reports')
        if not os.path.exists(reports_dir):
            return jsonify({'report': None})
        
        files = sorted([f for f in os.listdir(reports_dir) if f.endswith('.json')], reverse=True)
        if files:
            with open(os.path.join(reports_dir, files[0]), 'r', encoding='utf-8') as f:
                report = json.load(f)
            return jsonify({'report': report})
        return jsonify({'report': None})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@crypto_bp.route('/gate-history')
def crypto_gate_history():
    """Gate 히스토리 조회"""
    path = os.path.join('crypto_market', 'output', 'gate_history.json')
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                history = json.load(f)
            return jsonify({'history': history})
        except Exception:
            pass
    return jsonify({'history': []})


@crypto_bp.route('/prediction-history')
def crypto_prediction_history():
    """BTC 예측 히스토리 조회"""
    path = os.path.join('crypto_market', 'output', 'btc_prediction_history.json')
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                history = json.load(f)
            return jsonify({'history': history})
        except Exception:
            pass
    return jsonify({'history': []})


@crypto_bp.route('/lead-lag')
def crypto_lead_lag():
    """Crypto Lead-Lag 분석"""
    try:
        lead_lag_path = os.path.join('crypto_market', 'lead_lag', 'results.json')
        if os.path.exists(lead_lag_path):
            with open(lead_lag_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify(data)
        return jsonify({'pairs': []})
    except Exception as e:
        return jsonify({'error': str(e), 'pairs': []}), 500


@crypto_bp.route('/lead-lag/charts/<path:filename>')
def serve_lead_lag_chart(filename):
    """Serve Lead-Lag chart images"""
    try:
        charts_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'crypto_market', 'lead_lag', 'lead_lag_charts')
        return send_from_directory(charts_dir, filename)
    except Exception as e:
        return jsonify({'error': str(e)}), 404


@crypto_bp.route('/lead-lag/charts/list')
def list_lead_lag_charts():
    """List available Lead-Lag charts"""
    try:
        charts_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'crypto_market', 'lead_lag', 'lead_lag_charts')
        if not os.path.exists(charts_dir):
            return jsonify({'charts': []})
        
        files = sorted([f for f in os.listdir(charts_dir) if f.endswith('.png')], reverse=True)
        return jsonify({'charts': files})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@crypto_bp.route('/signal-analysis', methods=['POST'])
def crypto_signal_analysis():
    """LLM으로 VCP 시그널 분석 — 왜 이 코인이 감지되었는지 설명"""
    try:
        data = request.json
        if not data or 'symbol' not in data:
            return jsonify({'error': 'symbol required'}), 400

        symbol = data['symbol']
        signal_type = data.get('signal_type', 'VCP')
        score = data.get('score', 0)
        pivot_high = data.get('pivot_high', 0)
        vol_ratio = data.get('vol_ratio', 0)
        timeframe = data.get('timeframe', '4h')
        current_price = data.get('current_price', 0)

        distance_pct = ((current_price / pivot_high - 1) * 100) if pivot_high > 0 and current_price > 0 else 0

        prompt = f"""당신은 암호화폐 기술적 분석 전문가입니다. VCP(Volatility Contraction Pattern) 스캐너가 다음 코인을 감지했습니다. 왜 이 코인이 감지되었는지, 그리고 트레이딩 관점에서의 의미를 분석해주세요.

## 감지된 시그널
- **코인**: {symbol}
- **시그널 유형**: {signal_type} ({'피봇 고점 돌파 확인' if signal_type == 'BREAKOUT' else '돌파 임박'})
- **VCP 점수**: {score}/100
- **피봇 고점 (저항선)**: ${pivot_high}
- **현재 가격**: ${current_price}
- **피봇 대비**: {distance_pct:+.1f}%
- **거래량 비율**: {vol_ratio:.2f}x (평균 대비)
- **타임프레임**: {timeframe}

## 분석 요청사항
1. **VCP 패턴 해석**: 이 점수와 거래량 비율이 의미하는 바
2. **피봇 고점 분석**: 현재 가격과 피봇의 관계, 돌파 가능성
3. **리스크/리워드**: 진입 시 고려할 점, 손절/목표가 제안
4. **주의사항**: 이 시그널의 한계점이나 추가 확인이 필요한 부분

한국어로 간결하게 작성해주세요. 각 섹션은 2~3문장으로 제한. 총 200자 이내."""

        client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        response = client.chat.completions.create(
            model='gpt-4o-mini',
            messages=[
                {'role': 'system', 'content': '암호화폐 기술적 분석 전문가. 간결하고 실용적인 분석을 제공합니다.'},
                {'role': 'user', 'content': prompt}
            ],
            max_tokens=600,
            temperature=0.3,
        )

        analysis = response.choices[0].message.content

        return jsonify({
            'analysis': analysis,
            'symbol': symbol,
            'model': 'gpt-4o-mini',
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


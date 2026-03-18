# PART8: Flask API 서버

## `flask_app.py` (핵심 Crypto 엔드포인트)

```python
#!/usr/bin/env python3
from flask import Flask, jsonify, render_template, request
from datetime import datetime
import json

app = Flask(__name__)


# ============================================================
# CRYPTO API ENDPOINTS
# ============================================================

@app.route('/api/crypto/market-gate')
def api_crypto_market_gate():
    """Market Gate 분석 API"""
    try:
        from crypto_market.market_gate import run_market_gate_sync
        
        result = run_market_gate_sync()
        
        # 지표별 시그널 분류
        indicators = []
        for name, val in result.metrics.items():
            signal = 'Neutral'
            if isinstance(val, (int, float)) and val is not None:
                if name == 'btc_ema200_slope_pct_20':
                    signal = 'Bullish' if val > 1 else ('Bearish' if val < -1 else 'Neutral')
                elif name == 'fear_greed_index':
                    signal = 'Bullish' if val > 50 else ('Bearish' if val < 30 else 'Neutral')
                elif name == 'funding_rate':
                    if val is not None:
                        signal = 'Bullish' if -0.0003 < val < 0.0005 else 'Bearish'
                elif name == 'alt_breadth_above_ema50':
                    if val is not None:
                        signal = 'Bullish' if val > 0.5 else ('Bearish' if val < 0.35 else 'Neutral')
            
            indicators.append({
                'name': name,
                'value': val,
                'signal': signal
            })
        
        return jsonify({
            'gate_color': result.gate,
            'score': result.score,
            'summary': f"BTC 시장 상태: {result.gate} (점수: {result.score}/100)",
            'indicators': indicators,
            'top_reasons': result.reasons,
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/crypto/lead-lag')
def api_crypto_lead_lag():
    """Lead-Lag 분석 API"""
    try:
        from crypto_market.lead_lag.data_fetcher import fetch_all_data
        from crypto_market.lead_lag.granger import find_granger_causal_indicators
        
        # 데이터 수집
        df = fetch_all_data(start_date="2020-01-01", resample="monthly")
        
        if df.empty:
            return jsonify({'error': 'No data available'}), 500
        
        # BTC MoM을 예측하는 선행 지표 찾기
        target = "BTC_MoM"
        if target not in df.columns:
            target = "BTC"
        
        results = find_granger_causal_indicators(df, target=target, max_lag=6)
        
        leading_indicators = []
        for r in results[:10]:
            # 상관관계 계산
            corr = df[r.cause].corr(df[target].shift(r.best_lag))
            
            leading_indicators.append({
                'variable': r.cause,
                'lag': r.best_lag,
                'p_value': r.best_p_value,
                'correlation': float(corr) if not pd.isna(corr) else 0,
                'interpretation': r.get_interpretation()
            })
        
        return jsonify({
            'target': target,
            'leading_indicators': leading_indicators,
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/crypto/vcp-signals')
def api_crypto_vcp_signals():
    """VCP 시그널 목록 API"""
    try:
        from crypto_market.storage import make_engine, get_recent_signals
        
        engine = make_engine("crypto_market/signals.sqlite3")
        signals = get_recent_signals(engine, limit=50)
        
        return jsonify({
            'signals': signals,
            'count': len(signals),
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/crypto/timeline')
def api_crypto_timeline():
    """타임라인 이벤트 API"""
    try:
        import json
        from pathlib import Path
        
        timeline_path = Path("crypto_market/timeline_events.json")
        if timeline_path.exists():
            with open(timeline_path) as f:
                events = json.load(f)
        else:
            events = []
        
        return jsonify({
            'events': events,
            'count': len(events),
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============================================================
# DASHBOARD ROUTE
# ============================================================

@app.route('/app')
def dashboard():
    """메인 대시보드"""
    return render_template('dashboard.html')


@app.route('/')
def index():
    """루트 → 대시보드로 리다이렉트"""
    return redirect('/app')


# ============================================================
# MAIN
# ============================================================

if __name__ == '__main__':
    import os
    
    debug = os.environ.get('FLASK_DEBUG', 'true').lower() == 'true'
    port = int(os.environ.get('PORT', 5001))
    
    print(f"🚀 Starting Flask server on port {port}...")
    app.run(host='0.0.0.0', port=port, debug=debug)
```

---

## API 엔드포인트 요약

| Endpoint | Method | 설명 |
|----------|--------|------|
| `/api/crypto/market-gate` | GET | Market Gate 분석 (0-100점) |
| `/api/crypto/lead-lag` | GET | Granger Causality 선행 지표 |
| `/api/crypto/vcp-signals` | GET | VCP 시그널 목록 |
| `/api/crypto/timeline` | GET | 타임라인 이벤트 |
| `/app` | GET | 메인 대시보드 |

---

## 실행

```bash
# 기본 실행
python flask_app.py

# 프로덕션 모드
FLASK_DEBUG=false PORT=8000 python flask_app.py
```

---

## API 응답 예시

### Market Gate
```json
{
  "gate_color": "GREEN",
  "score": 78,
  "summary": "BTC 시장 상태: GREEN (점수: 78/100)",
  "indicators": [
    {"name": "btc_price", "value": 98500.0, "signal": "Neutral"},
    {"name": "fear_greed_index", "value": 65, "signal": "Bullish"}
  ],
  "top_reasons": ["조건이 전반적으로 양호함"]
}
```

### Lead-Lag
```json
{
  "leading_indicators": [
    {
      "variable": "DXY_MoM",
      "lag": 3,
      "p_value": 0.0123,
      "correlation": -0.45,
      "interpretation": "DXY_MoM은(는) BTC_MoM을(를) 3기간 선행하여 예측 가능"
    }
  ]
}
```

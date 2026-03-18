# 🪙 Bitcoin Analysis System - Complete Blueprint

> **ULTRATHINK MODE V2**: 실제 운영 중인 시스템의 **전체 소스 코드**를 포함한 완벽 복원 가이드

---

## 📚 블루프린트 목차

| Part | 파일 | 내용 |
|------|-----|------|
| **1** | [PART1_Infrastructure.md](./PART1_Infrastructure.md) | 환경 설정, requirements.txt, indicators.py |
| **2** | [PART2_Config.md](./PART2_Config.md) | config.py - TimeframeCfg, ScannerCfg, VCP Grades |
| **3** | [PART3_Models_Storage.md](./PART3_Models_Storage.md) | models.py, storage.py (SQLite) |
| **4** | [PART4_Data_Collection.md](./PART4_Data_Collection.md) | universe.py, fetch_async.py, futures_metrics.py |
| **5** | [PART5_Market_Gate.md](./PART5_Market_Gate.md) | market_gate.py (434줄, 100점 스코어링) |
| **6** | [PART6_VCP_Signals.md](./PART6_VCP_Signals.md) | signals.py, scoring.py, vcp_swings.py |
| **7** | [PART7_Lead_Lag.md](./PART7_Lead_Lag.md) | granger.py, data_fetcher.py (매크로 분석) |
| **8** | [PART8_Flask_API.md](./PART8_Flask_API.md) | flask_app.py (API 엔드포인트) |
| **9** | [PART9_Frontend.md](./PART9_Frontend.md) | dashboard.html (Glassmorphism UI) |

---

## ✅ 전체 파일 체크리스트

### 루트 파일
```
[  ] flask_app.py
[  ] requirements.txt
[  ] .env
```

### crypto_market/
```
[  ] __init__.py
[  ] config.py
[  ] models.py
[  ] storage.py
[  ] indicators.py
[  ] universe.py
[  ] fetch_async.py
[  ] futures_metrics.py
[  ] market_gate.py
[  ] signals.py
[  ] scoring.py
[  ] vcp_swings.py
[  ] run_scan.py
[  ] orchestrator.py
```

### crypto_market/lead_lag/
```
[  ] __init__.py
[  ] data_fetcher.py
[  ] granger.py
[  ] cross_correlation.py
[  ] llm_interpreter.py
[  ] visualizer.py
```

### crypto_market/vcp_backtest/
```
[  ] __init__.py
[  ] config.py
[  ] engine.py
[  ] walk_forward.py
[  ] risk_manager.py
[  ] fee_model.py
[  ] portfolio_manager.py
[  ] regime_config.py
[  ] data_quality.py
[  ] signal_replay.py
```

### crypto_market/operations/
```
[  ] __init__.py
[  ] scheduler.py
[  ] notifier.py
```

### templates/
```
[  ] dashboard.html
```

---

## 🚀 빠른 시작

```bash
# 1. 디렉토리 구조 생성
mkdir -p crypto_market/{lead_lag,vcp_backtest,operations}
mkdir -p templates

# 2. 의존성 설치
pip install flask pandas numpy yfinance ccxt statsmodels sqlalchemy python-dotenv requests aiohttp google-generativeai

# 3. 환경 변수 설정
echo "GEMINI_API_KEY=your_key_here" > .env

# 4. 서버 실행
python flask_app.py

# 5. 브라우저 접속
open http://localhost:5001/app
```

---

## 📊 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                    FLASK WEB SERVER                          │
│                     (flask_app.py)                           │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ Market Gate  │  │   Lead-Lag   │  │  VCP Scanner │       │
│  │   (100점)    │  │  (Granger)   │  │  (A/B/C/D)   │       │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘       │
│         │                 │                 │                │
│  ┌──────┴─────────────────┴─────────────────┴───────┐       │
│  │                    DATA LAYER                     │       │
│  │  yfinance │ ccxt │ Alternative.me │ Binance API  │       │
│  └───────────────────────────────────────────────────┘       │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│                    FRONTEND (Glassmorphism)                  │
│                     dashboard.html                           │
└─────────────────────────────────────────────────────────────┘
```

---

## 🔧 핵심 기능

### 1. Market Gate (시장 건전성)
- **Trend** (35점): BTC EMA 배열 + 기울기
- **Volatility** (18점): ATR% 안정성
- **Participation** (18점): 거래량 Z-score
- **Breadth** (18점): 알트 EMA50 위 비율
- **Leverage** (11점): 펀딩비

### 2. Lead-Lag (선행 지표)
- Granger Causality 검정
- 매크로 지표 → BTC 예측력 분석
- 최대 6개월 시차 검증

### 3. VCP Scanner (패턴 탐지)
- A/B/C/D 등급 분류
- 실시간 돌파/리테스트 감지
- 0-100점 품질 스코어링

---

## 📝 완전 복원 순서

1. **PART1** → 환경 설정
2. **PART2** → 설정 파일
3. **PART3** → 데이터 모델
4. **PART4** → 데이터 수집
5. **PART5** → Market Gate
6. **PART6** → VCP 시그널
7. **PART7** → Lead-Lag
8. **PART8** → Flask API
9. **PART9** → 프론트엔드

각 PART를 순서대로 복사-붙여넣기하면 **100% 동일한 시스템**이 만들어집니다.

---

## ⚠️ 중요 참고사항

1. **API 키 필수**: `.env`에 `GEMINI_API_KEY` 설정
2. **포트**: 기본 5001 (환경변수 `PORT`로 변경 가능)
3. **데이터베이스**: SQLite 자동 생성 (`signals.sqlite3`)
4. **자동 갱신**: 프론트엔드 10분마다, 백엔드 Orchestrator 1시간마다

---

**생성일**: 2025-12-27
**버전**: 2.0 (ULTRATHINK Complete Edition)

---

## 📦 추가 파트 (PART10-11)

| Part | 파일 | 내용 |
|------|-----|------|
| **10** | [PART10_Backtest.md](./PART10_Backtest.md) | 백테스트 엔진 (config, fee_model) |
| **11** | [PART11_Indicators_Swings.md](./PART11_Indicators_Swings.md) | indicators.py, vcp_swings.py 완전 |

---

## ⚠️ 실제 복원 시 참조해야 할 대용량 파일

블루프린트에는 핵심 로직만 포함되어 있습니다.  
**완전 복원**을 위해 아래 파일은 **직접 복사**하세요:

| 파일 | 크기 | 경로 |
|------|------|------|
| engine.py | 15KB | `crypto_market/vcp_backtest/engine.py` |
| risk_manager.py | 13KB | `crypto_market/vcp_backtest/risk_manager.py` |
| walk_forward.py | 10KB | `crypto_market/vcp_backtest/walk_forward.py` |
| orchestrator.py | 20KB | `crypto_market/orchestrator.py` |
| dashboard.html | 160KB | `templates/dashboard.html` |

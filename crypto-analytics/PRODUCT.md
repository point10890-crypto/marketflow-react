# CryptoAnalytics

**AI-Powered Crypto Market Intelligence Platform**

시장 레짐 분석, VCP 시그널 스캐닝, ML 가격 예측, 매크로 상관관계 분석을 하나의 플랫폼에서 제공합니다.

---

## Why CryptoAnalytics?

크립토 시장은 24/7 돌아갑니다. 수백 개 코인의 차트를 매일 눈으로 확인하는 것은 불가능합니다.

CryptoAnalytics는 **시장 상태 판단 → 시그널 탐색 → AI 분석 → 리스크 관리**까지의 전체 워크플로우를 자동화합니다.

| 기존 방식 | CryptoAnalytics |
|---|---|
| 수백 개 차트를 수동으로 확인 | 200+ 코인 자동 스캔 (4시간마다) |
| 감에 의존한 시장 판단 | 5개 지표 기반 Market Gate 점수화 |
| 단일 지표 의존 | 18개 피처 ML 앙상블 예측 |
| 매크로와 크립토를 별도로 분석 | Lead-Lag 인과관계 자동 분석 |
| 백테스트 없이 전략 운용 | Walk-Forward 검증 엔진 내장 |

---

## Core Features

### 1. Market Gate System — 시장 레짐 분류

시장의 건강 상태를 **GREEN / YELLOW / RED** 3단계로 자동 분류합니다.

```
GREEN (72+)  → 공격 모드. 적극적 진입 허용
YELLOW (48~71) → 선별 모드. 엄선된 시그널만 진입
RED (< 48)   → 방어 모드. 신규 진입 중단
```

**ULTRATHINK 스코어링 (100점 만점)**

| 카테고리 | 비중 | 측정 항목 |
|---|---|---|
| Trend | 35% | BTC EMA 배열 + EMA200 기울기 |
| Volatility | 18% | ATR% 기반 변동성 안정도 |
| Participation | 18% | 거래량 Z-score |
| Breadth | 18% | 알트코인 EMA50 상회 비율 |
| Leverage | 11% | 펀딩레이트 + OI 변화 |

모든 시그널과 전략이 **Gate 상태에 연동**되어, 하락장에서의 무리한 진입을 시스템적으로 차단합니다.

---

### 2. VCP Signal Scanner — 변동성 수축 패턴 탐지

Mark Minervini의 VCP(Volatility Contraction Pattern)를 크립토에 최적화하여 자동 탐지합니다.

**시그널 유형**
- **BREAKOUT** — 피봇 고점 돌파 확인
- **APPROACHING** — 돌파 임박 (저항선 2% 이내)
- **RETEST_OK** — 돌파 후 지지 확인 완료

**4단계 그레이딩**

| Grade | 조건 | 설명 |
|---|---|---|
| A | Close > EMA50 > EMA200 | Minervini 정석 VCP |
| B | Close > EMA50 | 완화된 VCP |
| C | Close > EMA200 | 기본 수축 패턴 |
| D | 축적 패턴 | 약세장 대응 |

**스코어링 (0~100)**
- 수축 비율 (Contraction Ratio)
- 거래량 비율 (Volume Ratio)
- EMA 이격도 (EMA Separation)
- EMA50 상회 비율 (Above-EMA50 Ratio)

**ML Win Probability — 시그널별 승률 예측**

2,500+ 과거 백테스트 트레이드를 학습한 ML 모델이 각 시그널의 **수익 확률(ML Win)**을 자동 산출합니다.

| ML Win | 해석 | 권장 액션 |
|---|---|---|
| 70%+ | 과거 유사 패턴 대부분 수익 | 적극 고려 |
| 50~70% | 수익 가능성 있음 | 다른 조건과 함께 판단 |
| 35~50% | 손실 가능성이 높음 | 주의 |
| 35% 미만 | 과거 유사 패턴 대부분 손실 | 진입 비추 |

- **4-모델 앙상블**: RandomForest, GradientBoosting, HistGradientBoosting, LogisticRegression
- **25개 피처**: 수축 품질, 거래량, 추세 강도, 돌파 강도, 시장 레짐 등
- **학습 데이터**: 2023~2025 백테스트 2,515건 트레이드 (WIN/LOSS 결과)
- 기존 Rule-based Score와 ML Win이 **둘 다 높으면** 신뢰도 상승

```
예시:
BFUSD/USDT  Score 50  ML Win 73.3%  → 점수는 보통이지만 패턴상 유리
LINEA/USDT  Score 39  ML Win 21.3%  → 점수도 낮고 패턴도 불리
```

> 6시간마다 자동 스캔 + 중복 알림 방지 + Gate 연동 필터링 + ML 승률 자동 산출

---

### 3. AI Price Prediction — 5일 방향 예측

**4-Algorithm Multi-Model Ensemble**로 BTC 5일 방향을 예측합니다.

| 모델 | 역할 |
|---|---|
| GradientBoosting (x3 seed) | 순차 학습 기반 앙상블 |
| RandomForest | 병렬 트리 기반 분류 |
| HistGradientBoosting | 대용량 최적화 부스팅 |
| LogisticRegression | 선형 기준선 모델 |

**18개 입력 피처**

| 구분 | 피처 |
|---|---|
| Technical | RSI-14, MACD, 볼린저밴드 위치, EMA 크로스 |
| Cross-Asset | ETH/BTC 비율, SPY/GLD/DXY 수익률 |
| Sentiment | Fear & Greed Index |
| Macro | VIX 레벨, VIX 백분위, TLT 수익률, 펀딩레이트 |

- **TimeSeriesSplit** 교차검증으로 데이터 누수 원천 차단
- 모델 7일 경과 시 **자동 재학습**
- 예측 이력 저장으로 **정확도 추적** 가능
- **모델별 예측 결과** 대시보드에서 개별 확인 가능
- **Feature Importance** 시각화로 근거 투명하게 제공

---

### 4. Daily Market Briefing — 매일 시장 브리핑

매일 자동으로 수집 + 정리되는 크립토 시장 종합 리포트입니다.

- **시가총액 & BTC 도미넌스** (CoinGecko)
- **주요 코인 현황** — BTC, ETH, SOL, BNB, XRP 가격 및 24h 변동
- **Top Movers** — 상위 100 코인 중 급등/급락 종목
- **Fear & Greed Index** — 0~100 시장 심리 지수
- **펀딩레이트** — BTC/ETH 무기한 선물 펀딩
- **Cross-Asset 상관관계** — BTC vs SPY, GLD, DXY 비교
- **텔레그램 자동 알림** 연동

---

### 5. Lead-Lag Macro Analysis — 매크로 인과관계 분석

BTC 가격에 **선행하는 매크로 지표**를 통계적으로 찾아냅니다.

**분석 방법론**
1. **Lagged Cross-Correlation** — 최대 ±12개월 시차 상관관계
2. **Granger Causality Test** — 통계적 예측력 검증 (p-value)
3. **AI 해석** — Gemini가 인과관계를 자연어로 설명

**분석 대상 지표**
- 연준 금리, M2 통화량, 실업수당 청구
- 달러 인덱스(DXY), 국채 수익률, VIX
- BTC 자기상관(Autoregressive)

**시각화 산출물**
- 상관관계 히트맵
- Granger 인과관계 네트워크
- CCF(Cross-Correlation Function) 차트

---

### 6. Risk Analysis — 포트폴리오 리스크 분석

15개 주요 크립토 자산의 리스크를 실시간 모니터링합니다.

| 지표 | 설명 |
|---|---|
| **VaR (95%)** | 95% 신뢰구간 최대 손실 추정 |
| **CVaR** | VaR 초과 시 기대 손실 |
| **상관관계 매트릭스** | 코인 간 동조화 수준 |
| **연간 변동성** | 자산별 변동성 비교 |
| **집중도 분석** | BTC 도미넌스, 상위 3개 비중 |

**자동 알림 조건**
- 낙폭 > -10%
- 변동성 > 80% (연간화)
- 코인 간 상관관계 > 0.90 (집중 리스크)

---

### 7. Backtesting Engine — Walk-Forward 검증

전략을 과거 데이터로 **Out-of-Sample 검증**합니다.

**주요 기능**
- **포지션 사이징** — 균등, 스코어 가중, 변동성 조정
- **진입/청산** — 시그널 캔들 종가 또는 다음 봉 시가
- **수수료 모델** — 커미션 + 슬리피지 양면 반영
- **Fake Breakout 필터** — 허위 돌파 시그널 제거
- **레짐별 성과 분석** — GREEN/YELLOW/RED 구간별 분리 평가
- **Equity Curve** — 자산 곡선 + 최대 낙폭 추적

```
python crypto_market/run_backtest.py backtest --start 2023-01-01 --end 2024-12-01
python crypto_market/run_backtest.py walkforward --train-months 6 --test-months 1
```

---

### 8. Playbook QA — Gemini RAG 기반 트레이딩 룰 질의

Google Gemini File Search API를 활용한 **트레이딩 플레이북 Q&A 시스템**입니다.

- 플레이북 문서를 업로드하면 자동 인덱싱
- 자연어로 트레이딩 규칙 질의 가능
- 출처(Citation) 기반 답변으로 신뢰성 확보
- **Post-Mortem Archive** — 트레이드 결과 기록 + 패턴 분석

```
Q: "Gate가 YELLOW일 때 진입 조건은?"
A: "min_score=60 이상, 선별적 진입만 허용됩니다." [출처: playbook_rules.txt]
```

---

## Dashboard

직관적인 대시보드에서 모든 데이터를 한눈에 확인할 수 있습니다.

| 페이지 | 내용 |
|---|---|
| **Overview** | Gate 상태, 시그널 수, 시스템 헬스 |
| **VCP Signals** | 시그널 테이블 + 캔들차트 + AI 분석 |
| **Briefing** | 시총, 주요 코인, Fear & Greed, 펀딩레이트 |
| **Prediction** | 상승 확률 게이지 + Feature Importance + 이력 |
| **Risk** | VaR/CVaR 지표, 상관관계 히트맵, 변동성 알림 |
| **Lead-Lag** | 매크로 히트맵, 인과관계 네트워크, CCF 차트 |

---

## Automation

**Orchestrator**가 전체 파이프라인을 자동 관리합니다.

| 주기 | 태스크 | 우선순위 |
|---|---|---|
| 4시간 | Market Gate 체크 | CRITICAL |
| 4시간 | VCP 스캔 (RED 시 스킵) | HIGH |
| 1시간 | Healthcheck | MEDIUM |
| 24시간 | Briefing + Prediction + Risk | MEDIUM |
| 24시간 | Lead-Lag 분석 | LOW |
| 7일 | Attribution 리포트 + 데이터 정리 | LOW |

**안정성 기능**
- **FileLock** — 동시 실행 방지
- **Idempotency** — 재실행 안전 (중복 처리 방지)
- **Notification Dedup** — 알림 중복 방지 (쿨다운)
- **Retry + Backoff** — 실패 시 자동 재시도
- **Structured Logging** — JSON 로그로 디버깅 용이

---

## Tech Stack

| 영역 | 기술 |
|---|---|
| **Backend** | Flask, SQLAlchemy, SQLite |
| **Frontend** | Next.js 16, React 19, TypeScript, TailwindCSS 4 |
| **ML/분석** | scikit-learn, pandas, numpy, scipy |
| **데이터 수집** | CCXT, yfinance, CoinGecko, Binance API, FRED |
| **AI/LLM** | OpenAI GPT-4o-mini, Google Gemini 2.5 |
| **인증** | NextAuth v5, JWT |
| **결제** | Stripe (구독 관리) |
| **알림** | Telegram Bot API |

---

## Cross-Platform

Windows와 macOS 모두에서 동작합니다.

- 파일 잠금: `fcntl` (macOS/Linux) / `msvcrt` (Windows) 자동 분기
- 임시 파일: `tempfile.gettempdir()` (OS별 적정 경로)
- 시그널 처리: `SIGTERM` 존재 여부 자동 감지
- 인코딩: 모든 파일 I/O에 `encoding='utf-8'` 명시
- 경로: `os.path.join()` 사용으로 경로 구분자 호환

---

## Quick Start

```bash
# 1. 의존성 설치
pip install -r requirements.txt
cd frontend && npm install

# 2. 환경 변수 설정
cp .env.example .env
# GOOGLE_API_KEY, TELEGRAM_BOT_TOKEN 등 설정

# 3. 백엔드 실행
python run.py

# 4. 프론트엔드 실행
cd frontend && npm run dev

# 5. 데이터 업데이트 (전체 파이프라인)
python orchestrator.py once

# 6. 스케줄러 데몬 실행
python orchestrator.py run
```

---

## Pricing

| | Free | Pro |
|---|---|---|
| VCP 시그널 조회 | O | O |
| Market Overview | O | O |
| **AI 시그널 분석** | - | O |
| **가격 예측 (ML)** | - | O |
| **리스크 알림 (VaR/CVaR)** | - | O |
| **백테스팅 엔진** | - | O |
| **Lead-Lag 분석** | - | O |
| **텔레그램 알림** | - | O |
| **우선 지원** | - | O |
| 가격 | 무료 | $29/월 |

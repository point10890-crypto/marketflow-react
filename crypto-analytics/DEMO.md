# CryptoAnalytics

### AI가 24시간 크립토 시장을 감시합니다. 당신은 알림만 받으세요.

---

> 200개 코인 자동 스캔 | ML 승률 예측 | 매크로 인과관계 분석 | 포트폴리오 리스크 모니터링

---

## 문제

```
매일 수백 개 차트를 눈으로 확인하고 있나요?
"이거 돌파하려나?" 감으로 판단하고 있나요?
손절은 항상 늦고, 진입은 항상 이르지 않나요?
```

**CryptoAnalytics는 이 과정을 자동화합니다.**

---

## 실제 동작 화면

### Market Gate — 지금 시장에 진입해도 되는가?

```
┌─────────────────────────────────────┐
│          MARKET GATE                │
│                                     │
│           ██████████                │
│          ██ RED  19 ██              │
│           ██████████                │
│                                     │
│  Trend        ▓░░░░░░░░░  12/35    │
│  Volatility   ▓▓▓░░░░░░░   5/18    │
│  Participation▓░░░░░░░░░   1/18    │
│  Breadth      ▓░░░░░░░░░   1/18    │
│  Leverage     ░░░░░░░░░░   0/11    │
│                                     │
│  → 방어 모드. 신규 진입 중단.        │
└─────────────────────────────────────┘
```

5개 카테고리 점수를 합산해 시장을 **GREEN / YELLOW / RED** 3단계로 분류합니다.
RED일 때는 시스템이 자동으로 신규 진입을 차단합니다.

---

### VCP Signal Scanner — 돌파 직전 코인을 찾아냅니다

```
┌──────────────────────────────────────────────────────────────────────┐
│ Symbol         Type         Score   ML Win   Pivot High   Vol Ratio │
├──────────────────────────────────────────────────────────────────────┤
│ BFUSD/USDT     APPROACHING    50    73.3%    $1.0215      0.85x    │
│ EURI/USDT      APPROACHING    55    70.7%    $1.1941      0.42x    │
│ AWE/USDT       APPROACHING    58    53.6%    $0.0847      0.32x    │
│ ZK/USDT        APPROACHING    39    50.1%    $0.0712      1.12x    │
│ ETHFI/USDT     APPROACHING    42    35.6%    $0.8432      0.68x    │
│ LINEA/USDT     BREAKOUT       39    21.3%    $0.0156      1.45x    │
│ OG/USDT        BREAKOUT       33    20.0%    $3.8200      0.91x    │
└──────────────────────────────────────────────────────────────────────┘
```

**Score** = 룰 기반 패턴 점수 (수축 품질, 추세, 거래량, 리스크)
**ML Win** = 과거 2,500+ 트레이드를 학습한 AI가 예측한 승률

둘 다 높으면 신뢰도 UP. 엇갈리면 주의 필요.

---

### ML Win이 뭔가요?

2023~2025년 실제 백테스트 **2,515건 트레이드**의 승/패를 학습한 결과입니다.

```
학습 데이터:  2,515 trades (WIN 751 / LOSS 1,764)
피처:         25개 (수축 패턴 + 거래량 + 추세 + 시장 레짐)
모델:         4-Algorithm Ensemble (RF, GB, HGB, LR)

Top Feature Importance:
  breakout_close_pct         ████████████████████████████  0.277
  entry_type_BREAKOUT        ██████████                    0.098
  ema_sep_pct                ██████                        0.061
  vol_ratio                  ██████                        0.060
  atrp_pct                   █████                         0.048
```

| ML Win | 의미 | 추천 |
|--------|------|------|
| **70%+** | 과거 유사 패턴 대부분 수익 | 적극 고려 |
| **50~70%** | 수익 가능성 있음 | 조건부 진입 |
| **35~50%** | 손실 가능성 높음 | 주의 |
| **< 35%** | 유사 패턴 대부분 손실 | 진입 비추 |

---

### BTC Direction Prediction — 5일 방향 예측

```
┌─────────────────────────────────────────────┐
│                                             │
│   Bearish 77.7%  ████████████████░░░░ 22.3% │
│                                             │
│              ▼ BEARISH                      │
│           77.7% probability                 │
│         Confidence: High                    │
│                                             │
│   ── Per-Model Predictions ──               │
│   GradientBoosting     Acc 69.7%    22.9%   │
│   RandomForest         Acc 73.4%    24.2%   │
│   HistGradientBoosting Acc 69.6%    20.5%   │
│   LogisticRegression   Acc 72.4%    21.4%   │
│                                             │
│   Key Drivers:                              │
│   ↓ btc_return_20d     -24.70   ████████    │
│   ↓ btc_rsi_14          32.05   ███████     │
│   ↓ btc_bb_position      0.50   ██████      │
│   ↓ btc_return_5d        -2.72  ████        │
│   ↓ eth_btc_relative    -3.52   ████        │
│                                             │
└─────────────────────────────────────────────┘
```

4개 ML 모델이 독립적으로 예측한 결과를 앙상블합니다.
**왜 이렇게 예측했는지** Key Drivers로 근거를 투명하게 보여줍니다.

---

### Lead-Lag Macro Analysis — BTC보다 먼저 움직이는 지표

```
┌─ Leading Indicators ──────────────────────┐
│  1. M2 Money Supply    2M ahead   +0.847  │
│  2. Initial Claims     3M ahead   -0.623  │
│  3. Fed Funds Rate     4M ahead   -0.584  │
│  4. BTC Autoregressive 1M ahead   +0.512  │
└───────────────────────────────────────────┘

┌─ Granger Predictive (p < 0.05) ───────────┐
│  M2         lag 2  p=0.0003  ***           │
│  DXY        lag 1  p=0.0021  **            │
│  VIX        lag 3  p=0.0089  **            │
│  TLT        lag 2  p=0.0234  *             │
└────────────────────────────────────────────┘
```

**Granger 인과관계 검정**으로 BTC 가격을 통계적으로 예측 가능한 매크로 지표를 찾아냅니다.
"M2 통화량이 2개월 선행해서 BTC를 예측한다" — 이런 인사이트를 자동으로.

---

### Risk Monitoring — 잃기 전에 알려줍니다

```
┌─ Portfolio Risk ──────────────────────────┐
│                                           │
│  VaR (95%, 1d):    -4.23%                 │
│  CVaR:             -6.15%                 │
│  Risk Level:       HIGH                   │
│                                           │
│  ⚠ ALERT: SOL 낙폭 -12.3% (임계값 -10%) │
│  ⚠ ALERT: BTC-ETH 상관 0.94 (집중 리스크) │
│                                           │
└───────────────────────────────────────────┘
```

15개 코인의 VaR/CVaR을 실시간 계산하고, 위험 신호 발생 시 텔레그램으로 알림.

---

## 자동화

모든 것이 자동으로 돌아갑니다.

```
매 4시간   →  Market Gate 체크 + VCP 스캔
매 24시간  →  시장 브리핑 + BTC 예측 + 리스크 분석
매 7일     →  모델 재학습 + 데이터 정리
```

텔레그램에 시그널 알림이 자동으로 옵니다.
대시보드에서 한눈에 전체 현황을 봅니다.

---

## 기술 스택

| 영역 | 기술 |
|---|---|
| Backend | Flask, SQLAlchemy, SQLite |
| Frontend | Next.js 16, React 19, TypeScript, TailwindCSS 4 |
| ML/분석 | scikit-learn (RF, GB, HGB, LR), pandas, numpy, scipy |
| 데이터 | CCXT, yfinance, CoinGecko, Binance API, FRED |
| AI/LLM | OpenAI GPT-4o-mini, Google Gemini 2.5 |
| 인증 | NextAuth v5, JWT |
| 결제 | Stripe (구독 관리) |
| 알림 | Telegram Bot API |

---

## Quick Start

```bash
# 설치
pip install -r requirements.txt
cd frontend && npm install

# 환경 변수
cp .env.example .env
# GOOGLE_API_KEY, TELEGRAM_BOT_TOKEN 등 설정

# 실행
python run.py          # 백엔드 (포트 5001)
cd frontend && npm run dev  # 프론트엔드 (포트 3000)

# 전체 데이터 업데이트
python orchestrator.py once
```

---

## 가격

|  | Free | Pro |
|---|---|---|
| VCP 시그널 조회 | O | O |
| Market Overview | O | O |
| **ML 승률 예측 (ML Win)** | - | O |
| **AI 시그널 분석 (GPT-4o)** | - | O |
| **BTC 방향 예측 (4-Model)** | - | O |
| **리스크 알림 (VaR/CVaR)** | - | O |
| **백테스팅 엔진** | - | O |
| **Lead-Lag 매크로 분석** | - | O |
| **텔레그램 알림** | - | O |
| 가격 | 무료 | **$29/월** |

---

## FAQ

**Q: ML Win 정확도는 얼마나 되나요?**
A: 최고 모델(GradientBoosting) CV Accuracy 68.6%, Ensemble 65.8%입니다. Baseline(전부 LOSS 예측) 70.1% 대비 WIN을 식별하는 능력이 핵심입니다. ML Win 70%+ 시그널의 실제 승률은 baseline보다 유의미하게 높습니다.

**Q: BTC 예측은 얼마나 맞나요?**
A: 4-모델 앙상블 CV Accuracy 71.3%입니다. 모델별로 69.6~73.4% 범위이며, RandomForest가 73.4%로 최고입니다.

**Q: 어떤 거래소를 지원하나요?**
A: Binance Spot을 기본 지원합니다. CCXT 기반이라 100+ 거래소로 확장 가능합니다.

**Q: Windows에서도 되나요?**
A: 네. 파일 잠금(fcntl/msvcrt), 경로(os.path.join), 인코딩(UTF-8) 모두 크로스 플랫폼 대응되어 있습니다.

---

<p align="center">
<b>차트 수백 개를 눈으로 보는 시대는 끝났습니다.</b><br>
AI가 감시하고, 당신은 결정만 하세요.
</p>

---

*본 서비스의 모든 예측은 통계적 분석에 기반한 참고 자료이며, 투자 조언이 아닙니다. 암호화폐 투자에는 원금 손실 위험이 있으며, 투자 결정은 본인의 판단과 책임 하에 이루어져야 합니다.*

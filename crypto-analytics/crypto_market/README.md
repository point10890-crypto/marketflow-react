# Crypto Market Analysis System (V3)

> **ULTRATHINK Architecture** | Production-Ready | Auto-Update Enabled

---

## 🚀 Quick Start

```bash
# 자동 오케스트레이터 실행 (권장)
python orchestrator.py run

# 또는 개별 실행
python run_scan.py              # VCP 스캔
python run_backtest.py backtest # 백테스트
python run_lead_lag.py          # Lead-Lag 분석
```

---

## 📦 시스템 구조

```
crypto_market/
├── 🎯 orchestrator.py           # 통합 스케줄러 (V3 NEW)
│
├── ══ Core ══
├── signals.py                   # VCP 신호 생성
├── scoring.py                   # 0-100 점수
├── market_gate.py               # GREEN/YELLOW/RED 판단
│
├── ══ Backtest Suite ══
├── vcp_backtest/
│   ├── engine.py                # 트레이드 시뮬레이션
│   ├── config.py                # 설정
│   ├── walk_forward.py          # OOS 검증
│   ├── regime_config.py         # Gate별 파라미터 (V2)
│   ├── data_quality.py          # 캐시/바이어스 (V2)
│   ├── portfolio_manager.py     # 신호 우선순위 (V2)
│   ├── fake_breakout_filter.py  # 가짜 돌파 필터 (V2)
│   ├── lead_lag_gate.py         # 매크로 게이트 (V2)
│   ├── gemini_collections.py   # Gemini RAG (V2)
│   └── risk_manager.py          # 리스크 관리 (V3)
│
├── ══ Lead-Lag Analysis ══
├── lead_lag/
│   ├── data_fetcher.py          # yfinance + FRED
│   ├── cross_correlation.py     # 상관분석
│   ├── granger.py               # 인과성 테스트
│   └── llm_interpreter.py       # Gemini 해석
│
├── ══ Operations (V3 NEW) ══
├── operations/
│   ├── scheduler.py             # APScheduler
│   └── notifier.py              # Telegram 알림
│
├── ══ Analysis (V3 NEW) ══
├── analysis/
│   └── attribution.py           # 성과 분해
│
├── ══ Testing (V3 NEW) ══
├── tests/
│   └── run_all.py               # 데이터 품질 테스트
│
└── ══ Experiments (V3 NEW) ══
    experiments/
    └── tracker.py               # 실험 추적/재현
```

---

## ⏰ Orchestrator 자동 업데이트

| 태스크 | 주기 | 설명 |
|--------|------|------|
| 🚦 gate_check | 4시간 | Market Gate 상태 확인 |
| 🔍 vcp_scan | 4시간 | VCP 신호 스캔 (Gate 의존) |
| 💓 healthcheck | 1시간 | 시스템 상태 점검 |
| 📊 daily_report | 24시간 | 일일 리포트 |
| 📈 leadlag_refresh | 24시간 | Lead-Lag 데이터 갱신 |
| 🧹 data_cleanup | 주간 | 캐시 정리 |
| 📊 attribution | 주간 | 성과 분석 리포트 |

### 명령어

```bash
python orchestrator.py run      # 데몬 시작
python orchestrator.py once     # 한 번 실행
python orchestrator.py status   # 상태 확인
python orchestrator.py test     # 테스트 (Dry Run)
```

---

## 🛡️ V3 핵심 기능

### 1. Experiment Tracking
```python
from experiments.tracker import ExperimentTracker

tracker = ExperimentTracker()
run = tracker.start_run(name="gate_test", config={...})
tracker.log_metrics({'win_rate': 0.55, 'pf': 1.2})
tracker.end_run()
```

### 2. Risk Manager
```python
from vcp_backtest.risk_manager import RiskManager

rm = RiskManager(initial_capital=10000)
result = rm.check_can_open_position(position_value=2000)
if result.allowed:
    # 진입
```

### 3. Performance Attribution
```python
from analysis.attribution import PerformanceAttribution

attr = PerformanceAttribution(trades)
print(attr.full_report())  # Gate/Grade/Entry별 분석
```

### 4. Telegram 알림
```bash
# .env에 설정
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id
```

---

## 🔧 CLI Reference

```bash
# VCP 스캔
python run_scan.py --exchange binance --timeframe 4h

# 백테스트
python run_backtest.py backtest --start 2023-01-01 --end 2024-12-01
python run_backtest.py walkforward --train-months 6 --test-months 2
python run_backtest.py regime-compare  # Gate ON/OFF 비교

# Lead-Lag
python run_lead_lag.py --target BTC --max-lag 6 --use-llm

# 테스트
python -m tests.run_all

# 실험 관리
python experiments/tracker.py list
python experiments/tracker.py show {run_id}
```

---

## 📊 Version History

| Version | Date | Features |
|---------|------|----------|
| V1 | 2025-12 | Core VCP, Backtest, Lead-Lag |
| V2 | 2025-12-26 | 6개 백테스트 모듈 (Regime, Portfolio, Filters) |
| V3 | 2025-12-26 | Orchestrator, Risk Manager, Attribution, Tests |

---

*Generated: 2025-12-26 | ULTRATHINK Mode | Auto-Update Enabled*

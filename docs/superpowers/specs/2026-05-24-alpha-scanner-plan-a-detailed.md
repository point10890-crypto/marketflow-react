# Plan A 정밀 계획 보고서 — 헛시그널 차단 + 백테스트 인프라

**날짜**: 2026-05-24
**기반 spec**: [`2026-05-24-alpha-scanner-enhancement-design.md`](./2026-05-24-alpha-scanner-enhancement-design.md)
**상위 로드맵**: [`2026-05-24-alpha-scanner-implementation-report.md`](./2026-05-24-alpha-scanner-implementation-report.md)
**상태**: 구현 계획 — 사용자 승인 대기

---

## Executive Summary

Plan A 의 본질은 **"점수 모델이 진짜 수익을 예측하는가?"** 를 정량 측정할 수 있는 인프라를 구축하면서, 동시에 한국 시장 특유의 명백한 헛시그널을 즉시 차단하는 작업이다. 이 두 가지는 분리 불가 — 차단(Phase 1) 효과는 백테스트(Phase 2) 로만 입증 가능하고, 백테스트는 차단 적용 전후 비교가 있어야 의미 있다.

**Plan A 만 도입해도 standalone 가치:**
- 즉시 정확도 개선 (KIND 블랙리스트 매칭만으로 다음날 -10% 손실 사례 30~50% 차단)
- 1,922개 기존 run + 가격 데이터로 baseline expectancy_r/IC 즉시 측정 가능
- Plan B/C/D 도입하지 않아도 운영 가능 (LLM 의존성 0)

**예상 소요**: 4~6 작업일 (집중) / 1~1.5주 (분산)
**예상 비용**: 일회성 개발 + 운영 비용 $0 (KIND/KRX/내부 데이터만 사용, LLM 0회)
**위험도**: 낮음 (외부 의존성 적고, 결정적 룰만 사용)

---

## Plan A 의 정확한 목표

### 목표 (1) — 헛시그널 차단 (Phase 1)

한국 시장 특유의 5가지 헛시그널 패턴을 결정적 룰로 자동 차단:
- KIND 시장경보 (단기과열/투자주의/투자경고/투자위험)
- 외인+기관 동조 매수 부재 (한국 특유 추세 신호)
- 윗꼬리 비율 ≥ 0.5 (마감 시점 매도 압력)
- 신용잔고율 ≥ 5% (청산 트리거 위험)
- 얇은 유동성 급등 (거래대금 < 100억 + 등락률 ≥ +15%)

### 목표 (2) — 백테스트 인프라 (Phase 2)

1,922개 기존 scanner_runs + `daily_prices.csv` 를 활용한 정량 검증 인프라:
- **Expectancy (R)**: Van Tharp 공식으로 1R 당 기대 수익 계산
- **IC (Information Coefficient)**: Spearman correlation (alpha_score vs ret_5d) — 신호 예측력
- **Profit Factor**: 총 이익 / 총 손실
- **A/B 비교**: 강화 전 (기존 점수) vs 강화 후 (Phase 1 게이트 적용) 페어드 비교

### Success Criteria (Plan A 단독)

| 지표 | 임계값 | 측정 방법 |
|------|--------|----------|
| `expectancy_r` (baseline) | 측정 가능 | 기존 1,922 run 백테스트로 baseline 도출 |
| `expectancy_r` (강화 후) | baseline +0.10 이상 | Phase 1 게이트 적용 후 동일 백테스트 |
| `IC` (강화 후) | baseline +0.03 이상 | 페어드 비교 |
| `KIND 블랙리스트 매칭 사례` | ≥ 5건/주 | 일일 fetch + 캐시 검증 |
| `5개 게이트 단위 테스트` | 100% PASS | pytest |

→ 모든 임계 통과 시 Plan A 성공 → Plan B 진행 결정

---

## 작업 분해 — 5개 작업 단위

### 작업 1: KIND 블랙리스트 fetcher (반일, ~4시간)

**왜 이게 첫 작업**: 외부 데이터 의존성 검증부터 — XML 파싱이 실패하면 후속 작업 무의미.

#### 1-1. 신규 파일: `app/services/mirofish/blacklist.py` (~80줄)

```python
"""KIND 시장경보 자동 fetcher.

KRX 한국거래소의 시장경보 (투자주의/투자경고/투자위험/단기과열) 종목을
일일 fetch + 1시간 캐시.

References:
- KIND 공시 페이지: https://kind.krx.co.kr/investwarn/investattentwarnrisky.do
- XML 응답 스키마는 KIND 시스템 변경 가능 — 스키마 변경 감지 시 알림
"""
import json
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

import requests

logger = logging.getLogger('mirofish.blacklist')

CACHE_FILE = Path(os.path.dirname(os.path.abspath(__file__))) / '../../../data/kind_blacklist_latest.json'
CACHE_TTL_HOURS = 1
KIND_URL = 'https://kind.krx.co.kr/investwarn/investattentwarnrisky.do'

CategoryType = Literal['short_term_overheating', 'caution', 'alert', 'danger']
RiskLevel = Literal['high', 'medium', 'low', 'clean']


def fetch_kind_blacklist() -> list[dict]:
    """KIND XML/HTML 응답 fetch + 종목별 카테고리 파싱.

    Returns:
        [{'ticker': '005930', 'name': '삼성전자', 'categories': ['caution'],
          'designated_date': '2026-05-23', 'expiry_date': '2026-05-30'}]
    """
    # 실제 KIND 응답은 HTML/XML 혼합 — 정확한 스키마는 작업 1-3 에서 확인
    ...


def is_blacklisted(ticker: str) -> dict:
    """캐시 우선 조회. 캐시 만료 시 fetch.

    Returns:
        {'listed': bool,
         'categories': list[CategoryType],
         'risk_level': RiskLevel,
         'designated_date': str | None,
         'expiry_date': str | None}
    """
    ...
```

#### 1-2. 캐시 전략

- 파일 위치: `data/kind_blacklist_latest.json`
- TTL: 1시간 (재고 빈도 vs 응답 시간 trade-off)
- 캐시 schema:
  ```json
  {
    "fetched_at": "2026-05-24T10:00:00",
    "stocks": [
      {"ticker": "...", "name": "...", "categories": [...], "designated_date": "...", "expiry_date": "..."}
    ],
    "schema_version": 1
  }
  ```

#### 1-3. KIND 실제 응답 검증 (작업 시작 첫 30분)

먼저 본PC 에서 curl 로 실제 KIND 응답 받아 스키마 확인:
```bash
curl -A "Mozilla/5.0" -s "https://kind.krx.co.kr/investwarn/investattentwarnrisky.do" | head -200
```

응답이 HTML 인지 XML 인지, 종목코드 추출 정규식 패턴 결정. 이 단계 실패 시 (예: KRX 변경 / 차단) → 작업 1 일시 중단 + 대안 검토 (FnGuide 스크리너 활용 등).

#### 1-4. 테스트: `tests/services/mirofish/test_blacklist.py` (~10개 케이스)

```python
def test_is_blacklisted_returns_listed_when_in_caution(mock_kind_response):
    # KIND 응답에 005930 = "투자주의" 포함된 경우
    result = is_blacklisted('005930')
    assert result['listed'] is True
    assert 'caution' in result['categories']
    assert result['risk_level'] == 'low'

def test_is_blacklisted_returns_not_listed_for_clean_stock(mock_kind_response):
    result = is_blacklisted('000660')  # 응답에 없음
    assert result['listed'] is False

def test_cache_hit_skips_network_fetch(mock_kind_response, tmp_cache):
    # 캐시 fresh (mtime within 1h) → fetch 호출 안 됨
    ...

def test_cache_miss_triggers_fetch(mock_kind_response, tmp_cache):
    # 캐시 stale (mtime > 1h) → fetch 호출
    ...

def test_fetch_failure_falls_back_to_stale_cache(mock_kind_response_500, tmp_cache):
    # fetch 실패 시 7일 이내 stale 캐시는 유지 (fail-safe)
    ...

def test_schema_change_detection_logs_warning(mock_kind_unexpected_schema):
    # KIND 응답 포맷 변경 감지 시 logger.warning + 이전 캐시 유지
    ...

def test_risk_level_mapping():
    # danger > alert > caution > short_term_overheating 순
    ...

# ... 추가 케이스
```

---

### 작업 2: 5개 헛시그널 게이트 적용 (1일, ~8시간)

#### 2-1. 수정 파일: `app/services/mirofish/alpha_scanner.py`

`apply_false_signal_gates()` 함수 신규 + 점수 계산 직전 호출 추가.

위치: `alpha_scanner.py:1144~1176` 부근 (점수 계산 단계 직전).

```python
def apply_false_signal_gates(candidate: ScannerCandidate, market_data: dict) -> ScannerCandidate:
    """헛시그널 게이트 5단계 — 점수 계산 직전 적용.

    Args:
        candidate: 1차 스크리닝 통과 후보
        market_data: 일봉/수급/신용잔고 등 외부 데이터 dict

    Returns:
        강화된 candidate (alpha_score 변경 또는 rejection_reason 설정)
    """
    from app.services.mirofish.blacklist import is_blacklisted

    # Gate 1: KIND 블랙리스트 → 강제 제외
    bl = is_blacklisted(candidate.ticker)
    if bl['listed']:
        candidate.alpha_score = 0
        candidate.rejection_reason = f"KIND_blacklist:{','.join(bl['categories'])}"
        candidate.gates_failed = ['kind_blacklist']
        return candidate

    # Gate 2: 외인+기관 동조 매수 (5일 누적 NET) → +2점 가산
    supply = market_data.get('supply_5d', {})
    if supply.get('foreign_net', 0) > 0 and supply.get('institution_net', 0) > 0:
        candidate.alpha_score += 2
        candidate.gates_passed.append('foreign_inst_dual_buy')

    # Gate 3: 윗꼬리 헛돌파 → -5점 감점
    daily = market_data.get('daily_today', {})
    high = daily.get('high', candidate.current_price)
    low = daily.get('low', candidate.current_price)
    close = daily.get('close', candidate.current_price)
    if high > low:
        wick_ratio = (high - close) / (high - low)
        if wick_ratio >= 0.5:
            candidate.alpha_score -= 5
            candidate.gates_warned.append(f'upper_wick:{wick_ratio:.2f}')

    # Gate 4: 신용잔고율 위험 → 강제 제외
    credit = market_data.get('credit_balance', {})
    listed_shares = market_data.get('listed_shares', 0)
    if listed_shares > 0:
        credit_ratio = credit.get('balance_shares', 0) / listed_shares
        if credit_ratio >= 0.05:
            candidate.alpha_score = 0
            candidate.rejection_reason = f"credit_balance_risk:{credit_ratio:.3f}"
            candidate.gates_failed.append('credit_balance')
            return candidate

    # Gate 5: 얇은 유동성 급등 → -10점 감점
    if (candidate.trading_value < 10_000_000_000  # 100억원
        and candidate.change_pct >= 15):
        candidate.alpha_score -= 10
        candidate.gates_warned.append(f'thin_liquidity_surge:tv={candidate.trading_value:.0f},chg={candidate.change_pct:.1f}')

    return candidate
```

#### 2-2. Signal 모델 확장 — 게이트 결과 추적

`ScannerCandidate` 클래스에 신규 필드 (이미 있으면 재활용):
```python
@dataclass
class ScannerCandidate:
    # ... 기존 필드
    gates_passed: list[str] = field(default_factory=list)
    gates_warned: list[str] = field(default_factory=list)
    gates_failed: list[str] = field(default_factory=list)
    rejection_reason: str | None = None
```

→ 백테스트 시 어느 게이트가 어떤 효과 냈는지 측정 가능

#### 2-3. 환경 토글로 비활성 가능

```python
# .env
ENABLE_ALPHA_PHASE_1_GATES=1  # 0 으로 즉시 비활성
```

```python
def apply_false_signal_gates(candidate, market_data):
    if os.getenv('ENABLE_ALPHA_PHASE_1_GATES', '1').strip().lower() in ('0', 'false', 'no'):
        return candidate
    # ... 게이트 로직
```

#### 2-4. 데이터 소스 매핑

각 게이트가 필요한 데이터 + 현재 가져오는 방법:

| 게이트 | 데이터 | 현재 위치 | 추가 fetch 필요? |
|--------|--------|----------|----------------|
| KIND | KIND XML | (신규) `blacklist.py` | 작업 1 |
| 외인+기관 | `supply_5d.foreign_net`, `supply_5d.institution_net` | `all_institutional_trend_data.csv` (이미 일일 수집) | ❌ |
| 윗꼬리 | `daily.high/low/close` | `daily_prices.csv` (이미 수집) | ❌ |
| 신용잔고 | `credit_balance.balance_shares`, `listed_shares` | KRX 신용공여잔고 (일일 무료 공개) | ✅ 신규 fetcher |
| 얇은유동성 | `trading_value`, `change_pct` | 스캐너가 이미 사용 | ❌ |

작업 2 에 신용잔고 fetcher 도 포함:
```python
# app/services/mirofish/credit_balance.py (~40줄)
def fetch_credit_balance_data() -> dict[str, dict]:
    """KRX 신용공여잔고 일일 fetch.

    Returns:
        {ticker: {'balance_shares': int, 'balance_value': float, 'date': str}}
    """
    ...
```

#### 2-5. 테스트: `tests/services/mirofish/test_false_signal_gates.py` (~12개)

```python
def test_gate1_kind_blacklist_zeros_score(mock_kind):
    # ticker '999999' = caution 지정
    candidate = ScannerCandidate(ticker='999999', alpha_score=80, ...)
    result = apply_false_signal_gates(candidate, mock_market_data)
    assert result.alpha_score == 0
    assert result.rejection_reason.startswith('KIND_blacklist')

def test_gate2_foreign_inst_dual_buy_adds_2pts():
    candidate = ScannerCandidate(alpha_score=70)
    market_data = {'supply_5d': {'foreign_net': 100_000_000, 'institution_net': 50_000_000}}
    result = apply_false_signal_gates(candidate, market_data)
    assert result.alpha_score == 72
    assert 'foreign_inst_dual_buy' in result.gates_passed

def test_gate2_single_buyer_no_bonus():
    # 외인만 매수, 기관 매도 → 가산 없음
    market_data = {'supply_5d': {'foreign_net': 100_000_000, 'institution_net': -50_000_000}}
    result = apply_false_signal_gates(candidate, market_data)
    assert result.alpha_score == 70  # 가산 없음

def test_gate3_upper_wick_50pct_subtracts_5pts():
    candidate = ScannerCandidate(alpha_score=80)
    market_data = {'daily_today': {'high': 10000, 'low': 9000, 'close': 9500}}
    # wick = (10000-9500)/(10000-9000) = 0.5
    result = apply_false_signal_gates(candidate, market_data)
    assert result.alpha_score == 75

def test_gate4_credit_balance_5pct_zeros_score():
    candidate = ScannerCandidate(alpha_score=80)
    market_data = {'credit_balance': {'balance_shares': 5_000_000}, 'listed_shares': 100_000_000}
    # ratio = 5%
    result = apply_false_signal_gates(candidate, market_data)
    assert result.alpha_score == 0
    assert 'credit_balance_risk' in result.rejection_reason

def test_gate5_thin_liquidity_surge_subtracts_10pts():
    candidate = ScannerCandidate(alpha_score=85, trading_value=5_000_000_000, change_pct=18)
    market_data = {}
    result = apply_false_signal_gates(candidate, market_data)
    assert result.alpha_score == 75

def test_env_toggle_off_skips_all_gates(monkeypatch):
    monkeypatch.setenv('ENABLE_ALPHA_PHASE_1_GATES', '0')
    candidate = ScannerCandidate(alpha_score=80, ticker='blacklisted_ticker')
    result = apply_false_signal_gates(candidate, mock_market_data)
    assert result.alpha_score == 80  # 변동 없음

# ... 추가 케이스 (gate 순서, 조합, edge case)
```

---

### 작업 3: 백테스트 스크립트 (1.5일, ~12시간)

#### 3-1. 신규 파일: `scripts/backtest_alpha_signals.py` (~120줄)

```python
"""알파 스캐너 백테스트 — Plan A 의 수익성 검증 본체.

기존 1,922개 scanner_runs + daily_prices.csv 활용.
Van Tharp expectancy 공식 + Spearman IC + profit factor 측정.
"""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

logger = logging.getLogger('backtest_alpha')

SCANNER_RUNS_DIR = Path('data/admin_mirofish/scanner_runs')
DAILY_PRICES = Path('data/daily_prices.csv')

# Success thresholds (Plan A 검증 기준)
SUCCESS_THRESHOLDS = {
    'expectancy_r_min': 0.30,
    'IC_min': 0.08,
    'profit_factor_min': 1.5,
    'sample_size_min': 100,
    'delta_expectancy_r_min': 0.10,  # baseline 대비 개선폭
}


def backtest_alpha_signals(
    min_alpha: int = 70,
    days_held: int = 5,
    apply_phase1_gates: bool = False,
) -> dict:
    """1,922 run 백테스트.

    Args:
        min_alpha: alpha_score 임계값 (이상만 trade)
        days_held: 보유 기간 (영업일)
        apply_phase1_gates: False = baseline, True = Phase 1 게이트 적용 후

    Returns:
        {
            'win_rate': float,
            'expectancy_r': float,
            'profit_factor': float,
            'IC': float,
            'avg_return_pct': float,
            'mdd_pct': float,
            'sample_size': int,
            'thresholds_met': dict,  # 각 임계값 통과 여부
        }
    """
    # 1) 모든 run 로드
    runs = load_all_scanner_runs(SCANNER_RUNS_DIR)
    candidates = flatten_candidates(runs, min_alpha=min_alpha)

    # 2) Phase 1 게이트 적용 (옵션)
    if apply_phase1_gates:
        candidates = [c for c in candidates if not is_filtered_by_gates(c)]

    # 3) 각 candidate 의 N일 후 수익률 계산
    prices = load_daily_prices(DAILY_PRICES)
    trades = []
    for c in candidates:
        entry = get_price_at(prices, c.ticker, c.scan_date)
        exit_ = get_price_at(prices, c.ticker, c.scan_date + timedelta(days=days_held))
        if entry is None or exit_ is None:
            continue
        ret_pct = (exit_ - entry) / entry * 100
        trades.append({
            'ticker': c.ticker,
            'alpha_score': c.alpha_score,
            'entry': entry,
            'exit': exit_,
            'ret_pct': ret_pct,
        })

    if len(trades) < SUCCESS_THRESHOLDS['sample_size_min']:
        logger.warning(f"sample size too small: {len(trades)}")

    # 4) 메트릭 계산
    return compute_metrics(trades)


def compute_metrics(trades: list[dict]) -> dict:
    """Van Tharp expectancy + Spearman IC + profit factor."""
    returns = np.array([t['ret_pct'] for t in trades])
    scores = np.array([t['alpha_score'] for t in trades])

    wins = returns[returns > 0]
    losses = returns[returns <= 0]

    win_rate = len(wins) / len(returns) if len(returns) > 0 else 0
    avg_win = wins.mean() if len(wins) > 0 else 0
    avg_loss = abs(losses.mean()) if len(losses) > 0 else 0.01  # divide-by-zero 방지

    # Expectancy in R units (1R = avg_loss, normalize)
    expectancy_r = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_loss

    profit_factor = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float('inf')

    # IC (Spearman)
    ic, _ = spearmanr(scores, returns) if len(scores) > 1 else (0, None)

    # MDD (Max Drawdown) — equity curve
    equity_curve = np.cumsum(returns)
    mdd = compute_mdd(equity_curve)

    # 임계 통과 여부
    thresholds_met = {
        'expectancy_r': expectancy_r >= SUCCESS_THRESHOLDS['expectancy_r_min'],
        'IC': ic >= SUCCESS_THRESHOLDS['IC_min'],
        'profit_factor': profit_factor >= SUCCESS_THRESHOLDS['profit_factor_min'],
        'sample_size': len(returns) >= SUCCESS_THRESHOLDS['sample_size_min'],
    }

    return {
        'win_rate': float(win_rate),
        'expectancy_r': float(expectancy_r),
        'profit_factor': float(profit_factor),
        'IC': float(ic) if ic is not None else 0,
        'avg_return_pct': float(returns.mean()),
        'mdd_pct': float(mdd),
        'sample_size': len(returns),
        'thresholds_met': thresholds_met,
    }


def run_ab_comparison(min_alpha=70, days_held=5) -> dict:
    """A/B 비교 — baseline (Phase 1 없음) vs 강화 (Phase 1 적용)."""
    baseline = backtest_alpha_signals(min_alpha=min_alpha, days_held=days_held, apply_phase1_gates=False)
    enhanced = backtest_alpha_signals(min_alpha=min_alpha, days_held=days_held, apply_phase1_gates=True)

    delta = {
        'delta_expectancy_r': enhanced['expectancy_r'] - baseline['expectancy_r'],
        'delta_IC': enhanced['IC'] - baseline['IC'],
        'delta_win_rate': enhanced['win_rate'] - baseline['win_rate'],
        'delta_profit_factor': enhanced['profit_factor'] - baseline['profit_factor'],
    }

    success = (
        delta['delta_expectancy_r'] >= SUCCESS_THRESHOLDS['delta_expectancy_r_min']
        and enhanced['thresholds_met']['expectancy_r']
        and enhanced['thresholds_met']['IC']
    )

    return {
        'baseline': baseline,
        'enhanced': enhanced,
        'delta': delta,
        'plan_a_success': success,
    }


if __name__ == '__main__':
    result = run_ab_comparison()
    print(json.dumps(result, indent=2, default=str))
    # 결과 저장
    output_path = Path('data/alpha_backtest_initial.json')
    output_path.write_text(json.dumps(result, indent=2, default=str))
    logger.info(f"Plan A success: {result['plan_a_success']}")
```

#### 3-2. 백테스트 수학 — Expectancy / IC / Profit Factor

**Expectancy (Van Tharp)**:
- R = 평균 손실 (1R 단위로 normalize)
- Expectancy = (`win_rate` × `avg_win` - `loss_rate` × `avg_loss`) / `avg_loss`
- 의미: 1R 위험 당 기대 수익. 0.3R 이상이면 통계적 우위.

**IC (Information Coefficient)**:
- Spearman rank correlation (alpha_score 순위 vs 미래 수익률 순위)
- 0.05 이상 = 통계적 유의, 0.08 이상 = 운영 가능 수준
- 0 = 신호 무력, 음수 = 신호 역방향 (강화 시 더 나쁨)

**Profit Factor**:
- 총 이익 / 총 손실 (절대값)
- 1.5 이상 = 운영 가능, 2.0 이상 = 우수

#### 3-3. 테스트: `tests/scripts/test_backtest_alpha.py` (~10개)

```python
def test_compute_metrics_basic():
    trades = [
        {'alpha_score': 80, 'ret_pct': 5.0},
        {'alpha_score': 75, 'ret_pct': -2.0},
        {'alpha_score': 70, 'ret_pct': 3.0},
        {'alpha_score': 90, 'ret_pct': 8.0},
    ]
    metrics = compute_metrics(trades)
    assert 0 < metrics['win_rate'] < 1
    assert metrics['IC'] > 0  # score 높을수록 ret 높음

def test_compute_metrics_handles_zero_losses():
    # 모든 trade 가 이익 → profit_factor = inf
    trades = [{'alpha_score': 80, 'ret_pct': 5.0}] * 10
    metrics = compute_metrics(trades)
    assert metrics['profit_factor'] == float('inf')

def test_ab_comparison_baseline_vs_enhanced():
    # mock scanner_runs 로 baseline + enhanced 둘 다 측정
    ...

def test_threshold_failure_detection():
    # expectancy_r < 0.3 → plan_a_success = False
    ...

# ... 추가 케이스
```

#### 3-4. 실행 방법

```bash
# 1회성 (Plan A 적용 전 baseline 측정)
PYTHON="/c/bitman_marketfloww/.venv/Scripts/python.exe"
cd /c/bitman_marketfloww
PYTHONIOENCODING=utf-8 "$PYTHON" scripts/backtest_alpha_signals.py
```

출력:
```json
{
  "baseline": {"expectancy_r": 0.18, "IC": 0.04, "sample_size": 1850, ...},
  "enhanced": {"expectancy_r": 0.32, "IC": 0.09, "sample_size": 1430, ...},
  "delta": {"delta_expectancy_r": 0.14, "delta_IC": 0.05},
  "plan_a_success": true
}
```

---

### 작업 4: 일일 백테스트 cron (반일, ~4시간)

#### 4-1. 수정 파일: `scheduler.py`

신규 함수 + 스케줄 등록:

```python
def run_alpha_backtest_daily():
    """일일 23:00 KST — 알파 스캐너 백테스트 + 7일 rolling.

    실패 시 텔레그램 알림 (개인 봇만).
    """
    logger.info("=" * 60)
    logger.info("📊 알파 스캐너 백테스트 시작")
    logger.info("=" * 60)
    try:
        from scripts.backtest_alpha_signals import run_ab_comparison
        result = run_ab_comparison()

        # 결과 저장
        output_path = Path(Config.DATA_DIR) / 'alpha_backtest_daily.json'
        output_path.write_text(json.dumps(result, indent=2, default=str))

        # 7일 rolling
        rolling = compute_rolling_7d_metrics()
        rolling_path = Path(Config.DATA_DIR) / 'alpha_backtest_rolling_7d.json'
        rolling_path.write_text(json.dumps(rolling, indent=2))

        # 임계 미달 알림
        if rolling['avg_expectancy_r'] < 0.15:
            send_telegram(
                f"⚠️ 알파 스캐너 7일 expectancy_r = {rolling['avg_expectancy_r']:.2f} < 0.15. 강화 효과 의심.",
                channel=False  # 개인봇만
            )

        return True
    except Exception as e:
        logger.exception("백테스트 실패")
        return False
```

스케줄 등록 (line 3000 부근):
```python
schedule.every().day.at("23:00").do(
    self._with_record(run_alpha_backtest_daily, 'alpha_backtest_daily',
                      max_retries=2, retry_delay=600)
)
```

#### 4-2. 7일 rolling 메트릭

```python
def compute_rolling_7d_metrics() -> dict:
    """최근 7일 일일 백테스트 결과 평균."""
    daily_files = sorted(Path(Config.DATA_DIR).glob('alpha_backtest_*.json'))[-7:]
    results = [json.loads(f.read_text()) for f in daily_files]

    if not results:
        return {'avg_expectancy_r': 0, 'avg_IC': 0, 'sample_count': 0}

    return {
        'avg_expectancy_r': np.mean([r['enhanced']['expectancy_r'] for r in results]),
        'avg_IC': np.mean([r['enhanced']['IC'] for r in results]),
        'avg_win_rate': np.mean([r['enhanced']['win_rate'] for r in results]),
        'sample_count': len(results),
        'period': f"{daily_files[0].stem} ~ {daily_files[-1].stem}",
    }
```

#### 4-3. miniPC 배포 시 고려사항

- `scheduler.py` 변경 → scp + 데몬 재시작 필요 (로또 작업 시 검증된 절차)
- 23:00 KST = miniPC 시간 — daemon 의 timezone 확인 (운영 머신 기준)
- 백테스트 실행 중 다른 task 와 충돌 X (백테스트는 read-only, 다른 task 는 23:00 에 없음)

---

### 작업 5: 통합 검증 + 1일 dry-run (1일, ~8시간)

#### 5-1. 단위 테스트 전체 PASS 확인

```bash
PYTHON="/c/bitman_marketfloww/.venv/Scripts/python.exe"
cd /c/bitman_marketfloww
PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/services/mirofish/ tests/scripts/test_backtest_alpha.py -v
```

Expected: ~30+ tests PASS.

#### 5-2. miniPC 배포

```bash
# 변경 파일 scp
scp app/services/mirofish/blacklist.py 'dynas@192.168.55.103:C:/bitman_marketfloww/app/services/mirofish/blacklist.py'
scp app/services/mirofish/credit_balance.py 'dynas@192.168.55.103:C:/bitman_marketfloww/app/services/mirofish/credit_balance.py'
scp app/services/mirofish/alpha_scanner.py 'dynas@192.168.55.103:C:/bitman_marketfloww/app/services/mirofish/alpha_scanner.py'
scp scripts/backtest_alpha_signals.py 'dynas@192.168.55.103:C:/bitman_marketfloww/scripts/backtest_alpha_signals.py'
scp scheduler.py 'dynas@192.168.55.103:C:/bitman_marketfloww/scheduler.py'
```

#### 5-3. miniPC 데몬 재시작

로또 작업에서 검증된 절차 재사용:
```bash
ssh dynas@192.168.55.103 'powershell -Command "
$daemons = Get-CimInstance Win32_Process -Filter \"Name='\''python.exe'\''\" | Where-Object { $_.CommandLine -like '\''*scheduler.py*--daemon*'\'' };
$daemons | ForEach-Object { Stop-Process -Id $_.ProcessId -Force };
Start-Sleep -Seconds 3;
Remove-Item C:\bitman_marketfloww\data\.scheduler.lock -Force -ErrorAction SilentlyContinue;
Start-ScheduledTask -TaskName MarketFlow-Scheduler"'
```

#### 5-4. 강제 발화 — 1회 백테스트 실행

```bash
ssh dynas@192.168.55.103 'powershell -Command "
cd C:\bitman_marketfloww
$env:PYTHONIOENCODING=\"utf-8\"
.\.venv\Scripts\python.exe scripts\backtest_alpha_signals.py"'
```

Expected: JSON 결과 출력 — `plan_a_success: true` 여부 확인.

#### 5-5. Plan A Success Criteria 검증

| 항목 | 기준 | 검증 방법 |
|------|------|----------|
| `expectancy_r` (enhanced) | ≥ 0.30 | 백테스트 출력 |
| `delta_expectancy_r` | ≥ 0.10 | 백테스트 출력 |
| `IC` (enhanced) | ≥ 0.08 | 백테스트 출력 |
| `delta_IC` | ≥ 0.03 | 백테스트 출력 |
| 단위 테스트 | 100% PASS | pytest |
| KIND 매칭 사례 | ≥ 5건 | `data/kind_blacklist_latest.json` |

#### 5-6. 결정 분기

- **모든 항목 통과** → Plan A 성공. 운영 적용 + Plan B 진행 결정 사용자에게 요청.
- **delta_expectancy_r < 0.10** → 강화 효과 부족. 게이트별 기여도 분석 후 부분 채택 검토.
- **단위 테스트 일부 실패** → 해당 게이트만 fix, 나머지는 적용.
- **KIND 매칭 0건** → fetch 로직 확인 (XML 스키마 변경 의심).

---

## 위험 + 완화

| 위험 | 가능성 | 영향 | 완화 |
|------|--------|------|------|
| KIND XML 스키마 변경 | 중 | 중 (블랙리스트 무력화) | 응답 검증 + 7일 stale 캐시 fallback + 텔레그램 알림 |
| 신용잔고 데이터 fetch 실패 | 중 | 작음 (5개 게이트 중 1개) | 게이트 4 skip + warning 로그 |
| 백테스트 결과가 기대 미달 | 중 | 큼 (R&D 임시 보류) | 게이트별 기여도 분석 → 효과 있는 게이트만 부분 채택 |
| 1,922 run 중 일부 ticker 가 daily_prices.csv 에 없음 | 중 | 작음 (sample 감소) | 결측 처리 + sample_size 출력에서 명확화 |
| 데몬 재시작 후 백테스트 cron 등록 누락 | 낮음 | 중 (자동 검증 안 됨) | 재시작 후 scheduler.log 에서 "alpha_backtest_daily" 등록 확인 |

---

## 일정 (작업일 기준)

| Day | 작업 |
|-----|------|
| Day 1 (오전) | 작업 1-3: KIND 실제 응답 검증 + XML 파싱 확정 |
| Day 1 (오후) | 작업 1: blacklist.py 구현 + 테스트 작성 |
| Day 2 | 작업 2: 5게이트 적용 + 테스트 + credit_balance fetcher |
| Day 3 | 작업 3: 백테스트 스크립트 (1.5일 중 첫째 날) |
| Day 4 (오전) | 작업 3: 백테스트 마무리 + 테스트 |
| Day 4 (오후) | 작업 4: cron 등록 + rolling 메트릭 |
| Day 5 (오전) | 작업 5: 통합 검증 + miniPC 배포 |
| Day 5 (오후) | 작업 5: 1회 백테스트 실행 + Success Criteria 검증 + 결과 보고 |

→ **집중 5 작업일**. 회의/장애 고려 1.5주.

---

## 다음 단계 (Plan A 후속)

1. **Plan A 성공 시** (Success Criteria 4개 모두 통과):
   - 운영 적용 (Telegram 발송 등 기존 흐름 유지)
   - 매일 23:00 백테스트 자동 실행
   - 사용자에게 Plan B 진행 의사 확인 → writing-plans 로 Plan B 정식 plan 작성

2. **Plan A 부분 실패 시**:
   - 어느 게이트가 효과 있고 어느 게이트가 효과 없는지 분석
   - 효과 있는 게이트만 운영 적용
   - 효과 없는 게이트는 `feedback_alpha_phase_1_gate_N_ineffective_YYYYMMDD.md` 메모

3. **Plan A 전체 실패 시** (예: delta_expectancy_r < 0 — 강화 후 더 나빠짐):
   - 모든 게이트 revert
   - 원인 분석 보고서 작성
   - spec v3 재설계 검토

---

## 사용자 결정 필요 (Plan A 시작 전)

다음 항목 confirm 필요:

1. **Plan A 시작 OK** — 위 일정대로 진행
2. **데이터 소스 우선순위** — KIND XML 응답 검증 시 차단/접근 불가하면 어떻게? (a) 작업 1 일시 중단 후 대안 검토, (b) FnGuide 스크리너 대체, (c) Plan A 전체 보류
3. **백테스트 임계값 조정 의향** — `expectancy_r >= 0.30` / `IC >= 0.08` 이 너무 빡빡하거나 느슨하다고 판단되면 사용자 의견
4. **운영 적용 시점** — Plan A Success Criteria 통과 즉시 vs 1주 dry-run 후 vs 사용자 수동 승인 후

---

## 부록: 변경 파일 전체 목록

### 신규 파일 (5개)
- `app/services/mirofish/blacklist.py` (~80줄)
- `app/services/mirofish/credit_balance.py` (~40줄)
- `scripts/backtest_alpha_signals.py` (~120줄)
- `tests/services/mirofish/test_blacklist.py` (~10 케이스)
- `tests/services/mirofish/test_false_signal_gates.py` (~12 케이스)
- `tests/services/mirofish/test_credit_balance.py` (~5 케이스)
- `tests/scripts/test_backtest_alpha.py` (~10 케이스)

### 수정 파일 (2개)
- `app/services/mirofish/alpha_scanner.py` — `apply_false_signal_gates()` 호출 추가, Signal 모델 확장 (~50줄 추가)
- `scheduler.py` — `run_alpha_backtest_daily()` + schedule 등록 (~30줄 추가)

### 신규 데이터 파일 (자동 생성)
- `data/kind_blacklist_latest.json`
- `data/credit_balance_latest.json`
- `data/alpha_backtest_initial.json` (1회성, baseline 측정)
- `data/alpha_backtest_daily.json` (매일 자동)
- `data/alpha_backtest_rolling_7d.json` (7일 평균)

### 환경변수 신규 (1개)
- `ENABLE_ALPHA_PHASE_1_GATES=1` (기본 활성, 0 으로 즉시 비활성)

# 알파 스캐너 강화 R&D — 설계 문서

**날짜**: 2026-05-24
**상태**: 설계 (사용자 검토 대기)
**다음 단계**: writing-plans 스킬 → 구현 plan 작성

## Goal

매주 5회 자동 실행 중인 MiroFish 알파 스캐너의 **정확도 (헛시그널 차단)** 와 **분석 깊이 (매매안 자동 생성)** 를 강화한다. 단순 종목 리스트가 아니라 진입가/손절가/목표가가 검증된 매매안 JSON 까지 자동 산출.

## Architecture

5-Phase 단계적 적용. 각 phase 는 독립 commit + 백테스트 검증 + 환경 토글로 즉시 비활성 가능. 기존 인프라 (alpha_scanner.py, MultiAIConsensusScreener, GraphRAG, position_sizer, FastMCP server) 를 90% 재활용. 신규 인프라는 최소화.

## Tech Stack

- Python 3.13, FastMCP, sqlite3, requests, asyncio
- LLM: Gemini 2.5 Flash (기존), GPT-4o (기존 — 새 모델 추가 없음)
- 백테스트: pandas + numpy (기존 us_market/backtest_engine.py 패턴 재활용; vectorbt 는 옵션)
- 한국 데이터: KRX (외인/기관 수급), KIND (시장경보), OpenDART (공시), Naver Finance (뉴스)

---

## Context — 왜 필요한가

### 현재 알파 스캐너의 한계

1. **헛시그널이 통과함**: alpha_score 100점이어도 다음날 -10% 되는 종목이 있음. 단기과열/투자경고/윗꼬리 등 한국 시장 특유의 패턴이 점수 모델에 반영 안 됨.
2. **분석 깊이가 얕음**: TOP 3 만 GraphRAG (Gemini deep) 분석. 나머지는 deterministic score 만 — "왜 알파인가" 가 사용자에게 보이지 않음.
3. **매매안이 없음**: 종목 리스트 + Telegram 알림만 제공. 사용자가 "그래서 얼마에 사고 얼마에 손절?" 을 매번 수동 판단.
4. **검증 인프라 부재**: 1,922회 누적 실행이 있지만 "alpha_score 가 진짜 미래 수익을 예측하는가?" 를 정량 측정하는 코드 없음. LLM hallucination 검증 불가.

### 사용자 목적 (확정)

- **정확도 강화**: 고스코어인데 헛시그널인 종목 제거 (input side)
- **분석 권장안**: 포지션/R-multiple 까지 검증된 구체 매매안 (output side)
- **MCP R&D**: 분석 자동화 도구를 MCP 형태로 모듈화. 외부 LLM (Claude/GPT) 클라이언트가 호출하여 사용 가능

---

## 딥리서치 7건 핵심 종합

| Research | 결과 |
|----------|------|
| **A. Multi-LLM Trading 패턴** | 추가 모델 도입은 ROI 낮음. **Selective Consensus** (교집합 confidence 상향/단독 하향) 가 가장 효율 |
| **B. 알파 스캐너 내부 코드** | alpha_score = `Alpha - 0.55·Risk + 신뢰도조정`. 게이트 = `alpha≥70 AND risk≤45`. 12개 MCP tool 이미 존재. 데이터는 모두 수집 중 (가격/뉴스/DART/수급/VCP/종가) |
| **C. 매매안 R-Multiple 패턴** | `PositionSizer.calculate()` 이미 존재. 고정 -3% 손절 → ATR/swing_low 기반 보강 필요. **가격은 코드, thesis 만 LLM** (hallucination 차단) |
| **D. 한국 시장 특화** | 즉시 채택 TOP 3: ① 외인+기관 동시 순매수 5일, ② **KIND 시장경보 블랙리스트**, ③ O'Neil 가중 RS. 미국식 PCR/다크풀 신호는 KR 무효 |
| **E. 백테스트 인프라** | `data/admin_mirofish/scanner_runs/` 1,922개 run + `daily_prices.csv` 1.5M행 → 즉시 백테스트 가능. 메트릭: **Expectancy(R), IC, Profit Factor**. 임계값: `expectancy_r≥0.20`, `IC≥0.05`, `sample≥100` |
| **F. MCP 디자인** | 4-part docstring (한 줄/When to use/When NOT/Returns). 중간 granularity + orchestrator 1개. `alpha_*` namespacing |
| **G. 유사 운영 시스템** | Bloomberg ASKB: LLM 은 보조용, 결정적 모델 본체. **소스별 신뢰 가중치**, **신호별 단독 백테스트 공개**, **점수 항목별 회귀 테스트** 즉시 적용 |

---

## 5-Phase 설계 — 단계적 적용

### Phase 1: 헛시그널 즉시 차단 (Quick Win)

**왜 1순위**: 가장 적은 코드로 가장 큰 정확도 개선. 한국 시장 특화 데이터를 활용해 명백한 헛시그널을 자동 제거.

**적용 항목** (`app/services/mirofish/alpha_scanner.py:1144~1176` 점수 계산 직전 게이트):

| 게이트 | 조건 | 데이터 소스 | 효과 |
|--------|------|------------|------|
| KIND 블랙리스트 | KIND 시장경보 (`investwarn`/`caution`/`alert`/`danger`) / 단기과열 매칭 시 | `https://kind.krx.co.kr/investwarn/investattentwarnrisky.do` (XML, 일일 무료) | alpha_score → 0 (강제 제외) |
| 외인+기관 동조 매수 | 5일 누적 외인_순매수 > 0 AND 기관_순매수 > 0 | `all_institutional_trend_data.csv` (이미 수집 중, 5일 누적 NET) | alpha_score += 2 |
| 윗꼬리 헛돌파 | (고가-종가)/(고가-저가) ≥ 0.5 | `daily_prices.csv` (이미 수집 중) | alpha_score -= 5 |
| 신용잔고율 위험 | 신용잔고 ≥ 발행주식수 5% | KRX 신용공여잔고 (일일 공개) | alpha_score → 0 (제외) |
| 얇은 유동성 급등 | 거래대금 < 100억 AND 등락률 ≥ +15% | KRX 시세 (스캐너가 이미 사용 중) | alpha_score -= 10 |

**신규 파일**:
- `app/services/mirofish/blacklist.py` — KIND XML 일일 fetch + 캐시 (1h TTL)
- `data/kind_blacklist_latest.json` — 캐시 결과 저장

**수정 파일**:
- `app/services/mirofish/alpha_scanner.py` — 점수 계산 함수에 게이트 호출 추가

### Phase 2: 백테스트 인프라 (수익 확률성 정량 측정)

**왜 2순위**: Phase 1 효과를 정량 측정해야 후속 phase 들의 가치도 입증 가능. 검증 없이 추가 강화 = overfitting 위험.

**핵심 스크립트** (`scripts/backtest_alpha_signals.py`, ~80줄):
```python
def backtest_alpha_signals(min_alpha=70, days_held=5) -> dict:
    """기존 1,922 run.json + daily_prices.csv 활용.

    Returns:
        {
            'win_rate': float,         # 단순 승률 %
            'expectancy_r': float,     # Van Tharp expectancy (R 단위)
            'profit_factor': float,    # 이익/손실 비
            'IC': float,               # Spearman alpha_score vs ret_5d
            'sample_size': int,
            'avg_return_pct': float,
            'mdd_pct': float,
        }
    """
```

**메트릭 임계값** (Research E):
- `expectancy_r ≥ 0.20` (1R 대비 0.2R 기대수익)
- `IC ≥ 0.05` (통계적 유의)
- `Profit Factor ≥ 1.4`
- `sample_size ≥ 100` (의미 있는 표본)

**A/B 비교**:
- 기존 점수 vs 강화 점수를 같은 run 에 병기
- 동일 종목 페어드 비교 → `delta_expectancy > 0` 확인

**일일 cron**:
- 매일 23:00 KST 자동 백테스트 → `data/alpha_backtest_daily.json` 저장
- 7일 rolling 결과 → 텔레그램 알림 (개인 봇만)

### Phase 3: 정밀화 — Selective Consensus + 섹터 RS

**왜 3순위**: Phase 1+2 가 동작한 후 미세 조정. 더 적은 효과지만 누적되면 큼.

**3-A. Selective Consensus 가중치 명시** (`engine/llm_analyzer.py:MultiAIConsensusScreener._build_consensus`):
```python
# 현재: 단순 dict merge
# 변경: 명시 가중치
def _build_consensus(picks_by_model):
    intersection = G ∩ O                      # Gemini ∩ OpenAI
    for ticker in intersection:
        confidence *= 1.20                    # 교집합 → confidence +20%
    for ticker in G ^ O:                      # 단독 (XOR)
        confidence *= 0.70                    # 단독 → -30%
```

**3-B. 섹터 상대강도 컬럼** (Signal 모델 + alpha_scanner):
```python
# Signal 모델 신규 필드
sector_rs: float          # O'Neil 가중 RS = 0.4·R_3m + 0.2·R_6m + 0.2·R_9m + 0.2·R_12m, 1~99 백분위
sector_excess_change: float  # 종목 등락률 - 섹터 평균 등락률
sector_consistency: str   # "leading" | "in_line" | "lagging"

# 점수 반영
if sector_rs >= 80 and sector_excess_change > 2: alpha_score += 3
if sector_rs < 30: alpha_score -= 5
```

**3-C. 가격 마디가 회피** (선택):
- 종가가 라운드 넘버 (천원, 만원) 직하 1% 이내 → alpha_score -= 2 (가짜 돌파 가능성)

### Phase 4: 신규 MCP tool 4개 + Orchestrator

**왜 4순위**: 외부 LLM 클라이언트가 사용할 도구 노출. Phase 1~3 로직이 안정화된 후 wrapping.

**기존 12개 도구 유지 + 신규 4개**:

#### `alpha_check_blacklist(ticker: str) -> dict`
```python
"""한국 KRX 시장경보/단기과열 블랙리스트 매칭 검사.

When to use: 알파 스캐너 후보 종목의 헛시그널 위험 사전 확인 시.
When NOT to use: 미국/해외 종목 (KIND 는 한국 거래소만).
Returns: {
    'listed': bool,
    'categories': list[str],  # ['investwarn', 'short_term_overheating', 'caution']
    'risk_level': str,        # 'high' | 'medium' | 'low' | 'clean'
    'expiry_date': str | None,
}
"""
```

#### `alpha_sector_rs(ticker: str, period: str = '12m') -> dict`
```python
"""O'Neil 가중 RS 계산 — 종목의 섹터 내 상대강도.

When to use: 종목이 섹터 동조 상승인지 단독 알파인지 판별 시.
When NOT to use: 신규 상장 3개월 미만 종목 (12개월 데이터 부족).
Returns: {
    'rs_rating': int,             # 1~99 백분위
    'sector': str,                # KRX 섹터 코드 (G07 등)
    'sector_excess_change': float,
    'consistency': str,           # 'leading' | 'in_line' | 'lagging'
}
"""
```

#### `alpha_generate_trade_plan(ticker: str, signal: dict) -> dict`
```python
"""ATR + R-multiple 매매안 JSON 생성.

When to use: 알파 통과 종목의 구체 매매안 (진입/손절/목표/포지션) 필요 시.
When NOT to use: 종가베팅 V2 의 Signal 객체가 이미 있는 경우 (`signal.to_trade_plan()` 사용).
Returns: 아래 'Trade Plan JSON 스키마' 참조
"""
```

#### `alpha_deep_dive(ticker: str) -> dict` ← **Orchestrator**
```python
"""단일 종목 종합 분석 — 알파 발굴 워크플로우 1-call.

When to use: 외부 LLM 클라이언트 (Claude Desktop, ChatGPT) 가 종목 하나에 대해
            모든 알파 분석을 한 번에 받고 싶을 때.
When NOT to use: 다수 종목 배치 처리 (대신 list_recent_scanner_runs).
Returns: {
    'ticker': str,
    'alpha_check': {...},          # alpha_check_blacklist 결과
    'sector_rs': {...},            # alpha_sector_rs 결과
    'consensus': {...},            # multi-AI consensus (기존 도구 활용)
    'evidence': {                  # 기존 get_kiwoom_quote + get_kiwoom_institution_trend + get_dart_disclosures 통합
        'news': [...], 'supply': {...}, 'disclosures': [...]
    },
    'trade_plan': {...},           # alpha_generate_trade_plan 결과
    'thesis': str,                 # ← LLM 자연어 (선택)
    'confidence': float,           # ← LLM 평가
}
"""
```

**MCP 도구 명세 규칙** (모든 신규 도구):
- 4-part docstring (한 줄 / When to use / When NOT to use / Returns)
- `Annotated[type, Field(description=..., ge=..., le=...)]` input 스키마
- `alpha_*` namespace prefix
- `ToolError("...")` 로 actionable 에러 메시지
- Timeout 30초 강제

### Phase 5: 회귀 테스트 + 1주 dry-run

**왜 5순위**: 강화 후 회귀 감지 인프라. Phase 1~4 안정화의 안전망.

**5-A. 점수 항목별 회귀 테스트** (`tests/test_scorer_factors.py`):
- `test_news_score_3pts_when_breakout_news_present`
- `test_supply_score_2pts_when_both_foreign_and_institution_buy_5d`
- `test_kind_blacklist_zeros_alpha_score`
- `test_sector_rs_high_adds_3pts`
- `test_upper_wick_subtracts_5pts`
- ... 각 점수 분기별 fixture + 단위 테스트 (총 15~20개)

**5-B. 1주 dry-run** (`scripts/dry_run_alpha_enhancement.py`):
- 7일 동안 강화 코드 실행하되 **실제 Telegram 발송은 X**
- 매매안 JSON 만 `data/alpha_dry_run_YYYYMMDD.json` 누적
- 7일 후 Phase 2 백테스트로 효과 측정
- 임계값 미달 시 자동 `git revert` 메모

---

## Trade Plan JSON 스키마

LLM hallucination 차단을 위한 엄격한 가드 (Research C, G 결합):

```json
{
  "ticker": "005930",
  "name": "삼성전자",
  "signal_date": "2026-05-24",
  "grade": "A",

  "thesis": "외인+기관 5일 동시 순매수, DART 자사주 공시, 섹터 RS 1.7σ, KIND 블랙리스트 미해당",
  "confidence": 0.72,

  "entry": {
    "price": 78000,
    "type": "next_open",
    "valid_until": "2026-05-26"
  },
  "stop": {
    "price": 75600,
    "method": "atr_1.5",
    "loss_pct": -3.08
  },
  "targets": [
    {"price": 80400, "r_multiple": 1.0, "action": "partial_50pct"},
    {"price": 82800, "r_multiple": 2.0, "action": "partial_30pct"},
    {"price": 85200, "r_multiple": 3.0, "action": "trail_stop"}
  ],

  "risk_per_share": 2400,
  "position_size_pct": 8.3,
  "max_hold_days": 10,

  "invalidation": "75600 종가 이탈 시 즉시 청산",
  "evidence_sources": [
    "KIND_2026-05-24",
    "KRX_dailysupply_2026-05-23",
    "OpenDART_2026-05-22",
    "ATR_14"
  ],
  "disclaimer": "추천안일 뿐, 매매 결정은 사용자 책임"
}
```

**책임 분담** (hallucination 차단):
- **코드가 계산**: `entry.price`, `stop.price`, `targets.*.price`, `risk_per_share`, `position_size_pct`, `evidence_sources`
- **LLM 이 생성**: `thesis` (200자 이내), `confidence` (0~1), `stop.method 선택` (atr_1.5 | swing_low | ma20)
- **템플릿**: `invalidation`, `disclaimer`

**호가단위 라운딩** (한국 시장):
- 1천원 미만: 1원
- 1천~5천원: 5원
- 5천~1만원: 10원
- 1만~5만원: 50원
- 5만~10만원: 100원
- 10만~50만원: 500원
- 50만원 이상: 1000원

---

## 데이터 흐름

```
[기존] alpha_scanner.create_scanner_run() — 5회/일 자동
   └─ Base alpha (가격/거래대금/이평선)
   └─ Add-on alpha (스크리너/VCP/종가)
   └─ 최종 alpha = Alpha - 0.55*Risk + 신뢰도

[Phase 1 신규] 헛시그널 게이트 (alpha_scanner 내부)
   ├─ KIND 블랙리스트 매칭 → 강제 제외
   ├─ 윗꼬리/신용잔고/얇은유동성 → 감점
   └─ 외인+기관 동조 → 가산

[Phase 3 신규] Selective Consensus + 섹터 RS
   ├─ Multi-AI Consensus 가중치 명시
   └─ Signal.sector_rs 컬럼 추가

[기존] auto_runner 게이트 (alpha≥70 AND risk≤45)
   └─ TOP 30 → Workflow GraphRAG TOP 3 (Gemini deep)

[Phase 4 신규] alpha_deep_dive orchestrator
   └─ 외부 LLM 클라이언트 호출 시
       ├─ alpha_check_blacklist
       ├─ alpha_sector_rs
       ├─ (기존) get_kiwoom_institution_trend / get_dart_disclosures
       └─ alpha_generate_trade_plan
   └─ 통합 JSON 반환

[기존 확장] Telegram 발송
   └─ 매매안 JSON 포함 (사용자 친화 포맷)

[Phase 2 신규] 일일 백테스트 cron
   └─ data/alpha_backtest_daily.json
```

---

## 테스트 / 검증 / 롤백 전략

### 테스트 매트릭스

| Phase | 단위 테스트 | 통합 테스트 | 라이브 검증 |
|-------|------------|------------|------------|
| 1 | KIND fetch + 5개 게이트 각 분기 (~10개) | scanner_run() 전후 비교 | 1일 dry-run, 헛시그널 제거 비율 측정 |
| 2 | backtest 함수 unit (~5개) | 1,922 run 전체 백테스트 → 메트릭 확인 | A/B 비교 dashboard |
| 3 | Selective Consensus 가중치 (~5개), Sector RS 계산 (~5개) | MultiAIConsensusScreener.screen_candidates() 회귀 | Phase 2 백테스트로 효과 측정 |
| 4 | 신규 MCP tool 4개 각 단위 (~12개) | mcp_server.py 통합 (FastMCP) | Claude Desktop 에서 alpha_deep_dive 호출 → JSON 검증 |
| 5 | 점수별 회귀 테스트 (~15개) | E2E pipeline | 1주 dry-run + 임계값 통과 |

### 임계값 (Phase 2 백테스트)

**강화 효과 인정 조건** (모두 충족):
- `expectancy_r ≥ 0.20`
- `IC(alpha_score, ret_5d) ≥ 0.05`
- `Profit Factor ≥ 1.4`
- `sample_size ≥ 100`
- A/B 비교: `delta_expectancy_r > 0` (강화 > 기존)

### 롤백 절차

각 phase 는 독립 commit + 환경 토글:
```bash
# .env 토글
ENABLE_ALPHA_PHASE_1_BLACKLIST=0      # KIND 블랙리스트 비활성
ENABLE_ALPHA_PHASE_3_CONSENSUS=0      # Selective consensus 비활성
ENABLE_ALPHA_PHASE_4_MCP=0            # 신규 MCP 비활성
```

임계값 미달 시:
1. `git revert <phase_commit_hash>` 후 새 commit
2. `feedback_alpha_phase_N_failed_YYYYMMDD.md` 메모 (왜 실패했는지)
3. memory index 갱신

---

## 운영 / 비용

### 비용 추정 (월간)

- LLM 호출 (Gemini Flash + GPT-4o 기존): 변화 없음
- KIND fetch: 무료
- 백테스트: 무료 (pandas/numpy)
- 추가 데이터 저장: ~50MB/월
- **총 marginal 비용**: $5~10/월

### 모니터링

- **일일 metric dashboard**: `/api/admin/mirofish/alpha_metrics_today`
  - 헛시그널 차단 건수
  - Selective consensus 통과율
  - 백테스트 7일 rolling expectancy_r / IC
- **개인 텔레그램 알림**:
  - expectancy_r 가 7일 연속 < 0.1 → 즉시 알림 (강화 효과 의심)
  - KIND fetch 실패 (3회 연속) → 알림

---

## Out of Scope (이 spec 에서 제외)

- **실시간 매매 자동 실행** (키움 OpenAPI 주문 자동화) — 별도 spec 필요. 위험성 + 규제 검토 우선
- **새 LLM 모델 도입** (Claude opus, Grok 등) — Research A 결론대로 ROI 낮음. 별도 검토
- **차트 패턴 시각 인식** (CNN/ViT) — 별도 R&D 사이클
- **옵션/ETF 자금 흐름** — KOSPI200 옵션 PCR 만 의미, 개별주 무효 (Research D)
- **CLAUDE.md §2 의 backtest/engine.py 경로 오표기 수정** — 별도 commit
- **회원 / 결제 / 인증** — 알파 스캐너 강화와 무관

---

## 완료 조건 (모든 phase 완료 시)

- [ ] Phase 1: KIND 블랙리스트 매칭 + 5개 게이트 적용. 단위 테스트 PASS.
- [ ] Phase 2: 백테스트 스크립트 + 일일 cron. 1,922 run 백테스트 통과.
- [ ] Phase 3: Selective Consensus + 섹터 RS. Phase 2 백테스트로 효과 측정.
- [ ] Phase 4: 신규 MCP tool 4개. Claude Desktop 에서 `alpha_deep_dive` 1-call 검증.
- [ ] Phase 5: 점수별 회귀 테스트 15+ PASS. 1주 dry-run + 임계값 통과.
- [ ] 운영 metric dashboard 가동.
- [ ] 비용 monthly < $30.

## Plan 단계 분리 권장

5-Phase 를 한 plan 으로 묶으면 너무 큼. 권장 분리:
- **Plan A (1차)**: Phase 1 + Phase 2 — 가장 큰 효과 + 검증 인프라 동시 구축
- **Plan B (2차)**: Phase 3 — Plan A 검증 통과 후 정밀화
- **Plan C (3차)**: Phase 4 — MCP tool 추가
- **Plan D (4차)**: Phase 5 — 운영 안정화

각 plan 은 독립 실행 가능. 사용자가 Plan A 만 도입하고 멈춰도 OK (Phase 1+2 만으로도 정확도 개선 + 효과 측정 가능).

---

## 참고 자료 (딥리서치 7건)

1. **Multi-LLM Trading Patterns** — TradingAgents (arXiv:2412.20138), TrustTrade (arXiv:2603.22567), MarketSenseAI
2. **알파 스캐너 내부 코드** — `app/services/mirofish/{alpha_scanner,auto_runner,mcp_server}.py` 분석
3. **R-Multiple 매매안** — Van Tharp Position Sizing, 내부 `engine/position_sizer.py`
4. **한국 시장 특화** — KIND 시장경보 공시, O'Neil RS (dalinaum/rs GitHub), 한국 CANSLIM 백테스트
5. **백테스트 인프라** — vectorbt 비교, 내부 `us_market/backtest_engine.py`, `data/admin_mirofish/scanner_runs/`
6. **MCP 디자인** — Anthropic "Writing tools for agents", FastMCP best practices, Pamela Fox 스키마 연구
7. **유사 운영 시스템** — Bloomberg ASKB, GS Marquee, Quiver Quantitative, AlphaGenerator (GitHub)

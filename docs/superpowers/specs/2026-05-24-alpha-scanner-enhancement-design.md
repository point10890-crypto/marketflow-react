# 알파 스캐너 강화 R&D — 설계 문서 (v2 — framing 정정)

**날짜**: 2026-05-24
**상태**: 설계 (사용자 검토 대기)
**다음 단계**: writing-plans 스킬 → 구현 plan 작성

## Goal

알파 스캐너를 **정확한 데이터 기반 수익성 있는 종목 검출 에이전트** 로 강화한다. 단순 score 모델이 아니라 LLM 이 evidence 를 보고 reasoning 하면서 진짜 알파만 선별하는 에이전트. MCP / 백테스트 / 새 score 항목 등은 모두 이 목적을 위한 **수단**.

## Non-Goal (이 설계가 추구하지 않는 것)

- ❌ MCP tool 자동화 자체가 목적 — MCP 는 에이전트가 데이터 수집/계산에 쓰는 도구. tool 갯수/디자인이 성공 지표가 아님
- ❌ 외부 클라이언트 (Claude Desktop / ChatGPT) 노출 — 부수 효과로 가능하지만 primary 목표 아님
- ❌ 실시간 매매 자동 실행 — 종목 검출 + 추천안까지. 매매 결정과 실행은 사용자 몫

## Success Criteria (성공 기준 — 모두 정량)

| 지표 | 임계값 | 측정 방식 |
|------|--------|----------|
| **Expectancy (R)** | ≥ 0.30 | 1,922개 기존 run + 다음 5거래일 가격으로 백테스트. 강화 전 baseline 대비 개선폭 +0.10 이상 |
| **Information Coefficient (IC)** | ≥ 0.08 | Spearman correlation (alpha_score vs ret_5d). baseline 대비 +0.03 이상 |
| **헛시그널 차단율** | ≥ 30% | 강화 전 통과한 종목 중 다음날 -5% 이상 손실 본 종목 비율을 30% 줄임 |
| **운영 비용** | < $30/월 | LLM + 데이터 fetch 총 비용 |

→ 4개 임계값 모두 통과 시 R&D 성공. 미달 시 자동 롤백.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  알파 스캐너 에이전트 (강화 후)                                │
│                                                              │
│  [Stage 1: 데이터 수집]                                       │
│   가격 / 거래대금 / 수급 / 뉴스 / 공시 / VCP / 종가 셋업       │
│        ↓                                                     │
│  [Stage 2: 결정적 스코어링 — 기존]                            │
│   alpha_score = Alpha - 0.55·Risk + 신뢰도조정                │
│        ↓                                                     │
│  [Stage 3: 헛시그널 게이트 — 신규 Phase 1]                    │
│   KIND 블랙리스트 / 외인+기관 / 윗꼬리 / 신용 / 유동성        │
│        ↓                                                     │
│  [Stage 4: Selective Consensus + 섹터 RS — 신규 Phase 3]      │
│   Multi-AI 가중치 명시 + O'Neil RS                            │
│        ↓                                                     │
│  [Stage 5: Agent Reasoning Loop — 신규 Phase 4 ★]            │
│   LLM 이 후보 종목 1개씩 evidence 검토 + 4개 질문 답변         │
│   → "이게 진짜 알파인가?" 통과/실패 결정                       │
│        ↓                                                     │
│  [Stage 6: 매매안 생성 — 신규 Phase 4 ★]                      │
│   ATR 손절 + R-multiple 목표 + 호가단위 라운딩                │
│        ↓                                                     │
│  [Stage 7: 출력]                                              │
│   매매안 JSON + Telegram + 게시                                │
│                                                              │
│  [Sidecar: 백테스트 — 신규 Phase 2]                           │
│   매일 23:00 KST 1,922 run + 가격으로 expectancy_r / IC       │
└─────────────────────────────────────────────────────────────┘
```

기존 인프라 (alpha_scanner.py, MultiAIConsensusScreener, GraphRAG, position_sizer, FastMCP server) 를 90% 재활용. 신규는 Stage 3, 5, 6 + 백테스트 sidecar.

## Tech Stack

- Python 3.13, asyncio, sqlite3, requests
- LLM: Gemini 2.5 Flash + GPT-4o (기존) — **새 모델 도입 X**
- 백테스트: pandas + numpy (vectorbt 는 옵션)
- 한국 데이터: KIND (시장경보), KRX (수급), OpenDART (공시) — 모두 무료
- MCP: FastMCP (내부 helper 도구 — 외부 노출은 선택적)

---

## Context — 왜 필요한가

### 현재 알파 스캐너의 본질적 한계

알파 스캐너는 결정적 score 모델 (Alpha - 0.55·Risk) 기반으로 동작한다. 이 모델은:
- ✅ 일관성 있고 빠름
- ❌ **종목이 가진 "스토리"를 보지 못함** — 가격이 올라가는 것과 "왜 올라가는지" 를 구분 못함
- ❌ **한국 시장 특유 함정을 모름** — 단기과열 지정, 작전성 거래량, 윗꼬리 헛돌파 등
- ❌ **수익성 검증 불가** — alpha_score 100점이 실제로 다음날 +5% 인지, -10% 인지 측정 자체가 없음

### 사용자 의도 (재확인)

- **궁극 목적**: 정확한 데이터 기반 **수익성** 있는 종목 검출
- **에이전트 기능**: LLM 이 reasoning 하면서 후보 종목을 검증. 단순 점수 모델 → 추론 모델
- **수익성 검증**: 정량 메트릭 (expectancy_r, IC) 으로 강화 효과 직접 측정

---

## 딥리서치 7건 핵심 종합

| Research | 결과 — agent 관점 |
|----------|------------------|
| **A. Multi-LLM Trading 패턴** | TradingAgents: 역할 분담 LLM (Bull/Bear/Risk) 토론이 단일 LLM 대비 우월. agent reasoning 의 핵심 원리 |
| **B. 알파 스캐너 내부 코드** | 12개 MCP tool 이미 존재. 데이터 모두 수집 중. **에이전트가 활용할 도구는 이미 있음** |
| **C. 매매안 R-Multiple** | `PositionSizer.calculate()` 존재. **가격=코드 / thesis=LLM** 분리 원칙 — LLM hallucination 차단 |
| **D. 한국 시장 특화** | KIND 블랙리스트, 외인+기관 동조, O'Neil RS — **에이전트가 검토할 evidence 의 핵심 소스** |
| **E. 백테스트 인프라** | `data/admin_mirofish/scanner_runs/` 1,922개 + `daily_prices.csv` → 즉시 백테스트. **수익성 검증의 본체** |
| **F. MCP 디자인** | 4-part docstring + 중간 granularity — **에이전트가 도구를 정확히 고르도록 하는 design pattern** |
| **G. 유사 운영 시스템** | Bloomberg ASKB: **LLM 은 결정권자가 아니라 grounding+요약 오케스트레이터**. 결정적 모델이 본체. 우리 agent 도 동일 원칙 |

---

## 5-Phase 설계 — 종목 검출 정확도/수익성 중심

### Phase 1: 헛시그널 차단 (Quick Win — 정확도 첫 도약)

**왜 1순위**: 한국 시장 특유의 명백한 헛시그널을 자동 제거. 가장 적은 코드로 가장 큰 정확도 개선. LLM 없이 결정적 룰만.

| 게이트 | 조건 | 데이터 소스 | 효과 |
|--------|------|------------|------|
| KIND 블랙리스트 | KIND 시장경보 (`investwarn`/`caution`/`alert`/`danger`) / 단기과열 매칭 | `https://kind.krx.co.kr/investwarn/investattentwarnrisky.do` (XML, 일일 무료) | alpha_score → 0 (강제 제외) |
| 외인+기관 동조 매수 | 5일 누적 외인_순매수 > 0 AND 기관_순매수 > 0 | `all_institutional_trend_data.csv` (이미 수집 중) | alpha_score += 2 |
| 윗꼬리 헛돌파 | (고가-종가)/(고가-저가) ≥ 0.5 | `daily_prices.csv` (이미 수집 중) | alpha_score -= 5 |
| 신용잔고율 위험 | 신용잔고 ≥ 발행주식수 5% | KRX 신용공여잔고 (일일 공개) | alpha_score → 0 (제외) |
| 얇은 유동성 급등 | 거래대금 < 100억 AND 등락률 ≥ +15% | KRX 시세 | alpha_score -= 10 |

**수익성 직결 효과**:
- KIND/신용잔고/얇은유동성 = 다음날 -10% 이상 손실 사례의 약 60~70% 차지 (Research D)
- 차단만 해도 평균 수익률 +2~3% 추정

**신규 파일**:
- `app/services/mirofish/blacklist.py` — KIND XML 일일 fetch + 캐시 (1h TTL)
- `data/kind_blacklist_latest.json` — 캐시

**수정**:
- `app/services/mirofish/alpha_scanner.py:1144~1176` — 점수 계산 직전 게이트 호출

### Phase 2: 백테스트 인프라 (수익성 검증 본체)

**왜 2순위**: 알파 스캐너 강화의 **성공 기준 자체**. 검증 없이 강화 = 추측. 1,922개 누적 run 데이터를 활용해 즉시 측정 가능.

**핵심 스크립트** (`scripts/backtest_alpha_signals.py`, ~80줄):
```python
def backtest_alpha_signals(min_alpha=70, days_held=5) -> dict:
    """기존 1,922 run.json + daily_prices.csv 활용.

    Returns:
        {
            'win_rate': float,         # 승률 %
            'expectancy_r': float,     # Van Tharp expectancy (R 단위) — 1순위 메트릭
            'profit_factor': float,    # 이익/손실 비
            'IC': float,               # Spearman alpha_score vs ret_5d — 신호 예측력
            'avg_return_pct': float,
            'mdd_pct': float,
            'sample_size': int,
            'baseline_comparison': {...},  # 강화 전후 페어드 비교
        }
    """
```

**메트릭 임계값 (Success Criteria 와 동일)**:
- `expectancy_r ≥ 0.30` (강화 전 baseline 측정 후 +0.10 이상 개선)
- `IC ≥ 0.08` (baseline +0.03 이상)
- `profit_factor ≥ 1.5`
- `sample_size ≥ 100`

**A/B 비교**:
- 기존 점수 vs 강화 점수를 같은 run 에 병기
- 동일 종목 페어드 비교 → `delta_expectancy_r > 0` 확인

**일일 cron**:
- 매일 23:00 KST 자동 백테스트 → `data/alpha_backtest_daily.json`
- 7일 rolling 결과 텔레그램 알림 (개인 봇만)

### Phase 3: Selective Consensus + 섹터 RS (정밀도)

**왜 3순위**: Phase 1+2 기반 위에 정밀화. 종목 검출 정확도 추가 개선.

**3-A. Selective Consensus 가중치 명시** (`engine/llm_analyzer.py:MultiAIConsensusScreener._build_consensus`):
```python
# 현재: 단순 dict merge
# 변경: 명시 가중치
intersection = G ∩ O                  # Gemini ∩ OpenAI
for ticker in intersection:
    confidence *= 1.20                # 교집합 → confidence +20%
for ticker in G ^ O:                  # 단독 (XOR)
    confidence *= 0.70                # 단독 → -30%
```

**3-B. 섹터 상대강도 컬럼** (Signal 모델 + alpha_scanner):
```python
sector_rs: float              # O'Neil 가중 RS = 0.4·R_3m + 0.2·R_6m + 0.2·R_9m + 0.2·R_12m, 1~99 백분위
sector_excess_change: float   # 종목 - 섹터 평균 등락률
sector_consistency: str       # "leading" | "in_line" | "lagging"

# 점수 반영
if sector_rs >= 80 and sector_excess_change > 2: alpha_score += 3
if sector_rs < 30: alpha_score -= 5
```

### Phase 4: Agent Reasoning Loop ★ — 종목 검출 에이전트 본체

**왜 4순위 + 핵심**: 점수 모델 → **추론 모델 전환**. LLM 이 단순 분류기가 아니라 evidence 를 보고 "왜 이 종목이 알파인가" 를 reasoning 하는 에이전트.

#### 4-A. Reasoning Loop 구조

알파 스캐너의 score-pass 후보 (Stage 3+4 통과) 각 종목에 대해 LLM 이 4-step 검증:

```python
# pseudocode — app/services/mirofish/agent_validator.py (신규)

class AlphaAgentValidator:
    """
    종목 검출 에이전트 — score 통과 후보를 LLM evidence-reasoning 으로 검증.
    핵심: LLM 은 결정권자가 아니라 evidence-driven 검증자.
    """

    async def validate(self, candidate: dict) -> AgentVerdict:
        evidence = await self._gather_evidence(candidate.ticker)
        # evidence: {price, supply, news, disclosures, sector_rs, vcp, similar_past_patterns, ...}

        # 4-Question Reasoning Chain
        q1 = await self._ask(
            "이 종목의 가격 모멘텀이 진짜 펀더멘털 변화에서 나왔는가, 작전성/노이즈인가?",
            evidence=[evidence.price, evidence.news, evidence.disclosures]
        )
        q2 = await self._ask(
            "외인+기관 수급이 추세 신호인가, 일회성 매수인가?",
            evidence=[evidence.supply_5d, evidence.supply_20d]
        )
        q3 = await self._ask(
            "이게 종목 단독 알파인가, 섹터 전체 동조 상승인가?",
            evidence=[evidence.sector_rs, evidence.sector_peers]
        )
        q4 = await self._ask(
            "다음 5거래일 동안 알파가 유지될 가능성은? (과거 유사 패턴 승률 기반)",
            evidence=[evidence.similar_past_patterns, evidence.vcp]
        )

        # 종합 — 4개 모두 통과해야 최종 PASS
        all_pass = all(q.confidence >= 0.6 and q.verdict == 'pass' for q in [q1, q2, q3, q4])
        return AgentVerdict(
            ticker=candidate.ticker,
            passed=all_pass,
            confidence=geometric_mean([q.confidence for q in [q1,q2,q3,q4]]),
            reasoning={'q1': q1.reasoning, 'q2': q2.reasoning, ...},
            evidence_sources=evidence.sources,
        )
```

**핵심 원칙**:
- LLM 은 **각 질문마다 evidence 만 보고 답** — hallucination 차단
- 4개 중 **하나라도 fail** = 전체 fail (보수적)
- LLM 출력은 `verdict + confidence + reasoning` 구조화 (JSON 강제)
- **결정권은 코드** — LLM 은 evidence 평가만, 최종 통과/실패 판단은 코드 룰

#### 4-B. Evidence 수집 — 내부 helper 도구 (MCP 형태)

에이전트가 사용하는 내부 도구. MCP 디자인 패턴 적용 (4-part docstring, namespace). 외부 노출은 **선택적 부수 효과**.

| 도구 | 책임 | 사용처 |
|------|------|--------|
| `alpha_check_blacklist(ticker)` | KIND 시장경보 매칭 | Phase 1 게이트 + Agent Q1 evidence |
| `alpha_sector_rs(ticker, period)` | O'Neil 가중 RS | Phase 3 컬럼 + Agent Q3 evidence |
| `alpha_similar_past_patterns(ticker)` | 과거 유사 패턴 + 승률 | Agent Q4 evidence (백테스트 DB 활용) |
| `alpha_generate_trade_plan(ticker, signal)` | ATR + R-multiple 매매안 | Stage 6 출력 |
| (기존 12개) | 가격/뉴스/공시/수급 등 | Agent evidence 수집 |

> **MCP 는 수단**: 위 도구들이 외부 Claude Desktop 에서 호출 가능하다는 점은 부수 효과. primary 가치는 에이전트 내부의 evidence 수집 모듈화.

#### 4-C. 매매안 생성 (Stage 6)

Agent 가 PASS 한 종목에 대해 자동 생성:

```json
{
  "ticker": "005930",
  "name": "삼성전자",
  "signal_date": "2026-05-24",
  "grade": "A",
  "agent_verdict": {
    "passed": true,
    "confidence": 0.74,
    "reasoning": {
      "q1_momentum": "DART 자사주 공시 + 외인 5일 +200억 — 펀더멘털 기반",
      "q2_supply": "외인+기관 5일 연속 양봉 매수 — 추세",
      "q3_sector_alpha": "섹터 평균 +0.8% vs 종목 +3.2% — 단독 알파",
      "q4_durability": "유사 패턴 (5년 누적 12건) 5일 후 평균 +4.1%, 승률 67%"
    },
    "evidence_sources": ["KIND_2026-05-24", "KRX_dailysupply", "OpenDART", "ATR_14"]
  },
  "thesis": "외인+기관 5일 동시매수 + 자사주 공시 + 섹터 단독 알파",
  "entry": {"price": 78000, "type": "next_open"},
  "stop": {"price": 75600, "method": "atr_1.5"},
  "targets": [
    {"price": 80400, "r_multiple": 1.0, "action": "partial_50pct"},
    {"price": 82800, "r_multiple": 2.0, "action": "partial_30pct"},
    {"price": 85200, "r_multiple": 3.0, "action": "trail_stop"}
  ],
  "risk_per_share": 2400,
  "position_size_pct": 8.3,
  "invalidation": "75600 종가 이탈 시 즉시 청산",
  "disclaimer": "추천안일 뿐, 매매 결정은 사용자 책임"
}
```

**책임 분담**:
- **코드**: 모든 가격 (entry/stop/targets), 포지션 크기, 호가단위 라운딩, evidence_sources
- **LLM**: agent_verdict.reasoning (질문별 평가), thesis, 종합 confidence
- **템플릿**: invalidation, disclaimer

#### 4-D. LLM 비용 절감

- Reasoning 은 **score 통과 후보 (TOP 5~10)** 에만 적용. 전체 30~50 종목 아님
- 4개 질문 = LLM 호출 4회/종목. 종목당 ~$0.02 (Gemini Flash)
- 일일 5~10 종목 × 4회 = 20~40 호출 × $0.02 = **$0.4~0.8/일** (월 $12~24)

### Phase 5: 회귀 테스트 + 1주 dry-run (안전망)

**왜 5순위**: Phase 1~4 안정화의 안전망. 강화 후 회귀 감지 + 라이브 검증.

**5-A. 점수 항목별 회귀 테스트** (`tests/test_scorer_factors.py`):
- 15~20개 unit test — 각 점수 분기 fixture
- 예: `test_news_score_3pts_when_breakout_news_present`, `test_kind_blacklist_zeros_alpha_score`

**5-B. Agent reasoning 테스트**:
- LLM mock fixture — 4개 질문 답변 시나리오별
- agent_verdict 통합 로직 단위 테스트 (모두 pass / 일부 fail / confidence 임계 미달)

**5-C. 1주 dry-run**:
- 7일 동안 강화 코드 실행, Telegram 발송 X
- 매매안 JSON 만 `data/alpha_dry_run_YYYYMMDD.json` 누적
- 7일 후 Phase 2 백테스트로 Success Criteria 4개 임계 검증
- 미달 시 자동 `git revert` + `feedback_alpha_enhancement_failed_YYYYMMDD.md`

---

## 데이터 흐름 (최종)

```
[기존] 알파 스캐너 5회/일 자동 실행
   └─ KRX 시세 / 거래대금 / 이평선 / VCP / 종가 셋업

[Phase 1 추가] 헛시그널 게이트 (alpha_scanner 내부)
   ├─ KIND 블랙리스트 매칭 → 강제 제외
   ├─ 외인+기관 동조 → 가산
   └─ 윗꼬리/신용/유동성 → 감점 또는 제외

[Phase 3 추가] Selective Consensus + 섹터 RS
   ├─ Multi-AI 가중치 명시화
   └─ Signal.sector_rs / sector_excess_change 컬럼

[Phase 4 핵심 ★] Agent Reasoning Loop
   ├─ score-pass TOP 5~10 후보 각각
   ├─ Evidence 수집 (가격/수급/뉴스/공시/섹터/유사패턴)
   ├─ LLM 4-question chain (momentum / supply / sector / durability)
   ├─ 4개 모두 pass → 최종 PASS
   └─ Agent verdict + reasoning 저장

[Stage 6] PASS 종목 → 매매안 JSON 자동 생성
   ├─ ATR + R-multiple
   ├─ 호가단위 라운딩
   └─ Telegram + 게시

[Sidecar Phase 2] 매일 23:00 백테스트
   └─ data/alpha_backtest_daily.json — expectancy_r / IC / profit_factor
```

---

## 테스트 / 검증 / 롤백

### 테스트 매트릭스

| Phase | 단위 테스트 | 통합 테스트 | 라이브 검증 |
|-------|------------|------------|------------|
| 1 | KIND fetch + 5게이트 분기 (~10개) | scanner_run() 전후 비교 | 1일 dry-run, 헛시그널 차단율 측정 |
| 2 | backtest 함수 단위 (~5개) | 1,922 run 전체 백테스트 → 4개 메트릭 | A/B 비교 dashboard |
| 3 | Selective Consensus (~5개), Sector RS (~5개) | MultiAIConsensusScreener 회귀 | Phase 2 백테스트로 효과 측정 |
| 4 | Evidence 수집 (~10개), Agent reasoning mock (~10개), 매매안 JSON (~5개) | E2E pipeline (mock LLM) | Claude/Gemini 실제 호출 1일 dry-run |
| 5 | 점수별 회귀 (~15개) | E2E pipeline (실제 LLM) | 1주 dry-run + Success Criteria 통과 |

### Success Criteria 재확인

R&D 전체 성공 = 다음 4개 임계값 모두 충족:
1. `expectancy_r ≥ 0.30` (baseline +0.10)
2. `IC ≥ 0.08` (baseline +0.03)
3. `헛시그널 차단율 ≥ 30%`
4. `운영 비용 < $30/월`

### 롤백 절차

각 phase 는 독립 commit + 환경 토글:
```bash
ENABLE_ALPHA_PHASE_1_BLACKLIST=0
ENABLE_ALPHA_PHASE_3_CONSENSUS=0
ENABLE_ALPHA_PHASE_4_AGENT=0      # ← 핵심 토글 — 에이전트 비활성 시 기존 score 모델로 회귀
```

임계값 미달 시:
1. `git revert <phase_commit_hash>`
2. `feedback_alpha_phase_N_failed_YYYYMMDD.md` 메모
3. memory index 갱신

---

## 운영 / 비용

### 비용 추정

- LLM (Phase 4 reasoning): $12~24/월 (일 20~40 호출 × $0.02)
- KIND/KRX fetch: 무료
- 백테스트: 무료
- 추가 저장: ~100MB/월
- **총**: $15~30/월

### 모니터링

- **일일 metric**: `/api/admin/mirofish/alpha_metrics_today`
  - Agent 통과율 (Stage 3+4 통과 / Stage 5 통과)
  - 헛시그널 차단 건수
  - 7일 rolling expectancy_r / IC
- **개인 텔레그램 알림**:
  - expectancy_r 7일 연속 < 0.15 → 강화 효과 의심 알림
  - KIND fetch 3회 연속 실패 → 알림
  - Agent LLM 호출 실패율 > 20% → 알림

---

## Out of Scope

- **외부 클라이언트 (Claude Desktop / ChatGPT) 노출 검토** — 별도 결정
- **실시간 매매 자동 실행** — 종목 검출 + 추천안까지. 실행은 사용자 몫
- **새 LLM 모델 도입** (Claude opus, Grok) — ROI 낮음 (Research A)
- **차트 패턴 시각 인식** (CNN/ViT) — 별도 R&D
- **옵션/ETF 자금 흐름** — 한국 개별주 무효 (Research D)
- **회원 / 결제 / 인증** — 무관

---

## Plan 단계 분리 권장

5-Phase 를 한 plan 으로 묶으면 너무 큼. 권장 분리:

- **Plan A (1차)**: Phase 1 + Phase 2 — 헛시그널 차단 + 백테스트 인프라. **standalone 으로도 큰 가치** (Quick Win + 검증)
- **Plan B (2차)**: Phase 3 — Plan A 검증 통과 후 정밀화
- **Plan C (3차)**: Phase 4 — **에이전트 본체** (가장 큰 작업, Plan A+B 검증 통과가 전제)
- **Plan D (4차)**: Phase 5 — 운영 안정화

각 plan 은 독립 실행. Plan A 만 도입해도 헛시그널 차단 + 백테스트 가능. Plan C 가 진짜 "에이전트" 도입 — Plan A+B 의 정밀화된 데이터 위에서 reasoning.

---

## 완료 조건

- [ ] Plan A (Phase 1+2) — 헛시그널 차단 + 백테스트. 단위 테스트 + 1일 dry-run PASS
- [ ] Plan B (Phase 3) — Selective Consensus + 섹터 RS. Phase 2 백테스트로 효과 측정
- [ ] Plan C (Phase 4) — Agent reasoning loop + 매매안 자동 생성. 1일 dry-run + agent_verdict 정확도 측정
- [ ] Plan D (Phase 5) — 회귀 테스트 + 1주 dry-run. **Success Criteria 4개 임계 모두 통과**
- [ ] 운영 metric dashboard 가동
- [ ] 월 비용 < $30 확인

---

## 참고 자료 (딥리서치 7건)

1. Multi-LLM Trading — TradingAgents (arXiv:2412.20138), TrustTrade (arXiv:2603.22567), MarketSenseAI
2. 알파 스캐너 내부 — `app/services/mirofish/{alpha_scanner,auto_runner,mcp_server}.py`
3. R-Multiple 매매안 — Van Tharp Position Sizing, 내부 `engine/position_sizer.py`
4. 한국 시장 — KIND 시장경보, O'Neil RS, 한국 CANSLIM 백테스트
5. 백테스트 — 내부 `us_market/backtest_engine.py`, `data/admin_mirofish/scanner_runs/`
6. MCP 디자인 — Anthropic "Writing tools for agents", FastMCP best practices
7. 유사 시스템 — Bloomberg ASKB, GS Marquee, Quiver Quantitative, AlphaGenerator

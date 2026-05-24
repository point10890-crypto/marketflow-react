# 알파 스캐너 강화 구현 보고서

**날짜**: 2026-05-24
**기반 spec**: [`2026-05-24-alpha-scanner-enhancement-design.md`](./2026-05-24-alpha-scanner-enhancement-design.md)
**상태**: 구현 전략 — 사용자 검토 대기

---

## Executive Summary

알파 스캐너를 **수익성 있는 종목 검출 에이전트** 로 강화하는 작업을 4개 plan 으로 분리하여 순차 실행. 각 plan 은 독립 가치 + 검증 인프라 통과 후 다음 plan 진행. **총 일정 4~6주, 비용 월 $15~30.**

| Plan | 핵심 산출 | 소요 시간 | 가치 | 의존성 |
|------|----------|----------|------|--------|
| **A. 헛시그널 차단 + 백테스트** | KIND 블랙리스트 + 5게이트 + 백테스트 스크립트 | 1~1.5주 | 즉시 정확도 +20~30% | 없음 (Quick Win) |
| **B. 정밀화** | Selective Consensus 가중치 + O'Neil RS | 1주 | Plan A 위에서 추가 정밀도 | Plan A 백테스트 통과 |
| **C. 에이전트 본체** | LLM 4-question reasoning loop + 매매안 자동 생성 | 2~3주 | **핵심 — 검출 에이전트 도입** | Plan A+B 통과 |
| **D. 운영 안정화** | 회귀 테스트 15+개 + 1주 dry-run + Success Criteria 검증 | 1주 | 전체 검증 + 롤백 안전망 | Plan A+B+C 완료 |

**총 R&D 성공 조건** (Plan D 종료 시점):
- `expectancy_r ≥ 0.30` (baseline +0.10)
- `IC ≥ 0.08` (baseline +0.03)
- 헛시그널 차단율 ≥ 30%
- 운영 비용 < $30/월

---

## 추진 전략

### 원칙

1. **기존 인프라 90% 재활용** — 새 모듈/라이브러리 도입 최소화
2. **각 phase 독립 commit** — 임계값 미달 시 `git revert` 즉시 가능
3. **환경 토글로 비활성화 가능** — `ENABLE_ALPHA_PHASE_N=0` 으로 안전 종료
4. **검증 우선** — Plan A 의 백테스트 인프라가 Plan B/C 의 효과 측정에도 사용됨

### 순서 결정 이유

- **A 먼저 (헛시그널 차단 + 백테스트 동시)**: 가장 적은 코드로 가장 큰 정확도 개선 + 검증 인프라 동시 구축. Plan A 만 도입하고 멈춰도 가치 있음.
- **B 두 번째 (정밀화)**: A 의 백테스트로 효과 측정 가능. A 효과가 검증된 위에서 추가 정밀도.
- **C 핵심 (에이전트)**: A+B 의 정밀화된 데이터를 받아서 LLM 이 reasoning. 가장 큰 작업이라 마지막에 안정된 기반 위에서.
- **D 마지막 (운영)**: A+B+C 모두 적용된 시스템의 종합 검증 + 롤백 안전망.

---

## Plan A 구현 상세 — 헛시그널 차단 + 백테스트 (1~1.5주)

### 작업 1: KIND 블랙리스트 fetcher (반일)

**신규 파일**: `app/services/mirofish/blacklist.py`

**기능**:
- `https://kind.krx.co.kr/investwarn/investattentwarnrisky.do` 일일 XML fetch
- 종목코드 + 카테고리 (investwarn/caution/alert/danger/short_term_overheating) 파싱
- `data/kind_blacklist_latest.json` 캐시 (TTL 1시간)
- 함수: `is_blacklisted(ticker) -> {listed: bool, categories: list, risk_level: str}`

**테스트**:
- `tests/services/mirofish/test_blacklist.py`
- Mock XML 응답으로 5개 케이스 (정상/주의/경고/위험/단기과열)

### 작업 2: 5개 헛시그널 게이트 추가 (1일)

**수정 파일**: `app/services/mirofish/alpha_scanner.py:1144~1176`

```python
# 점수 계산 직전 게이트 호출
def apply_false_signal_gates(candidate: ScannerCandidate) -> ScannerCandidate:
    # Gate 1: KIND 블랙리스트
    bl = is_blacklisted(candidate.ticker)
    if bl['listed']:
        candidate.alpha_score = 0
        candidate.rejection_reason = f"KIND_blacklist:{bl['categories']}"
        return candidate

    # Gate 2: 외인+기관 동조 매수 (가산)
    if foreign_inst_dual_buy_5d(candidate.ticker):
        candidate.alpha_score += 2

    # Gate 3: 윗꼬리 헛돌파 (감점)
    if upper_wick_ratio(candidate) >= 0.5:
        candidate.alpha_score -= 5

    # Gate 4: 신용잔고율 (제외)
    if credit_balance_ratio(candidate.ticker) >= 0.05:
        candidate.alpha_score = 0
        candidate.rejection_reason = "credit_balance_risk"
        return candidate

    # Gate 5: 얇은 유동성 급등 (감점)
    if candidate.trading_value < 10_000_000_000 and candidate.change_pct >= 15:
        candidate.alpha_score -= 10

    return candidate
```

**테스트**:
- `tests/services/mirofish/test_false_signal_gates.py`
- 각 게이트별 분기 케이스 (~10개)

### 작업 3: 백테스트 스크립트 (1.5일)

**신규 파일**: `scripts/backtest_alpha_signals.py` (~80줄)

**기능**:
- `data/admin_mirofish/scanner_runs/*.json` 전체 로드 (1,922개)
- 각 run 의 candidates 에 대해 `daily_prices.csv` 에서 5거래일 후 가격 lookup
- 메트릭 계산:
  - `win_rate`, `expectancy_r`, `profit_factor`, `IC`, `avg_return_pct`, `mdd_pct`
- A/B 비교: 강화 전 (기존 점수) vs 강화 후 (Phase 1 게이트 적용)

**임계값 자동 판정**:
```python
SUCCESS_THRESHOLDS = {
    'expectancy_r_min': 0.30,
    'IC_min': 0.08,
    'profit_factor_min': 1.5,
    'sample_size_min': 100,
    'delta_expectancy_r_min': 0.10,  # baseline 대비 개선폭
}
```

**테스트**:
- `tests/scripts/test_backtest_alpha.py`
- 합성 데이터로 win_rate / expectancy_r / IC 계산 검증

### 작업 4: 일일 백테스트 cron (반일)

**수정 파일**: `scheduler.py`

**스케줄 등록**:
```python
schedule.every().day.at("23:00").do(
    self._with_record(run_alpha_backtest_daily, 'alpha_backtest_daily')
)
```

**산출**:
- `data/alpha_backtest_daily.json` (당일 결과)
- `data/alpha_backtest_rolling_7d.json` (7일 평균)
- expectancy_r 7일 연속 < 0.15 시 개인 텔레그램 알림

### 작업 5: 통합 검증 + 1일 dry-run (1일)

- 단위 테스트 전체 PASS 확인
- miniPC 배포 (scp) → 데몬 재기동 → 스캐너 1회 강제 발화
- 1,922 run 전체 백테스트 실행 → SUCCESS_THRESHOLDS 통과 확인
- 통과 시 commit + 운영 적용

**예상 일정**: 4~5 작업일 (집중 시) 또는 1~1.5주 (분산 시)

---

## Plan B 구현 상세 — 정밀화 (1주)

### 작업 1: Selective Consensus 가중치 명시 (2일)

**수정 파일**: `engine/llm_analyzer.py:MultiAIConsensusScreener._build_consensus`

```python
def _build_consensus(picks_by_model):
    gemini = set(picks_by_model['gemini'])
    openai = set(picks_by_model['openai'])
    intersection = gemini & openai
    g_only = gemini - openai
    o_only = openai - gemini

    consensus = []
    for ticker in intersection:
        confidence = base_confidence(ticker) * 1.20  # 교집합 +20%
        consensus.append({'ticker': ticker, 'confidence': confidence, 'source': 'consensus_strong'})
    for ticker in g_only | o_only:
        confidence = base_confidence(ticker) * 0.70  # 단독 -30%
        consensus.append({'ticker': ticker, 'confidence': confidence, 'source': 'single_model'})

    return sorted(consensus, key=lambda x: x['confidence'], reverse=True)
```

**테스트**: 기존 `tests/test_multi_ai_consensus.py` 확장 — 가중치 검증 케이스 5개 추가

### 작업 2: O'Neil 가중 RS 계산 (2일)

**신규 파일**: `app/services/mirofish/sector_rs.py`

**기능**:
- 종목별 3개월/6개월/9개월/12개월 수익률 계산 (`daily_prices.csv`)
- `RS = 0.4·R_3m + 0.2·R_6m + 0.2·R_9m + 0.2·R_12m`
- KRX 28개 섹터별 종목 → 백분위 변환 (1~99)
- 함수: `calculate_sector_rs(ticker) -> {rs_rating, sector, sector_excess_change, consistency}`

**수정**: alpha_scanner.py Signal 모델에 `sector_rs`, `sector_excess_change`, `sector_consistency` 컬럼 추가

**점수 반영**:
```python
if signal.sector_rs >= 80 and signal.sector_excess_change > 2:
    alpha_score += 3
if signal.sector_rs < 30:
    alpha_score -= 5
```

### 작업 3: Plan A 백테스트로 효과 측정 (1일)

- Plan B 적용 후 백테스트 실행
- A → A+B expectancy_r 변화 측정
- delta > 0 확인 시 Plan C 진행, 음수면 가중치 조정

**예상 일정**: 5 작업일

---

## Plan C 구현 상세 — 에이전트 본체 (2~3주, 핵심 작업)

### 작업 1: Evidence 수집 helper 도구 (4일)

**신규 파일**: `app/services/mirofish/agent_evidence.py`

```python
class EvidenceCollector:
    """에이전트가 사용하는 종목별 evidence 수집기.

    기존 12개 MCP tool + 신규 4개 helper 통합.
    각 evidence 는 source + timestamp + raw_data + summary 4-tuple.
    """

    async def collect(self, ticker: str) -> Evidence:
        return Evidence(
            price=await self._price_evidence(ticker),
            supply=await self._supply_evidence(ticker),
            news=await self._news_evidence(ticker),
            disclosures=await self._dart_evidence(ticker),
            sector=await self._sector_evidence(ticker),
            similar_patterns=await self._historical_patterns(ticker),
            blacklist_check=await self._blacklist_evidence(ticker),
        )
```

**기존 도구 재활용**:
- `get_kiwoom_quote`, `get_kiwoom_institution_trend` (기존)
- `get_dart_disclosures`, `get_news_summary` (기존)
- Phase 1 `is_blacklisted`, Phase 3 `calculate_sector_rs`

**신규 helper**:
- `alpha_similar_past_patterns(ticker)` — `data/admin_mirofish/scanner_runs/` DB 활용

**테스트**: `tests/services/mirofish/test_evidence_collector.py` — 각 evidence 타입별 ~10개

### 작업 2: Agent Reasoning Loop (5~7일, 핵심)

**신규 파일**: `app/services/mirofish/agent_validator.py`

```python
class AlphaAgentValidator:
    """LLM 4-question reasoning chain — score-pass 후보를 evidence 기반 검증.

    핵심 원칙: LLM = evidence 평가자, 결정권 = 코드
    """

    QUESTIONS = [
        AgentQuestion(
            id='q1_momentum',
            text="가격 모멘텀이 펀더멘털 변화에서 나왔는가, 작전성/노이즈인가?",
            evidence_keys=['price', 'news', 'disclosures'],
            min_confidence=0.6,
        ),
        AgentQuestion(
            id='q2_supply',
            text="외인+기관 수급이 추세 신호인가, 일회성 매수인가?",
            evidence_keys=['supply.foreign_5d', 'supply.foreign_20d', 'supply.institution_5d'],
            min_confidence=0.6,
        ),
        AgentQuestion(
            id='q3_sector',
            text="종목 단독 알파인가, 섹터 동조 상승인가?",
            evidence_keys=['sector.rs', 'sector.peers_change'],
            min_confidence=0.6,
        ),
        AgentQuestion(
            id='q4_durability',
            text="다음 5거래일 알파 유지 가능성은? (과거 유사 패턴 승률 기반)",
            evidence_keys=['similar_patterns', 'vcp'],
            min_confidence=0.6,
        ),
    ]

    async def validate(self, candidate: ScannerCandidate) -> AgentVerdict:
        evidence = await self.evidence_collector.collect(candidate.ticker)
        answers = []
        for q in self.QUESTIONS:
            answer = await self._ask_llm(q, evidence)
            answers.append(answer)

        all_pass = all(
            a.verdict == 'pass' and a.confidence >= q.min_confidence
            for a, q in zip(answers, self.QUESTIONS)
        )

        return AgentVerdict(
            ticker=candidate.ticker,
            passed=all_pass,
            confidence=geometric_mean([a.confidence for a in answers]),
            reasoning={a.id: a.reasoning for a in answers},
            evidence_sources=evidence.sources,
        )
```

**LLM 프롬프트 설계**:
- System: "너는 알파 검증 에이전트다. 주어진 evidence 만 보고 답하라. evidence 에 없는 사실 추론 금지."
- User: 각 질문 + evidence JSON
- Output 강제: `{verdict: 'pass'|'fail', confidence: 0~1, reasoning: str}` JSON 만

**비용 통제**:
- score-pass TOP 5~10 만 검증 (전체 30~50 종목 아님)
- 4 questions × Gemini Flash × $0.005/call = $0.02/종목
- 일 20~40 호출 = $0.4~0.8/일 = **$12~24/월**

**테스트**:
- LLM mock fixture (verdict 시나리오별 10개)
- `tests/services/mirofish/test_agent_validator.py` — agent_verdict 통합 로직 검증

### 작업 3: 매매안 자동 생성 (3일)

**수정 파일**: `engine/position_sizer.py` — `calculate_with_atr()` 메서드 추가

```python
def calculate_with_atr(self, entry, atr14, swing_low, grade) -> PositionResult:
    """ATR 기반 손절 + R-multiple 목표 매매안 생성."""
    stop = max(swing_low * 0.998, entry - 1.5 * atr14)
    risk_per_share = entry - stop
    targets = [entry + r * risk_per_share for r in [1.0, 2.0, 3.0]]
    # 한국 호가단위 라운딩
    stop = round_to_krx_tick(stop)
    targets = [round_to_krx_tick(t) for t in targets]
    return PositionResult(...)
```

**신규 파일**: `app/services/mirofish/trade_plan.py`

```python
def generate_trade_plan(candidate, agent_verdict) -> dict:
    """매매안 JSON 생성 — 가격은 코드, thesis 는 LLM verdict 활용."""
    return {
        'ticker': candidate.ticker,
        'agent_verdict': agent_verdict.to_dict(),
        'thesis': summarize_agent_reasoning(agent_verdict),  # LLM-generated 요약
        'entry': {...}, 'stop': {...}, 'targets': [...],
        'position_size_pct': ..., 'invalidation': ..., 'disclaimer': ...,
    }
```

### 작업 4: Pipeline 통합 + 1일 dry-run (3일)

- `alpha_scanner.create_scanner_run()` 에서 score-pass 후 agent validator 호출
- 통과 종목만 매매안 JSON 생성 → Telegram 발송 (개인 봇 + 채널)
- 1일 라이브 dry-run → agent_verdict 정확도 측정

**예상 일정**: 12~16 작업일 (2~3주)

---

## Plan D 구현 상세 — 운영 안정화 (1주)

### 작업 1: 점수 항목별 회귀 테스트 (3일)

**신규 파일**: `tests/services/mirofish/test_scorer_factors.py`

각 점수 항목별 분기 fixture + unit test:
- `test_news_score_3pts_when_breakout_news_present`
- `test_supply_score_2pts_when_both_foreign_and_inst_buy_5d`
- `test_kind_blacklist_zeros_alpha_score`
- `test_sector_rs_high_adds_3pts`
- `test_upper_wick_subtracts_5pts`
- `test_agent_verdict_all_pass_when_all_q_confidence_above_threshold`
- ... 총 15~20개

### 작업 2: 1주 dry-run (7일 + 1일 분석)

**신규 파일**: `scripts/dry_run_alpha_enhancement.py`

- 7일 동안 강화 코드 실행하되 **Telegram 발송 X**
- 매매안 JSON 만 `data/alpha_dry_run_YYYYMMDD.json` 누적
- 매일 자정 자동 백테스트로 실시간 가격 매칭
- 7일 후 4개 Success Criteria 임계 검증:
  - `expectancy_r ≥ 0.30`
  - `IC ≥ 0.08`
  - `헛시그널 차단율 ≥ 30%`
  - `운영 비용 < $30/월`

### 작업 3: 임계 통과 시 운영 적용 (1일)

**임계 통과**:
- `ENABLE_ALPHA_PHASE_*=1` 모두 활성
- Telegram 발송 재개
- Memory index 갱신 + 운영 가이드 작성

**임계 미달**:
- 어느 phase 가 문제인지 백테스트로 식별
- 해당 phase `git revert`
- `feedback_alpha_phase_N_failed_YYYYMMDD.md` 작성

**예상 일정**: 8~10 작업일 (1주 dry-run 포함)

---

## 위험 요소 + 완화책

| 위험 | 가능성 | 영향 | 완화책 |
|------|--------|------|--------|
| **KIND XML 스키마 변경** | 낮음 | 중 (블랙리스트 무력화) | 스키마 변경 감지 + fallback (캐시 7일 유지) |
| **백테스트 결과가 임계 미달** | 중 | 큼 (R&D 실패) | A/B 비교로 어느 phase 가 문제인지 식별 → 해당 phase 만 revert |
| **LLM hallucination — agent verdict 가 evidence 와 모순** | 중 | 중 | JSON 출력 강제 + evidence_keys 검증 + reasoning 키워드 매칭 검사 |
| **LLM 비용 초과 ($30/월)** | 낮음 | 중 | score-pass TOP 5~10 만 검증 + Phase 4 토글로 즉시 비활성 |
| **agent_verdict 정확도 < 백테스트** | 중 | 큼 (agent 무가치) | Plan A+B 만 도입하고 Plan C 보류 결정 가능 — 독립적 가치 |
| **데이터 소스 (KRX, FnGuide) 차단** | 낮음 | 중 | 캐시 7일 유지 + 다중 소스 fallback (이미 구현 패턴 존재) |
| **scheduler 데몬 다중 실행** | 낮음 | 중 | 로또 작업에서 검증됨 — heartbeat thread 안정성 OK |

---

## 검증 매트릭스 (전체)

| 검증 항목 | Plan A | Plan B | Plan C | Plan D |
|---------|--------|--------|--------|--------|
| 단위 테스트 | ~15개 | ~10개 | ~25개 | ~20개 |
| 통합 테스트 | scanner_run() 회귀 | MultiAIConsensusScreener 회귀 | E2E pipeline (mock LLM) | E2E (실제 LLM) |
| 라이브 검증 | 1일 dry-run | A 백테스트 효과 | 1일 dry-run | **1주 dry-run + Success Criteria** |
| 백테스트 임계 | A 단독 | A+B 누적 | A+B+C 누적 | **최종 4개 임계 통과** |

---

## 결정 필요 사항 (사용자 confirm 필요)

다음 항목 중 의견 / 결정 필요:

1. **Plan A 부터 시작 OK?** — 또는 다른 Plan 우선?
2. **Plan A 만 도입하고 멈출 가능성**: A 백테스트 결과에 따라 Plan B/C/D 보류 결정 가능. 이 옵션 열어둘지?
3. **LLM 모델 선택**: Plan C 에서 Gemini Flash 만 사용 (월 $12~24) vs Gemini + GPT-4o 둘 다 (월 $30~60)?
4. **Telegram 발송 정책**: Plan C dry-run 중 매매안을 채널에도 발송할지 (자랑/인사이트 공유), 개인봇만 (테스트)?
5. **운영 시작 시점**: 모든 Plan D 통과 후 한 번에 vs Plan A 통과 시점부터 부분 운영?

---

## 다음 단계

위 결정 사항 confirm 후:

1. **writing-plans 스킬 invoke** → Plan A 의 정식 implementation plan 작성
   - 위치: `docs/superpowers/plans/2026-05-24-alpha-scanner-plan-a.md`
   - 각 작업을 2~5분 단위 step 으로 분해
   - TDD 사이클 (실패 테스트 → 구현 → 통과)
2. **Plan A 구현 시작** (subagent-driven 또는 inline 선택)
3. Plan A 완료 + 백테스트 통과 → Plan B 진행 결정
4. (이하 반복)

---

## 부록: 관련 파일 목록

### Plan A 변경 파일
- 신규: `app/services/mirofish/blacklist.py`
- 신규: `scripts/backtest_alpha_signals.py`
- 신규: `tests/services/mirofish/test_blacklist.py`
- 신규: `tests/services/mirofish/test_false_signal_gates.py`
- 신규: `tests/scripts/test_backtest_alpha.py`
- 수정: `app/services/mirofish/alpha_scanner.py:1144~1176`
- 수정: `scheduler.py` (일일 cron 등록)

### Plan B 변경 파일
- 신규: `app/services/mirofish/sector_rs.py`
- 수정: `engine/llm_analyzer.py:MultiAIConsensusScreener`
- 수정: `app/services/mirofish/alpha_scanner.py` (Signal 모델 확장)
- 확장: `tests/test_multi_ai_consensus.py`

### Plan C 변경 파일
- 신규: `app/services/mirofish/agent_evidence.py`
- 신규: `app/services/mirofish/agent_validator.py`
- 신규: `app/services/mirofish/trade_plan.py`
- 신규: `tests/services/mirofish/test_evidence_collector.py`
- 신규: `tests/services/mirofish/test_agent_validator.py`
- 수정: `engine/position_sizer.py` — `calculate_with_atr()` 추가
- 수정: `app/services/mirofish/alpha_scanner.py` (pipeline 통합)

### Plan D 변경 파일
- 신규: `tests/services/mirofish/test_scorer_factors.py`
- 신규: `scripts/dry_run_alpha_enhancement.py`
- 신규: `data/alpha_dry_run_YYYYMMDD.json` (자동 생성)

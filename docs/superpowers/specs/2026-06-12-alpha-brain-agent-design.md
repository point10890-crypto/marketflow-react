# MiroFish Alpha Brain Agent — 설계 문서

- 날짜: 2026-06-12
- 상태: 사용자 승인 완료 (브레인스토밍 종결)
- 범위: `app/services/mirofish/` 에이전트 자율 계층 신규 설계

## 1. 배경과 문제

MiroFish 알파 파이프라인(스캐너 → auto_runner → GraphRAG TOP3 → outcome_tracker → 백테스트 → learning_policy)은 각 단계가 코드로 존재하지만, **피드백 루프가 실제로 닫힌 적이 없다**:

- 백테스트 아티팩트 stale (확인 시점 기준 마지막 생성 2026-06-05, 샘플 32건 < 최소 100건)
- `outcome_tracker` 평가 샘플 0건 — 자동 호출 경로 부재
- 결과적으로 `learning_policy`는 항상 `observe_only` — bounded 학습이 한 번도 활성화되지 않음

또한 MCP 도구 표면(FastMCP :8765, 읽기 21종 + 가드된 변형 4종, 감사 로그, 뮤테이션 게이트)은 존재하지만 이를 호출해 판단하는 **에이전트 두뇌가 없다** (`hermes_bridge`는 계약만 정의).

## 2. 목표

**학습 시스템으로 분석력을 강화해 종목 검출이 수익화 가능한 인텔리전트 시스템 구축.**

에이전트의 단일 목적 함수: **Top3 추천의 전방 수익 기대값** (`outcome_tracker` 5/10/20일 horizon expectancy_r + hit rate). 운영 자동화(신선도 유지 등)는 이 KPI를 달성하기 위한 수단이다.

사용자 결정 사항:
- 자율성: **완전 자율 (bounded 범위 내)** — 파라미터·가중치 조정까지 승인 없이 적용, 단 하드 바운드 + 자동 롤백 + 감사 필수
- 런타임: **인프로세스 Python 사이클 루프** (기존 `llm_client` 폴백 체인: deepseek → openai → gemini)
- 아키텍처: **A안 사이클형** (Sense → Think → Act → Learn)

## 3. 아키텍처 개요

신규 모듈 `app/services/mirofish/alpha_brain_agent.py` (+ 보조 모듈 `edge_map.py`).

```
[scheduler 16:30 / 23:30 KST]
        │
        ▼
┌─ Sense (결정론적) ─────────────────────────────┐
│ 파이프라인 스냅샷·백테스트·outcome KPI·학습정책  │
│ + edge_map 재계산 + 직전 결정 자기평가          │
└────────────────┬───────────────────────────────┘
                 ▼
┌─ Think (LLM 1회, 구조화 JSON 강제) ────────────┐
│ 관찰 + 엣지맵 통계 + 자기평가 → 결정 목록 생성  │
└────────────────┬───────────────────────────────┘
                 ▼
┌─ Act (화이트리스트 실행기, LLM 불신뢰) ────────┐
│ 액션별 바운드 재검증 → 실행 or 기각             │
│ 가중치 변경은 반드시 오프라인 리플레이 선검증    │
└────────────────┬───────────────────────────────┘
                 ▼
┌─ Learn ────────────────────────────────────────┐
│ agent_journal.jsonl 기록 → 다음 사이클 자기평가 │
└────────────────────────────────────────────────┘
```

## 4. 컴포넌트

### 4.1 Sense — `build_agent_observation()`

결정론적 스냅샷 빌더. `autonomous_mcp` 읽기 함수 재사용:
- 파이프라인 운영 스냅샷, 백테스트 daily/rolling 요약, outcome KPI, `learning_policy` 상태
- **엣지맵** (4.2) 최신본
- 직전 사이클 결정들의 사후 성과 비교 (파라미터 조정 baseline 대비 expectancy_r/IC 변화 — 결정론적 계산)
- 신선도 진단: 백테스트 stale 여부, 미평가 outcome 수

### 4.2 Edge Map — `edge_map.py` (신규, 결정론적 패턴 마이닝)

평가 완료된 outcome 전체를 특징 버킷별로 집계해 `data/admin_mirofish/edge_map.json` 생성:

- 축: 섹터, 테마 태그, 알파 점수 구간, 시장 레짐(market_gate), 수급 프로파일(외인/기관 5일), 거래대금 구간
- 버킷 값: hit_rate, expectancy_r, sample_count, horizon별 분해
- 최소 샘플 미만 버킷은 `insufficient` 표기 (LLM이 과신하지 않도록)
- lookahead-safe: 평가 완료(horizon 경과) 표본만 사용

LLM 판단의 원료. 에이전트는 감이 아니라 검증된 수익 패턴 통계 위에서 가설을 세운다.

### 4.3 Think — LLM 결정

`llm_client` 폴백 체인 1회 호출. 출력은 구조화 JSON:

```json
{
  "assessment": "현 상태 요약 판단",
  "hypotheses": [
    {"id": "h1", "statement": "RISK_ON × 외인+기관 동시매수 태그 과소반영", "proposed_delta": {"tag": "...", "delta": 1.5}}
  ],
  "decisions": [
    {"action": "refresh_outcomes", "reason": "..."},
    {"action": "test_hypothesis", "hypothesis_id": "h1", "reason": "..."}
  ],
  "confidence": 0.8
}
```

스키마 검증 실패 시 1회 재시도, 재실패 시 "no decision" 저널 기록 후 사이클 정상 종료.

### 4.4 Act — 화이트리스트 액션 실행기

LLM 결정을 그대로 실행하지 않는다. 실행기가 액션별 하드 바운드를 재검증하고, 범위 밖 결정은 기각 + 저널 기록.

| 액션 | 효과 | 가드 |
|---|---|---|
| `refresh_backtest` | `backtest_alpha_signals` 재실행 (in-process) | 사이클당 1회 |
| `refresh_outcomes` | 최근 워크플로우 outcome 일괄 평가 (`outcome_tracker`) | 최근 50개 워크플로우 한정 |
| `refresh_learning_feedback` | 기존 `autonomous_mcp.refresh_learning_feedback` | — |
| `test_hypothesis` | 제안된 점수 델타를 **과거 데이터 오프라인 리플레이**로 검증 | lookahead-safe 리플레이만; 사이클당 최대 2건 |
| `apply_scoring_delta` | 리플레이 **통과한** 가설만 `learning_policy` bounded tag/global delta 메모리에 적용 | 기존 캡 준수 (tag ±2.0, global ±3.0); 리플레이 미통과 시 실행기가 기각 |
| `trigger_reanalysis` | 손실 추천 부검(post-mortem) 워크플로우 재실행 | 일일 비용캡 공유, 최대 2종목/사이클 |
| `adjust_parameter` | `agent_overrides.json`에 임계값 기록 | min_alpha [60,85]·사이클당 ±3, max_risk [35,55]·±3, min_top_score [40,70]·±5 |
| `revert_parameter` / `revert_scoring_delta` | 오버라이드/델타 제거 | — |
| `send_brief` | 사이클 요약 텔레그램 (**개인봇만**, channel=False) | 사이클당 1회 |

**가중치 변경의 불변 조건: 검증 없이 적용되는 변경은 존재하지 않는다.**
`엣지맵 통계 → 가설 → 오프라인 리플레이 사전 검증 → bounded 적용 → 실전 outcome 사후 검증 → 악화 시 자동 롤백` — 이중 검증이 수익화 가능한 학습의 안전 조건.

`agent_overrides.json` 소비 우선순위: **env 명시값 > 에이전트 오버라이드 > 코드 기본값**. `auto_runner._tunables()`와 스캐너 임계값 로딩에 오버라이드 계층 삽입. env가 항상 이기므로 사람이 언제든 강제 가능(킬스위치).

### 4.5 Learn — 의사결정 저널

`data/admin_mirofish/agent_journal.jsonl` (append-only):
- 매 사이클: 관찰 요약, KPI 스냅샷, 가설, 결정, 실행/기각 결과, 적용 시 baseline 지표
- 기각된 가설도 기록 (기각 사유가 다음 사이클 프롬프트의 학습 재료)
- 다음 사이클 Sense에서 직전 조정의 실제 성과를 결정론적으로 비교 → 자기평가 텍스트 생성 → Think 프롬프트 주입

### 4.6 손실 부검 (재분석의 목적)

`trigger_reanalysis`는 stop-loss 도달 또는 horizon 수익 음수인 추천을 대상으로 "어떤 신호가 거짓이었나"를 분석하고, 결과를 음수 태그 델타 후보와 엣지맵 보강으로 환류한다. 손실 패턴 차단이 수익률 개선의 최단 경로.

## 5. 스케줄링

`scheduler.py`에 등록 (miniPC 운영 기준):

| 시각 (KST) | 사이클 | 주요 판단 |
|---|---|---|
| 16:30 | 장 마감 사이클 | 당일 검출 품질 리뷰, outcome 갱신, 손실 부검, 재분석 |
| 23:30 | 백테스트 후 사이클 | 백테스트 해석, 가설 검증, 델타 적용/롤백 |

23:00 백테스트가 실행되지 않았으면 23:30 사이클이 `refresh_backtest`로 직접 복구한다.

## 6. 안전장치

1. **자동 롤백 (결정론적, LLM 무관)**: 조정 시 baseline (expectancy_r, IC) 저장 → 이후 2회 연속 백테스트에서 baseline 대비 악화 시 실행기가 강제 revert
2. **서킷 브레이커**: 3회 연속 사이클 실패 → 24시간 정지 (auto_runner 패턴)
3. **비용캡**: 사이클당 LLM 1~2회; 재분석은 auto_runner 일일 $5 캡 공유
4. **감사**: 전 액션 `audit.jsonl` 기록 (기존 autonomous_mcp 패턴)
5. **단계적 활성화**: 첫 주 `MIROFISH_AGENT_DRY_RUN=1` — 유지보수 액션(백테스트/outcome 갱신)만 실제 실행, 델타·파라미터 조정은 제안만 저널 기록. 저널 검토 후 완전 자율 전환
6. **킬스위치**: `MIROFISH_AGENT_ENABLED=0` + env 우선순위
7. **금지 행위**: 기존 `PROHIBITED_ACTIONS` 준수 (주문 실행, 시크릿 접근, 파괴적 파일시스템 조작 불가)

## 7. 가시성

- `GET /api/admin/mirofish/agent/status` — 상태, 활성 오버라이드/델타, KPI 추이, 최근 저널 20건 (`admin_mirofish` 라우트 확장)
- MCP 도구 `get_agent_brain_status` (기존 `mcp_server` 패턴)
- 프론트 관리자 카드는 후속 작업 (이번 범위 제외)

## 8. 우선순위 (구현 순서)

| 순위 | 항목 | 이유 |
|---|---|---|
| 1 | outcome 자동 평가 + 엣지맵 | 학습 원료. 현재 0건 — 이것 없이는 어떤 지능도 불가 |
| 2 | 백테스트 신선도 자가 유지 | 검증 장치 확보 |
| 3 | 가설 → 리플레이 → bounded 델타 루프 | 분석력 강화의 본체 |
| 4 | 손실 부검 재분석 | 음수 패턴 제거 |
| 5 | 임계값 튜닝 (`adjust_parameter`) | 보조적 |

## 9. 에러 핸들링

- LLM 전 폴백 실패 → "no decision" 저널 기록, 사이클 정상 종료 (유지보수 액션은 결정론적 규칙으로 LLM 없이도 실행: stale 감지 시 자동 refresh)
- 액션 개별 try/except 격리 — 한 액션 실패가 사이클 전체를 죽이지 않음
- 저널/오버라이드 쓰기는 `write_json_atomic` 사용

## 10. 테스트 전략

LLM 전부 모킹. 핵심 테스트 (`tests/test_mirofish_alpha_brain_agent.py`, `tests/test_mirofish_edge_map.py`):

1. 결정 JSON 스키마 검증·기각 경로
2. 실행기 바운드 강제 (범위 밖 델타/파라미터 기각)
3. 리플레이 미통과 가설의 `apply_scoring_delta` 기각
4. 자동 롤백 트리거 (2회 연속 악화)
5. 오버라이드 우선순위 (env > agent > default)
6. 서킷 브레이커 개폐
7. stale 백테스트 감지 → `refresh_backtest` 경로
8. 엣지맵 집계 정확성 + 최소 샘플 `insufficient` 처리 + lookahead-safe 필터
9. 드라이런 모드에서 변형 액션 차단

## 11. 비범위 (이번 작업에서 제외)

- 프론트엔드 관리자 카드 UI
- 상주형 ReAct 데몬 (B안) — 구조는 확장 가능하게 두되 구현하지 않음
- 멀티 에이전트 토론 통합 (C안)
- 실주문/매매 연동 (영구 금지 항목)

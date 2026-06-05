# Worker Routing Rules

## Decision Tree

```
작업 성격 파악
│
1. 메인 코딩 / 디버깅 / 기획 · 설계 · 요구사항 · 전략 · 문서화?
│   └── claude-main
│
2. claude-main 산출물 리뷰 / 비판적 검증?
│   └── codex-critic   (Codex의 주된 역할)
│
3. 보조 구현 / 코드 분석 / 테스트 / 이미지 생성?
│   └── codex-main
│
4. 이미지 · 스크린샷 분석 / 50페이지+ 문서 / 제3자 시각의 검토?
│   └── gemini
│
└── 판단 어려움?
    └── claude-main으로 시작 후 필요 시 추가
```

## 복합 작업 우선순위

한 작업이 여러 분기에 해당할 때:

1. **선행 의존성 우선**: codex-critic은 리뷰 대상(보통 claude-main 결과)이 먼저 있어야 함 → 해당 산출물 뒤에 호출
2. **Orchestrator 내부 추론 우선**: 별도 worker 호출 전에 orchestrator 자체 추론으로 해결 가능한지 먼저 판단. 그래도 부족할 때만 claude-main 호출 (claude-main도 비용·쿼터 대상)
3. **검증은 한 번만**: codex-critic은 작업당 1회 원칙. 재호출은 검증 실패 시만
4. **gemini는 명시적 트리거 시만**: 멀티모달 또는 "제3자 시각의 검토 필요" 명시 없으면 호출 금지

## 토폴로지 패턴 (worker를 어떻게 엮을까)

decision tree로 "누구를" 고른 뒤, "어떻게 엮을지" 고른다. **단일 orchestrator 구조에 맞는 4패턴만** 쓴다.

| 패턴 | 언제 | 이 시스템에서 |
|------|------|-------------|
| Pipeline (순차) | 앞 결과가 뒤 입력 | 기본. claude-main → codex-critic → claude-main(반영) |
| Fan-out/Fan-in (병렬→통합) | 서로 독립된 산출물 여럿을 하나로 통합 | 예: claude-main(코드) ∥ gemini(이미지). 각 brief에 "타 worker 결과 미참조" 명시. 통합은 아래 Fan-in 규칙 |
| Expert Pool (전문가 선택) | 작업 성격에 맞는 worker만 | 새 실행 패턴이 아니라 **worker 선택 정책** — 위 decision tree + 최소 worker set이 곧 이 패턴 |
| Producer-Reviewer (생성+게이트) | 산출물 품질 검증 필요 | claude-main(생성) → codex-critic(adversarial 게이트) |

**금지**: 같은 입력에 같은 종류 worker 동시 호출 (예: claude-main 2개).
**배제**: Supervisor(별도 long-lived 조정자 worker/런타임 동적분배 계층 추가)·Hierarchical Delegation(worker가 worker를 부르는 재귀 위임)은 단일 orchestrator·worker간 무통신·file-as-memory와 충돌 → 미사용.

### Fan-in 규칙 (병렬 결과 통합)

병렬 worker 결과를 orchestrator가 하나로 합칠 때:
1. 각 worker 원문을 `result.md`에 그대로 보존 (요약본만 남기지 말 것 — telephone game 방지)
2. 결과가 충돌하면 삭제 금지 → 양쪽 출처 병기, 권위 우선순위/사실검증으로 해소, `log.md` [DECISION]에 근거 기록
3. 통합 결론 한 줄을 `context.md`에 기록

## Worker 역할 상세

### claude-main
- **용도**: 메인 코딩, 디버깅, 기획, 요구사항 정의, 설계 문서, 사용자 스토리, 아키텍처, 전략 수립
- **결과물**: 코드 (구현·수정·diff), 설계 문서, 구조도, 의사결정 근거
- **호출 명령**: Claude Code 내장 **Task tool (sub-agent)**
  - `subagent_type`: `claude-main`
  - `prompt`: brief.md 내용 그대로 전달
  - `model`: `gemini-2.5-pro` (또는 현 에이전트 환경의 Pro 모델)
  - `description`: 짧은 작업명 (3~5 단어)
- **비용**: 있음 → 승인 필요
- **파일 쓰기**: 직접 수행하지 않으며, 반환된 텍스트를 Orchestrator가 받아 `result.md`에 기록.

### codex-main
- **용도**: 보조 구현 (claude-main 산출물 기반), 코드베이스 분석, 리팩토링, 테스트 작성, diff 생성, 로컬 CLI 검증
- **결과물**: 코드, diff, 테스트 결과, CLI 출력

### codex-critic
- **용도**: `claude-main` 및 `codex-main` 산출물의 논리 검증, 엣지 케이스 점검, 보안 취약점 비평
- **결과물**: 비평 보고서, 개선 권고 사항

### gemini
- **용도**: 긴 문서/로그 분석, 멀티모달 분석(차트 이미지 등), 제3자의 객관적 검토
- **결과물**: 종합 분석 및 요약 보고서

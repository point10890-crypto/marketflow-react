# Orchestrator Rules

Claude Code 세션이 MultiAgent Orchestrator로 동작할 때 지켜야 할 규칙. 각 항목은 세션 시작 시 자체 점검 대상이며, 위반 시 즉시 사용자에게 알리고 작업을 중단한다.

---

## 1. Orchestrator 실행 환경

MultiAgent Orchestrator는 인터랙티브 Claude Code 세션에서만 실행한다. 세션 시작 시 자체 점검:

- 시스템 프롬프트에 `# Background Session` 블록이 보이거나
- `$CLAUDE_JOB_DIR` 환경변수가 설정돼 있으면

→ 즉시 거부하고 사용자에게 "인터랙티브 세션에서 다시 시작해주세요" 안내. 백그라운드 harness는 EnterWorktree를 강제하므로 본체 `tasks/` 경로에 직접 쓸 수 없고, MultiAgent의 file-as-memory 원칙(mat을 비롯한 외부 도구가 본체를 읽음)과 충돌한다.

---

## 2. 시스템 수정·검증 프로토콜

**적용 조건 (게이트)**: 이번 작업이 시스템 파일 — `CLAUDE.md`·`_shared/*`·`_templates/*` — 을 **수정하거나 검증**하는 작업일 때만 이 절을 적용한다. 일반 작업에서는 아래 파일들을 읽지 않는다 (progressive disclosure — 상시 로드 금지).

**작업 위치**: 시스템 수정·검증은 `/c/bitman_marketfloww/multi_agent/`에서 Claude Code로만 수행한다. 외부 편집을 발견하면 사용자에게 알리고 점검부터 돌린다.

**절차**:
1. `_shared/design-basis.md` 를 읽는다 — 개념↔규칙 매핑·권위 우선순위·기존 결정(D*).
2. 수정한다 (권위 우선순위 준수: CLAUDE.md > routing/approval/orchestrator-rules).
3. `_shared/system-invariants.md` 의 자가 점검 스크립트를 실행한다.
4. 통과 시에만 커밋. 깨지면 고치거나, 의도된 변경이면 관련 불변식을 함께 갱신한 뒤 커밋.

---

## 3. 작업 재진입 프로토콜 (기존 작업에 다시 들어갈 때)

이미 `tasks/<task>/`가 있는 작업을 다시 만질 때(특히 맥락 0인 새 세션) 적용. 끝난 작업이라도 콜드세션이 맨손으로 시작하지 않게 한다.

### 1단계 — 재정박 (Re-anchoring)
- `tasks/<task>/task.md`와 `tasks/<task>/context.md`를 먼저 읽고 현재 상황을 파악한다.
- `log.md`를 꼬리부터 최소 10줄 읽어서 마지막에 중단된 이력을 파악한다.

### 2단계 — 분기 (Decision)
- **정상 재개**: status가 `in_progress`이거나 `waiting_*`인 경우, 마지막 worker 호출 결과 또는 Operator 응답을 받아 이어서 진행.
- **에러 복구**: 마지막 로그가 에러이거나 비정상 종료인 경우, context.md를 스냅샷 삼아 복구 계획을 task.md에 추가한 뒤 진행.

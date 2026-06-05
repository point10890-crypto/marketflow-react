# MultiAgent Orchestration — Operating Rules

## Architecture

```
Orchestrator (Claude Code session, internal reasoning)
└── Worker Pool (모두 외부 호출 — 승인 필요)
    ├── claude-main    메인 코딩 · 디버깅 · 설계 · 아키텍처 · 전략
    ├── codex-main     보조 구현 · 코드 분석 · 테스트 · diff · 로컬 검증 · 이미지 생성
    ├── codex-critic   산출물 리뷰·비평 (Codex의 주된 역할)
    └── gemini         멀티모달 · 긴 문서 · 제3자 시각의 검토
```

**중요**: Orchestrator의 내부 추론은 worker가 아님. claude-main worker 호출은 별도 모델 호출이므로 승인·쿼터 대상.

## Task Lifecycle

1. `tasks/<task-name>/task.md` 작성 (status: pending)
2. `_shared/routing.md` 참조 → 최소 worker set 결정
3. **target_repo 확인** (외부 산출물 작업인 경우):
   - 본 프로젝트의 기본 target_repo는 `/c/bitman_marketfloww` (또는 `c:/bitman_marketfloww`) 입니다.
   - codex-main이 planned_workers에 포함되거나 코드·문서·이미지를 만드는 작업이면 사용자에게 `target_repo` 경로를 묻습니다.
   - 사용자가 "없음"이라고 답하거나 분석·리뷰·요약·기획만 하는 작업이면 묻지 않고 `tasks/<task>/artifacts/`에 diff·patch로 산출합니다.
   - 사용자가 자연어 요청에 이미 경로를 포함했으면 다시 묻지 않습니다.
4. 모든 worker(claude-main 포함) 사용 시 `task.md`의 `workers_approved`에 명시적 기록 필요
5. 각 worker에 `brief.md` 작성 (≤ 1200자 한글 / 240단어 영문)
6. worker 실행 → `result.md` 저장
7. `result.md`의 Verification Checklist 실행
8. 검증 결과를 `log.md`에 append (`[VERIFICATION]` 태그)
9. 완료 후 교훈 추가 (분류): **시스템 운영 자체**에 대한 일반 교훈 → `_shared/learnings.md`(추적·공개). **특정 외부 프로젝트 한정**(mat·hwpx 등) → `_local/learnings.md`(git 추적 안 함, 없으면 생성). `_local/learnings.md`는 명시 요청 없이는 로드하지 않는다.

> **기존 작업 재개 시**(새 세션 포함)는 1번부터가 아니라 `_shared/orchestrator-rules.md` §3 **재진입 프로토콜**을 먼저 따른다 (재정박 → 분기 → 에러 후 진행).

## Context Rules

| 파일 | 제한 (측정 가능 기준) | 목적 |
|------|------------------|------|
| `context.md` | ≤ 1500자 (한글) / ≤ 300단어 (영문) | 현재 스냅샷만. 히스토리 아님 |
| `brief.md` | ≤ 1200자 (한글) / ≤ 240단어 (영문) | worker가 실행에 필요한 것만 |
| `sources/` | 무제한 | 원본 자료. 경로로만 참조 |
| `artifacts/` | 무제한 | worker 산출물 원본 |

**측정 명령어 (Git Bash / WSL)**:
```bash
wc -m tasks/<task>/context.md   # 한글 글자수 (UTF-8 multi-byte)
wc -w tasks/<task>/context.md   # 영문 단어수
```

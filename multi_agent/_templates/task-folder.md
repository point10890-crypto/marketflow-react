# Task Folder Setup Guide

새 작업 시작 시 이 가이드대로 폴더와 파일을 생성한다.

## 폴더 구조

```
tasks/<task-name>/
├── task.md              # 필수. _templates/task.md 복사
├── context.md           # 필수. 현재 스냅샷, ≤ 1500자 한글 / 300단어 영문
├── log.md               # 필수. _templates/log.md 복사. append-only
├── sources/             # 선택. 원본 자료 (긴 문서, 참고 데이터 등)
│   └── *.md, *.csv, *.txt
├── workers/             # worker 호출 시 동적 생성
│   └── <role>/          # claude-main | codex-main | codex-critic | gemini
│       ├── brief.md     # _templates/worker-brief.md 복사. ≤ 1200자 한글
│       └── result.md    # _templates/worker-result.md 복사
└── artifacts/           # 선택. worker 산출물 원본
    └── *
```

## 생성 절차

### Step 1: 작업 폴더 + 필수 파일

```bash
TASK=my-task-name
ROOT=/c/bitman_marketfloww/multi_agent
mkdir -p "$ROOT/tasks/$TASK"
cp "$ROOT/_templates/task.md"    "$ROOT/tasks/$TASK/task.md"
cp "$ROOT/_templates/log.md"     "$ROOT/tasks/$TASK/log.md"
cp "$ROOT/_templates/context.md" "$ROOT/tasks/$TASK/context.md"
```

### Step 1.5: target_repo 확인 (외부 산출물 작업인 경우)

codex-main이 planned_workers에 포함되거나 코드·문서·이미지를 만드는 작업이면, task.md 채우기 전에 사용자에게 짧게 묻는다:

> "이 작업의 산출물이 들어갈 외부 폴더(target_repo)가 있나요?
> (기본값: /c/bitman_marketfloww. 없으면 tasks/<task>/artifacts/에 diff로 남깁니다)"

답을 task.md의 메모 또는 후속 brief.md의 `target_repo` 필드에 기록한다.

**예외 (묻지 않음)**:
- 분석·리뷰·요약·기획만 하는 작업 (gemini 단독 또는 claude-main 단독 문서 작성)
- 사용자가 자연어 요청에 이미 target_repo 경로를 포함한 경우

### Step 2: task.md 채우기

- `status: pending` → 작업 진행에 따라 갱신
- `goal`, `constraints`, `acceptance criteria` 작성
- `planned_workers`에 `_shared/routing.md` 참조하여 최소 set만 명시
- `workers_approved`는 비워두고 승인 후 채움

### Step 3: context.md 작성

- 현재 시점 스냅샷만 (히스토리 X)
- 1500자 한글 / 300단어 영문 이하 강제 (`wc -m` / `wc -w`로 측정)
- 긴 자료는 `sources/`에 두고 경로로 참조

### Step 4: 자료 추가 (선택)

```bash
mkdir -p "$ROOT/tasks/$TASK/sources"
# 원본 자료 복사 또는 작성
```

### Step 5: Worker 호출 시 (승인 후)

#### 5-1. brief 먼저 생성·작성
```bash
ROLE=claude-main  # 또는 codex-main, codex-critic, gemini
mkdir -p "$ROOT/tasks/$TASK/workers/$ROLE"
cp "$ROOT/_templates/worker-brief.md" "$ROOT/tasks/$TASK/workers/$ROLE/brief.md"
# brief.md 작성 (≤ 1200자)
```

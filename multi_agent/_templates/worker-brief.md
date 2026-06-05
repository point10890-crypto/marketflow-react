# Brief — [worker-role] / [작업명]

<!-- HARD LIMIT: 1200자 한글 / 240단어 영문 (wc -m / wc -w). 파일 내용 inline 금지. 경로만 전달. -->

## Execution Context (codex-main / codex-critic 필수)

```yaml
target_repo: /c/bitman_marketfloww    # 작업 대상 절대 경로 (없으면 N/A)
write_scope: none             # none | tasks-only | "src/**, tests/**" 등 패턴
                              # 외부 repo 쓰기는 task.md workers_approved에 별도 승인 필요
```

## Objective

한 문장. 이 worker가 완료해야 하는 것.

## Input

```
# 파일 경로로만 참조. 내용을 여기에 붙여넣지 말 것.
task:    tasks/<task-name>/task.md
context: tasks/<task-name>/context.md
sources: tasks/<task-name>/sources/<파일명>
```

## Task Details

<!-- 구체적인 지시 사항 및 요구하는 최종 결과물(output_format) 지정 -->
1. 지시사항 1
2. 지시사항 2

## Output Format

<!-- 예: Markdown 표, 코드 diff 등 기대하는 포맷 설명 -->

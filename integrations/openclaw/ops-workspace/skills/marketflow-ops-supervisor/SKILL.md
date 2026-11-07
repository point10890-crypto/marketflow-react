---
name: marketflow-ops-supervisor
description: Use when the administrator asks whether MarketFlow is healthy, why a menu page is broken, what an incident means, or what to do next, using the read-only Control Center MCP.
user-invocable: true
---

# MarketFlow operations review

Use only available `marketflow_ops__*` tools. Never guess a tool name.

## Read

1. `marketflow_ops__get_control_center_summary` — always first.
2. `marketflow_ops__list_control_center_incidents` — `state="open"` for now,
   `state="recent"` for "what happened today".
3. `marketflow_ops__get_control_center_check_history` — one `check_id` at a time.
4. `marketflow_ops__get_control_center_runbook` — for every failing item you report.

## Diagnose in this order (the first failing layer usually explains the rest)

1. `monitor:*` — is the monitor itself fresh?
2. `port:*`, `heartbeat:*`, `watchdog:*`, `public:*` — are processes and the tunnel up?
3. `security:*` — any protected route answering without a token is the most urgent item.
4. `endpoint:*`, `gate:*` — do the page APIs answer correctly and fast?
5. `data:*`, `job:*`, `task:*` — is data fresh, did scheduled work run?
6. `provider:*`, `host:*` — external APIs, disk, memory, hardware errors.

## Report format (Korean)

- 한 줄 결론: 전체 상태, 회원 영향(어느 메뉴가 안 되는지).
- 원인 사슬: 가장 아래 계층의 실패부터.
- 사람이 할 일: runbook `human` 항목을 그대로, 순서대로. 자동 복구 중이면 그 사실과 기다릴 시간.
- 모르는 것: unknown/skipped 항목과 그 이유.

Never present a proposal as something already done.

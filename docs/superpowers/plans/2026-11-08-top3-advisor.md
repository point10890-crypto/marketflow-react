# TOP3 Advisor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Deliver an authenticated, saved news-grounded TOP3 advisor with actual three-agent debate.
**Architecture:** A deterministic saved-input adapter feeds a resumable three-stage worker. The read API projects only validated saved results; an admin trigger queues work for a bounded scheduler.
**Tech Stack:** Existing Flask/Python, AIRouter, atomic JSON/filelock, Windows Task Scheduler.
**Spec:** `docs/superpowers/specs/2026-11-08-top3-advisor-design.md`

## Global Constraints

No original AlphaLab/CIO mutations, no orders or new provider/key, no invented facts; share the evidence USD 1/day cap. At most six shortlisted stocks and three final research picks. Completed/charged stages never replay for identical facts. GET is read-only. Stage only intentional source/docs/tests.

## Tasks

- [ ] 1. Input adapter: create `app/services/mirofish/alpha_lab/advisor_inputs.py` and `tests/test_alpha_lab_advisor_inputs.py`. Test sealed real-shaped fixture, union/dedup, exact-symbol news matching, stale/future/binding exclusion, stable fingerprint, deterministic score and preserved plan/hold. Implement the spec's `build_input` contract, independent of debate code.
- [ ] 2. Debate worker: create `app/services/mirofish/alpha_lab/advisor.py` and `tests/test_alpha_lab_advisor.py`. Test role sequence/dependence, local grounding, public projections, per-stage persistence, retry/cost failure boundaries and GET freshness. Consume task 1 contract; use mocked build_input while it is being implemented. Expose `run_once`, `read_view`, `request_refresh`.
- [ ] 3. API/operations: root owns `app/routes/admin_mirofish.py`, CLI/installer `scripts/run_top3_advisor.py`, `scripts/install_top3_advisor_task.ps1`, route/CLI tests and operations docs. Admin POST only enqueues; no synchronous inference. GET existing AI Brain gate. Scheduler own lock/budget shared. Test access/status/errors/arguments/no-secret projections.
- [ ] 4. Integration/review: independently review each task and final diff; correct findings. Run all advisor and existing evidence/routing tests, signal smoke and relevant broader CI. Run a bounded actual saved-input debate; verify restart has no new provider calls and original AlphaLab hashes unchanged. Record evidence privately.
- [ ] 5. Commit/push/CI/deploy: user already authorized delivery. Commit only after tests pass, PR/CI/merge, MiniPC fast-forward/restart via established launcher; install own task and verify health, API auth, source freshness, actual debate output, task execution/reuse. Record release receipt and concise Korean result.

## Review Focus

1. News mentioning multiple companies cannot lend an official claim to the wrong symbol.
2. A recovered/corrupt/stale decision must not appear current even if debate succeeded earlier.
3. Paid output receipt failure or kill must not repay completed/uncertain work.
4. Lack of qualifying entries cannot become artificial buy approval through ranking.
5. An HTTP refresh or source polling clock must not cause paid reruns or API latency.

# AlphaLab evolution implementation plan

> **For agentic workers:** Use superpowers:subagent-driven-development to
> implement each independently reviewed task with its focused test cycle.

**Goal:** Run a real future-only comparison of fixed entry/rank challengers
automatically, preserving original detection evidence and exposing actual progress.

**Architecture:** Pure causal policy/outcome engine; independently locked,
immutable experiment memory; post-publication saved-data hook and read-only
optional status; one shared portrait frontend component.

**Tech Stack:** Existing Python/Flask, standard library, FileLock, React/TypeScript/Vitest.

**Spec:** `docs/superpowers/specs/2026-10-14-alpha-evolution-design.md`.

## Global constraints

No new dependencies, paid APIs, executable generated strategies, live orders,
account approval, modified existing research/ranking/Kelly/first decisions, or
historical test reuse as independent evidence. Three fixed challengers; the
first106 future enrolled decision sessions plus10 maturation sessions; first36
nomination,10 embargo and60 confirmation-only rejection; existing ExecutionPolicy; research qualification
awaits review. Exact interfaces and gates are specified in the design.

## Review focus

- Same-day reselection/late enrollment must not erase the first decision or clock.
- Source revisions after closure must preserve result bodies and hold statistics.
- Empty/skipped slots must remain visible rather than improve conditional averages.
- A better confirmation arm must not replace the validation-nominated arm.
- A saved optional sidecar must never collect sources or write during GET.

### Task1: deterministic policy and comparison engine

Owner: engine worker. Create `app/services/mirofish/alpha_lab/evolution.py` and
`tests/test_alpha_lab_evolution.py`.

- [ ] Write failing tests for catalogue, full-pool gates, causal prefixes, frozen
  band entries, source revisions, paired cash/unknown accounting and nomination.
- [ ] Implement `protocol_spec`, `build_cohort`, `observe_cohort`, `summarize`
  exactly as the design. Keep JSON-only public result fields and finite values.
- [ ] Run `python -m pytest tests/test_alpha_lab_evolution.py -q`; fix until green.

### Task2: immutable memory and optional service integration

Owner: root. Create `evolution_store.py`, `scripts/run_alpha_lab_evolution.py`,
store/integration tests; modify only AlphaLab `service.py` and operations docs.

- [ ] Write failing protocol/idempotency/restart/GET/failure-containment tests.
- [ ] Preserve successful stages in the new evolution namespace, refuse corrupt
  and late cohorts, publish bounded status atomically after successful validation.
- [ ] Return full discovery from existing `_add_opportunities`; add isolated
  post-publication refresh and pure saved-status attachment.
- [ ] Run focused store/integration plus existing service/routes/catalyst tests.

### Task3: shared portrait status

Owner: UI worker. Create `AlphaLabEvolutionPanel.tsx`, `evolutionContext.ts`,
corresponding frontend tests; add optional type to `alphaLabApi.ts` and component
to shared `AlphaLabPanel.tsx`.

- [ ] Write failing legacy/null/negative/revision/current-binding tests.
- [ ] Render actual four-arm states/metrics and next step with mobile wrapping;
  absent optional data adds no loading work or account claims.
- [ ] Run focused Vitest, full frontend test/lint/build and390px viewport check.

### Task4: actual evidence, review and release

- [ ] Run engine/store against a real current MiniPC canonical snapshot in
  isolated storage. Preserve its source hashes, timestamps and limitations.
- [ ] Independently review causality, all fixed gates and failure/restart paths.
- [ ] Run full backend CI and frontend validation on exact final tree.
- [ ] Commit only intended source/docs/tests, push, attach PR, merge after CI.
- [ ] Pull committed source on MiniPC; preserve DB and all original data;
  restart existing Flask watchdog; initialize the saved-data-only evolution
  protocol and verify new saved API status without replaying original research.
- [ ] Run authorized frontend deploy, verify actual public API/current identity,
  automatic20:30 hook configuration and deployed390px UI. Save final evidence.

# AlphaLab detection v2 implementation plan

> **For agentic workers:** Use subagent-driven development; write failing tests before implementation, then review and validate each deliverable.

**Goal:** Repair reproduced selection failures and add a causally evaluated new detector without rewriting old decisions.

**Architecture:** New pure v2 discovery and explicit board policy dispatch reuse execution primitives; immutable v1 controls and separate v2 forward evidence remain distinct. Existing member UI accepts known v1/v2 contracts and shows the new policy clearly.

**Tech Stack:** Python/Flask, React/TypeScript/Vite, Windows Task Scheduler.

**Spec:** `docs/superpowers/specs/2026-10-19-alpha-detection-v2-design.md`.

## Constraints and review focus

No secrets/paid API/orders; approved exposure0. No retrospective rewrite, no
winner/threshold tuning, no v1 evolution changes, no expensive GET. Test future
bar perturbation, negative-score and correlation rejection, recent deterioration,
unknown/mixed policy, first-decision immutability, source/plan binding and failure
preservation. Reuse the current source snapshot for offline/isolated validation.

- [x] Detector: failing causal recovery/relative-strength/liquidity/tail tests;
  implement `discovery_v2.py` with fixed policy and historical-prefix execution;
  preserve v1 default output and run focused discovery/execution checks.
- [x] Board: failing v2 negative/after-correlation/legacy/unknown-policy tests;
  implement explicit v2 builder and safe projection/store/account/Telegram
  dispatch; retain v1 builder semantics for frozen controls.
- [x] Integration: failing service tests proving old journal/evolution preservation,
  separate v2 forward/protocol, policy/hash identities and cheap GET. Wire scheduled
  and manual scan paths, bounded public API and current member clients.
- [x] Freeze and run one retrospective comparison; save measured outputs and
  limitations without changing policy thresholds after seeing results.
- [ ] Run focused Python/frontend checks then full CI and build; independent
  review; stage intentional sources only; commit/push/PR/merge tested tree.
- [ ] Deploy exact commit, verify isolated current-input v2 pipeline before normal
  publication, preserve old journal hashes, health/tasks/source identities and
  authenticated mobile member view; record final evidence and realistic limits.

## Measured evidence before deployment

The fixed retrospective comparison produced v1 +2.9493% continuous paper account
return and v2 0% with zero trades. No threshold was adjusted after this result;
improved profit detection is not established. Full51-symbol saved-input service
execution and the real response's frontend validator passed in an isolated root
with network and Telegram disabled. Current v2 selection is empty. Independent
integration review and146 focused tests passed, including date/60th-session arm
recovery, old first/closed-result immutability and exact original control selection.
Final CI/deployment evidence belongs in the private dated review directory, not
in a versioned generated report or a revised historical decision.

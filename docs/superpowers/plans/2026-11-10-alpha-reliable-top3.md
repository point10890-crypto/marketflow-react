# Reliable collection and TOP3 implementation plan

Specification: ../specs/2026-11-10-alpha-reliable-top3-design.md

1. Source worker: dated KIS regular-session minute provider/replay and adversarial unit tests. Own regular_source.py and its tests.
2. Root: immutable input overlay, independent candidate desk orchestration, scheduled/recovery/API/monitor integration and focused tests. Preserve hashed v4 model/store files unchanged.
3. Advisor worker: authoritative desk adapter, sealed-order advisor behavior, source/entry-ceiling UI and tests. Coordinate exact directory contract with root.
4. Independent review: source semantics, chronology, raw replay, first-decision preservation, failure/empty states, budget and UI.
5. Root: focused then wider tests/build; real-data diagnostic receipt; commit only intentional sources after green checks; CI, committed MiniPC/backend deployment, frontend deployment, task/API/mobile/PC verification.

Ruling: existing explicit implementation/commit/push/deploy authorization continues; no additional approval loop. No new paid API, account permission, real orders, or automatic trading exposure.
Ruling: keep the original model parameters. Data normalization and deterministic candidate provenance are the interventions; new source cohort is evaluated prospectively from the next declared session.

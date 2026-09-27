# JEV shadow implementation / execution ledger

Spec: docs/jev_pipeline_rd_2026_09_28/REPORT.md in original development checkout.
Approved: implement, test, commit, push and deploy without intermediate confirmation.

Ruling: deploy an operational shadow research pipeline, not an untrained live ranker.
There is no verified TypeSafe key or point-in-time training dataset. Production ranks,
orders and notifications must not depend on the experimental scores. Learned ranking
and performance promotion require measured data, not synthetic fixtures.

## Tasks
1. Contracts and fixed official-provider adapter; redact errors, validate distributions,
   require timestamps, retain unknown, bound requests. RED -> GREEN.
2. Durable candidate snapshots, idempotent evaluation, raw response and feature export;
   no calls on GET/status; explicit live opt-in; SQLite claim for duplicate workers.
3. Workflow snapshot integration; admin-only status/snapshot/evaluation endpoints;
   offline chronological evaluation CLI. RED -> GREEN.
4. Focused and broad backend regression tests; fresh independent branch review.
5. Commit/push, fast-forward production source, restart MarketFlow-Flask only;
   local/public health and authenticated feature smoke. Preserve production data.

Ruling: existing frontend change belongs to previous user request; leave it untouched.
Backend-only implementation requires no frontend asset redeploy.
Pre-flight: shared contract is snapshot -> request -> validated response -> features;
unknown/errors are never numerically converted to neutral or used for live ranking.

## Progress
- Setup: isolated managed worktree; base deefad686a99; production reachable via SSH minipc.
- Credentials: local TYPESAFE_API_KEY / TYPESAFE_AI_API_KEY absent (values not printed).

## Operations

This release is backend-only. Production ranking is unchanged. Workflow creation
captures all scanner candidates before admission limits; no provider call is automatic.

- `python scripts/mirofish_semantic_shadow.py status`
- `python scripts/mirofish_semantic_shadow.py snapshot --input scanner-run.json`
- `python scripts/mirofish_semantic_shadow.py evaluate --snapshot-id js_<id>`
- `python scripts/mirofish_semantic_shadow.py export --snapshot-id js_<id> --output rows.json`
- `python scripts/mirofish_semantic_shadow.py train-evaluate --input labeled.json --output comparison.json --train-before 2026-08-01T00:00:00Z --test-from 2026-08-05T00:00:00Z --as-of 2026-09-01T00:00:00Z`

Official evaluation requires TYPESAFE_API_KEY and MIROFISH_JEV_LIVE_ENABLED=true
in the server environment. Default is disabled; do not use third-party proxy keys.
Requests are fixed to api.typesafe.ai and jev-1.13.0. Default batch is 5 calls,
UTC-day budget 100 calls; MIROFISH_JEV_BATCH_CALL_LIMIT and
MIROFISH_JEV_DAILY_CALL_LIMIT are bounded at 20 and 1000 respectively.
Network uncertainty remains recorded, without automatic paid retries. Preserve
claims.sqlite3 with snapshots/responses when moving servers to retain deduplication.

Authenticated admin API prefix: /api/admin/mirofish/semantic-shadow.
GET /status; POST /snapshots {scanner_run_id}; GET /snapshots/{id};
POST /snapshots/{id}/evaluate. GET does not trigger provider work.
Snapshots use data/admin_mirofish/semantic_decisions; these artifacts are not committed.

## Research contract and limits

Only timestamped source text/summary is eligible. Numeric-only packets and nested
un-normalized documents are intentionally ineligible. All recorded availability,
publication, observation and retrieval timestamps must be <= decision time.
Export preserves unknown labels; supply verified filled execution returns,
benchmark return, cost_bps, and label_end_at before training. Do not fill missing
returns with zero. Features must share an exact schema across all accepted rows.
Gross/benchmark returns use fractions (0.01 = 1 percent). Stable source event IDs
purge overlapping evidence across training and test, including partial overlap.

The chronological ridge baseline is an offline experiment, not a production model.
Metrics compare Top3 on the same eligible cohort; they do not estimate whole-universe
coverage or compounded account performance. 5-day block intervals are exploratory.
There is no claim of improved real trading performance without a mature real dataset.
Synthetic tests prove contracts and leakage controls, not investment effectiveness.

Independent review found timestamp precedence and event-identity leakage; both
were corrected with regression coverage before release.

Verification: 840 MiroFish/signal-contract tests passed (exit 0); focused suite
82 passed; compileall and git diff --check passed. CLI status verified disabled,
no key configured, no provider calls. Live provider inference remains unverified.

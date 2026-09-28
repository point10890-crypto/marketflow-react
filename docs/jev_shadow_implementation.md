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

## DeepSeek alternative (2026-09-28)

Approved extension: use the existing DeepSeek account while Jev access is pending.
No new plugin/dependency or frontend change is required. Adapter decisions remain
shadow features until real performance is evaluated. No orders or alerts are sent.

Configuration (server .env; keys never in source):
- MIROFISH_SEMANTIC_PROVIDER=deepseek
- MIROFISH_SEMANTIC_LIVE_ENABLED=true
- DEEPSEEK_API_KEY=<existing server key>
- MIROFISH_SEMANTIC_DEEPSEEK_MODEL=deepseek-flash
- MIROFISH_SEMANTIC_BATCH_CALL_LIMIT=1 (maximum 3)
- MIROFISH_SEMANTIC_DAILY_CALL_LIMIT=20 (maximum 100)

The official models endpoint returned deepseek-flash and deepseek-v4-pro during
verification. The previous v4-flash alias resolved to deepseek-flash; use the
reported model explicitly. Official requests go only to api.deepseek.com.
No third-party base URL, implicit provider fallback, or automatic paid retry.
The fixed JSON prompt disables thinking, caps output at 1800 tokens, and caps
request bytes at 12000. Every claimed fact must quote an exact source substring.
unknown and not_stated are explicit categories, not assumed safe/no-risk.
Features are categorical indicators, NOT calibrated probabilities. Store provider,
resolved model, input/output tokens and raw response; monetary estimate is null
until current account pricing is verified. Request count limits bound spend exposure.

Operational steps:
1. Capture the scanner run with snapshot, or use a workflow snapshot.
2. `python scripts/mirofish_semantic_shadow.py enrich --snapshot-id js_<id>`
   attaches up to three recent raw news headlines per candidate from the existing
   local omni ledger. No inferred AI summaries are used. A NEW snapshot uses the
   current observation time; the old snapshot is never backdated or overwritten.
3. Evaluate the returned ID with `evaluate --snapshot-id js_<new_id> --provider deepseek`.
   Repeat the SAME ID to resume deferred candidates without repeating paid successes.
4. Export and label verified subsequent returns for offline comparison as before.

Admin API also offers POST /semantic-shadow/snapshots/{id}/enrich. Inference stays
explicit POST/CLI; reading status never spends tokens. Existing candidate capture
is automatic in workflow creation, but recurring paid evaluation is not scheduled
by this release. Existing candidate snapshot storage remains backward compatible;
DeepSeek evaluation files use a .deepseek.json suffix, separate from Jev files.

Headlines provide limited evidence; sufficient means sufficient for the stated
classification, not sufficient to invest. Lack of eligible news remains ineligible.
The actual synthetic Korean contract-cancellation probe produced cancelled/yes with
an exact quote, 1033 input + 236 output tokens. This validates API integration only,
not real-market accuracy, probability calibration, or improved returns.

Alternative-provider release verification: 848 MiroFish/signal-contract tests
passed; compileall and diff whitespace checks passed. Fresh review corrected
legacy Jev cache compatibility. Regression tests also cover no paid retry of an
old uncertain Jev claim. A pre-existing regime test was leaking its environment
constant into later tests; its teardown now restores the environment before reload.

## Automatic worker and final operational acceptance

The earlier manual-only limitation is removed by `worker`: it reads the newest
scanner run (maximum age 36 hours), snapshots and enriches once, and drains one
bounded batch each invocation. A durable provider-specific job receipt preserves
the immutable enriched snapshot across restarts. SQLite prevents concurrent workers.
A completed scanner run is not re-enriched/recharged. Deferred/budget-limited work
remains pending; failures/uncertainty remain visible without paid blind retries.
Status includes worker state and counts. No trading/ranking promotion is implied.

The production Windows task MarketFlow-Semantic-Shadow invokes this CLI every
30 minutes, separately from Flask and the existing scanner scheduler. Disabling
MIROFISH_SEMANTIC_LIVE_ENABLED stops inference. Daily UTC quota remains 20 calls.

`python scripts/validate_semantic_provider.py --env-file <env> --output-dir <path>`
runs six synthetic Korean gold cases against the actual provider. All six passed
(contract cancellation, dilution, audit concern, conditional guidance, unrelated
news, correction), covering 12 predeclared label assertions and quoted-evidence
validation. These are small synthetic acceptance tests, not a broad accuracy claim.

Historical workflow returns cannot validate newly observed semantic features:
backdating current headlines or joining them to already-known returns introduces
look-ahead bias. Prospective performance labels must mature after the new snapshot.

Fresh worker review found no critical repeat-charge or credential-routing defects.
Six live gold cases used 6119 input and 1379 output tokens in total. Existing real
candidate acceptance covered 4 eligible of 20 candidates; 16 lacked eligible text.
Pending state, process exclusion, stale input rejection and cached completion are
covered in worker regressions. Scheduled-task execution is verified on the target
account after deployment, rather than inferred from successful registration.

Operational acceptance uncovered a real quote-format defect: the provider appended
one wrapping quote to an otherwise verbatim headline. The validator now permits
only removal of outer quote/whitespace characters when the remaining >=8-character
text is an exact source substring. Changed words still fail. Original raw responses
are preserved, normalization is explicitly recorded, and the `revalidate` CLI
rechecks failed saved responses without any provider request or new charge.

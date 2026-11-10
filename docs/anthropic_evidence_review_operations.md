# Anthropic evidence review operations

Scope: MarketFlow Kongming article interpretation and AlphaLab top-candidate evidence comparison. Implementation plan: `docs/superpowers/plans/2026-11-08-anthropic-analysis.md`.

## Decision contract

The deterministic AlphaLab decision, rank, ATR prices, Kelly allocation, original source cutoff and closed outcomes are unchanged. The new analysis interprets supplied saved evidence. It does not approve trades, invent missing quotes, predict a guaranteed return, or establish calibrated probabilities.

If the saved opportunity board has no approved candidates, comparison may use the existing sealed report's research watchlist. The view explicitly labels that basis as research, retaining the original decision's hold. An empty watchlist waits for data rather than constructing stocks from model memory. News received after the original decision may explain the current situation but is never attributed to the original decision.

## Cost and continuity

From the 2026-11-10 operational correction, optional scheduled article
extraction leaves `min(9, daily_call_cap)` calls of shared headroom for priority
candidate/TOP3 comparisons. The atomic shared ledger still enforces the same
USD 1/day and 100-attempt maximum, including fallback. No existing charged or
unknown reservation is released to create headroom.

Only the two new operations use Anthropic first. Haiku extracts article evidence; Sonnet compares a bounded group. Existing DeepSeek/OpenAI routing for other work remains unchanged. The feature's combined default admission ceiling is USD 1 per UTC day and 100 provider attempts per day, including fallback. Token/output caps and content-addressed reuse reduce actual spend below that ceiling. Pending or unknown usage retains its conservative reservation; unknown cost is not reported as zero. There is no automatic payment or credit top-up.

The read endpoints return stored results only. Refreshing a page never submits paid inference. A separate worker checks for new evidence, retaining completed stages. Credit/authentication/model failures open the provider circuit; eligible existing providers can continue within the same feature cap. If all providers fail, the view displays an unverified/delayed state and never fabricates a successful analysis. Recovery checks are bounded; repeated scheduler ticks must not repeatedly charge identical inputs.

## API and UI

- `GET /api/admin/mirofish/kongming/article-evidence-reviews`: same admin/active Kongming entitlement as the existing article service.
- `GET /api/admin/mirofish/alpha-lab/candidate-review`: same admin/active AI Brain entitlement as AlphaLab.
- Both are private/no-store. The public projection excludes raw prompts, provider responses and credentials.
- Display includes actual provider/model, fallback status, generated/source times, current decision binding, strengths, risks, what to check next and source links.

## Prospective evaluation

Start a new evaluation cohort at deployment; do not change previous labels or choose thresholds to fit their outcomes. Preserve all comparison inputs, original ranks, model/prompt/schema versions, selected and rejected evidence and provider cost. Observe 5/10/20-session outcomes with the existing entry/cost/benchmark assumptions. Compare evidence correctness, contradicted claims, missing sources, cost and eventual net outcomes against the unchanged baseline. The initial 40-session observation window is a starting protocol, not proof of profitability; insufficient or dependent samples remain inconclusive. Promotion into the actual selection policy requires a separate prospective review.

## Official references checked 2026-11-08

- [Models and IDs](https://platform.claude.com/docs/en/models/overview)
- [Pricing](https://platform.claude.com/docs/en/about-claude/pricing)
- [Structured output contract](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)

Structured output enforces shape, not factual correctness. Evidence identifiers and quoted spans are validated locally. Native citations are not combined with strict JSON output. No paid web-search tool is enabled.

## Verification record

Preflight: the production account's read-only `/v1/models` request returned HTTP 200 and listed `claude-haiku-5-5` and `claude-sonnet-5-5`. Anthropic and the existing fallback credential presence were checked without exposing values. This proves model access, not remaining credit or inference quality. Paid primary/fallback and release verification results will be appended after execution.

## Runtime controls

- Worker: `python -X utf8 -m scripts.run_evidence_review`; production scheduled task `MarketFlow-Evidence-Review`, startup and every five minutes, SYSTEM, overlapping instances ignored, four-minute hard limit. The worker has a 210-second internal deadline and reserves time to persist completed stages.
- New-operation provider requests have a 30-second timeout and SDK retries disabled. The worker only begins another routed stage with at least 100 seconds remaining.
- `AI_EVIDENCE_REVIEW_DAILY_BUDGET_USD` defaults to `1` and is clamped to 0–1; `AI_EVIDENCE_REVIEW_DAILY_MAX_CALLS` defaults to `100` and is clamped to 0–100. Invalid limits disable new paid admission. These are UTC-day caps for this feature on its shared production routing ledger, not the entire application's spend.
- `AI_ANTHROPIC_EXTRACT_MODEL` / `AI_ANTHROPIC_REVIEW_MODEL` select models with verified pricing. Default `claude-haiku-5-5` / `claude-sonnet-5-5`; an unknown price blocks new spend. SDK `anthropic==1.3.0` uses its native HTTP client.
- State: `data/evidence_review/state.json`; sealed receipts: `data/evidence_review/runs/<fingerprint>.json`; shared billing ledger: `data/ai_routing/usage.sqlite3`. Raw text is private and excluded from read APIs.
- Credit/authentication/model pre-inference rejection has known zero usage. An eligible retry after the one-hour cooldown may use a new request identity. Unknown or charged failures retain their identity and reservation; subsequent ticks cannot repay the same request/provider. Successful fallback remains cached without repeatedly testing the exhausted primary.
- Disable paid work by disabling the scheduled task or setting the feature budget to zero. Saved results and original stock analysis remain readable. Do not delete receipts or reset billing reservations to force retries.

## Output validity

Every finding includes a type, an existing source identifier and a literal quoted span. `reported` must equal its quotation; `inference` is explicitly an interpretation; `missing` cites the saved absence/status; `verified` is restricted to the fixed template for independently verified OpenDART numeric claims. Free prose cannot introduce numeric predictions, trade approval or asserted official confirmation. Unsupported evidence stays unverified even if a provider returned valid JSON.

The wire schema uses only Anthropic-supported structural constraints; local validation enforces one finding per group and 80-character text/quote limits. A real API rejected `maxItems`, so this unsupported keyword is intentionally excluded. RSS excerpts are bounded private collector evidence; unchanged polling does not rewrite their acquisition time.

A response with valid target identity and group structure may omit individual findings that fail the existing semantic validator. Surviving findings are unchanged; an all-invalid response is rejected. The selected raw response and its filtered projection are bound together in the private receipt. Public `omitted_findings` explicitly reports omissions so partial evidence is not mistaken for a complete review. This reduces unnecessary whole-response fallback charges without relaxing claim checks.

## Pre-release acceptance, 2026-11-08 KST

- Real independent saved inputs: OCI article and the sealed AlphaLab research watchlist (LG유플러스 032640, 삼성E&A 028050, 셀트리온 068270). Original research decisions remained held; these are comparison inputs, not newly approved purchases.
- Real Haiku article output: three retained findings, `SUCCESS_PRIMARY`, 3,186 input / 354 output tokens, estimated USD 0.0004956.
- Real Sonnet batched comparison: five retained findings, four rejected findings explicitly omitted, `SUCCESS_PRIMARY`, 3,784 input / 1,086 output tokens, estimated USD 0.018428. All original symbols and stored source/decision bindings retained.
- Exhausted-credit acceptance: injected a definitive zero-cost Anthropic rejection while calling the existing DeepSeek provider for real. Result `SUCCESS_FALLBACK`, `insufficient_balance`, three retained findings, 2,061 input / 962 output tokens, estimated USD 0.00326502. This is failure injection, not an assertion that the production Anthropic account is exhausted.
- Early failed development probes and their costs remain recorded separately. The values above describe representative successful runs, not total development spend or a future fixed price.
- Independent code review approved routing budgets, quote/claim guards, access control, source identity, raw receipt persistence, partial omission and selected-provider binding. Final release/CI and production receipt are recorded after deployment.
- Restart/reuse acceptance: reran the same real primary and forced-fallback candidate inputs in new Python processes; both completed with zero new provider attempts. This validates durable reuse beyond an in-memory cache.
- Final production receipt will be stored at `data/operations/anthropic-evidence-release-20261108.json` on the MiniPC, including release identity, task history, API access checks, cost ledger and unchanged AlphaLab input hashes. Generated receipts are intentionally excluded from Git.

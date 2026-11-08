# News-grounded TOP3 advisor operations

## Purpose and boundary

This endpoint provides a current research shortlist with supporting evidence, counterarguments and a final relative ranking. It joins MarketFlow's saved independent RSS/OpenDART/KIS verification with sealed AlphaLab research and leadership records. It is not a new full-market scan, calibrated profit probability, automated order service or replacement for CIO approval. Candidate coverage and original hold reasons remain visible. Zero to three valid research picks may be returned; the service never invents stocks to fill three slots.

The input pool is the union of saved issued/research candidates and the same-bound leadership watchlist. An article alone cannot qualify an entry. Imported original-Kongming archive rows do not pass as newly independently collected evidence. Later news is labeled current-review evidence rather than retroactively becoming the original stock decision's basis. Reference entry/stop/target fields remain attached to their original fixed decision.

Baseline score: `70 × saved-metric percentile + 20 × leadership-check fraction + 5 × verified-filing availability + 5 × verified-price availability`. Percentiles compare the same stored metric within the selected pool, ties use midranks and a singleton uses 0.5. Evidence points measure completeness, not positive sentiment; article count and unverified/negative headlines add no points. The chair may change this relative order using grounded arguments. Public `rank` is the final order and `baseline_rank` preserves the deterministic input order.

## Endpoints

- `GET https://marketflow-api.bit-man.net/api/admin/mirofish/alpha-lab/top3-advisor`: authenticated administrator or active AI Brain/Kongming entitlement; no body or query parameters. Returns saved public results only with `Cache-Control: private, no-store`.
- `POST` to the same path, empty body or `{}`: administrator only; queues a refresh marker and returns HTTP 202. No paid API, news fetch or stock computation runs on the request thread. It cannot force a paid rerun of unchanged facts.

Use the application's existing Bearer authentication; do not place tokens in URLs. `top3` contains exact stock identity, ranking components, source references, original plan/hold, strengths, risks and what to check next. `debate` includes distinct analyst, critic and chair results, actual providers/models/fallback, token usage and known/unknown cost. `sources` contains provenance and clocks; raw prompts/responses and private receipts are excluded.

`ready` means all three stages completed with primary-provider output and the final ranking is sealed; it is not permission to buy. `degraded` can still provide research picks, with explicit incomplete, fallback or locally recovered debate. `stale`, `missing` and `unavailable` contain no current picks. A locally recovered paid response has unknown provider/cost metadata when that metadata was not durably saved. Token usage and known estimated cost aggregate all attempts in each role, including fallback. Source cutoff/acquisition clocks are preserved from the saved debate input rather than advanced by a GET request.

## Debate and cost

Three genuinely distinct dependent calls: the catalyst analyst evaluates the supplied evidence; the risk critic sees that argument and original evidence; the chair sees both and returns a unique top-three ordering from the permitted candidates. Each statement requires a supplied evidence ID and literal quote associated with that exact symbol. No model can invent prices, Kelly allocations, official confirmation or buy eligibility. Untrusted source text is evidence, never an instruction.

The first two calls reuse `news_event_extract`, and the chair uses `candidate_review`. Existing Anthropic → DeepSeek → OpenAI routing and the **shared evidence USD 1 per UTC day / 100 provider attempts** admission cap apply, including other evidence-review work. This is not an additional dollar budget. No credit purchase, automatic top-up or new credentials. Exhausted providers use the existing permitted fallback; when all are unavailable, return deterministic research ranking with incomplete/degraded debate, never fabricated consensus.

The worker saves each pending request identity before calling a provider and captures raw responses privately before validation. Completed stages remain fixed; polling, process restarts and manual refresh do not repay them. Unknown/charged failed attempts keep their identity. Only definitive zero-use rejections can receive a new identity after the bounded cooldown. Receipt-write failures stop fallback/publication. Source/policy/prompt changes create a new comparison identity without editing historical decisions.

An explicit budget admission refusal with no provider attempts or raw response may retry after one hour using the **same request ID**. Only its run admission counter changes, bypassing transient in-memory result caching while preserving the durable ledger's cross-run duplicate fence. This permits recovery after daily capacity returns without replaying completed or uncertain charged calls.

Before any retry, the worker checks all non-released reservations for the previous request across providers and pools. Any claimed, charged, unknown or unreadable reservation blocks redispatch, including providers that are currently unavailable. Only conclusively settled zero-token/zero-cost reservations permit retry. A budget refusal takes same-ID priority even if skipped provider attempts report zero usage; skipped attempts never justify bypassing another provider's pending charge.

If that request-wide proof finds actual reservations and every one is conclusively settled at zero tokens and cost, a new identity is allowed to recover from the router's settled-request fence. With no reservations, a budget-admission retry retains the same identity. The returned skipped-attempt list alone is never sufficient proof.

## Windows operation

Install from the approved deployed repository:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install_top3_advisor_task.ps1
```

Task `MarketFlow-Top3-Advisor` runs as SYSTEM at startup and every five minutes (offset by two minutes from the general evidence worker). It has IgnoreNew and a four-minute hard limit. The CLI has a 210-second soft deadline and starts another routed stage only when at least 100 seconds remain. A debate can finish across ticks. Its own file lock also protects manual invocation:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m scripts.run_top3_advisor
```

Storage is isolated under `data/top3_advisor/`; the existing shared billing ledger remains `data/ai_routing/usage.sqlite3`. The CLI emits bounded operational metadata only. Existing collection/verification jobs remain responsible for refresh; the advisor never backdates new data or fetches source data on GET. Do not delete receipts or billing reservations to force retries. Disabling this task stops new advisor inference while saved read access remains available; the shared evidence budget can also be set to zero to stop all new inference in this pool.

## Evaluation and release gates

The ranking policy is a transparent hypothesis, not measured forward alpha. Register a fresh cohort at release and freeze the initial policy for the next 40 trading sessions; do not tune to outcomes already inspected. Compare original research rank and advisor rank using immutable issue-time inputs and the existing 5/10/20-session entry, cost, benchmark and missing-observation protocol. Separate source correctness, operational completion and subsequent net returns; missing quotes are not wins or zero returns. Do not promote research picks to approved entries based solely on this ranking.

Release requires meaningful tests for source binding/freshness, per-symbol evidence, role dependence, interrupted-call recovery, cost reuse, authorization and private serialization. Verify the actual production endpoint, task history and health after deployment, and retain checksums of original AlphaLab state. Store private deployment receipts under `data/operations/`; never commit keys, member details or generated artifacts.

## Pre-release verification, 2026-11-08 KST

- 103 advisor/input/API/CLI tests passed locally. Related evidence/signal checks (66) and routing/source/AlphaLab checks (317) passed. Independent final code review approved the implementation after reproducing and closing admission-recovery and request-wide no-rebill edge cases.
- Native AIRouter tests with fake provider transport cover three-role dependence, charged/unknown duplicate fencing, zero-use fallback, partial-stage recovery, shared cap exhaustion and restored-capacity recovery. No unit test sends paid requests.
- The saved real-input fixture contains 49 previously inspected stocks, five available research/leadership candidates and no matching recent independently collected RSS articles. The adapter reports that absence instead of presenting imported archive material as independently verified news. All candidates retain their existing held status; original input hashes remain unchanged.
- Final CI and real provider production acceptance are separate release gates. Record deployed revision, actual selected symbols, role/provider/model/cost, source times, scheduler result and repeat-run provider-attempt count in the private release receipt.

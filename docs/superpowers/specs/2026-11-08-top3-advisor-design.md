# News-grounded TOP3 advisor

Build a saved advisor endpoint joining MarketFlow's independent news/filing/price verification with AlphaLab candidates and a genuine three-call debate. This is a new research ranking, never a rewrite or promotion of sealed CIO decisions.

## Input and ranking contract

`advisor_inputs.build_input(*, alpha_root, article_root, now=None)` returns a bounded dictionary. It reads the sealed AlphaLab report and validated board binding. Candidate universe is the union of issued/report candidates and the same-bound leadership watchlist (not the whole market); expose inspected/pool/shortlisted counts. Reject corrupt, future, mismatched and older-than-72-hour decisions. Deduplicate exact symbol/name/market, cap shortlist at six. Preserve original entry eligibility/hold reasons and reference prices without recomputing Kelly or claims of profitability.

Return `targets`, `sources` (evidence_review source shape), `candidates`, `coverage`, `warnings`, `decision_id`, `source_input_fingerprint`, `source_origin_at`, `source_cutoff_at`, `fingerprint`, `status`. Targets use exact symbol/name/market. Each candidate has `symbol,name,market,rank,score,score_components,basis,entry_status,hold_reasons,plan,source_at,evidence_ids`. Scores are deterministic research ordering, not probabilities. Document formula. Match recent 72-hour article inputs by exact symbol; include official verification/price absence and negative/unverified news rather than treating article count as bullish. Max two recent articles per symbol and 80 total sources. Each source must identify permitted `target_symbols`; future timestamps excluded; post-decision evidence labeled. No source text instructions trusted. Reference prices are from the original decision only.

Fingerprint binds substantive facts, original eligibility, source verification, policy and input identity; polling wall clock does not change it. Missing or unavailable evidence is explicit. A stale input returns no current picks.

## Debate and durability

`advisor.run_once(root=ROOT, *, alpha_root, article_root, now=None, router=None, deadline=None)` locks its own store. Three independent dependent calls: catalyst analyst, risk critic (sees analyst), chair (sees both). Two NEWS_EVENT_EXTRACT operations and one CANDIDATE_REVIEW share existing USD 1/day and 100-attempt evidence cap and provider fallback; no new spend pool or credentials. Max six candidates, bounded tokens; provider timeout/retry policy unchanged. Three stages can span scheduler ticks. Completed stages and first fixed final output never rerun for the same versioned facts. Save request identity before inference and raw response before validation. Uncertain/charged failures cannot replay; definitive zero-use failure can retry after bounded cooldown.

Use the existing grounded findings schema/validation with exact targets and literal evidence quotes; additionally restrict evidence IDs to each symbol's permitted sources. Critic must see prior evidence, chair must see both; chair returns a unique subset/permutation of supplied symbols up to three, with explicit grounded findings. Reject unknown/duplicate targets and invented prices/probabilities. Agent prose never changes entry eligibility, source freshness, quantities or CIO approval. Each stage persists provider/model/fallback/cost/usage and public grounded arguments; raw prompts/responses remain private.

`advisor.read_view(...)` performs no acquisition or inference. Return `schema_version,status,generated_at,decision_id,input_fingerprint,source_origin_at,source_cutoff_at,coverage,warnings,top3,debate,sources,empty_reason,live_orders:false`. Public fields only, no private raw text. Recheck current binding/freshness before labeling output current. Before debate or during provider exhaustion, expose deterministically ranked research picks with `debate_complete:false` and truthful degraded status; never fabricate consensus. If fewer than three valid candidates return actual count. Final stage ranking has grounded rationale but no evidence of future profitability is claimed.

## API and operation

GET `/api/admin/mirofish/alpha-lab/top3-advisor`: existing active AI Brain or Kongming/admin access, private/no-store, no arguments/body, saved read only.
POST same path: admin-only empty object, enqueue a bounded refresh marker, return 202; no provider call on HTTP thread. Idempotent refresh cannot change content identity or erase completed output. Independent `MarketFlow-Top3-Advisor` scheduler at startup/every five minutes, 210-second soft/four-minute hard bound and IgnoreNew. Use shared existing provider ledger. No orders, no Telegram changes, no source refresh inside advisor. Existing collection/verification jobs supply updates.

## Validation and evaluation

Tests cover binding/freshness/symbol aliases, missing/negative news, score determinism, prompt injection and quotes, duplicate/unknown ranking, role dependence, restart dedup, partial-stage repair, provider exhaustion, no HTTP inference, authorization and private projections. Existing evidence/AI-routing tests remain green. Preserve hashes of AlphaLab immutable state for real acceptance. Register a new forward comparison cohort at release; do not optimize to old observed outcomes. Deploy only tested committed source and verify health, auth and actual saved response with source/cost clocks.

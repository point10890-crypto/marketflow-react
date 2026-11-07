# Anthropic catalyst and candidate analysis

Goal: Connect Anthropic to MarketFlow's independent Kongming article evidence and AlphaLab top candidates, with low spending, durable reuse, exhausted-credit fallback, and verified deployment.
Architecture: Two opt-in operations in the existing Flask AI router; scheduled saved-evidence worker; read-only entitlement-gated views; mobile readable interpretation cards. Original quantitative decisions and prices remain immutable.
Tech stack: Python/Flask, SQLite routing ledger, Anthropic Messages, existing DeepSeek/OpenAI adapters, Task Scheduler, React/Vite/TypeScript.
Spec: User approval 2026-11-08 and docs/anthropic_marketflow_application_review_2026_11_08.md (first two features).

## Global constraints
- No secret output, trades, new data subscription, entitlement changes, diagnostic Telegram, or alteration of previous decisions/outcomes.
- Unknown/missing facts remain unknown; exact supplied evidence IDs, source cutoff, symbols, quotes must validate. News alone never approves a buy. Deterministic ATR/Kelly/prices stay authoritative.
- GET never incurs inference. Save successful stages and content hashes; failed/uncertain calls must not loop. A fallback is visibly identified; total outage uses explicitly unverified deterministic evidence/old result with its original time.
- Anthropic primary only for new NEWS_EVENT_EXTRACT and CANDIDATE_REVIEW; preserve existing provider orders. Default Haiku extraction, Sonnet single batched comparison; existing DeepSeek then budgeted OpenAI fallback.
- All calls including fallback have bounded output, time, retries and persistent spend admission. Default new-feature cap USD 1/day and 100 calls/day; pending/unknown costs retain conservative reservation. Operator can configure a smaller cap. No automatic top-up.
- No tuning on historical outcomes. Comparison is an independently stored current evidence review; performance promotion needs future validation.

## Tasks
1. [ ] Provider: app/services/ai_routing/{contracts,policy,providers,pricing,router,budget}.py and focused tests. Add two operation policies, official-host adapter and native usage, structured output, exhausted-credit/auth handling and persistent bounded admission. Red tests: legacy policy unchanged, actual provider/fallback, low-credit 400, unavailable model, usage/cost, concurrent cap, timeout unknown cost. Reuse current breaker and routing ledger.
2. [ ] Pipeline: app/services/evidence_review.py (+ store if needed), scripts/run_evidence_review.py, scripts/install_evidence_review_task.ps1, app/routes/kongming_catalyst.py and app/routes/admin_mirofish.py route wiring; focused tests. Consume independent saved articles/verification and sealed AlphaLab opportunities, review at most 8 new recent articles per tick and top 3 candidates once per source/model/prompt/schema fingerprint. Store raw plus validated results, attempt/cost metadata, cooldown/recovery. Dedicated 5-minute task independent of request threads and original collectors. APIs GET article evidence reviews and candidate comparison enforce existing matching entitlement.
3. [ ] Frontend: new typed API/component plus KongmingArticleCandidatesPanel and AlphaLabPanel. Show saved review, current source/decision binding, ranked strengths/risks and source links, fallback/degraded/stale status. Existing cards/prices/navigation/admin access preserved. Test unauthorized, outage, saved cache, input change and 320px responsive layout. Apply relevant Taste skill, no redesign.
4. [ ] Integration/review: focused suites then full relevant Python/frontend checks; bounded primary and forced-fallback verification. Document schedule, budget, recovery, artifacts, model access and observed spend. Independent code review of credit handling, provenance and authorization.
5. [ ] Release: commit intentional files, push PR, passing CI, merge, MiniPC ff deploy via watchdog, frontend npm run deploy; verify SHA/health, saved APIs/admin/member/anon, scheduled run, primary/fallback and desktop/mobile.

## Review focus
Never hide failure as PASS; no arbitrary model symbols/numbers; no paid calls during GET; no restoring stale evidence under a new decision; daily cap survives parallel workers/restart; fallback is bounded and transparent; no key/error-body leakage.

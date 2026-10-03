# Specialized stock-research agents

The user supplied the four-agent/CIO architecture and requested Python message-based implementation. The approved outcome is a working, independently testable data → quant → risk → CIO → execution pipeline for market-cap-leading quality stocks. Current data acquisition remains a dependency, not a claim that the acquired files are already validated trading inputs.

## Decisions

- Use standard-library `asyncio` actors/queues and SQLite persistence. No LangGraph/Celery service, Redis, new AI account, or per-number LLM call is needed for deterministic calculations.
- Keep implementation in `app/services/mirofish/trading_agents/`, with an opt-in local CLI. Preserve Flask routes, current scanners, indexes and production deployment.
- Execution is paper-only. No live broker, account API, credentials, or real orders are called by this implementation.
- Treat -2σ as a prespecified empirical return-pattern hypothesis. Do not assume a Maxwell–Boltzmann stock-return distribution, automatic mean reversion, or disappearance of all one-day correlations.
- Require the existing train/validation sample, win rate, payoff, net-expectancy and Wilson gates. Holdout metrics cannot select stocks or estimate Kelly. At most three candidates are returned; fewer are valid.
- Estimate Kelly from actual net-return samples, apply half Kelly and a 20% per-position cap, 60% exposure cap and 40% cash floor. High prior volatility reduces exposure again. These are limits, not guaranteed optimal allocations or bankruptcy protection.
- Preserve current-cohort/survivorship limitations. Excluding financially weak stocks alone does not remove historical survivorship bias.

## Shared messages

`AgentMessage(run_id, stage, payload, parent_id=None, schema_version=1)` is an immutable strict finite JSON snapshot. `message_id` is the canonical content SHA-256. `to_dict`/`from_dict` verify the digest. Stages are `request`, `data`, `quant`, `risk`, `approval`, `execution`. Messages reject credential fields before they can enter a journal.

An actor receives one message and emits a message linked to its parent's digest. SQLite stores completed messages by run/stage. Same run ID with different input is rejected. A resumed run reuses verified completed stages rather than retraining or executing again.

## Input contract

The request is placed in `payload.input`:

- `as_of`: closed observation date, ISO YYYY-MM-DD.
- `universe`: existing normalized listing rows (`symbol,name,market,market_cap,volume,share_type,source,date`). Rank common KOSPI/KOSDAQ shares first, at most 100; retain KOSDAQ GLOBAL source labels.
- `current_financials`: full current financial-quality rows accepted by `evaluate_quality`.
- `prices`, `fundamentals`: dated rows accepted by the existing Kelly research engine. Data agent filters to the fixed approved cohort before quant calculations.
- `evidence`: boolean `price_adjustment_verified`, `financial_vintage_verified`; `source_timestamps` and `source_hashes` maps with `universe,prices,current_financials,fundamentals`, aware capture timestamps and 64-digit SHA-256. Captures after the actual decision clock are rejected. Synthetic fixtures additionally require `synthetic=true,trusted_fixture=true` and remain labeled synthetic throughout.
- `splits`: `train_end,validation_end,test_end`; no date is later than `as_of`. A stale test-end signal cannot start a new position.
- `config`: nested `research` engine overrides and `risk` limits. Risk overrides can tighten the hard limits; they cannot increase exposure or Kelly fraction above 0.5.
- `account_id`, `portfolio`: paper-account identity, nonnegative finite cash and a `positions` map of symbol to nonnegative finite quantity.
- `execution`: a supplied next-session date strictly after `as_of`, quotes mapping symbol to positive `price,volume`, quote `date` matching execution date, and explicit `source`. Quotes affect risk valuation/execution, never historical qualification. Fee/slippage/sell-tax assumptions are explicit numeric basis points.

## Actor outputs

1. **DataAgent** emits `payload.data`: `status=ready|blocked`, reasons, ranked rows, quality results, approved symbols, scoped prices/fundamentals and provenance metadata. Unverified acquired source files yield a blocked result. Invalid declared-verified numbers raise a structured failure. No imputed financials, altered OHLC or replacement stock is introduced.
2. **QuantAgent** emits `payload.quant`: all frozen `qualified` rows and at most three fresh `candidates`, exact symbol/name/market, train/validation evidence, estimated Kelly and prior volatility. Test metrics are omitted from selection messages. A blocked data message produces a hold without running the engine.
3. **RiskAgent** emits `payload.risk`: `status=approved|held|rejected`, reasons and target weight map. New entries need fresh candidates; existing independently qualified positions can remain in the rebalance plan. A verified loss of qualification can produce a paper liquidation plan. Missing prices or blocked data cannot produce fills.
4. **CIO** emits `payload.approval`: decision, exact stored risk message ID, canonical target-weight hash, paper account, execution date and paper mode. It independently checks identity, parent links, hard limits and source-state consistency. An actor's confidence is not an approval credential.
5. **ExecutionAgent** verifies the persisted CIO message and risk digest, then emits `payload.execution`: status, paper fills, cash/quantity ledger, date and idempotency information. Sells precede buys; costs and cash constraints apply to both. At most one atomic paper rebalance per `(account_id, execution_date)` is allowed across runs and process restarts. Invalid quotes or transactional failure leave the account and daily slot unchanged.

## Recovery and verification

Completed stage messages and the final report are immutable. Errors store sanitized stage/type identifiers. Concurrent attempts cannot double-fill a paper account. A replayed run returns the same persisted fills rather than applying them again. Stage timeouts, invalid hashes and wrong parent/run/stage identifiers are explicit failures.

Tests cover each actor plus real end-to-end synthetic runs, blocked acquired data, future/invalid evidence, independence from holdout outcomes, conservative weights, insufficient cash, zero volume, approval tampering, rollback, daily deduplication, interruption/resume, and concurrent runs. Real acquired data must remain blocked until its source validation is actually complete.

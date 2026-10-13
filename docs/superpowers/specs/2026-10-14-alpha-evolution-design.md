# AlphaLab autonomous evolution pilot

The operator asked Codex to lead implementation autonomously, with the goal of
better forward profit potential rather than more status reports. This pilot
adds a working, bounded research loop to the existing daily detection system.
Existing deployment authorization covers implementation, verification and
release; real-account orders, new paid services and inherited credentials are
outside the scope. Profitability is an empirical outcome, not a deliverable we
can assert before independent observations mature.

## Problem and objective

The first two unrevised prospective observations stopped out. They motivate
testing entry quality, but cannot select a winning parameter or validate an
improvement. Existing mean-reversion setups do not require recovery, the live
reference band does not enforce its lower bound, and uncertainty-adjusted
negative ranks can still fill three slots. Historical source volumes also
continue to change after the 20:30 acquisition buffer.

Implement deterministic data, hypothesis, comparison, risk-audit and memory
agents. Their concrete result is an immutable, reproducible comparison of three
fixed challengers against the incumbent, updated automatically after successful
research. They cannot generate executable code, tune inspected test windows,
change existing ranking/Kelly/CIO contracts, or place orders.

## Fixed catalogue

Control preserves the current board's selected stocks and next-open paper
execution. Exactly three challengers are registered; no parameter sweep:

1. `entry-band-v1`: same selected stocks; the first observed next-session open
   must be inside the frozen signal-close entry band. Otherwise retain an
   explicit cash/skip result without delaying entry to another session.
2. `recovery-confirmed-v1`: use the full eligible discovery pool and the existing
   ranking implementation; additionally require a positive candle body and a
   close above the preceding close. Breakout setups must actually clear the
   previous 20-session high (`breakout_20 > 0`). No future candle is a selector.
3. `positive-rank-v1`: preserve existing evidence gates and correlation-aware
   ranking, but omit candidates with a final score <= 0. Re-rank remaining
   eligible candidates deterministically and leave unused slots in cash.

The original `ExecutionPolicy` remains horizon10, ATR14x2, maximum stop8%,
reward/risk2, fee5bps, slippage5bps, sell-tax20bps. Entries use next-open rebased
barriers. Stress doubles all three costs without changing selection or fills.
Existing paper ledgers have different execution semantics from live guidance;
this pilot never presents either as a brokerage fill.

## Pure engine

New `evolution.py` owns the fixed catalogue, causal policy decisions, outcome
replay and paired metrics. Interfaces:

* `protocol_spec()` -> JSON-compatible fixed manifest, including hashes,
  policies and gates below.
* `build_cohort(inputs, report, discovery, *, protocol, now)` -> frozen cohort.
  Inputs are the existing canonical `load_inputs` result and full discovery pool
  retained before original BUY3 truncation. Freeze actual decision clock,
  original first board identity, source session/fingerprint/audit, names,
  dated quality cohort, full pool and the last64 OHLCV bars per cohort symbol.
  Reject future rows and nonfinite values. Decisions after the immutable
  declaration only; source session must equal the KST decision date.
* `observe_cohort(cohort, prices_by_symbol, *, now)` -> updated observation
  envelope. Never regenerate selections. Respect next union-calendar session,
  missing/zero-volume bars, stop-first ambiguity and actual closed horizons.
  Closed/unfilled/skipped result bodies stay sealed; later numeric/calendar
  changes are separate revision evidence, excluded from strict metrics.
* `summarize(protocol, cohorts)` -> bounded public status. Retain paired no-trade
  days. Pending, missing, open or revised records cannot become completed wins.

Each arm has at most3 slots. Primary descriptive comparison is equal-slot
watchlist return: sum of completed returns/3, with known cash skips at zero.
This is not overlapping-account portfolio P&L. Paired results require all
baseline and challenger slots resolved and unrevised. Report both accepted
trades and skipped opportunities, including missed control winners and avoided
control losers. Show cost-stress result, downside tail, coverage and sample
counts. Never report a win rate or probability from scores.

## Immutable memory and future-only assessment

New `evolution_store.py` owns only `data/alpha_lab/evolution/`: immutable hashed
protocol, one first cohort per source/decision day, independent observations,
immutable candidate-review receipts, compact atomic status. Use existing atomic
helpers and FileLock. GET reads only checked bounded status JSON. Existing
production reports, issued decisions, journals, source files and notification
receipts remain untouched by evolution.

Fixed future evaluation window: first106 enrolled decision sessions followed by
up to10 label-maturation sessions. The first36 sessions nominate a challenger
using paired doubled-cost mean only. A10-session embargo follows to mature nomination labels before the untouched60-session confirmation. Those60 sessions may reject that fixed
selection but cannot replace it with another arm. No extensions based on
observed profitability. Same-day reruns never renew the experiment clock.

Research-candidate gates: full declared window resolved, at least30 entered
unrevised confirmation outcomes for both nominee and control, at least6 full
nonoverlapping 10-session confirmation blocks, positive normal and stress net means, positive paired advantage versus
control, nonpositive worsening of downside-tail loss, and a conservative block
mean advantage margin bound using fixed multiplier3.5 on the confirmation blocks only; this is a conservative research gate, not a calibrated probability. Missing/revised coverage
or missing/unbound capture provenance prevents qualification. Known historical
vintage, adjustment and current-cohort limitations remain explicit for human review.
Disjoint decision blocks can still share market regimes and overlapping holding
periods; the margin is a fixed research indicator, not an independence claim or
calibrated confidence interval.
All qualification is research-only, `live_orders=false`, `approved_exposure=0`,
`awaiting_review`; the existing AgentDesk M0/CIO/account contract stays intact.

If no challenger qualifies, preserve the incumbent and record the exact reason.
Old NAVER/Alteogen outcomes and historical tests are diagnostic motivation only;
they are never backfilled as prospective challenger evidence.

## Integration and UI

`service._add_opportunities` returns its already-computed full discovery pool.
After successful publication, an independently caught evolution refresh receives
that pool and canonical inputs. Failure cannot undo successful research or source
collection. An explicit CLI initializes/replays only saved canonical inputs,
without acquisitions, Telegram or orders. Existing 20:30 scheduled research
covers both scheduled and manual runs; no duplicate daily task is installed.

`service.read_status` attaches optional `evolution` only from saved artifacts,
bound to the current board identity/fingerprint/audit. A mismatch is held, not
silently shown as current. The shared AlphaLab panel shows a portrait card with
actual phase, next step, four arms, current selected stock names/codes, paired
net/stress results, resolved/skipped/revised counts and review reasons. Null
means no evidence. No fabricated confidence, account returns or model promotion.

## Evidence and verification

Meaningful synthetic tests cover future-prefix invariance, selection gates,
negative score/cash slots, lower-band/gap skip, next-session timing, missing and
zero-volume quotes, stress-cost parity, sealed terminal/revision behavior,
immutable protocol and cohorts, restart/idempotency/capacity/corrupt files,
validation-only nomination and confirmation-only rejection, GET purity and
optional-failure containment. UI tests cover null/negative/revised metrics,
current identity mismatch, legacy absence and mobile wrapping.

Run a representative real canonical snapshot in isolated research storage.
Record its actual provenance and selected names, including no-selection states.
Then pass focused regressions, full backend CI, frontend tests/build, independent
review, MiniPC scheduled-hook/runtime verification and actual deployed portrait
UI. Do not claim independent profitability before the future window matures.

Methodological references: [Microsoft RD-Agent](https://github.com/microsoft/RD-Agent)
and [RD-Agent Quant](https://arxiv.org/abs/2505.15155) inform the hypothesis /
experiment / feedback separation; no reported paper return is adopted as our
performance. [Bailey et al.](https://sdm.lbl.gov/oapapers/ssrn-id2507040-bailey.pdf)
motivates bounded trials and independent evaluation. No framework source is
vendored and no extra paid model calls are required.

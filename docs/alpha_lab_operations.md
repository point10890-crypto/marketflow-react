# AlphaLab: independent stock-detection agents

AlphaLab compares four fixed strategies on the current financial-quality subset
of the market-cap TOP100: momentum, liquidity breakout, mean reversion, and a
ridge model trained on completed costed bracket outcomes. It uses deterministic
agents instead of paid language-model calls. No new external agent API key is
required. The existing Flask/React deployment and current trading approvals stay
separate from this research tournament.

## Read and run

- Member screen: `/dashboard/ai-bain/chart-predict`, **에이전트 매매 제안**.
- Saved status: `GET /api/admin/mirofish/alpha-lab`.
- Fixed background experiment: `POST /api/admin/mirofish/alpha-lab` with `{}`.
- Both require an admin or active AI Brain member and use private/no-store.
- GET never acquires data or fits a model. Client options, symbols, thresholds,
  and input paths cannot be supplied to this route.

```powershell
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe scripts\refresh_alpha_lab_inputs.py --fetch
.\.venv\Scripts\python.exe scripts\run_alpha_lab.py
# Or run both with failure-preserving orchestration:
powershell -NoProfile -File scripts\refresh_alpha_lab.ps1
```

Canonical input registry: `data/alpha_lab/inputs/current.json`, pointing to sealed
snapshots with CSV, acquisition manifest and TOP100/current-quality report.
The collector recovers completed stages, verifies source/hash/cohort agreement,
and publishes one atomic pointer only after success. Holidays without a dated
listing preserve the previous snapshot; it never rewrites the source date.
On a worktree use explicit `--env-file` and `--corp-codes` paths from this project.
Do not copy or log their contents. The first seed is the existing long-history
price acquisition or an explicit `--seed-prices` file. Later runs reuse the
current canonical price snapshot as their seed.

## Evaluation and rejection

The recent chronological window is 504 training, 126 validation and 126 test
sessions, separated by a 10-session embargo. This is **one recent fixed split**,
not an extensive multi-year walk-forward study. Normalization and labels use
training information only. A separate latest serving refit never changes the
frozen evaluation model or champion. Scores are rankings, not probabilities.

Validation selects the champion; the untouched test period only accepts or
rejects that selection. Negative held-out or doubled-cost returns, fewer than
30 completed test outcomes, inactive entry setup, stale or unverified sources
hold allocation at zero. There is no hindsight switch to the best test winner.
Research watchlists may still show three identified stocks for observation.

Execution enters on the next union-calendar session's open, IOC. Missing or
zero-volume quotes do not fill. Opening gap exits can fund opening entries;
intraday/closing exits cannot. Simultaneous intraday stop/target is stop-first.
ATR uses signal-date prices only. The default horizon is 10 sessions, ATR14×2,
loss cap 8%, reward/risk 2. Costs are hypothetical: fee 5, slippage 5 and sell tax
20 basis points; stress doubles all three. Fractional shares are research-only.

Kelly uses **actual net winning and losing returns from the same policy**,
half-Kelly, maximum new allocation 20%, planned account loss 1%, cash buffer
40% and at most three positions. Estimated stop loss is not a guaranteed loss
bound. Allocation caps apply at entry; later price drift is measured, not
silently rebalanced. None of these controls guarantees profit or prevents ruin.

## Forward evidence

`forward.json` freezes the first watchlist each KST decision day, its original
OHLC snapshot, costs, provenance and integrity digests. Entry observations only
start after the actual decision date, even if the input prices are older.
Closed and unfilled outcomes are immutable. Later source revisions are separate
audit evidence; revised closed outcomes are excluded from summary statistics.
These are watchlist outcome observations, not brokerage account P&L. At 730
decision days the journal requires explicit archival rather than silent eviction.
Unsigned/corrupt journals fail closed and preserve the previous public report.
Observation time and consumed source time are separate. A morning rerun with
only yesterday's data must not claim to have consumed today's absent session.
New results seal the calendar cutoff at the last supplied session (or the
existing fixed exit/unfilled-entry session). Revision checks bound legacy
inflated cutoffs by the stored consumed bars/calendar without rewriting the
original result. A later normal session append can continue an open outcome;
a new date inside an already consumed interval, a restored missing entry quote,
or changed OHLCV still records a revision and holds that result.

The 2026-10-07 operational correction addresses source latency only. It changes
no ranking, strategy parameters, cost assumptions, sizing, approvals or reported
returns. Existing revision events and terminal results remain immutable, even
when an old event also contained an overly broad calendar reason. Provider
restatements are real evidence: the public feed has revised prior close/high and
volume values after collection. Capture after 15:30 does not establish a final
KRX close or verified adjustment/vintage. Do not clear revisions or recalculate
historical outcomes to make the success rate improve. Regression validation
uses fixed synthetic delayed-append, past-gap, missing-entry and OHLCV-revision
fixtures, independently of historical strategy performance.

## Clear manual proposals

The member API derives `proposal_summary` and each candidate's `proposal` from
the verified saved result. The conclusion and stock actions appear before
strategy diagnostics. Projection is cheap and never fits models, acquires
sources, rewrites saved evidence or changes the frozen forward journal.

- **매수 제안 (buy):** a conditional manual research proposal. The stock must
  match the validation-selected champion, its qualified calibration, positive
  validation mean and positive held-out/doubled-cost returns, with at least 30
  completed validation/test/stress outcomes. It also requires an active setup,
  current symbol session, valid source timestamps and a finite reference plan.
  Research weight is above zero and at most 20%; weight times planned stop
  fraction is at most 1%. Legacy decisions expire 24 hours after the original scan; certified opportunity decisions use the next-session window described below.
- **진입 대기 (wait):** missing/zero/insufficient evidence, inactive setup,
  stale/missing/future price/source timestamps, invalid plan, expired decision,
  refresh failure, or ongoing/failed analysis. Legacy missing fields do not
  become a buy proposal. Source sessions may be at most seven calendar days old.
- **매매 제외 (avoid):** the matching strategy lost money in the held-out or
  doubled-cost test. This excludes a new buy; it is not advice to sell an
  existing holding. A negative strategy can be excluded even if no champion
  was selected. In-progress/failed status suppresses any retained buy proposal.

`proposal.proposed_weight` is a manual research suggestion and remains separate
from the existing `risk.weight` and CIO approval. Historical vintage,
current-cohort and adjustment limitations remain present; this proposal layer
does not change `analysis_ready`, approve capital or enable broker orders.
Prices are last-closed-price references, never live quotes or promised fills.
Next-open entry requires checking the actual opening price and recalculating
barriers and sizing. Excluded/waiting stocks' reference plans are collapsed
under evidence details, so they do not look like active entry instructions.

The UI suppresses retained buy proposals during a rerun, status/poll errors,
failed analysis and client-side expiry, including while a view remains open.
Decisive wording describes an action recommendation, not certain future profit.

Local replay evidence lives in `data/alpha_lab/runs/`; compact private member
status lives in `data/alpha_lab/status.json`. Generated artifacts remain ignored.

## Operations and sources

Dedicated Windows MiniPC tasks, installed with `scripts/install_alpha_lab_tasks.ps1`:

- `MarketFlow-AlphaLab-Research`:20:30KST,90-minute limit, post-session source acquisition then research. An official closed date skips collection and preserves the last report.
- `MarketFlow-AlphaLab-Prime`:08:55KST,3-minute limit, official KIS session calendar preparation.
- `MarketFlow-AlphaLab-Monitor`:09:00–15:30KST every five minutes,3-minute limit, at most the three current proposal references. Known closed days issue no quote requests.

All use IgnoreNew and saved atomic/locked artifacts. Task installation does not launch a first research cycle. GET remains a cheap read; READY screens re-read saved status every30seconds and RUNNING screens every4seconds.
Flask production remains127.0.0.1:5003; development remains5001. Chart index scheduling stays independent.

### Daily-feed settling window (2026-10-08 source audit)

The former18:45 collection accepted a daily feed that was still changing. A bounded3-symbol probe at19:26KST found actual same-day close/volume changes for000660,007660 and196170 against the immutable18:45 snapshot; the previous day's rows were stable in that probe. This is a temporal input defect, not a capture-timestamp-only revision. The official [NXT trading system](https://www.nextrade.co.kr/menu/transactionSys.do) states that its aftermarket ends20:00. That timing is consistent with the observed updates; the NAVER feed's exact venue/adjustment semantics remain unverified.

Acquisition now waits until20:30KST, a30-minute buffer after that session. Explicit earlier same-day requests are rejected before collection/publication, and actual per-symbol/CSV capture times must meet the same cutoff. A versioned acquisition policy prevents reuse of old provisional snapshots as compliant inputs; old sealed files, first decisions and terminal outcomes remain preserved. The weekday helper is still not an exchange holiday certificate; the scheduled wrapper retains its official KIS calendar check. A time buffer cannot guarantee provider finality: later numeric corrections still create source revisions and remain excluded from performance. No parameters or inspected historical windows were retuned, and no realized profit is inferred.

The separate admin-symbol acquisition path uses the same buffer for its official-calendar selection and raw-price cache. It records the price capture separately from later financial captures, which cannot make an early price appear settled. Next-session entry expiry remains15:30KST. Legacy saved reports remain readable for audit; deployment does not rerun their first decisions. The next scheduled compliant collection publishes a separate snapshot atomically.

## Certified session windows and price monitoring

New optional `next-session-proposal-v1` windows apply only to the separate quality-setup BUY candidates. The first source identity and origin are frozen under `data/alpha_lab/monitor/`. Manual rescans against the same fingerprint/opportunity audit/candidate plan do not renew the window. The first certified session/deadline is also sealed; later calendar corrections hold the proposal instead of moving its entry day. Once KIS calendar dates fully establish the first trading session strictly after that origin day, the window ends at that session15:30KST. Missing/failed calendar confirmation produces a null window and a WAIT view. Legacy tournament candidates retain their original24-hour rule.

The calendar source is official `CTCA0903R` (`tr_day_yn` and `opnd_yn`), successfully fetched once per date and persisted. Failed calendar observations retry no earlier than15minutes, at most3attempts per KSTday. There is no fallback to a weekday-only trading-day claim. Calendar ranges with missing dates, invalid flags, future captures or corrupted artifacts hold confirmation.

Quote evidence uses KRX market code J. The current minute close and its business-date/time come from `FHKST03010200`; the **daily opening price** comes from `FHKST01010100`. A minute bar opening is never interpreted as the session opening. Provider inputs must be at most120seconds old at acquisition; saved quotes lose active guidance at420seconds. HTTP/API errors, future/previous-session quotes, changed identities, incomplete scans and failed attempts remove live guidance.

An observed opening-reference decision is fixed once for that source/session. Open above the close×1.02 ceiling or below the original reference stop skips entry for that session. Accepted reference barriers use the frozen ATR: distance=min(2ATR, opening×8%), stop=opening−distance and target=opening+2distance, retaining the existing quarter-Kelly research cap. Later quotes may show reference stop/target or monitor-only states. These are observations/reference plans, never actual brokerage fills or tracked user positions; approved exposure and live orders remain zero/false.

The separate current-candidate forward panel uses the existing sealed daily next-open paper journal. Closed unrevised outcomes form the win-rate/mean-return denominator; pending, open, unfilled and revised events are shown separately. The manual2% entry guard and live monitor are **not applied to that historical/forward simulation**. No account P&L is inferred.

Official provider references: [KIS holiday API](https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_stock/chk_holiday/chk_holiday.py), [KIS minute-price API](https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_stock/inquire_time_itemchartprice/inquire_time_itemchartprice.py).


Independent implementations were informed by:

- [Microsoft Qlib](https://github.com/microsoft/qlib), MIT, inspected revision
  `be725493eb1a6bbb42bf11b37aa7669f59610ff1` — causal OHLCV factors and model evaluation.
- [Microsoft RD-Agent](https://github.com/microsoft/RD-Agent), inspected revision
  `484776c211e4fbbeef03e0ec00d6bbee7362a4f4` — repeatable hypothesis/evaluation records.
- [FreqAI](https://www.freqtrade.io/en/stable/freqai-running/) and
  [lookahead analysis](https://www.freqtrade.io/en/stable/lookahead-analysis/) —
  frozen-window evaluation and temporal perturbation tests. GPL implementation
  source was not copied.
- [Thorp's Kelly paper](https://www.edwardothorp.com/wp-content/uploads/2016/11/TheKellyCriterionAndTheStockMarket.pdf).

No full framework was vendored; a benchmark or open-source project is not proof
of profitable Korean-stock operation. Current-cohort survivorship, historical
financial/price vintages, corporate actions, gaps, correlated outcomes, market
regimes and real fill quality remain explicit limitations.

## Evidence/account contract and portrait stock desk (2026-10-08)

Saved AlphaLab GET responses now include an additive `agent_desk`, bound to the existing maximum-three `opportunity_engine` identities. Twelve deterministic roles audit saved observations; they do not imply twelve LLM calls, a completed agent consensus or new source acquisition. The current integration supplies no certified extra collector. Absent foreign flow, FX, disclosure or other source records therefore remain missing. Historical win rates remain observations; Bull/Base/Bear forecasts are null and strategy promotion remains M0. Existing frozen decisions, ranking, forward outcomes and CIO approval are unchanged.

Trusted server evidence records require exact symbol/opportunity identity, role, claim, explicit S/A/B/C grade, original lineage/upstream origins and source/available/fetched/expiry timestamps. Each direction/risk core claim requires two independent S/A authoritative market/disclosure/official-news lineages. Generic news, social/search interest and B/C records cannot authorize a core claim. Connected origins count once, including copied chains; future availability cannot enter the original decision. The additive validity window is tightened by source age, source expiry and the existing quote/entry windows.

`POST /api/admin/mirofish/alpha-lab/account-plan` uses the existing admin-or-active-AI-Brain gate and private/no-store headers. It accepts only `{account, opportunity_ids}` and derives prices from current saved server plans. Explicit equity, available cash, daily/weekly PnL and confirmed complete holdings are required. Duplicate JSON keys, extra fields, oversized requests and nonfinite/boolean monetary inputs are rejected. Account values are request-only: no browser storage, research journal writes or account logs. Stale displayed identities return409 and require a fresh result.

Reference sizing floors whole shares at the maximum entry reference, then applies shared cash, current holdings, confirmed saved theme, existing reference weight and quarter Kelly. Limits are planned trade risk0.5%, daily new-entry stop−1.5%, weekly stop−4%, symbol max5%, theme30%, minimum cash40%, maximum3 concurrent stocks. Both usable FX and foreign-flow evidence absent => globalHALT. Unknown trusted theme, expired evidence/quote or failed audit withholds quantities. Gap/fill losses can exceed the planned loss. `ready` means deterministic reference arithmetic is ready, not a promoted strategy or CIO approval; orders always remain disabled.

Both the AI Brain stock desk and chart-analogue page share the portrait layout: stock/action, prominent entry/stop/target, next action and invalidation first; full evidence, role and account details expand below. Source expiry, refresh/error, account edits and logout invalidate dependent calculations. Additional watchlist rows become vertical on phones and retain table semantics on desktop. The optional contract is backward compatible with older responses; absence cannot expose account quantities.

`empirical_cvar` accepts only actual completed costed return arrays as an optional diagnostic. It does not change ranking or infer tail losses from a win rate. M1 replay, predeclared independent OOS, probability calibration, M2 paper duration and M3 human approval remain promotion requirements, not claims established by this integration.

## Decision evidence receipts and market guard (2026-10-09)

The selected K-EQUITY v2 ideas are independently implemented inside AlphaLab;
the downloaded package, probability weights and its mutable policy runtime are
not transplanted. TOP3 ranking, existing Kelly math, frozen research and forward
outcomes remain intact. The new optional `agent_desk.contract` carries a full
SHA-256 policy hash, exact decision identity, receipt ID/status and one ordered
market check per displayed candidate. Legacy desks remain displayable, but a
missing contract never permits account quantities.

Only an authenticated administrator may publish a receipt through
`POST /api/admin/mirofish/alpha-lab/evidence`. The exact JSON envelope contains
`schema_version: 1`, `decision_id`, `input_fingerprint`, `source_audit_hash`,
`policy_hash`, `evidence` and `market_states`; both maps are keyed by current
six-digit candidate symbols. Obtain the current identities and policy hash from
the saved status GET. The route rejects query overrides, duplicate JSON keys,
nonfinite numbers, extra fields and bodies above256KiB. Rejections are bounded
409/503 responses and never echo source payloads. Members can read the compact
audit and request reference arithmetic, but cannot import evidence.

Evidence retains the existing explicit source metadata, lineage and original
availability/capture timestamps. Each record additionally requires a stable
`evidence_id`, `direction` (`up`, `down`, `neutral`, `unknown`), finite `figure`
or null, `unit`, `conflict_group` and explicit `missing_reason`. Unknown/null
claims can document a gap but cannot certify a core claim. Opposite authoritative
directions for the same server-derived claim hold its audit; caller-supplied
group names cannot hide a contradiction. Duplicate IDs with different contents
are rejected by the auditor, while copied upstream lineages still count once.
Legacy unstructured evidence is explicitly missing directional semantics. A
reference account plan additionally requires usable flow and disclosure roles.
Source claims must have been available and fetched by the original decision
cutoff; later market observations do not repair that historical evidence.

Market state is a separate current observation: exact symbol/opportunity/decision,
explicit S/A source grade, source/available/fetched timestamps, session,
`vi_active`, `sidecar_active`, `circuit_active`, and each corresponding
`*_released_at`. False flags require explicit null only if never observed active,
otherwise a real release timestamp. Current facts expire420seconds after source
time, including the exact boundary. VI holds new reference quantities until
300seconds after release; sidecar/circuit cooldowns are900seconds. The source
must explicitly report continuous trading and the KST clock must be09:00–15:05
on a weekday; that clock window does not replace the existing official next-session
calendar. Account validity is the earliest of market, quote, evidence and entry
deadlines. Missing event feeds hold quantities without removing TOP3 stock cards.

Receipts live under `data/alpha_lab/desk-evidence/runs/{snapshot_id}.json` and an
atomic decision-specific `current/{decision_id}.json`. The body hash includes an
owned policy snapshot; identical imports are idempotent and do not refresh clocks.
Previous receipts are never overwritten. Once a market symbol is recorded, later
imports must retain it and advance its source time before changing its facts;
they cannot erase activation/release history to replay an older safe state.
Corrupt receipts or changed policies hold the decision rather than silently
repairing it. GET only reads these files; it does not collect sources or write.

This release supplies the checked ingestion path, not a newly certified upstream
feed. Existing KIS flow, cached FX and DART adapters lack some required lineage,
availability or event-release fields. Collectors must provide actual verified
facts before publishing; do not synthesize independence, grade, timestamps or
inactive-event flags. Raw evidence and collector details stay server-side;
the portrait stock desk shows saved/missing/held receipt status, policy hash and
per-stock market reasons. M0, unavailable forecasts and disabled orders remain.

## Private detection-event delivery (2026-10-09)

The operator explicitly requested immediate delivery and subsequent new detection
events through `@bitman75_bot`. This authorizes this narrow private automation;
the older one-shot scanner confirmation flow and other notification flags are
unchanged. OpenClaw remains independent and read-only.

`ALPHA_LAB_TELEGRAM_ENABLED=true` opts in. Both scheduled research and the manual
scan hook send only after the research report and exact first-issued decision
are saved. The event key is the frozen decision identity, recipient fingerprint
and fixed message digest. New source inputs can produce a new decision even for
the same symbols. Re-running that decision, member GETs, page refreshes, evidence
receipt updates and five-minute price ticks do not send repeated stock messages.

The sender verifies `getMe` equals `bitman75_bot` and `getChat` is the configured
private operator chat before sending one escaped TOP3 message. It uses the
project's personal bot token by default; the optional token-key alias is limited
to the project's two existing Telegram token keys. It never targets a channel.
The message uses saved names/codes, reference entry/stop/target, reference weights
and the held status with the actual source session. It does not substitute monitored
prices, advertise calibrated probabilities or claim execution approval.

Private receipts under `data/alpha_lab/notifications/` are separate from research
and scanner ledgers. A locked pending claim is persisted before transport;
verified delivery, pending or uncertain acceptance prevent replay of the exact
event. Timeout, malformed success or ambiguous server failure never cause an
automatic duplicate. Authentication/blocked-recipient errors require operator
action. Rate-limit recovery is bounded and respects the returned delay. Public
CLI output contains only sanitized status/decision/digest/count/session fields;
do not print, copy or stage private receipts, tokens, recipients or raw messages.

`scripts/run_alpha_lab_telegram.py` defaults to a saved preview. `--send` performs
one explicitly authorized send; `--automatic` honors the opt-in. The independent
`scripts/install_alpha_lab_telegram_task.ps1` installs only
`MarketFlow-AlphaLab-Telegram-Events`, a five-minute recovery check for the latest
decision. It does not rerun research or modify the existing research/prime/monitor
tasks. Research success survives transport failures; missing/invalid saved
decisions cannot send. The notification task and CLI load only this project's
environment, without exposing its contents.

## Price detection and public-news chronology (2026-10-09)

Optional saved `catalyst_context` binds to the current decision/input/source-audit
hashes and the earliest hash-valid issued decision per selected stock. Publication,
actual first capture and first decision clocks stay distinct. General media are
B supporting context; later reports never become an original selection reason,
probability, Kelly input or CIO approval.

The public YNA industry RSS supplements the existing nine feeds. Exact issuer
matching handles Latin case, mixed-script spacing and complete Korean particles;
group/chairman-only stories are not attributed to an issuer by assumption.
The existing source allowlist and per-source kill switches remain effective.
The compact stock chronology requires an exact issuer name/code in the title;
body-only mentions remain in the ledger but cannot present another issuer's
positive report as this stock's own catalyst.

Bounded reads retain the latest256 and pre-first-decision256 ledger rows per
stock. The eight displayed reports reserve four slots per capture period, then
fill unused slots from recent remaining reports. Original article capture clocks
stay unchanged; follow-up volume does not displace all pre-selection evidence.

Successful news sweeps and post-publication research refresh a separate immutable
sidecar. Failed updates preserve prior pointers without undoing completed research
or acquisition. GET only reads checked JSON; it performs no SQLite initialization,
RSS requests, fitting, writes or Telegram delivery. Detection receipts stay intact.

`python scripts/run_alpha_lab_catalysts.py` explicitly refreshes the context using
the existing read-only news ledger. Its first run freezes the protocol start for
`price_setup_leads_catalyst_72h_v1`. Subsequent new research decisions enroll selected
stocks and the exact same quality-universe controls. Historical decisions remain
historical; cohorts and original hashes cannot be retuned after observation. This
release registers and preserves observations; matured comparisons and rejection
of chance are not claimed. Missing RSS coverage is not evidence of no event.

Audit: `docs/sk_hynix_detection_audit_2026_10_09.md`. Provisional-price source
revisions remain terminal holds, excluded from completed performance.

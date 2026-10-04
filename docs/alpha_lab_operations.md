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

- `MarketFlow-AlphaLab-Research`:18:45KST,90-minute limit, completed-session source acquisition then research. An official closed date skips collection and preserves the last report.
- `MarketFlow-AlphaLab-Prime`:08:55KST,3-minute limit, official KIS session calendar preparation.
- `MarketFlow-AlphaLab-Monitor`:09:00–15:30KST every five minutes,3-minute limit, at most the three current proposal references. Known closed days issue no quote requests.

All use IgnoreNew and saved atomic/locked artifacts. Task installation does not launch a first research cycle. GET remains a cheap read; READY screens re-read saved status every30seconds and RUNNING screens every4seconds.
Flask production remains127.0.0.1:5003; development remains5001. Chart index scheduling stays independent.

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

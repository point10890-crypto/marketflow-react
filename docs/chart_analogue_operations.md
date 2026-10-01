# Historical chart analogue operations

This is a MarketFlow implementation using local price history. It does not call AlphaSquare, require its membership, use its proprietary model or call a generative model. Historical similarity is evidence for research, not a calibrated future success probability.

## Access

- Member page: `/dashboard/ai-bain/chart-predict?code=003690`.
- API: `GET /api/admin/mirofish/chart-analogue/003690` and `GET /api/admin/mirofish/chart-analogue/status`.
- Existing admin/active AI Brain access applies. Endpoints are read-only. No orders, payment operations or automatic notifications are created.

## Data installation and refresh

The repository already depends on NumPy. Reuse the project virtual environment; no additional ML package or model download is needed.

```powershell
# On the Windows MiniPC after pulling tested source:
Set-Location C:\bitman_marketfloww
.\scripts\install_chart_analogue_task.ps1
Get-ScheduledTaskInfo -TaskName MarketFlow-ChartAnalogue-Index
```

The dedicated task runs daily at18:10 Asia/Seoul on the MiniPC, with an initial build on installation. The existing `data/daily_prices.csv` supplies symbol names and the universe only. Its regular14:50 collection is an intraday observation and cannot substitute for a completed close.

The independent collector retrieves completed daily bars from the same NAVER public chart source used by the project's FinanceDataReader path, with bounded requests and concurrency. It atomically publishes `data/chart_analogue/closed_prices.csv`, preserving previous successful per-symbol snapshots and their actual capture timestamps when a provider request fails. Complete provider failure preserves the existing snapshot and index. The offline builder publishes a single atomic NPZ from this separate feed. Original market files, member data and credentials remain unchanged. Generated files are ignored by Git. Refresh requires price-provider network access; prediction API requests use only the prepared index. No vendor key or LLM call is required.

The source uses supplier-adjusted prices, as documented in the [FinanceDataReader guide](https://github.com/FinanceData/FinanceDataReader/wiki/Quick-Start). Every response identifies this basis. A newly collected adjusted history is knowable only from its actual capture time; it cannot be retroactively used for an earlier decision cutoff.

To rebuild manually:

```powershell
.\scripts\refresh_chart_analogue_index.ps1
```

The underlying daily price producer must continue updating its source. Rebuilding an old CSV does not make its data fresh. The API distinguishes unavailable index, insufficient history, insufficient analogues and stale observations rather than substituting predictions.

## Interpretation and validation

- The default input is252 observed daily sessions, with5/20/40-session historical outcomes. Outcome durations are observations in the source, not guaranteed consecutive exchange-calendar sessions.
- The displayed up frequency is the selected historical cohort's frequency. It is not a calibrated probability for the query stock. P10/P90 describe this cohort's range; they are not formal confidence intervals.
- Data capture time and completed historical outcomes must precede the decision cutoff. Intraday captures, unknown captures, duplicate sessions and severe discontinuities are filtered. The independent feed uses supplier-adjusted prices; corporate-action revisions and data-provider uncertainty remain visible. Explicit offline imports may use unadjusted prices and are labelled separately.
- Scanner integration records evidence in shadow mode before candidate selection. It does not change existing scores or production TOP3. Each run stores the source/model/cutoff in its chart analogue artifact.
- A forecast can be technically correct without improving detection performance. Prospective or chronological comparisons against the existing scanner, costs, market benchmarks and overlapping-outcome dependence must justify enabling any ranking weight.

Focused validation:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_chart_analogue.py tests/test_chart_analogue_source.py tests/test_chart_analogue_routes.py tests/test_chart_analogue_scanner.py -q
Set-Location frontend-react
npm run test
npm run build
```

Deployment follows the existing Windows5003 Flask task and `frontend-react/npm run deploy`. Verify the index task exit status, Flask health, unauthorized access rejection and the member page with actual numerical results before claiming installation complete. `scripts/verify_chart_analogue_installation.py` independently recalculates neighbour returns and checks finite JSON, capture cutoffs and repeatability.

## Prospective comparison of final TOP3

Workflow completion preserves the actual final TOP3 and the existing eligible pool. The comparison selector takes three covered eligible stocks with the highest frozen 20-observed-session chart median, with deterministic final-score/symbol tie breaks. It never changes production ranking, CIO eligibility, orders or alerts. A partial TOP3 or missing forecast is recorded as insufficient data rather than filled with invented picks.

Each cohort stores its actual recording time, final workflow decision time, original scanner forecast, source captures/basis and selected stocks in a write-once snapshot under `data/chart_analogue/evaluation/`. New captures are accepted only on the decision's Korean calendar day. An offline ingestion reads the original scanner artifact; it does not recompute old predictions against a newly refreshed corpus. The first eligible complete cohort per Korean decision day is fixed before checking future outcomes. Repeated intraday cohorts do not inflate paired-day counts, and missing outcome legs do not cause substitution with a later cohort or survivor stocks.

The comparison uses the first completed observed close on a date strictly after the decision's Korean date, then 5/20/40 further observed sessions. This is a paper close-to-close research convention, not an executed fill or a verified exchange-calendar sequence. Each basket has three equally weighted stocks. The cost assumptions are 23 basis points round trip plus 10 basis points of total round-trip slippage: 0.33 percentage points deducted from each basket's gross return. These are research assumptions, not measured personal fees. The existing TOP3 basket is the strategy benchmark; market-index outperformance is unavailable without a matching verified market series.

The evaluator pins one saved price index for the entire evaluation run. Entry and exit prices therefore share one supplier-adjusted snapshot. The frozen forecast is never rewritten. A revised same-date reference is identified as rebased, so new adjusted exits are not divided by an old unadjusted-vintage anchor. Complete spans and actual microsecond capture cutoffs are checked. A long gap or discontinuity immediately before entry cannot be substituted with a later resumed price path. Pending/blocked results have null returns, not zero. Only pairs whose six stock legs have matured contribute to descriptive average returns. Overlapping horizons and common market regimes still create dependence; day counts do not prove statistical independence or forward efficacy.

`GET /api/admin/mirofish/chart-analogue/evaluation` has the existing admin/AI Brain gate and reads a small cached report only. The member page shows comparison counts and waiting/blocked states independently of the currently queried stock. It starts no collection, inference or evaluation from an HTTP read.

The existing 18:10 price-refresh task now also evaluates retained cohorts after successfully publishing its new index. After updating tested source, initialize only this new stage:

```powershell
Set-Location C:\bitman_marketfloww
.\.venv\Scripts\python.exe scripts\evaluate_chart_analogue_shadow.py --ingest-latest
```

Evaluation updates cached results atomically; a failed evaluation retains the already prepared price index. Results cannot mature until the required later closes have actually arrived. The report's collecting state is an honest completed evaluation run with pending outcomes, not evidence of increased detection profit. Live ranking remains unchanged until a separate assessment of matured evidence justifies a policy change.

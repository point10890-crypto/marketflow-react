# Win-rate / Kelly research implementation plan

**Goal:** Turn the supplied 60% win-rate / 20% allocation hypothesis into an executable, reproducible offline stock research backtest, with no order execution.

**Architecture:** A standard-library engine consumes validated daily prices and point-in-time fundamental rows. Completed, non-overlapping train/validation trades determine eligibility and weights before an untouched portfolio-test period. A CLI accepts CSVs or a clearly labelled synthetic demonstration and exports JSON, CSV ledgers and a readable HTML report.

**Scope:** New `app/services/mirofish/kelly_research.py`, `scripts/backtest_winrate_kelly.py`, their focused tests and a usage guide. Existing scanners, accounts, broker routes, schedulers and production posts are outside this change. No new dependencies, paid providers or deployment.

## Research contract

- Signals use a daily return below a prior-only rolling mean by at least two standard deviations. This is a mean-reversion hypothesis, not a Maxwell–Boltzmann assumption or proof of undervaluation.
- Daily signal at session t can only enter at the explicitly chosen price of session t+1. Default is next-session close because the existing cache has no opens; open mode requires actual opens. Exit is entry plus five market sessions by default.
- Train and validation labels must finish inside their periods. Freeze selection and empirical log-growth Kelly estimates at validation end; test results cannot select candidates.
- Both periods require at least 30 completed samples, observed win rate >=60%, mean win / absolute mean loss >=1, positive net expectancy and Wilson lower bound >=60%. Confidence intervals are diagnostics under model assumptions; cross-symbol dependence and repeated trials are not removed by these gates.
- A gambling payoff example p=.60, b=1 gives .20. Actual stock allocation uses empirical net-return log growth, half Kelly and a 20% cap. Prior volatility further reduces risk; total planned exposure is at most 60% with a cash reserve.
- Default fixed-quantity/horizon simulation preserves the calibration trade contract. Optional daily constant-weight rebalancing reports its different execution/payoff assumptions. Fees, slippage and user-specified sell tax apply to every fill. There is no guarantee against loss or ruin.
- Missing sessions or prices of a held security fail explicitly. Missing, stale or future fundamentals cannot pass financial qualification. Current survivors and retrospectively adjusted prices do not prove survivorship-free or historically available data.

## Tasks

- [x] Engine: write failing temporal-integrity, statistical, sizing, accounting and missing-data tests; implement the pure engine; run focused tests (42 passed).
- [x] CLI: write failing CSV validation and export/demo tests; implement typed inputs, source metadata, reusable atomic JSON output and CSV/HTML reports (11 passed).
- [x] Demonstrate: run synthetic next-close, next-open and daily-rebalance modes; run codes 003690/005930/000660 from the real close-only cache. Real candidates remain blocked for missing point-in-time fundamentals.
- [x] Review: independent replay confirms no fictitious zero-volume fills, current-only signals, holdout selection freeze and cash/fill reconciliation (maximum observed accounting error 2.3e-16).
- [x] Verify: engine/CLI plus existing alpha-backtest and signal-contract tests total 62 passed; compile/diff checks pass. Generated JSON/CSV/HTML and the usage guide are the deliverables. Runtime outputs are ignored by Git.

## Sources

- [David Aldous, Kelly criterion and stock returns](https://www.stat.berkeley.edu/~aldous/Real_World/kelly.html): maximize expected log wealth using the return distribution.
- [Bailey et al., Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf): a simple holdout alone does not establish freedom from overfitting, especially after repeated trials.

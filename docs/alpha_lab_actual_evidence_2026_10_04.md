# Initial actual-data experiment: 2026-10-04

The first tournament inspected 52 current financial-quality stocks from a
TOP100 ranking dated 2026-10-01, using the audited long OHLCV acquisition ending
2026-10-02. The raw file has 421,295 rows across 100 symbols. Its SHA-256 is
`072989062b3b23570fdacd79b9e9ced24e1d56507d5bdbf2dfc9235c0a51b10c`.

The frozen training ends 2025-08-20; validation ends 2026-03-16; untouched test
starts 2026-03-31 and ends 2026-10-02. Returns below are hypothetical portfolio
returns with 10% per new research position, costs included. These are not live
account profits, and no strategy is promoted by its test ranking.

| Fixed strategy | Validation return | Test return | Doubled-cost test | Test win frequency | Closed test outcomes |
|---|---:|---:|---:|---:|---:|
| Momentum | +2.33% | −1.87% | −3.92% | 35.85% | 53 |
| Liquidity breakout | +20.69% | −5.49% | −6.72% | 30.30% | 33 |
| Mean reversion | +7.84% | −4.30% | −6.12% | 37.50% | 48 |
| Ridge ranker | +17.31% | −13.63% | −15.49% | 25.45% | 55 |

Validation selected liquidity breakout: 45 completed outcomes, 60% net winning
frequency and positive cost stress. Its subsequent failure rejects economic
deployment. The adapter preserves that selection and reports **held**, rather
than selecting a different strategy after seeing the test results.

Initial watchlist (not buy recommendations): 산일전기 062040, 리노공업 058470,
에코프로 086520. All allocatable weights are 0%. ATR plans and net-payoff Kelly
values remain visible for interpretation. The first actual decision day has
three pending future observations and zero matured outcomes; pre-decision
history is never reported as forward success.

Current-cohort survivorship, historical price/financial vintages, adjustment
verification, exact exchange calendar, and real execution remain unverified.
The complete private run and frozen forward journal stay outside Git. This
experiment is useful evidence of rejection, not evidence of a profitable edge.

The separate actual input refresh completed on 2026-10-04 using the existing
public 2026-10-02 dated ranking, DART financials, and OHLCV collectors. It acquired
100 symbols / 421,295 raw rows and retained 52 financial-quality stocks. The
loader used 214,834 valid rows, excluding 2,311 invalid OHLCV rows and 204,150
outside the quality scope. All three published input hashes matched. The final
experiment reproduced the same watchlist and rejected the selected strategy.
The optimized replay completed in about 10 seconds on this development host.
Failed refreshes preserve the previous valid snapshot and are surfaced in the
report. Final release/CI/production evidence is recorded separately after it exists.

# Alpha Desk: selected combination of the existing opportunity engine and handoff

The existing maximum-three opportunity engine now has causal leadership observations and a visible research watchlist. AI Brain's main dashboard uses the same authenticated desk as chart analysis; its read-only mode does not start scans or poll the API. No new provider, dependency, scheduler or order path is introduced.

## Reviewed inputs

| Input | SHA-256 |
|---|---|
| marketflow_alpha_team_and_kelly.diff | 464f2aa4296d887b4ef53d0d3379e59ad0e2af2b5d04c8759aa7e860f8a8b86f |
| SKILL_alpha_team.md | b8175bdcaca16cde64d0044a3cc96c77ee0da548024bf8ca6b5b8b175bbec048 |
| CODEX_HANDOFF_alpha_desk.md | 24bdf716ddb5ab183ab310a12163f04b22688c48bc6e2af7f9d5410f5817179c |
| Handoff's extracted 69-file patch | a1ffc859cddcb76b3d178f8ef77bab85661b1ccdbe4d8b42e739334e6f7afce6 |

The extracted patch hash matches the handoff. Its engine files are unchanged from the supplied diff; the substantive extra UI change is the AI Brain dashboard mount. This revision differs from the October 4 source reviewed in `alpha_team_selected_integration_2026_10_04.md`. In particular, it **does** generate `score_outcomes_confirmation`; that old criticism does not apply to this revision. Advertised long-term IC, portfolio and conviction-tier performance were not reproduced or imported as verified results.

## Adopted and adapted

- Top three cards retain the existing completed-net-outcome Kelly, doubled-cost evidence, uncertainty and correlation ranking. Plans still use the original ten-session policy, quarter-Kelly reference, 5% single-name and 15% board limits, official calendar/current-price checks and fixed initial expiry.
- Optional `quality-leadership-context-v1` annotations use only observations through the bound input session. Each usable symbol needs 252 consecutive observed cohort-calendar OHLCV bars; missing, duplicated, invalid, flagged or nontradable observations are not filled or repaired.
- The trend template uses close > MA50 > MA150 > MA200, MA200 above its value 20 sessions earlier, close at least 75% of the 252-session high and 130% of the low.
- A fixed descriptive rank averages percentiles of 120-session log-return trend quality, proximity to the 252-session high and 63-session return **among strict-trend names**. This is inspired by the proposal's rule F but substitutes a fixed observation for its trained committee; it is a new research heuristic, not the supplied validated rule F.
- Four displayed checks are strict-cohort top three, 21-session return of 10–40%, the full trend template, and proximity to the 252-session high. They overlap; their count is neither a probability nor proof of independent evidence. No post-selection historical conviction-tier profit claim is shown.
- Market breadth is the fraction of usable current quality-cohort stocks above MA200. At least eight valid names are required. Broad/mixed/weak bands are fixed at 60%/40%; otherwise the state is unknown. This is **not** KOSPI, a market-wide breadth measure or permission to buy at normal weight.
- Up to seven additional strict-trend names appear in a research table with observed close and returns. No weak names are inserted to reach ten; no unvalidated target, stop or Kelly is invented for this table. Clicking a name opens existing detailed analysis.
- Main candidates can be mean-reversion or other existing setups. A low leadership-check count is displayed honestly and does not silently change that policy. The two ranks are explicitly labeled.
- Context is separately versioned and audited under `opportunities/leadership-runs/`. Adding it does not edit/reissue sealed opportunities or old forward journals. GET projects only saved context and recursively removes private extensions. Bad optional context is omitted while original guidance survives.
- AI Brain main uses a wide desk followed by the existing narrow operational cards. Its independent read failure does not erase other sections. A token switch immediately removes another account's result; failed/stale/running reads suppress current entry guidance. Manual refresh is GET-only; local clock/visibility updates do not call providers.

## Not imported

The standalone 14-analyst research/runtime, marcap panel loader, new Alpha Team routes, ten-name forced proposals, account simulator, insurance-stop policy and duplicated Kelly package were not installed into operations.

| Review finding | Why it blocks wholesale import |
|---|---|
| Discovery labels can exit after the discovery cutoff | Rule/trade selection leaks confirmation results; future-mutation invariance is required. |
| `run_book` selects `entered & done` before entry | Future completion changes earlier eligibility and buying power. |
| Missing panel returns become zero; cache lacks revision checks | Missing observations and corporate actions can distort the research price history. |
| Later intraday exits fund earlier same-day entries | Execution ordering uses proceeds unavailable at entry time. |
| Historical net-win probability uses today's gross planned outcomes | It is a different payoff/cost model from completed net outcomes. |
| Duplicate market-close handling and fee-aware caps are incomplete | Repeated events can change fills; fees can breach position/cash limits. |
| Live re-admission, research-selected rules and conviction thresholds differ | Historical claims cannot certify the current live policy or independent validation. |
| Loose new API/client schemas and account-change handling | Can produce nonfinite JSON, UI crashes, stale labels and previous-account display. |

The current net-outcome Kelly and causal execution already cover stronger versions of the supplied duplicate package. A separate, source-vintage-controlled long-market study would require purged exit cutoffs, missing/terminal-outcome policy, matching live/research rules, actual benchmark data and a new prospective evaluation. No historical performance is claimed here.

## Representative verification

The saved 52-name, October 2 price snapshot was replayed through actual `service.scan_once` with isolated output storage and no provider calls. It produced 51 valid 252-session histories, 29 names above MA200 (56.9%) and four strict-trend research names: 코웨이, KT&G, HD현대마린솔루션, 삼성전자. Existing three opportunities remained 알테오젠, SK스퀘어, 이수페타시스; their leadership counts were 0/4, 0/4 and 1/4.

This is a saved-data replay, not an October 5 live price signal. The original discovery hash remained `41b7348c2d9d5712a2af4aeb765aecfc78a5d71418758778b5dc75ef74a08821`; original source output files were unchanged. GET did not write files. Actual entries, fills and account PnL were not inferred. Current-cohort survival bias, historical source vintage and corporate-action adjustment remain unverified.

Tests cover future-row invariance, gaps/halts/invalid OHLCV, thin cohorts, ties, undefined volatility, unsafe labels, source/symbol binding, recursive privacy, optional malformed context, sealed identity/price preservation, account changes, idle expiry, read-only desk lifecycle and existing chart behavior. The integrated test/build and browser results are recorded in the task's implementation artifacts; generated artifacts are not committed.

| Final check | Result |
|---|---|
| AlphaLab backend suite plus signal contract | 607 passed; zero failures/errors/skips |
| Full frontend suite | 65 files / 756 tests passed |
| Production frontend build | TypeScript and Vite passed; 18 routes prerendered |
| Real-snapshot browser, 1440px and 390px | Three original cards and four strict observations; no page errors, external requests or page horizontal overflow; both detail links and disclosure work |
| Local replay API | Authenticated 200, anonymous 401, private no-store, no internal paths |

Existing Browserslist age, React Router future-flag, unrelated test act/canvas and bundler timing warnings did not fail the checks. The browser/API verification uses a loopback-only fixture identity and never a production account.

No production credentials, account database, remote branch reset, provider-data download, scheduled-task installation or deployment command was used in this selected integration.

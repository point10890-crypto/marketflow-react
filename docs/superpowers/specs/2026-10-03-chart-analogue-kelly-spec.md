# Chart analogue → Kelly research system

## Result

Integrate source-backed large-cap stock discovery, historical analogue evidence, cost-adjusted outcomes, temporal stability checks, Kelly scenario sizing and frozen forward observation into the existing AI Brain chart page. The system scans the current market-cap TOP100's 52 financial-screen survivors, with reference owners restricted to the same approved universe. It displays at most three clearly labelled research candidates and all exclusion reasons. No brokerage connection or financial certification is created.

## Contracts

`chart_analogue_kelly.scan(universe, *, as_of=None, index_root=None, progress=None)` pins one NPZ vintage. The universe uses `ranking.ranked`, `quality.passed` and dated source metadata. Public protocol: `schema_version=1`, `policy_id=chart-analogue-kelly-v1`, `mode=research`, `status=ready|blocked`; source, policy, universe counters, candidates, leaderboard, approval and portfolio are explicit. `_audit` is saved separately.

Fixed policy: horizon 20 observed sessions after next-close entry; roundtrip cost 33 bps; minimum 30 cases in each cohort; similarity >=0.8; maximum three positions, 0.2 per position, 0.6 aggregate exposure, 0.4 cash; fractional Kelly 0.5. Source dates, actual capture microseconds, partitions and price barriers cannot be dropped. Stale or future source/universe data blocks the scan. Candidate owners outside the 52-stock scope cannot enter reference evidence.

Choose a label-independent chronological split. Training exits precede the split; validation input starts at/after it. Per-owner entire input/outcome spans cannot overlap. This is retrospective stability in today's surviving cohort, not vintage-correct walk-forward validation. Shared market regimes remain correlated; the Wilson lower bound is descriptive under its binomial assumption. Both cohorts must have >=30 samples, net win frequency >=60%, Wilson 95% lower bound >=60%, finite payoff >=1 and positive net expectancy for a positive research scenario weight. No-loss payoff is unknown. Kelly uses validation net return fractions, not binary odds or gross win frequency. Sequence: empirical optimum → half → 20% cap → extra half above 3% prior daily volatility → total/cash guard.

`approval.status=held`, `approved_exposure=0`, every `approved_weight=null` regardless of retrospective performance. Informational research weights are separate; unqualified candidates have zero research weight. Empty/no-loss/insufficient metrics cannot masquerade as positive evidence. Current-universe survivorship and unverified historical financial vintage remain visible.

## API and persistence

Separate authenticated GET/POST `/api/admin/mirofish/chart-analogue/kelly`; preserve existing admin/AI Brain gate and private no-store. GET reads bounded stored JSON and small NPZ metadata only. POST starts one fixed offline scan under a cross-process file lock. CLI accepts explicit prepared index and universe file; snapshots the universe atomically for subsequent runs. Completed same-input/source/cutoff runs are reused. Interrupted jobs remain retryable and previous results stay identifiable as stale. No network or LLM calls.

First successful shortlist per Korean decision day is frozen into a bounded journal before publishing the latest report. Later scans do not rewrite it. On a subsequent scan, existing observed_outcomes verifies source/basis/reference and records actual next-close entry →20-session exit. Forward metrics stay separate from retrospective metrics and do not auto-authorize trades. Pending outcomes remain pending. Repeated or failed publication recovers the original daily decision.

## User interface

Existing dense dark AI Brain layout, no new libraries. Put the panel above existing TOP3. Show actual stock names/codes, status, costs, sample counts, train/validation frequencies and confidence lower bound, downside and expectancy. Show normalized current252-session input against a closest factual historical case with its observed subsequent path. Selecting a stock updates existing individual analysis. Expose empirical→half→cap→volatility→scenario sizing and local KRW capital calculator. Clearly distinguish approved allocation held from research scenario. Include all-universe reasons, source vintage, stale/errors and forward observation counts. Existing subscription/auth routing remains intact.

## Verification

Boundary tests for scope/identity, future microsecond captures, next-close costs, full-span purge, no-loss/insufficient returns, finite output, stale data, deterministic ranking, private access gate, empty request enforcement, single-flight reuse, immutable daily decisions and pending forward outcomes. Actual 52-stock run plus repeat-run reuse. Frontend invalid contract/unknown approval/stale/empty/error/interaction tests, relevant regressions, full Vitest and build. Inspect the same React report component against actual output at desktop and mobile widths. Commit only intended source, tests and docs after passing checks. Generated data and credentials remain untracked.

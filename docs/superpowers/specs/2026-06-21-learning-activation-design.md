# MiroFish Learning Activation Design - 2026-06-21

## Objective

MiroFish learning exists to improve Top3 alpha candidate detection. It must not
become a generic automation feature, and it must not mutate production scoring
weights directly.

This change activates verified outcome memory gradually when replay-safe
evidence is useful but still immature. The current hard gate requires 100
backtest samples before any outcome-memory ranking delta can affect the scanner.
That is too conservative for the current 52-sample positive backtest state, but
lowering the gate directly would be unsafe. The design therefore separates
bounded early learning from full adaptive learning.

## Components

### 1. Learning Readiness

Expose a read-only learning readiness snapshot for operators and AI Brain
views:

- whether outcome-memory scoring is active
- why it is blocked or capped
- backtest sample progress toward bounded and full gates
- applied cap status
- Top3 performance guard status
- look-ahead safety and production weight mutation status

The readiness snapshot is explanatory only. It does not change scanner scores.

### 2. Bounded Maturing Gate

Keep the full replay gate at 100 samples. Add a bounded gate at 40 samples:

- `< 40`: observe-only, no ranking delta
- `40 <= samples < 100`: `maturing`, small caps only
- `>= 100`: existing full caps if quality gates pass
- negative expectancy or negative IC: defensive mode, downside-only memory

Caps:

| State | Tag Delta | Global Delta |
|---|---:|---:|
| maturing/watch | -1.50 to +0.75 | -2.00 to +1.00 |
| full ready/validated | -2.00 to +2.00 | -3.00 to +3.00 |
| defensive | -2.00 to +0.00 | -3.00 to +0.00 |

This lets the scanner learn lightly from real outcomes while preventing immature
samples from dominating alpha rank.

### 3. Top3 Metrics Guard

The guard watches look-ahead-safe Top3 performance metrics after learning is
active. It stores a baseline and disables learning if the current Top3 return
lift or precision-at-3 deteriorates for two consecutive qualified evaluations.

Guard rules:

- Top3 metrics must have enough qualified observations before the guard can
  disable anything.
- If metrics are insufficient, the guard remains advisory.
- If the guard disables learning, `score_control` forces `observe_only`.
- `MIROFISH_LEARNING_DISABLED=true` is a manual kill switch and also forces
  `observe_only`.

## Safety

- Production scoring weights remain unchanged.
- All ranking deltas remain bounded.
- Backtest artifacts must be marked look-ahead-safe.
- The full 100-sample threshold is preserved.
- UI/API exposure must say whether scoring is active, capped, or blocked.

## Verification

Required checks:

- 39 samples block learning.
- 40 to 99 samples enable `bounded_maturing` caps only.
- 100+ validated samples enable full `bounded_adaptive` caps.
- Guard-disabled and env-disabled states force zero caps.
- Scanner `mcp_ranking_delta` becomes non-zero only when policy allows it.
- Admin route exposes readiness without requiring a scoring mutation.

# AlphaLab detection v2

## Intent and authorization

The operator requested root-cause analysis, improved profitable-stock discovery,
tests, commit/push and verified deployment. Existing Flask/React/MiniPC architecture
and manual-only CIO contract remain. No broker orders, paid API, secret copying,
historical decision rewriting or profit guarantee is authorized by this change.

## Reproduced defects, not hindsight attribution

A monotonically falling synthetic series activates the old mean-reversion setup.
A positive full-year confirmation can conceal a negative recent tail. Negative
uncertainty-adjusted scores can fill all three slots and become entry candidates.
These mechanisms are independently reproduced; three losing primary paper outcomes
are not enough to attribute all losses to one mechanism or calibrate future wins.

## Fixed v2 specification (before evaluating its results)

Keep original v1 discovery/builder and original 106-session evolution protocol as
unchanged controls. New discovery ID is `quality-setup-opportunity-v2`, selection
basis `causal_recovery_recent_stress_then_confirmation`; new board ID is
`profit-opportunity-v2`. Known legacy records remain readable, with policy included
in new stable identities. Unknown policies fail closed.

Use the same TOP100 financial-quality universe, 1260-session history, 1008-session
calibration, 252-session confirmation, next-session open IOC, ATR14x2, stop cap8%,
2R target, 10-session horizon and 5/5/20bps fee/slippage/sell-tax assumptions.
Double costs without changing fills. Preserve quarter-Kelly reference cap5%,
planned-risk cap1%, zero approved exposure and disabled live orders.

At EACH historical and current signal prefix, require contiguous 61-session
prices, positive volume, close above SMA60, SMA20 above SMA60, positive
20-session relative return versus the same dated quality-cohort median and
20-session average close-times-volume >= KRW1billion. This cohort comparison is
descriptive, not an official KOSPI index. Apply the existing strategy setup too.
Mean reversion additionally requires close above the preceding session's high
and above its own open; a falling price alone is never a recovery signal.

Retain original calibration/confirmation completed-outcome gates. Additionally
require >=5 completed trades whose entry falls in the latest126 confirmation
sessions, with positive net and doubled-cost mean and compounded returns.
Recompute outcomes using those same causal gates; never attach v1 performance to
v2. No parameter grid or iterative tuning on the inspected losses is permitted.

For ranking, start with calibration stress mean minus1.96 standard errors, cap
that score at the recent126-session stress mean, then subtract the existing
causal correlation penalty. Both base and final scores must be positive. This
is a ranking heuristic, not a confidence interval or calibrated probability.
Empty slots remain cash. Current/future quote checks cannot override a failed
economic gate. Public wording identifies recovery, recent evidence and holds.

## Evidence and rollout

Preserve all old primary/opportunity journals and first-issued decisions. Keep
v1 inputs/report for the existing evolution control even when member output is
v2. New v2 forward evidence has a separate namespace and a sealed declaration;
only decision sessions strictly after its actual KST declaration day enroll.
Use fixed60 new decision sessions plus10 maturity sessions, no early winning
promotion, no extension based on returns; keep CIO approval held. Protocol and
policy hashes are immutable and code changes require a separately declared
version. New-member v2 evidence must not be pooled with old v1 outcomes.

Offline comparison is explicitly retrospective and current-cohort biased. Freeze
one comparison on the last252 supplied sessions, four63-session blocks, signals
every20 sessions and same data/cost/execution. Compare the full eligible universe
and both policies, not only today's survivors. Record slots, rejected reasons,
costed outcomes, pending/revised coverage and a continuous3-slot/5%/cash40%
portfolio separately; slot returns are not portfolio returns. Results cannot
establish untouched OOS, adjustment/vintage correctness or guaranteed profit.

GET stays saved-data-only. Live deployment must preserve legacy journal hashes,
use the tested merged commit, verify both health endpoints, actual saved v2
output, source/plan binding, existing tasks and authenticated member rendering.
Research refresh after deployment must not resend an old Telegram event or
mutate the old evolution cohort; verify new output in an isolated saved-input
root before publishing through the normal pipeline. Completed source collection
is reused. Logs, keys and raw notification receipts never enter reports.

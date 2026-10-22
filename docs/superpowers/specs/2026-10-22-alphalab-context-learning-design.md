# Contextual candidate model: a separate experimental hypothesis

Declared on 2026-10-22 before running this model on the newly collected KIS snapshot. The previous fixed v3 experiment remains intact: its recent 126-session comparison has 115 events, mean net return -2.4990%, and doubled-cost mean -2.8894%. These are negative results, not a validation success. Do not loosen v3 gates or relabel that comparison as an untouched v4 holdout.

## Fixed model

Policy `contextual-candidates-v4` keeps the v3 causal price setup, source contract, execution costs, ATR brackets, opening ceiling and chronological split. It replaces the unconditional pooled economic gate with a formation-only contextual model. Training contains only completed selected trades in the original 504-session formation phase; the following ten-session embargo and 126-session comparison do not supply training labels, feature scales, neighbor choices or threshold tuning.

At each original signal, features are return20, momentum60, relative return20, close/SMA20-1, close/SMA60-1, prior-high proximity-1, volume ratio, and the cohort median return20. Standardize with other-symbol formation feature means and scales; zero-variance dimensions contribute zero. Find the nearest 60 formation events by Euclidean distance, excluding the target symbol. Break ties by distance, signal date and symbol. Require at least 30 events, five distinct symbols, and five distinct nonoverlapping ten-session signal-date blocks. Same-block observations are averaged before estimating returns, so contemporaneous peers are not independent evidence.

For net and doubled-cost returns separately, shrink the equally weighted neighborhood block mean toward the equally weighted formation block mean with weight block_count/(block_count+5). The shrinkage prior also excludes the target symbol. Require both local observed means and both shrunken expected means to be positive. Rank qualifying current setups by expected stressed return, then structural score and symbol; return at most three, without padding. This is experimental conditional inference, not a calibrated win probability or proven future profitability. The old negative unconditional comparison remains visible with interpretation `v3_unconditional_retrospective_control_not_v4_holdout`.

Fractional empirical Kelly uses equally weighted local block returns, a 0.25 multiplier, a maximum 1% reference allocation, and the existing planned-loss bound. Approved exposure is zero and orders remain disabled. Output includes sample count, descriptive wins/win rate, symbol/block coverage, local and expected net/stress returns, training end, and explicit exclusion of target-symbol labels. A failed contextual gate returns no proposal; do not tune this design to force the current stocks through.

## Integration and new evidence

Freeze this model code and source contract in the new candidate desk protocol. Register a new prospective 60-decision-session window, with ten-session maturation, from actual declaration time. Immutable first decisions, source revisions and terminal outcomes remain preserved. No automatic promotion from retrospective or paper returns. Source data semantics and uncertified historical vintages remain disclosed.

Tests cover future-label invariance, exclusion of target labels including the prior, formation cutoffs, same-block duplication, nonpositive contexts, no padding, execution parity, immutable publication, source revisions, strict mobile payloads and saved-only API operation. Real first results are saved separately from v3 and not reused for threshold optimization.

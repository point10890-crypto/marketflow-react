# Autonomous Alpha Agent Lab — 2026-10-04

The user explicitly delegates architecture, implementation, research, testing and delivery to the agent team and requests creative alternatives beyond existing systems. No repeated design approval is required. The goal is a working, source-backed research and forward-observation system that can identify economically useful stock candidates; neither profit nor perfect reliability can be certified before observed evidence.

## Design

An independent AlphaLab compares four preregistered strategies: cross-sectional momentum, liquidity breakout, mean reversion and a learned ridge factor ranker. Qlib causal factors and rolling evaluation, FreqAI completed-data retraining and lookahead checks, and RD-Agent hypothesis/evaluation separation inspire original implementations. External benchmark results are research examples, not evidence for Korean stocks. No third-party executable code is installed or blindly vendored. Qlib reference revision: be725493eb1a6bbb42bf11b37aa7669f59610ff1 (MIT); RD-Agent 484776c211e4fbbeef03e0ec00d6bbee7362a4f4; Freqtrade GPL is conceptual reference only.

Agents: data audit, factor construction, learner, independent cost/replay critic, Kelly/risk and forward monitor. Structured stage outputs and input/content fingerprints make research reproducible. Existing persisted CIO and live operating contracts remain the risk boundary; this first complete system runs independent research/paper results and never places real orders or invents verified provenance.

## Input and scope

The dated TOP100 ranking and explicit current-financial quality cohort constrain every scan. Missing quality evidence is a held result, not an all-stock fallback. Long historical OHLCV is available locally with supplier-reported unverified corporate-action and vintage flags. Audit manifest hashes, identities, duplicates, finite values, OHLC consistency, volume, dates and actual capture times. Preserve original files and limitations; do not flip analysis_ready. Suspended/zero-volume sessions cannot produce fills. Unusable rows/symbols have recorded exclusion reasons. Current-cohort survivorship bias is visible.

## Research protocol

Use chronological fit/validation/untouched-test segments with matured net bracket labels; features and fit normalization only observe available prefixes. Strategy parameters are frozen before comparisons. Select the champion on validation only, never on the displayed final test. Evaluate the same policies with doubled trading costs. A candidate score is a model/rule score, not a probability. Show diagnostic portfolios separately from calibrated Kelly allocations and maintain zero weights where statistical evidence is insufficient. Append-future and modified-heldout tests must not change earlier features or validation selection.

## Replay and sizing

Signal after close, next observed session opening entry, frozen ATR stop/target, same-bar ambiguity stop-first, actual gaps, zero-volume deferral and finite horizon. OPEN exits may finance OPEN buys; later intraday or closing exits may not. Allocation limits include fees: position20%, portfolio60%, cash40%, maximum3positions. Mark missing quotes with last observed price and record nontradability. Price drift is disclosed and prevents additional allocations beyond caps; no claim that mark-to-market drift is mechanically eliminated. No forced final liquidation or unrealized-label wins. Kelly p/a/b comes from the same completed NET outcome distribution, half Kelly, position cap and a1% planned-account-risk limit. Planned stops do not bound gap loss.

## Product

Add a compact AlphaLab panel to the existing AI Brain chart-predict page, preserving access gates and symbol search. It shows agents, strategy validation/test/stress comparisons, actual top3 identities, plans, cautious sizing/held reasons, provenance and future observations. GET saved status is cheap. POST starts only the fixed-policy background scan; caller cannot choose paths, thresholds or order settings. Responses contain no secrets or host paths. Existing chart task invokes the new optional stage when canonical inputs exist. Same-day first forward decisions remain frozen, results mature from subsequent observed OHLCV, and duplicate refreshes cannot duplicate observations.

## Completion evidence

Focused red/green tests, existing regression tests, complete CI, frontend tests/lint/build, actual dated52-stock run, source and report hashes, browser desktop/mobile proof, deployed API/UI and MiniPC health. Commit/push/merge/deploy retain prior explicit user authorization. Future profitability remains an observed metric, not a completion assertion. Document known limits and leave automated forward monitoring operating.
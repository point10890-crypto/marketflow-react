# AlphaLab frontend verification — 2026-10-04

## Implemented member surface

The existing `/dashboard/ai-bain/chart-predict` page includes a compact strategy
laboratory above the existing chart/Kelly panels. Existing `ProGuard`,
`AiBainGuard`, symbol-name search and `code` query navigation remain in place.
The new panel reads saved status on mount and starts the fixed research policy
only on an explicit click. It polls while running, preserves the last validated
report during reruns/failures, and discards results from prior tokens.

The API boundary rejects nonfinite prices/scores, unsafe allocation weights,
more than three candidates, duplicate/invalid symbols, inconsistent price plans,
unknown strategy references, non-validation champion selection, private host
paths and unsafe research-reference links. Research quantities use fractions;
the view formats them as percentages. Unavailable values remain pending.

## Preserved existing PWA work

Comparison with `e9cbe2213cbff5f0f4c51d58e2a08bf1c169f35d`
(`Merge origin/main into codex/pwa-install-state`) identified the legitimate
source commit `3a49e7f25ad86254bd89e60cc36eb266454aa8c4`
(`fix: hide PWA install UI after installation`, 2026-10-03).
Its exact seven-file patch was applied without a cherry-pick or commit:

- `frontend-react/src/hooks/usePWAInstall.ts`
- `frontend-react/src/components/layout/InstallPrompt.tsx`
- `frontend-react/src/components/layout/Sidebar.tsx`
- `frontend-react/src/pages/AccountPage.tsx`
- `frontend-react/src/pages/LandingPage.tsx`
- `frontend-react/src/test/pwaInstall.test.tsx`
- `frontend-react/src/test/pwaInstallCtaGating.test.tsx`

The fix records installation in the current session, recognizes iOS standalone
mode, consumes single-use installation prompts and removes installation CTAs
and guides after installation. The reference's whole tree was not restored:
that would remove newer ATR/Kelly backend work in the current branch.

## Verification after PWA preservation

- Focused affected check: five test files, 88 tests passed.
- `npm run test`: **59 test files, 464 tests passed**, exit code 0.
- `npm run build`: exit code 0; TypeScript passed, Vite transformed 296 modules,
  and the SEO prerender completed all 18 routes.
- `git diff --check`: passed.

The build was generated from working changes on base revision `6d2d84b48faa`.
It is a local build verification, not evidence of production deployment or
an actual backend research run. Deployment and actual API/browser verification
remain the coordinating agent's integration work.

The first broad test run found one related regression in
`chartAnalogueEvaluation.test.tsx`: its global API fake treated the new
`/alpha-lab` request as a chart request. That boundary and the equivalent chart
page fake were corrected before the final green run.
Nonfatal existing output included stale Browserslist metadata and jsdom canvas
`getContext` messages. Neither caused a test or build failure.

## Economic hold explanations and actual saved payload follow-up

The backend's held-out loss, cost-stress loss, completed-sample, source
verification and inactive-entry reasons now have Korean explanations. The
fixed-split, correlated-outcome, assumed-cost, diagnostic-allocation and
subsequent-price-drift limitations are translated as well. A failed input refresh
explicitly says that the earlier valid snapshot was retained.

After these label changes, the affected three test files passed **72 tests**,
including 21 AlphaLab tests. `npm run lint` passed with host permissions, and a
fresh `npm run build` passed TypeScript, Vite and all 18 prerendered routes.

An ephemeral test read the actual public `status` inside the local storage
envelope and passed **two checks**: the frontend runtime validator accepts the
payload, and the real panel renders its stock identities, economic holds,
retained-snapshot explanation, four-strategy comparison and six agent states.
The validation-selected `liquidity_breakout` remains selected with status `held`;
its displayed fixed-test net return is -5.5%, and all three candidate weights
remain zero. The storage envelope SHA-256 at verification was
`d5fb90d545f8ac41936703508112f6d15c75461d59fe54af7c3b1242dfaccd02`.

The ephemeral test was removed with `Remove-Item -LiteralPath` after resolving
and checking that its path belonged to the assigned worktree. No actual price
data, saved status, or temporary fixture was added to source control. This is
actual saved-result validation/rendering evidence, not live provider or
production-browser verification.

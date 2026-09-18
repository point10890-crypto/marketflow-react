# Public guide enrichment implementation plan

> Execute the approved content work in the existing MarketFlow checkout. The editor handles the coupled data/rendering change; independent agents validate evidence and review the result.

**Goal:** Make the seven public education guides more useful through reproducible examples, source links, limitations and honest editorial provenance.

**Architecture:** Keep `guides.mjs` as the shared source for React and build-time HTML. Add publication/update metadata and shared reference markup; no backend dependency.

**Tech stack:** React/TypeScript, Vite, Node ESM, Vitest, Cloudflare Pages.

**Spec:** User-approved conversation of 2026-09-05: verify materials, enrich seven guides including DART/AI/VCP cases, review, deploy, check public pages and reassess review readiness.

## Global constraints

- No fabricated experience, personal review, market numbers or performance claims. Hypothetical arithmetic must be labeled and checked.
- Preserve original publication dates and Google verification tag/file. Do not install Analytics or submit AdSense review.
- Treat historical local artifacts as evidence only for the fields they contain, not current production performance. Publish no secrets, raw licensed datasets or internal paths.
- Preserve unrelated files. Stage only intentional changes. Test before committing; deploy only the approved frontend scope.

## Task 1: Verify source material and write the content

- [x] Independently inspect DART, AI outcome and VCP case provenance; save a bounded editorial evidence note.
- [x] Enrich `frontend-react/src/data/guides.mjs` with concrete methods, worked examples, mistakes and checklists for all seven topics.
- [x] Add `updatedDate`, `sources` and an honest common editorial disclosure; preserve `date`.
- [x] Correct planned-vs-realized loss, compounding, unsupported performance and automatic good/bad disclosure claims.

## Task 2: Render provenance consistently

- [x] First add a failing user-visible metadata/source test in `frontend-react/src/test/guideArticle.test.tsx`.
- [x] Update guide typings, React article/list dates and `dateModified` JSON-LD.
- [x] Share source/disclosure markup between React and `scripts/prerender-seo.mjs`; preserve canonical and creator identity.
- [x] Run focused tests; build and inspect all seven generated articles for body/source/schema parity.

## Task 3: Review and release

- [x] Independent editorial/code review; resolve factual or rendering issues.
- [x] Run full frontend tests, lint/build and browser checks. Distinguish pre-existing failures from changed-code failures.
- [ ] Commit only intended files, push approved release and run `npm run deploy` with the local cmd.exe script-shell override.
- [ ] Verify seven public URLs, canonical, JSON-LD, reference links and Google ownership assets. Do not claim approval or indexation.

## Progress

- Baseline: focused tests passed (2 files, 9 tests).
- Source checks: the VCP snapshot has insufficient provenance; use a verification-hold case. The selected AI artifact has five evaluated rows and no pending rows; do not invent missing-data examples.
- Red/green: seven new article-provenance tests failed on missing publication/update metadata, then passed with the implementation. Focused total: 16 passed.
- Full frontend: 39 test files / 236 tests passed; lint passed; production build passed (14 prerendered routes). Browser DART table and AI article have no page-level horizontal overflow at a 390px viewport.
- Generated-output audit: all seven exact shared bodies/reference blocks, canonical URLs, publication/update dates and citation arrays passed. An initial one-off audit command had an unquoted CSS-selector syntax error; corrected inspection passed without changing product code.
- Independent review: conditional dilution language and VCP section ordering corrected; scoped re-review reported no remaining findings.
- Release checks remain pending at this pre-release commit; actual deployed URL verification belongs in the final release handoff.

# Search Console indexing repair — 2026-09-17

## Verified starting state

Search Console report (updated September 14): 19 indexed URLs, 22 excluded
(12 redirects, 9 alternate canonicals, 1 robots exclusion). `/dashboard` is
intentionally blocked. URL inspection of `/community/post/3` showed the user
declared canonical and Google's selected canonical both pointing to the homepage.
The live initial HTML confirmed that error. The property had no submitted sitemap.

## Implemented

- Standardize public canonical and structured-data URLs on the final trailing
  slash form used by Pages static directories. Static sitemap follows that form.
- Pages Functions serve initial community article/board HTML with distinct
  title, canonical, Open Graph, structured data and actual public content.
  React continues to provide the interactive app using the same canonical.
- Fetch only anonymous `/api/public/community` endpoints. Preserve the backend's
  public-board allowlist, active-board and hidden-post restrictions. Missing
  posts return HTTP 404/noindex; upstream failures return 503 with retry hints.
- Sanitize article HTML with an explicit tag/attribute/scheme allowlist, escape
  titles and JSON-LD, decode text once for descriptions, resolve upload images
  to the API host. Do not forward client credentials to the public API.
- Add a cursor-paginated public sitemap API returning IDs only. Unlike the UI's
  notice list, it includes all public notices, including those older than 20.
- `/sitemap.xml` combines static URLs with live public board/post URLs, deduped.
  Fail instead of returning a partial sitemap on upstream/pagination failures.
  The 19,000-post bound should be replaced by sitemap indexes before reaching it.
- Scope Function invocations to community and sitemap paths. Private dashboard,
  admin, login and payment robots restrictions stay intact.

## Validation before release

- Original canonical tests failed (4); fixed suite passed.
- Description entity test failed before decoding fix, then passed.
- Frontend: 42 files / 246 tests passed; build and 17 static readiness checks passed.
- Edge: 11 tests passed, including missing/private data, pagination, XSS and redirects.
- Backend: 13 tests passed in isolated MiniPC worktree
  `C:\Temp\marketflow_seo_verify_20260917`. Local Python crashed in native code
  while constructing unrelated Pydantic schemas; the independent host was used
  for validation instead of treating that crash as a passing test.
- Actual workerd/Pages runtime on port4174: post3 and notice200 with self canonical;
  nonexistent post404 without a homepage canonical. Worker compiled successfully.
- Independent read-only review: no outstanding blocking findings.

## Rollout order and Google follow-up

Deploy backend endpoint before frontend Functions. Verify live sitemap coverage,
canonical signals before/after JavaScript, API health and private404 behavior.
Then submit the sitemap in Search Console and request indexing for principal
corrected pages. Existing redirect/private exclusions are intentional; do not
unblock private pages or expect every alternate address to become indexed.

Reference: https://support.google.com/webmasters/answer/7440203?hl=ko
Functions routing: https://developers.cloudflare.com/pages/functions/routing/

Google indexing and AdSense approval are separate decisions. Submissions do not
guarantee indexing or approval and report counts may lag the deployed changes.

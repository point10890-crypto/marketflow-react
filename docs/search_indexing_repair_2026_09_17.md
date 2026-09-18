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

## Production evidence

- Backend deployed first from main at `7a13ea995f593eb09074422a8b4be16415977ebf`.
  Backed up the previous public route with a matching SHA-256 before pull.
  Restarted only `MarketFlow-Flask` (production port 5003).
- MiniPC localhost and public API `/healthz` and `/api/health`: HTTP 200.
  New anonymous sitemap endpoint: HTTP 200, 155 public post IDs, no next cursor.
- Official frontend `npm run deploy` succeeded:
  https://63f2a6a0.bitman-marketflow.pages.dev
  Custom domain, Pages production domain and deployment URL serve the new
  `7a13ea995f59` assets.
- Live post3 and notice board: HTTP 200 with distinct self canonicals and initial
  article/list content. Static guide canonical matches its trailing-slash URL.
  Browser-rendered post3 retained exactly one matching canonical and correct title.
- Slashless public paths redirect 308 to the canonical slash form. Missing
  post/unknown board return 404 instead of homepage content. Robots still blocks
  the private dashboard.
- Live XML sitemap: HTTP 200, application/xml, 176 distinct canonical URLs,
  including all 155 public post IDs. No slash mismatch.
- Search Console accepted `/sitemap.xml` on September 17, then showed
  "사이트맵 처리 완료", 176 discovered pages and 0 videos. The initial pending
  fetch label cleared when processing completed.
- Search Console individually accepted indexing requests for these corrected
  canonical URLs (each showed "색인 생성 요청됨" and priority crawl queue receipt):
  - https://bit-man.net/community/post/3/
  - https://bit-man.net/community/notice/
  - https://bit-man.net/guide/signal-verification-worked-example/
- These are accepted crawl requests, not proof of completed indexing. Google
  had discovered the URLs via the sitemap but had not indexed them at inspection.
- Release implementation was also cherry-picked into the original development
  branch as `c45d6f7`, preserving unrelated existing work and untracked files.
- Temporary local Pages verification server on port 4174 was stopped.

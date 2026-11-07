# Existing AI Brain 10,000 KRW conversion

Goal: eligible existing AI Brain members apply in-app; administrators approve and Kongming access follows automatically.

Architecture: use the current subscription request queue and administrator transaction. A distinct `aibain_kongming_conversion` request costs exactly KRW 10,000 and does not renew AI/base subscriptions. Server eligibility is authoritative. Preserve existing mobile three-step checkout.

Ruling: conversion adds Kongming until the current finite AI Brain expiry, captured at application. It does not add 30 days. An indefinite manual entitlement cannot imply an unlimited paid add-on; exclude it from automatic checkout. Previously bundled or converted accounts cannot repeatedly receive conversion pricing. Suspension, expiry, changed eligibility and pending requests fail closed.

Contract: `user.ai_bundle_conversion = {eligible: boolean, amount: 10000, expires_at: string|null, reason: string}`; request `plan=aibain_kongming_conversion`, `expected_amount=10000`, nonblank `depositor_name`. Persist conversion expiry in a nullable request column. Application is duplicate-safe; approval revalidates active entitlement and is idempotent. Archived approved requests still consume conversion eligibility. Never alter real members/payments for testing.

- [x] Backend: eligibility, atomic request insertion, receipt expiry, approval/access/audit, status and admin summaries. Meaningful API tests cover invalid price, unauthorized/expired/bundled/duplicate, rejection/reapplication, expiry while pending, repeated approval and preservation of PRO/AI dates.
- [x] Frontend: prominent conversion card in existing plan/member entry, exact price and expiry in payment/pending, distinct admin type/confirmation, fresh eligibility check before showing bank details. Test new flow and unchanged normal pricing.
- [ ] Independent review; focused and full frontend checks, backend regressions and CI.
- [ ] Commit/push, production DB backup, MiniPC pull/restart + health, Pages deployment, isolated deployed-code request/approve/access verification, real data integrity and responsive UI verification.
- [ ] Correct notice 315 from Kakao-only migration to direct app application after production succeeds.

Review focus: stale client user data; concurrent double submission/approval; archived approvals; expiry while awaiting approval; mistakenly granting a fresh 30 days or changing admin/base access.

# Subscription renewal and member management implementation plan

> **For agentic workers:** Use subagent-driven-development for the assigned independent tasks. Check only the files you own into the eventual release.

**Goal:** Expired members can immediately reapply and administrators can approve renewal, expire every subscription product, reactivate membership and delete an account from a readable desktop or portrait workflow.

**Architecture:** Extend the existing Flask subscription endpoints and React subscription entry component. The server remains authoritative for access and pending applications. Use the existing isolated worktree and preserve unrelated AlphaLab work.

**Tech stack:** Flask, SQLAlchemy, SQLite, React, TypeScript, Tailwind, pytest and Vitest.

**Spec:** The user's November 5 request and established subscription semantics: Pro is time limited, Ultra Pro is lifetime unless explicitly expired by an administrator, and AI Brain temporarily pauses Pro's remaining time.

## Constraints and review focus

- Production is Windows MiniPC `C:\bitman_marketfloww`, API `127.0.0.1:5003`; preserve the separate 5001 producer.
- No real member approvals, expirations, deletions, payments or notification sends during implementation or release verification.
- Expiry does not delete account history. Pending requests survive forced expiry and require a deliberate approve or reject action.
- A pending application must lead to approval status rather than another payment request. Network failure must not invent an active entitlement or empty application history.
- Paused Pro and lifetime Ultra Pro must not be incorrectly expired by a leftover timestamp. Explicitly expired Ultra Pro must be renewable.
- Protect administrator accounts and suspended/rejected status from accidental access restoration.
- Delete confirmation describes account/content removal and retained administrative history; it does not promise complete historical personal-data erasure.

## Task 1 Backend administration

Owner: backend worker. Files: `app/routes/admin.py` and focused backend tests.

- [x] Add failing tests for all-product expiry including premium, paused Pro and AI Brain; authorization and blocked-user guards; pending history preservation; renewal after expiry.
- [x] Implement `POST /api/admin/users/{id}/expire` with `{note?}` returning `{message,user}`. Expire both products, clear pause, set renewable expired status, and commit the audit with the entitlement changes.
- [x] Test deletion with foreign keys enabled and surviving replies by other members. Detach parent references, atomically preserve the delete audit, and sanitize failures.
- [x] Preserve legacy `/revoke`, billing amounts and subscription history. Run focused backend checks.

## Task 2 Member renewal flow

Owner: member UI worker. Files: shared expiry/funnel helpers, `SubscriptionEntry`, PlanSelect, PendingApproval and focused tests.

- [x] Add failing clock-boundary, paused/lifetime, pending-precedence, rejection, late-response and retry tests.
- [x] Reuse the persistent entry card and 30-minute reminder. Make prior-plan reapplication the primary action and alternative plans secondary.
- [x] Share expiry semantics, keep pending approval visible, retain rejection reasons and reapplication buttons, and guard account changes and stale status reads.
- [x] Verify mobile portrait layout and existing subscription journey tests.

## Task 3 Administrator controls

Owner: admin UI worker. Files: UsersTab, SubscriptionsTab, a focused member-action panel, related tests; ProExpiryTab only as needed.

- [x] Add failing tests for visible member controls, exact pending approval, all-product expiry, action errors, double submission and partial delete failure.
- [x] Expose a compact subscription management entry on desktop, mobile and detail views. Approve existing pending requests before allowing direct grants.
- [x] Reuse grant and extension endpoints; use the new expiry API. Explain the account deletion target and effects, and keep failed records visible.
- [x] Invalidate older reads when mutations begin and preserve errors/retry behavior.

## Task 4 Session consistency and integration

Owner: root. Files: `AuthContext.tsx`, `lib/api.ts`, auth consistency tests and this plan.

- [x] Reproduce old authentication responses overwriting renewal or resurrecting logout.
- [x] Guard all authentication reads by session identity and read generation. Keep transport failures offline tolerant and accept a current definitive 401.
- [x] Add the typed `adminAPI.expireSubscription(id,note,token)` wrapper and integrate worker contracts.
- [x] Run focused tests, then frontend lint/tests/build, backend impact checks and CI. Review authorization and preserved state with an independent reviewer.
- [ ] Commit only this change, push, deploy through the existing frontend command and guarded MiniPC restart, then verify public health and production UI without real mutations.

# Control Center integration

Goal: integrate the supplied Control Center into current MarketFlow so administrators see service, data, schedule, authentication, and monitor failures reliably without increasing production load or mutating business data.

Base: main d820985a653308cc7c3bf7a3484546f4a243d903. Supplied patch SHA-256 9b7a1f5e98d0170bb25f67a39c33300cf8f8e178b6da58f8e10342a92f8aeb20, 33 files, based on older PR 52. Apply was clean; source claims must still be independently verified.

Rulings:

| Area | Risk in handoff | Integration ruling |
|---|---|---|
| Workspace | Main checkout has unrelated community edits | Reuse clean linked worktree on codex/control-center-20261107; preserve user work |
| Prior feature | Subscription conversion just deployed | Keep its code/access contract intact and run regression checks |
| Monitoring | GET does not guarantee absence of side effects; full app factory may start workers/migrate DB | Audit collectors, use isolated inventory app, bounded read probes, no business data writes |
| Freshness | One healthy fast heartbeat may mask stalled standard/deep work | Verify each tier and partial/unknown coverage explicitly; never show skipped data as healthy |
| Operations | Document suggests extra identities/alerts/OpenClaw grants | Do not enable Telegram, create an admin account, or alter OpenClaw configuration. Ship inactive preview assets only |
| Scheduling | New process must not overload API or shared SQLite | Bound requests, prevent overlap, validate host/root and exact scheduled commands before registration |
| UI | Dense desktop-first supplied screen | Preserve MarketFlow layout, prioritize mobile portrait, admin-only route and stale/error states |

Tasks:
- [ ] Review/fix runner, storage, incident lifecycle and admin API; meaningful failure/concurrency regression tests.
- [ ] Review/fix HTTP, provider, local checks and inventory; authentication, secret redaction and no-side-effect tests.
- [ ] Review/refine frontend route/menu and mobile states; focused then full Vitest/lint/build.
- [ ] Reconcile runtime contracts and task registration with actual MiniPC read-only evidence.
- [ ] Independent whole-branch review, focused backend regressions, full CI, commit/push/merge.
- [ ] Deploy verified source; bounded first no-alert run; inspect failures honestly; register safe recurring tasks; verify scheduled run and production admin API/bundles.

No real orders, account/payment mutations, paid model calls, new credentials, other project ports (8080), or automatic repair actions. Prior quiet service-guard notification preference remains in force.

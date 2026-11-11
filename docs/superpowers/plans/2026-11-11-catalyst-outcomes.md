# Catalyst outcome desk implementation plan

Goal: source-grounded historical returns and current research candidates on a twice-daily dashboard.
Architecture: read-only source adapters -> bounded cached daily-price acquisition -> immutable per-horizon outcome store -> frozen candidate policy -> saved GET view and React panel.
Spec: docs/superpowers/specs/2026-11-11-catalyst-outcomes-design.md

- [ ] Source adapters in app/services/catalyst_outcomes/sources.py and prices.py; independent tests for full inactive archive, source identity/provenance, bounded/resumable pricing.
- [ ] Pure analytics and service/store with tests first: session causality, costs, missing/halt/event flags, revisions, per-slot idempotency, candidate policy and coverage.
- [ ] Authenticated GET route, CLI and Windows schedule10:00/15:00 with recovery; GET never acquires or fits.
- [ ] Typed React client/panel on dashboard and catalyst page; semantic mobile layout, all cases/search/pagination; tests/lint/build.
- [ ] Independent review, focused then broad tests, live bounded bootstrap and source replay, commit/push/CI/deploy and actual operation/PC/mobile verification.

Review focus: weekends/holidays and today's incomplete bar; imported late discoveries vs recorded receipts; duplicate syndication and repeated same-stock events; source revision cannot rewrite closed outcome; partial source/price failures cannot publish misleading full coverage.

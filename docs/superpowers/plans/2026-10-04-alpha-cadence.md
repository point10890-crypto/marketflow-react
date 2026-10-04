# AlphaLab Cadence Implementation Plan
> For agentic workers: use superpowers:subagent-driven-development; preserve unrelated edits.
**Goal:** Complete close detection -> official next-session reference -> five-minute guard -> existing paper outcome workflow.
**Architecture:** Separate provider + monitor registry/projection; root integrates existing proposals/service/routes. Frontend polls saved data.
**Tech Stack:** Flask/Python, requests/filelock, React/TypeScript/Vite, Windows Task Scheduler.
**Spec:** docs/superpowers/specs/2026-10-04-alpha-cadence.md

## Global Constraints
No broker orders/new fees/secret output. Development5001, production5003; preserve both original journals. Optional backward-compatible fields, no GET I/O mutation/external calls. Pin source identity, don't renew window on rescan.

## Review Focus
1. Holiday/calendar gaps and future/previous-day quotes never certify current-price eligibility.
2. Same snapshot rescan must not renew source-bound origin/window.
3. Late quote failure or changed snapshot must hide earlier price guidance.
4. Session opening must not be replaced by minute opening, no actual fill claim.
5. Paper summaries exclude revised outcomes and never imply account P&L or guard-tested performance.

## Task1: strict provider and operations scripts (handoff_agents_review)
Files alpha_lab/market_provider.py; tests/test_alpha_lab_market_provider.py; scripts/run_alpha_lab_monitor.py; scripts/install_alpha_lab_tasks.ps1; update refresh_alpha_lab.ps1 to skip verified closed days via monitor CLI calendar-check.
- [x] Add injected HTTP/time failure and minute-vs-day open tests; run red.
- [x] Implement normalized calendar/quote provider and bounded CLI task wrappers.
- [x] Run focused provider and script checks green; leave git to root.
Interface KISMarketProvider.fetch_calendar(base_date,now)->{source,captured_at,days:[{date,is_open}]}; fetch_quote(symbol,now)->{symbol,price,opening_price,quote_at,fetched_at,source}.
CLI calls monitor.run_monitor(root,provider,now); calendar-check returns0open/10closed/2unknown and wrapper preserves original source failures.

## Task2: sealed monitor lifecycle (handoff_bracket_review)
Files alpha_lab/monitor.py; tests/test_alpha_lab_monitor.py.
- [x] Write red injected-clock/storage tests for five Review Focus cases.
- [x] Implement register_report(root,report,now), run_monitor(root,provider,now), attach_operations(status,root,now), calendar_check(root,provider,now).
- [x] Persist authoritative calendar once/day; identity+origin freeze; attach optional public proposal_window only certified/identity exact.
- [x] Reprice signalATR at accepted official opening reference, never orders/fills.
- [x] Run focused monitor tests green; preserve original files/journals; leave git to root.

## Task3: API+proposal integration(root)
Files service.py, proposals.py, opportunities.py, admin_mirofish.py and focused tests.
- [x] Add red tests for optional certified session window vs legacy24h and cheaper GET.
- [x] Register first source identity only after complete report creation; route read+project optional operations; suppress running/failure guidance.
- [x] Use rigorously validated session window for opportunities expiry; legacy unchanged without it.
- [x] Run focused regression tests.

## Task4: operations UI(alpha_system_ui_scope)
Files alphaLabApi.ts, AlphaLabPanel.tsx, alphaLabPanel.test.tsx.
- [x] Add red runtime-validator/identity/calendar expiry/poll+stale+paper tests.
- [x] Optional strict typed operations, compact cadence panel, per-BUY quote states and opening-reference plan, separate existing opportunity forward outcome summary.
- [x] Poll saved status every30sec with request generation/token cleanup, retain4sec running poll; no paid computation.
- [x] Focused tests green then root broad tests/build.

## Task5: independent review + completion(root)
- [x] Cross-review implementations and fix failures.
- [x] Full Python/frontend, lint/build, diffcheck.
- [ ] Commit focused owned source only, push, CI, attachedPR, merge tested tree.
- [ ] Deploy backend and tasks MiniPC, verify real KIS closed-state/calendar + API health/auth/noorders/journal integrity.
- [ ] npm run deploy and actual desktop/mobile browser with final artifact/build verification.

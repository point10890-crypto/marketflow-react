# AlphaLab cadence and next-session monitoring
Date: 2026-10-04
User authorization: "구축 구현 작업 진행 완료 까지 해", continuing authorized commit/push/deploy work.

## Outcome and scope
Connect the existing close-based BUY3 analysis with authoritative KIS next-session confirmation, saved five-minute price guard monitoring, automatic UI refresh and existing forward paper outcomes. Keep manual investment decisions and no broker orders. No new paid model, account, dependency or communication channel.

## Design
Existing daily research remains18:45KST and follows successful completed-session source acquisition. Dedicated monitor primes a KIS session calendar08:55 then ticks every300seconds through15:30. Known closed dates skip source collection and quote requests; missing/calendar failure never certifies an open session. GET reads sealed artifacts and projects time expiry only, never fetches, fits or writes.
Provider source: official KIS CTCA0903R calendar (tr_day_yn AND opnd_yn); J-market inquire-price daily stck_oprc paired with FHKST03010200 output2 business-date/time minute close. Require finite positive values, current business date, bounded timestamp and success rt_cd; no response/key logging.
Source identity = canonical fingerprint + opportunity audit hash + stable BUY candidate/plan hash. Pin first report decision_at for that identity in a separate sealed monitor registry. Rescans do not renew it. Entry session is first authoritative trading date strictly after original KST decision date; missing calendar dates hold. New optional next-session-proposal-v1 window ends at that session15:30KST, overriding legacy24h only after complete identity/calendar validation. Original stored report, experiments and both forward journals remain unchanged.
Use frozen candidate plan. ATR is available in opportunity plan; adjusted opening-reference barriers use min(2ATR, open*.08), target=open+2distance. Quotes are observations and references, never fills. Opening above1.02reference or below original stop skips new entry for that session; subsequent observations cannot reinterpret opening as accepted. No capital approval.
Monitor stale/failure/pending/research error/identity mismatch hide live guidance. Quote TTL420seconds; provider incoming trade-age maximum120seconds and no future dates. Public monitor projection compares server/current time and original identities; old current quotes never survive a failed attempt as fresh.
Forward panel uses existing opportunity_scan.forward, explicitly paper_next_open outcomes and entry_guard_applied=false. Denominator is closed/unrevised outcomes only, unknown/no matured yields null, no account return.

## Public contract (optional AlphaLabStatus.operations)
schema_version=1; policy_version=alpha-cadence-v1; generated_at UTC.
cadence: timezone Asia/Seoul, research_time18:45, monitor_interval_seconds300, market_state open/closed/holiday/unknown, calendar_status ready/held/failed, calendar_checked_at UTC|null, last_scan_at UTC|null, next_scan_at UTC|null, last_monitor_at UTC|null, next_monitor_at UTC|null, reasons enum list.
monitoring: status ready/held/failed, decision_at currentreport UTC|null, origin_at pinned UTC|null, input_fingerprint64hex|null, opportunity_audit_hash64hex|null, entry_session date|null, valid_until UTC|null, observed_at UTC|null, quotes<=3, reasons enum[].
quote: symbol6digits, price positive|null, quote_at UTC|null, fetched_at UTC|null, opening_price positive|null, source KIS:J:FHKST03010200+FHKST01010100, entry_state wait_open/within_band/above_ceiling/below_stop/target_reached/closed/stale/unavailable, reference_price positive, entry_ceiling=reference*1.02, stop_price/target_price originalreference; adjusted_plan optional{entry_price,stop_price,target_price,loss_fraction,proposed_weight}; reasons enum[].
paper: existing opportunity forward summary counts+decisions/matured/win_rate/mean_net_return, basis frozen_watchlist_next_open_outcomes_not_account_pnl, entry_guard_applied=false.
Optional report.proposal_window: policy_version next-session-proposal-v1, input_fingerprint, opportunity_audit_hash, origin_at, entry_session, valid_until, calendar_source KIS:CTCA0903R. Validated by server and client, exact nextsession15:30 timestamp, origin<=decision, source consistency, maximum7KSTdays. No authority/order flags change.

## Persistence
Separate monitor registry/calendar/current artifacts under data/alpha_lab/monitor. FileLock and atomic JSON hash envelopes. Preserve terminal source-bound opening-reference decision, last failure replaces current guidance, append bounded immutable observations or preserve source-bound decision audit. Capacity fails closed. Generated data never staged.

## Verification and delivery
Inject clock/provider/storage, red then green for weekend+holiday rollover, original-time persistence, stale/future/symbol mismatch, invalid calendar, opening-vs-minute-open, gap skip persistence, ATR/caps, saved corruption, missing sources, cheap GET, latest-request UI races, clock/timer/focus expiry, paper denominator. Focused tests then complete Python/frontend checks +lint+build. Independent review. Commit/push/CI/PRmerge, MiniPCff-only task installation+Flask5003restart, frontend npm run deploy, health/auth/bundle/task config and user-authenticated deployed browser desktop/mobile proof. TodaySunday live verification must show closed/awaiting next official session; replayed open-session tests do not count as live fills.


## Bounded recovery ruling
Successful official calendar snapshots are reused for the KSTday. Failed observations retry no earlier than15minutes, at most3attempts per KSTday; unknown results never certify a session. First certified entry session/deadline are sealed separately per source identity; later official-calendar disagreement yields calendar_revision and WAIT instead of moving the window.

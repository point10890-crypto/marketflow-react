# TOP3 advisor operational audit — 2026-11-10 KST

## Observed production state

Baseline release: `fb378d8f`. At 19:40 KST, MarketFlow's article collector,
evidence-review worker and TOP3 advisor had successful scheduled-task exit codes.
Authenticated TOP3 GET and both health endpoints returned HTTP 200 in about one
second. The independent BusinessPost feeds had a 19:30 collection receipt and
their newest article was published at 18:22. Imported original-Kongming archive
rows remained separate from independently collected MarketFlow articles.

The currently sealed regular-session desk inspected 49 stocks and contained one
research candidate, 삼성E&A (`028050`), from the November 9 price session. The
three debate roles had completed: analyst via the permitted OpenAI fallback,
critic/chair via Anthropic. The analyst's fallback reason was `invalid_json`,
not account-access failure. No recent 72-hour article matched this candidate in
the BusinessPost store. The newer multi-publisher Omni archive's matching
Samsung E&A articles were also older than 72 hours. Those articles must not be
relabeled as current to populate a shortlist.

This is operational evidence, not proof of profitable stock selection. The
20:30 research schedule, sealed contextual ranking, original entry plan and CIO
approval contract remain unchanged. No new profit-claim, threshold tuning,
account order, paid provider, or increased spending ceiling is introduced.

## Confirmed problems and fixes

1. **Price evidence was ambiguous.** `with_verified_prices` measures an article's
   post-receipt price reaction, but its absence was described as missing saved
   price data. Sealed desks now provide separate `sealed_reference_price`
   context; event-price absences explicitly use
   `article_post_receipt_price_response`. The UI labels that count “기사 후 가격
   검증”. Neither becomes a claim that current quotes or causal impact are
   independently verified.
2. **News coverage omitted another existing collector.** The advisor now joins
   the existing MarketFlow Omni SQLite archive read-only, with no fetch or
   additional paid search. Exact saved stock symbol and title identity, aware
   publication/receipt clocks, a 72-hour horizon, safe original links, sports
   exclusions and duplicate controls are enforced. The query has a half-second
   progress deadline and bounded per-symbol rows. Unknown producer poll
   freshness remains explicit. Imported original-Kongming rows stay excluded.
3. **New titles could displace useful validation.** The bounded article selection
   preserves articles with existing symbol-bound verified filing/price evidence
   ahead of newer unverified titles. Duplicate publisher records cannot inflate
   the evidence count. Missing event-price data stays explicitly citable.
4. **Event clocks were actually worker-start clocks.** Request, raw-response
   receipt, completion, cooldown and final-seal timestamps now advance with
   monotonic elapsed time anchored to the run's start. Old completed receipts
   are preserved byte-for-byte; their historical timestamps are not repaired
   retrospectively.
5. **Recovered results and fallback causes were misleading.** CLI completion
   counts include `RECOVERED_RESPONSE`; the UI distinguishes invalid output,
   exhausted budget and exhausted credits instead of calling every fallback an
   access restriction.
6. **Optional article work exhausted the shared call count.** At inspection the
   November 10 UTC-day ledger contained 100 settled provider attempts, costing
   approximately USD 0.09843; 42 saved article reviews had budget refusals.
   Optional scheduled article extraction now leaves up to nine calls inside the
   existing limit for priority comparison/TOP3 work (three roles, up to three
   providers each). Admission is checked atomically against all existing pool
   usage. Other priority comparisons may also consume this headroom; it is not
   a guarantee of unlimited TOP3 refreshes. Already spent attempts stay spent.
   No quota reset or increase is permitted by this correction.

## Validation and release evidence

Regression tests first reproduced missing price scope, false event clocks,
recovered-stage undercount, missing multi-publisher linkage and stripped original
links. Focused tests also cover unchanged ranks/plans/decisions, no extra charges
on replay, bounded read-only databases, invalid/future timestamps, exact issuer
matching, richer validation retention, deduplication and safe public projection.

The prompt and substantive input change create a new comparison fingerprint.
Existing completed receipts and uncertain charged attempts are retained; no
ledger is reset to force another payment. New work remains under the existing
shared USD 1/day admission ceiling. A budget refusal remains incomplete and is
not reported as a completed discussion.

Local and production evidence is retained under
`data/top3-audit-20261110/` and `data/operations/`, outside Git. Final acceptance
checks include CI on the reviewed commit, production task history, authenticated
API output, original-decision hashes, unchanged-input no-call replay, actual
role completion clocks and PC/mobile rendering. Production release identifiers
and actual selected stocks belong in those receipts rather than this static
pre-release audit.

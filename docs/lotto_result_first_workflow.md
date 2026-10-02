# Lotto recommendation result-first workflow

Updated: 2026-10-02

## Reader flow

1. Read the last completed draw's official numbers and compare every combination actually published before that draw.
2. Follow the original recommendation link and inspect matched main numbers, bonus match and the rank for each individual six-number combination.
3. Read the new draw's recommendation. Its opening section links back to the previous result report.

Historical predictions are never regenerated after a draw. Legacy posts are recovered from their currently published HTML, and the report explains that no pre-draw immutable snapshot exists for those old posts. Missing or ambiguous recommendations remain unverified rather than being counted as losing tickets.

## Sources and calculation

The primary official adapter uses the endpoint exposed by the Donghaeng Lottery result page:

- Page: https://www.dhlottery.co.kr/lt645/result
- API: `/lt645/selectPstLt645InfoNew.do?srchDir=center&srchLtEpsd={draw}`

The response can contain neighboring rounds. Validate the exact requested round, its expected Saturday, six unique main numbers in 1..45 and a distinct bonus number. Results remain pending before Saturday 21:00 KST. The original recommendation must predate the Saturday 20:35 KST broadcast. Naive community timestamps are interpreted as UTC, matching the application's database contract.

Rank comparison is deterministic: 6 main numbers is rank 1; 5 and the bonus is rank 2; 5 is rank 3; 4 is rank 4; 3 is rank 5. Other combinations are not winning combinations. Bonus matching does not add to the main-number count. Every published combination, including non-winning combinations, stays in the result table. This is a comparison of recommended numbers, not proof that a ticket was bought or a prize paid.

## Publication and recovery

`python scripts/lotto_analysis.py` ensures the completed result report before publishing the next recommendation. `--results-only` publishes or repairs the completed report without generating new recommendations or calling an LLM/image provider. `--dry-run` does not publish.

A separate file lock prevents concurrent manual/scheduled lotto workflows. Recommendation and result posts use exact round/type identification and are checked against the same API that receives writes. A successful POST is verified by GET. A failed later step is resumed using saved prepared content and receipts rather than generating different numbers or duplicating an earlier post.

The default publication API is `https://marketflow-api.bit-man.net`. `LOTTO_PUBLICATION_API_URL` is an explicit lotto-only override for isolated fixtures; saved receipts are bound to that API identity. Incomplete list responses stop publication. Legacy titles are recognized alongside the new standardized titles.

New recommendation generation and its final POST both require a time before Saturday 20:35 KST, including generation that crosses the cutoff. Result-only publication and adding the review link to an existing recommendation remain allowed afterward.

New recommendations include a deterministic, machine-readable complete number table and save their prepared candidate/body snapshot and publication receipt. Existing current recommendations receive only the result summary/link prefix; their previous title, number content and images are preserved.

## Schedule

Existing recommendation schedules stay Friday 17:00 and Saturday 09:00 KST. Separate result jobs run Saturday 21:10 with a Sunday 09:00 recovery. They use separate daily run keys from the recommendation jobs.

The MiniPC's `MarketFlow-Scheduler` daemon must be restarted to load new schedule registrations. Flask production remains port 5003, and production community verification uses `https://marketflow-api.bit-man.net`. Localhost-only publication checks are insufficient.

## Verification

Focused tests cover official source integrity/pending draws, bonus ranks, exact round/type deduplication, legacy/canonical number recovery, full result disclosure, result-before-recommendation ordering, no inference in results-only mode, post verification, interrupted pin recovery, file locks and scheduler job keys. Live validation compares the prior published source, official result and saved output against the deployed community API and visible frontend.

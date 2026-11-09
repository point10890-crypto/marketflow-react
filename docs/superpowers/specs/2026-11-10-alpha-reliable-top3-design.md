# AlphaLab regular-session evidence and TOP3

## Observed problem
The November 6 KIS daily close saved after 20:30 changed in 47 of 49 symbols on November 9. On November 10, live public-price probes for 028050, 000660, and 033780 reproduced the old values at 19:59 and the revised values at 15:30. Adjusted/original daily queries agreed for those probes. This is observed session mixing, not proof of arbitrary corruption or proof that every revision has this cause.

TOP3 currently reads only legacy report/decision/leadership artifacts, not the contextual Candidate Desk. News completeness and heterogeneous score percentiles can change its order independently of the contextual costed model.

## Implementation contract
1. Add an immutable regular-session acquisition overlay. Reuse validated 756-session KIS daily inputs; acquire date-addressed J minute pages bounded to 09:00–15:30 for the latest price session. Independently replay saved public raw pages, enforce date/cursor/duplicate/clock/finite-OHLC constraints, require explicit opening and closing bars. Reconstruct regular-session OHLC; keep KIS published daily volume/turnover with that exact basis named. Do not claim a second independent provider or certified corporate-action history. Preserve original daily rows and a difference receipt.
2. Run the existing formation-only, other-symbol contextual model without threshold tuning on this corrected input in `candidate-regular-v1`. Keep every prior v4 decision/outcome unchanged. New source contract includes the new implementation identity. Declare a fresh 60-decision-session plus 10-session maturation evaluation, after declaration; bootstrap is outside that window. No automatic promotion or real orders.
3. On collection failure preserve success objects, retry only failed symbols, and publish only a complete validated snapshot. Invalid current overlay never falls back silently to old candidates. GET performs no collection, fitting, inference, or writes.
4. The new desk is preferred by the analysis view, price monitor and TOP3. TOP3 receives exact frozen symbols/ranks/plans/source identity; v4 is compatibility only when the new desk is genuinely absent; legacy only when both desks are absent. A hold, cash decision, failed attempt or expired decision must not resurrect legacy picks. AI debate explains evidence and risk but cannot reorder this sealed costed shortlist. Reference weights remain research values; approved exposure is zero.
5. Show source basis and reference entry ceiling in the existing compact mobile-readable TOP3 cards. Expose missing news/filings as missing; do not invent positive catalysts or treat news as a standalone buy signal.

## Validation
Malformed/minute-incomplete/duplicate/future/wrong-session raw evidence rejected; replay matches OHLC; failures resume, no partial pointer; legacy files byte-identical; first decision immutable; revision attribution retained; fresh desk selected with sealed order regardless of legacy/LLM order; source/plan identity bound through API/UI; task smoke and public health verified. Evaluate new forward outcomes only, with fees, tax, slippage, stress costs and cohort bias disclosed. No profit claim from bootstrap or test fixtures.

## Research basis
- KIS official daily and dated-minute examples: https://github.com/koreainvestment/open-trading-api/tree/main/examples_llm/domestic_stock
- KIS market/session guide: https://file.koreainvestment.com/Storage/customer/guide/regards/nxt01.html
- KRX daily API requires an authorized key/service application: https://openapi.krx.co.kr/contents/OPP/USES/service/OPPUSES002_S2.cmd?BO_ID=JvJFzlAENzZlPBDNGAWC
- Qlib separates dataset/model/backtest/evaluation and reports costed outcomes: https://github.com/microsoft/qlib
- RD-Agent research workflow: https://github.com/microsoft/RD-Agent

Apply replayable experiment separation, not a wholesale framework migration or an unsupported claim that public example returns transfer to Korean stocks.

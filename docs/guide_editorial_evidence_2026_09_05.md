# Guide enrichment evidence record — 2026-09-05

## Purpose and publication boundary

Seven existing public guides were substantially enriched, not replaced by bulk-generated posts. Original publication date remains 2026-08-27; substantive revision date is 2026-09-05. Public content distinguishes fictional arithmetic from historical observations. No personal trading history, professional review, current signal validity or performance claim is attributed to the operator.

AI (Codex) supported drafting, source comparison and arithmetic checks. The existing operator profile remains “구독자 1만 명 이상”. This work neither installs Google Analytics nor submits an AdSense review. Site ownership verification is preserved.

## Bounded evidence audit

The unit of analysis is one disclosure, one saved evaluation batch, and one historical VCP snapshot with a matched symbol/date price record. This is not a statistical assessment of the production pipeline.

| Case | Evidence checked | Result / publication limit |
|---|---|---|
| DART | `data/dart_disclosures/202404.jsonl`, company 009420, receipt 20240430000665; official DART original | 2024-04-30 disposal decision, 8,970 shares, R&D employee stock grant, account transfer, planned 2024-05-02–05-31. Decision is not proof of completed disposal or market sale. |
| AI | `data/admin_mirofish/workflows/mcp_20260602065635_ca4fe7b745/outcomes.json` | Generated 2026-09-04T15:41:34+09:00; 5 evaluated, 0 pending. Symbol 000660: entry 2026-04-13, 81 later price rows, horizons 5/10/20. No missing-case claim or profitability claim. |
| AI provenance | `app/services/mirofish/outcome_tracker.py`, CSV loading and forward selection | `date > entry_date` and positive prices are checked, but `update_time` is not retained in evaluation rows. Status/`lookahead_safe` does not establish final closes, source identity, point-in-time universe or full bias control. No code change in this scope. |
| VCP | `data/vcp_kr_latest.json`, matched symbol/date in `data/daily_prices.csv` | Snapshot timestamp string 2026-04-14T15:42:53.183703, 147 candidates; symbol 294630 price update string 2026-04-14 15:13:56. No explicit timezone/source or per-symbol `as_of`. Do not label these as same-time verified closing data. |

The VCP price/ratio values are deliberately omitted from public content because currency and averaging-period provenance are incomplete. Absence of evidence is reported as a verification limitation, not an allegation about the issuer or a claim that current production is broken. The internal DART keyword-classification note and the public HanAll example are separate events; they are not merged into a single narrative.

Internal raw files, local absolute paths and credentials are not included in deployed HTML. No licensed raw price history is republished. Readers can independently inspect the official DART case; AI/VCP cases are explicitly limited internal observations, not independent external audits.

## Primary references

- [HanAll original disclosure](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20240430000665)
- [OpenDART search response fields](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019001)
- [SEC convertible securities](https://www.investor.gov/introduction-investing/investing-basics/glossary/convertible-securities): actual dilution depends on conversion; distinguish potential issuance from completed issuance and rights-issue participation.
- [KRX Data Marketplace](https://data.krx.co.kr/contents/MDC/MAIN/main/index.cmd): official navigation to per-stock prices/investor trading statistics; not asserted to be the source of the local snapshots.
- [Cboe VIX methodology](https://cdn.cboe.com/resources/vix/VIX_Methodology.pdf): 30-day expected S&P 500 volatility, not a domestic direction forecast.
- [FINRA stop-order risks](https://www.finra.org/investors/insights/stop-orders-factors-consider-during-volatile-markets): trigger versus execution price and non-execution risk. US scope is stated.
- [CFTC AI trading advisory](https://www.cftc.gov/LearnAndProtect/AdvisoriesAndArticles/AITradingBots.html): AI does not guarantee future outcomes; not an endorsement or audit of MarketFlow.
- [AdSense content and user experience](https://support.google.com/adsense/answer/10015918?hl=ko)
- [Google people-first content guidance](https://developers.google.com/search/docs/fundamentals/creating-helpful-content?hl=ko)

## Independently checked educational arithmetic

All examples are hypothetical, not market observations or target returns.

- Contractions: (10,000−8,000)/10,000=20%; (9,800−8,820)/9,800=10%; (9,700−9,215)/9,700=5%. Volume: 40,000/100,000=0.4.
- Five-day flow: foreign 17, institution 2, turnover 500 (all KRW 100 million units); combined 19/500=3.8%.
- Breadth: 48/80=60% with 80/100=80% coverage; treating missing as negative incorrectly changes the first denominator to 100.
- Closing example: A 2+3+2+1+1+1+2+0=12; B 3+3+2+1+1+2+0+0=12. Missing evidence is separately labeled, not equated with negative evidence.
- Position size: floor(250,000/700)=357; notional 3,570,000; planned loss 249,900; gap loss at 8,900 is 392,700 or 1.5708R, before costs.
- Ten losses: 1−0.98^10 = 18.2927193% versus 20% for ten fixed losses each 2% of initial capital.
- Expected value: 0.5×2−0.5×1=0.5R; 0.7×0.5−0.3×2=−0.25R, before costs.
- Hypothetical contract: 300/1,000=30%; a three-year contract total is not current-year revenue or profit.

## Release checks

Record actual test/build/review/deployment results in the implementation plan and release handoff. Approval, indexing and revenue are not guaranteed by this work. The seven-guide scope is not a claim that every site-wide advertising, community or consent issue has been resolved.

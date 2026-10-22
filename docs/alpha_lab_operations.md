# AlphaLab: independent stock-detection agents

AlphaLab compares four fixed strategies on the current financial-quality subset
of the market-cap TOP100: momentum, liquidity breakout, mean reversion, and a
ridge model trained on completed costed bracket outcomes. It uses deterministic
agents instead of paid language-model calls. No new external agent API key is
required. The existing Flask/React deployment and current trading approvals stay
separate from this research tournament.

## Read and run

- Member screen: `/dashboard/ai-bain/chart-predict`, **에이전트 매매 제안**.
- Saved status: `GET /api/admin/mirofish/alpha-lab`.
- Fixed background experiment: `POST /api/admin/mirofish/alpha-lab` with `{}`.
- Both require an admin or active AI Brain member and use private/no-store.
- GET never acquires data or fits a model. Client options, symbols, thresholds,
  and input paths cannot be supplied to this route.

```powershell
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe scripts\refresh_alpha_lab_inputs.py --fetch
.\.venv\Scripts\python.exe scripts\run_alpha_lab.py
# Or run both with failure-preserving orchestration:
powershell -NoProfile -File scripts\refresh_alpha_lab.ps1
```

Canonical input registry: `data/alpha_lab/inputs/current.json`, pointing to sealed
snapshots with CSV, acquisition manifest and TOP100/current-quality report.
The collector recovers completed stages, verifies source/hash/cohort agreement,
and publishes one atomic pointer only after success. Holidays without a dated
listing preserve the previous snapshot; it never rewrites the source date.
On a worktree use explicit `--env-file` and `--corp-codes` paths from this project.
Do not copy or log their contents. The first seed is the existing long-history
price acquisition or an explicit `--seed-prices` file. Later runs reuse the
current canonical price snapshot as their seed.

## Evaluation and rejection

The recent chronological window is 504 training, 126 validation and 126 test
sessions, separated by a 10-session embargo. This is **one recent fixed split**,
not an extensive multi-year walk-forward study. Normalization and labels use
training information only. A separate latest serving refit never changes the
frozen evaluation model or champion. Scores are rankings, not probabilities.

Validation selects the champion; the untouched test period only accepts or
rejects that selection. Negative held-out or doubled-cost returns, fewer than
30 completed test outcomes, inactive entry setup, stale or unverified sources
hold allocation at zero. There is no hindsight switch to the best test winner.
Research watchlists may still show three identified stocks for observation.

Execution enters on the next union-calendar session's open, IOC. Missing or
zero-volume quotes do not fill. Opening gap exits can fund opening entries;
intraday/closing exits cannot. Simultaneous intraday stop/target is stop-first.
ATR uses signal-date prices only. The default horizon is 10 sessions, ATR14×2,
loss cap 8%, reward/risk 2. Costs are hypothetical: fee 5, slippage 5 and sell tax
20 basis points; stress doubles all three. Fractional shares are research-only.

Kelly uses **actual net winning and losing returns from the same policy**,
half-Kelly, maximum new allocation 20%, planned account loss 1%, cash buffer
40% and at most three positions. Estimated stop loss is not a guaranteed loss
bound. Allocation caps apply at entry; later price drift is measured, not
silently rebalanced. None of these controls guarantees profit or prevents ruin.

## Forward evidence

`forward.json` freezes the first watchlist each KST decision day, its original
OHLC snapshot, costs, provenance and integrity digests. Entry observations only
start after the actual decision date, even if the input prices are older.
Closed and unfilled outcomes are immutable. Later source revisions are separate
audit evidence; revised closed outcomes are excluded from summary statistics.
These are watchlist outcome observations, not brokerage account P&L. At 730
decision days the journal requires explicit archival rather than silent eviction.
Unsigned/corrupt journals fail closed and preserve the previous public report.
Observation time and consumed source time are separate. A morning rerun with
only yesterday's data must not claim to have consumed today's absent session.
New results seal the calendar cutoff at the last supplied session (or the
existing fixed exit/unfilled-entry session). Revision checks bound legacy
inflated cutoffs by the stored consumed bars/calendar without rewriting the
original result. A later normal session append can continue an open outcome;
a new date inside an already consumed interval, a restored missing entry quote,
or changed OHLCV still records a revision and holds that result.

The 2026-10-07 operational correction addresses source latency only. It changes
no ranking, strategy parameters, cost assumptions, sizing, approvals or reported
returns. Existing revision events and terminal results remain immutable, even
when an old event also contained an overly broad calendar reason. Provider
restatements are real evidence: the public feed has revised prior close/high and
volume values after collection. Capture after 15:30 does not establish a final
KRX close or verified adjustment/vintage. Do not clear revisions or recalculate
historical outcomes to make the success rate improve. Regression validation
uses fixed synthetic delayed-append, past-gap, missing-entry and OHLCV-revision
fixtures, independently of historical strategy performance.

## Clear manual proposals

The member API derives `proposal_summary` and each candidate's `proposal` from
the verified saved result. The conclusion and stock actions appear before
strategy diagnostics. Projection is cheap and never fits models, acquires
sources, rewrites saved evidence or changes the frozen forward journal.

- **매수 제안 (buy):** a conditional manual research proposal. The stock must
  match the validation-selected champion, its qualified calibration, positive
  validation mean and positive held-out/doubled-cost returns, with at least 30
  completed validation/test/stress outcomes. It also requires an active setup,
  current symbol session, valid source timestamps and a finite reference plan.
  Research weight is above zero and at most 20%; weight times planned stop
  fraction is at most 1%. Legacy decisions expire 24 hours after the original scan; certified opportunity decisions use the next-session window described below.
- **진입 대기 (wait):** missing/zero/insufficient evidence, inactive setup,
  stale/missing/future price/source timestamps, invalid plan, expired decision,
  refresh failure, or ongoing/failed analysis. Legacy missing fields do not
  become a buy proposal. Source sessions may be at most seven calendar days old.
- **매매 제외 (avoid):** the matching strategy lost money in the held-out or
  doubled-cost test. This excludes a new buy; it is not advice to sell an
  existing holding. A negative strategy can be excluded even if no champion
  was selected. In-progress/failed status suppresses any retained buy proposal.

`proposal.proposed_weight` is a manual research suggestion and remains separate
from the existing `risk.weight` and CIO approval. Historical vintage,
current-cohort and adjustment limitations remain present; this proposal layer
does not change `analysis_ready`, approve capital or enable broker orders.
Prices are last-closed-price references, never live quotes or promised fills.
Next-open entry requires checking the actual opening price and recalculating
barriers and sizing. Excluded/waiting stocks' reference plans are collapsed
under evidence details, so they do not look like active entry instructions.

The UI suppresses retained buy proposals during a rerun, status/poll errors,
failed analysis and client-side expiry, including while a view remains open.
Decisive wording describes an action recommendation, not certain future profit.

Local replay evidence lives in `data/alpha_lab/runs/`; compact private member
status lives in `data/alpha_lab/status.json`. Generated artifacts remain ignored.

## Operations and sources

Dedicated Windows MiniPC tasks, installed with `scripts/install_alpha_lab_tasks.ps1`:

- `MarketFlow-AlphaLab-Research`:20:30KST,90-minute limit, post-session source acquisition then research. An official closed date skips collection and preserves the last report.
- `MarketFlow-AlphaLab-Prime`:08:55KST,3-minute limit, official KIS session calendar preparation.
- `MarketFlow-AlphaLab-Monitor`:09:00–15:30KST every five minutes,3-minute limit, at most the three current proposal references. Known closed days issue no quote requests.

All use IgnoreNew and saved atomic/locked artifacts. Task installation does not launch a first research cycle. GET remains a cheap read; READY screens re-read saved status every30seconds and RUNNING screens every4seconds.
Flask production remains127.0.0.1:5003; development remains5001. Chart index scheduling stays independent.

### Daily-feed settling window (2026-10-08 source audit)

The former18:45 collection accepted a daily feed that was still changing. A bounded3-symbol probe at19:26KST found actual same-day close/volume changes for000660,007660 and196170 against the immutable18:45 snapshot; the previous day's rows were stable in that probe. This is a temporal input defect, not a capture-timestamp-only revision. The official [NXT trading system](https://www.nextrade.co.kr/menu/transactionSys.do) states that its aftermarket ends20:00. That timing is consistent with the observed updates; the NAVER feed's exact venue/adjustment semantics remain unverified.

Acquisition now waits until20:30KST, a30-minute buffer after that session. Explicit earlier same-day requests are rejected before collection/publication, and actual per-symbol/CSV capture times must meet the same cutoff. A versioned acquisition policy prevents reuse of old provisional snapshots as compliant inputs; old sealed files, first decisions and terminal outcomes remain preserved. The weekday helper is still not an exchange holiday certificate; the scheduled wrapper retains its official KIS calendar check. A time buffer cannot guarantee provider finality: later numeric corrections still create source revisions and remain excluded from performance. No parameters or inspected historical windows were retuned, and no realized profit is inferred.

The separate admin-symbol acquisition path uses the same buffer for its official-calendar selection and raw-price cache. It records the price capture separately from later financial captures, which cannot make an early price appear settled. Next-session entry expiry remains15:30KST. Legacy saved reports remain readable for audit; deployment does not rerun their first decisions. The next scheduled compliant collection publishes a separate snapshot atomically.

## Certified session windows and price monitoring

New optional `next-session-proposal-v1` windows apply only to the separate quality-setup BUY candidates. The first source identity and origin are frozen under `data/alpha_lab/monitor/`. Manual rescans against the same fingerprint/opportunity audit/candidate plan do not renew the window. The first certified session/deadline is also sealed; later calendar corrections hold the proposal instead of moving its entry day. Once KIS calendar dates fully establish the first trading session strictly after that origin day, the window ends at that session15:30KST. Missing/failed calendar confirmation produces a null window and a WAIT view. Legacy tournament candidates retain their original24-hour rule.

The calendar source is official `CTCA0903R` (`tr_day_yn` and `opnd_yn`), successfully fetched once per date and persisted. Failed calendar observations retry no earlier than15minutes, at most3attempts per KSTday. There is no fallback to a weekday-only trading-day claim. Calendar ranges with missing dates, invalid flags, future captures or corrupted artifacts hold confirmation.

Quote evidence uses KRX market code J. The current minute close and its business-date/time come from `FHKST03010200`; the **daily opening price** comes from `FHKST01010100`. A minute bar opening is never interpreted as the session opening. Provider inputs must be at most120seconds old at acquisition; saved quotes lose active guidance at420seconds. HTTP/API errors, future/previous-session quotes, changed identities, incomplete scans and failed attempts remove live guidance.

An observed opening-reference decision is fixed once for that source/session. Open above the close×1.02 ceiling or below the original reference stop skips entry for that session. Accepted reference barriers use the frozen ATR: distance=min(2ATR, opening×8%), stop=opening−distance and target=opening+2distance, retaining the existing quarter-Kelly research cap. Later quotes may show reference stop/target or monitor-only states. These are observations/reference plans, never actual brokerage fills or tracked user positions; approved exposure and live orders remain zero/false.

The separate current-candidate forward panel uses the existing sealed daily next-open paper journal. Closed unrevised outcomes form the win-rate/mean-return denominator; pending, open, unfilled and revised events are shown separately. The manual2% entry guard and live monitor are **not applied to that historical/forward simulation**. No account P&L is inferred.

Official provider references: [KIS holiday API](https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_stock/chk_holiday/chk_holiday.py), [KIS minute-price API](https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_stock/inquire_time_itemchartprice/inquire_time_itemchartprice.py).


Independent implementations were informed by:

- [Microsoft Qlib](https://github.com/microsoft/qlib), MIT, inspected revision
  `be725493eb1a6bbb42bf11b37aa7669f59610ff1` — causal OHLCV factors and model evaluation.
- [Microsoft RD-Agent](https://github.com/microsoft/RD-Agent), inspected revision
  `484776c211e4fbbeef03e0ec00d6bbee7362a4f4` — repeatable hypothesis/evaluation records.
- [FreqAI](https://www.freqtrade.io/en/stable/freqai-running/) and
  [lookahead analysis](https://www.freqtrade.io/en/stable/lookahead-analysis/) —
  frozen-window evaluation and temporal perturbation tests. GPL implementation
  source was not copied.
- [Thorp's Kelly paper](https://www.edwardothorp.com/wp-content/uploads/2016/11/TheKellyCriterionAndTheStockMarket.pdf).

No full framework was vendored; a benchmark or open-source project is not proof
of profitable Korean-stock operation. Current-cohort survivorship, historical
financial/price vintages, corporate actions, gaps, correlated outcomes, market
regimes and real fill quality remain explicit limitations.

## Evidence/account contract and portrait stock desk (2026-10-08)

Saved AlphaLab GET responses now include an additive `agent_desk`, bound to the existing maximum-three `opportunity_engine` identities. Twelve deterministic roles audit saved observations; they do not imply twelve LLM calls, a completed agent consensus or new source acquisition. The current integration supplies no certified extra collector. Absent foreign flow, FX, disclosure or other source records therefore remain missing. Historical win rates remain observations; Bull/Base/Bear forecasts are null and strategy promotion remains M0. Existing frozen decisions, ranking, forward outcomes and CIO approval are unchanged.

Trusted server evidence records require exact symbol/opportunity identity, role, claim, explicit S/A/B/C grade, original lineage/upstream origins and source/available/fetched/expiry timestamps. Each direction/risk core claim requires two independent S/A authoritative market/disclosure/official-news lineages. Generic news, social/search interest and B/C records cannot authorize a core claim. Connected origins count once, including copied chains; future availability cannot enter the original decision. The additive validity window is tightened by source age, source expiry and the existing quote/entry windows.

`POST /api/admin/mirofish/alpha-lab/account-plan` uses the existing admin-or-active-AI-Brain gate and private/no-store headers. It accepts only `{account, opportunity_ids}` and derives prices from current saved server plans. Explicit equity, available cash, daily/weekly PnL and confirmed complete holdings are required. Duplicate JSON keys, extra fields, oversized requests and nonfinite/boolean monetary inputs are rejected. Account values are request-only: no browser storage, research journal writes or account logs. Stale displayed identities return409 and require a fresh result.

Reference sizing floors whole shares at the maximum entry reference, then applies shared cash, current holdings, confirmed saved theme, existing reference weight and quarter Kelly. Limits are planned trade risk0.5%, daily new-entry stop−1.5%, weekly stop−4%, symbol max5%, theme30%, minimum cash40%, maximum3 concurrent stocks. Both usable FX and foreign-flow evidence absent => globalHALT. Unknown trusted theme, expired evidence/quote or failed audit withholds quantities. Gap/fill losses can exceed the planned loss. `ready` means deterministic reference arithmetic is ready, not a promoted strategy or CIO approval; orders always remain disabled.

Both the AI Brain stock desk and chart-analogue page share the portrait layout: stock/action, prominent entry/stop/target, next action and invalidation first; full evidence, role and account details expand below. Source expiry, refresh/error, account edits and logout invalidate dependent calculations. Additional watchlist rows become vertical on phones and retain table semantics on desktop. The optional contract is backward compatible with older responses; absence cannot expose account quantities.

`empirical_cvar` accepts only actual completed costed return arrays as an optional diagnostic. It does not change ranking or infer tail losses from a win rate. M1 replay, predeclared independent OOS, probability calibration, M2 paper duration and M3 human approval remain promotion requirements, not claims established by this integration.

## Decision evidence receipts and market guard (2026-10-09)

The selected K-EQUITY v2 ideas are independently implemented inside AlphaLab;
the downloaded package, probability weights and its mutable policy runtime are
not transplanted. TOP3 ranking, existing Kelly math, frozen research and forward
outcomes remain intact. The new optional `agent_desk.contract` carries a full
SHA-256 policy hash, exact decision identity, receipt ID/status and one ordered
market check per displayed candidate. Legacy desks remain displayable, but a
missing contract never permits account quantities.

Only an authenticated administrator may publish a receipt through
`POST /api/admin/mirofish/alpha-lab/evidence`. The exact JSON envelope contains
`schema_version: 1`, `decision_id`, `input_fingerprint`, `source_audit_hash`,
`policy_hash`, `evidence` and `market_states`; both maps are keyed by current
six-digit candidate symbols. Obtain the current identities and policy hash from
the saved status GET. The route rejects query overrides, duplicate JSON keys,
nonfinite numbers, extra fields and bodies above256KiB. Rejections are bounded
409/503 responses and never echo source payloads. Members can read the compact
audit and request reference arithmetic, but cannot import evidence.

Evidence retains the existing explicit source metadata, lineage and original
availability/capture timestamps. Each record additionally requires a stable
`evidence_id`, `direction` (`up`, `down`, `neutral`, `unknown`), finite `figure`
or null, `unit`, `conflict_group` and explicit `missing_reason`. Unknown/null
claims can document a gap but cannot certify a core claim. Opposite authoritative
directions for the same server-derived claim hold its audit; caller-supplied
group names cannot hide a contradiction. Duplicate IDs with different contents
are rejected by the auditor, while copied upstream lineages still count once.
Legacy unstructured evidence is explicitly missing directional semantics. A
reference account plan additionally requires usable flow and disclosure roles.
Source claims must have been available and fetched by the original decision
cutoff; later market observations do not repair that historical evidence.

Market state is a separate current observation: exact symbol/opportunity/decision,
explicit S/A source grade, source/available/fetched timestamps, session,
`vi_active`, `sidecar_active`, `circuit_active`, and each corresponding
`*_released_at`. False flags require explicit null only if never observed active,
otherwise a real release timestamp. Current facts expire420seconds after source
time, including the exact boundary. VI holds new reference quantities until
300seconds after release; sidecar/circuit cooldowns are900seconds. The source
must explicitly report continuous trading and the KST clock must be09:00–15:05
on a weekday; that clock window does not replace the existing official next-session
calendar. Account validity is the earliest of market, quote, evidence and entry
deadlines. Missing event feeds hold quantities without removing TOP3 stock cards.

Receipts live under `data/alpha_lab/desk-evidence/runs/{snapshot_id}.json` and an
atomic decision-specific `current/{decision_id}.json`. The body hash includes an
owned policy snapshot; identical imports are idempotent and do not refresh clocks.
Previous receipts are never overwritten. Once a market symbol is recorded, later
imports must retain it and advance its source time before changing its facts;
they cannot erase activation/release history to replay an older safe state.
Corrupt receipts or changed policies hold the decision rather than silently
repairing it. GET only reads these files; it does not collect sources or write.

This release supplies the checked ingestion path, not a newly certified upstream
feed. Existing KIS flow, cached FX and DART adapters lack some required lineage,
availability or event-release fields. Collectors must provide actual verified
facts before publishing; do not synthesize independence, grade, timestamps or
inactive-event flags. Raw evidence and collector details stay server-side;
the portrait stock desk shows saved/missing/held receipt status, policy hash and
per-stock market reasons. M0, unavailable forecasts and disabled orders remain.

## Private detection-event delivery (2026-10-09)

The operator explicitly requested immediate delivery and subsequent new detection
events through `@bitman75_bot`. This authorizes this narrow private automation;
the older one-shot scanner confirmation flow and other notification flags are
unchanged. OpenClaw remains independent and read-only.

`ALPHA_LAB_TELEGRAM_ENABLED=true` opts in. Both scheduled research and the manual
scan hook send only after the research report and exact first-issued decision
are saved. The event key is the frozen decision identity, recipient fingerprint
and fixed message digest. New source inputs can produce a new decision even for
the same symbols. Re-running that decision, member GETs, page refreshes, evidence
receipt updates and five-minute price ticks do not send repeated stock messages.

The sender verifies `getMe` equals `bitman75_bot` and `getChat` is the configured
private operator chat before sending one escaped TOP3 message. It uses the
project's personal bot token by default; the optional token-key alias is limited
to the project's two existing Telegram token keys. It never targets a channel.
The message uses saved names/codes, reference entry/stop/target, reference weights
and the held status with the actual source session. It does not substitute monitored
prices, advertise calibrated probabilities or claim execution approval.

Private receipts under `data/alpha_lab/notifications/` are separate from research
and scanner ledgers. A locked pending claim is persisted before transport;
verified delivery, pending or uncertain acceptance prevent replay of the exact
event. Timeout, malformed success or ambiguous server failure never cause an
automatic duplicate. Authentication/blocked-recipient errors require operator
action. Rate-limit recovery is bounded and respects the returned delay. Public
CLI output contains only sanitized status/decision/digest/count/session fields;
do not print, copy or stage private receipts, tokens, recipients or raw messages.

`scripts/run_alpha_lab_telegram.py` defaults to a saved preview. `--send` performs
one explicitly authorized send; `--automatic` honors the opt-in. The independent
`scripts/install_alpha_lab_telegram_task.ps1` installs only
`MarketFlow-AlphaLab-Telegram-Events`, a five-minute recovery check for the latest
decision. It does not rerun research or modify the existing research/prime/monitor
tasks. Research success survives transport failures; missing/invalid saved
decisions cannot send. The notification task and CLI load only this project's
environment, without exposing its contents.

## Price detection and public-news chronology (2026-10-09)

Optional saved `catalyst_context` binds to the current decision/input/source-audit
hashes and the earliest hash-valid issued decision per selected stock. Publication,
actual first capture and first decision clocks stay distinct. General media are
B supporting context; later reports never become an original selection reason,
probability, Kelly input or CIO approval.

The public YNA industry RSS supplements the existing nine feeds. Exact issuer
matching handles Latin case, mixed-script spacing and complete Korean particles;
group/chairman-only stories are not attributed to an issuer by assumption.
The existing source allowlist and per-source kill switches remain effective.
The compact stock chronology requires an exact issuer name/code in the title;
body-only mentions remain in the ledger but cannot present another issuer's
positive report as this stock's own catalyst.

Bounded reads retain the latest256 and pre-first-decision256 ledger rows per
stock. The eight displayed reports reserve four slots per capture period, then
fill unused slots from recent remaining reports. Original article capture clocks
stay unchanged; follow-up volume does not displace all pre-selection evidence.

Successful news sweeps and post-publication research refresh a separate immutable
sidecar. Failed updates preserve prior pointers without undoing completed research
or acquisition. GET only reads checked JSON; it performs no SQLite initialization,
RSS requests, fitting, writes or Telegram delivery. Detection receipts stay intact.

`python scripts/run_alpha_lab_catalysts.py` explicitly refreshes the context using
the existing read-only news ledger. Its first run freezes the protocol start for
`price_setup_leads_catalyst_72h_v1`. Subsequent new research decisions enroll selected
stocks and the exact same quality-universe controls. Historical decisions remain
historical; cohorts and original hashes cannot be retuned after observation. This
release registers and preserves observations; matured comparisons and rejection
of chance are not claimed. Missing RSS coverage is not evidence of no event.

Audit: `docs/sk_hynix_detection_audit_2026_10_09.md`. Provisional-price source
revisions remain terminal holds, excluded from completed performance.

## Autonomous prospective improvement (2026-10-14)

The shared portrait desk now displays **자동 개선 연구**. The existing 20:30 KST
research job refreshes a separate evolution journal only after the original
research report and issued decision have been published. Optional trial failure
cannot undo a completed research stage, ranking, Kelly, CIO or Telegram receipt.
GET reads saved bounded JSON only; no model fitting or source requests occur.

Four policies compare the same dated financial-quality universe: current TOP3,
next-open entry restricted to the frozen reference band, closed-bar recovery
confirmation, and positive final correlation-adjusted ranking with cash for
unused slots. All use next-session IOC, ATR14×2, 8% stop cap, 2R target and
10-session horizon. Fees/slippage/sell tax are 5/5/20 bps; stress doubles costs
without choosing different trades. These are paper watchlist returns, not an
account return. Missing or revised quotes do not become profitable outcomes.

The protocol freezes at initialization, then enrolls only future same-session
decisions acquired after 20:30. Input `capture_audit` preserves each quality
symbol's actual first/last accepted-row acquisition clock without changing the
original source fingerprint. The first decision per session, full discovery
pool and 64-bar causal prefixes are immutable. Later source changes audit the
original result and exclude revised evidence; later prices beyond the fixed
10-session horizon cannot rewrite an earlier outcome.

The finite trial has 106 decision sessions: 36 nominate one challenger, 10 allow
its labels to mature, and 60 independently confirm or reject that fixed nominee.
Up to 10 additional sessions mature the final labels. No profitable-result-based
extensions or substitution of a better confirmation winner are allowed. Nomination
receipts bind to the protocol ID and ordered first-36 cohort IDs. Qualification
requires the whole declared window resolved/unrevised, at least 30 entered
confirmation outcomes for nominee and control, six complete 10-session blocks,
positive normal/stress means and paired advantages, nonworse tail loss, and
positive block advantage minus 3.5 standard errors. This fixed research gate is
not a calibrated probability or assurance of profitability.
Separate decision blocks can share market and holding-period effects; the
3.5-error margin is a fixed research metric rather than a confidence interval.

Memory lives only under `data/alpha_lab/evolution/`: signed protocol/cohorts,
recoverable observations, bound nomination, review receipts and compact status.
The latest attempt has separate recoverable metadata. A failed refresh visibly
holds saved status, while successful earlier stages and first decisions remain.
Known historical-vintage, adjustment, current-cohort and paper-fill limitations
stay explicit. Every result is `research_only=true`, `live_orders=false`,
`approved_exposure=0`; an accepted research candidate is **awaiting human review**.

Saved-source-only initialization/recovery (no collection, Telegram or orders):

```powershell
.\.venv\Scripts\python.exe scripts\run_alpha_lab_evolution.py
```

Running this command for an old saved report initializes a waiting trial with
zero prospective cohorts. It never backfills old losing/winning decisions.
The next successful scheduled research supplies its first future comparison.
No duplicate Windows task, paid dependency or execution key is installed.

## 검출 2.0 운영 계약 (2026-10-19)

회원 공통 검출은 `quality-setup-opportunity-v2`와 `profit-opportunity-v2`로
구분한다. 과거 공통 전략의 `forward.json`, 기존 종목별 BUY 관측,
106결정세션 `evolution/` 실험은 원본 대조군으로 유지한다. 서로 다른 선정
파이프라인의 손익을 합치거나 기존 손실을 새 정책 성과로 옮기지 않는다.
v2 화면에서 이전 공통 전략 후보는 대기·참고 비중 0으로 표시하며,
저장된 최초 계획이나 종료 결과 자체를 수정하지 않는다. 관리자 단일 종목
검색은 별도 v1 진단 경로이므로 v2 공통 검출 통과를 뜻하지 않는다.

v2는 현재와 모든 과거 신호 시점에 같은 인과적 조건을 적용한다. 연속
61세션 가격, 현재 양수 거래량, 종가>SMA60, SMA20>SMA60, 같은 날짜의 재무
적격 코호트 대비 양수 20세션 상대수익, 20세션 평균 거래대금 10억원 이상을
요구한다. 코호트 중앙값은 공식 시장지수가 아니다. 기존 전략 조건도
충족해야 하며 평균회귀는 종가가 전일 고가와 당일 시가를 모두 넘는 회복을
추가 확인한다. 과거와 현재에 서로 다른 필터를 붙이지 않는다.

1,008세션 형성·252세션 확인의 기존 완료 거래 검사를 유지하고, 최근
126세션 안에 진입한 완료 거래 5건 이상에서 일반·비용 2배 평균과 복리
순수익이 모두 양수여야 한다. 순위 점수는 형성 구간 비용 2배 평균에서
표준오차의 1.96배를 차감한 값과 최근 126세션 비용 2배 평균 중 작은 값이다.
기존 상관 차감 후에도 양수인 종목만 최대 세 칸을 채운다. 이는 순위용
지표이며 신뢰구간이나 미래 승률이 아니다. 미충족 칸은 현금으로 남기며,
새 시세·뉴스·관리자 진단이 경제성 탈락 종목을 다시 BUY로 승격하지 않는다.

새 전향 비교는 `data/alpha_lab/detection-v2/`에 따로 저장한다. 최초 실행의
실제 KST 선언일 뒤 날짜부터 당일 입력과 종목별 20:30 이후 실제 취득 시각이
일치하는 새 결정만 최대 60세션 등록한다. 이후 10세션의 종료 관측을 위한
여유를 두며, 승패를 보고 등록 기간을 늘리거나 조기 승격하지 않는다.
`window_complete`는 60개 결정 등록 완료를 뜻하며 수익성·종료 관측 완료나
실투자 승인 상태가 아니다. 기존 106세션 실험에는 계속 원래 v1 보고서와
전체 후보 풀을 전달한다.

cohort는 양쪽 원래 후보·결정 시각·출처·15개 일봉 스냅샷과 정확한 board
식별자를 먼저 봉인한다. 한쪽 저널 쓰기가 실패하면 완료 단계는 보존하고
누락된 원래 결정만 복구한다. 날짜가 지나거나 60번째 등록 직후 실패해도
같은 원칙을 적용한다. 복구 후 관측은 현재 전체 가격 입력으로만 전진하며,
과거 스냅샷으로 기존 진행·종료 결과를 되감지 않는다. 동일 종목 재검출은
새 고정 결정에 귀속한다. 정책·계산 의존 코드의 정규화 해시가 바뀌면 기존
선언으로 계속 수집하지 않고 별도 버전을 선언해야 한다.

GET은 저장 상태 투영만 수행한다. 쿼터 켈리 참고 한도 5%, 계획 손실 한도
1%, CIO 승인 노출 0 및 주문 비활성을 유지한다. 일봉 20:30 취득 정책은
가격 시장 구분·수정주가·당시 자료 및 당시 종목 목록 검증을 대신하지 않는다.
현재 코호트 편향과 출처 수정은 계속 표시하고 수정 결과는 원본을 보존한 채
성과 집계에서 제외한다.

고정 후향 비교와 적용 범위는 `docs/alpha_lab_detection_audit_2026_10_19.md`에
기록한다. 해당 비교는 v1 연속 모의 계좌 +2.9493%, v2 무거래 0%였고 현재
v2 통과 종목도 0개였다. 더 나은 수익 검출이 입증된 결과가 아니므로,
이 결과를 본 뒤 조건을 완화하거나 같은 구간에 다시 최적화하지 않는다.
배포 완료 여부는 감사 문서의 최종 검증 기록에서 별도로 확인한다.

## KIS 문맥 후보 데스크 (2026-10-22)

`candidate-desk/`는 기존 v1/v2 원본과 독립된 신규 정책이다. API/연구 CLI는
`candidate_service`를 통해 기존 보고서를 유지하면서 선택적 `candidate_desk`를
추가한다. 회원 AI Brain 권한은 그대로이며 GET은 저장 자료만 읽는다.

입력은 현재 재무 적격 대형주 코호트를 대상으로 KIS `FHKST03010100`, 시장 J,
일봉 D, 수정주가 요청 0의 최대 756세션을 수집한다. NAVER 가격을 혼합하지
않는다. 성공 종목별 해시 객체를 먼저 보존하고 실패 종목만 재시도한다.
출처 계약·실제 취득 시각·기업행사/당시 자료 미검증 상태를 함께 저장한다.

고정 v3 공동 검증의 최근 결과가 음수였으므로 그 검증 문턱은 유지한다.
별도 `contextual-candidates-v4`는 형성 구간에서 다른 종목의 유사 조건
60건을 찾아 시간 블록별 순손익을 추정한다. 최소 30건·5종목·5블록,
일반/비용 2배의 관측 평균과 축소 추정치가 모두 양수인 현재 조건만 최대
3개를 제안한다. 이는 실험적 조건부 추정이며 v3 음수 대조 결과가 v4의
독립 검증 성과가 된 것은 아니다. 상세 선언은 context-learning 설계 문서에 둔다.

참고 비중은 쿼터 켈리와 종목별 1% 상한을 적용한다. CIO 승인 노출 0,
실계좌 주문 없음은 그대로다. 다음 공식 거래일은 실제 생성일 이후로
고정하며 참고 진입·손절·목표·2% 추격 상한은 해당 결정에 귀속한다.
실제 시가가 상한을 넘거나 손절선 이하이면 진입하지 않는다. 아래쪽 시가가
손절선 위인 경우에는 실제 시가로 ATR 계획을 다시 계산한다.

60개의 서로 다른 향후 결정일과 추가 10세션 성숙을 별도로 관측한다.
같은 날의 재실행은 관측 수를 늘리지 않는다. 첫 결과·종료 손익은 보존하며
신호/소비 시세 수정·삭제는 원본을 유지한 채 검증 제외한다. 실패 갱신,
오래된 출처와 만료된 진입 계획은 활성 후보로 노출하지 않는다.

기존 연구·시세 감시·Telegram 예약을 재사용한다. 감시는 새 결정의 공식
진입일과 장중에만 최대 세 종목을 조회하고 저장된 신선한 시세만 투영한다.
Telegram은 별도 중복 방지 장부를 사용하며 기존 수신자/동의 설정을 유지한다.
과거 이벤트를 재전송하지 않는다. 완료된 기존 연구를 반복하지 않고 신규
단계만 복구하려면 `python scripts/run_alpha_lab.py --desk-only`를 사용한다.

### 배포 식별과 Windows 복구 검증

`/api/health`의 버전은 명시한 프로젝트의 Git HEAD/ref 메타데이터를 제한된
크기로 읽어 표시한다. 요청마다 Git 명령을 실행하거나 서비스 PATH·전역 Git
신뢰 설정에 의존하지 않는다. 이 값은 체크아웃 식별자이므로 실제 실행본
확인은 정확한 배포 커밋, 5003 프로세스 교체, 저장 분석 해시와 인증된 화면을
함께 대조한다. 기존 5001 프로듀서는 별도로 보존한다.

Windows 5.1 헬스 프로브는 저장소의 `scripts/health_probe_native.cs`를 사용한다.
새 프로세스를 일시 중지 상태로 만들고 전용 Windows Job에 넣은 뒤 실행한다.
부모가 먼저 종료해도 그 프로브의 하위 프로세스까지 정리한다. 외부 `taskkill`
트리 정리의 지연에 의존하지 않으며 다른 서버 프로세스를 이 Job에 넣지 않는다.
출력 크기와 대기 한도를 유지하고, 준비·정리 실패는 정상 응답으로 취급하지 않는다.
시스템 권한·PATH·인증 설정을 바꾸거나 추가 도구를 내려받지 않는다.

Windows 회귀 검사는 앱·키·운영 엔드포인트 없이 PowerShell 5.1에서
소유한 시험 프로세스만 검증한다. 실행 명령은
`python -m pytest --noconftest tests/test_watchdog_health_probe.py -q`다.
상위 프로세스 종료 뒤 남는 하위 프로세스, 시간 초과, 관계없는 프로세스의
생존과 잘못된 출력도 검사한다. 운영 검증은 이 검사와 별도로 예약 작업의
정상 결과, 원래 5001 PID 보존, 로컬·공개 헬스 응답을 확인한다.

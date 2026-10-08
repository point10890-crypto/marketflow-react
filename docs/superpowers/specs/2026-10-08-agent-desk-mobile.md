# Evidence-aware agent desk and mobile portrait

The user approved connecting the reviewed v1 architecture to the existing AlphaLab stock desk, with mobile portrait as the primary reading surface. Existing TOP3 research recommendations remain visible; account-approved plans are a separate, clearly identified contract.

## Boundaries

- React/Vite and Flask, no new dependency, paid provider, live brokerage order, payment or messaging.
- Existing frozen decisions, ranking policy, outcomes, calendar/quote expiry and CIO approval remain intact. Existing 5% symbol reference cap and quarter Kelly must not be loosened by the new 10% v1 ceiling.
- Saved GET projections remain bounded and read-only, without fitting, scanning, external calls or writes.
- Unknown evidence, probabilities, accounts and outcomes stay unknown. Historical win rates are observations, not calibrated forecasts. No refit against inspected test intervals.
- Missing both usable foreign flow and FX stops new account plans. Account limits and supplied holdings must be explicit, with quantities absent until the account and evidence checks pass.
- Account inputs are request-only; never persist them to browser storage, files, application logs or research journals.

## Interfaces

`decision_contract.build_agent_desk(status, *, now=None, evidence=None) -> dict` consumes the existing projected AlphaLab status. `evidence` is a trusted server-supplied mapping from symbol to evidence records, never accepted from the account-plan client. The current integration has no certified extra source collection and displays missing roles honestly.

`status.agent_desk` is optional for old servers and has this structure:

```ts
interface AgentDesk {
  schema_version: 1;
  policy_version: 'evidence-account-v1';
  generated_at: string;
  order_allowed: false;
  roles: Array<{id: string; title: string; status: 'passed' | 'held' | 'unavailable'; detail: string}>;
  candidates: Array<{
    opportunity_id: string; symbol: string; name: string;
    state: 'No-trade' | 'Watch' | 'Conditional plan' | 'Exit review';
    audit: {status: 'passed' | 'held'; reasons: string[]; independent_sources: number};
    probability: {kind: 'unavailable'; bull: null; base: null; bear: null; reason: string};
    invalidation: {price_below: number | null; price_above: number | null; valid_until: string | null; detail: string};
    missing: string[];
  }>;
  promotion: {stage: 'M0'; reasons: string[]};
}
```

There are exactly twelve role IDs: regime, fx_liquidity, flow, disclosure, sector, event, micro, sentiment, auditor, leader, risk_guard, review. They are deterministic task contracts, not twelve model calls. Source audit deduplicates upstream lineage, rejects unavailable/future/stale data, prevents social-only direction and does not treat distinct websites copying one source as independent. Required core claims require two independent non-social lineages. Fixed heuristics may not claim calibrated probabilities or independent validation. Identity must bind to existing opportunities.

`account_plan.build_account_plan(status, account, *, now=None) -> dict` consumes the current server status with the agent desk, and an account object:

```ts
interface AccountInput {
  equity: number;
  available_cash: number;
  daily_pnl: number;
  weekly_pnl: number;
  positions_confirmed: true;
  positions: Array<{symbol: string; theme: string; market_value: number}>;
}
interface AccountPlan {
  schema_version: 1; policy_version: 'evidence-account-v1';
  status: 'ready' | 'held' | 'halt'; reasons: string[];
  generated_at: string; valid_until: string | null;
  order_allowed: false;
  limits: {trade_risk: number; daily_stop: number; weekly_stop: number; symbol_cap: number; theme_cap: number; cash_floor: number};
  plans: Array<{opportunity_id: string; symbol: string; name: string;
    status: 'ready' | 'held' | 'halt'; reasons: string[];
    quantity: number | null; weight: number; budget: number; planned_loss: number;
    entry_price: number | null; stop_price: number | null; target_price: number | null}>;
}
```

New endpoint `POST /api/admin/mirofish/alpha-lab/account-plan` accepts exactly `{account, opportunity_ids}` where IDs must equal the currently displayed server candidates. JSON/body/query limits and existing admin-or-AI-Brain auth apply. It reads saved state and never scans or writes an account. On malformed input return 400, unavailable saved state 503, otherwise a structured held/halt/ready result. Each quantity is floored from the maximum entry reference, stop distance, available cash and portfolio caps. Per-trade planned risk <=0.5% equity; daily PnL <=-1.5% or weekly <=-4% stops all new positions. Symbol <=min(existing reference,5%,v1 10%); theme <=30%; cash floor >=40%; no more than three concurrent stocks. Gap losses can exceed the planned loss and are stated plainly. Unknown theme prevents a theme-approved plan.

`AccountPlan.status='ready'` means the deterministic account-limit calculation is ready, not a calibrated strategy, promoted model or CIO-approved trade. M0 and unavailable scenario forecasts alone do not prevent this calculation once current source audits, entry timing and account limits pass. Its quantities are research references; approval remains held and orders disabled.

## Mobile surface

- Both `/dashboard/ai-bain` and `/dashboard/ai-bain/chart-predict` use the shared panel.
- At 360/390/430px, one-column cards show rank/name/action first, then entry/stop/target, next action and invalidation. Main body ~16px, stock names >=20px, tabular numeric alignment, 44px interactive targets.
- Source audits, twelve-role status, history and calculation detail are disclosures; essential plan conditions are never hidden.
- Additional watchlist becomes vertical mobile items and a desktop table. No document horizontal overflow.
- Optional account form has visible labels, explicit zero-holdings confirmation or editable holdings, no default account facts. Clear dependent plans on input edit, source refresh/error, changed identity, expired evidence or logout. Required data cannot be implicitly zeroed.
- Preserve existing admin search, navigation, polling generation/expiry safeguards and dark brand. No decorative hero or animation dependency.

## Acceptance

Focused regression tests cover lineage duplication, social-only claims, future availability, missing flow+FX, fabricated probability rejection, missing account values, stale IDs, hard-stop equality, portfolio/theme/cash limits, NaN/bools, expired quote/plan, stale asynchronous responses and mobile disclosures. Existing research advice and frozen journals remain unchanged. Full frontend lint/Vitest/build and Python CI must pass before release. Verify actual saved API, role/price correspondence and mobile document width/touch targets on the deployed app.

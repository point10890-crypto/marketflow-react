# AlphaCore backend boundary

This package is an additive AlphaClaw v1.1 backend. It does not import or call
the operational Claw/KIS paths and it cannot place a real order.

## Runtime modes

- `ALPHACLAW_MODE=shadow` (default): pure risk evaluation and read-only status;
  paper-capital event writes and fill generation are blocked.
- `ALPHACLAW_MODE=paper`: enables only the isolated internal paper ledger and
  deterministic paper fill simulator.
- Every other value fails configuration validation. There is no live mode.

The DB path is `ALPHA_CORE_DB_PATH` when set, otherwise
`data/alphaclaw/paper.db`. `PaperLedger(...)` construction never creates or
changes a file.

## Safe bootstrap and status

From the repository root in PowerShell:

```powershell
$env:ALPHACLAW_MODE = 'shadow'
.\.venv\Scripts\python.exe -m app.services.alpha_core bootstrap
.\.venv\Scripts\python.exe -m app.services.alpha_core status
```

`bootstrap` creates schema only. It does not initialize capital, propose an
intent, call a data source, or create a fill. `status` opens an existing DB with
SQLite `mode=ro` and `query_only`; when no DB exists it reports
`available=false` without creating one.

Paper capital initialization is intentionally an explicit Python API call after
mode and policy review:

```python
ledger = PaperLedger(mode="paper")
ledger.initialize()
ledger.initialize_capital(
    10_000_000,
    effective_at="2026-08-24T09:00:00+09:00",
    idempotency_key="capital-policy-v1",
)
```

This is internal simulated KRW, not a brokerage balance.

## GET/read integration contract

Create route readers as `PaperLedger(path, read_only=True)`. Public reads are:

- `status()`
- `list_events(limit=100, after_id=None, aggregate_id=None, event_type=None)`
- `list_intents(limit=100, status=None)`
- `list_risk_decisions(limit=100, decision=None, intent_id=None)`
- `portfolio()`
- `verify_integrity()`

JSON payload columns are decoded before return. Portfolio values include
`nav_krw`, `drawdown_pct`, and `snapshot_hash`; unavailable measures remain
`None` rather than being converted to zero.

## Write sequence

The bounded paper sequence is:

1. `propose_intent`
2. pure `RiskKernel.evaluate(..., mode="paper")`
3. `record_risk_decision` (reservation and approval in one transaction)
4. `submit_paper` (consumes the exact hash-bound approval once)
5. pure `simulate_fill(..., mode="paper")`
6. `record_fill`
7. pure `reconcile_projection`
8. `record_reconciliation`

All state changes append immutable hash-chained events. Projection and status
queries replay those events; they do not update positions or cash rows.

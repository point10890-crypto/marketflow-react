"""Side-effect-free replay reconciliation for the paper ledger."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from .contracts import ReconciliationResult, canonical_hash, normalize_timestamp
from .paper_ledger import PaperLedger


def reconcile_projection(
    ledger: PaperLedger,
    *,
    reconciled_at: str | datetime,
    expected_projection: Mapping[str, Any] | None = None,
    intent_id: str | None = None,
) -> ReconciliationResult:
    """Compare replay with an optional independently stored projection.

    The function never records its result.  Call ``record_reconciliation``
    explicitly after reviewing the returned contract.
    """

    at = normalize_timestamp(reconciled_at)
    replay = ledger.portfolio()
    replay_hash = str(replay["snapshot_hash"])
    expected_material = (
        {key: value for key, value in expected_projection.items() if key != "snapshot_hash"}
        if expected_projection is not None
        else {key: value for key, value in replay.items() if key != "snapshot_hash"}
    )
    expected_hash = canonical_hash(expected_material)
    discrepancies: list[str] = []
    integrity = ledger.verify_integrity()
    if integrity.get("ok") is not True:
        discrepancies.extend(str(item) for item in integrity.get("errors") or ("LEDGER_INTEGRITY_UNKNOWN",))
    if replay.get("cash_krw") is not None and int(replay["cash_krw"]) < 0:
        discrepancies.append("NEGATIVE_CASH")
    for position in replay.get("positions") or []:
        if int(position.get("quantity") or 0) < 0:
            discrepancies.append(f"NEGATIVE_POSITION:{position.get('symbol_id')}")
    if replay_hash != expected_hash:
        discrepancies.append("PROJECTION_HASH_MISMATCH")

    if any(
        item.startswith(("EVENT_", "GLOBAL_", "AGGREGATE_", "NEGATIVE_"))
        for item in discrepancies
    ):
        status = "HALTED"
    elif discrepancies:
        status = "MISMATCH"
    else:
        status = "MATCHED"
    seed = canonical_hash(
        {
            "replay_projection_hash": replay_hash,
            "expected_projection_hash": expected_hash,
            "discrepancies": sorted(discrepancies),
            "reconciled_at": at,
            "intent_id": intent_id,
        }
    ).split(":", 1)[1]
    return ReconciliationResult(
        reconciliation_id=f"prec_{seed[:24]}",
        status=status,
        replay_projection_hash=replay_hash,
        expected_projection_hash=expected_hash,
        discrepancies=tuple(sorted(discrepancies)),
        reconciled_at=at,
        intent_id=intent_id,
    )


"""Alpha Core paper-ledger read API.

The routes in this module are deliberately projection-only.  They never
initialize the ledger, append an event, approve risk, simulate a fill, or call
a broker.  A missing database is a valid pre-bootstrap state and is reported
as such without creating files on disk.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from app.auth.decorators import admin_or_aibain_required


kr_alpha_core_bp = Blueprint("kr_alpha_core", __name__)

_API_SCHEMA_PREFIX = "marketflow.alpha_core.api"
_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500


def _generated_at() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _runtime_mode() -> str:
    from app.services.alpha_core.config import resolve_mode

    return resolve_mode()


def _paper_db_path() -> Path:
    from app.services.alpha_core import default_db_path

    return default_db_path()


def _open_reader():
    """Open an existing ledger in SQLite read-only/query-only mode.

    Importing the service is intentionally lazy so a not-yet-bootstrapped
    deployment can still report ``not_initialized``.  The path check also
    protects the GET boundary from SQLite's default create-on-connect behavior.
    """
    db_path = _paper_db_path()
    if not db_path.is_file():
        return None

    from app.services.alpha_core import PaperLedger

    return PaperLedger(db_path=db_path, read_only=True)


def _respond(payload: dict[str, Any], status: int = 200):
    response = jsonify(payload)
    response.status_code = status
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    return response


def _read_failed(resource: str, exc: Exception, *, mode: str):
    current_app.logger.error(
        "Alpha Core %s read failed",
        resource,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return _respond(
        {
            "schema_version": f"{_API_SCHEMA_PREFIX}.error.v1",
            "mode": mode,
            "ledger_environment": "paper",
            "generated_at": _generated_at(),
            "status": "unavailable",
            "error": {
                "code": "ALPHA_CORE_READ_FAILED",
                "resource": resource,
            },
        },
        status=503,
    )


def _configuration_failed(resource: str, exc: Exception):
    current_app.logger.error(
        "Alpha Core %s configuration rejected",
        resource,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return _respond(
        {
            "schema_version": f"{_API_SCHEMA_PREFIX}.error.v1",
            "mode": "invalid",
            "generated_at": _generated_at(),
            "status": "configuration_error",
            "available": False,
            "risk_state": "BLOCK_NEW",
            "error": {
                "code": "ALPHA_CORE_MODE_INVALID",
                "resource": resource,
            },
        },
        status=503,
    )


def _limit_arg() -> int:
    try:
        value = int(request.args.get("limit", _DEFAULT_LIMIT))
    except (TypeError, ValueError):
        value = _DEFAULT_LIMIT
    return max(1, min(value, _MAX_LIMIT))


def _optional_int_arg(name: str) -> int | None:
    raw = request.args.get(name)
    if raw in (None, ""):
        return None
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return None


def _optional_text_arg(name: str, max_length: int = 128) -> str | None:
    value = (request.args.get(name) or "").strip()
    return value[:max_length] or None


def _risk_item_projection(item: dict[str, Any]) -> dict[str, Any]:
    projected = dict(item)
    reasons = projected.get("reason_codes")
    if not isinstance(reasons, (list, tuple)):
        reasons = []
    projected["reason_codes"] = list(reasons)
    projected.setdefault("reasons", list(reasons))
    return projected


def _empty_status(mode: str) -> dict[str, Any]:
    return {
        "schema_version": f"{_API_SCHEMA_PREFIX}.status.v1",
        "mode": mode,
        "ledger_environment": "paper",
        "generated_at": _generated_at(),
        "status": "not_initialized",
        "available": False,
        "database": {"available": False, "initialized": False},
        "counts": {
            "events": 0,
            "intents": 0,
            "risk_decisions": 0,
            "fills": 0,
            "unreconciled": 0,
            "outbox_pending": 0,
        },
        "risk_state": "BLOCK_NEW",
        "quality": {"status": "not_initialized", "ok": False},
    }


def _status_projection(raw: dict[str, Any], *, mode: str) -> dict[str, Any]:
    intent_counts = raw.get("intent_counts")
    if not isinstance(intent_counts, dict):
        intent_counts = {}
    risk_counts = raw.get("risk_decision_counts")
    if not isinstance(risk_counts, dict):
        risk_counts = {}
    integrity = raw.get("integrity")
    if not isinstance(integrity, dict):
        integrity = {"status": "unknown", "ok": False}

    available = raw.get("available") is not False
    ledger_risk_state = raw.get("kill_state") or "BLOCK_NEW"
    effective_risk_state = "BLOCK_NEW" if mode == "shadow" else ledger_risk_state
    return {
        "schema_version": f"{_API_SCHEMA_PREFIX}.status.v1",
        "source_schema_version": raw.get("schema_version"),
        "mode": raw.get("mode") or mode,
        "ledger_environment": raw.get("environment") or "paper",
        "generated_at": _generated_at(),
        "status": "ok" if available else "not_initialized",
        "available": available,
        "database": {"available": available, "initialized": available},
        "counts": {
            "events": int(raw.get("event_count") or 0),
            "intents": sum(int(value or 0) for value in intent_counts.values()),
            "risk_decisions": sum(int(value or 0) for value in risk_counts.values()),
            "fills": int(raw.get("fill_count") or 0),
            "unreconciled": int(raw.get("unreconciled_count") or 0),
            "outbox_pending": int(raw.get("outbox_pending_count") or 0),
        },
        "intent_counts": intent_counts,
        "risk_decision_counts": risk_counts,
        "risk_state": effective_risk_state,
        "ledger_risk_state": ledger_risk_state,
        "last_event_at": raw.get("last_event_at"),
        "quality": integrity,
    }


@kr_alpha_core_bp.route("/status", methods=["GET"])
@admin_or_aibain_required
def alpha_core_status():
    try:
        mode = _runtime_mode()
    except Exception as exc:  # invalid/live mode must fail closed
        return _configuration_failed("status", exc)
    try:
        reader = _open_reader()
    except Exception as exc:  # pragma: no cover - deployment/import failure
        return _read_failed("status", exc, mode=mode)
    if reader is None:
        return _respond(_empty_status(mode))
    try:
        return _respond(_status_projection(reader.status(), mode=mode))
    except Exception as exc:  # pragma: no cover - exact SQLite errors vary
        return _read_failed("status", exc, mode=mode)


@kr_alpha_core_bp.route("/portfolio", methods=["GET"])
@admin_or_aibain_required
def alpha_core_portfolio():
    try:
        mode = _runtime_mode()
    except Exception as exc:  # invalid/live mode must fail closed
        return _configuration_failed("portfolio", exc)
    try:
        reader = _open_reader()
    except Exception as exc:  # pragma: no cover - deployment/import failure
        return _read_failed("portfolio", exc, mode=mode)
    if reader is None:
        return _respond(
            {
                "schema_version": f"{_API_SCHEMA_PREFIX}.portfolio.v1",
                "mode": mode,
                "ledger_environment": "paper",
                "generated_at": _generated_at(),
                "status": "not_initialized",
                "cash": None,
                "nav": None,
                "gross_exposure": 0,
                "net_exposure": 0,
                "drawdown": None,
                "cash_krw": None,
                "reserved_cash_krw": 0,
                "gross_exposure_krw": 0,
                "net_exposure_krw": 0,
                "positions": [],
                "as_of": None,
                "units": {
                    "cash": "KRW",
                    "nav": "KRW",
                    "gross_exposure": "KRW",
                    "net_exposure": "KRW",
                    "drawdown": "percent",
                },
            }
        )
    try:
        raw = reader.portfolio()
        cash = raw.get("cash_krw")
        gross = raw.get("gross_exposure_krw")
        net = raw.get("net_exposure_krw")
        return _respond(
            {
                **raw,
                "schema_version": f"{_API_SCHEMA_PREFIX}.portfolio.v1",
                "source_schema_version": raw.get("schema_version"),
                "mode": mode,
                "ledger_environment": "paper",
                "generated_at": _generated_at(),
                "status": "ok",
                "cash": cash,
                "nav": raw.get("nav_krw"),
                "gross_exposure": gross,
                "net_exposure": net,
                "drawdown": raw.get("drawdown_pct"),
                "units": {
                    "cash": "KRW",
                    "nav": "KRW",
                    "gross_exposure": "KRW",
                    "net_exposure": "KRW",
                    "drawdown": "percent",
                },
            }
        )
    except Exception as exc:  # pragma: no cover - exact SQLite errors vary
        return _read_failed("portfolio", exc, mode=mode)


@kr_alpha_core_bp.route("/risk-decisions", methods=["GET"])
@admin_or_aibain_required
def alpha_core_risk_decisions():
    limit = _limit_arg()
    decision = _optional_text_arg("decision", max_length=32)
    intent_id = _optional_text_arg("intent_id")
    try:
        mode = _runtime_mode()
    except Exception as exc:  # invalid/live mode must fail closed
        return _configuration_failed("risk-decisions", exc)
    try:
        reader = _open_reader()
    except Exception as exc:  # pragma: no cover - deployment/import failure
        return _read_failed("risk-decisions", exc, mode=mode)
    items: list[dict[str, Any]] = []
    status = "not_initialized"
    if reader is not None:
        try:
            items = reader.list_risk_decisions(
                limit=limit,
                decision=decision,
                intent_id=intent_id,
            )
            items = [_risk_item_projection(item) for item in items]
            status = "ok"
        except Exception as exc:  # pragma: no cover - exact SQLite errors vary
            return _read_failed("risk-decisions", exc, mode=mode)
    return _respond(
        {
            "schema_version": f"{_API_SCHEMA_PREFIX}.risk_decisions.v1",
            "mode": mode,
            "ledger_environment": "paper",
            "generated_at": _generated_at(),
            "status": status,
            "count": len(items),
            "items": items,
            "filters": {
                "limit": limit,
                "decision": decision,
                "intent_id": intent_id,
            },
        }
    )


@kr_alpha_core_bp.route("/hypotheses", methods=["GET"])
@admin_or_aibain_required
def alpha_core_hypotheses():
    """Advertise the intentionally deferred research registry explicitly."""
    try:
        mode = _runtime_mode()
    except Exception as exc:  # invalid/live mode must fail closed
        return _configuration_failed("hypotheses", exc)
    return _respond(
        {
            "schema_version": f"{_API_SCHEMA_PREFIX}.hypotheses.v1",
            "mode": mode,
            "ledger_environment": "paper",
            "generated_at": _generated_at(),
            "status": "not_implemented",
            "count": 0,
            "items": [],
        }
    )


@kr_alpha_core_bp.route("/ledger", methods=["GET"])
@admin_or_aibain_required
def alpha_core_ledger():
    limit = _limit_arg()
    after_id = _optional_int_arg("after_id")
    aggregate_id = _optional_text_arg("aggregate_id")
    event_type = _optional_text_arg("event_type", max_length=64)
    try:
        mode = _runtime_mode()
    except Exception as exc:  # invalid/live mode must fail closed
        return _configuration_failed("ledger", exc)
    try:
        reader = _open_reader()
    except Exception as exc:  # pragma: no cover - deployment/import failure
        return _read_failed("ledger", exc, mode=mode)
    items: list[dict[str, Any]] = []
    status_raw: dict[str, Any] = {}
    status = "not_initialized"
    if reader is not None:
        try:
            items = reader.list_events(
                limit=limit,
                after_id=after_id,
                aggregate_id=aggregate_id,
                event_type=event_type,
            )
            status_raw = reader.status()
            status = "ok"
        except Exception as exc:  # pragma: no cover - exact SQLite errors vary
            return _read_failed("ledger", exc, mode=mode)

    intent_counts = status_raw.get("intent_counts")
    if not isinstance(intent_counts, dict):
        intent_counts = {}
    pending_states = {
        "proposed",
        "reserved",
        "approved",
        "rule_approved",
        "paper_submitted",
        "partial",
        "pending",
    }
    pending = sum(
        int(value or 0)
        for key, value in intent_counts.items()
        if str(key).lower() in pending_states
    )
    unreconciled = int(status_raw.get("unreconciled_count") or 0)
    return _respond(
        {
            "schema_version": f"{_API_SCHEMA_PREFIX}.ledger.v1",
            "mode": mode,
            "ledger_environment": "paper",
            "generated_at": _generated_at(),
            "status": status,
            "count": len(items),
            "pending": pending,
            "reconcile_required": unreconciled > 0,
            "reconciliation": {
                "required": unreconciled > 0,
                "unreconciled_count": unreconciled,
            },
            "items": items,
            "filters": {
                "limit": limit,
                "after_id": after_id,
                "aggregate_id": aggregate_id,
                "event_type": event_type,
            },
        }
    )

"""Cutoff-safe full/compact TradingAgents comparison.

The default mode is a local replay over an already persisted EvidencePacket and
two saved result artifacts.  Provider execution is possible only with the
explicit ``--live`` switch and a fresh, healthy DeepSeek decisive-model health
record.  The script never rebuilds evidence from current market files.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import inspect
import json
import math
import os
import re
import sys
import threading
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.ai_routing.contracts import AnalysisStatus, Operation  # noqa: E402
from app.services.ai_routing.policy import policy_for  # noqa: E402
from app.services.ai_routing.reporting import (  # noqa: E402
    HEALTH_SCHEMA_VERSION,
    HEALTH_SNAPSHOT_PATH,
)
from app.services.ai_routing.store import RoutingStore  # noqa: E402
from app.services.mirofish import evidence_packet as evidence_packet_mod  # noqa: E402
from app.services.mirofish.tradingagents import data_hub, engine  # noqa: E402
from app.utils.atomic_json import write_json_atomic  # noqa: E402
from app.utils.paths import DATA_DIR  # noqa: E402


_MAX_JSON_BYTES = 16 * 1024 * 1024
_MAX_HEALTH_BYTES = 64 * 1024
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
_ENGINE_INJECTION_LOCK = threading.Lock()
_SUCCESS_STATUSES = {
    AnalysisStatus.SUCCESS_PRIMARY.value,
    AnalysisStatus.SUCCESS_FALLBACK.value,
}


class ReplayValidationError(ValueError):
    """A fixed, secret-free canonical replay rejection code."""


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _parse_utc(value: object, *, code: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ReplayValidationError(code)
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReplayValidationError(code) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _aware_now(now: datetime | None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ReplayValidationError("now_must_be_timezone_aware")
    return current.astimezone(timezone.utc)


def _packet_body_fingerprint(packet: Mapping[str, Any]) -> str:
    body = copy.deepcopy(dict(packet))
    body.pop("fingerprint", None)
    return _sha(body)


def _contains_non_finite_number(value: Any) -> bool:
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, Decimal):
        return not value.is_finite()
    if isinstance(value, Mapping):
        return any(_contains_non_finite_number(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_non_finite_number(item) for item in value)
    return False


def validate_evidence_packet(packet: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and copy one complete, cutoff-bound canonical packet."""
    if not isinstance(packet, Mapping):
        raise ReplayValidationError("packet_not_object")
    frozen = copy.deepcopy(dict(packet))
    for field in ("symbol", "name", "market", "as_of"):
        if not isinstance(frozen.get(field), str) or not frozen[field].strip():
            raise ReplayValidationError(f"packet_{field}_missing")
    if frozen.get("schema_version") != evidence_packet_mod.SCHEMA_VERSION:
        raise ReplayValidationError("packet_schema_version_mismatch")
    if frozen.get("prompt_version") != evidence_packet_mod.PROMPT_VERSION:
        raise ReplayValidationError("packet_prompt_version_mismatch")
    fingerprint = frozen.get("fingerprint")
    if not isinstance(fingerprint, str) or not _FINGERPRINT_RE.fullmatch(fingerprint):
        raise ReplayValidationError("packet_fingerprint_invalid")

    cutoff = _parse_utc(frozen["as_of"], code="packet_as_of_invalid")
    sources = frozen.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ReplayValidationError("packet_sources_missing")
    source_ids: list[str] = []
    for source in sources:
        if not isinstance(source, Mapping):
            raise ReplayValidationError("packet_source_invalid")
        evidence_id = source.get("evidence_id")
        if not isinstance(evidence_id, str) or not evidence_id.strip():
            raise ReplayValidationError("source_evidence_id_missing")
        if not isinstance(source.get("source"), str) or not source["source"].strip():
            raise ReplayValidationError("source_name_missing")
        fetched_at = _parse_utc(source.get("fetched_at"), code="source_fetched_at_invalid")
        if fetched_at > cutoff:
            raise ReplayValidationError("source_after_as_of")
        content_fingerprint = source.get("content_fingerprint")
        if (
            not isinstance(content_fingerprint, str)
            or not _FINGERPRINT_RE.fullmatch(content_fingerprint)
            or content_fingerprint != _sha(source.get("content"))
        ):
            raise ReplayValidationError("source_fingerprint_mismatch")
        source_ids.append(evidence_id)
    if len(source_ids) != len(set(source_ids)):
        raise ReplayValidationError("duplicate_evidence_id")
    if frozen.get("evidence_ids") != source_ids:
        raise ReplayValidationError("packet_evidence_ids_mismatch")
    if not isinstance(frozen.get("numeric_inputs"), Mapping):
        raise ReplayValidationError("packet_numeric_inputs_missing")
    if not isinstance(frozen.get("deterministic_scores"), Mapping):
        raise ReplayValidationError("packet_scores_missing")
    if _contains_non_finite_number(frozen.get("numeric_inputs")) or _contains_non_finite_number(
        frozen.get("deterministic_scores")
    ):
        raise ReplayValidationError("packet_numeric_non_finite")
    if not isinstance(frozen.get("execution_inputs"), Mapping):
        raise ReplayValidationError("packet_execution_inputs_missing")
    if not isinstance(frozen.get("models"), Mapping):
        raise ReplayValidationError("packet_models_missing")
    if _packet_body_fingerprint(frozen) != fingerprint:
        raise ReplayValidationError("packet_fingerprint_mismatch")
    return frozen


def _blank_profile() -> dict[str, Any]:
    return {
        "call_count": None,
        "attempt_count": None,
        "ledger_available": False,
        "ledger_logical_calls": 0,
        "ledger_attempts": 0,
        "ledger_live_attempts": 0,
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "known_input_tokens": 0,
        "known_output_tokens": 0,
        "known_total_tokens": 0,
        "unknown_usage_attempts": 0,
        "usage_completeness": None,
        "verdict": None,
        "analysis_status": None,
        "schema_success": None,
    }


def _base_report(packet: Mapping[str, Any], *, live: bool) -> dict[str, Any]:
    return {
        "schema_version": "tradingagents-profile-comparison-v1",
        "packet_id": packet["fingerprint"],
        "symbol": packet["symbol"],
        "name": packet["name"],
        "market": packet["market"],
        "as_of": packet["as_of"],
        "live": bool(live),
        "blocked": False,
        "blocked_reason": None,
        "profiles": {"full": _blank_profile(), "compact": _blank_profile()},
        "verdict_disagreement": None,
        "numeric_violations": [],
        "source_violations": [],
        "schema_violations": [],
        "identity_violations": [],
        "hidden_failures": [],
        "lookahead_safe": True,
    }


def _safe_health_snapshot(path: str | Path | None) -> Mapping[str, Any] | None:
    selected = Path(path) if path is not None else Path(HEALTH_SNAPSHOT_PATH)
    try:
        if selected.name != "health.json" or not selected.is_file():
            return None
        if selected.stat().st_size <= 0 or selected.stat().st_size > _MAX_HEALTH_BYTES:
            return None
        value = json.loads(selected.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, Mapping) else None


def _health_timestamp_is_fresh(
    checked_at: object,
    ttl_seconds: object,
    now: datetime,
) -> bool:
    if (
        isinstance(ttl_seconds, bool)
        or not isinstance(ttl_seconds, int)
        or ttl_seconds <= 0
        or ttl_seconds > 86_400
    ):
        return False
    try:
        checked = _parse_utc(checked_at, code="health_timestamp_invalid")
    except ReplayValidationError:
        return False
    age = (now - checked).total_seconds()
    return 0 <= age < ttl_seconds


def deepseek_decisive_is_healthy(
    snapshot: Mapping[str, Any] | None,
    *,
    now: datetime | None = None,
) -> bool:
    """Require a fresh exact-model DeepSeek decisive record; OA is irrelevant."""
    if not isinstance(snapshot, Mapping) or snapshot.get("schema_version") != HEALTH_SCHEMA_VERSION:
        return False
    if not os.getenv("DEEPSEEK_API_KEY", "").strip():
        return False
    telemetry = snapshot.get("telemetry")
    activation = snapshot.get("cost_saving_activation")
    if not (
        isinstance(telemetry, Mapping)
        and telemetry.get("complete") is True
        and telemetry.get("status") == "complete"
        and isinstance(activation, Mapping)
        and activation.get("ready") is True
        and activation.get("status") == "ready"
    ):
        return False
    current = _aware_now(now)
    if not _health_timestamp_is_fresh(
        snapshot.get("checked_at"), snapshot.get("ttl_seconds"), current
    ):
        return False
    providers = snapshot.get("providers")
    if not isinstance(providers, list):
        return False
    expected_model = policy_for(Operation.DECISIVE_TEXT).models["deepseek"]
    matches = [
        row
        for row in providers
        if isinstance(row, Mapping)
        and row.get("provider") == "deepseek"
        and row.get("operation") == Operation.DECISIVE_TEXT.value
    ]
    if len(matches) != 1:
        return False
    row = matches[0]
    return bool(
        row.get("configured") is True
        and row.get("available") is True
        and row.get("status") == "healthy"
        and row.get("model") == expected_model
        and _health_timestamp_is_fresh(
            row.get("checked_at"), row.get("ttl_seconds"), current
        )
    )


def _decimal_number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _iter_fields(value: Any, *, prefix: str = ""):
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in {"evidence_packet", "raw_prompt", "raw_response", "raw_error", "error"}:
                continue
            path = f"{prefix}.{key}" if prefix else str(key)
            yield path, str(key), item
            yield from _iter_fields(item, prefix=path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _iter_fields(item, prefix=f"{prefix}[{index}]")


def _ledger_metrics(store: RoutingStore | None, run_id: object) -> dict[str, Any]:
    empty = {
        "ledger_available": store is not None,
        "ledger_logical_calls": 0,
        "ledger_attempts": 0,
        "ledger_live_attempts": 0,
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "known_input_tokens": 0,
        "known_output_tokens": 0,
        "known_total_tokens": 0,
        "unknown_usage_attempts": 0,
        "usage_completeness": None,
        "_ledger_error": False,
    }
    if store is None or not isinstance(run_id, str) or not run_id:
        return empty
    try:
        with store.transaction() as connection:
            rows = connection.execute(
                """SELECT status, input_tokens, output_tokens, usage_mapping_status
                   FROM provider_attempts WHERE run_id=? ORDER BY request_id, attempt_number""",
                (run_id,),
            ).fetchall()
            logical_row = connection.execute(
                """SELECT COUNT(DISTINCT request_id) AS logical_calls
                   FROM provider_attempts WHERE run_id=?""",
                (run_id,),
            ).fetchone()
    except Exception:
        return {**empty, "ledger_available": False, "_ledger_error": True}
    logical_calls = int(logical_row["logical_calls"] or 0)
    live_rows = [row for row in rows if not str(row["status"] or "").startswith("skipped_")]
    if not live_rows:
        return {
            **empty,
            "ledger_logical_calls": logical_calls,
            "ledger_attempts": len(rows),
        }
    known_input = 0
    known_output = 0
    unknown = 0
    for row in live_rows:
        quarantined = row["usage_mapping_status"] == "quarantined"
        if quarantined or row["input_tokens"] is None or row["output_tokens"] is None:
            unknown += 1
            continue
        known_input += int(row["input_tokens"])
        known_output += int(row["output_tokens"])
    complete = unknown == 0
    return {
        "ledger_available": True,
        "ledger_logical_calls": logical_calls,
        "ledger_attempts": len(rows),
        "ledger_live_attempts": len(live_rows),
        "input_tokens": known_input if complete else None,
        "output_tokens": known_output if complete else None,
        "total_tokens": known_input + known_output if complete else None,
        "known_input_tokens": known_input,
        "known_output_tokens": known_output,
        "known_total_tokens": known_input + known_output,
        "unknown_usage_attempts": unknown,
        "usage_completeness": (len(live_rows) - unknown) / len(live_rows),
        "_ledger_error": False,
    }


def _violation(profile: str, code: str, **fields: Any) -> dict[str, Any]:
    return {"profile": profile, "code": code, **fields}


def _profile_report(
    profile: str,
    result: Mapping[str, Any],
    packet: Mapping[str, Any],
    store: RoutingStore | None,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    violations: dict[str, list[dict[str, Any]]] = {
        "numeric_violations": [],
        "source_violations": [],
        "schema_violations": [],
        "identity_violations": [],
        "hidden_failures": [],
    }
    expected_identity = {
        "symbol": packet["symbol"],
        "market": packet["market"],
        "target": packet["name"],
    }
    for field, expected in expected_identity.items():
        if result.get(field) != expected:
            violations["identity_violations"].append(
                _violation(profile, f"{field}_mismatch")
            )
    if result.get("profile") != profile:
        violations["schema_violations"].append(_violation(profile, "profile_mismatch"))
    if result.get("evidence_fingerprint") != packet["fingerprint"]:
        violations["source_violations"].append(
            _violation(profile, "evidence_fingerprint_mismatch")
        )
    embedded_packet = result.get("evidence_packet")
    if not isinstance(embedded_packet, Mapping):
        violations["source_violations"].append(_violation(profile, "evidence_packet_missing"))
    elif _canonical(embedded_packet) != _canonical(packet):
        violations["source_violations"].append(_violation(profile, "evidence_packet_mismatch"))

    verdict_doc = result.get("verdict")
    verdict = (
        str(verdict_doc.get("verdict") or "").strip().upper()
        if isinstance(verdict_doc, Mapping)
        else ""
    )
    allowed = set(packet.get("allowed_verdicts") or [])
    if not verdict or verdict not in allowed:
        violations["schema_violations"].append(_violation(profile, "verdict_schema_invalid"))
        verdict = ""

    analysis_status = result.get("analysis_status")
    if not isinstance(analysis_status, str) or not analysis_status:
        violations["hidden_failures"].append(
            _violation(profile, "analysis_status_missing")
        )
        analysis_status = None
    elif analysis_status not in {item.value for item in AnalysisStatus}:
        violations["schema_violations"].append(
            _violation(profile, "analysis_status_invalid")
        )
        analysis_status = None

    usage = result.get("provider_usage")
    calls: int | None = None
    attempts: int | None = None
    if isinstance(usage, Mapping):
        value = usage.get("calls")
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            calls = value
        else:
            violations["schema_violations"].append(
                _violation(profile, "call_count_invalid")
            )
        value = usage.get("attempts")
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            attempts = value
        else:
            violations["schema_violations"].append(
                _violation(profile, "attempt_count_invalid")
            )
    else:
        violations["schema_violations"].append(
            _violation(profile, "provider_usage_missing")
        )
    if calls is not None and attempts is not None and attempts < calls:
        violations["schema_violations"].append(
            _violation(profile, "attempt_count_invalid")
        )
        attempts = None

    authoritative: dict[str, Any] = {}
    authoritative.update(dict(packet.get("numeric_inputs") or {}))
    authoritative.update(dict(packet.get("deterministic_scores") or {}))
    for path, key, actual in _iter_fields(result):
        if key not in authoritative or authoritative[key] is None:
            continue
        expected_number = _decimal_number(authoritative[key])
        actual_number = _decimal_number(actual)
        if expected_number is None or actual_number != expected_number:
            violations["numeric_violations"].append(
                _violation(profile, "numeric_mismatch")
            )

    allowed_ids = set(packet.get("evidence_ids") or [])
    for path, key, value in _iter_fields(result):
        cited: list[Any] = []
        if key == "evidence_id":
            cited = [value]
        elif key == "evidence_ids" and isinstance(value, list):
            cited = value
        for evidence_id in cited:
            if evidence_id not in allowed_ids:
                violations["source_violations"].append(
                    _violation(profile, "unknown_evidence_id")
                )

    ledger = _ledger_metrics(store, result.get("routing_run_id"))
    ledger_error = bool(ledger.pop("_ledger_error", False))
    if ledger_error:
        violations["hidden_failures"].append(
            _violation(profile, "ledger_unavailable")
        )
    elif attempts is None:
        if ledger["ledger_attempts"] > 0 or (calls is not None and calls > 0):
            violations["hidden_failures"].append(
                _violation(profile, "ledger_attempt_count_unverifiable")
            )
    elif attempts > 0 and not ledger["ledger_available"]:
        violations["hidden_failures"].append(
            _violation(profile, "ledger_unavailable")
        )
    elif ledger["ledger_available"] and ledger["ledger_attempts"] != attempts:
        violations["hidden_failures"].append(
            _violation(profile, "ledger_attempt_count_mismatch")
        )
    if not ledger_error:
        if calls is None and ledger["ledger_logical_calls"] > 0:
            violations["hidden_failures"].append(
                _violation(profile, "ledger_call_count_unverifiable")
            )
        elif (
            calls is not None
            and ledger["ledger_available"]
            and ledger["ledger_logical_calls"] != calls
        ):
            violations["hidden_failures"].append(
                _violation(profile, "ledger_call_count_mismatch")
            )
    if analysis_status in _SUCCESS_STATUSES and not verdict:
        violations["hidden_failures"].append(
            _violation(profile, "success_without_verdict")
        )
    schema_success = not any(
        violations[key]
        for key in ("schema_violations", "identity_violations", "source_violations")
    )
    summary = {
        "call_count": calls,
        "attempt_count": attempts,
        **ledger,
        "verdict": verdict or None,
        "analysis_status": analysis_status,
        "schema_success": schema_success,
    }
    return summary, violations


def _safe_engine_injection_available() -> bool:
    try:
        parameters = inspect.signature(engine.run_deep_analysis).parameters
    except (TypeError, ValueError):
        return False
    accepts_keywords = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )
    return (
        callable(getattr(data_hub, "bundle_from_evidence_packet", None))
        and callable(getattr(data_hub, "gather_bundle", None))
        and (
            accepts_keywords
            or {"profile", "evidence_packet", "force"} <= set(parameters)
        )
    )


def run_engine_profile(
    *,
    profile: str,
    packet: dict[str, Any],
    frozen_bundle: dict[str, Any],
    artifact_root: str | Path,
    force: bool,
) -> dict[str, Any]:
    """Run one profile in a process-local frozen-source, isolated-root scope."""
    if profile not in {"full", "compact"} or not _safe_engine_injection_available():
        raise ReplayValidationError("safe_full_injection_unavailable")
    selected_root = Path(artifact_root)
    selected_root.mkdir(parents=True, exist_ok=True)
    execution = packet.get("execution_inputs") or {}
    with _ENGINE_INJECTION_LOCK:
        original_gather = data_hub.gather_bundle
        original_root = engine.RUNS_ROOT

        def frozen_gather(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            return copy.deepcopy(frozen_bundle)

        data_hub.gather_bundle = frozen_gather
        engine.RUNS_ROOT = os.fspath(selected_root)
        try:
            result = engine.run_deep_analysis(
                packet["name"],
                symbol=packet["symbol"],
                use_llm=bool(execution.get("use_llm")),
                brain=copy.deepcopy(execution.get("brain")),
                profile=profile,
                evidence_packet=packet,
                force=bool(force),
            )
        finally:
            data_hub.gather_bundle = original_gather
            engine.RUNS_ROOT = original_root
    if not isinstance(result, dict):
        raise ReplayValidationError("runner_invalid_result")
    return result


def compare_profiles(
    packet: Mapping[str, Any],
    *,
    full_result: Mapping[str, Any] | None = None,
    compact_result: Mapping[str, Any] | None = None,
    live: bool = False,
    runner: Callable[..., Mapping[str, Any]] | None = None,
    store: RoutingStore | None = None,
    health_snapshot: Mapping[str, Any] | None = None,
    health_path: str | Path | None = None,
    artifact_root: str | Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Compare saved results or explicitly execute two cutoff-identical profiles."""
    frozen_packet = validate_evidence_packet(packet)
    report = _base_report(frozen_packet, live=live)
    results: dict[str, Mapping[str, Any]] = {}

    if not live:
        if not isinstance(full_result, Mapping) or not isinstance(compact_result, Mapping):
            raise ReplayValidationError("saved_results_required")
        results = {"full": full_result, "compact": compact_result}
    else:
        if dict(frozen_packet.get("models") or {}) != engine.routing_model_ids():
            raise ReplayValidationError("packet_model_identity_mismatch")
        current = _aware_now(now)
        snapshot = (
            health_snapshot
            if health_snapshot is not None
            else _safe_health_snapshot(health_path)
        )
        if not deepseek_decisive_is_healthy(snapshot, now=current):
            report["blocked"] = True
            report["blocked_reason"] = "deepseek_decisive_health_unavailable"
            return report
        selected_runner = runner or run_engine_profile
        if selected_runner is run_engine_profile and not _safe_engine_injection_available():
            report["blocked"] = True
            report["blocked_reason"] = "safe_full_injection_unavailable"
            return report
        frozen_bundle = data_hub.bundle_from_evidence_packet(
            frozen_packet,
            brain=copy.deepcopy((frozen_packet.get("execution_inputs") or {}).get("brain")),
        )
        root = Path(artifact_root) if artifact_root is not None else (
            Path(DATA_DIR)
            / "admin_mirofish"
            / "profile_comparisons"
            / f"{current.strftime('%Y%m%dT%H%M%S%fZ')}_{frozen_packet['fingerprint'][:12]}"
        )
        for profile in ("full", "compact"):
            packet_copy = copy.deepcopy(frozen_packet)
            before = _canonical(packet_copy)
            try:
                result = selected_runner(
                    profile=profile,
                    packet=packet_copy,
                    frozen_bundle=copy.deepcopy(frozen_bundle),
                    artifact_root=root / profile,
                    force=profile == "compact",
                )
            except ReplayValidationError:
                raise
            except Exception:
                report["blocked"] = True
                report["blocked_reason"] = "profile_runner_failed"
                report["hidden_failures"].append(
                    _violation(profile, "runner_failed")
                )
                return report
            if _canonical(packet_copy) != before:
                raise ReplayValidationError("runner_mutated_packet")
            if not isinstance(result, Mapping):
                raise ReplayValidationError("runner_invalid_result")
            results[profile] = result

    all_violations = {
        "numeric_violations": [],
        "source_violations": [],
        "schema_violations": [],
        "identity_violations": [],
        "hidden_failures": [],
    }
    for profile in ("full", "compact"):
        summary, violations = _profile_report(
            profile,
            results[profile],
            frozen_packet,
            store,
        )
        report["profiles"][profile] = summary
        for key, values in violations.items():
            all_violations[key].extend(values)
    report.update(all_violations)
    if any(
        item.get("code")
        in {
            "ledger_unavailable",
            "ledger_attempts_missing",
            "ledger_attempt_count_mismatch",
            "ledger_attempt_count_unverifiable",
            "ledger_call_count_mismatch",
            "ledger_call_count_unverifiable",
        }
        for item in report["hidden_failures"]
    ):
        report["blocked"] = True
        report["blocked_reason"] = "ledger_usage_unverifiable"
    full_verdict = report["profiles"]["full"]["verdict"]
    compact_verdict = report["profiles"]["compact"]["verdict"]
    report["verdict_disagreement"] = (
        full_verdict != compact_verdict
        if full_verdict is not None and compact_verdict is not None
        else None
    )
    return report


def _read_json(path: str | Path) -> dict[str, Any]:
    selected = Path(path)
    try:
        if not selected.is_file() or not 0 < selected.stat().st_size <= _MAX_JSON_BYTES:
            raise ReplayValidationError("input_file_unavailable")
        value = json.loads(selected.read_text(encoding="utf-8"))
    except ReplayValidationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReplayValidationError("input_json_invalid") from exc
    if not isinstance(value, dict):
        raise ReplayValidationError("input_json_not_object")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare TradingAgents profiles safely")
    parser.add_argument("packet", help="saved canonical EvidencePacket JSON")
    parser.add_argument("--full-result", help="saved full-profile result JSON")
    parser.add_argument("--compact-result", help="saved compact-profile result JSON")
    parser.add_argument("--ledger", help="optional central usage.sqlite3 path")
    parser.add_argument("--health-snapshot", help="live health.json path")
    parser.add_argument("--artifact-root", help="isolated live artifact directory")
    parser.add_argument("--output", help="write sanitized JSON report atomically")
    parser.add_argument("--live", action="store_true", help="explicitly allow profile execution")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        packet = _read_json(args.packet)
        store = RoutingStore(args.ledger) if args.ledger else None
        if args.live:
            report = compare_profiles(
                packet,
                live=True,
                store=store,
                health_path=args.health_snapshot,
                artifact_root=args.artifact_root,
            )
        else:
            if not args.full_result or not args.compact_result:
                raise ReplayValidationError("saved_results_required")
            report = compare_profiles(
                packet,
                full_result=_read_json(args.full_result),
                compact_result=_read_json(args.compact_result),
                store=store,
            )
        exit_code = 2 if report.get("blocked") else 0
    except ReplayValidationError as exc:
        report = {
            "schema_version": "tradingagents-profile-comparison-v1",
            "blocked": True,
            "blocked_reason": str(exc),
        }
        exit_code = 2
    if args.output:
        write_json_atomic(args.output, report, sort_keys=True)
    else:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

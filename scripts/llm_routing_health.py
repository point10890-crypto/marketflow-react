"""Secret-safe, opt-in live health check for the central AI router.

Offline mode is the default.  It reports configuration without constructing
provider clients, touching the network, or replacing the last persisted live
snapshot.  ``--live`` performs one direct adapter call per configured vendor;
it deliberately does not use the router, retry, or fall back.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.ai_routing.contracts import (  # noqa: E402
    Operation,
    ProviderAttempt,
    ProviderErrorClass,
    RoutingRequest,
    TokenUsage,
    VisionImage,
)
from app.services.ai_routing.policy import (  # noqa: E402
    policy_for,
    vision_attestation_is_valid,
)
from app.services.ai_routing.providers import (  # noqa: E402
    AdapterResponse,
    ProviderCallError,
    ProviderAdapter,
    build_default_adapters,
    classify_exception,
)
from app.services.ai_routing.reporting import (  # noqa: E402
    HEALTH_SCHEMA_VERSION,
    HEALTH_SNAPSHOT_PATH,
)
from app.services.ai_routing.telemetry import record_attempt  # noqa: E402
from app.utils.atomic_json import write_json_atomic  # noqa: E402


DEFAULT_TTL_SECONDS = 300
MAX_TTL_SECONDS = 86_400
# Gemini 2.5 Flash can consume about 50-60 reasoning tokens before emitting
# the one-word vision probe response.  Keep the probe small while leaving
# enough room to avoid misclassifying a healthy image request as EMPTY.
_MAX_OUTPUT_TOKENS = 64
_CALLER_ENDPOINT = "llm_routing_health"
_DEFAULT_RECORDER = object()
_SAFE_ATTESTATION_FIELDS = (
    "provider",
    "endpoint",
    "model",
    "modality",
    "checked_at",
    "ttl_seconds",
    "capable",
    "healthy",
)
_ERROR_STATUS = {
    ProviderErrorClass.AUTHENTICATION: "authentication",
    ProviderErrorClass.INSUFFICIENT_BALANCE: "insufficient_balance",
    ProviderErrorClass.RATE_LIMIT: "rate_limit",
    ProviderErrorClass.TIMEOUT: "timeout",
    ProviderErrorClass.CONNECTION: "connection",
    ProviderErrorClass.SERVER_ERROR: "server_error",
    ProviderErrorClass.MODEL_UNAVAILABLE: "model_unavailable",
    ProviderErrorClass.BUDGET_EXHAUSTED: "billing",
    ProviderErrorClass.CLIENT_UNAVAILABLE: "unavailable",
    ProviderErrorClass.BREAKER_OPEN: "unavailable",
    ProviderErrorClass.PAYLOAD_TOO_LARGE: "unavailable",
    ProviderErrorClass.INVALID_JSON: "unavailable",
    ProviderErrorClass.NUMERIC_MISMATCH: "unavailable",
    ProviderErrorClass.EMPTY: "unavailable",
    ProviderErrorClass.REFUSAL: "unavailable",
    ProviderErrorClass.UNKNOWN: "unknown",
}

# A real 1x1 PNG lets the Gemini probe verify image acceptance with the same
# single physical request used for model health.
_ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


@dataclass(frozen=True)
class ProbeSpec:
    """One vendor's only permitted physical health request."""

    provider: str
    operation: Operation
    model: str
    configured: bool
    request: RoutingRequest


@dataclass(frozen=True)
class ProbeResult:
    """Successful probe response plus optional independent Vision evidence.

    A normal decisive DeepSeek response has no Vision attestation.  A custom
    deployment probe may attach a separately measured capability record, but
    it is persisted only after the central policy validates its exact identity,
    model, modality, timestamp, TTL, and health flags.
    """

    response: AdapterResponse
    vision_attestation: Mapping[str, object] | None = None


Probe = Callable[[ProbeSpec], ProbeResult | AdapterResponse]
AttemptRecorder = Callable[[ProviderAttempt], object]


def _utc_now(now: datetime | None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return current.astimezone(timezone.utc)


def _validated_ttl(ttl_seconds: int) -> int:
    if (
        isinstance(ttl_seconds, bool)
        or not isinstance(ttl_seconds, int)
        or ttl_seconds <= 0
        or ttl_seconds > MAX_TTL_SECONDS
    ):
        raise ValueError("ttl_seconds must be an integer between 1 and 86400")
    return ttl_seconds


def _configured(name: str) -> bool:
    return bool(os.getenv(name, "").strip())


def _provider_specs() -> list[ProbeSpec]:
    decisive = policy_for(Operation.DECISIVE_TEXT)
    vision = policy_for(Operation.VISION)
    definitions = (
        (
            "deepseek",
            Operation.DECISIVE_TEXT,
            decisive.models["deepseek"],
            _configured("DEEPSEEK_API_KEY"),
        ),
        (
            "openai",
            Operation.DECISIVE_TEXT,
            decisive.models["openai"],
            _configured("OPENAI_API_KEY"),
        ),
        (
            "gemini",
            Operation.VISION,
            vision.models["gemini"],
            _configured("GEMINI_API_KEY") or _configured("GOOGLE_API_KEY"),
        ),
    )
    specs: list[ProbeSpec] = []
    for provider, operation, model, configured in definitions:
        is_vision = operation is Operation.VISION
        request = RoutingRequest(
            operation=operation,
            prompt=(
                "Reply with OK if this image can be processed."
                if is_vision
                else "Reply with the single word OK."
            ),
            run_id="llm-routing-health",
            request_id=f"llm-health-{provider}-{uuid.uuid4().hex}",
            max_output_tokens=_MAX_OUTPUT_TOKENS,
            caller_endpoint=_CALLER_ENDPOINT,
            images=(VisionImage(_ONE_PIXEL_PNG),) if is_vision else (),
            openai_fallback_allowed=False,
        )
        specs.append(
            ProbeSpec(
                provider=provider,
                operation=operation,
                model=model,
                configured=configured,
                request=request,
            )
        )
    return specs


def _provider_record(
    spec: ProbeSpec,
    *,
    available: bool | None,
    status: str,
    checked_at: str,
    ttl_seconds: int,
) -> dict[str, object]:
    # This is the complete persisted provider allowlist.  In particular, no
    # adapter URL, exception text, response text, or credential can enter it.
    return {
        "provider": spec.provider,
        "operation": spec.operation.value,
        "configured": spec.configured,
        "available": available,
        "model": spec.model,
        "status": status,
        "checked_at": checked_at,
        "ttl_seconds": ttl_seconds,
    }


def _safe_attestation(
    raw: Mapping[str, object] | None,
    *,
    model: str,
    now: datetime,
) -> dict[str, object] | None:
    if not isinstance(raw, Mapping):
        return None
    candidate = {name: raw.get(name) for name in _SAFE_ATTESTATION_FIELDS}
    if not vision_attestation_is_valid(candidate, model=model, now=now):
        return None
    return candidate


def _derived_vision_record(attestation: Mapping[str, object]) -> dict[str, object]:
    return {
        "provider": "deepseek",
        "operation": Operation.VISION.value,
        "configured": True,
        "available": True,
        "model": attestation["model"],
        "status": "healthy",
        "checked_at": attestation["checked_at"],
        "ttl_seconds": attestation["ttl_seconds"],
    }


def _normalize_probe_result(value: ProbeResult | AdapterResponse) -> ProbeResult:
    if isinstance(value, ProbeResult):
        result = value
    elif isinstance(value, AdapterResponse):
        result = ProbeResult(response=value)
    else:
        raise ProviderCallError(ProviderErrorClass.UNKNOWN)
    if not isinstance(result.response, AdapterResponse):
        raise ProviderCallError(ProviderErrorClass.UNKNOWN)
    if not isinstance(result.response.text, str) or not result.response.text.strip():
        raise ProviderCallError(ProviderErrorClass.EMPTY, usage=result.response.usage)
    return result


def _classify_probe_exception(exc: Exception) -> ProviderErrorClass:
    """Use the central classifier while keeping HTTP 402 fail-closed and safe."""
    if isinstance(exc, ProviderCallError):
        return exc.error_class
    try:
        response = getattr(exc, "response", None)
        status = getattr(exc, "status_code", None) or getattr(
            response, "status_code", None
        )
    except Exception:
        return ProviderErrorClass.UNKNOWN
    # ``providers.classify_exception`` historically used a misspelled enum
    # member for this branch.  Keep the health contract stable without changing
    # or bypassing the classifier for any other provider failure.
    if status == 402:
        return ProviderErrorClass.INSUFFICIENT_BALANCE
    try:
        return classify_exception(exc)
    except Exception:
        return ProviderErrorClass.UNKNOWN


def _call_adapter(spec: ProbeSpec, adapters: Mapping[str, ProviderAdapter]) -> AdapterResponse:
    adapter = adapters.get(spec.provider)
    if adapter is None:
        raise ProviderCallError(ProviderErrorClass.CLIENT_UNAVAILABLE)
    return adapter.generate(
        spec.request,
        model=spec.model,
        max_output_tokens=_MAX_OUTPUT_TOKENS,
    )


def _record_probe_attempt(
    spec: ProbeSpec,
    *,
    recorder: AttemptRecorder | None,
    checked_at: str,
    latency_ms: float,
    usage: TokenUsage,
    error_class: ProviderErrorClass | None,
) -> bool:
    if recorder is None:
        return False
    attempt = ProviderAttempt(
        request_id=spec.request.request_id or f"llm-health-{spec.provider}",
        run_id=spec.request.run_id,
        provider=spec.provider,
        model=spec.model,
        endpoint="health.adapter.generate",
        operation=spec.operation,
        attempt_number=1,
        event_ts_utc=checked_at,
        selected=error_class is None,
        status="success" if error_class is None else "failed",
        latency_ms=latency_ms,
        max_output_tokens=_MAX_OUTPUT_TOKENS,
        usage=usage,
        error_class=error_class,
        fallback_from=None,
        fallback_reason=None,
        breaker_state="closed",
        cache_hit=False,
        caller_endpoint=_CALLER_ENDPOINT,
    )
    try:
        result = recorder(attempt)
    except Exception:
        # A local telemetry failure must not cause a second external probe.  The
        # snapshot still truthfully represents the one physical call just made.
        return False
    # Existing recorders such as ``list.append`` return None.  Only an explicit
    # False means the idempotent ledger insert did not account for this probe.
    return result is not False


def _activation(
    providers: list[dict[str, object]], *, live: bool, telemetry_complete: bool = True
) -> dict[str, object]:
    if not live:
        return {"ready": False, "status": "blocked", "reason": "live_probe_required"}
    if not telemetry_complete:
        return {
            "ready": False,
            "status": "blocked",
            "reason": "health_accounting_unavailable",
        }
    decisive = next(
        item
        for item in providers
        if item["provider"] == "deepseek"
        and item["operation"] == Operation.DECISIVE_TEXT.value
    )
    if decisive["configured"] is not True:
        reason = "deepseek_decisive_unconfigured"
    elif decisive["available"] is not True or decisive["status"] != "healthy":
        reason = "deepseek_decisive_unhealthy"
    else:
        return {
            "ready": True,
            "status": "ready",
            "reason": "deepseek_decisive_healthy",
        }
    return {"ready": False, "status": "blocked", "reason": reason}


def run_health_check(
    *,
    live: bool = False,
    adapters: Mapping[str, ProviderAdapter] | None = None,
    probe: Probe | None = None,
    attempt_recorder: AttemptRecorder | None | object = _DEFAULT_RECORDER,
    snapshot_path: str | Path = HEALTH_SNAPSHOT_PATH,
    now: datetime | None = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> dict[str, object]:
    """Return a secret-free report and persist it only for explicit live mode."""
    ttl = _validated_ttl(ttl_seconds)
    current = _utc_now(now)
    checked_at = current.isoformat()
    if adapters is not None and probe is not None:
        raise ValueError("pass adapters or probe, not both")

    specs = _provider_specs()
    provider_records: list[dict[str, object]] = []
    accepted_attestation: dict[str, object] | None = None
    telemetry_complete = True

    if not live:
        for spec in specs:
            provider_records.append(
                _provider_record(
                    spec,
                    available=None if spec.configured else False,
                    status="unknown" if spec.configured else "unavailable",
                    checked_at=checked_at,
                    ttl_seconds=ttl,
                )
            )
    else:
        configured_specs = [spec for spec in specs if spec.configured]
        active_adapters: Mapping[str, ProviderAdapter] = {}
        if probe is None and configured_specs:
            active_adapters = adapters if adapters is not None else build_default_adapters()
        recorder = (
            record_attempt if attempt_recorder is _DEFAULT_RECORDER else attempt_recorder
        )
        for spec in specs:
            if not spec.configured:
                provider_records.append(
                    _provider_record(
                        spec,
                        available=False,
                        status="unavailable",
                        checked_at=checked_at,
                        ttl_seconds=ttl,
                    )
                )
                continue

            started = time.monotonic()
            usage = TokenUsage.unknown()
            error_class: ProviderErrorClass | None = None
            outcome: ProbeResult | None = None
            try:
                raw_result = probe(spec) if probe is not None else _call_adapter(spec, active_adapters)
                outcome = _normalize_probe_result(raw_result)
                usage = outcome.response.usage
                available = True
                status = "healthy"
            except Exception as exc:
                error_class = _classify_probe_exception(exc)
                if isinstance(exc, ProviderCallError):
                    usage = exc.usage
                available = False
                status = _ERROR_STATUS.get(error_class, "unknown")
            latency_ms = round(max(0.0, (time.monotonic() - started) * 1_000), 3)
            provider_records.append(
                _provider_record(
                    spec,
                    available=available,
                    status=status,
                    checked_at=checked_at,
                    ttl_seconds=ttl,
                )
            )
            recorded = _record_probe_attempt(
                spec,
                recorder=recorder if callable(recorder) else None,
                checked_at=checked_at,
                latency_ms=latency_ms,
                usage=usage,
                error_class=error_class,
            )
            telemetry_complete = recorded and telemetry_complete

            if (
                spec.provider == "deepseek"
                and available
                and outcome is not None
                and outcome.vision_attestation is not None
            ):
                vision_model = str(
                    policy_for(Operation.VISION).models.get("deepseek_vision") or ""
                )
                if vision_model:
                    accepted_attestation = _safe_attestation(
                        outcome.vision_attestation,
                        model=vision_model,
                        now=current,
                    )

        if accepted_attestation is not None:
            provider_records.append(_derived_vision_record(accepted_attestation))

    report: dict[str, object] = {
        "schema_version": HEALTH_SCHEMA_VERSION,
        "service": "ai-routing-health",
        "mode": "live" if live else "offline",
        "checked_at": checked_at,
        "ttl_seconds": ttl,
        "providers": provider_records,
        "cost_saving_activation": _activation(
            provider_records,
            live=live,
            telemetry_complete=telemetry_complete,
        ),
    }
    if live:
        report["telemetry"] = {
            "complete": telemetry_complete,
            "status": "complete" if telemetry_complete else "unavailable",
        }
    if accepted_attestation is not None:
        report["vision_attestation"] = accepted_attestation
    if live:
        write_json_atomic(str(Path(snapshot_path)), report, sort_keys=True)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="perform one direct probe per configured vendor and persist health.json",
    )
    parser.add_argument(
        "--snapshot",
        default=str(HEALTH_SNAPSHOT_PATH),
        help="live snapshot destination (offline mode never writes it)",
    )
    parser.add_argument("--ttl-seconds", type=int, default=DEFAULT_TTL_SECONDS)
    args = parser.parse_args(argv)
    report = run_health_check(
        live=args.live,
        snapshot_path=args.snapshot,
        ttl_seconds=args.ttl_seconds,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if args.live and report["cost_saving_activation"]["ready"] is not True:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

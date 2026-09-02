"""Replay-safe, symbol-scoped evidence packets for compact AI analysis."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping

SCHEMA_VERSION = "mirofish.evidence.v1"
PROMPT_VERSION = "compact.v1"


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _source_record(raw: Mapping[str, Any]) -> dict[str, Any]:
    fetched_at = str(raw.get("fetched_at") or raw.get("observed_at") or "").strip()
    source = str(raw.get("source") or raw.get("source_type") or "").strip()
    evidence_id = str(raw.get("evidence_id") or raw.get("id") or "").strip()
    content = raw.get("content") if isinstance(raw.get("content"), Mapping) else {
        "source": source, "fetched_at": fetched_at,
        "freshness": raw.get("freshness"), "confidence": raw.get("confidence"),
        "text": raw.get("text"), "title": raw.get("title"), "metadata": raw.get("metadata"),
    }
    return {
        "evidence_id": evidence_id or _sha(content)[:16],
        "source": source,
        "fetched_at": fetched_at,
        "freshness": raw.get("freshness") or "unknown",
        "confidence": raw.get("confidence"),
        "content_fingerprint": _sha(content),
        "source_type": str(raw.get("source_type") or source),
        "title": str(raw.get("title") or evidence_id or source),
        "content": deepcopy(content),
    }


def _first_present(*values: Any) -> Any:
    return next((value for value in values if value is not None), None)


def _timestamp(value: str) -> datetime:
    clean = str(value or "").strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(clean)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def build_evidence_packet(
    candidate: Mapping[str, Any], *, profile: str = "compact",
    models: Mapping[str, str] | None = None,
    schema_version: str = SCHEMA_VERSION, prompt_version: str = PROMPT_VERSION,
    deterministic_scores: Mapping[str, Any] | None = None,
    risk_gates: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a canonical value whose fingerprint excludes transient generation time."""
    symbol = str(candidate.get("symbol") or candidate.get("code") or "").strip()
    name = str(candidate.get("name") or candidate.get("display_name") or "").strip()
    market = str(candidate.get("market") or "").strip()
    price = candidate.get("price") if isinstance(candidate.get("price"), Mapping) else {}
    as_of = str(candidate.get("as_of") or candidate.get("observed_at") or price.get("date") or "").strip()
    missing = [key for key, value in (("symbol", symbol), ("name", name), ("market", market), ("as_of", as_of)) if not value]
    if missing:
        raise ValueError(f"evidence packet missing required fields: {','.join(missing)}")

    raw_sources = candidate.get("source_packets") or candidate.get("sources") or []
    if not isinstance(raw_sources, list):
        raw_sources = []
    if not raw_sources:
        raise ValueError("evidence packet requires explicit provenance")
    sources = [_source_record(source) for source in raw_sources if isinstance(source, Mapping)]
    if not sources or any(not source["source"] or not source["fetched_at"] for source in sources):
        raise ValueError("evidence packet requires complete provenance")
    try:
        cutoff = _timestamp(as_of)
        if any(_timestamp(source["fetched_at"]) > cutoff for source in sources):
            raise ValueError("source fetched_at is after as_of")
    except ValueError as exc:
        if "after as_of" in str(exc):
            raise
        raise ValueError("evidence packet provenance timestamp is invalid") from exc
    sources.sort(key=lambda item: (item["source"], item["evidence_id"]))
    numeric_inputs = {
        "current_price": _first_present(price.get("current_price"), price.get("price"), candidate.get("current_price"), (
            candidate.get("price") if not isinstance(candidate.get("price"), Mapping) else None
        )),
        "change_pct": _first_present(price.get("change_rate"), price.get("change_pct"), candidate.get("change_rate"), candidate.get("change_pct")),
        "volume": _first_present(price.get("volume"), candidate.get("volume")), "alpha_score": candidate.get("alpha_score"),
        "risk_score": candidate.get("risk_score"),
    }
    scores = dict(deterministic_scores or {}) or {
        "alpha": candidate.get("alpha_score"), "risk": candidate.get("risk_score"),
        "trend": (candidate.get("trend") or {}).get("trend_score")
        if isinstance(candidate.get("trend"), Mapping) else None,
        "relative_strength": candidate.get("rs_rating"),
    }
    packet = {
        "symbol": symbol, "name": name, "market": market, "as_of": as_of,
        "sources": sources, "evidence_ids": [source["evidence_id"] for source in sources],
        "numeric_inputs": numeric_inputs, "deterministic_scores": scores,
        "risk_gates": dict(risk_gates or candidate.get("risk_gates") or {}),
        "risk_flags": list(candidate.get("risk_flags") or []),
        "invalidation_conditions": list(candidate.get("invalidation_conditions") or []),
        "chart_analysis": deepcopy(candidate.get("chart_analysis")),
        "allowed_verdicts": ["STRONG_BUY", "BUY", "HOLD", "SELL"],
        "schema_version": str(schema_version), "prompt_version": str(prompt_version),
        "profile": str(profile), "models": dict(models or {}),
        "cache_eligible": bool(sources),
    }
    packet["fingerprint"] = _sha(packet)
    return packet


def cache_key(packet: Mapping[str, Any]) -> str:
    return _sha({key: packet.get(key) for key in (
        "symbol", "as_of", "fingerprint", "profile", "models", "prompt_version", "schema_version"
    )})


canonical_evidence_packet = build_evidence_packet

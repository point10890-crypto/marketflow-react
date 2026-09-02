"""Replay-safe, symbol-scoped evidence packets for compact AI analysis."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Mapping

SCHEMA_VERSION = "mirofish.evidence.v1"
PROMPT_VERSION = "compact.v1"


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _source_record(raw: Mapping[str, Any], fallback_source: str, fallback_time: str) -> dict[str, Any]:
    fetched_at = str(raw.get("fetched_at") or raw.get("observed_at") or fallback_time).strip()
    source = str(raw.get("source") or raw.get("source_type") or fallback_source).strip()
    evidence_id = str(raw.get("evidence_id") or raw.get("id") or "").strip()
    content = {
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
    }


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
    fallback_source = str(candidate.get("source") or "").strip()
    if not raw_sources and fallback_source:
        freshness = candidate.get("source_freshness") or {}
        raw_sources = [{
            "source": fallback_source, "observed_at": as_of,
            "freshness": freshness.get("status") if isinstance(freshness, Mapping) else "unknown",
            "confidence": candidate.get("source_confidence"),
            "text": {"price": candidate.get("current_price") or candidate.get("price"),
                     "change_pct": candidate.get("change_rate") or candidate.get("change_pct"),
                     "volume": candidate.get("volume")},
        }]
    sources = [_source_record(source, fallback_source, as_of) for source in raw_sources if isinstance(source, Mapping)]
    sources.sort(key=lambda item: (item["source"], item["evidence_id"]))
    numeric_inputs = {
        "current_price": candidate.get("current_price") or price.get("current_price") or (
            candidate.get("price") if not isinstance(candidate.get("price"), Mapping) else None
        ),
        "change_pct": candidate.get("change_rate") or candidate.get("change_pct"),
        "volume": candidate.get("volume"), "alpha_score": candidate.get("alpha_score"),
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

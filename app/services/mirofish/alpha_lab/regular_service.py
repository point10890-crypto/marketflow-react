"""Compose the regular-session Candidate Desk without changing the v4 desk."""
from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from pathlib import Path
import threading

from filelock import FileLock, Timeout

from . import candidate_service, candidate_store, regular_inputs, store
from .desk_selection import directory as select_directory

ROOT = candidate_service.ROOT
DESK_DIRECTORY = regular_inputs.DESK_DIRECTORY
save_desk_evidence = candidate_service.save_desk_evidence

def _canonical_scope(root):
    directory = root / "inputs"
    pointer = store._read(directory / "current.json")
    attempt = store._read(directory / "last_attempt.json")
    if (not isinstance(pointer, dict) or not isinstance(attempt, dict)
            or attempt.get("status") != "complete" or not pointer.get("snapshot_id")
            or attempt.get("snapshot_id") != pointer["snapshot_id"]):
        raise regular_inputs.RegularInputError("regular_inputs_baseline")
    return pointer["snapshot_id"], pointer["latest_session"], pointer["hashes"]["universe_report"]


def _acquire(root, *, now=None, provider=None):
    scope = _canonical_scope(root)
    inputs = regular_inputs.collect_inputs(root, now=now, provider=provider, expected_scope=scope[1:])
    if _canonical_scope(root) != scope:
        raise regular_inputs.RegularInputError("regular_inputs_stale")
    return inputs


def _analysis(directory, inputs):
    code_hash = candidate_store._code_hash()
    identity = inputs["input_fingerprint"]
    source_hash = inputs["provenance"]["source_contract_hash"]
    path = directory / "runs" / f"{inputs['latest_session']}-{identity[:24]}-{code_hash[:24]}.json"
    binding = dict(code_hash=code_hash, input_fingerprint=identity, source_contract_hash=source_hash)
    saved = candidate_store._load(path)
    if saved is None:
        result = candidate_service._detect(inputs)
        candidate_store._save(path, dict(binding=binding, result=result))
        return result
    if saved["binding"] != binding:
        raise ValueError("regular_analysis_integrity")
    return saved["result"]


def _entry(calendar_provider, now):
    try:
        current = candidate_store._clock(now)
        provider = calendar_provider or candidate_service.KISMarketProvider()
        calendar = provider.fetch_calendar(current.astimezone(candidate_store.KST).date().isoformat(), now=now)
        moment = store.timestamp(now)
        return moment, candidate_service._entry(calendar, candidate_store._clock(moment))
    except Exception:
        return store.timestamp(now), (None, None)


def _desk(inputs, result, moment, entry, expiry):
    provenance = inputs["provenance"]
    return dict(
        schema_version=1, policy_version=candidate_store.POLICY,
        state="ready" if result["candidates"] else "held", input_fingerprint=inputs["input_fingerprint"],
        generated_at=moment, latest_session=inputs["latest_session"], entry_session=entry, valid_until=expiry,
        source=dict(provider="KIS", venue="KRX", adjusted_requested=True,
                    captured_at=provenance["captured_at"], source_contract_hash=provenance["source_contract_hash"],
                    acquisition_policy=regular_inputs.ACQUISITION_POLICY,
                    regular_session_verified=True, price_basis=regular_inputs.PRICE_BASIS,
                    volume_basis=regular_inputs.VOLUME_BASIS, historical_vintage_verified=False,
                    corporate_action_adjustment_verified=False),
        candidates=deepcopy(result["candidates"]), funnel=deepcopy(result["funnel"]),
        evidence=deepcopy(result["evidence"]), reasons=list(dict.fromkeys(result.get("reasons", []))),
        model=deepcopy(result["model"]), approved_exposure=0., live_orders=False,
    )


def refresh_desk(root=None, *, now=None, provider=None, calendar_provider=None):
    root = Path(root) if root is not None else ROOT
    directory = root / DESK_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(directory / "refresh.lock"))
    try:
        with lock.acquire(timeout=0):
            candidate_store.set_attempt(directory, "running", now=now)
            error = "source_unavailable"
            try:
                inputs = _acquire(root, now=now, provider=provider)
                latest = inputs["latest_session"]
                if any(row["desk"]["latest_session"] > latest
                       for row in candidate_store.read_decisions(directory)["records"]):
                    raise regular_inputs.RegularInputError("regular_inputs_stale")
                error = "analysis_unavailable"
                result = _analysis(directory, inputs)
                moment, (entry, expiry) = _entry(calendar_provider, now)
                if entry is None:
                    error = "calendar_unavailable"
                    raise ValueError(error)
                candidate_store.publish(directory, _desk(inputs, result, moment, entry, expiry), inputs, now=moment)
                candidate_store.set_attempt(directory, "complete", now=moment)
            except Exception:
                candidate_store.set_attempt(directory, "failed", now=now, error=error)
            return candidate_store.read_public(directory, now=now)
    except Timeout:
        return candidate_store.read_public(directory, now=now)


def read_status(*, now=None):
    directory = select_directory(ROOT)
    if directory.name == "candidate-desk" and ROOT == candidate_service.ROOT:
        return candidate_service.read_status(now=now)
    result = dict(candidate_service._legacy_read(ROOT, now=now))
    result.pop("candidate_desk", None)
    result.pop("candidate_desk_unavailable", None)
    desk = candidate_store.read_public(directory, now=now)
    if desk is not None:
        from .candidate_monitor import read_view
        desk["monitoring"] = read_view(ROOT, desk, now=now)
        result["candidate_desk"] = desk
    elif directory.name == DESK_DIRECTORY or (directory / "attempt.json").exists():
        result["candidate_desk_unavailable"] = True
    try:
        attempt = candidate_store._load(directory / "attempt.json") or {}
        age = candidate_store._clock(now) - candidate_store._clock(attempt["at"])
        if attempt.get("state") == "running" and timedelta(0) <= age <= timedelta(minutes=20):
            result["state"] = "running"
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return result


def _scan(root, *, desk_only):
    directory = root / DESK_DIRECTORY
    candidate_store.set_attempt(directory, "running")
    try:
        previous = candidate_service.scan_once(root, desk_only=desk_only)
        legacy_desk = previous.get("candidate_desk") or {}
        legacy_attempt = candidate_store._load(root / "candidate-desk" / "attempt.json") or {}
        if (previous.get("state") in ("ready", "held")
                and legacy_desk.get("state") in ("ready", "held")
                and legacy_attempt.get("state") == "complete"):
            desk = refresh_desk(root)
            previous.pop("candidate_desk", None)
            previous.pop("candidate_desk_unavailable", None)
            return dict(previous, candidate_desk=desk) if desk is not None else dict(
                previous, candidate_desk_unavailable=True)
    except Exception:
        previous = dict(state="failed", error="scan_unavailable")
    candidate_store.set_attempt(directory, "failed", error="source_unavailable")
    previous.pop("candidate_desk", None)
    return dict(previous, candidate_desk_unavailable=True)


def scan_once(root=None, *, desk_only=False):
    root = Path(root) if root is not None else ROOT
    lock = FileLock(str(root / "regular-compose.lock"))
    try:
        with lock.acquire(timeout=0):
            return _scan(root, desk_only=desk_only)
    except Timeout:
        return dict(candidate_service._legacy_read(root), state="running")


def start_scan():
    root = ROOT
    lock = FileLock(str(root / "regular-compose.lock"), thread_local=False)
    try:
        lock.acquire(timeout=0)
    except Timeout:
        return dict(read_status(), state="running")

    def run():
        try:
            _scan(root, desk_only=False)
        finally:
            lock.release()

    try:
        candidate_store.set_attempt(root / DESK_DIRECTORY, "running")
        threading.Thread(target=run, name="alpha-regular-candidate-research", daemon=True).start()
    except Exception:
        lock.release()
        candidate_store.set_attempt(root / DESK_DIRECTORY, "failed", error="analysis_unavailable")
        return read_status()
    return dict(read_status(), state="running")

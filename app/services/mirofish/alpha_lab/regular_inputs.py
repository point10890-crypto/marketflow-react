"""Replayable regular-session overlay over the sealed candidate daily inputs."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path

from filelock import FileLock, Timeout

from . import candidate_inputs as daily, regular_source
from .daily_source import _clock, _cutoff, _session, _symbol

DESK_DIRECTORY = "candidate-regular-v1"
PRICE_BASIS = "KRX_regular_0900_1530_OHLC"
VOLUME_BASIS = "KIS_published_daily"
ACQUISITION_POLICY = "krx-regular-ohlc-v1"
PRICE_FIELDS = ("open", "high", "low", "close")
_CAPTURE_FIELDS = (*PRICE_FIELDS, "volume", "traded_value")


class RegularInputError(ValueError):
    def __init__(self, code, *, failures=None):
        self.code = code
        self.failures = dict(failures or {})
        self.failed_symbols = sorted(self.failures)
        super().__init__(code)


def source_contract():
    directory = Path(__file__).parent
    implementations = ("regular_source.py", "regular_inputs.py", "regular_service.py")
    return dict(
        policy=ACQUISITION_POLICY,
        regular_source=deepcopy(regular_source.SOURCE_CONTRACT),
        daily_source=deepcopy(daily.SOURCE_CONTRACT),
        price_basis=PRICE_BASIS,
        volume_basis=VOLUME_BASIS,
        implementation={name: hashlib.sha256((directory / name).read_bytes().replace(
            b"\r\n", b"\n")).hexdigest() for name in implementations},
    )


def _paths(alpha_root):
    root = Path(alpha_root)
    return root / DESK_DIRECTORY / "inputs", root / "candidate-desk" / "inputs"


def _now(now):
    return _clock(datetime.now(timezone.utc) if now is None else now)


def _read(path):
    try:
        return daily._read(path)
    except daily.CandidateInputError:
        raise RegularInputError("regular_inputs_integrity") from None


def _spec(baseline):
    provenance = baseline["provenance"]
    contract = source_contract()
    session = _session(baseline["latest_session"])
    symbols = sorted(_symbol(symbol) for symbol in baseline["names"])
    if (not daily._digest(provenance["snapshot_id"])
            or not daily._digest(provenance["scope_hash"])
            or not daily._digest(baseline["input_fingerprint"])
            or not 1 <= len(symbols) <= 100
            or set(symbols) != set(baseline["prices_by_symbol"])
            or any(not rows or rows[-1]["date"] != session
                   for rows in baseline["prices_by_symbol"].values())):
        raise RegularInputError("regular_inputs_baseline")
    return dict(baseline_snapshot=provenance["snapshot_id"],
                baseline_input_fingerprint=baseline["input_fingerprint"],
                scope_hash=provenance["scope_hash"], symbols=symbols, latest_session=session,
                source_contract=contract, source_contract_hash=daily._hash(contract))


def _replay_object(root, digest, symbol, session, upper):
    if not daily._digest(digest):
        raise RegularInputError("regular_inputs_integrity")
    value = _read(root / "objects" / f"{digest}.json")
    try:
        result = regular_source.replay(value, symbol, session, upper)
        if daily._hash(value) != digest or result != value:
            raise ValueError()
        return result
    except (ValueError, TypeError, KeyError, OverflowError):
        raise RegularInputError("regular_inputs_integrity") from None


def _assemble(baseline, spec, objects, references):
    result = deepcopy(baseline)
    audit = {}
    for symbol in spec["symbols"]:
        value = objects[symbol]
        latest = result["prices_by_symbol"][symbol][-1]
        original = deepcopy(latest)
        latest.update({field: value["bar"][field] for field in PRICE_FIELDS})
        audit[symbol] = dict(original_daily=original, regular_bar=deepcopy(value["bar"]),
                             differences={field: dict(daily=original[field], regular=value["bar"][field])
                                          for field in _CAPTURE_FIELDS
                                          if original[field] != value["bar"][field]})
    result["regular_audit"] = audit
    result["capture_audit"] = {symbol: objects[symbol]["capture"] for symbol in spec["symbols"]}
    result["provenance"].update(
        snapshot_version=ACQUISITION_POLICY, snapshot_id=daily._hash(spec),
        source_contract=spec["source_contract"], source_contract_hash=spec["source_contract_hash"],
        symbols_hash=daily._hash(dict(symbols=spec["symbols"], scope=spec["scope_hash"])),
        symbol_hashes=references, captured_at=max((obj["captured_at"] for obj in objects.values()), key=_clock),
        baseline_snapshot=spec["baseline_snapshot"], baseline_input_fingerprint=spec["baseline_input_fingerprint"],
        regular_session_verified=True, price_basis=PRICE_BASIS, volume_basis=VOLUME_BASIS,
    )
    result.pop("input_fingerprint")
    result["input_fingerprint"] = daily._hash(result)
    return result


def _load_snapshot(root, identity, baseline, spec, upper):
    if not daily._digest(identity) or identity != daily._hash(spec):
        raise RegularInputError("regular_inputs_integrity")
    saved = _read(root / "snapshots" / f"{identity}.json")
    references = saved.get("objects")
    if (saved.get("spec") != spec or not isinstance(references, dict)
            or set(references) != set(spec["symbols"])):
        raise RegularInputError("regular_inputs_integrity")
    objects = {symbol: _replay_object(root, references[symbol], symbol, spec["latest_session"], upper)
               for symbol in spec["symbols"]}
    result = _assemble(baseline, spec, objects, references)
    if (saved.get("input_fingerprint") != result["input_fingerprint"]
            or saved.get("regular_audit") != result["regular_audit"]):
        raise RegularInputError("regular_inputs_integrity")
    return result


def _pointer_result(root, baseline_root, pointer, baseline, spec, upper):
    identity = pointer.get("snapshot_id")
    if not daily._digest(identity) or not daily._digest(pointer.get("baseline_snapshot")):
        raise RegularInputError("regular_inputs_integrity")
    if pointer["baseline_snapshot"] != spec["baseline_snapshot"]:
        # A new daily publication can supersede a valid older overlay. Replay it
        # from its original daily snapshot before replacing the complete pointer.
        try:
            baseline = daily._load_snapshot(baseline_root, pointer["baseline_snapshot"], upper=upper)
            spec = _spec(baseline)
        except (ValueError, TypeError, KeyError):
            raise RegularInputError("regular_inputs_integrity") from None
    result = _load_snapshot(root, identity, baseline, spec, upper)
    if pointer.get("input_fingerprint") != result["input_fingerprint"]:
        raise RegularInputError("regular_inputs_integrity")
    return result


def load_inputs(alpha_root, *, now=None):
    """Replay the current pointer and both evidence layers with no provider calls."""
    root, baseline_root = _paths(alpha_root)
    upper = _now(now)
    baseline = daily.load_inputs(baseline_root)
    spec = _spec(baseline)
    pointer = _read(root / "current.json")
    if pointer.get("baseline_snapshot") != spec["baseline_snapshot"]:
        raise RegularInputError("regular_inputs_stale")
    return _pointer_result(root, baseline_root, pointer, baseline, spec, upper)


def _collect_objects(root, spec, provider, now):
    session = spec["latest_session"]
    directory = root / "epochs" / spec["source_contract_hash"] / session
    objects, references, failures = {}, {}, {}
    for symbol in spec["symbols"]:
        slot = directory / f"{symbol}.json"
        if slot.exists():
            ref = _read(slot)
            if set(ref) != {"sha256"}:
                raise RegularInputError("regular_inputs_integrity")
            digest = ref["sha256"]
            value = _replay_object(root, digest, symbol, session, _now(now))
        else:
            lower = _now(now)
            try:
                raw = provider.fetch_session(symbol, session)
                value = regular_source.replay(raw, symbol, session, _now(now))
                if not _cutoff(session) <= lower <= _clock(value["capture"]["first"]):
                    raise RegularInputError("regular_inputs_capture")
            except regular_source.RegularSourceError as exc:
                failures[symbol] = regular_source.RegularSourceError(exc.code).code
                continue
            except RegularInputError as exc:
                failures[symbol] = exc.code
                continue
            except Exception:
                failures[symbol] = "regular_inputs_provider"
                continue
            digest = daily._hash(value)
            path = root / "objects" / f"{digest}.json"
            if path.exists():
                _replay_object(root, digest, symbol, session, _now(now))
            else:
                daily._write(path, value)
            daily._write(slot, dict(sha256=digest))
        objects[symbol], references[symbol] = value, digest
    daily._write(directory / "attempt.json", dict(failures=failures, objects=references))
    if failures:
        raise RegularInputError("regular_inputs_incomplete", failures=failures)
    return objects, references


def collect_inputs(alpha_root, *, now=None, provider=None, expected_scope=None):
    """Acquire missing regular evidence and atomically publish only full replay."""
    root, baseline_root = _paths(alpha_root)
    root.mkdir(parents=True, exist_ok=True)
    try:
        with FileLock(str(root / "acquisition.lock"), timeout=1):
            baseline = daily.load_inputs(baseline_root)
            spec = _spec(baseline)
            if expected_scope is not None and expected_scope != (spec["latest_session"], spec["scope_hash"]):
                raise RegularInputError("regular_inputs_stale")
            identity = daily._hash(spec)
            upper = _now(now)
            cutoff = _cutoff(spec["latest_session"])
            if upper < cutoff:
                raise RegularInputError("regular_inputs_session_incomplete")
            if upper - cutoff > timedelta(hours=72):
                raise RegularInputError("regular_inputs_stale")
            pointer_path = root / "current.json"
            if pointer_path.exists():
                pointer = _read(pointer_path)
                current = _pointer_result(root, baseline_root, pointer, baseline, spec, upper)
                if pointer["snapshot_id"] == identity:
                    return current
            manifest_path = root / "snapshots" / f"{identity}.json"
            if manifest_path.exists():
                result = _load_snapshot(root, identity, baseline, spec, upper)
            else:
                objects, references = _collect_objects(root, spec, provider or regular_source.KISRegularProvider(), now)
                result = _assemble(baseline, spec, objects, references)
                daily._write(manifest_path, dict(spec=spec, objects=references, regular_audit=result["regular_audit"],
                                               input_fingerprint=result["input_fingerprint"]))
            if _read(baseline_root / "current.json").get("snapshot_id") != spec["baseline_snapshot"]:
                raise RegularInputError("regular_inputs_stale")
            daily._write(pointer_path, dict(snapshot_id=identity, baseline_snapshot=spec["baseline_snapshot"],
                                          input_fingerprint=result["input_fingerprint"]))
            return result
    except Timeout:
        raise RegularInputError("regular_inputs_busy") from None

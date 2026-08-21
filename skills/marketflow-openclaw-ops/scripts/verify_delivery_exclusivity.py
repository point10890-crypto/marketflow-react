"""Verify the sanitized environment boundary for one verified Telegram send."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any


DEFAULT_ENV_PATH = Path(__file__).resolve().parents[3] / ".env"
TRANSPORT_TRUE = frozenset({"1", "true", "yes", "y", "on"})
TRANSPORT_FALSE = frozenset({"0", "false", "no", "n", "off"})
DRY_RUN_TRUE = frozenset({"1", "true", "yes", "on"})
DRY_RUN_FALSE = frozenset({"0", "false", "no", "off"})
FLAG_POLICY = (
    (
        "ALPHA_SCANNER_TELEGRAM_ENABLED",
        False,
        False,
        TRANSPORT_TRUE,
        TRANSPORT_FALSE,
    ),
    (
        "MIROFISH_WORKFLOW_TELEGRAM_ENABLED",
        False,
        False,
        TRANSPORT_TRUE,
        TRANSPORT_FALSE,
    ),
    (
        "ALPHA_SCANNER_CURRENT_TELEGRAM_ENABLED",
        False,
        False,
        TRANSPORT_TRUE,
        TRANSPORT_FALSE,
    ),
    (
        "MIROFISH_AUTO_RUNNER_DRY_RUN",
        True,
        True,
        DRY_RUN_TRUE,
        DRY_RUN_FALSE,
    ),
)


def verify_delivery_exclusivity(
    *,
    env_file: str | os.PathLike[str] = DEFAULT_ENV_PATH,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return only resolved booleans and their non-sensitive source labels."""
    process_env = os.environ if environ is None else environ
    try:
        dotenv = _read_flag_values(Path(env_file))
    except (OSError, UnicodeError):
        return {
            "ok": False,
            "status": "environment_unreadable",
            "flags": {},
        }

    flags: dict[str, dict[str, Any]] = {}
    safe = True
    invalid = False
    for name, default, required, truthy, falsy in FLAG_POLICY:
        if name in process_env:
            raw = process_env.get(name)
            source = "process"
        elif name in dotenv:
            raw = dotenv[name]
            source = "dotenv"
        else:
            raw = None
            source = "default"
        if raw is None:
            resolved: bool | None = default
        else:
            normalized = str(raw).strip().lower()
            if normalized in truthy:
                resolved = True
            elif normalized in falsy:
                resolved = False
            else:
                resolved = None
                invalid = True
        flags[name] = {"resolved": resolved, "source": source}
        safe = safe and resolved is required

    return {
        "ok": safe and not invalid,
        "status": (
            "invalid_flag_value"
            if invalid
            else "verified_exclusive"
            if safe
            else "unsafe_delivery_environment"
        ),
        "flags": flags,
    }


def _read_flag_values(path: Path) -> dict[str, str | None]:
    if not path.is_file():
        return {}
    allowed = {
        name
        for name, _default, _required, _truthy, _falsy in FLAG_POLICY
    }
    values: dict[str, str | None] = {}
    with path.open("r", encoding="utf-8-sig") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            key, separator, raw_value = line.partition("=")
            key = key.strip()
            if not separator or key not in allowed:
                continue
            values[key] = _clean_dotenv_value(raw_value)
    return values


def _clean_dotenv_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    if " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_PATH))
    args = parser.parse_args(argv)
    result = verify_delivery_exclusivity(env_file=args.env_file)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())

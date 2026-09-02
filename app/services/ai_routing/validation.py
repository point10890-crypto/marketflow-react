"""Local output validation; provider text never enters telemetry."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from .contracts import ProviderErrorClass, RoutingRequest


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    error_class: ProviderErrorClass | None = None
    parsed: Any = None
    numeric_validation: str = "not_requested"


def _path_value(document: Any, path: str) -> Any:
    value = document
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            raise KeyError(path)
        value = value[part]
    return value


def validate_response(text: str | None, request: RoutingRequest) -> ValidationResult:
    if not text or not text.strip():
        return ValidationResult(False, ProviderErrorClass.EMPTY)
    parsed: Any = None
    if request.json_mode or request.expected_numbers:
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError):
            return ValidationResult(False, ProviderErrorClass.INVALID_JSON)
    if request.expected_numbers:
        try:
            for path, expected in request.expected_numbers.items():
                actual = _path_value(parsed, path)
                if Decimal(str(actual)) != Decimal(str(expected)):
                    return ValidationResult(
                        False,
                        ProviderErrorClass.NUMERIC_MISMATCH,
                        parsed,
                        "failed",
                    )
        except (KeyError, InvalidOperation, TypeError, ValueError):
            return ValidationResult(
                False,
                ProviderErrorClass.NUMERIC_MISMATCH,
                parsed,
                "failed",
            )
        return ValidationResult(True, parsed=parsed, numeric_validation="passed")
    return ValidationResult(True, parsed=parsed)


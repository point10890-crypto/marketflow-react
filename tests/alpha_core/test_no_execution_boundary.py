import ast
from pathlib import Path

import pytest

from app.services.alpha_core import AlphaCoreConfigurationError, resolve_mode


ROOT = Path(__file__).resolve().parents[2] / "app" / "services" / "alpha_core"


def test_alpha_core_has_no_network_or_broker_client_imports():
    forbidden_roots = {
        "requests", "httpx", "aiohttp", "socket", "websocket", "websockets",
        "kis", "pykis", "ccxt", "alpaca_trade_api",
    }
    found = []
    for path in ROOT.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = {alias.name.split(".", 1)[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                roots = {(node.module or "").split(".", 1)[0]}
            else:
                continue
            overlap = roots & forbidden_roots
            if overlap:
                found.append((path.name, sorted(overlap)))
    assert found == []


def test_no_runtime_value_can_enable_real_execution():
    for value in ("live", "real", "production", "broker", "1"):
        with pytest.raises(AlphaCoreConfigurationError):
            resolve_mode(value)

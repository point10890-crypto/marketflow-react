"""Preview the OpenClaw configuration for the read-only MarketFlow Ops Supervisor.

Prints the `mcp.servers.marketflow_ops` entry and the `marketflow-ops` agent
profile. It writes nothing. The existing research agent (`marketflow`, 19
read-only MiroFish tools) is unchanged; applying this profile is a separate,
reviewed step (docs/control_center_design_2026_11_07.md, section 6).

    .venv\\Scripts\\python.exe scripts\\preview_openclaw_ops_agent.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from app.services.control_center.mcp_ops import TOOL_NAMES  # noqa: E402

SERVER_NAME = 'marketflow_ops'
AGENT_ID = 'marketflow-ops'
SKILL = 'marketflow-ops-supervisor'
DENIED_AGENT_TOOLS = ['group:runtime', 'group:fs', 'browser', 'cron', 'gateway', 'message',
                      'sessions_spawn', 'sessions_send', 'subagents']


def python_command(repo: Path) -> Path:
    win = repo / '.venv' / 'Scripts' / 'python.exe'
    return win if os.name == 'nt' or win.exists() else repo / '.venv' / 'bin' / 'python'


def build(repo: Path = REPO) -> dict:
    allowed = [f'{SERVER_NAME}__{n}' for n in TOOL_NAMES]
    return {
        'mcp.servers.' + SERVER_NAME: {
            'command': str(python_command(repo)),
            'args': ['-m', 'app.services.control_center.mcp_ops', '--transport', 'stdio'],
            'cwd': str(repo),
            'env': {'PYTHONIOENCODING': 'utf-8'},
            'connectionTimeoutMs': 20_000, 'requestTimeoutMs': 60_000, 'supportsParallelToolCalls': False,
            'toolFilter': {'include': list(TOOL_NAMES), 'exclude': []},
        },
        'agents.' + AGENT_ID: {
            'name': 'MarketFlow Ops Supervisor',
            'workspace': str(repo / 'integrations' / 'openclaw' / 'ops-workspace'),
            'sandbox': {'mode': 'all', 'scope': 'agent', 'workspaceAccess': 'none'},
            'skills': [SKILL],
            'tools': {'allow': allowed, 'deny': DENIED_AGENT_TOOLS,
                      'sandbox': {'tools': {'alsoAllow': allowed}}},
        },
        'invariants': {
            'ops_tools': len(TOOL_NAMES), 'mutation_tools': 0, 'bindings': 0,
            'research_agent_must_deny': f'{SERVER_NAME}__*',
            'ops_agent_must_deny': 'marketflow__*',
        },
    }


if __name__ == '__main__':
    print(json.dumps(build(), ensure_ascii=False, indent=2))

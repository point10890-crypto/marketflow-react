"""Configure a least-privilege OpenClaw agent for MarketFlow MiroFish.

The default mode is a read-only preview. ``--apply`` performs a fail-closed
preflight, validates one atomic OpenClaw config batch, applies it, and probes the
existing MiroFish stdio server. It never configures a model, channel, daemon,
schedule, Telegram delivery, or order execution.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator


DEFAULT_SERVER_NAME = 'marketflow'
DEFAULT_AGENT_ID = 'marketflow'
DEFAULT_SKILL_NAME = 'marketflow-readonly'
COMMAND_TIMEOUT_SECONDS = 180
BATCH_MARKER = '<transient-batch-file>'

REQUIRED_WORKSPACE_FILES = (
    '.gitignore',
    'AGENTS.md',
    'HEARTBEAT.md',
    'IDENTITY.md',
    'SOUL.md',
    'TOOLS.md',
    'USER.md',
    f'skills/{DEFAULT_SKILL_NAME}/SKILL.md',
)

# Deliberately narrower than the complete MiroFish MCP surface. Each tool is
# observational at the service boundary and is covered by the read-only tests.
READ_ONLY_TOOLS = [
    'get_autonomous_status',
    'get_mcp_security_policy',
    'get_market_clock',
    'get_pipeline_operating_snapshot',
    'get_mcp_resource_snapshot',
    'get_repository_state',
    'list_recent_scanner_runs',
    'get_alpha_research_snapshot',
    'list_recent_workflows',
    'list_safe_artifacts',
    'read_safe_artifact',
    'get_top3_summary',
    'get_alpha_scanner_diagnostics',
    'get_tradingview_provider_status',
    'get_outcomes_kpi',
    'get_pipeline_today_snapshot',
    'get_backtest_summary',
    'resolve_target',
    'search_targets',
]

MUTATING_TOOLS = [
    'run_candidate_detection_alert',
    'run_autonomous_scan_analysis',
    'refresh_learning_feedback',
    'send_latest_workflow_telegram',
    'run_multi_mcp_deep_research',
    'run_multi_mcp_live_market_scan',
]

DENIED_AGENT_TOOLS = [
    'group:runtime',
    'group:fs',
    'browser',
    'cron',
    'gateway',
    'message',
    'sessions_spawn',
    'sessions_send',
    'subagents',
]

_SAFE_ID_RE = re.compile(r'^[a-z][a-z0-9_-]{0,31}$')
_ALLOWED_EXISTING_TARGET_FIELDS = {
    'id',
    'name',
    'workspace',
    'agentDir',
    'sandbox',
    'tools',
    'skills',
}


class ConfigurationAppliedError(RuntimeError):
    """Report a post-write verification failure without hiding applied state."""

    def __init__(self, message: str, *, result: dict[str, Any]):
        super().__init__(message)
        self.result = result


def build_server_config(
    repo_root: Path,
    *,
    agent_id: str = DEFAULT_AGENT_ID,
) -> dict[str, Any]:
    """Return the OpenClaw ``mcp.servers`` entry for local stdio use."""
    repo_root = repo_root.resolve()
    return {
        'command': str(_python_command(repo_root)),
        'args': [
            str(repo_root / 'mirofish_mcp_server.py'),
            '--transport',
            'stdio',
        ],
        'cwd': str(repo_root),
        'env': {
            'PYTHONIOENCODING': 'utf-8',
            'MIROFISH_MCP_ALLOW_MUTATION': 'false',
        },
        'connectionTimeoutMs': 20_000,
        'requestTimeoutMs': 120_000,
        'supportsParallelToolCalls': False,
        'toolFilter': {
            'include': list(READ_ONLY_TOOLS),
            'exclude': list(MUTATING_TOOLS),
        },
        # OpenClaw's normal registry is global. This is an additional Codex
        # projection boundary; non-target OpenClaw agents are denied below.
        'codex': {'agents': [agent_id]},
    }


def build_agent_profile(
    repo_root: Path,
    server_name: str = DEFAULT_SERVER_NAME,
) -> dict[str, Any]:
    """Return the dedicated OpenClaw agent's hard tool and sandbox boundary."""
    repo_root = repo_root.resolve()
    prefix = _safe_server_prefix(server_name)
    allowed_tools = [f'{prefix}__{name}' for name in READ_ONLY_TOOLS]
    return {
        'name': 'MarketFlow Read-Only',
        'workspace': str(repo_root / 'integrations' / 'openclaw' / 'workspace'),
        'sandbox': {
            'mode': 'all',
            'scope': 'agent',
            'workspaceAccess': 'none',
        },
        'skills': [DEFAULT_SKILL_NAME],
        'tools': {
            'allow': allowed_tools,
            'deny': list(DENIED_AGENT_TOOLS),
            'sandbox': {
                'tools': {
                    'alsoAllow': allowed_tools,
                },
            },
        },
    }


def build_setup_plan(
    repo_root: Path,
    *,
    server_name: str = DEFAULT_SERVER_NAME,
    agent_id: str = DEFAULT_AGENT_ID,
    openclaw_command: str = 'openclaw',
) -> dict[str, Any]:
    """Build an auditable plan with one validated configuration write."""
    if server_name != DEFAULT_SERVER_NAME:
        raise ValueError(
            f'OpenClaw MCP server name is fixed to {DEFAULT_SERVER_NAME!r} '
            'so the managed skill and tool prefix remain exact'
        )
    _validate_identifier(server_name, label='server name')
    _validate_identifier(agent_id, label='agent id')
    repo_root = repo_root.resolve()
    server_config = build_server_config(repo_root, agent_id=agent_id)
    agent_profile = build_agent_profile(repo_root, server_name=server_name)
    commands = [
        [openclaw_command, 'config', 'validate', '--json'],
        [openclaw_command, 'agents', 'list', '--bindings', '--json'],
        [openclaw_command, 'config', 'get', 'agents.list', '--json'],
        [openclaw_command, 'mcp', 'show', server_name, '--json'],
        [
            openclaw_command,
            'config',
            'set',
            '--batch-file',
            BATCH_MARKER,
            '--replace',
            '--dry-run',
            '--json',
        ],
        [
            openclaw_command,
            'config',
            'set',
            '--batch-file',
            BATCH_MARKER,
            '--replace',
            '--json',
        ],
        [openclaw_command, 'config', 'validate', '--json'],
        [openclaw_command, 'mcp', 'doctor', server_name, '--probe'],
    ]
    return {
        'repo_root': str(repo_root),
        'server_name': server_name,
        'agent_id': agent_id,
        'server_config': server_config,
        'agent_profile': agent_profile,
        'non_target_deny': f'{_safe_server_prefix(server_name)}__*',
        'commands': commands,
    }


def apply_setup_plan(
    plan: dict[str, Any],
    *,
    runner: Callable[[list[str]], Any] | None = None,
) -> dict[str, Any]:
    """Validate and atomically reconcile the OpenClaw agent and MCP config."""
    validate_setup_inputs(plan, require_cli=runner is None)
    run = runner or _run_command
    commands = plan['commands']
    executed: list[list[str]] = []

    current_validation = run(commands[0])
    executed.append(commands[0])
    _require_success(current_validation, commands[0])

    inventory_result = run(commands[1])
    executed.append(commands[1])
    _require_success(inventory_result, commands[1])
    inventory = _json_rows(inventory_result.stdout, label='OpenClaw agent inventory')

    configured_result = run(commands[2])
    executed.append(commands[2])
    if int(configured_result.returncode) == 0:
        configured_agents = _json_rows(
            configured_result.stdout,
            label='OpenClaw agents.list config',
        )
    elif _is_missing_config_path_result(configured_result, 'agents.list'):
        configured_agents = []
    else:
        _require_success(configured_result, commands[2])
        configured_agents = []

    mcp_result = run(commands[3])
    executed.append(commands[3])
    if int(mcp_result.returncode) == 0:
        existing_mcp = _json_object(mcp_result.stdout, label='OpenClaw MCP config')
        _validate_existing_mcp_owner(existing_mcp, plan['server_config'])
    elif _is_missing_mcp_result(mcp_result):
        existing_mcp = None
    else:
        _require_success(mcp_result, commands[3])
        existing_mcp = None

    reconciled_agents, agent_index, agent_created = _reconcile_agents(
        configured_agents,
        inventory,
        plan=plan,
    )
    operations = [
        {'path': 'agents.list', 'value': reconciled_agents},
        {
            'path': f'mcp.servers.{plan["server_name"]}',
            'value': plan['server_config'],
        },
    ]
    with _transient_batch_file(operations) as batch_path:
        dry_run_command = _with_batch(commands[4], str(batch_path))
        dry_run_result = run(dry_run_command)
        executed.append(commands[4])
        _require_success(dry_run_result, dry_run_command)

        apply_command = _with_batch(commands[5], str(batch_path))
        apply_result = run(apply_command)
        executed.append(commands[5])
        _require_success(apply_result, apply_command)

    executed.append(commands[6])
    applied_result = {
        'applied': True,
        'config_applied': True,
        'verified': False,
        'agent_created': agent_created,
        'agent_index': agent_index,
        'existing_mcp_reconciled': existing_mcp is not None,
        'batch_operations': len(operations),
        'commands_run': executed,
    }
    try:
        validation_result = run(commands[6])
        _require_success(validation_result, commands[6])
    except RuntimeError as exc:
        raise ConfigurationAppliedError(
            'OpenClaw configuration was applied, but post-write validation failed: '
            f'{exc}',
            result=applied_result,
        ) from exc

    executed.append(commands[7])
    try:
        probe_result = run(commands[7])
    except RuntimeError as exc:
        raise ConfigurationAppliedError(
            'OpenClaw configuration was applied, but the MarketFlow MCP probe failed: '
            f'{exc}',
            result=applied_result,
        ) from exc
    if int(probe_result.returncode) != 0:
        detail = str(probe_result.stderr or probe_result.stdout or '').strip()
        raise ConfigurationAppliedError(
            'OpenClaw configuration was applied, but the MarketFlow MCP probe failed: '
            f'{detail[:500]}',
            result=applied_result,
        )

    applied_result['verified'] = True
    return applied_result


def validate_setup_inputs(plan: dict[str, Any], *, require_cli: bool = True) -> None:
    """Fail before any OpenClaw write when local prerequisites are incomplete."""
    errors: list[str] = []
    server_config = plan['server_config']
    workspace = Path(plan['agent_profile']['workspace'])
    python = Path(server_config['command'])
    entrypoint = Path(server_config['args'][0])

    if not python.is_file():
        errors.append(f'MarketFlow virtualenv Python is missing: {python}')
    if not entrypoint.is_file():
        errors.append(f'MCP entrypoint is missing: {entrypoint}')
    if not workspace.is_dir():
        errors.append(f'OpenClaw workspace is missing: {workspace}')
    else:
        for relative in REQUIRED_WORKSPACE_FILES:
            if not (workspace / relative).is_file():
                errors.append(f'managed workspace file is missing: {workspace / relative}')
    if server_config.get('env', {}).get('MIROFISH_MCP_ALLOW_MUTATION') != 'false':
        errors.append('MIROFISH_MCP_ALLOW_MUTATION must be false')
    if require_cli and _resolve_openclaw_executable(plan['commands'][0][0]) is None:
        errors.append(f'OpenClaw CLI is not executable: {plan["commands"][0][0]}')
    if errors:
        raise RuntimeError('OpenClaw setup preflight failed: ' + '; '.join(errors))


def main(
    argv: list[str] | None = None,
    *,
    runner: Callable[[list[str]], Any] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument('--server-name', default=DEFAULT_SERVER_NAME)
    parser.add_argument('--agent-id', default=DEFAULT_AGENT_ID)
    parser.add_argument('--openclaw-command', default='openclaw')
    parser.add_argument('--apply', action='store_true', help='apply and probe the configuration')
    parser.add_argument('--json', action='store_true', help='print machine-readable output')
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    workspace = repo_root / 'integrations' / 'openclaw' / 'workspace'
    result = {
        'service': 'marketflow-openclaw-mcp-setup',
        'repo_root': str(repo_root),
        'workspace': str(workspace),
        'server_name': args.server_name,
        'agent_id': args.agent_id,
        'apply_requested': bool(args.apply),
        'applied': False,
        'config_applied': False,
        'verified': False,
    }
    try:
        plan = build_setup_plan(
            repo_root,
            server_name=args.server_name,
            agent_id=args.agent_id,
            openclaw_command=args.openclaw_command,
        )
    except (ValueError, RuntimeError) as exc:
        result['error'] = str(exc)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f'MarketFlow OpenClaw MCP setup failed: {result["error"]}')
        return 1

    result.update({
        'mcp_entrypoint_exists': (repo_root / 'mirofish_mcp_server.py').is_file(),
        'python_command_exists': Path(plan['server_config']['command']).is_file(),
        'workspace_ready': _workspace_ready(workspace),
        **plan,
    })
    exit_code = 0
    if args.apply:
        try:
            result.update(apply_setup_plan(plan, runner=runner))
        except ConfigurationAppliedError as exc:
            result.update(exc.result)
            result['error'] = str(exc)
            exit_code = 1
        except RuntimeError as exc:
            result['error'] = str(exc)
            exit_code = 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if result.get('error'):
            print(f'MarketFlow OpenClaw MCP setup failed: {result["error"]}')
        else:
            mode = 'applied and probed' if result['applied'] else 'preview (no changes applied)'
            print(f'MarketFlow OpenClaw MCP setup {mode}')
            print(f'- repository: {repo_root}')
            print(f'- workspace: {workspace}')
            print(f'- MCP entrypoint exists: {result["mcp_entrypoint_exists"]}')
            print(f'- Python command exists: {result["python_command_exists"]}')
            print(f'- workspace ready: {result["workspace_ready"]}')
            print(f'- allowed MCP tools: {len(READ_ONLY_TOOLS)}')
            print(json.dumps(plan, ensure_ascii=False, indent=2))
    return exit_code


def _reconcile_agents(
    configured_agents: list[dict[str, Any]],
    inventory: list[dict[str, Any]],
    *,
    plan: dict[str, Any],
) -> tuple[list[dict[str, Any]], int, bool]:
    agent_id = str(plan['agent_id'])
    profile = plan['agent_profile']
    desired_workspace = str(profile['workspace'])
    configured_by_id = _unique_agents(configured_agents, label='agents.list')
    inventory_by_id = _unique_agents(inventory, label='agent inventory')

    for other_id, item in inventory_by_id.items():
        if other_id == agent_id or not item.get('workspace'):
            continue
        if _paths_overlap(str(item['workspace']), desired_workspace):
            raise RuntimeError(
                f'OpenClaw agent workspace overlaps target workspace: {other_id}'
            )

    existing = configured_by_id.get(agent_id)
    inventory_target = inventory_by_id.get(agent_id)
    if (existing is None) != (inventory_target is None):
        raise RuntimeError('OpenClaw agent inventory and agents.list disagree for target id')

    agent_created = existing is None
    preserved_agent_dir: str | None = None
    if existing is not None and inventory_target is not None:
        inventory_workspace = str(inventory_target.get('workspace') or '')
        configured_workspace = str(existing.get('workspace') or '')
        if not _paths_equal(inventory_workspace, desired_workspace):
            raise RuntimeError('existing OpenClaw agent workspace does not match target')
        if not _paths_equal(configured_workspace, desired_workspace):
            raise RuntimeError('existing agents.list workspace does not match target')
        if bool(inventory_target.get('isDefault')):
            raise RuntimeError('existing MarketFlow agent must not be the default agent')
        if _binding_count(inventory_target.get('bindings')):
            raise RuntimeError('existing MarketFlow agent has channel bindings')
        unexpected = set(existing) - _ALLOWED_EXISTING_TARGET_FIELDS
        if unexpected:
            raise RuntimeError(
                'existing MarketFlow agent has unsupported configuration fields: '
                + ', '.join(sorted(unexpected))
            )
        configured_agent_dir = str(existing.get('agentDir') or '')
        inventory_agent_dir = str(inventory_target.get('agentDir') or '')
        if configured_agent_dir and not _paths_equal(
            configured_agent_dir,
            inventory_agent_dir,
        ):
            raise RuntimeError(
                'existing MarketFlow agentDir does not match the agent inventory'
            )
        target_agent_dir = configured_agent_dir or inventory_agent_dir
        if target_agent_dir:
            for other_id, item in inventory_by_id.items():
                if other_id == agent_id or not item.get('agentDir'):
                    continue
                if _paths_overlap(str(item['agentDir']), target_agent_dir):
                    raise RuntimeError(
                        f'MarketFlow agentDir overlaps OpenClaw agentDir: {other_id}'
                    )
        if configured_agent_dir:
            preserved_agent_dir = configured_agent_dir

    reconciled = copy.deepcopy(configured_agents)
    implicit_defaults = [
        item
        for other_id, item in inventory_by_id.items()
        if other_id not in configured_by_id
        and other_id != agent_id
        and bool(item.get('isDefault'))
    ]
    if len(implicit_defaults) > 1:
        raise RuntimeError('OpenClaw agent inventory has multiple implicit defaults')
    missing_non_defaults = [
        other_id
        for other_id, item in inventory_by_id.items()
        if other_id not in configured_by_id
        and other_id != agent_id
        and not bool(item.get('isDefault'))
    ]
    if missing_non_defaults:
        raise RuntimeError(
            'OpenClaw agent inventory and agents.list disagree for agent ids: '
            + ', '.join(sorted(missing_non_defaults))
        )
    if implicit_defaults:
        # A fresh baseline exposes the implicit ``main`` agent through the
        # inventory while ``agents.list`` is still absent or empty. Materialize
        # that placeholder first so appending MarketFlow cannot make it the
        # default agent. Runtime-only inventory fields are deliberately omitted.
        default_id = str(implicit_defaults[0].get('id') or '')
        reconciled.insert(0, {'id': default_id})

    if existing is None:
        default_ids = [
            other_id
            for other_id, item in inventory_by_id.items()
            if bool(item.get('isDefault'))
        ]
        if len(default_ids) != 1 or default_ids[0] == agent_id:
            raise RuntimeError(
                'cannot add MarketFlow without preserving one non-target default agent'
            )

    deny_pattern = str(plan['non_target_deny'])
    for item in reconciled:
        if str(item.get('id') or '') == agent_id:
            continue
        tools = item.get('tools')
        if tools is None:
            tools = {}
        if not isinstance(tools, dict):
            raise RuntimeError(f'OpenClaw agent tools config is invalid: {item.get("id")}')
        deny = tools.get('deny') or []
        if not isinstance(deny, list) or not all(isinstance(value, str) for value in deny):
            raise RuntimeError(f'OpenClaw agent deny config is invalid: {item.get("id")}')
        tools = copy.deepcopy(tools)
        tools['deny'] = list(dict.fromkeys([*deny, deny_pattern]))
        item['tools'] = tools

    target = {
        'id': agent_id,
        'name': profile['name'],
        'workspace': desired_workspace,
        'sandbox': copy.deepcopy(profile['sandbox']),
        'skills': copy.deepcopy(profile['skills']),
        'tools': copy.deepcopy(profile['tools']),
    }
    if preserved_agent_dir:
        target['agentDir'] = preserved_agent_dir

    existing_index = next(
        (index for index, item in enumerate(reconciled) if str(item.get('id') or '') == agent_id),
        None,
    )
    if existing_index is None:
        reconciled.append(target)
        agent_index = len(reconciled) - 1
    else:
        reconciled[existing_index] = target
        agent_index = existing_index
    return reconciled, agent_index, agent_created


def _validate_existing_mcp_owner(
    existing: dict[str, Any],
    desired: dict[str, Any],
) -> None:
    same_command = _paths_equal(str(existing.get('command') or ''), str(desired['command']))
    same_cwd = _paths_equal(str(existing.get('cwd') or ''), str(desired['cwd']))
    same_args = existing.get('args') == desired.get('args')
    if not (same_command and same_cwd and same_args):
        raise RuntimeError(
            'OpenClaw MCP server name conflict: existing marketflow server has a different owner'
        )


def _unique_agents(
    rows: list[dict[str, Any]],
    *,
    label: str,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in rows:
        agent_id = str(item.get('id') or item.get('agentId') or '')
        if not agent_id:
            raise RuntimeError(f'{label} contains an agent without an id')
        if agent_id in result:
            raise RuntimeError(f'{label} contains duplicate agent id: {agent_id}')
        result[agent_id] = item
    return result


def _binding_count(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, (list, tuple, dict, set)):
        return len(value)
    return 0


def _python_command(repo_root: Path) -> Path:
    if os.name == 'nt':
        return repo_root / '.venv' / 'Scripts' / 'python.exe'
    return repo_root / '.venv' / 'bin' / 'python'


def _safe_server_prefix(value: str) -> str:
    return value.lower()


def _validate_identifier(value: str, *, label: str) -> None:
    if not _SAFE_ID_RE.fullmatch(value):
        raise ValueError(f'{label} must match {_SAFE_ID_RE.pattern}')


def _workspace_ready(workspace: Path) -> bool:
    return workspace.is_dir() and all(
        (workspace / relative).is_file() for relative in REQUIRED_WORKSPACE_FILES
    )


def _paths_equal(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return _normalized_path(left) == _normalized_path(right)


def _paths_overlap(left: str, right: str) -> bool:
    left_path = _normalized_path(left)
    right_path = _normalized_path(right)
    try:
        common = os.path.commonpath([left_path, right_path])
    except ValueError:
        return False
    return common in {left_path, right_path}


def _normalized_path(value: str) -> str:
    expanded = os.path.expanduser(value)
    return os.path.normcase(os.path.abspath(os.path.realpath(expanded)))


@contextmanager
def _transient_batch_file(operations: list[dict[str, Any]]) -> Iterator[Path]:
    """Write a private, bounded-lifetime batch without command-line payloads."""
    descriptor, raw_path = tempfile.mkstemp(
        prefix='marketflow-openclaw-',
        suffix='.json',
    )
    path = Path(raw_path)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as handle:
            json.dump(operations, handle, ensure_ascii=False, separators=(',', ':'))
            handle.write('\n')
        yield path
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _with_batch(template: list[str], batch_json: str) -> list[str]:
    return [batch_json if part == BATCH_MARKER else part for part in template]


def _json_rows(raw: str, *, label: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(raw or '[]')
    except json.JSONDecodeError as exc:
        raise RuntimeError(f'{label} did not return JSON') from exc
    if isinstance(payload, dict) and isinstance(payload.get('agents'), list):
        payload = payload['agents']
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise RuntimeError(f'{label} did not return an object list')
    return payload


def _json_object(raw: str, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw or '{}')
    except json.JSONDecodeError as exc:
        raise RuntimeError(f'{label} did not return JSON') from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f'{label} did not return an object')
    return payload


def _is_missing_mcp_result(result: Any) -> bool:
    detail = str(result.stderr or result.stdout or '').lower()
    return 'no mcp server named' in detail


def _is_missing_config_path_result(result: Any, path: str) -> bool:
    detail = str(result.stderr or result.stdout or '').lower()
    return f'config path not found: {path.lower()}' in detail


def _resolve_openclaw_executable(command: str) -> str | None:
    resolved = shutil.which(command)
    if resolved:
        return resolved
    candidate = Path(command).expanduser()
    if candidate.is_file():
        return str(candidate.resolve())
    if command != 'openclaw' or os.name != 'nt':
        return None
    local_app_data = os.getenv('LOCALAPPDATA')
    if not local_app_data:
        return None
    portable = Path(local_app_data) / 'OpenClaw' / 'deps' / 'portable-node' / 'openclaw.cmd'
    return str(portable) if portable.is_file() else None


def _run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    resolved_command = list(command)
    executable = _resolve_openclaw_executable(resolved_command[0])
    if executable:
        resolved_command[0] = executable
    try:
        return subprocess.run(
            resolved_command,
            check=False,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise RuntimeError(
            f'OpenClaw command execution failed: {type(exc).__name__}'
        ) from exc


def _require_success(result: Any, command: list[str]) -> None:
    if int(result.returncode) == 0:
        return
    detail = str(result.stderr or result.stdout or '').strip()
    raise RuntimeError(
        f'OpenClaw command failed ({result.returncode}): {command[:4]}: {detail[:500]}'
    )


if __name__ == '__main__':
    raise SystemExit(main())

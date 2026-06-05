"""Prepare Hermes Agent MCP configuration for MarketFlow.

This script does not install Hermes and does not read secrets. By default it
prints the config preview only. Pass --write to update the native Hermes
config.yaml path for the current OS.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_SERVER_NAME = 'marketflow_mirofish'
DEFAULT_INCLUDE_TOOLS = [
    'get_autonomous_status',
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
    'get_workflow_share_payload',
    'get_hermes_bridge_status',
    'get_hermes_bridge_manifest',
    'preview_hermes_sidecar_task',
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument('--config', default=str(default_hermes_config_path()))
    parser.add_argument('--server-name', default=DEFAULT_SERVER_NAME)
    parser.add_argument('--write', action='store_true', help='write config.yaml after creating a backup')
    parser.add_argument('--json', action='store_true', help='print machine-readable result')
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    config_path = Path(args.config).expanduser().resolve()
    server_config = build_server_config(repo_root)
    result = {
        'service': 'marketflow-hermes-mcp-setup',
        'config_path': str(config_path),
        'server_name': args.server_name,
        'repo_root': str(repo_root),
        'mcp_entrypoint_exists': (repo_root / 'mirofish_mcp_server.py').exists(),
        'python_command_exists': Path(server_config['command']).exists() if _looks_like_path(server_config['command']) else True,
        'write_requested': bool(args.write),
        'wrote_config': False,
        'backup_path': None,
        'server_config': server_config,
    }

    if args.write:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        if config_path.exists():
            backup_path = config_path.with_suffix(config_path.suffix + f'.bak-{_timestamp()}')
            shutil.copy2(config_path, backup_path)
            result['backup_path'] = str(backup_path)
        content = merge_config(config_path, args.server_name, server_config)
        config_path.write_text(content, encoding='utf-8')
        result['wrote_config'] = True

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_human_result(result, config_path, args.server_name, server_config)
    return 0


def build_server_config(repo_root: Path) -> dict[str, Any]:
    python_path = repo_root / '.venv' / 'Scripts' / 'python.exe'
    command = str(python_path if python_path.exists() else 'python')
    return {
        'command': command,
        'args': [
            str(repo_root / 'mirofish_mcp_server.py'),
            '--transport',
            'stdio',
        ],
        'env': {
            'PYTHONIOENCODING': 'utf-8',
            'HOME_SERVER': 'marketflow',
        },
        'timeout': 60,
        'connect_timeout': 20,
        'supports_parallel_tool_calls': False,
        'tools': {
            'include': DEFAULT_INCLUDE_TOOLS,
            'resources': True,
            'prompts': False,
        },
    }


def default_hermes_config_path() -> Path:
    """Return Hermes Agent's default config path for this OS."""
    if os.name == 'nt':
        local_app_data = os.environ.get('LOCALAPPDATA')
        if local_app_data:
            return Path(local_app_data) / 'hermes' / 'config.yaml'
    return Path.home() / '.hermes' / 'config.yaml'


def merge_config(config_path: Path, server_name: str, server_config: dict[str, Any]) -> str:
    existing = config_path.read_text(encoding='utf-8') if config_path.exists() else ''
    loaded = _try_load_yaml(existing) if existing.strip() else {}
    if loaded is not None:
        loaded.setdefault('mcp_servers', {})
        loaded['mcp_servers'][server_name] = server_config
        return _dump_yaml(loaded)

    snippet_path = config_path.with_name(f'{server_name}.yaml')
    snippet_path.write_text(_dump_yaml({'mcp_servers': {server_name: server_config}}), encoding='utf-8')
    raise SystemExit(
        f'Existing config could not be parsed without PyYAML. Wrote snippet: {snippet_path}'
    )


def print_human_result(
    result: dict[str, Any],
    config_path: Path,
    server_name: str,
    server_config: dict[str, Any],
) -> None:
    print('MarketFlow Hermes MCP setup preview')
    print(f'- config: {config_path}')
    print(f'- server: {server_name}')
    print(f'- entrypoint exists: {result["mcp_entrypoint_exists"]}')
    print(f'- python command exists: {result["python_command_exists"]}')
    print(f'- wrote config: {result["wrote_config"]}')
    if result['backup_path']:
        print(f'- backup: {result["backup_path"]}')
    print()
    print(_dump_yaml({'mcp_servers': {server_name: server_config}}))


def _try_load_yaml(text: str) -> dict[str, Any] | None:
    try:
        import yaml  # type: ignore
    except Exception:
        return {} if not text.strip() else None
    loaded = yaml.safe_load(text) if text.strip() else {}
    return loaded if isinstance(loaded, dict) else {}


def _dump_yaml(data: dict[str, Any]) -> str:
    try:
        import yaml  # type: ignore
    except Exception:
        return _minimal_yaml(data)
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120)


def _minimal_yaml(data: Any, indent: int = 0) -> str:
    lines: list[str] = []
    pad = ' ' * indent
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                lines.append(f'{pad}{key}:')
                lines.append(_minimal_yaml(value, indent + 2).rstrip())
            else:
                lines.append(f'{pad}{key}: {_format_scalar(value)}')
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, (dict, list)):
                lines.append(f'{pad}-')
                lines.append(_minimal_yaml(item, indent + 2).rstrip())
            else:
                lines.append(f'{pad}- {_format_scalar(item)}')
    else:
        lines.append(f'{pad}{_format_scalar(data)}')
    return '\n'.join(lines) + '\n'


def _format_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if value is None:
        return 'null'
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if not text or any(ch in text for ch in ':#{}[],"\n\t') or text.lower() in {'true', 'false', 'null'}:
        return json.dumps(text)
    return text


def _looks_like_path(value: str) -> bool:
    return '\\' in value or '/' in value or value.endswith('.exe')


def _timestamp() -> str:
    return datetime.now().strftime('%Y%m%d%H%M%S')


if __name__ == '__main__':
    sys.exit(main())

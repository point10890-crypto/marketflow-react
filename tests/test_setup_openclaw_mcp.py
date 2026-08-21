from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.mirofish.mcp_server import create_mcp_server
from scripts import setup_openclaw_mcp


class _CallLog(list):
    def __init__(self):
        super().__init__()
        self.batch_operations: dict[int, list[dict]] = {}
        self.batch_paths: list[str] = []


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / 'mirofish_mcp_server.py').write_text('print("ok")', encoding='utf-8')
    for python in (
        repo / '.venv' / 'Scripts' / 'python.exe',
        repo / '.venv' / 'bin' / 'python',
    ):
        python.parent.mkdir(parents=True, exist_ok=True)
        python.write_text('', encoding='utf-8')
    workspace = repo / 'integrations' / 'openclaw' / 'workspace'
    for relative in setup_openclaw_mcp.REQUIRED_WORKSPACE_FILES:
        path = workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('# managed test fixture\n', encoding='utf-8')
    return repo


def _completed(returncode: int = 0, stdout: str = '{}', stderr: str = ''):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _fake_openclaw(
    plan,
    *,
    inventory,
    configured_agents,
    existing_mcp='desired',
    dry_run_returncode=0,
    probe_returncode=0,
):
    calls = _CallLog()

    def runner(command: list[str]):
        calls.append(list(command))
        call_index = len(calls) - 1
        if '--batch-file' in command:
            batch_path = command[command.index('--batch-file') + 1]
            calls.batch_paths.append(batch_path)
            calls.batch_operations[call_index] = json.loads(
                Path(batch_path).read_text(encoding='utf-8')
            )
        if command[:3] == ['openclaw', 'config', 'validate']:
            return _completed(stdout=json.dumps({'ok': True}))
        if command[:3] == ['openclaw', 'agents', 'list']:
            return _completed(stdout=json.dumps(inventory))
        if command[:4] == ['openclaw', 'config', 'get', 'agents.list']:
            if configured_agents is None:
                return _completed(
                    returncode=1,
                    stdout='Config path not found: agents.list.',
                )
            return _completed(stdout=json.dumps(configured_agents))
        if command[:4] == ['openclaw', 'mcp', 'show', plan['server_name']]:
            if existing_mcp is None:
                return _completed(
                    returncode=1,
                    stdout=f'No MCP server named "{plan["server_name"]}"',
                )
            payload = plan['server_config'] if existing_mcp == 'desired' else existing_mcp
            return _completed(stdout=json.dumps(payload))
        if command[:4] == ['openclaw', 'config', 'set', '--batch-file']:
            if '--dry-run' in command and dry_run_returncode:
                return _completed(returncode=dry_run_returncode, stderr='dry run rejected')
            return _completed(stdout=json.dumps({'ok': True, 'operations': 2}))
        if command[:4] == ['openclaw', 'mcp', 'doctor', plan['server_name']]:
            if probe_returncode:
                return _completed(returncode=probe_returncode, stderr='probe failed')
            return _completed(stdout=json.dumps({'ok': True}))
        raise AssertionError(f'unexpected command: {command}')

    return runner, calls


def _batch_operations(calls: _CallLog, command: list[str]):
    return calls.batch_operations[calls.index(command)]


def test_server_config_exposes_only_registered_read_only_tools(tmp_path):
    repo = _repo(tmp_path)

    config = setup_openclaw_mcp.build_server_config(repo)
    registered = {
        tool.name
        for tool in asyncio.run(create_mcp_server(host='127.0.0.1', port=18766).list_tools())
    }

    assert len(setup_openclaw_mcp.READ_ONLY_TOOLS) == 19
    assert config['command'] == str(setup_openclaw_mcp._python_command(repo))
    assert config['args'] == [
        str(repo / 'mirofish_mcp_server.py'),
        '--transport',
        'stdio',
    ]
    assert config['cwd'] == str(repo)
    assert config['env']['MIROFISH_MCP_ALLOW_MUTATION'] == 'false'
    assert config['env']['PYTHONIOENCODING'] == 'utf-8'
    assert config['toolFilter']['include'] == setup_openclaw_mcp.READ_ONLY_TOOLS
    assert set(config['toolFilter']['include']) <= registered
    assert set(config['toolFilter']['include']).isdisjoint(setup_openclaw_mcp.MUTATING_TOOLS)
    assert config['codex']['agents'] == ['marketflow']
    assert config['supportsParallelToolCalls'] is False


def test_agent_profile_has_no_host_filesystem_shell_or_delivery_access(tmp_path):
    repo = _repo(tmp_path)

    profile = setup_openclaw_mcp.build_agent_profile(repo)

    assert profile['name'] == 'MarketFlow Read-Only'
    assert profile['workspace'] == str(repo / 'integrations' / 'openclaw' / 'workspace')
    assert profile['sandbox'] == {
        'mode': 'all',
        'scope': 'agent',
        'workspaceAccess': 'none',
    }
    assert profile['skills'] == ['marketflow-readonly']
    expected_allow = [
        f'marketflow__{name}' for name in setup_openclaw_mcp.READ_ONLY_TOOLS
    ]
    assert profile['tools']['allow'] == expected_allow
    assert profile['tools']['sandbox']['tools']['alsoAllow'] == expected_allow
    assert {
        'group:runtime',
        'group:fs',
        'browser',
        'cron',
        'gateway',
        'message',
        'sessions_spawn',
    } <= set(profile['tools']['deny'])
    assert not any(name.startswith('marketflow__run_') for name in profile['tools']['allow'])
    assert not any('telegram' in name for name in profile['tools']['allow'])


def test_setup_preview_is_machine_readable_and_does_not_apply(tmp_path, capsys):
    repo = _repo(tmp_path)

    rc = setup_openclaw_mcp.main(['--repo-root', str(repo), '--json'])

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload['service'] == 'marketflow-openclaw-mcp-setup'
    assert payload['apply_requested'] is False
    assert payload['applied'] is False
    assert payload['server_name'] == 'marketflow'
    assert payload['agent_id'] == 'marketflow'
    assert payload['mcp_entrypoint_exists'] is True
    assert payload['python_command_exists'] is True
    assert payload['workspace_ready'] is True


def test_invalid_identifier_returns_structured_json_error(tmp_path, capsys):
    rc = setup_openclaw_mcp.main(
        [
            '--repo-root',
            str(_repo(tmp_path)),
            '--agent-id',
            'INVALID AGENT ID',
            '--json',
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload['applied'] is False
    assert payload['config_applied'] is False
    assert payload['verified'] is False
    assert 'agent id must match' in payload['error']


def test_setup_plan_uses_one_validated_batch_write(tmp_path):
    plan = setup_openclaw_mcp.build_setup_plan(_repo(tmp_path))
    commands = plan['commands']

    assert commands[0] == ['openclaw', 'config', 'validate', '--json']
    assert ['openclaw', 'agents', 'list', '--bindings', '--json'] in commands
    assert ['openclaw', 'config', 'get', 'agents.list', '--json'] in commands
    assert ['openclaw', 'mcp', 'show', 'marketflow', '--json'] in commands
    assert sum('--batch-file' in command and '--dry-run' in command for command in commands) == 1
    assert sum('--batch-file' in command and '--dry-run' not in command for command in commands) == 1
    assert not any(command[:3] == ['openclaw', 'agents', 'add'] for command in commands)
    assert not any(command[:3] == ['openclaw', 'mcp', 'set'] for command in commands)
    assert commands[-2] == ['openclaw', 'config', 'validate', '--json']
    assert commands[-1] == ['openclaw', 'mcp', 'doctor', 'marketflow', '--probe']


def test_custom_server_name_is_rejected_to_keep_skill_prefix_exact(tmp_path):
    with pytest.raises(ValueError, match='server name is fixed'):
        setup_openclaw_mcp.build_setup_plan(
            _repo(tmp_path),
            server_name='other-marketflow',
        )


def test_apply_atomically_reconciles_safe_agent_and_denies_non_target(tmp_path):
    repo = _repo(tmp_path)
    plan = setup_openclaw_mcp.build_setup_plan(repo)
    workspace = plan['agent_profile']['workspace']
    inventory = [
        {
            'id': 'main',
            'workspace': str(tmp_path / 'main-workspace'),
            'bindings': 0,
            'isDefault': True,
        },
        {
            'id': 'marketflow',
            'workspace': workspace,
            'agentDir': str(tmp_path / 'marketflow-agent'),
            'bindings': 0,
            'isDefault': False,
        },
    ]
    configured = [
        {'id': 'main', 'tools': {'deny': ['browser']}},
        {
            'id': 'marketflow',
            'name': 'marketflow',
            'workspace': workspace,
            'agentDir': str(tmp_path / 'marketflow-agent'),
            'sandbox': {'mode': 'all'},
            'tools': {'allow': ['old']},
            'skills': ['old'],
        },
    ]
    runner, calls = _fake_openclaw(
        plan,
        inventory=inventory,
        configured_agents=configured,
    )

    result = setup_openclaw_mcp.apply_setup_plan(plan, runner=runner)

    assert result['applied'] is True
    assert result['agent_created'] is False
    assert result['agent_index'] == 1
    writes = [
        command
        for command in calls
        if command[:4] == ['openclaw', 'config', 'set', '--batch-file']
        and '--dry-run' not in command
    ]
    assert len(writes) == 1
    operations = _batch_operations(calls, writes[0])
    agents = next(item['value'] for item in operations if item['path'] == 'agents.list')
    mcp = next(item['value'] for item in operations if item['path'] == 'mcp.servers.marketflow')
    assert agents[0]['tools']['deny'] == ['browser', 'marketflow__*']
    assert agents[1]['name'] == 'MarketFlow Read-Only'
    assert agents[1]['workspace'] == workspace
    assert agents[1]['agentDir'] == str(tmp_path / 'marketflow-agent')
    assert agents[1]['skills'] == ['marketflow-readonly']
    assert agents[1]['tools'] == plan['agent_profile']['tools']
    assert mcp == plan['server_config']
    assert mcp['codex']['agents'] == ['marketflow']
    dry_run_index = next(i for i, command in enumerate(calls) if '--dry-run' in command)
    apply_index = calls.index(writes[0])
    assert dry_run_index < apply_index


def test_setup_apply_creates_missing_agent_without_agents_add(tmp_path, capsys):
    repo = _repo(tmp_path)
    plan = setup_openclaw_mcp.build_setup_plan(repo)
    inventory = [
        {
            'id': 'main',
            'workspace': str(tmp_path / 'main-workspace'),
            'bindings': 0,
            'isDefault': True,
        },
    ]
    configured = [{'id': 'main'}]
    runner, calls = _fake_openclaw(
        plan,
        inventory=inventory,
        configured_agents=configured,
        existing_mcp=None,
    )

    rc = setup_openclaw_mcp.main(
        ['--repo-root', str(repo), '--apply', '--json'],
        runner=runner,
    )

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload['applied'] is True
    assert payload['agent_created'] is True
    assert payload['agent_index'] == 1
    assert not any(command[:3] == ['openclaw', 'agents', 'add'] for command in calls)
    write = next(
        command
        for command in calls
        if command[:4] == ['openclaw', 'config', 'set', '--batch-file']
        and '--dry-run' not in command
    )
    agents = next(
        item['value']
        for item in _batch_operations(calls, write)
        if item['path'] == 'agents.list'
    )
    assert [item['id'] for item in agents] == ['main', 'marketflow']


@pytest.mark.parametrize('configured_agents', [None, []])
def test_fresh_baseline_materializes_default_agent_before_marketflow(
    tmp_path,
    configured_agents,
):
    repo = _repo(tmp_path)
    plan = setup_openclaw_mcp.build_setup_plan(repo)
    default_workspace = str(tmp_path / 'openclaw-default-workspace')
    inventory = [
        {
            'id': 'main',
            'workspace': default_workspace,
            'agentDir': str(tmp_path / 'openclaw-main-agent'),
            'bindings': 0,
            'isDefault': True,
            'routes': ['default (no explicit rules)'],
        },
    ]
    runner, calls = _fake_openclaw(
        plan,
        inventory=inventory,
        configured_agents=configured_agents,
        existing_mcp=None,
    )

    result = setup_openclaw_mcp.apply_setup_plan(plan, runner=runner)

    assert result['applied'] is True
    write = next(
        command
        for command in calls
        if command[:4] == ['openclaw', 'config', 'set', '--batch-file']
        and '--dry-run' not in command
    )
    agents = next(
        item['value']
        for item in _batch_operations(calls, write)
        if item['path'] == 'agents.list'
    )
    assert [item['id'] for item in agents] == ['main', 'marketflow']
    assert agents[0] == {
        'id': 'main',
        'tools': {'deny': ['marketflow__*']},
    }
    assert agents[1]['name'] == 'MarketFlow Read-Only'


def test_apply_preflight_fails_before_openclaw_writes(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    plan = setup_openclaw_mcp.build_setup_plan(repo)
    calls: list[list[str]] = []

    with pytest.raises(RuntimeError, match='preflight failed'):
        setup_openclaw_mcp.apply_setup_plan(
            plan,
            runner=lambda command: calls.append(command) or _completed(),
        )

    assert calls == []


@pytest.mark.parametrize(
    ('workspace_override', 'bindings', 'is_default', 'error'),
    [
        ('other', 0, False, 'workspace'),
        (None, 1, False, 'bindings'),
        (None, 0, True, 'default'),
    ],
)
def test_existing_agent_collision_fails_closed(
    tmp_path,
    workspace_override,
    bindings,
    is_default,
    error,
):
    repo = _repo(tmp_path)
    plan = setup_openclaw_mcp.build_setup_plan(repo)
    workspace = (
        str(tmp_path / 'other-workspace')
        if workspace_override
        else plan['agent_profile']['workspace']
    )
    inventory = [
        {
            'id': 'marketflow',
            'workspace': workspace,
            'bindings': bindings,
            'isDefault': is_default,
        },
    ]
    configured = [{'id': 'marketflow', 'workspace': workspace}]
    runner, calls = _fake_openclaw(
        plan,
        inventory=inventory,
        configured_agents=configured,
    )

    with pytest.raises(RuntimeError, match=error):
        setup_openclaw_mcp.apply_setup_plan(plan, runner=runner)

    assert not any(
        command[:4] == ['openclaw', 'config', 'set', '--batch-file']
        and '--dry-run' not in command
        for command in calls
    )


def test_overlapping_agent_workspace_fails_closed(tmp_path):
    repo = _repo(tmp_path)
    plan = setup_openclaw_mcp.build_setup_plan(repo)
    target_workspace = Path(plan['agent_profile']['workspace'])
    inventory = [
        {
            'id': 'main',
            'workspace': str(target_workspace.parent),
            'bindings': 0,
            'isDefault': True,
        },
    ]
    runner, calls = _fake_openclaw(
        plan,
        inventory=inventory,
        configured_agents=[{'id': 'main'}],
        existing_mcp=None,
    )

    with pytest.raises(RuntimeError, match='overlaps'):
        setup_openclaw_mcp.apply_setup_plan(plan, runner=runner)

    assert not any('--batch-file' in command for command in calls)


@pytest.mark.parametrize('inventory_suffix', ['different', 'main/shared-child'])
def test_existing_target_agent_dir_must_match_and_not_overlap_other_agents(
    tmp_path,
    inventory_suffix,
):
    repo = _repo(tmp_path)
    plan = setup_openclaw_mcp.build_setup_plan(repo)
    main_agent_dir = tmp_path / 'agents' / 'main'
    configured_target_dir = main_agent_dir / 'shared-child'
    inventory_target_dir = tmp_path / 'agents' / inventory_suffix
    inventory = [
        {
            'id': 'main',
            'workspace': str(tmp_path / 'main-workspace'),
            'agentDir': str(main_agent_dir),
            'bindings': 0,
            'isDefault': True,
        },
        {
            'id': 'marketflow',
            'workspace': plan['agent_profile']['workspace'],
            'agentDir': str(inventory_target_dir),
            'bindings': 0,
            'isDefault': False,
        },
    ]
    configured = [
        {'id': 'main'},
        {
            'id': 'marketflow',
            'workspace': plan['agent_profile']['workspace'],
            'agentDir': str(configured_target_dir),
        },
    ]
    runner, calls = _fake_openclaw(
        plan,
        inventory=inventory,
        configured_agents=configured,
    )

    with pytest.raises(RuntimeError, match='agentDir'):
        setup_openclaw_mcp.apply_setup_plan(plan, runner=runner)

    assert not any('--batch-file' in command for command in calls)


def test_conflicting_mcp_server_owner_fails_before_write(tmp_path):
    repo = _repo(tmp_path)
    plan = setup_openclaw_mcp.build_setup_plan(repo)
    inventory = [
        {
            'id': 'main',
            'workspace': str(tmp_path / 'main-workspace'),
            'bindings': 0,
            'isDefault': True,
        },
    ]
    runner, calls = _fake_openclaw(
        plan,
        inventory=inventory,
        configured_agents=[{'id': 'main'}],
        existing_mcp={'command': r'C:\other\python.exe', 'args': ['other.py']},
    )

    with pytest.raises(RuntimeError, match='MCP server name conflict'):
        setup_openclaw_mcp.apply_setup_plan(plan, runner=runner)

    assert not any('--batch-file' in command for command in calls)


def test_batch_dry_run_failure_leaves_config_unmodified(tmp_path):
    repo = _repo(tmp_path)
    plan = setup_openclaw_mcp.build_setup_plan(repo)
    runner, calls = _fake_openclaw(
        plan,
        inventory=[
            {
                'id': 'main',
                'workspace': str(tmp_path / 'main-workspace'),
                'bindings': 0,
                'isDefault': True,
            },
        ],
        configured_agents=[{'id': 'main'}],
        existing_mcp=None,
        dry_run_returncode=1,
    )

    with pytest.raises(RuntimeError, match='dry run rejected'):
        setup_openclaw_mcp.apply_setup_plan(plan, runner=runner)

    assert not any(
        command[:4] == ['openclaw', 'config', 'set', '--batch-file']
        and '--dry-run' not in command
        for command in calls
    )


def test_post_apply_probe_failure_reports_config_applied_but_not_verified(
    tmp_path,
    capsys,
):
    repo = _repo(tmp_path)
    plan = setup_openclaw_mcp.build_setup_plan(repo)
    runner, _calls = _fake_openclaw(
        plan,
        inventory=[
            {
                'id': 'main',
                'workspace': str(tmp_path / 'main-workspace'),
                'bindings': 0,
                'isDefault': True,
            },
        ],
        configured_agents=[{'id': 'main'}],
        existing_mcp=None,
        probe_returncode=1,
    )

    rc = setup_openclaw_mcp.main(
        ['--repo-root', str(repo), '--apply', '--json'],
        runner=runner,
    )

    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload['applied'] is True
    assert payload['config_applied'] is True
    assert payload['verified'] is False
    assert 'configuration was applied' in payload['error']


def test_run_command_resolves_windows_openclaw_shim_and_has_timeout(monkeypatch):
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        setup_openclaw_mcp.shutil,
        'which',
        lambda name: r'C:\Users\tester\OpenClaw\openclaw.cmd' if name == 'openclaw' else None,
    )

    def fake_run(command, **kwargs):
        captured['command'] = command
        captured['kwargs'] = kwargs
        return subprocess.CompletedProcess(command, 0, stdout='{}', stderr='')

    monkeypatch.setattr(setup_openclaw_mcp.subprocess, 'run', fake_run)

    result = setup_openclaw_mcp._run_command(['openclaw', 'agents', 'list', '--json'])

    assert result.returncode == 0
    assert captured['command'][0] == r'C:\Users\tester\OpenClaw\openclaw.cmd'
    assert captured['kwargs']['timeout'] == setup_openclaw_mcp.COMMAND_TIMEOUT_SECONDS


@pytest.mark.parametrize(
    'failure',
    [
        subprocess.TimeoutExpired(cmd=['openclaw'], timeout=1),
        OSError('executable failed'),
    ],
)
def test_run_command_wraps_execution_failures_as_runtime_errors(monkeypatch, failure):
    monkeypatch.setattr(setup_openclaw_mcp.shutil, 'which', lambda _name: 'openclaw')
    monkeypatch.setattr(
        setup_openclaw_mcp.subprocess,
        'run',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(failure),
    )

    with pytest.raises(RuntimeError, match='OpenClaw command execution failed'):
        setup_openclaw_mcp._run_command(['openclaw', 'config', 'validate'])


def test_path_comparison_expands_home_directory(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('USERPROFILE', str(tmp_path))

    assert setup_openclaw_mcp._paths_equal(
        '~/agents/marketflow',
        str(tmp_path / 'agents' / 'marketflow'),
    )


def test_large_unrelated_agent_config_uses_cleaned_batch_file_without_output_leak(
    tmp_path,
    capsys,
):
    repo = _repo(tmp_path)
    plan = setup_openclaw_mcp.build_setup_plan(repo)
    marker = 'private-unrelated-agent-value<&|'
    large_deny = [f'unrelated_tool_{index:05d}_*' for index in range(2_000)]
    inventory = [
        {
            'id': 'main',
            'workspace': str(tmp_path / 'main-workspace'),
            'bindings': 0,
            'isDefault': True,
        },
    ]
    configured = [
        {
            'id': 'main',
            'name': marker,
            'tools': {'deny': large_deny},
        },
    ]
    runner, calls = _fake_openclaw(
        plan,
        inventory=inventory,
        configured_agents=configured,
        existing_mcp=None,
    )

    rc = setup_openclaw_mcp.main(
        ['--repo-root', str(repo), '--apply', '--json'],
        runner=runner,
    )

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert rc == 0
    assert payload['applied'] is True
    assert marker not in output
    assert large_deny[-1] not in output
    assert all(len(subprocess.list2cmdline(command)) < 2_048 for command in calls)
    assert len(calls.batch_paths) == 2
    assert all(not Path(path).exists() for path in calls.batch_paths)
    applied_operations = next(
        calls.batch_operations[index]
        for index, command in enumerate(calls)
        if '--batch-file' in command and '--dry-run' not in command
    )
    agents = next(
        item['value']
        for item in applied_operations
        if item['path'] == 'agents.list'
    )
    assert agents[0]['name'] == marker
    assert agents[0]['tools']['deny'] == [*large_deny, 'marketflow__*']
    assert all('<transient-batch-file>' in command for command in payload['commands_run'] if '--batch-file' in command)

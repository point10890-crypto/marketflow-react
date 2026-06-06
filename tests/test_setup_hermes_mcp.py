from __future__ import annotations

import json
from pathlib import Path

from scripts import setup_hermes_mcp


def test_build_server_config_uses_marketflow_mcp_entrypoint(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / 'mirofish_mcp_server.py').write_text('print("ok")', encoding='utf-8')

    config = setup_hermes_mcp.build_server_config(repo)

    assert config['args'][0].endswith('mirofish_mcp_server.py')
    assert config['args'][1:] == ['--transport', 'stdio']
    assert config['tools']['resources'] is True
    assert config['tools']['prompts'] is False
    assert 'get_hermes_bridge_manifest' in config['tools']['include']
    assert 'get_hermes_learning_task_pack' in config['tools']['include']
    assert 'get_outcomes_kpi' in config['tools']['include']
    assert 'graphrag_get_scan_history' in config['tools']['include']


def test_default_config_path_matches_native_windows(monkeypatch, tmp_path):
    if setup_hermes_mcp.os.name != 'nt':
        return

    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'LocalAppData'))

    path = setup_hermes_mcp.default_hermes_config_path()

    assert path == tmp_path / 'LocalAppData' / 'hermes' / 'config.yaml'


def test_setup_script_dry_run_does_not_write_config(tmp_path, capsys):
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / 'mirofish_mcp_server.py').write_text('print("ok")', encoding='utf-8')
    config_path = tmp_path / '.hermes' / 'config.yaml'

    rc = setup_hermes_mcp.main([
        '--repo-root',
        str(repo),
        '--config',
        str(config_path),
        '--json',
    ])

    assert rc == 0
    assert not config_path.exists()
    payload = json.loads(capsys.readouterr().out)
    assert payload['wrote_config'] is False
    assert payload['server_name'] == 'marketflow_mirofish'


def test_setup_script_write_creates_yaml_config(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / 'mirofish_mcp_server.py').write_text('print("ok")', encoding='utf-8')
    config_path = tmp_path / '.hermes' / 'config.yaml'

    rc = setup_hermes_mcp.main([
        '--repo-root',
        str(repo),
        '--config',
        str(config_path),
        '--write',
    ])

    assert rc == 0
    content = config_path.read_text(encoding='utf-8')
    assert 'mcp_servers:' in content
    assert 'marketflow_mirofish:' in content
    assert 'mirofish_mcp_server.py' in content

from __future__ import annotations

from app.services.mirofish import hermes_bridge


def test_hermes_status_is_sidecar_and_secret_safe():
    status = hermes_bridge.build_hermes_bridge_status()

    assert status['service'] == 'mirofish-hermes-bridge'
    assert status['integration_mode'] == 'sidecar_mcp_client'
    assert status['hermes_agent']['vendored_into_marketflow'] is False
    assert 'alpha' in status['alpha_objective'].lower()
    assert 'MIROFISH_MCP_API_KEY' in status['safety']['mutation_gate']['requires_api_key']
    assert 'broker_order_execution' in status['safety']['tool_policy']['prohibited']

    rendered = str(status).lower()
    assert 'xai-' not in rendered
    assert 'telegram_bot_token' not in rendered
    assert 'dart_api_key' not in rendered


def test_hermes_manifest_whitelists_read_tools_and_guards_mutations():
    manifest = hermes_bridge.build_hermes_mcp_manifest()
    config = manifest['hermes_config_yaml']['mcp_servers']['marketflow_mirofish']
    include = config['tools']['include']

    assert manifest['name'] == 'marketflow-mirofish'
    assert config['command']
    assert 'mirofish_mcp_server.py' in ' '.join(config['args'])
    assert 'get_autonomous_status' in include
    assert 'get_hermes_learning_task_pack' in include
    assert 'get_outcomes_kpi' in include
    assert 'graphrag_get_scan_history' in include
    assert 'run_autonomous_scan_analysis' in include
    assert manifest['tool_surface']['guarded_mutation_include'] == hermes_bridge.GUARDED_MUTATION_TOOLS
    assert config['supports_parallel_tool_calls'] is False
    assert manifest['learning_task_pack']['dry_run_only'] is True


def test_hermes_preview_does_not_execute_mutating_tools():
    preview = hermes_bridge.preview_hermes_task({
        'task': 'top3_dry_run',
        'limit': 11,
        'max_events': 5,
        'top_n': 3,
    })

    assert preview['service'] == 'mirofish-hermes-bridge-preview'
    assert preview['dry_run_only'] is True
    assert preview['executes_tools'] is False
    run_step = next(step for step in preview['planned_tool_calls'] if step['tool'] == 'run_autonomous_scan_analysis')
    assert run_step['args']['dry_run'] is True
    assert run_step['args']['send_telegram'] is False
    assert run_step['args']['top_n'] == 3


def test_hermes_prompt_pack_keeps_alpha_goal_and_forbids_hype():
    prompt_pack = hermes_bridge.build_hermes_prompt_pack()
    prompt = prompt_pack['system_prompt']

    assert 'Top 3' in prompt
    assert '뉴스/테마/소셜 신호는 단독 매수 근거가 아니다' in prompt
    assert '주문 실행' in prompt
    assert '과장 표현을 제한' in prompt


def test_hermes_learning_task_pack_is_read_only_and_replay_safe():
    pack = hermes_bridge.build_hermes_learning_task_pack({
        'mode': 'weekly_post_mortem',
        'horizon_days': 20,
        'limit_workflows': 500,
    })

    assert pack['service'] == 'mirofish-hermes-learning-task-pack'
    assert pack['mode'] == 'weekly_post_mortem'
    assert pack['dry_run_only'] is True
    assert pack['executes_tools'] is False
    assert pack['workdir'].endswith('bitman_marketfloww')
    assert pack['result_artifact_contract']['path_template'] == 'multi_agent/tasks/{YYYY-MM-DD}/result.md'
    assert pack['learning_append_contract']['append_only'] is True

    tools = {step['tool']: step for step in pack['planned_tool_calls']}
    assert 'get_outcomes_kpi' in tools
    assert 'get_backtest_summary' in tools
    assert 'graphrag_get_scan_history' in tools
    assert tools['refresh_learning_feedback']['args']['commit'] is False
    assert tools['refresh_learning_feedback']['args']['limit'] == 200

    rendered = str(pack).lower()
    assert 'telegram_bot_token' not in rendered
    assert 'xai-' not in rendered

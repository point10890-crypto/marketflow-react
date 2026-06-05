"""Hermes Agent sidecar contract for the MiroFish MCP control-plane."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
MCP_ENTRYPOINT = REPO_ROOT / 'mirofish_mcp_server.py'
DEFAULT_MCP_PORT = 8765
DEFAULT_MCP_PATH = '/mcp'

READ_ONLY_TOOLS = [
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
    'get_alpha_scanner_diagnostics',
    'get_tradingview_provider_status',
    'resolve_target',
    'search_targets',
]

GUARDED_MUTATION_TOOLS = [
    'run_candidate_detection_alert',
    'run_autonomous_scan_analysis',
    'refresh_learning_feedback',
    'send_latest_workflow_telegram',
]

PROHIBITED_ACTIONS = [
    'broker_order_execution',
    'direct_env_or_secret_read',
    'destructive_git_or_filesystem_action',
    'generated_data_staging_without_operator_request',
    'news_or_social_as_standalone_buy_signal',
]

HERMES_RESEARCH_SOURCE = {
    'repository': 'https://github.com/NousResearch/hermes-agent',
    'docs': 'https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp',
    'license': 'MIT',
    'integration_basis': [
        'Hermes can connect to local stdio MCP servers through mcp_servers.<name>.command and args.',
        'Hermes supports per-server tool filtering with tools.include.',
        'Hermes can run scheduled workflows through its built-in cron feature.',
    ],
}


def build_hermes_bridge_status() -> dict[str, Any]:
    """Return a redacted readiness view for using Hermes as a sidecar."""
    entrypoint_exists = MCP_ENTRYPOINT.exists()
    python_command = _default_python_command()
    return {
        'service': 'mirofish-hermes-bridge',
        'state': 'ready' if entrypoint_exists else 'degraded',
        'ready': bool(entrypoint_exists),
        'integration_mode': 'sidecar_mcp_client',
        'alpha_objective': (
            'Hermes is an automation and memory sidecar. MiroFish scanner, '
            'risk filters, GraphRAG analysis, and outcome feedback remain the '
            'source of alpha detection truth.'
        ),
        'hermes_agent': {
            'source': HERMES_RESEARCH_SOURCE,
            'vendored_into_marketflow': False,
            'recommended_runtime': 'MiniPC or isolated operator shell',
            'recommended_transport': 'stdio',
        },
        'marketflow_mcp': {
            'entrypoint': _repo_relative(MCP_ENTRYPOINT),
            'entrypoint_exists': entrypoint_exists,
            'python_command': str(python_command),
            'python_command_exists': _command_path_exists(python_command),
            'stdio': _stdio_server_config(),
            'streamable_http': _http_server_config(),
            'tool_counts': {
                'read_only': len(READ_ONLY_TOOLS),
                'guarded_mutation': len(GUARDED_MUTATION_TOOLS),
                'prohibited': len(PROHIBITED_ACTIONS),
            },
        },
        'safety': build_hermes_security_policy(),
        'recommended_first_task': 'top3_dry_run',
        'generated_at': _now_iso(),
    }


def build_hermes_security_policy() -> dict[str, Any]:
    """Return the policy Hermes should follow before calling MarketFlow tools."""
    return {
        'default_mode': 'read_only_first',
        'mutation_gate': {
            'requires_env': 'MIROFISH_MCP_MUTATION_ENABLED=true',
            'requires_api_key': 'MIROFISH_MCP_API_KEY',
            'requires_confirmation_phrase': 'confirmed-send-top3',
            'telegram_send_is_mutating': True,
        },
        'tool_policy': {
            'read_only_include': READ_ONLY_TOOLS,
            'guarded_mutation_include': GUARDED_MUTATION_TOOLS,
            'prohibited': PROHIBITED_ACTIONS,
        },
        'financial_policy': {
            'orders_allowed': False,
            'llm_can_interpret_numbers_but_not_invent_them': True,
            'weak_signals_require_confirmation': True,
            'top3_verdict_must_include_target_symbol_name_market': True,
            'backtest_requires_entry_date_horizon_costs_and_no_lookahead': True,
        },
        'artifact_policy': {
            'safe_root': 'data/admin_mirofish',
            'relative_paths_only': True,
            'secrets_redacted': True,
            'generated_artifacts_not_staged_by_default': True,
        },
    }


def build_hermes_mcp_manifest() -> dict[str, Any]:
    """Return a machine-readable integration manifest for Hermes MCP config."""
    include_tools = READ_ONLY_TOOLS + GUARDED_MUTATION_TOOLS
    return {
        'schema_version': '2026-06-05.hermes-marketflow.v1',
        'name': 'marketflow-mirofish',
        'title': 'MarketFlow MiroFish MCP',
        'description': (
            'Hermes Agent sidecar configuration for MarketFlow alpha scanner, '
            'multi-stock GraphRAG workflow, Top 3 ranking, and Telegram delivery.'
        ),
        'source': HERMES_RESEARCH_SOURCE,
        'marketflow_goal': (
            'Detect, rank, validate, monitor, and learn from Korean equity alpha '
            'candidates with the highest forward profit potential.'
        ),
        'transports': {
            'recommended_stdio': _stdio_server_config(),
            'optional_streamable_http': _http_server_config(),
        },
        'hermes_config_yaml': {
            'mcp_servers': {
                'marketflow_mirofish': {
                    **_stdio_server_config(),
                    'timeout': 60,
                    'connect_timeout': 20,
                    'supports_parallel_tool_calls': False,
                    'tools': {
                        'include': include_tools,
                        'resources': True,
                        'prompts': False,
                    },
                },
            },
        },
        'hermes_commands': {
            'add_stdio': _stdio_add_command(),
            'test': 'hermes mcp test marketflow_mirofish',
            'reload_inside_hermes': '/reload-mcp',
        },
        'tool_surface': build_hermes_security_policy()['tool_policy'],
        'cron_recipes': _cron_recipes(),
        'validation_checks': [
            'hermes mcp test marketflow_mirofish',
            'Call get_autonomous_status and verify service is mirofish-autonomous-mcp.',
            'Call get_pipeline_operating_snapshot and verify scanner/workflow state is readable.',
            'Run preview task top3_dry_run before enabling any mutation.',
        ],
        'generated_at': _now_iso(),
    }


def build_hermes_runbook() -> dict[str, Any]:
    """Return the operator runbook for enabling Hermes without changing scoring logic."""
    return {
        'title': 'Hermes sidecar runbook for MiroFish',
        'principles': [
            'Do not make Hermes the alpha scoring engine.',
            'Keep scanner and GraphRAG outputs deterministic and replayable.',
            'Start read-only, then enable guarded mutation only for Telegram or workflow triggers.',
            'Never expose secrets or order execution tools through Hermes.',
        ],
        'steps': [
            {
                'phase': 'prepare',
                'actions': [
                    'Install Hermes in an isolated operator account or MiniPC shell.',
                    'Confirm MarketFlow Flask and MiroFish MCP dependencies are installed.',
                    'Keep the MarketFlow repo path stable on the MiniPC.',
                ],
            },
            {
                'phase': 'connect_mcp',
                'actions': [
                    'Add the marketflow_mirofish stdio config to ~/.hermes/config.yaml.',
                    'Whitelist only the tools listed in this manifest.',
                    'Run hermes mcp test marketflow_mirofish.',
                ],
            },
            {
                'phase': 'dry_run',
                'actions': [
                    'Ask Hermes to run scanner health and top3_dry_run previews.',
                    'Verify source freshness, missing data, and target identifiers.',
                    'Compare results with MarketFlow admin endpoint output.',
                ],
            },
            {
                'phase': 'guarded_automation',
                'actions': [
                    'Set MIROFISH_MCP_MUTATION_ENABLED only on MiniPC if automation is approved.',
                    'Use confirmation phrase for Telegram sends.',
                    'Keep all broker/order functions disabled.',
                ],
            },
        ],
        'rollback': [
            'Set mcp_servers.marketflow_mirofish.enabled=false in Hermes config.',
            'Restart Hermes or run /reload-mcp.',
            'Leave MarketFlow scanner and scheduler untouched.',
        ],
        'generated_at': _now_iso(),
    }


def build_hermes_prompt_pack() -> dict[str, Any]:
    """Return Korean operating prompts for Hermes when attached to MarketFlow."""
    system_prompt = (
        '너는 MarketFlow MiroFish 알파 검출 보조 에이전트다. 목적은 MCP 자동화가 아니라 '
        '정확한 데이터 기반으로 수익 가능성이 높은 Top 3 후보를 더 잘 찾고, 나쁜 후보를 더 빨리 '
        '걸러내며, 사후 성과 피드백으로 검출 품질을 개선하는 것이다.\n\n'
        '원칙:\n'
        '1. 숫자는 MarketFlow MCP 도구, API, 파일, 결정적 계산에서만 가져온다.\n'
        '2. 뉴스/테마/소셜 신호는 단독 매수 근거가 아니다. 가격, 거래대금, 수급, 공시, 리스크와 결합한다.\n'
        '3. 모든 최종 판단에는 종목명, 종목코드, 시장, 분석 시점, 데이터 신선도, 부족 데이터를 표시한다.\n'
        '4. 주문 실행, 계좌 작업, 비밀 조회, 파괴적 파일 작업은 금지한다.\n'
        '5. Telegram 전송과 workflow 실행은 운영자가 승인한 mutation gate를 통과한 경우에만 수행한다.\n'
        '6. 결론은 확률적 언어로 표현하고 과장 표현을 피한다.'
    )
    return {
        'name': 'marketflow-mirofish-hermes-prompts',
        'language': 'ko',
        'system_prompt': system_prompt,
        'task_prompts': {
            'scanner_health': (
                'MarketFlow MCP에서 get_autonomous_status, get_market_clock, '
                'get_pipeline_operating_snapshot, get_mcp_resource_snapshot을 읽고 '
                '오늘 알파 스캐너가 지속 감시 가능한 상태인지 점검해라.'
            ),
            'top3_dry_run': (
                '새 스캐너 이벤트를 실제 전송 없이 dry-run으로 Top 3 분석 계획까지 점검해라. '
                '후보 종목별 데이터 신선도, 리스크 필터, GraphRAG 근거, 사후 검증 가능성을 표시해라.'
            ),
            'post_close_learning': (
                '최근 workflow의 사후 성과 피드백을 look-ahead bias 없이 점검하고, '
                '알파 점수 보정에 유효한 신호와 무효 신호를 분리해라.'
            ),
            'telegram_preview': (
                '최신 Top 3 텔레그램 메시지를 전송하지 말고 한국어 운영자 검토용으로 미리보기만 작성해라.'
            ),
        },
        'generated_at': _now_iso(),
    }


def preview_hermes_task(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a non-executing plan for a Hermes sidecar task."""
    payload = payload or {}
    task = str(payload.get('task') or 'top3_dry_run').strip() or 'top3_dry_run'
    plans = {
        'scanner_health': [
            {'tool': 'get_autonomous_status', 'args': {}},
            {'tool': 'get_market_clock', 'args': {}},
            {'tool': 'get_pipeline_operating_snapshot', 'args': {}},
            {'tool': 'get_mcp_resource_snapshot', 'args': {'include_deferred': True}},
        ],
        'top3_dry_run': [
            {'tool': 'get_market_clock', 'args': {}},
            {'tool': 'list_recent_scanner_runs', 'args': {'limit': 5}},
            {'tool': 'run_autonomous_scan_analysis', 'args': {
                'dry_run': True,
                'sync': False,
                'send_telegram': False,
                'limit': int(payload.get('limit') or 20),
                'max_events': int(payload.get('max_events') or 5),
                'top_n': int(payload.get('top_n') or 3),
                'refresh_learning': True,
            }},
            {'tool': 'get_top3_summary', 'args': {}},
        ],
        'post_close_learning': [
            {'tool': 'get_market_clock', 'args': {}},
            {'tool': 'list_recent_workflows', 'args': {'limit': 10}},
            {'tool': 'refresh_learning_feedback', 'args': {
                'limit': int(payload.get('limit') or 20),
                'commit': False,
            }},
        ],
        'telegram_preview': [
            {'tool': 'get_top3_summary', 'args': {}},
            {'tool': 'get_workflow_share_payload', 'args': {}},
        ],
    }
    selected = plans.get(task, plans['top3_dry_run'])
    return {
        'service': 'mirofish-hermes-bridge-preview',
        'task': task,
        'dry_run_only': True,
        'executes_tools': False,
        'planned_tool_calls': selected,
        'mutation_blocked': any(step['tool'] in GUARDED_MUTATION_TOOLS for step in selected),
        'operator_note': (
            'This endpoint only previews the Hermes workflow. It does not call MCP tools, '
            'send Telegram messages, or change scanner state.'
        ),
        'generated_at': _now_iso(),
    }


def _default_python_command() -> Path | str:
    venv_python = REPO_ROOT / '.venv' / 'Scripts' / 'python.exe'
    if venv_python.exists():
        return venv_python
    return 'python'


def _stdio_server_config() -> dict[str, Any]:
    return {
        'command': str(_default_python_command()),
        'args': [
            str(MCP_ENTRYPOINT),
            '--transport',
            'stdio',
        ],
        'env': {
            'PYTHONIOENCODING': 'utf-8',
            'HOME_SERVER': 'marketflow',
        },
    }


def _http_server_config() -> dict[str, Any]:
    return {
        'url': f'http://127.0.0.1:{DEFAULT_MCP_PORT}{DEFAULT_MCP_PATH}',
        'server_command': str(_default_python_command()),
        'server_args': [
            str(MCP_ENTRYPOINT),
            '--transport',
            'streamable-http',
            '--host',
            '127.0.0.1',
            '--port',
            str(DEFAULT_MCP_PORT),
            '--path',
            DEFAULT_MCP_PATH,
        ],
    }


def _stdio_add_command() -> str:
    args = ' '.join(f'--args "{arg}"' for arg in _stdio_server_config()['args'])
    return f'hermes mcp add marketflow_mirofish --command "{_stdio_server_config()["command"]}" {args}'


def _cron_recipes() -> list[dict[str, Any]]:
    return [
        {
            'name': 'kr_pre_open_scanner_health',
            'schedule_kst': '08:45 market days',
            'task': 'scanner_health',
            'send_telegram': False,
            'purpose': 'Confirm data freshness and scanner readiness before the Korean market opens.',
        },
        {
            'name': 'kr_intraday_top3_watch',
            'schedule_kst': 'every 15 minutes during 09:00-15:30 market session',
            'task': 'top3_dry_run first; guarded send only for new events',
            'send_telegram': 'guarded',
            'purpose': 'Detect new scanner events, batch up to 5 candidates, analyze, and rank Top 3.',
        },
        {
            'name': 'kr_post_close_learning',
            'schedule_kst': '16:20 market days',
            'task': 'post_close_learning',
            'send_telegram': False,
            'purpose': 'Refresh outcome feedback without look-ahead bias.',
        },
    ]


def _repo_relative(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _command_path_exists(command: Path | str) -> bool:
    if isinstance(command, Path):
        return command.exists()
    return True


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

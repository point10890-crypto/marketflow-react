import json

import pytest
from flask import Flask

from app.routes.admin_mirofish import admin_mirofish_bp
from app.services.mirofish import autonomous_mcp, pipeline_overview


def _candidate(symbol='000001', name='Alpha One'):
    return {
        'symbol': symbol,
        'display_name': name,
        'name': name,
        'market': 'KOSPI',
        'alpha_score': 82,
        'risk_score': 24,
        'action': 'BUY_CANDIDATE',
    }


def _event(symbol='000001'):
    return {
        'key': f'{symbol}:BUY_CANDIDATE:2026-05-10',
        'candidate': _candidate(symbol),
    }


def _workflow_result():
    return {
        'ok': True,
        'id': 'wfmcp_test',
        'status': 'completed',
        'scanner_run_id': 'mfas_test',
        'event_count': 1,
        'analysis_runs': [{'symbol': '000001'}],
        'top3': [
            {
                'symbol': '000001',
                'target': 'Alpha One',
                'market': 'KOSPI',
                'candidate': _candidate(),
                'verdict': {'action': 'BUY', 'confidence_pct': 80},
            }
        ],
        'outcome_status': 'pending',
    }


@pytest.fixture
def isolated_autonomous_paths(tmp_path, monkeypatch):
    root = tmp_path / 'autonomous'
    monkeypatch.setattr(autonomous_mcp, 'AUTONOMOUS_ROOT', root)
    monkeypatch.setattr(autonomous_mcp, 'AUDIT_LOG_PATH', root / 'audit.jsonl')
    monkeypatch.setattr(autonomous_mcp, 'LEARNING_FEEDBACK_PATH', root / 'learning_feedback.json')
    return root


def test_candidate_detection_defaults_to_dry_run_without_telegram(isolated_autonomous_paths, monkeypatch):
    monkeypatch.setattr(
        autonomous_mcp.alpha_scanner,
        'run_scanner_alert_check',
        lambda *args, **kwargs: {
            'run': {'id': 'mfas_test', 'candidate_count': 1},
            'events': [_event()],
            'message': '<b>preview</b>',
            'alert_blocked': False,
            'blocked_reason': None,
        },
    )
    commit_calls = []
    monkeypatch.setattr(
        autonomous_mcp.alpha_scanner,
        'commit_scanner_alert_events',
        lambda result: commit_calls.append(result) or {'committed': True},
    )

    result = autonomous_mcp.run_candidate_detection_alert({'limit': 10})

    assert result['status'] == 'dry_run'
    assert result['dry_run'] is True
    assert result['telegram_sent'] is False
    assert result['state_committed'] is False
    assert result['events'][0]['symbol'] == '000001'
    assert commit_calls == []


def test_candidate_detection_commits_when_aibain_send_succeeds(isolated_autonomous_paths, monkeypatch):
    monkeypatch.setenv(autonomous_mcp.MUTATION_ENV, 'true')
    monkeypatch.setenv(autonomous_mcp.SHARED_SECRET_ENV, 'secret-1')
    monkeypatch.setattr(
        autonomous_mcp.alpha_scanner,
        'run_scanner_alert_check',
        lambda *args, **kwargs: {
            'run': {'id': 'mfas_test', 'candidate_count': 1},
            'events': [_event()],
            'message': '<b>scanner event</b>',
            'alert_blocked': False,
            'blocked_reason': None,
        },
    )
    commit_calls = []
    monkeypatch.setattr(
        autonomous_mcp.alpha_scanner,
        'commit_scanner_alert_events',
        lambda result: commit_calls.append(result) or {'committed': True},
    )
    from app.utils import aibain_notify
    monkeypatch.setattr(aibain_notify, 'send_scanner_alert', lambda message: True)

    result = autonomous_mcp.run_candidate_detection_alert(
        {
            'dry_run': False,
            'send_telegram': True,
            'confirmation': autonomous_mcp.CONFIRM_SEND_PHRASE,
            'api_key': 'secret-1',
            'commit_state': True,
        },
        send_fn=lambda message: False,
    )

    assert result['status'] == 'sent'
    assert result['telegram_sent'] is False
    assert result['aibain_sent'] is True
    assert result['ok'] is True
    assert result['state_committed'] is True
    assert len(commit_calls) == 1


def test_autonomous_status_exposes_safe_mcp_policy(monkeypatch):
    monkeypatch.delenv(autonomous_mcp.MUTATION_ENV, raising=False)
    monkeypatch.delenv(autonomous_mcp.SHARED_SECRET_ENV, raising=False)
    monkeypatch.setattr(
        autonomous_mcp,
        '_mcp_http_status',
        lambda: {
            'url': 'http://127.0.0.1:8765/mcp',
            'healthy': True,
            'status_code': 200,
            'server_name': 'MarketFlow MiroFish Autonomous MCP',
            'server_version': 'test',
            'checked_at': '2026-05-11T00:00:00+00:00',
        },
    )
    monkeypatch.setattr(
        autonomous_mcp,
        '_scheduled_task_status',
        lambda task_name: {
            'task_name': task_name,
            'registered': True,
            'query_ok': True,
            'last_result': '0',
            'checked_at': '2026-05-11T00:00:00+00:00',
        },
    )
    monkeypatch.setattr(
        autonomous_mcp.pipeline_overview,
        'get_pipeline_operating_snapshot',
        lambda: {
            'schema_version': 'mirofish.operating_workflow.v1',
            'current_stage_id': 'top3',
            'stages': [{'id': 'scanner'}, {'id': 'top3'}],
        },
    )

    status = autonomous_mcp.get_autonomous_status()
    policy = autonomous_mcp.get_mcp_security_policy()

    assert 'get_autonomous_status' in status['tools']
    assert 'get_mcp_security_policy' in status['tools']
    assert 'get_market_clock' in status['tools']
    assert 'get_pipeline_operating_snapshot' in status['tools']
    assert 'get_repository_state' in status['tools']
    assert 'get_alpha_research_snapshot' in status['tools']
    assert 'list_safe_artifacts' in status['tools']
    assert 'read_safe_artifact' in status['tools']
    assert status['runtime']['mcp_server']['healthy'] is True
    assert status['operating_workflow']['schema_version'] == 'mirofish.operating_workflow.v1'
    assert 'mirofish://pipeline/operating' in status['resources']
    assert 'mirofish://scanner/research' in status['resources']
    assert status['runtime']['startup_task']['registered'] is True
    assert status['runtime']['watchdog_task']['registered'] is True
    assert policy['mutation_enabled'] is False
    assert policy['shared_secret_configured'] is False
    assert policy['artifact_allowlist_root'] == 'data/admin_mirofish'
    assert 'get_pipeline_operating_snapshot' in policy['read_only_tools']
    assert 'get_alpha_research_snapshot' in policy['read_only_tools']
    assert 'read_safe_artifact' in policy['read_only_tools']
    assert 'run_autonomous_scan_analysis' in policy['mutating_tools']


def test_alpha_research_snapshot_tool_is_read_only(monkeypatch):
    calls = []
    monkeypatch.setattr(
        autonomous_mcp.alpha_research,
        'build_alpha_research_snapshot',
        lambda run_id=None, limit=20: calls.append((run_id, limit)) or {
            'ok': True,
            'status': 'ready',
            'schema_version': 'mirofish.alpha_research.v1',
            'run': {'id': run_id or 'latest'},
        },
    )

    snapshot = autonomous_mcp.get_alpha_research_snapshot(run_id='mfas_test', limit=5)

    assert snapshot['ok'] is True
    assert snapshot['run']['id'] == 'mfas_test'
    assert calls == [('mfas_test', 5)]


def test_pipeline_operating_snapshot_is_machine_readable(monkeypatch):
    monkeypatch.setattr(
        pipeline_overview.alpha_scanner,
        'get_scanner_schedule_status',
        lambda now=None: {
            'last_run_id': 'mfas_test',
            'last_run_at': '2026-05-12T09:00:00+09:00',
            'candidate_count': 12,
            'freshness_status': 'fresh',
        },
    )
    monkeypatch.setattr(
        pipeline_overview,
        '_count_scanner_runs_today',
        lambda now_kst: 1,
    )
    monkeypatch.setattr(
        pipeline_overview,
        '_alerts_today',
        lambda now_kst: {
            'scanner_alerts_today': 0,
            'scanner_last_alert_at': None,
        },
    )
    monkeypatch.setattr(
        pipeline_overview.workflow_svc,
        'read_latest_workflow',
        lambda: {
            'id': 'wfmcp_test',
            'status': 'completed',
            'created_at': '2026-05-12T00:00:00+00:00',
            'completed_at': '2026-05-12T00:05:00+00:00',
            'scanner_run_id': 'mfas_test',
            'event_count': 5,
            'analysis_runs': [{'symbol': '000001'} for _ in range(5)],
            'top3': [{'symbol': '000001'}, {'symbol': '000002'}, {'symbol': '000003'}],
            'event_state_committed': True,
            'outcome_status': 'pending',
        },
    )

    snapshot = pipeline_overview.get_pipeline_operating_snapshot()
    stage_ids = [stage['id'] for stage in snapshot['stages']]
    stages = {stage['id']: stage for stage in snapshot['stages']}

    assert snapshot['schema_version'] == 'mirofish.operating_workflow.v1'
    assert stage_ids == ['scanner', 'batch', 'graphrag', 'top3', 'telegram', 'outcomes']
    assert snapshot['workflow_id'] == 'wfmcp_test'
    assert stages['scanner']['status'] == 'complete'
    assert stages['graphrag']['progress_pct'] == 100.0
    assert stages['top3']['count'] == 3
    assert stages['telegram']['status'] == 'complete'
    assert stages['outcomes']['status'] == 'ready'


def test_safe_artifact_reads_are_allowlisted(tmp_path, monkeypatch):
    safe_root = tmp_path / 'admin_mirofish'
    run_dir = safe_root / 'scanner_runs' / 'mfas_test'
    run_dir.mkdir(parents=True)
    (run_dir / 'run.json').write_text(json.dumps({'id': 'mfas_test'}), encoding='utf-8')
    (safe_root / 'secret.txt').write_text('not allowed', encoding='utf-8')
    monkeypatch.setattr(autonomous_mcp, 'SAFE_ARTIFACT_ROOT', safe_root)

    listing = autonomous_mcp.list_safe_artifacts(kind='scanner_runs', limit=10)
    result = autonomous_mcp.read_safe_artifact('scanner_runs/mfas_test/run.json')

    assert listing['items'][0]['path'] == 'scanner_runs/mfas_test/run.json'
    assert result['ok'] is True
    assert result['content']['id'] == 'mfas_test'
    with pytest.raises(ValueError):
        autonomous_mcp.read_safe_artifact('../.env')
    with pytest.raises(ValueError):
        autonomous_mcp.read_safe_artifact(str(run_dir / 'run.json'))
    with pytest.raises(ValueError):
        autonomous_mcp.read_safe_artifact('secret.txt')


def test_mutating_tools_require_guard_and_redact_secret(isolated_autonomous_paths, monkeypatch):
    monkeypatch.delenv(autonomous_mcp.MUTATION_ENV, raising=False)

    with pytest.raises(PermissionError):
        autonomous_mcp.run_autonomous_scan_analysis({
            'dry_run': False,
            'send_telegram': True,
            'api_key': 'sk_super_secret',
            'confirmation': autonomous_mcp.CONFIRM_SEND_PHRASE,
        })

    audit = (isolated_autonomous_paths / 'audit.jsonl').read_text(encoding='utf-8')
    assert 'rejected' in audit
    assert 'sk_super_secret' not in audit
    assert '[REDACTED]' in audit


def test_autonomous_scan_sends_telegram_then_commits_state(isolated_autonomous_paths, monkeypatch):
    monkeypatch.setenv(autonomous_mcp.MUTATION_ENV, 'true')
    monkeypatch.setenv(autonomous_mcp.SHARED_SECRET_ENV, 'secret-1')
    monkeypatch.setattr(
        autonomous_mcp.workflow,
        'start_workflow_from_scanner_events',
        lambda *args, **kwargs: _workflow_result(),
    )
    monkeypatch.setattr(
        autonomous_mcp.workflow,
        'build_workflow_top3_telegram_message',
        lambda result: '<b>MiroFish Top 1</b>',
    )
    commit_calls = []
    monkeypatch.setattr(
        autonomous_mcp.workflow,
        'commit_workflow_event_state',
        lambda result: commit_calls.append(result) or {'committed': True},
    )
    monkeypatch.setattr(
        autonomous_mcp,
        'refresh_learning_feedback',
        lambda payload: {
            'generated_at': '2026-05-10T00:00:00+00:00',
            'workflow_count': 1,
            'evaluated_count': 1,
            'hit_rate_pct': 100.0,
            'average_forward_return_pct': 8.0,
            'production_weights_mutated': False,
            'recommendations': [],
        },
    )
    sent = []

    result = autonomous_mcp.run_autonomous_scan_analysis(
        {
            'dry_run': False,
            'sync': True,
            'send_telegram': True,
            'confirmation': autonomous_mcp.CONFIRM_SEND_PHRASE,
            'api_key': 'secret-1',
            'commit_event_state': True,
        },
        send_fn=lambda message: sent.append(message) or True,
    )

    assert result['status'] == 'completed'
    assert result['telegram_sent'] is True
    assert result['event_state_committed'] is True
    assert result['top_symbols'] == ['000001']
    assert sent == ['<b>MiroFish Top 1</b>']
    assert len(commit_calls) == 1


def test_autonomous_scan_commits_state_when_aibain_delivery_succeeds(isolated_autonomous_paths, monkeypatch):
    monkeypatch.setenv(autonomous_mcp.MUTATION_ENV, 'true')
    monkeypatch.setenv(autonomous_mcp.SHARED_SECRET_ENV, 'secret-1')
    monkeypatch.setattr(
        autonomous_mcp.workflow,
        'start_workflow_from_scanner_events',
        lambda *args, **kwargs: _workflow_result(),
    )
    monkeypatch.setattr(
        autonomous_mcp.workflow,
        'build_workflow_top3_telegram_message',
        lambda result: '<b>MiroFish Top 1</b>',
    )
    commit_calls = []
    monkeypatch.setattr(
        autonomous_mcp.workflow,
        'commit_workflow_event_state',
        lambda result: commit_calls.append(result) or {'committed': True},
    )
    monkeypatch.setattr(
        autonomous_mcp,
        'refresh_learning_feedback',
        lambda payload: {
            'generated_at': '2026-05-10T00:00:00+00:00',
            'workflow_count': 1,
            'evaluated_count': 1,
            'hit_rate_pct': 100.0,
            'average_forward_return_pct': 8.0,
            'production_weights_mutated': False,
            'recommendations': [],
        },
    )
    from app.utils import aibain_notify
    monkeypatch.setattr(aibain_notify, 'send_workflow_top3', lambda message: True)

    result = autonomous_mcp.run_autonomous_scan_analysis(
        {
            'dry_run': False,
            'sync': True,
            'send_telegram': True,
            'confirmation': autonomous_mcp.CONFIRM_SEND_PHRASE,
            'api_key': 'secret-1',
            'commit_event_state': True,
        },
        send_fn=lambda message: False,
    )

    assert result['status'] == 'completed'
    assert result['telegram_sent'] is False
    assert result['aibain_sent'] is True
    assert result['event_state_committed'] is True
    assert len(commit_calls) == 1


def test_learning_feedback_is_advisory_and_lookahead_safe(isolated_autonomous_paths, monkeypatch):
    monkeypatch.setenv(autonomous_mcp.MUTATION_ENV, 'true')
    monkeypatch.setattr(
        autonomous_mcp.workflow,
        'list_workflows',
        lambda limit=20: [{'id': 'wfmcp_test', 'status': 'completed'}],
    )
    monkeypatch.setattr(
        autonomous_mcp.workflow,
        'read_workflow',
        lambda workflow_id: {'id': workflow_id, 'status': 'completed'},
    )
    monkeypatch.setattr(
        autonomous_mcp.outcome_tracker,
        'refresh_workflow_outcomes',
        lambda workflow_id, workflow=None: {
            'workflow_id': workflow_id,
            'status': 'evaluated',
            'summary': {'hit_rate_pct': 50.0},
            'items': [
                {
                    'symbol': '000001',
                    'status': 'evaluated',
                    'hit': True,
                    'forward_return_pct': 6.5,
                    'feature_snapshot': {
                        'alpha_score': 82,
                        'risk_score': 24,
                        'final_score': 88,
                        'signal_quality': 'high_conviction',
                        'strategy_tags': ['momentum', 'trend_quality'],
                        'scanner_action': 'BUY_CANDIDATE',
                        'cio_action': 'BUY',
                    },
                },
                {
                    'symbol': '000002',
                    'status': 'evaluated',
                    'hit': False,
                    'forward_return_pct': -2.0,
                    'feature_snapshot': {
                        'alpha_score': 68,
                        'risk_score': 52,
                        'final_score': 54,
                        'signal_quality': 'watch',
                        'strategy_tags': ['event_risk'],
                        'scanner_action': 'WATCH',
                        'cio_action': 'HOLD',
                    },
                },
            ],
        },
    )

    feedback = autonomous_mcp.refresh_learning_feedback({'commit': True, 'limit': 5})

    assert feedback['lookahead_safe'] is True
    assert feedback['production_weights_mutated'] is False
    assert feedback['evaluated_count'] == 2
    assert feedback['hit_rate_pct'] == 50.0
    assert feedback['average_forward_return_pct'] == 2.25
    assert feedback['alpha_memory']['available'] is True
    assert feedback['alpha_memory']['sample_count'] == 2
    assert feedback['alpha_memory']['strongest_positive']['key'] in {'momentum', 'trend_quality'}
    assert feedback['alpha_memory']['weakest_negative']['key'] == 'event_risk'
    saved = json.loads((isolated_autonomous_paths / 'learning_feedback.json').read_text(encoding='utf-8'))
    assert saved['mode'] == 'bounded_adaptive_policy_preview'
    assert saved['learning_policy']['primary_objective'] == 'improve Top3 alpha candidate detection from replay-safe outcomes'
    assert saved['learning_policy']['production_weights_mutated'] is False
    assert saved['alpha_memory']['score_profile']['hit_avg_alpha'] == 82
    summary = autonomous_mcp._learning_summary(feedback)
    assert summary['alpha_memory']['score_profile']['hit_avg_alpha'] == 82
    assert summary['alpha_memory']['cohorts']['strategy_tags'][0]['key'] in {'momentum', 'trend_quality'}
    assert summary['learning_policy']['available'] is True


def test_admin_autonomous_routes_are_registered():
    app = Flask(__name__)
    app.register_blueprint(admin_mirofish_bp, url_prefix='/api/admin/mirofish')

    rules = {str(rule) for rule in app.url_map.iter_rules()}

    assert '/api/admin/mirofish/autonomous/status' in rules
    assert '/api/admin/mirofish/autonomous/learning' in rules
    assert '/api/admin/mirofish/autonomous/candidate-alert' in rules
    assert '/api/admin/mirofish/autonomous/scan-analysis' in rules
    assert '/api/admin/mirofish/autonomous/learning/refresh' in rules
    assert '/api/admin/mirofish/autonomous/telegram/latest' in rules

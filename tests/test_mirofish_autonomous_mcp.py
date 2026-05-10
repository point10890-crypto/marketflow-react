import json

import pytest
from flask import Flask

from app.routes.admin_mirofish import admin_mirofish_bp
from app.services.mirofish import autonomous_mcp


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


def test_autonomous_status_exposes_safe_mcp_policy(monkeypatch):
    monkeypatch.delenv(autonomous_mcp.MUTATION_ENV, raising=False)
    monkeypatch.delenv(autonomous_mcp.SHARED_SECRET_ENV, raising=False)

    status = autonomous_mcp.get_autonomous_status()
    policy = autonomous_mcp.get_mcp_security_policy()

    assert 'get_autonomous_status' in status['tools']
    assert 'get_mcp_security_policy' in status['tools']
    assert 'get_market_clock' in status['tools']
    assert 'get_repository_state' in status['tools']
    assert 'list_safe_artifacts' in status['tools']
    assert 'read_safe_artifact' in status['tools']
    assert policy['mutation_enabled'] is False
    assert policy['shared_secret_configured'] is False
    assert policy['artifact_allowlist_root'] == 'data/admin_mirofish'
    assert 'read_safe_artifact' in policy['read_only_tools']
    assert 'run_autonomous_scan_analysis' in policy['mutating_tools']


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
                {'symbol': '000001', 'status': 'evaluated', 'hit': True, 'forward_return_pct': 6.5},
                {'symbol': '000002', 'status': 'evaluated', 'hit': False, 'forward_return_pct': -2.0},
            ],
        },
    )

    feedback = autonomous_mcp.refresh_learning_feedback({'commit': True, 'limit': 5})

    assert feedback['lookahead_safe'] is True
    assert feedback['production_weights_mutated'] is False
    assert feedback['evaluated_count'] == 2
    assert feedback['hit_rate_pct'] == 50.0
    assert feedback['average_forward_return_pct'] == 2.25
    saved = json.loads((isolated_autonomous_paths / 'learning_feedback.json').read_text(encoding='utf-8'))
    assert saved['mode'] == 'advisory_feedback_only'


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

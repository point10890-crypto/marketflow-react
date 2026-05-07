from datetime import datetime, timezone

from flask import Flask

from app.routes.admin_mirofish import admin_mirofish_bp
from app.services.mirofish import outcome_tracker, workflow


def _candidate(symbol, name, alpha, risk, rank=1, action='BUY_CANDIDATE'):
    return {
        'rank': rank,
        'symbol': symbol,
        'name': name,
        'display_name': name,
        'market': 'KOSPI',
        'action': action,
        'alpha_score': alpha,
        'risk_score': risk,
        'ranking_score': alpha - risk * 0.5,
        'signal_quality': 'high_conviction' if alpha >= 80 else 'actionable',
        'strategy_tags': ['momentum', 'trend_quality'],
        'analysis_profile': {'source_count': 4, 'trend_20d_pct': 20 + rank, 'volume_ratio': 1.5},
        'entry_plan': {'status': 'ready'},
        'price': {'date': '2026-05-07', 'current_price': 1000 * rank},
    }


def _scanner_result(candidates):
    return {
        'run': {
            'id': 'mfas_test',
            'candidate_count': len(candidates),
            'freshness': {'status': 'fresh'},
            'candidates': candidates,
        },
        'events': [
            {
                'event_key': f"{item['symbol']}:{item['action']}:2026-05-07",
                'key': f"{item['symbol']}:{item['action']}:2026-05-07",
                'candidate': item,
            }
            for item in candidates
        ],
        'new_event_count': len(candidates),
        'alert_blocked': False,
        'blocked_reason': None,
        'state_path': 'unused.json',
        'state': {},
    }


def _analysis_run(candidate, action='BUY', confidence=75, graph_links=40, brain_score=60):
    return {
        'id': f"mf_{candidate['symbol']}",
        'status': 'completed',
        'display_name': candidate['display_name'],
        'symbol': candidate['symbol'],
        'market': candidate['market'],
        'pipeline': {'graph_links': graph_links, 'similar_events': 3, 'graph_method': 'rule'},
        'brain': {'score': brain_score, 'regime': 'neutral', 'crisis': 'Lv.2'},
        'verdict': {
            'action': action,
            'label': action,
            'confidence_pct': confidence,
            'bullish': 5,
            'neutral': 4,
            'bearish': 1,
            'target': candidate['display_name'],
            'summary': f"{candidate['display_name']} {action}",
        },
        'artifacts': {'run': f"/api/admin/mirofish/runs/mf_{candidate['symbol']}"},
    }


def test_workflow_runs_multi_target_graphrag_and_selects_top3(tmp_path, monkeypatch):
    candidates = [
        _candidate('000001', 'Alpha One', 80, 20, 1),
        _candidate('000002', 'Beta Two', 76, 35, 2),
        _candidate('000003', 'Gamma Three', 90, 18, 3),
        _candidate('000004', 'Delta Four', 72, 40, 4),
    ]
    monkeypatch.setattr(workflow, 'WORKFLOWS_ROOT', str(tmp_path / 'workflows'))
    monkeypatch.setattr(workflow, 'WORKFLOW_STATE_ROOT', str(tmp_path / 'workflows' / '_state'))
    monkeypatch.setattr(workflow.alpha_scanner, 'run_scanner_alert_check', lambda *args, **kwargs: _scanner_result(candidates))
    monkeypatch.setattr(workflow.alpha_scanner, 'commit_scanner_alert_events', lambda result: {'committed': True})

    def fake_create(candidate, agent_count, mode):
        if candidate['symbol'] == '000002':
            return _analysis_run(candidate, action='HOLD', confidence=55, graph_links=20, brain_score=50)
        if candidate['symbol'] == '000004':
            return _analysis_run(candidate, action='SELL', confidence=62, graph_links=10, brain_score=45)
        return _analysis_run(candidate, action='BUY', confidence=80 if candidate['symbol'] == '000003' else 72, graph_links=60, brain_score=70)

    monkeypatch.setattr(workflow, '_create_analysis_run', fake_create)

    result = workflow.start_workflow_from_scanner_events(
        {'limit': 20, 'agent_count': 10, 'top_n': 3, 'max_parallel': 2},
        async_mode=False,
    )

    assert result['status'] == 'completed'
    assert result['event_count'] == 4
    assert len(result['analysis_runs']) == 4
    assert len(result['top3']) == 3
    assert result['top3'][0]['symbol'] == '000003'
    assert all(item['verdict']['target'] for item in result['top3'])
    assert result['summary']['top_symbols'] == [item['symbol'] for item in result['top3']]


def test_workflow_attaches_forward_outcomes_without_lookahead(tmp_path, monkeypatch):
    candidates = [_candidate('000001', 'Alpha One', 80, 20, 1)]
    price_history = tmp_path / 'daily_prices.csv'
    price_history.write_text(
        '\n'.join([
            'ticker,date,name,current_price,change,change_rate,high,low,open,volume,update_time',
            '000001,2026-05-07,Alpha One,9999,0,0,9999,9999,9999,10,now',
            '000001,2026-05-08,Alpha One,1010,0,0,1010,1010,1010,10,now',
            '000001,2026-05-11,Alpha One,1020,0,0,1020,1020,1020,10,now',
            '000001,2026-05-12,Alpha One,1030,0,0,1030,1030,1030,10,now',
            '000001,2026-05-13,Alpha One,1040,0,0,1040,1040,1040,10,now',
            '000001,2026-05-14,Alpha One,1100,0,0,1100,1100,1100,10,now',
        ]),
        encoding='utf-8',
    )
    monkeypatch.setattr(workflow, 'WORKFLOWS_ROOT', str(tmp_path / 'workflows'))
    monkeypatch.setattr(workflow, 'WORKFLOW_STATE_ROOT', str(tmp_path / 'workflows' / '_state'))
    monkeypatch.setattr(outcome_tracker, 'PRICE_HISTORY_PATH', str(price_history))
    monkeypatch.setattr(workflow.alpha_scanner, 'run_scanner_alert_check', lambda *args, **kwargs: _scanner_result(candidates))
    monkeypatch.setattr(workflow.alpha_scanner, 'commit_scanner_alert_events', lambda result: {'committed': True})
    monkeypatch.setattr(workflow, '_create_analysis_run', lambda candidate, agent_count, mode: _analysis_run(candidate, action='BUY', confidence=80))

    result = workflow.start_workflow_from_scanner_events(
        {'limit': 20, 'top_n': 1, 'max_parallel': 1},
        async_mode=False,
    )

    outcome = result['top3'][0]['outcome']
    assert outcome['lookahead_safe'] is True
    assert outcome['entry_date'] == '2026-05-07'
    assert outcome['entry_price'] == 1000
    assert outcome['horizons']['5']['exit_date'] == '2026-05-14'
    assert outcome['horizons']['5']['return_pct'] == 10.0
    assert outcome['forward_return_pct'] == 10.0
    assert outcome['hit'] is True
    assert result['summary']['outcome']['top3_hit_rate_pct'] == 100.0
    assert (tmp_path / 'workflows' / result['id'] / 'outcomes.json').is_file()


def test_workflow_defaults_to_five_event_batch_and_top3(tmp_path, monkeypatch):
    candidates = [
        _candidate(f'00000{index}', f'Alpha {index}', 90 - index, 20 + index, index)
        for index in range(1, 7)
    ]
    monkeypatch.setattr(workflow, 'WORKFLOWS_ROOT', str(tmp_path / 'workflows'))
    monkeypatch.setattr(workflow, 'WORKFLOW_STATE_ROOT', str(tmp_path / 'workflows' / '_state'))
    monkeypatch.setattr(workflow.alpha_scanner, 'run_scanner_alert_check', lambda *args, **kwargs: _scanner_result(candidates[:kwargs['max_events']]))
    monkeypatch.setattr(workflow.alpha_scanner, 'commit_scanner_alert_events', lambda result: {'committed': True})
    monkeypatch.setattr(workflow, '_create_analysis_run', lambda candidate, agent_count, mode: _analysis_run(candidate, action='BUY', confidence=70))

    result = workflow.start_workflow_from_scanner_events({'limit': 20}, async_mode=False)

    assert result['status'] == 'completed'
    assert result['event_count'] == 5
    assert len(result['analysis_runs']) == 5
    assert len(result['top3']) == 3
    assert result['filters']['batch_size'] == 5
    assert result['filters']['top_n'] == 3


def test_workflow_returns_no_new_events_without_creating_batch(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow, 'WORKFLOWS_ROOT', str(tmp_path / 'workflows'))
    monkeypatch.setattr(workflow, 'WORKFLOW_STATE_ROOT', str(tmp_path / 'workflows' / '_state'))
    monkeypatch.setattr(workflow.alpha_scanner, 'run_scanner_alert_check', lambda *args, **kwargs: _scanner_result([]))

    result = workflow.start_workflow_from_scanner_events({'limit': 20}, async_mode=False)

    assert result['status'] == 'no_new_events'
    assert result['candidate_count'] == 0


def test_workflow_dry_run_previews_candidates(tmp_path, monkeypatch):
    candidates = [_candidate('000001', 'Alpha One', 80, 20, 1)]
    monkeypatch.setattr(workflow, 'WORKFLOWS_ROOT', str(tmp_path / 'workflows'))
    monkeypatch.setattr(workflow, 'WORKFLOW_STATE_ROOT', str(tmp_path / 'workflows' / '_state'))
    monkeypatch.setattr(workflow.alpha_scanner, 'run_scanner_alert_check', lambda *args, **kwargs: _scanner_result(candidates))

    result = workflow.start_workflow_from_scanner_events({'limit': 20, 'dry_run': True}, async_mode=False)

    assert result['status'] == 'dry_run'
    assert result['candidate_count'] == 1
    assert result['candidates'][0]['display_name'] == 'Alpha One'


def test_force_workflow_accepts_watch_candidates_for_top3_pipeline(tmp_path, monkeypatch):
    candidates = [_candidate('000001', 'Alpha One', 61, 35, 1, action='WATCH')]
    monkeypatch.setattr(workflow, 'WORKFLOWS_ROOT', str(tmp_path / 'workflows'))
    monkeypatch.setattr(workflow, 'WORKFLOW_STATE_ROOT', str(tmp_path / 'workflows' / '_state'))
    monkeypatch.setattr(workflow.alpha_scanner, 'create_scanner_run', lambda payload: _scanner_result(candidates)['run'])
    monkeypatch.setattr(workflow, '_create_analysis_run', lambda candidate, agent_count, mode: _analysis_run(candidate, action='HOLD', confidence=65))

    result = workflow.start_workflow_from_scanner_events(
        {'force': True, 'limit': 20, 'top_n': 1, 'max_parallel': 1},
        async_mode=False,
    )

    assert result['status'] == 'completed'
    assert result['event_count'] == 1
    assert result['top3'][0]['symbol'] == '000001'
    assert result['filters']['actions'] == ['BUY_CANDIDATE', 'WATCH']


def test_workflow_monitor_check_can_run_sync_without_committing_event_state(tmp_path, monkeypatch):
    candidates = [_candidate('000001', 'Alpha One', 80, 20, 1)]
    monkeypatch.setattr(workflow, 'WORKFLOWS_ROOT', str(tmp_path / 'workflows'))
    monkeypatch.setattr(workflow, 'WORKFLOW_STATE_ROOT', str(tmp_path / 'workflows' / '_state'))
    scanner_kwargs = {}
    def fake_scanner(*args, **kwargs):
        scanner_kwargs.update(kwargs)
        return _scanner_result(candidates)
    monkeypatch.setattr(workflow.alpha_scanner, 'run_scanner_alert_check', fake_scanner)
    commit_calls = []
    monkeypatch.setattr(workflow.alpha_scanner, 'commit_scanner_alert_events', lambda result: commit_calls.append(result) or {'committed': True})
    monkeypatch.setattr(workflow, '_create_analysis_run', lambda candidate, agent_count, mode: _analysis_run(candidate))

    result = workflow.run_workflow_monitor_check({
        'limit': 20,
        'sync': True,
        'commit_event_state': False,
        'top_n': 1,
        'max_parallel': 1,
    })

    assert result['status'] == 'completed'
    assert result['event_state_committed'] is False
    assert scanner_kwargs['block_on_stale'] is False
    assert commit_calls == []


def test_build_workflow_top3_telegram_message_names_exact_targets():
    candidate = _candidate('000001', 'Alpha One', 80, 20, 1)
    message = workflow.build_workflow_top3_telegram_message({
        'id': 'mcp_test123',
        'scanner_run_id': 'mfas_test',
        'scanner_freshness': {'status': 'fresh'},
        'event_count': 1,
        'completed_at': '2026-05-07T12:00:00+00:00',
        'analysis_runs': [{'symbol': '000001'}],
        'summary': {'top_count': 1},
        'top3': [{
            'candidate': candidate,
            'target': 'Alpha One',
            'symbol': '000001',
            'market': 'KOSPI',
            'final_score': 88.5,
            'verdict': {'action': 'BUY', 'confidence_pct': 75},
            'graph': {'links': 42},
            'brain': {'score': 63, 'regime': 'neutral'},
            'reason': 'Alpha One final_score=88.5',
        }],
    })

    assert 'MiroFish MCP Top 3' in message
    assert 'Alpha One' in message
    assert '000001' in message
    assert 'Final score' in message
    assert 'Freshness' in message


def test_commit_workflow_event_state_uses_workflow_state_file(tmp_path, monkeypatch):
    candidate = _candidate('000001', 'Alpha One', 80, 20, 1)
    monkeypatch.setattr(workflow, 'WORKFLOWS_ROOT', str(tmp_path / 'workflows'))
    monkeypatch.setattr(workflow, 'WORKFLOW_STATE_ROOT', str(tmp_path / 'workflows' / '_state'))
    captured = {}

    def fake_commit(result):
        captured.update(result)
        return {'sent_event_count': len(result['events'])}

    monkeypatch.setattr(workflow.alpha_scanner, 'commit_scanner_alert_events', fake_commit)

    state = workflow.commit_workflow_event_state({
        'id': 'mcp_test123',
        'created_at': '2026-05-07T12:00:00+00:00',
        'scanner_run_id': 'mfas_test',
        'scanner_candidate_count': 1,
        'event_count': 1,
        'candidates': [candidate],
        'top3': [],
    })

    assert state == {'sent_event_count': 1}
    assert captured['state_path'].endswith('scanner_event_state.json')
    assert captured['run']['id'] == 'mfas_test'
    assert captured['events'][0]['event_key'] == '000001:BUY_CANDIDATE:2026-05-07'


def test_admin_mirofish_workflow_routes_are_registered():
    app = Flask(__name__)
    app.register_blueprint(admin_mirofish_bp, url_prefix='/api/admin/mirofish')

    rules = {str(rule) for rule in app.url_map.iter_rules()}

    assert '/api/admin/mirofish/workflow/status' in rules
    assert '/api/admin/mirofish/workflow/scan-analyze' in rules
    assert '/api/admin/mirofish/workflows' in rules
    assert '/api/admin/mirofish/workflows/latest' in rules
    assert '/api/admin/mirofish/workflows/<workflow_id>' in rules
    assert '/api/admin/mirofish/workflows/<workflow_id>/outcomes' in rules
    assert '/api/admin/mirofish/workflows/<workflow_id>/outcomes/refresh' in rules

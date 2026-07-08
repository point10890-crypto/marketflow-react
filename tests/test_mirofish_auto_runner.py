from datetime import datetime, timedelta, timezone

from app.services.mirofish import auto_runner


def _gate(results, name):
    return next(item for item in results['gates'] if item['name'] == name)


def _patch_base(monkeypatch):
    now_utc = datetime.now(timezone.utc)
    now_kst = datetime(2026, 5, 18, 10, 0, tzinfo=auto_runner.KST)
    monkeypatch.setattr(auto_runner, '_now_kst', lambda: now_kst)
    monkeypatch.setattr(
        auto_runner,
        '_read_state',
        lambda: {'phase': 'IDLE', 'paused': False, 'today': {}},
    )
    monkeypatch.setattr(
        auto_runner.alpha_scanner,
        'run_scanner_alert_check',
        lambda *args, **kwargs: {
            'events': [],
            'alert_blocked': False,
            'blocked_reason': None,
        },
    )
    return now_utc


def test_auto_runner_accepts_fresh_monitor_when_latest_run_is_unchanged(monkeypatch):
    now_utc = _patch_base(monkeypatch)
    monkeypatch.setattr(
        auto_runner.alpha_scanner,
        'get_scanner_schedule_status',
        lambda now=None: {
            'last_run_at': (now_utc - timedelta(minutes=30)).isoformat(),
            'freshness_status': 'fresh',
        },
    )
    monkeypatch.setattr(
        auto_runner.alpha_scanner,
        'read_scanner_monitor_state',
        lambda: {
            'last_checked_at': (now_utc - timedelta(seconds=45)).isoformat(),
            'last_status': 'unchanged',
            'source_changed': False,
        },
    )

    result = auto_runner._evaluate_gates(force=False, tuning=auto_runner._tunables())

    scanner_gate = _gate(result, 'scanner_freshness')
    assert scanner_gate['ok'] is True
    assert 'monitor' in scanner_gate['detail']
    assert result['failed_reason'].startswith('new_events:')


def test_auto_runner_blocks_when_run_and_monitor_are_stale(monkeypatch):
    now_utc = _patch_base(monkeypatch)
    monkeypatch.setattr(
        auto_runner.alpha_scanner,
        'get_scanner_schedule_status',
        lambda now=None: {
            'last_run_at': (now_utc - timedelta(minutes=30)).isoformat(),
            'freshness_status': 'fresh',
        },
    )
    monkeypatch.setattr(
        auto_runner.alpha_scanner,
        'read_scanner_monitor_state',
        lambda: {
            'last_checked_at': (now_utc - timedelta(minutes=30)).isoformat(),
            'last_status': 'unchanged',
            'source_changed': False,
        },
    )

    result = auto_runner._evaluate_gates(force=False, tuning=auto_runner._tunables())

    scanner_gate = _gate(result, 'scanner_freshness')
    assert scanner_gate['ok'] is False
    assert result['failed_reason'].startswith('scanner_freshness:')


def test_auto_runner_quality_hold_commits_events_without_telegram(monkeypatch):
    state = {
        'phase': 'IDLE',
        'paused': False,
        'today': {'triggers': 0, 'successes': 0, 'failures': 0, 'skip_reasons': {}},
        'recent_cycles': [],
    }
    writes = []
    monkeypatch.setattr(auto_runner, '_read_state', lambda: dict(state))
    monkeypatch.setattr(auto_runner, '_write_state', lambda payload: writes.append(payload))
    monkeypatch.setattr(auto_runner, '_append_history', lambda payload: writes.append({'history': payload}))
    monkeypatch.setattr(
        auto_runner.workflow_svc,
        'start_workflow_from_scanner_events',
        lambda **kwargs: {
            'id': 'mcp_low_quality',
            'status': 'completed',
            'top3': [{'symbol': '000001', 'final_score': 40.0}],
            'summary': {
                'quality': {
                    'recommendation': 'hold',
                    'reasons': ['best_score_below_floor'],
                },
            },
        },
    )
    commit_calls = []
    monkeypatch.setattr(
        auto_runner.workflow_svc,
        'commit_workflow_event_state',
        lambda result, **kwargs: commit_calls.append((result, kwargs)) or {},
    )
    monkeypatch.setattr(
        auto_runner.workflow_svc,
        'build_workflow_top3_telegram_message',
        lambda result: (_ for _ in ()).throw(AssertionError('telegram message should not be built')),
    )

    tuning = auto_runner._tunables()
    tuning['min_top_score'] = 50
    result = auto_runner._fire_workflow(tuning, {}, {'outcome': 'triggered'}, 0.0)

    assert result['success'] is True
    assert result['quality_hold'] is True
    assert result['telegram_ok'] is False
    assert result['quality_reason'] == 'best_score_below_floor'
    assert commit_calls
    assert commit_calls[0][1] == {'sync_dashboard': False}
    assert any(item.get('history', {}).get('outcome') == 'quality_hold' for item in writes)


def test_tunables_use_agent_override_when_env_unset(monkeypatch):
    from app.services.mirofish import agent_actions

    monkeypatch.delenv('MIROFISH_AUTO_RUNNER_MIN_ALPHA', raising=False)
    monkeypatch.setattr(agent_actions, 'param_override', lambda name: 73.0 if name == 'min_alpha' else None)

    assert auto_runner._tunables()['min_alpha'] == 73.0


def test_tunables_env_beats_agent_override(monkeypatch):
    from app.services.mirofish import agent_actions

    monkeypatch.setenv('MIROFISH_AUTO_RUNNER_MIN_ALPHA', '68')
    monkeypatch.setattr(agent_actions, 'param_override', lambda _name: 73.0)

    assert auto_runner._tunables()['min_alpha'] == 68.0

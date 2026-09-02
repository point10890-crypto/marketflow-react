from datetime import datetime, timedelta, timezone
from contextlib import contextmanager

import pytest

from app.services.mirofish import auto_runner


@pytest.fixture(autouse=True)
def _isolate_canonical_alert_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(auto_runner.alpha_scanner, 'DATA_ROOT', str(tmp_path))


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
    tuning['dry_run'] = False
    tuning['min_top_score'] = 50
    result = auto_runner._fire_workflow(tuning, {}, {'outcome': 'triggered'}, 0.0)

    assert result['success'] is True
    assert result['quality_hold'] is True
    assert result['telegram_ok'] is False
    assert result['quality_reason'] == 'best_score_below_floor'
    assert commit_calls
    assert commit_calls[0][1] == {'sync_dashboard': False}
    assert any(item.get('history', {}).get('outcome') == 'quality_hold' for item in writes)


def test_auto_runner_holds_canonical_guard_through_workflow_send_and_commit(monkeypatch):
    """The trusted Top3 runner must not race verified or realtime alert delivery."""
    state = {
        'phase': 'IDLE',
        'paused': False,
        'today': {'triggers': 0, 'successes': 0, 'failures': 0, 'skip_reasons': {}},
        'recent_cycles': [],
    }
    active = {'value': False, 'entries': 0}

    @contextmanager
    def guard(*args, **kwargs):
        active['entries'] += 1
        active['value'] = True
        try:
            yield 'canonical-state.json'
        finally:
            active['value'] = False

    result = {
        'id': 'mcp_guarded',
        'status': 'completed',
        'top3': [{'symbol': '000001', 'final_score': 88.0}],
        'event_candidates': [{
            'symbol': '000001',
            'action': 'BUY_CANDIDATE',
            'price': {'date': '2026-08-21'},
        }],
        'summary': {'quality': {'recommendation': 'send', 'reasons': []}},
    }

    def start(**kwargs):
        assert active['value'] is False
        return result

    def should_send(payload, **kwargs):
        assert active['value'] is False
        return True, 'quality_gate_passed'

    def build(payload):
        assert active['value'] is False
        return '<b>guarded top3</b>'

    def revalidate(candidates, **kwargs):
        assert active['value'] is True
        return {
            'ok': True,
            'status': 'ready',
            'event_keys': ['000001:BUY_CANDIDATE:2026-08-21'],
            'conflicting_event_keys': [],
        }

    def send(message, **kwargs):
        assert active['value'] is True
        return True

    def commit(payload, **kwargs):
        assert active['value'] is True
        return {'committed': True}

    monkeypatch.setattr(auto_runner.alpha_scanner, 'scanner_alert_delivery_guard', guard)
    monkeypatch.setattr(auto_runner.alpha_scanner, 'revalidate_scanner_alert_delivery', revalidate)
    monkeypatch.setattr(auto_runner, '_read_state', lambda: dict(state))
    monkeypatch.setattr(auto_runner, '_write_state', lambda payload: None)
    monkeypatch.setattr(auto_runner, '_append_history', lambda payload: None)
    monkeypatch.setattr(auto_runner, '_record_success', lambda *args, **kwargs: None)
    monkeypatch.setattr(auto_runner.workflow_svc, 'start_workflow_from_scanner_events', start)
    monkeypatch.setattr(auto_runner.workflow_svc, 'should_send_workflow_top3', should_send)
    monkeypatch.setattr(auto_runner.workflow_svc, 'build_workflow_top3_telegram_message', build)
    monkeypatch.setattr(auto_runner.workflow_svc, 'commit_workflow_event_state', commit)
    monkeypatch.setattr(auto_runner, '_build_deep_enrich_message', lambda top3: '')
    from app.utils import scheduler, aibain_notify
    monkeypatch.setattr(scheduler, '_send_telegram_long', send)
    monkeypatch.setattr(aibain_notify, 'send_workflow_top3', lambda message: False)
    tuning = auto_runner._tunables()
    tuning['dry_run'] = False
    tuning['min_top_score'] = 50

    outcome = auto_runner._fire_workflow(tuning, {}, {'outcome': 'triggered'}, 0.0)

    assert outcome['success'] is True
    assert outcome['telegram_ok'] is True
    assert active == {'value': False, 'entries': 1}


def test_auto_runner_canonical_overlap_skips_transport_and_dashboard_overwrite(monkeypatch):
    """A verified event claimed during analysis suppresses Top3 transport at final recheck."""
    state = {
        'phase': 'IDLE',
        'paused': False,
        'today': {'triggers': 0, 'successes': 0, 'failures': 0, 'skip_reasons': {}},
        'recent_cycles': [],
    }
    result = {
        'id': 'mcp_overlap',
        'status': 'completed',
        'top3': [{'symbol': '000001', 'final_score': 88.0}],
        'event_candidates': [{
            'symbol': '000001', 'action': 'BUY_CANDIDATE', 'price': {'date': '2026-08-21'},
        }],
        'summary': {'quality': {'recommendation': 'send', 'reasons': []}},
    }
    monkeypatch.setattr(auto_runner, '_read_state', lambda: dict(state))
    monkeypatch.setattr(auto_runner, '_write_state', lambda payload: None)
    monkeypatch.setattr(auto_runner, '_append_history', lambda payload: None)
    monkeypatch.setattr(auto_runner, '_record_quality_hold', lambda *args, **kwargs: None)
    monkeypatch.setattr(auto_runner.workflow_svc, 'start_workflow_from_scanner_events', lambda **kwargs: result)
    monkeypatch.setattr(auto_runner.workflow_svc, 'should_send_workflow_top3', lambda *args, **kwargs: (True, 'ready'))
    monkeypatch.setattr(auto_runner.workflow_svc, 'build_workflow_top3_telegram_message', lambda payload: '<b>top3</b>')
    monkeypatch.setattr(auto_runner.alpha_scanner, 'revalidate_scanner_alert_delivery', lambda candidates: {
        'ok': False,
        'status': 'event_overlap',
        'event_keys': ['000001:BUY_CANDIDATE:2026-08-21'],
        'conflicting_event_keys': ['000001:BUY_CANDIDATE:2026-08-21'],
    })
    commits = []
    monkeypatch.setattr(
        auto_runner.workflow_svc,
        'commit_workflow_event_state',
        lambda payload, **kwargs: commits.append(kwargs) or {},
    )
    from app.utils import scheduler, aibain_notify
    monkeypatch.setattr(scheduler, '_send_telegram_long', pytest.fail)
    monkeypatch.setattr(aibain_notify, 'send_workflow_top3', pytest.fail)
    tuning = auto_runner._tunables()
    tuning.update({'dry_run': False, 'min_top_score': 50})

    outcome = auto_runner._fire_workflow(tuning, {}, {'outcome': 'triggered'}, 0.0)

    assert outcome['canonical_hold'] is True
    assert outcome['telegram_ok'] is False
    assert commits == [{'sync_dashboard': False}]


def test_auto_runner_delivery_guard_timeout_fails_without_transport(monkeypatch):
    """A busy canonical sender fails boundedly after analysis instead of deadlocking."""
    state = {
        'phase': 'IDLE', 'paused': False,
        'today': {'triggers': 0, 'successes': 0, 'failures': 0, 'skip_reasons': {}},
        'recent_cycles': [],
    }

    @contextmanager
    def timed_out_guard(*args, **kwargs):
        raise auto_runner.FileLockTimeout('canonical-alert.lock')
        yield  # pragma: no cover

    result = {
        'id': 'mcp_timeout', 'status': 'completed',
        'top3': [{'symbol': '000001', 'final_score': 88.0}],
        'event_candidates': [{
            'symbol': '000001', 'action': 'BUY_CANDIDATE', 'price': {'date': '2026-08-21'},
        }],
        'summary': {'quality': {'recommendation': 'send', 'reasons': []}},
    }
    failures = []
    monkeypatch.setattr(auto_runner, '_read_state', lambda: dict(state))
    monkeypatch.setattr(auto_runner, '_write_state', lambda payload: None)
    monkeypatch.setattr(auto_runner, '_append_history', lambda payload: None)
    monkeypatch.setattr(auto_runner, '_record_failure', lambda *args: failures.append(args[2]))
    monkeypatch.setattr(auto_runner.workflow_svc, 'start_workflow_from_scanner_events', lambda **kwargs: result)
    monkeypatch.setattr(auto_runner.workflow_svc, 'should_send_workflow_top3', lambda *args, **kwargs: (True, 'ready'))
    monkeypatch.setattr(auto_runner.workflow_svc, 'build_workflow_top3_telegram_message', lambda payload: '<b>top3</b>')
    monkeypatch.setattr(auto_runner.alpha_scanner, 'scanner_alert_delivery_guard', timed_out_guard)
    from app.utils import scheduler
    monkeypatch.setattr(scheduler, '_send_telegram_long', pytest.fail)
    tuning = auto_runner._tunables()
    tuning.update({'dry_run': False, 'min_top_score': 50})

    outcome = auto_runner._fire_workflow(tuning, {}, {'outcome': 'triggered'}, 0.0)

    assert outcome['error'] == 'alert_delivery_guard_timeout'
    assert failures == ['alert_delivery_guard_timeout']


def test_auto_runner_dry_run_does_not_wait_for_delivery_guard(monkeypatch):
    """A no-send dry run stays available while another process owns the delivery lock."""
    state = {
        'phase': 'IDLE', 'paused': False,
        'today': {'triggers': 0}, 'recent_cycles': [],
    }
    monkeypatch.setattr(auto_runner, '_read_state', lambda: dict(state))
    monkeypatch.setattr(auto_runner, '_write_state', lambda payload: None)
    monkeypatch.setattr(auto_runner, '_append_history', lambda payload: None)
    monkeypatch.setattr(auto_runner.alpha_scanner, 'scanner_alert_delivery_guard', pytest.fail)
    tuning = auto_runner._tunables()
    tuning['dry_run'] = True

    outcome = auto_runner._fire_workflow(tuning, {}, {'outcome': 'triggered'}, 0.0)

    assert outcome == {'fired': True, 'dry_run': True}


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


def test_tunables_default_to_dry_run_without_explicit_operator_opt_in(monkeypatch):
    monkeypatch.delenv('MIROFISH_AUTO_RUNNER_DRY_RUN', raising=False)

    assert auto_runner._tunables()['dry_run'] is True


def test_local_cost_counter_is_explicitly_advisory():
    bucket = auto_runner._empty_daily_bucket()
    assert bucket['cost_accounting'] == 'estimated_advisory'

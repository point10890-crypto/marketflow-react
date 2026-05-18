from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app import create_app
from app.auth.decorators import generate_token
from app.models import db
from app.models.user import User
from app.services.mirofish import subscriber_runs


@pytest.fixture
def isolated_subscriber_policy(tmp_path, monkeypatch):
    state_dir = tmp_path / 'subscriber_runs'
    monkeypatch.setattr(subscriber_runs, 'STATE_ROOT', str(state_dir))
    monkeypatch.setattr(subscriber_runs, 'STATE_FILE', str(state_dir / 'aibain_run_usage.json'))
    monkeypatch.setenv('MIROFISH_AIBAIN_RUN_DAILY_LIMIT', '2')
    monkeypatch.setenv('MIROFISH_AIBAIN_RUN_CONCURRENT_LIMIT', '5')
    monkeypatch.setenv('MIROFISH_AIBAIN_RUN_CACHE_MINUTES', '30')

    runs: dict[str, dict] = {}
    created_payloads: list[dict] = []

    def fake_create_run(payload):
        run_id = f"run-{len(created_payloads) + 1}"
        created_payloads.append(dict(payload))
        run = {
            'id': run_id,
            'target': payload['target'],
            'mode': payload.get('mode', 'full'),
            'status': 'running' if payload.get('async') else 'completed',
            'created_at': datetime.now(timezone.utc).isoformat(),
        }
        runs[run_id] = run
        return run

    def fake_read_run(run_id):
        return runs.get(str(run_id))

    monkeypatch.setattr(subscriber_runs.store, 'create_run', fake_create_run)
    monkeypatch.setattr(subscriber_runs.store, 'read_run', fake_read_run)
    return {'runs': runs, 'created_payloads': created_payloads}


def test_aibain_run_reuses_recent_same_request(isolated_subscriber_policy):
    first = subscriber_runs.create_aibain_run_for_user(
        {'target': 'Samsung Electronics', 'agent_count': 10, 'mode': 'full'},
        user_id=7,
        user_email='brain@test.local',
    )
    second = subscriber_runs.create_aibain_run_for_user(
        {'target': 'Samsung Electronics', 'agent_count': 10, 'mode': 'full'},
        user_id=7,
        user_email='brain@test.local',
    )

    assert second['id'] == first['id']
    assert second['subscriber_policy']['reused_cached_run'] is True
    assert second['subscriber_policy']['used_today'] == 1
    assert len(isolated_subscriber_policy['created_payloads']) == 1
    assert isolated_subscriber_policy['created_payloads'][0]['async'] is True


def test_aibain_run_daily_limit_blocks_new_targets(isolated_subscriber_policy, monkeypatch):
    monkeypatch.setenv('MIROFISH_AIBAIN_RUN_CACHE_MINUTES', '0')

    subscriber_runs.create_aibain_run_for_user(
        {'target': 'Samsung Electronics', 'agent_count': 10, 'mode': 'full'},
        user_id=8,
        user_email='limit@test.local',
    )
    subscriber_runs.create_aibain_run_for_user(
        {'target': 'SK hynix', 'agent_count': 10, 'mode': 'full'},
        user_id=8,
        user_email='limit@test.local',
    )

    with pytest.raises(subscriber_runs.AIBainRunLimitError) as exc_info:
        subscriber_runs.create_aibain_run_for_user(
            {'target': 'Doosan', 'agent_count': 10, 'mode': 'full'},
            user_id=8,
            user_email='limit@test.local',
        )

    assert 'daily run limit' in str(exc_info.value)
    assert exc_info.value.policy['used_today'] == 2
    assert exc_info.value.policy['daily_limit'] == 2


def test_aibain_run_concurrent_limit_blocks_second_active_run(isolated_subscriber_policy, monkeypatch):
    monkeypatch.setenv('MIROFISH_AIBAIN_RUN_DAILY_LIMIT', '5')
    monkeypatch.setenv('MIROFISH_AIBAIN_RUN_CONCURRENT_LIMIT', '1')
    monkeypatch.setenv('MIROFISH_AIBAIN_RUN_CACHE_MINUTES', '0')

    subscriber_runs.create_aibain_run_for_user(
        {'target': 'Samsung Electronics', 'agent_count': 10, 'mode': 'full'},
        user_id=9,
        user_email='concurrent@test.local',
    )

    with pytest.raises(subscriber_runs.AIBainRunLimitError) as exc_info:
        subscriber_runs.create_aibain_run_for_user(
            {'target': 'SK hynix', 'agent_count': 10, 'mode': 'full'},
            user_id=9,
            user_email='concurrent@test.local',
        )

    assert 'concurrent run limit' in str(exc_info.value)
    assert exc_info.value.policy['active_count'] == 1


def test_aibain_subscriber_can_create_run_through_route(tmp_path, monkeypatch):
    state_dir = tmp_path / 'route_state'
    monkeypatch.setattr(subscriber_runs, 'STATE_ROOT', str(state_dir))
    monkeypatch.setattr(subscriber_runs, 'STATE_FILE', str(state_dir / 'aibain_run_usage.json'))

    runs: dict[str, dict] = {}

    def fake_create_run(payload):
        run = {
            'id': 'route-run-1',
            'target': payload['target'],
            'status': 'running',
            'created_at': datetime.now(timezone.utc).isoformat(),
        }
        runs[run['id']] = run
        return run

    monkeypatch.setattr(subscriber_runs.store, 'create_run', fake_create_run)
    monkeypatch.setattr(subscriber_runs.store, 'read_run', lambda run_id: runs.get(str(run_id)))

    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'MARKETFLOW_BACKGROUND_WORKERS': 'false',
        'SECRET_KEY': 'aibain-route-test-secret',
    })

    with app.app_context():
        user = User(
            email='aibain-route@test.local',
            name='AI Brain Route',
            role='user',
            status='approved',
            tier='pro',
            aibain_enabled=True,
        )
        user.set_password('test-password-1234')
        db.session.add(user)
        db.session.commit()
        token = generate_token(user.id)

    resp = app.test_client().post(
        '/api/admin/mirofish/runs',
        json={'target': 'Samsung Electronics', 'agent_count': 10, 'mode': 'full', 'async': True},
        headers={'Authorization': f'Bearer {token}'},
    )

    assert resp.status_code == 202
    data = resp.get_json()
    assert data['id'] == 'route-run-1'
    assert data['subscriber_policy']['role'] == 'aibain'
    assert data['subscriber_policy']['used_today'] == 1

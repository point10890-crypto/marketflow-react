# -*- coding: utf-8 -*-
"""C2 (2026-09-03) — 잡 레지스트리 + 수동 재실행 트리거 큐 회귀 테스트.

- JOB_REGISTRY 는 setup_schedules() 를 선언형으로 미러링한다 (record_key 동기화 검사).
- describe_jobs() 는 JSON 안전 (callable 없음) 이어야 Flask 가 파일로 읽을 수 있다.
- Flask enqueue → 데몬 drain/run → results 파일 (tmp DATA_DIR) — 잡 함수는 mock.
- 손상된 요청 파일은 데몬을 죽이지 않고 리셋된다.
- get_scheduler_status().daemon 이 jobs/trigger_results 를 병합한다.
- POST /api/scheduler/trigger/<job_key> 는 jobs 파일 키를 검증하고 큐에 넣는다 (파일 없으면 구 5개 맵 폴백).
"""
from __future__ import annotations

import inspect
import json
import re
import threading
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

import scheduler


# ─────────────────────────── 레지스트리 ───────────────────────────

def test_registry_entries_are_complete_and_describe_is_json_safe():
    reg = scheduler.JOB_REGISTRY
    assert len(reg) >= 20
    for key, job in reg.items():
        assert job['label'], key
        assert callable(job['func']), key
        assert isinstance(job['record_key'], str) and job['record_key'], key
        assert job['market'] in {'KR', 'US', 'Crypto', 'System'}, key
        assert job['schedule'], key
        assert job['record_key'] in job['record_keys'] or job['record_keys'], key

    described = scheduler.describe_jobs()
    json.dumps(described)  # callable 이 섞이면 TypeError
    assert [d['key'] for d in described] == list(reg.keys())
    assert all('func' not in d for d in described)
    for must in ('kr_jongga', 'us_market', 'crypto', 'vcp_all', 'buy_screen'):
        assert must in reg
    assert reg['kr_jongga']['func'] is scheduler.run_kr_full_update
    assert reg['crypto']['market'] == 'Crypto'


def test_registry_mirrors_setup_schedules_record_keys():
    """레지스트리의 record_key/record_keys 접두사가 실제 등록 코드에 있어야 한다 (드리프트 방지)."""
    src = inspect.getsource(scheduler.Scheduler.setup_schedules)
    for key, job in scheduler.JOB_REGISTRY.items():
        if key == 'alpha_intraday_watch':  # _with_record 없이 등록 (함수 내부 게이트)
            assert '_run_alpha_intraday_watch' in src
            continue
        if job['record_keys'] != [job['record_key']]:
            prefix = job['record_key'] + '_'
            assert re.search(rf"f\"{re.escape(prefix)}\{{", src), key
        else:
            assert f"'{job['record_key']}'" in src, key


# ─────────────────────────── 트리거 큐 (데몬 측) ───────────────────────────

@pytest.fixture()
def daemon_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler.Config, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(scheduler, '_LAST_RUN_FILE', str(tmp_path / 'scheduler_last_run.json'))
    monkeypatch.setattr(scheduler, 'send_telegram', lambda *a, **k: True)
    monkeypatch.setattr(scheduler.time, 'sleep', lambda *_: None)
    import app.utils.paths as paths
    monkeypatch.setattr(paths, 'DATA_DIR', str(tmp_path))
    return tmp_path


def _join_trigger_threads():
    for t in threading.enumerate():
        if t.name.startswith('trigger-'):
            t.join(timeout=10)


def test_write_jobs_file_is_atomic_and_readable_by_flask(daemon_dir):
    from app.utils import scheduler as sch

    assert scheduler.write_jobs_file() is True
    data = json.loads((daemon_dir / 'scheduler_jobs.json').read_text(encoding='utf-8'))
    assert data['pid'] and data['generated_at']
    assert [j['key'] for j in data['jobs']] == list(scheduler.JOB_REGISTRY.keys())
    assert [j['key'] for j in sch.read_daemon_jobs()] == list(scheduler.JOB_REGISTRY.keys())
    assert not list(daemon_dir.glob('.tmp_*'))


def test_enqueue_then_daemon_runs_job_and_records_outcome(daemon_dir, monkeypatch):
    from app.utils import scheduler as sch

    calls = []

    def fake_job():
        calls.append(1)
        return True

    monkeypatch.setitem(scheduler.JOB_REGISTRY, 'fake_ok', {
        'label': '가짜 잡', 'func': fake_job, 'schedule': '매일 00:00', 'market': 'System',
        'record_key': 'fake_ok', 'record_keys': ['fake_ok'],
    })
    req = sch.enqueue_trigger_request('fake_ok', requested_by='admin@test')
    queued = json.loads((daemon_dir / 'scheduler_trigger_requests.json').read_text(encoding='utf-8'))
    assert queued[0]['id'] == req['id'] and queued[0]['job_key'] == 'fake_ok'
    assert queued[0]['requested_by'] == 'admin@test'

    assert scheduler.poll_trigger_requests() == 1
    _join_trigger_threads()

    assert calls == [1]
    # 큐는 비워지고, 결과는 ok=True + finished_at, last_run 은 record_key 로 기록
    assert json.loads((daemon_dir / 'scheduler_trigger_requests.json').read_text(encoding='utf-8')) == []
    results = json.loads((daemon_dir / 'scheduler_trigger_results.json').read_text(encoding='utf-8'))
    assert len(results) == 1
    assert results[0]['id'] == req['id'] and results[0]['ok'] is True
    assert results[0]['finished_at'] and results[0]['error'] is None
    last_run = json.loads((daemon_dir / 'scheduler_last_run.json').read_text(encoding='utf-8'))
    assert 'fake_ok' in last_run

    # 같은 날 재실행 — force 게이트 우회로 다시 돈다 (관리자가 명시적으로 눌렀다)
    sch.enqueue_trigger_request('fake_ok')
    scheduler.poll_trigger_requests()
    _join_trigger_threads()
    assert calls == [1, 1]
    assert scheduler.poll_trigger_requests() == 0  # 소비된 뒤 재폴링은 no-op


def test_failing_and_unknown_jobs_are_recorded_not_raised(daemon_dir, monkeypatch):
    from app.utils import scheduler as sch

    def boom():
        raise RuntimeError('kaboom')

    monkeypatch.setitem(scheduler.JOB_REGISTRY, 'fake_boom', {
        'label': '터지는 잡', 'func': boom, 'schedule': '-', 'market': 'System',
        'record_key': 'fake_boom', 'record_keys': ['fake_boom'],
    })
    monkeypatch.setitem(scheduler.JOB_REGISTRY, 'fake_false', {
        'label': '실패 잡', 'func': lambda: False, 'schedule': '-', 'market': 'System',
        'record_key': 'fake_false', 'record_keys': ['fake_false'],
    })
    sch.enqueue_trigger_request('fake_boom')
    sch.enqueue_trigger_request('fake_false')
    sch.enqueue_trigger_request('no_such_job')
    assert scheduler.poll_trigger_requests() == 3
    _join_trigger_threads()

    by_key = {r['job_key']: r for r in json.loads(
        (daemon_dir / 'scheduler_trigger_results.json').read_text(encoding='utf-8'))}
    assert by_key['fake_boom']['ok'] is False and by_key['fake_boom']['finished_at']
    assert by_key['fake_false']['ok'] is False and 'failure' in by_key['fake_false']['error']
    assert by_key['no_such_job']['ok'] is False and 'unknown' in by_key['no_such_job']['error']
    assert not (daemon_dir / 'scheduler_last_run.json').exists()


def test_malformed_request_file_is_logged_and_reset(daemon_dir):
    path = daemon_dir / 'scheduler_trigger_requests.json'
    path.write_text('{not json', encoding='utf-8')
    assert scheduler.drain_trigger_requests() == []
    assert json.loads(path.read_text(encoding='utf-8')) == []

    path.write_text(json.dumps({'id': 'x'}), encoding='utf-8')  # dict (list 아님)
    assert scheduler.drain_trigger_requests() == []
    path.write_text(json.dumps([{'id': 'a'}, 'junk', {'id': 'b', 'job_key': 'kr_jongga'}]), encoding='utf-8')
    assert [r['id'] for r in scheduler.drain_trigger_requests()] == ['b']


def test_trigger_results_are_capped(daemon_dir, monkeypatch):
    monkeypatch.setattr(scheduler, 'TRIGGER_RESULT_CAP', 5)
    for i in range(8):
        scheduler._upsert_trigger_result({'id': f'r{i}', 'job_key': 'x', 'ok': True})
    rows = json.loads((daemon_dir / 'scheduler_trigger_results.json').read_text(encoding='utf-8'))
    assert [r['id'] for r in rows] == ['r3', 'r4', 'r5', 'r6', 'r7']
    scheduler._upsert_trigger_result({'id': 'r5', 'job_key': 'x', 'ok': False})
    rows = json.loads((daemon_dir / 'scheduler_trigger_results.json').read_text(encoding='utf-8'))
    assert [r['ok'] for r in rows if r['id'] == 'r5'] == [False]


# ─────────────────────────── Flask status 병합 ───────────────────────────

def test_status_merges_jobs_last_runs_and_trigger_results(tmp_path, monkeypatch):
    import app.utils.paths as paths
    from app.utils import scheduler as sch

    monkeypatch.setattr(paths, 'DATA_DIR', str(tmp_path))
    now = datetime(2026, 9, 3, 15, 0, 0)
    (tmp_path / 'scheduler_heartbeat.json').write_text(
        json.dumps({'pid': 1, 'ts': (now - timedelta(seconds=10)).isoformat(timespec='seconds')}), encoding='utf-8')
    (tmp_path / 'scheduler_jobs.json').write_text(json.dumps({
        'generated_at': now.isoformat(timespec='seconds'), 'pid': 1,
        'jobs': [
            {'key': 'kr_jongga', 'label': '종가베팅', 'schedule': '평일 14:50', 'market': 'KR',
             'record_key': 'kr_jongga', 'record_keys': ['kr_jongga']},
            {'key': 'leading_screener', 'label': '주도주', 'schedule': '평일 09:07, 10:07', 'market': 'KR',
             'record_key': 'leading_screener',
             'record_keys': ['leading_screener_0907', 'leading_screener_1007']},
            {'key': 'us_market', 'label': 'US', 'schedule': '평일 04:00', 'market': 'US',
             'record_key': 'us_market', 'record_keys': ['us_market']},
        ],
    }), encoding='utf-8')
    (tmp_path / 'scheduler_last_run.json').write_text(json.dumps({
        'kr_jongga': (now - timedelta(hours=30)).strftime('%Y-%m-%dT%H:%M:%S'),
        'leading_screener_0907': (now - timedelta(hours=6)).strftime('%Y-%m-%dT%H:%M:%S'),
        'leading_screener_1007': (now - timedelta(hours=5)).strftime('%Y-%m-%dT%H:%M:%S'),
    }), encoding='utf-8')
    (tmp_path / 'scheduler_trigger_results.json').write_text(json.dumps([
        {'id': 'old', 'job_key': 'kr_jongga', 'started_at': '2026-09-03T10:00:00',
         'finished_at': '2026-09-03T10:05:00', 'ok': False, 'error': 'x'},
        {'id': 'new', 'job_key': 'kr_jongga', 'started_at': '2026-09-03T14:00:00',
         'finished_at': None, 'ok': None, 'error': None},
    ]), encoding='utf-8')
    (tmp_path / 'scheduler_trigger_requests.json').write_text(json.dumps([
        {'id': 'q1', 'job_key': 'us_market', 'requested_at': '2026-09-03T14:59:00', 'requested_by': None},
    ]), encoding='utf-8')

    state = sch._read_daemon_state(now=now)
    assert state['alive'] is True
    jobs = {j['key']: j for j in state['jobs']}
    assert list(jobs) == ['kr_jongga', 'leading_screener', 'us_market']
    assert jobs['kr_jongga']['age_minutes'] == 1800.0
    assert jobs['kr_jongga']['running'] is True
    assert jobs['kr_jongga']['last_trigger']['id'] == 'new'  # 최신 결과가 이긴다
    assert jobs['leading_screener']['age_minutes'] == 300.0  # 시각별 키 중 최신
    assert jobs['us_market']['last_run'] is None and jobs['us_market']['age_minutes'] is None
    assert jobs['us_market']['queued'] is True
    assert [r['id'] for r in state['trigger_results']] == ['new', 'old']
    assert state['pending_triggers'] == 1

    status = sch.get_scheduler_status()
    assert len(status['daemon']['jobs']) == 3
    json.dumps(status)


def test_status_without_jobs_file_has_empty_board(tmp_path, monkeypatch):
    import app.utils.paths as paths
    from app.utils import scheduler as sch

    monkeypatch.setattr(paths, 'DATA_DIR', str(tmp_path))
    state = sch._read_daemon_state()
    assert state['jobs'] == [] and state['trigger_results'] == [] and state['pending_triggers'] == 0


# ─────────────────────────── POST /api/scheduler/trigger ───────────────────────────

@pytest.fixture()
def admin_client(monkeypatch, tmp_path):
    monkeypatch.delenv('SECRET_KEY', raising=False)
    import app.utils.paths as paths
    from app import create_app
    from app.auth import decorators as deco

    monkeypatch.setattr(paths, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(deco, '_get_current_user',
                        lambda: SimpleNamespace(status='approved', is_admin=True, email='ops@test', id=1))
    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
    })
    return app.test_client(), tmp_path


def test_trigger_route_validates_against_jobs_file_and_enqueues(admin_client):
    client, data_dir = admin_client
    (data_dir / 'scheduler_jobs.json').write_text(json.dumps({'jobs': [
        {'key': 'kr_jongga', 'label': 'x', 'schedule': 'x', 'market': 'KR',
         'record_key': 'kr_jongga', 'record_keys': ['kr_jongga']},
    ]}), encoding='utf-8')

    bad = client.post('/api/scheduler/trigger/not_a_job')
    assert bad.status_code == 400
    assert bad.get_json()['available'] == ['kr_jongga']

    ok = client.post('/api/scheduler/trigger/kr_jongga')
    assert ok.status_code == 200
    body = ok.get_json()
    assert body['status'] == 'queued' and body['job_key'] == 'kr_jongga' and body['id']
    queued = json.loads((data_dir / 'scheduler_trigger_requests.json').read_text(encoding='utf-8'))
    assert queued[0]['id'] == body['id'] and queued[0]['requested_by'] == 'ops@test'

    status = client.get('/api/scheduler/status').get_json()
    assert status['daemon']['jobs'][0]['queued'] is True
    assert status['daemon']['pending_triggers'] == 1


def test_trigger_route_falls_back_to_legacy_map_without_jobs_file(admin_client, monkeypatch):
    client, data_dir = admin_client
    from app.utils import scheduler as sch
    monkeypatch.setattr(sch, '_run_us_update', lambda: True)

    res = client.post('/api/scheduler/trigger/us-update')
    assert res.status_code == 200
    assert res.get_json() == {'status': 'triggered', 'task': 'us-update'}
    assert not (data_dir / 'scheduler_trigger_requests.json').exists()

    bad = client.post('/api/scheduler/trigger/kr_jongga')
    assert bad.status_code == 400
    assert 'jongga-v2' in bad.get_json()['available']

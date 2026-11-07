# -*- coding: utf-8 -*-
"""운영 관제 센터 — 인벤토리 분류, 계약, 판정 규칙, 사건·알림, 실행기, 관리자 API."""
from __future__ import annotations

import json
import os
from datetime import datetime

import pytest

from app.services.control_center import alerts, contracts, http_checks, incidents, local_checks, runner, store
from app.services.control_center.model import KST, CheckResult


@pytest.fixture(scope='module')
def app():
    from app import create_app

    return create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                       'MARKETFLOW_BACKGROUND_WORKERS': 'false', 'SECRET_KEY': 'test-control-center-secret'})


@pytest.fixture
def cc(tmp_path, monkeypatch):
    monkeypatch.setenv('CONTROL_CENTER_DIR', str(tmp_path))
    return str(tmp_path)


# ─────────────────────────── 인벤토리 · 보안 게이트 ───────────────────────────

def test_inventory_classifies_every_admin_route_as_protected(app):
    from app.services.control_center.inventory import build_inventory

    inv = build_inventory(app)
    assert len(inv) > 300
    admin_routes = [r for r in inv if r['rule'].startswith('/api/admin/')]
    assert admin_routes and all(r['auth'] in ('admin', 'admin_or_aibain') for r in admin_routes), \
        [r['rule'] for r in admin_routes if r['auth'] not in ('admin', 'admin_or_aibain')]
    gated = [r for r in inv if r['rule'].startswith('/api/kr/') and not r['rule'].startswith('/api/kr/ai-chart-image/')]
    assert gated and all(r['auth'] != 'public' for r in gated)
    cc_routes = {r['rule']: r for r in inv if r['rule'].startswith('/api/admin/control-center/')}
    assert cc_routes and all(r['auth'] == 'admin' and not r['mutating'] for r in cc_routes.values())


def test_isolated_inventory_matches_production_factory_routes(app):
    from app import create_route_inventory_app
    from app.services.control_center.inventory import build_inventory

    assert build_inventory(create_route_inventory_app()) == build_inventory(app)


def test_every_public_route_is_reviewed_in_contracts(app):
    """새 공개(무인증) 라우트가 생기면 이 테스트가 실패한다 — contracts.json 에서 의도를 밝혀야 한다."""
    from app.services.control_center.inventory import build_inventory

    c = contracts.load()
    ep = c['endpoints']
    reviewed = set(ep['public_safe']) | set(ep['public_mutation_ok']) | set(ep['public_info_exposure']) \
        | set(ep['public_reviewed']) | set(ep['exclude'])
    public = {r['rule'] for r in build_inventory(app) if r['auth'] == 'public'}
    assert public - reviewed == set(), f'검토되지 않은 공개 라우트: {sorted(public - reviewed)}'


def test_decorator_chain_survives_functools_wraps():
    from app.auth.decorators import admin_required
    from app.services.control_center.inventory import decorator_chain

    @admin_required
    def view():
        return 'x'

    assert view.__qualname__.endswith('view')          # wraps 가 이름을 덮어써도
    assert decorator_chain(view)[0] == 'admin_required'  # 코드 객체로 데코레이터를 찾는다


def test_sample_path_fills_variables():
    from app.services.control_center.inventory import sample_path

    assert sample_path('/api/kr/stock/<code>/hub') == ('/api/kr/stock/005930/hub', True)
    assert sample_path('/api/x/<int:post_id>') == ('/api/x/1', True)
    assert sample_path('/api/health') == ('/api/health', False)


def test_service_token_matches_app_format(app, monkeypatch):
    from app.auth import decorators

    assert http_checks.APP_TOKEN_EXPIRY == decorators.TOKEN_EXPIRY
    monkeypatch.setenv('SECRET_KEY', app.config['SECRET_KEY'])
    monkeypatch.setenv('CONTROL_CENTER_SERVICE_USER_ID', '7')
    token = http_checks.mint_service_token()
    with app.app_context():
        assert decorators.validate_token(token) == 7
    monkeypatch.delenv('CONTROL_CENTER_SERVICE_USER_ID')
    assert http_checks.mint_service_token() is None


# ─────────────────────────── 계약 ───────────────────────────

def test_contracts_are_valid_and_never_watch_8080():
    c = contracts.load()
    assert all(int(p['port']) != 8080 for p in c['ports'])
    bad = json.loads(json.dumps(c))
    bad['ports'].append({'id': 'other', 'port': 8080})
    with pytest.raises(contracts.ContractError):
        contracts.validate(bad)
    dup = json.loads(json.dumps(c))
    dup['data'].append(dict(dup['data'][0]))
    with pytest.raises(contracts.ContractError):
        contracts.validate(dup)


def test_deep_contract_paths_exist_in_app(app):
    rules = {r.rule for r in app.url_map.iter_rules()}
    missing = [d['path'] for d in contracts.load()['endpoints']['deep'] if d['path'] not in rules]
    assert missing == []


# ─────────────────────────── 판정 규칙 ───────────────────────────

def _kst(*a):
    return datetime(*a, tzinfo=KST)


def test_schedule_parser():
    assert local_checks.parse_schedule('매 5분') == {'kind': 'interval', 'minutes': 5}
    assert local_checks.parse_schedule('매 4시간') == {'kind': 'interval', 'minutes': 240}
    assert local_checks.parse_schedule('평일 09:00, 13:30') == {'kind': 'times', 'times': [(9, 0), (13, 30)], 'weekdays_only': True}
    assert local_checks.parse_schedule('매일 04:00')['weekdays_only'] is False
    assert local_checks.parse_schedule('월 1회')['kind'] == 'unknown'


def test_job_missed_slot_pending_and_weekend():
    job = {'key': 'kr_jongga', 'label': '종가베팅', 'schedule': '평일 15:10, 16:00', 'market': 'KR',
           'record_keys': ['kr_jongga_1510', 'kr_jongga_1600']}
    thu = _kst(2026, 11, 5, 16, 20)
    runs = {'kr_jongga_1510': '2026-11-05T15:12:00'}
    r = local_checks.evaluate_job(job, runs, thu, critical={'kr_jongga'})
    assert r.status == 'ok' and r.severity == 'critical' and '16:00' in r.detail       # 16:00 은 유예 중
    r = local_checks.evaluate_job(job, runs, _kst(2026, 11, 5, 17, 0))
    assert r.status == 'fail' and '16:00' in r.detail
    assert local_checks.evaluate_job(job, {}, _kst(2026, 11, 7, 17, 0)).status == 'skipped'   # 토요일


def test_interval_job_respects_market_hours():
    job = {'key': 'm', 'label': 'm', 'schedule': '매 5분', 'market': 'KR', 'record_key': 'm'}
    assert local_checks.evaluate_job(job, {'m': '2026-11-05T10:00:00'}, _kst(2026, 11, 5, 10, 10)).status == 'ok'
    assert local_checks.evaluate_job(job, {'m': '2026-11-05T09:00:00'}, _kst(2026, 11, 5, 10, 10)).status == 'fail'
    assert local_checks.evaluate_job(job, {}, _kst(2026, 11, 5, 20, 0)).status == 'skipped'


def test_windows_task_evaluation():
    cfg = {'critical': ['MarketFlow-Flask', 'MarketFlow-Scheduler'], 'resident': []}
    rows = [{'name': 'MarketFlow-Flask', 'state': 'Disabled', 'last_result': 0},
            {'name': 'MarketFlow-Wave-Screener', 'state': 'Ready', 'last_result': 0x41303},
            {'name': 'MarketFlow-Kongming', 'state': 'Ready', 'last_result': 1}]
    by = {r.id: r for r in local_checks.evaluate_tasks(rows, cfg)}
    assert by['task:MarketFlow-Flask'].status == 'fail'
    assert by['task:MarketFlow-Wave-Screener'].status == 'warn'
    assert by['task:MarketFlow-Kongming'].status == 'warn' and '0x1' in by['task:MarketFlow-Kongming'].detail
    assert by['task:MarketFlow-Scheduler'].status == 'fail'                      # 등록조차 안 됨


def test_data_freshness_weekend_allowance(tmp_path):
    p = tmp_path / 'x.json'
    p.write_text(json.dumps({'updated_at': '2026-11-06T16:00:00+09:00'}), encoding='utf-8')
    item = {'id': 'x', 'path': str(p), 'field': 'updated_at', 'max_age_hours': 30, 'calendar': 'kr_trading'}
    assert local_checks.check_data([item], _kst(2026, 11, 8, 20, 0))[0].status == 'ok'       # 일요일: +48h
    assert local_checks.check_data([item], _kst(2026, 11, 11, 20, 0))[0].status == 'fail'    # 수요일: 5일 지남
    missing = dict(item, path=str(tmp_path / 'none.json'))
    assert local_checks.check_data([missing])[0].status == 'fail'


def test_heartbeat_and_watchdog(tmp_path):
    hb = tmp_path / 'hb.json'
    hb.write_text(json.dumps({'ts': '2026-11-05T10:00:00'}), encoding='utf-8')
    now = _kst(2026, 11, 5, 10, 2)
    assert local_checks.check_heartbeats([{'id': 'h', 'path': str(hb), 'max_age_sec': 180}], now)[0].status == 'ok'
    assert local_checks.check_heartbeats([{'id': 'h', 'path': str(hb), 'max_age_sec': 60}], now)[0].status == 'fail'
    wd = tmp_path / 'wd.json'
    wd.write_text(json.dumps({'consecutive_failures': 4, 'status': 'unhealthy', 'updated_at': '2026-11-05T10:01:00'}), encoding='utf-8')
    assert local_checks.check_watchdog_states([{'id': 'w', 'path': str(wd)}], now)[0].status == 'fail'


def test_ports_never_probe_8080():
    assert local_checks.check_ports([{'id': 'x', 'port': 8080}]) == []


def test_auth_gate_sweep_flags_open_route_as_security_incident(monkeypatch):
    codes = {'/a': 401, '/b': 200, '/c': 404, '/d': None}
    monkeypatch.setattr(http_checks, 'http_get', lambda url, **k: {
        'status': codes[url.replace('http://h', '')], 'ms': 3, 'json': None, 'error': 'ConnectionError', 'retry_after': None,
        'bytes': 0, 'ctype': ''})
    rows = [{'rule': p, 'probe_path': p, 'auth': 'admin'} for p in codes]
    by = {r.id: r for r in http_checks.auth_gate_sweep('http://h', rows, pause=0)}
    assert by['gate:/a'].status == 'ok'
    assert by['security:/b'].status == 'fail' and by['security:/b'].severity == 'critical'
    assert by['gate:/c'].status == 'unknown'
    assert by['gate:/d'].status == 'unknown'


def test_probe_contract_checks_keys_freshness_and_budget(monkeypatch):
    body = {'status': 'ok', 'updated_at': '2026-11-01T10:00:00+09:00'}
    monkeypatch.setattr(http_checks, 'http_get', lambda url, **k: {
        'status': 200, 'ms': 9000, 'json': body, 'error': None, 'retry_after': None, 'bytes': 10, 'ctype': 'application/json'})
    c = {'path': '/x', 'auth': 'admin', 'expect_keys': ['status'], 'budget_ms': 1000,
         'freshness': {'field': 'updated_at', 'max_age_hours': 30}}
    r = http_checks.probe_contract('http://h', c, 'tok', _kst(2026, 11, 5, 12, 0))
    assert r.status == 'fail' and '데이터' in r.detail and '응답' in r.detail
    assert http_checks.probe_contract('http://h', c, None).status == 'skipped'      # 서비스 계정 없음


# ─────────────────────────── 사건 · 알림 ───────────────────────────

def _r(status, family='endpoint', severity='critical', cid='endpoint:/x'):
    return CheckResult(cid, family, '/x', status, 'detail', severity=severity)


def test_incident_opens_after_consecutive_failures_and_resolves(cc):
    with store.connect() as conn:
        assert incidents.apply(conn, _r('fail'), 'standard') is None              # 1회는 일시적일 수 있다
        opened = incidents.apply(conn, _r('fail'), 'standard')
        assert opened['kind'] == 'open'
        assert incidents.apply(conn, _r('fail'), 'standard') is None              # 이미 열림
        assert incidents.apply(conn, _r('ok'), 'standard') is None
        resolved = incidents.apply(conn, _r('ok'), 'standard')
        assert resolved['kind'] == 'resolve'
        assert incidents.apply(conn, _r('fail', family='data', cid='data:y'), 'standard')['kind'] == 'open'  # data 는 1회


def test_alert_dispatch_is_opt_in_deduped_and_quiet_for_info(cc):
    sent = []
    with store.connect() as conn:
        incidents.apply(conn, _r('fail', family='data', cid='data:a'), 'standard')
        ch = conn.execute('SELECT id FROM incidents').fetchone()
        change = {'kind': 'open', 'incident_id': ch['id'], 'check_id': 'data:a', 'family': 'data', 'target': '/x',
                  'severity': 'critical', 'detail': 'd'}
        snap = {'overall': 'fail', 'counts': {}}
        assert alerts.dispatch(conn, [change], snap, enabled=False, sender=sent.append) == 0 and sent == []
        assert alerts.dispatch(conn, [change], snap, enabled=True, sender=lambda t: sent.append(t) or True) == 1
        assert alerts.dispatch(conn, [change], snap, enabled=True, sender=lambda t: sent.append(t) or True) == 0  # 중복 없음
        info = dict(change, severity='info')
        assert alerts.dispatch(conn, [info], snap, enabled=True, sender=lambda t: sent.append(t) or True) == 0
    assert len(sent) == 1 and '사건 발생' in sent[0] and 'TELEGRAM' not in sent[0]


# ─────────────────────────── 실행기 · 스냅샷 · API ───────────────────────────

def test_runner_writes_snapshot_and_pages_roll_up(cc, monkeypatch):
    fake = [CheckResult('endpoint:/api/kr/jongga-v2/latest', 'endpoint', 'j', 'fail', 'HTTP 500', severity='critical'),
            CheckResult('data:kr_jongga', 'data', '종가베팅 V2', 'ok', 'fresh', severity='critical'),
            CheckResult('port:flask_primary', 'process', 'flask', 'ok', 'up', severity='critical')]
    monkeypatch.setattr(runner, 'run_checks', lambda tier, c, states, base_dir=None: list(fake))
    for _ in range(2):
        res = runner.run('fast', send_alerts=False)
    assert res['overall'] == 'fail'
    snap = runner.read_snapshot()
    assert snap['monitor']['status'] == 'unknown'
    page = next(p for p in snap['pages'] if p['path'] == '/dashboard/kr/closing-bet')
    assert page['status'] == 'fail' and page['critical']
    assert snap['counts']['open_incidents'] == 1
    assert os.path.exists(os.path.join(cc, 'heartbeat.json'))


def test_runner_reports_its_own_crash(cc, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError('x')

    monkeypatch.setattr(runner, 'run_checks', boom)
    runner.run('deep', send_alerts=False)
    snap = runner.read_snapshot()
    assert any(s['check_id'] == 'monitor:runner_deep' for s in snap['failing'])


def test_read_snapshot_without_runner_is_fail(cc):
    snap = runner.read_snapshot()
    assert snap['overall'] == 'unknown' and snap['monitor']['status'] == 'fail'


def test_tier_lock_prevents_overlap(cc):
    with runner.TierLock('fast') as a:
        assert a.acquired
        with runner.TierLock('fast') as b:
            assert not b.acquired


def test_admin_api_requires_admin_and_reads_snapshot(app, cc, monkeypatch):
    from app.auth.decorators import generate_token
    from app.models import db
    from app.models.user import User

    client = app.test_client()
    for path in ('/api/admin/control-center/summary', '/api/admin/control-center/incidents',
                 '/api/admin/control-center/routes', '/api/admin/control-center/checks/x/history'):
        assert client.get(path).status_code == 401
        assert client.post(path).status_code in (401, 405)
    with app.app_context():
        db.create_all()
        admin = User(email='cc-admin@test.local', name='cc', role='admin', status='approved', tier='premium')
        admin.set_password('test-password-1234')
        db.session.add(admin)
        db.session.commit()
        token = generate_token(admin.id)
    h = {'Authorization': f'Bearer {token}'}
    monkeypatch.setattr(runner, 'run_checks', lambda *a, **k: [CheckResult('port:flask_primary', 'process', 'f', 'ok', 'up')])
    runner.run('fast', send_alerts=False)
    body = client.get('/api/admin/control-center/summary', headers=h).get_json()
    assert body['schema'] == 'marketflow.control_center.v1' and body['monitor']['status'] == 'unknown'
    routes = client.get('/api/admin/control-center/routes', headers=h).get_json()
    assert routes['totals']['routes'] > 300
    assert routes['totals']['auth_gate'] == len(contracts.load()['endpoints']['auth_probe_safe'])
    hist = client.get('/api/admin/control-center/checks/port:flask_primary/history', headers=h).get_json()
    assert hist['history'] and hist['state']['status'] == 'ok'


# ─────────────────────────── OpenClaw 운영 MCP ───────────────────────────

def test_ops_mcp_exposes_exactly_four_read_only_tools(cc, monkeypatch):
    import asyncio

    from app.services.control_center import mcp_ops

    server = mcp_ops.create_server()
    names = sorted(t.name for t in asyncio.run(server.list_tools()))
    assert names == sorted(mcp_ops.TOOL_NAMES)
    assert all(n.startswith(('get_', 'list_')) for n in names)          # 조회 동사만
    banned = ('restart', 'trigger', 'send', 'write', 'delete', 'set_', 'update', 'execute', 'order', 'apply')
    assert not any(b in n for n in names for b in banned)


def test_ops_mcp_summary_and_runbook(cc, monkeypatch):
    from app.services.control_center import mcp_ops

    monkeypatch.setattr(runner, 'run_checks', lambda *a, **k: [
        CheckResult('port:flask_primary', 'process', 'flask', 'fail', 'down', severity='critical')])
    runner.run('fast', send_alerts=False)
    runner.run('fast', send_alerts=False)
    s = mcp_ops.summary()
    assert s['overall'] == 'fail' and s['failing'][0]['check_id'] == 'port:flask_primary'
    assert s['open_incidents'] and 'heartbeat' not in s['monitor']
    rb = mcp_ops.runbook_for('port:flask_primary')
    assert rb['match'] == 'port:flask_primary' and rb['human']
    assert mcp_ops.runbook_for('security:/api/x')['match'] == 'security:'
    assert mcp_ops.runbook_for('zzz')['match'] is None


def test_existing_openclaw_research_profile_is_untouched():
    import importlib.util
    import pathlib

    spec = importlib.util.spec_from_file_location(
        'setup_openclaw_mcp', pathlib.Path(__file__).resolve().parents[1] / 'scripts' / 'setup_openclaw_mcp.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert len(mod.READ_ONLY_TOOLS) == 19
    from app.services.control_center import mcp_ops
    assert not set(mcp_ops.TOOL_NAMES) & set(mod.READ_ONLY_TOOLS + mod.MUTATING_TOOLS)

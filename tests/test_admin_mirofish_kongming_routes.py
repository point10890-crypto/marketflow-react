import http.client
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from flask import Flask

from app.auth import decorators as auth
from app.routes.admin_mirofish import admin_mirofish_bp


PREFIX = '/api/admin/mirofish/kongming'
STATUS = PREFIX + '/catalyst-validation'
HISTORY = PREFIX + '/catalyst-validation-history'
LEGACY_ALLOWLIST = 'KONGMING_CATALYST_ALLOWED_USER_IDS'
AT = '2026-11-07T09:00:00+09:00'


class Upstream:
    def __init__(self):
        self.connections = []
        self.requests = []
        self.read_limits = []
        self.closed = 0
        self.status = 200
        self.content_type = 'application/json; charset=utf-8'
        self.body = b'{"items":[]}'
        self.error = None

    def connect(self, host, port, timeout):
        self.connections.append((host, port, timeout))
        return self

    def request(self, method, path, headers):
        self.requests.append((method, path, headers))

    def getresponse(self):
        if self.error:
            raise self.error
        return self

    def getheader(self, name, default=None):
        return self.content_type if name.lower() == 'content-type' else default

    def read(self, amount):
        self.read_limits.append(amount)
        return self.body[:amount]

    def close(self):
        self.closed += 1

    def set_json(self, payload):
        self.body = json.dumps(payload).encode('utf-8')


@pytest.fixture
def gateway(monkeypatch):
    app = Flask(__name__)
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
    auth.db.init_app(app)
    app.register_blueprint(admin_mirofish_bp, url_prefix='/api/admin/mirofish')
    caller = SimpleNamespace(user=SimpleNamespace(
        id=42, email='fixture@example.test', status='approved', is_admin=True,
        is_aibain_active=False, is_kongming_active=False,
    ))
    upstream = Upstream()
    monkeypatch.setattr(auth, '_get_current_user', lambda: caller.user)
    monkeypatch.setattr(http.client, 'HTTPConnection', upstream.connect)
    monkeypatch.delenv(LEGACY_ALLOWLIST, raising=False)
    return app.test_client(use_cookies=False), caller, upstream


@pytest.mark.parametrize(('case', 'status'), [
    ('anonymous', 401), ('member', 403), ('suspended', 403),
    ('legacy_aibain', 403), ('expired_bundle', 403), ('pending_bundle', 403),
    ('rejected_admin', 403),
])
@pytest.mark.parametrize('path', [STATUS, HISTORY])
def test_denies_anonymous_blocked_or_unentitled_users(gateway, case, status, path):
    client, caller, upstream = gateway
    if case == 'anonymous':
        caller.user = None
    elif case == 'member':
        caller.user.is_admin = False
    elif case == 'suspended':
        caller.user.status = 'suspended'
        caller.user.is_kongming_active = True
    elif case in ('legacy_aibain', 'expired_bundle', 'pending_bundle'):
        caller.user.is_admin = False
        caller.user.is_aibain_active = case != 'pending_bundle'
    elif case == 'rejected_admin':
        caller.user.status = 'rejected'

    assert client.get(path).status_code == status
    assert not upstream.connections


@pytest.mark.parametrize('path', [STATUS, HISTORY])
@pytest.mark.parametrize('admin_id,legacy_allowlist', [(42, None), (73, '7,42')])
def test_admin_can_read_without_bundle_or_matching_legacy_allowlist(gateway, monkeypatch, path, admin_id, legacy_allowlist):
    client, caller, upstream = gateway
    caller.user.id = admin_id
    if legacy_allowlist is not None:
        monkeypatch.setenv(LEGACY_ALLOWLIST, legacy_allowlist)

    response = client.get(path)

    assert response.status_code == 200
    assert 'no-store' in response.headers['Cache-Control']
    assert upstream.connections


@pytest.mark.parametrize('path', [STATUS, HISTORY])
def test_bundle_member_can_read_without_base_tier(gateway, path):
    client, caller, upstream = gateway
    caller.user.is_admin = False
    caller.user.is_kongming_active = True
    response = client.get(path)
    assert response.status_code == 200
    assert 'no-store' in response.headers['Cache-Control']
    assert upstream.connections


def test_bundle_does_not_grant_general_mirofish_run_creation(gateway):
    client, caller, _ = gateway
    caller.user.is_admin = False
    caller.user.is_kongming_active = True

    response = client.post('/api/admin/mirofish/runs', json={})

    assert response.status_code == 403


def test_validation_projects_only_the_displayed_fields_and_uses_fixed_loopback(gateway):
    client, _, upstream = gateway
    shown = {
        'hash': 'source-hash', 'computed_at': AT, 'history_count': 4,
        'current_eligible_count': 0, 'current_eligible_symbol_count': 0,
        'quote_expiry_seconds': 60,
        'operation': {'state': 'ready', 'task_errors': {'ValueError': 1}},
        'swing_watch': {'source_as_of': '2026-11-06', 'population': 1,
            'baseline_count': 1, 'baseline_rows': [{'symbol': '005930', 'name': '테스트',
                'common_pass': False, 'failed_common': ['조건'], 'missing_common': []}],
            'common_watch_count': 0, 'watch_rows': [], 'common_funnel': [{'label': '자료', 'count': 1}]},
        'items': [{'task_id': 'fixture-task', 'symbol': '005930', 'name': '테스트',
            'article_title': '검증 기사', 'article_url': 'https://www.businesspost.co.kr/BP?command=article_view&num=1',
            'article_published_at': AT, 'first_seen_at': AT, 'checked_at': AT,
            'primary': {'status': 'related_filing_found', 'checks': [{
                'status': 'related_filing_found', 'filing': {'report_nm': '원문 확인'},
                'claims': [{'metric': '매출', 'article_amount_krw': '100', 'official_amount_krw': None, 'verified': False}],
            }]},
            'styles': {'scalp': {'state': 'technical_checked', 'technical_pass': True,
                'qualified': False, 'eligible': False, 'currently_eligible': False,
                'blockers': ['성과 검증 대기'], 'quote': {
                    'observed_at': AT, 'received_at': AT,
                    'plan': {'valid_until': '2026-11-07T09:30:00+09:00'},
                }}}}],
    }
    raw = deepcopy(shown)
    raw['internal_path'] = 'hidden'
    raw['operation']['private_error'] = 'hidden'
    raw['swing_watch']['baseline_rows'][0]['raw_source'] = 'hidden'
    raw['items'][0]['primary']['checks'][0]['filing']['private_fields'] = 'hidden'
    quote = raw['items'][0]['styles']['scalp']['quote']
    quote['raw_quote'] = 'hidden'
    quote['plan'].update(valid_from=AT, entry_price=100_000)
    raw['items'][0]['styles']['unknown'] = {'private_fields': 'hidden'}
    upstream.set_json(raw)

    response = client.get(STATUS + '?url=https://wrong.example.test/', headers={
        'Authorization': 'Bearer test-only', 'Cookie': 'session=test-only',
        'X-Upstream-Host': 'wrong.example.test',
    })

    assert response.status_code == 200
    assert response.get_json() == shown
    assert 'no-store' in response.headers['Cache-Control']
    assert upstream.requests == [('GET', '/api/catalyst-validation', {'Accept': 'application/json'})]
    assert len(upstream.connections) == 1
    host, port, timeout = upstream.connections[0]
    assert (host, port) == ('127.0.0.1', 8768)
    assert 0 < timeout <= 5
    assert upstream.closed == 1


def test_validation_preserves_optional_source_worker_timing(gateway):
    client, _, upstream = gateway
    shown = {'last_run_at': AT, 'last_change_at': AT, 'age_seconds': 0,
             'stalled': False, 'worker_interval_seconds': 10}
    upstream.set_json({'items': [], 'live': {**shown, 'internal_path': 'hidden'}})

    response = client.get(STATUS)

    assert response.status_code == 200
    assert response.get_json() == {'items': [], 'live': shown}


def test_history_uses_its_own_path_and_drops_raw_history(gateway):
    client, _, upstream = gateway
    row = {'id': 'fixture', 'checked_at': AT, 'name': '테스트', 'symbol': '005930',
        'primary': {'status': 'no_matching_filing'}, 'market_state': 'closed', 'buy_eligible': False}
    upstream.set_json({
        'items': [{**row, 'private_source': 'hidden', 'styles': {'scalp': {'quote': {'plan': {'valid_until': AT}}}}}],
        'private_metadata': 'hidden', 'quote_expiry_seconds': 60,
    })
    response = client.get(HISTORY)

    assert response.status_code == 200
    assert response.get_json() == {'items': [row]}
    assert 'no-store' in response.headers['Cache-Control']
    assert upstream.requests == [('GET', '/api/catalyst-validation-history', {'Accept': 'application/json'})]


@pytest.mark.parametrize('fault', ['redirect', 'timeout', 'html', 'invalid_json', 'missing_items', 'invalid_flag', 'oversized'])
def test_upstream_failures_are_generic_and_bounded(gateway, fault):
    client, _, upstream = gateway
    if fault == 'redirect':
        upstream.status = 302
    elif fault == 'timeout':
        upstream.error = TimeoutError('private upstream detail')
    elif fault == 'html':
        upstream.content_type = 'text/html'
    elif fault == 'invalid_json':
        upstream.body = b'{not-json'
    elif fault == 'missing_items':
        upstream.body = b'{}'
    elif fault == 'invalid_flag':
        upstream.set_json({'items': [{'styles': {'scalp': {'currently_eligible': 'false'}}}]})
    else:
        upstream.body = b' ' * (8 * 1024 * 1024 + 1)

    response = client.get(STATUS)

    assert response.status_code == 502
    assert response.get_json() == {'error': 'kongming_catalyst_unavailable'}
    assert 'no-store' in response.headers['Cache-Control']
    assert len(upstream.connections) == upstream.closed == 1
    assert all(0 < size <= 8 * 1024 * 1024 + 1 for size in upstream.read_limits)


def test_proxy_registers_only_the_two_read_routes(gateway):
    client, _, upstream = gateway
    assert client.get(PREFIX + '/businesspost').status_code == 404
    assert client.post(STATUS).status_code == 405
    assert client.post(HISTORY).status_code == 405
    assert not upstream.connections

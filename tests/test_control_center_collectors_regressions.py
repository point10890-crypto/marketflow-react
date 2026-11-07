import json
from datetime import datetime

import pytest

from app.services.control_center import contracts, http_checks, local_checks, provider_checks
from app.services.control_center.model import KST


def test_rejects_untrusted_api_base_and_path(monkeypatch):
    monkeypatch.setenv('CONTROL_CENTER_API_BASE', 'https://evil.invalid')
    with pytest.raises(contracts.ContractError):
        http_checks.api_base({})
    for base in ('http://127.0.0.1:8080', 'http://user@127.0.0.1:5003', 'http://127.0.0.1:5003/api'):
        monkeypatch.setenv('CONTROL_CENTER_API_BASE', base)
        with pytest.raises(contracts.ContractError):
            http_checks.api_base({})
    c = {'path': '//evil.invalid', 'auth': 'public'}
    assert http_checks.probe_contract('http://127.0.0.1:5003', c, None).status == 'unknown'


def test_rejects_remote_token_before_opening_connection():
    result = http_checks.http_get('https://evil.invalid/', token='test-credential')
    assert result['status'] is None
    assert result['error'] == 'UnsafeURL'


def test_gate_stops_on_rate_limit_and_marks_remaining_unknown(monkeypatch):
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return {'status': 429, 'ms': 1}

    monkeypatch.setattr(http_checks, 'http_get', get)
    rows = [{'rule': f'/api/{i}', 'probe_path': f'/api/{i}', 'auth': 'admin'} for i in range(3)]
    results = http_checks.auth_gate_sweep('http://127.0.0.1:5003', rows, pause=0)
    assert len(calls) == 1 and calls[0][1]['read_body'] is False
    assert [r.status for r in results] == ['warn', 'unknown', 'unknown']


def test_invalid_and_future_content_do_not_fall_back_to_fresh_mtime(tmp_path, monkeypatch):
    p = tmp_path / 'item.json'
    monkeypatch.setattr(local_checks, 'resolve_path', lambda template: str(p))
    now = datetime(2026, 11, 7, 10, tzinfo=KST)
    cfg = [{'id': 'item', 'path': '{data}/item.json', 'field': 'updated_at'}]
    for raw in ('not json', '{"updated_at": true}', '{"updated_at": "2027-01-01"}'):
        p.write_text(raw, encoding='utf-8')
        assert local_checks.check_data(cfg, now)[0].status == 'unknown'


def test_kr_holiday_skips_kr_job():
    holiday = datetime(2026, 5, 5, 14, tzinfo=KST)
    job = {'key': 'price', 'schedule': '매 5분', 'market': 'KR'}
    assert local_checks.evaluate_job(job, {}, holiday).status == 'skipped'


def test_windows_task_requires_valid_baseline():
    rows = [{'name': 'MarketFlow-a', 'state': 'Ready'},
            {'name': 'MarketFlow-b', 'state': 'Unknown', 'last_result': 0},
            {'name': 'MarketFlow-c', 'state': 'Ready', 'last_result': 0}]
    assert [r.status for r in local_checks.evaluate_tasks(rows, {})] == ['unknown', 'unknown', 'unknown']


def test_provider_network_probes_require_opt_in(monkeypatch):
    monkeypatch.setenv('TEST_DART_KEY', 'test')
    monkeypatch.delenv('CONTROL_CENTER_PROVIDER_NETWORK_ENABLED', raising=False)
    monkeypatch.setattr(provider_checks, '_dart_list', lambda *args: pytest.fail('network collector called'))
    c = [{'id': 'dart', 'type': 'dart_list', 'env': 'TEST_DART_KEY'}]
    assert provider_checks.check_providers(c, {})[0].status == 'skipped'


def test_empty_provider_report_is_unknown(monkeypatch):
    monkeypatch.setattr(provider_checks, '_read_json', lambda p: {'mode': 'live', 'providers': []})
    assert provider_checks._ai_routing_health({'id': 'llm'}, datetime.now(KST)).status == 'unknown'


def test_http_redirect_and_unauthorized_responses_never_read_body(monkeypatch):
    from http import client

    calls = []

    class Socket:
        def settimeout(self, timeout):
            pass

        def shutdown(self, mode):
            pass

    class Response:
        status = 302

        def getheader(self, name):
            return {'Content-Type': 'application/json', 'Location': 'https://evil.invalid/'}.get(name)

        def read1(self, amount):
            pytest.fail('response body read')

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    class Connection:
        def __init__(self, host, port, **kwargs):
            calls.append((host, port))
            self.sock = Socket()

        def connect(self):
            pass

        def request(self, method, path, headers):
            assert method == 'GET'
            assert path == '/api/admin/check'
            assert headers.get('Authorization') in ('Bearer test-credential', None)

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(client, 'HTTPConnection', Connection)
    monkeypatch.setattr(client, 'HTTPSConnection', Connection)
    url = 'http://127.0.0.1:5003/api/admin/check'
    assert http_checks.http_get(url, token='test-credential')['status'] == 302
    Response.status = 401
    assert http_checks.http_get(url, read_body=False)['status'] == 401
    assert calls == [('127.0.0.1', 5003), ('127.0.0.1', 5003)]


def test_us_holiday_uses_new_york_session_calendar():
    now = datetime(2026, 7, 6, 20, tzinfo=KST)  # Monday 07:00 ET; Friday observed holiday
    assert local_checks._calendar_allowance('us_trading', now) == 72


def test_future_and_overwritten_job_records_are_unknown():
    now = datetime(2026, 11, 5, 17, tzinfo=KST)
    job = {'key': 'test', 'schedule': '매일 10:00, 16:00'}
    for value in ('2026-11-05T16:10:00', '2026-11-05T18:00:00'):
        assert local_checks.evaluate_job(job, {'test': value}, now).status == 'unknown'


def test_ignored_task_is_omitted_but_failure_code_is_reported():
    rows = [{'name': 'ignored', 'state': 'Disabled', 'last_result': 0},
            {'name': 'archival', 'state': 'Ready', 'last_result': 3}]
    results = local_checks.evaluate_tasks(rows, {'critical': ['ignored', 'archival'], 'ignore': ['ignored']})
    assert [(r.id, r.status) for r in results] == [('task:archival', 'fail')]


def test_public_override_cannot_point_to_internal_or_other_route(monkeypatch):
    monkeypatch.setattr(http_checks, 'http_get', lambda *a, **k: pytest.fail('network collector called'))
    for url in ('http://127.0.0.1:5003/healthz', 'https://marketflow-api.bit-man.net/api/system/update-single'):
        monkeypatch.setenv('PUBLIC_CHECK', url)
        item = {'id': 'api', 'url': 'https://marketflow-api.bit-man.net/healthz', 'env': 'PUBLIC_CHECK'}
        assert http_checks.check_public_urls([item])[0].status == 'unknown'


def test_kis_token_checks_only_active_namespaced_cache(monkeypatch):
    from app.services import kis_screener

    now = datetime(2026, 11, 5, 17, tzinfo=KST)
    monkeypatch.setattr(kis_screener, '_token_namespace', lambda: 'real:test-fingerprint')
    active = {'token': 'must-not-appear', 'expires_at': now.timestamp() + 3600,
              'mode': 'real', 'app_key_fingerprint': 'test-fingerprint'}
    payload = {'version': 2, 'tokens': {'paper:other': active}}
    monkeypatch.setattr(provider_checks, '_read_json', lambda p: payload)
    assert provider_checks._kis_token_cache({'id': 'kis'}, now).status == 'unknown'
    payload['tokens']['real:test-fingerprint'] = active
    result = provider_checks._kis_token_cache({'id': 'kis'}, now)
    assert result.status == 'ok'
    assert 'must-not-appear' not in str(result.to_dict())


@pytest.mark.parametrize(('body', 'status'), [
    ({'state': 'open', 'incidents': []}, 'ok'),
    ({'state': 'open'}, 'fail'),
    (None, 'fail'),
    ([], 'fail'),
])
def test_incidents_contract_checks_field_presence(monkeypatch, body, status):
    monkeypatch.setattr(http_checks, 'http_get', lambda *args, **kwargs: {
        'status': 200, 'json': body, 'ms': 1, 'bytes': 0, 'error': None,
    })
    c = {'path': '/api/admin/control-center/incidents', 'expect_keys': ['state', 'incidents']}
    assert http_checks.probe_contract('http://127.0.0.1:5003', c, 'test').status == status


@pytest.mark.parametrize('content', ['broken json', '', '{}', '[]', 'true', 'null', '"text"'])
def test_metadata_only_freshness_requires_nonempty_json(tmp_path, content):
    artifact = tmp_path / 'us-decision.JSON'
    artifact.write_text(content, encoding='utf-8')
    cfg = [{'id': 'decision', 'path': str(artifact)}]
    assert local_checks.check_data(cfg)[0].status == 'unknown'


def test_valid_json_without_timestamp_uses_file_metadata(tmp_path):
    artifact = tmp_path / 'us-decision.json'
    artifact.write_text('{"signal": "neutral"}', encoding='utf-8')
    cfg = [{'id': 'decision', 'path': str(artifact)}]
    result = local_checks.check_data(cfg)[0]
    assert result.status == 'ok'
    assert result.data['freshness_basis'] == 'mtime'


@pytest.mark.parametrize('wrapped', [True, False])
def test_scheduler_job_registry_reads_writer_shape(tmp_path, monkeypatch, wrapped):
    monkeypatch.setattr(local_checks, 'DATA_DIR', str(tmp_path))
    jobs = [{'key': 'scheduler_sample', 'label': 'Sample job', 'schedule': '매 5분',
             'market': 'System', 'record_key': 'sample_record', 'record_keys': ['sample_record']}]
    registry = {'generated_at': '2026-11-07T10:00:00', 'pid': 42, 'jobs': jobs} if wrapped else jobs
    (tmp_path / 'scheduler_jobs.json').write_text(json.dumps(registry), encoding='utf-8')
    (tmp_path / 'scheduler_last_run.json').write_text('{"sample_record": "2026-11-07T10:01:00"}', encoding='utf-8')
    now = datetime(2026, 11, 7, 10, 5, tzinfo=KST)
    assert [(row.id, row.status) for row in local_checks.check_jobs({}, now)] == [('job:scheduler_sample', 'ok')]


@pytest.mark.parametrize('registry', [{}, {'jobs': {}}, {'jobs': []}, {'jobs': [{'schedule': '매 5분'}]},
                                     {'jobs': [{'key': 'test', 'record_keys': {'invalid': []}}]}])
def test_invalid_or_empty_scheduler_registry_remains_unknown(tmp_path, monkeypatch, registry):
    monkeypatch.setattr(local_checks, 'DATA_DIR', str(tmp_path))
    (tmp_path / 'scheduler_jobs.json').write_text(json.dumps(registry), encoding='utf-8')
    results = local_checks.check_jobs({})
    assert [(row.id, row.status) for row in results] == [('job:_registry', 'unknown')]
    assert '데몬이 한 번도' not in results[0].detail


@pytest.mark.parametrize('baseline', [[], {}, {'test': {}}, {'test': 'malformed'}])
def test_invalid_scheduler_success_baseline_remains_unknown(tmp_path, monkeypatch, baseline):
    monkeypatch.setattr(local_checks, 'DATA_DIR', str(tmp_path))
    (tmp_path / 'scheduler_jobs.json').write_text('{"jobs": [{"key": "test"}]}', encoding='utf-8')
    (tmp_path / 'scheduler_last_run.json').write_text(json.dumps(baseline), encoding='utf-8')
    assert [(row.id, row.status) for row in local_checks.check_jobs({})] == [('job:_baseline', 'unknown')]

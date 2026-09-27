import copy
import importlib
import json
from concurrent.futures import ThreadPoolExecutor

import pytest


def module():
    try:
        return importlib.import_module('app.services.mirofish.semantic_decisions')
    except ModuleNotFoundError:
        pytest.fail('semantic shadow pipeline is not implemented')


def candidate(symbol='SYN001'):
    return {'symbol': symbol, 'name': '가상기업A', 'market': 'TEST',
            'source_cutoff': '2026-09-28T01:00:00+00:00',
            'alpha_score': 80, 'risk_score': 20,
            'source_packets': [{'source': 'synthetic', 'evidence_id': 'e1',
                'fetched_at': '2026-09-28T00:59:00+00:00',
                'content': {'text': '가상기업A는 계약 해지를 확정했다.'}}]}


def response(m):
    answers = {}
    for k, q in m.QUESTIONS.items():
        if q['type'] == 'choice':
            keys = list(q['criteria'])
            answers[k] = {'type': 'choice', 'choice': keys[0], 'confidence': 1.0,
                          'probabilities': {v: float(v == keys[0]) for v in keys}}
        else:
            answers[k] = {'type': 'noul', 'noul': 0.8}
    return {'model': m.MODEL, 'answers': answers,
            'usage': {'input_tokens': 1000, 'output_tokens': 30}}


def test_request_rejects_future_or_ambiguous_time():
    m = module()
    c = candidate()
    packet = m.build_request(c)
    assert packet['state']['target']['symbol'] == 'SYN001'
    assert packet['state']['evidence'][0]['text'].startswith('가상기업A')
    for bad in ['2026-09-28T02:00:00+00:00', '2026-09-28']:
        c['source_packets'][0]['fetched_at'] = bad
        with pytest.raises(ValueError):
            m.build_request(c)


def test_missing_text_is_not_invented_from_numeric_snapshot():
    m = module()
    c = candidate()
    c['source_packets'][0]['content'] = {'price': 1234}
    with pytest.raises(ValueError, match='text'):
        m.build_request(c)


@pytest.mark.parametrize('mutation', ['missing', 'nan', 'sum', 'choice', 'model', 'usage', 'bool'])
def test_invalid_responses_rejected(mutation):
    m = module()
    r = response(m)
    if mutation == 'missing': r['answers'].pop('relevance')
    if mutation == 'nan': r['answers']['correction']['noul'] = float('nan')
    if mutation == 'sum': r['answers']['relevance']['probabilities']['direct'] = .2
    if mutation == 'choice': r['answers']['relevance']['choice'] = 'invented'
    if mutation == 'model': r['model'] = 'other'
    if mutation == 'usage': r['usage']['input_tokens'] = -1
    if mutation == 'bool': r['answers']['correction']['noul'] = True
    with pytest.raises(ValueError):
        m.validate_response(r)


def test_off_is_no_network_and_snapshot_immutable(tmp_path, monkeypatch):
    m = module()
    monkeypatch.delenv('MIROFISH_JEV_LIVE_ENABLED', raising=False)
    c = candidate()
    original = copy.deepcopy(c)
    record = m.record_snapshot([c], root=tmp_path, workflow_id='mcp_demo', decision_at=c['source_cutoff'])
    result = m.evaluate_snapshot(record['id'], root=tmp_path, transport=lambda *_: pytest.fail('network'))
    assert result['status'] == 'disabled'
    assert c == original
    assert record['candidate_count'] == 1
    assert record['ranking_effect'] == 'none'


def test_live_validates_persists_and_reuses_without_repeat(tmp_path, monkeypatch):
    m = module()
    monkeypatch.setenv('MIROFISH_JEV_LIVE_ENABLED', 'true')
    monkeypatch.setenv('TYPESAFE_API_KEY', 'test-only-key')
    calls = []
    def transport(payload, key):
        calls.append(payload)
        return response(m)
    c = candidate()
    snap = m.record_snapshot([c], root=tmp_path, workflow_id='mcp_demo', decision_at=c['source_cutoff'])
    first = m.evaluate_snapshot(snap['id'], root=tmp_path, transport=transport)
    second = m.evaluate_snapshot(snap['id'], root=tmp_path, transport=transport)
    assert first['validated_count'] == second['validated_count'] == 1
    assert len(calls) == 1
    assert first['results'][0]['features']['risk_contract_termination'] == .8
    assert first['ranking_effect'] == 'none'
    assert 'test-only-key' not in ''.join(p.read_text(encoding='utf-8') for p in tmp_path.rglob('*.json'))


def test_concurrent_claims_do_not_duplicate_provider_call(tmp_path, monkeypatch):
    m = module()
    monkeypatch.setenv('MIROFISH_JEV_LIVE_ENABLED', 'true')
    monkeypatch.setenv('TYPESAFE_API_KEY', 'test-key')
    c = candidate()
    snap = m.record_snapshot([c], root=tmp_path, workflow_id='mcp_demo', decision_at=c['source_cutoff'])
    calls = []
    def transport(payload, key):
        calls.append(1)
        return response(m)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: m.evaluate_snapshot(snap['id'], root=tmp_path, transport=transport), range(2)))
    assert len(calls) == 1


def test_failed_provider_does_not_cache_success_or_leak_secrets(tmp_path, monkeypatch):
    m = module()
    monkeypatch.setenv('MIROFISH_JEV_LIVE_ENABLED', 'true')
    monkeypatch.setenv('TYPESAFE_API_KEY', 'private-key')
    c = candidate()
    snap = m.record_snapshot([c], root=tmp_path, workflow_id='mcp_demo', decision_at=c['source_cutoff'])
    def fail(*_): raise TimeoutError('private-key')
    result = m.evaluate_snapshot(snap['id'], root=tmp_path, transport=fail)
    assert result['validated_count'] == 0
    assert result['results'][0]['status'] == 'uncertain'
    assert result['results'][0]['features'] is None
    assert 'private-key' not in json.dumps(result)


def test_snapshot_traversal_rejected(tmp_path):
    with pytest.raises(ValueError):
        module().read_snapshot('../secrets', root=tmp_path)


def test_scanner_observed_at_provenance_supported():
    c = candidate()
    c['source_packets'][0]['observed_at'] = c['source_packets'][0].pop('fetched_at')
    assert module().build_request(c)['state']['evidence']


def test_status_is_read_only(tmp_path):
    module().status(root=tmp_path / 'absent')
    assert not (tmp_path / 'absent').exists()


def test_workflow_captures_all_scanner_candidates_without_evaluation(tmp_path, monkeypatch):
    from app.services.mirofish import workflow
    m = module()
    monkeypatch.setattr(m, 'ROOT', tmp_path)
    monkeypatch.setattr(m, 'evaluate_snapshot', lambda *a, **k: pytest.fail('must not call provider'))
    record = {'id': 'mcp_example', 'created_at': candidate()['source_cutoff']}
    assert hasattr(workflow, '_record_semantic_snapshot'), 'workflow snapshot seam missing'
    workflow._record_semantic_snapshot(record, {'run': {'candidates': [candidate(str(i)) for i in range(8)]}})
    assert record['semantic_shadow']['candidate_count'] == 8
    assert len(m.read_snapshot(record['semantic_shadow']['id'])['candidates']) == 8


def test_semantic_api_admin_gate_and_no_get_work(monkeypatch, tmp_path):
    from flask import Flask
    from types import SimpleNamespace
    import app.auth.decorators as auth
    from app.routes.admin_mirofish import admin_mirofish_bp
    m = module()
    monkeypatch.setattr(m, 'ROOT', tmp_path)
    app = Flask(__name__)
    app.register_blueprint(admin_mirofish_bp, url_prefix='/api/admin/mirofish')
    client = app.test_client()
    url = '/api/admin/mirofish/semantic-shadow/status'
    monkeypatch.setattr(auth, '_get_current_user', lambda: None)
    assert client.get(url).status_code == 401
    monkeypatch.setattr(auth, '_get_current_user', lambda: SimpleNamespace(role='user', status='approved', is_admin=False))
    assert client.get(url).status_code == 403
    monkeypatch.setattr(auth, '_get_current_user', lambda: SimpleNamespace(role='admin', status='approved', is_admin=True, id=1, email='test@example.invalid'))
    assert client.get(url).json['ranking_effect'] == 'none'
    assert not list(tmp_path.iterdir())


def test_all_recorded_times_checked_and_event_identity_stable():
    m = module()
    c = candidate()
    ids = m.evidence_event_ids(c)
    c['source_cutoff'] = '2026-09-29T01:00:00Z'
    assert m.evidence_event_ids(c) == ids
    c = candidate()
    c['source_packets'][0]['available_at'] = '2026-09-28T00:00:00Z'
    c['source_packets'][0]['content']['available_at'] = '2026-09-29T00:00:00Z'
    with pytest.raises(ValueError, match='future_evidence'):
        m.build_request(c)
    c = candidate()
    c['source_packets'][0]['observed_at'] = '2026-09-29T00:00:00Z'
    with pytest.raises(ValueError, match='future_evidence'):
        m.build_request(c)

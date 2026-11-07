from types import SimpleNamespace

import pytest
from flask import Flask

from app.auth import decorators as auth
from app.routes.admin_mirofish import admin_mirofish_bp
from app.services import evidence_review


ARTICLE = '/api/admin/mirofish/kongming/article-evidence-reviews'
CANDIDATE = '/api/admin/mirofish/alpha-lab/candidate-review'


@pytest.fixture
def gateway(monkeypatch):
    app = Flask(__name__)
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
    auth.db.init_app(app)
    app.register_blueprint(admin_mirofish_bp, url_prefix='/api/admin/mirofish')
    caller = SimpleNamespace(user=SimpleNamespace(id=42, email='fixture@example.test', status='approved',
        is_admin=True, is_aibain_active=False, is_kongming_active=False))
    calls = []
    monkeypatch.setattr(auth, '_get_current_user', lambda: caller.user)

    def read(kind):
        calls.append(kind)
        return dict(schema_version=1, kind=kind, status='waiting', last_run_at=None, items=[], empty_reason='review_pending',
                    raw='secret', prompt='secret', private_error='secret')

    def no_inference(*args, **kwargs):
        pytest.fail('GET must never execute the worker')

    monkeypatch.setattr(evidence_review, 'read_article_reviews', lambda: read('article'))
    monkeypatch.setattr(evidence_review, 'read_candidate_review', lambda: read('candidate'))
    monkeypatch.setattr(evidence_review, 'run_once', no_inference)
    return app.test_client(), caller, calls


@pytest.mark.parametrize('path', [ARTICLE, CANDIDATE])
@pytest.mark.parametrize('case,code', [('anonymous', 401), ('member', 403), ('blocked', 403)])
def test_saved_review_denies_unauthorized_before_store(gateway, path, case, code):
    client, caller, calls = gateway
    if case == 'anonymous':
        caller.user = None
    elif case == 'member':
        caller.user.is_admin = False
    else:
        caller.user.status = 'suspended'
    assert client.get(path).status_code == code
    assert not calls


@pytest.mark.parametrize('path', [ARTICLE, CANDIDATE])
def test_saved_review_is_get_only_private_and_no_inference(gateway, path):
    client, caller, calls = gateway
    response = client.get(path)
    assert response.status_code == 200
    assert response.json['items'] == []
    assert 'secret' not in response.get_data(as_text=True)
    assert 'no-store' in response.headers['Cache-Control']
    assert client.post(path).status_code == 405
    assert client.get(path+'?refresh=true').status_code == 400
    assert len(calls) == 1


def test_article_and_alpha_review_reuse_matching_entitlements(gateway):
    client, caller, calls = gateway
    caller.user.is_admin = False
    caller.user.is_aibain_active = True
    assert client.get(ARTICLE).status_code == 403
    assert client.get(CANDIDATE).status_code == 200
    caller.user.is_aibain_active = False
    caller.user.is_kongming_active = True
    assert client.get(ARTICLE).status_code == 200
    assert client.get(CANDIDATE).status_code == 200


def test_saved_review_store_error_never_leaks_details(gateway, monkeypatch):
    client, _, _ = gateway
    def error():
        raise ValueError('sk-private-secret')
    monkeypatch.setattr(evidence_review, 'read_candidate_review', error)
    response = client.get(CANDIDATE)
    assert response.status_code == 503
    assert 'sk-private-secret' not in response.get_data(as_text=True)


def test_saved_omission_count_is_public_but_rejection_text_stays_private(gateway, monkeypatch):
    client, _, _ = gateway
    monkeypatch.setattr(evidence_review, 'read_candidate_review', lambda: dict(
        schema_version=1, kind='candidate', status='ready', last_run_at=None,
        items=[dict(omitted_findings=1, raw='private rejected text', rejections=['private reason'])]))
    response = client.get(CANDIDATE)
    assert response.status_code == 200
    assert response.json['items'] == [dict(omitted_findings=1)]
    assert 'private' not in response.get_data(as_text=True)

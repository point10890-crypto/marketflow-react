import json

from filelock import Timeout

from app.services import evidence_review
from scripts import run_evidence_review


def test_cli_runs_bounded_worker_with_explicit_roots(tmp_path, monkeypatch, capsys):
    recorded = {}
    def run(**kwargs):
        recorded.update(kwargs)
        return dict(status='complete', article_attempts=0, candidate_attempts=0)
    monkeypatch.setattr(evidence_review, 'run_once', run)
    result = run_evidence_review.main(['--root', str(tmp_path/'reviews'), '--article-root', str(tmp_path/'articles'),
                                     '--alpha-root', str(tmp_path/'alpha')])
    assert result == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'complete'
    assert recorded['root'] == tmp_path/'reviews'
    assert recorded['article_root'] == tmp_path/'articles'
    assert recorded['alpha_root'] == tmp_path/'alpha'


def test_cli_overlap_is_nonfailure_and_private_errors_are_redacted(monkeypatch, capsys):
    def overlap(**kwargs):
        raise Timeout('private-path')
    monkeypatch.setattr(evidence_review, 'run_once', overlap)
    assert run_evidence_review.main([]) == 0
    assert json.loads(capsys.readouterr().out) == dict(status='already_running')
    def fail(**kwargs):
        raise ValueError('sk-private-secret')
    monkeypatch.setattr(evidence_review, 'run_once', fail)
    assert run_evidence_review.main([]) == 1
    assert json.loads(capsys.readouterr().out) == dict(status='failed', error='evidence_review_unavailable')


def test_cli_reports_all_provider_failure_as_nonzero(monkeypatch, capsys):
    monkeypatch.setattr(evidence_review, 'run_once', lambda **kwargs: dict(status='failed', successful=0, unverified=1))
    assert run_evidence_review.main([]) == 1
    assert json.loads(capsys.readouterr().out)['status'] == 'failed'

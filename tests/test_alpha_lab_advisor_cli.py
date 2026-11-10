import json
import time

from filelock import Timeout

from scripts import run_top3_advisor


def test_cli_deadline_roots_and_public_task_summary(tmp_path,monkeypatch,capsys):
    from app.services.mirofish.alpha_lab import advisor
    seen={}
    def run(**kwargs):
        seen.update(kwargs)
        return dict(status='ready',debate_complete=True,raw='secret')
    monkeypatch.setattr(advisor,'run_once',run)
    before=time.monotonic()
    assert run_top3_advisor.main(['--root',str(tmp_path/'advisor'),'--article-root',str(tmp_path/'articles'),
                                 '--alpha-root',str(tmp_path/'alpha')]) == 0
    assert seen['root']==tmp_path/'advisor' and seen['article_root']==tmp_path/'articles'
    assert seen['alpha_root']==tmp_path/'alpha'
    assert before+209 <= seen['deadline'] <= time.monotonic()+210
    assert json.loads(capsys.readouterr().out)==dict(status='ready',debate_complete=True)


def test_cli_overlap_and_exception_redaction(monkeypatch,capsys):
    from app.services.mirofish.alpha_lab import advisor
    def overlap(**kwargs):
        raise Timeout('private')
    monkeypatch.setattr(advisor,'run_once',overlap)
    assert run_top3_advisor.main([])==0
    assert json.loads(capsys.readouterr().out)==dict(status='already_running')
    def fail(**kwargs):
        raise ValueError('sk-private')
    monkeypatch.setattr(advisor,'run_once',fail)
    assert run_top3_advisor.main([])==1
    assert json.loads(capsys.readouterr().out)==dict(status='failed',error='top3_advisor_unavailable')


def test_cli_failed_status_is_nonzero(monkeypatch,capsys):
    from app.services.mirofish.alpha_lab import advisor
    monkeypatch.setattr(advisor,'run_once',lambda **_:dict(status='failed'))
    assert run_top3_advisor.main([])==1
    assert json.loads(capsys.readouterr().out)['status']=='failed'


def test_cli_counts_recovered_validated_stage_as_completed(monkeypatch,capsys):
    from app.services.mirofish.alpha_lab import advisor
    monkeypatch.setattr(advisor,'run_once',lambda **_:dict(status='degraded',debate=dict(
        debate_complete=True,stages=[dict(status=status) for status in
            ('SUCCESS_PRIMARY','RECOVERED_RESPONSE','SUCCESS_FALLBACK')])))
    assert run_top3_advisor.main([])==0
    summary=json.loads(capsys.readouterr().out)
    assert summary['debate_complete'] is True and summary['completed_stages']==3
    assert summary['status']=='degraded'


def test_cli_uses_same_configured_roots_as_read_api(tmp_path,monkeypatch,capsys):
    from app.services.mirofish.alpha_lab import advisor
    seen={}
    def run(**kwargs):
        seen.update(kwargs)
        return dict(status='waiting')
    monkeypatch.setattr(advisor,'run_once',run)
    monkeypatch.setattr(advisor,'ALPHA_ROOT',tmp_path/'configured-alpha')
    monkeypatch.setattr(advisor,'ROOT',tmp_path/'configured-advisor')
    monkeypatch.setattr(advisor.articles,'ROOT',tmp_path/'configured-articles')
    assert run_top3_advisor.main([])==0
    assert seen['alpha_root']==tmp_path/'configured-alpha'
    assert seen['root']==tmp_path/'configured-advisor'
    assert seen['article_root']==tmp_path/'configured-articles'
    capsys.readouterr()

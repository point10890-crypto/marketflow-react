import pytest
from filelock import Timeout
from app.services.mirofish.kongming_technical import service
from scripts import run_kongming_technical as cli


@pytest.mark.parametrize('state,code', [('ready',0),('partial',0),('busy',0),('failed',1),('unexpected',1)])
def test_worker_logs_only_safe_summary(monkeypatch,capsys,tmp_path,state,code):
    monkeypatch.setattr(service,'run_once',lambda root:dict(status=state,processed=2,failed=0,private='secret'))
    assert cli.main(['--root',str(tmp_path)])==code
    output=capsys.readouterr().out
    assert 'secret' not in output


def test_worker_busy_and_failure_do_not_leak(monkeypatch,capsys):
    def busy(root):raise Timeout('private lock')
    monkeypatch.setattr(service,'run_once',busy)
    assert cli.main([])==0
    assert 'private' not in capsys.readouterr().out
    def fail(root):raise RuntimeError('secret token')
    monkeypatch.setattr(service,'run_once',fail)
    assert cli.main([])==1
    assert 'secret' not in capsys.readouterr().out

import time

import pytest


@pytest.mark.parametrize('state,code', [('ready',0),('partial',0),('no_surge',0),('waiting',0),('unavailable',1)])
def test_worker_bounded_summary(monkeypatch, capsys, tmp_path, state, code):
    from app.services.surge_trace import service
    from scripts import run_surge_trace
    seen = []
    def run(**kwargs):
        assert time.monotonic() < kwargs['deadline'] <= time.monotonic()+81
        seen.append(kwargs)
        return {'status':state,'items':[],'private':'not-for-logs','operation':{'processed':2,'pending':3}}
    monkeypatch.setattr(service,'run_once',run)
    assert run_surge_trace.main(['--root',str(tmp_path)]) == code
    output = capsys.readouterr().out
    assert 'not-for-logs' not in output
    assert 'processed' in output
    assert seen[0]['root'] == tmp_path


def test_worker_sanitizes_unexpected_failure(monkeypatch,capsys):
    from app.services.surge_trace import service
    from scripts import run_surge_trace
    monkeypatch.setattr(service,'run_once',lambda **kwargs: (_ for _ in ()).throw(RuntimeError('secret-text')))
    assert run_surge_trace.main([]) == 1
    assert 'secret-text' not in capsys.readouterr().out

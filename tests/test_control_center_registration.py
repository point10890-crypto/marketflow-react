"""Installer preview must be inert and a development checkout cannot register SYSTEM tasks."""
import json
import os
from pathlib import Path
import subprocess

import pytest

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows Task Scheduler installer')
SCRIPT = Path(__file__).resolve().parents[1] / 'deploy/register_control_center_tasks.ps1'


def test_registration_preview_is_quiet_bounded_and_complete():
    result = subprocess.run(['powershell', '-NoProfile', '-File', str(SCRIPT), '-Plan'],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    plans = json.loads(result.stdout)
    assert {p['EveryMinutes'] for p in plans} == {1, 10, 60}
    assert len({p['Name'] for p in plans}) == 3
    assert len({p['DelayMinutes'] for p in plans}) == 3
    for plan in plans:
        assert plan['Arguments'].endswith(' --no-alerts')
        assert 0 < plan['LimitMinutes'] <= 15
        assert Path(plan['WorkingDirectory']).resolve() == SCRIPT.parents[1]


def test_registration_refuses_unowned_host_before_task_changes():
    env = dict(os.environ, COMPUTERNAME='UNOWNED-TEST-HOST')
    result = subprocess.run(['powershell', '-NoProfile', '-File', str(SCRIPT)],
                            capture_output=True, text=True, timeout=20, env=env)
    assert result.returncode != 0
    assert 'Registration is restricted' in result.stderr
    assert 'Registered MarketFlow-' not in result.stdout

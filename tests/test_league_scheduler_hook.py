import re
from pathlib import Path

import scheduler
from app.services.forecast_league import db

ROOT = Path(__file__).resolve().parent.parent


def test_scheduler_only_enqueues_league_jobs(tmp_path, monkeypatch):
    monkeypatch.setenv('FORECAST_LEAGUE_DIR', str(tmp_path / 'league'))
    assert scheduler.run_league_morning() is True
    assert scheduler.run_league_evening() is True
    with db.connect() as conn:
        kinds = [row['kind'] for row in conn.execute('SELECT kind FROM jobs ORDER BY job_id')]
        statuses = {row['status'] for row in conn.execute('SELECT status FROM jobs')}
    assert kinds == ['sync_universe', 'submit_baselines', 'collect_regular', 'resolve', 'score']
    assert statuses == {'queued'}                      # 스케줄러는 실행하지 않는다


def test_scheduler_registers_both_slots_on_weekdays():
    source = (ROOT / 'scheduler.py').read_text(encoding='utf-8')
    assert re.search(r"\.at\('07:30'\)\.do\(\s*self\._with_record\(run_league_morning, 'league_morning'", source)
    assert re.search(r"\.at\('20:45'\)\.do\(\s*self\._with_record\(run_league_evening, 'league_evening'", source)


def test_register_script_targets_the_drain_command():
    script = (ROOT / 'deploy' / 'register_league_worker_task.ps1').read_text(encoding='utf-8')
    assert '-X utf8 -m app.services.league_worker drain' in script
    assert "MINIPC-NQYLP" in script and "'SYSTEM'" in script
    assert 'Unregister-ScheduledTask' not in script

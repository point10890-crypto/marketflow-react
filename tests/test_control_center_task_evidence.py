from datetime import datetime, timedelta
from app.services.control_center import runner, store
from app.services.control_center.model import CheckResult, KST


def test_running_self_requires_recent_successful_completion(tmp_path):
    now = datetime(2026,11,8,1,tzinfo=KST)
    def item():
        return CheckResult('task:MarketFlow-ControlCenter-Standard','task','standard','unknown',
                           '현재 작업 완료 대기', value={'last_run':now.isoformat()})
    assert runner.completed_monitor_task_evidence([item()],str(tmp_path),now)[0].status == 'unknown'
    with store.connect(str(tmp_path)) as conn:
        run_id = store.start_run(conn, 'standard', (now-timedelta(minutes=10)).isoformat())
        store.record_results(conn, run_id, [CheckResult('monitor:runner_standard','monitor','standard','ok')])
        conn.execute('UPDATE runs SET finished_at=? WHERE id=?', ((now-timedelta(minutes=9)).isoformat(),run_id))
    assert runner.completed_monitor_task_evidence([item()],str(tmp_path),now)[0].status == 'ok'
    assert runner.completed_monitor_task_evidence([item()],str(tmp_path),now+timedelta(hours=1))[0].status == 'unknown'
    with store.connect(str(tmp_path)) as conn:
        conn.execute("UPDATE results SET status='fail'")
    assert runner.completed_monitor_task_evidence([item()],str(tmp_path),now)[0].status == 'unknown'

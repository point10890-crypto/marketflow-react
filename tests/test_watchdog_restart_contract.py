from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_claw_watchdog_supports_one_shot_deployment_restart():
    script = (ROOT / "scripts" / "claw_watchdog.ps1").read_text(encoding="utf-8")
    assert "data\\claw\\restart.request" in script
    assert "Remove-Item -LiteralPath $RestartRequestFile" in script
    assert "marketflow_claw start" in script


def test_claw_watchdog_prefers_pidfile_and_bounds_wmi_fallback():
    script = (ROOT / "scripts" / "claw_watchdog.ps1").read_text(encoding="utf-8")
    assert "function Read-ClawPidFile" in script
    assert "function Resolve-ClawProcess" in script
    assert "function Get-ClawFallbackPids" in script
    assert "Wait-Job -Job $job -Timeout $WmiTimeoutSeconds" in script
    assert "WMI fallback timed out" in script
    assert script.index("Read-ClawPidFile") < script.index("Get-ClawFallbackPids)", script.index("function Resolve-ClawProcess"))


def test_claw_watchdog_verifies_new_pid_and_post_restart_heartbeat():
    script = (ROOT / "scripts" / "claw_watchdog.ps1").read_text(encoding="utf-8")
    assert "$RestartVerifyTimeoutSeconds = 90" in script
    assert "function Wait-ClawRestart" in script
    assert "$newPid -ne [int]$OldPid" in script
    assert "$after.HeartbeatWriteTime -ge $NotBefore.AddSeconds(-1)" in script
    assert "restart confirmed: PID" in script
    assert "restart FAILED after ${RestartVerifyTimeoutSeconds}s" in script


def test_claw_watchdog_stops_task_wrapper_before_starting_new_instance():
    script = (ROOT / "scripts" / "claw_watchdog.ps1").read_text(encoding="utf-8")
    stop_call = script.index("Stop-ScheduledTask -TaskName $TaskName -ErrorAction Stop")
    start_call = script.index("Start-ScheduledTask -TaskName $TaskName -ErrorAction Stop")
    assert stop_call < start_call
    assert "$TaskStopTimeoutSeconds = 15" in script
    assert "function Wait-ClawTaskStopped" in script
    assert "Start-Sleep -Milliseconds $TaskStatePollMilliseconds" in script
    assert "remained Running after ${TaskStopTimeoutSeconds}s" in script


def test_scheduler_watchdog_supports_exact_pid_deployment_restart():
    script = (ROOT / "scripts" / "scheduler_watchdog.ps1").read_text(encoding="utf-8")
    assert "data\\scheduler_restart.request" in script
    assert "taskkill.exe /F /T /PID $oldPid" in script
    assert "Remove-Item -LiteralPath $RestartRequestFile" in script


def test_scheduler_watchdog_polls_for_real_restart_readiness():
    script = (ROOT / "scripts" / "scheduler_watchdog.ps1").read_text(encoding="utf-8")
    assert "$RestartVerifyTimeoutSeconds = 180" in script
    assert "$RestartPollSeconds = 3" in script
    assert "function Wait-DaemonRestart" in script
    assert "$newPid -ne [int]$OldPid" in script
    assert "$after.HeartbeatWriteTime -ge $NotBefore.AddSeconds(-1)" in script
    assert "heartbeat.pid -ne $pidNum" in script
    assert "Start-Sleep -Seconds 8" not in script
    assert "Start-Sleep -Seconds 5" not in script


def test_scheduler_watchdog_uses_bounded_wmi_only_as_pidfile_fallback():
    script = (ROOT / "scripts" / "scheduler_watchdog.ps1").read_text(encoding="utf-8")
    assert "function Get-SchedulerFallbackPids" in script
    assert "Wait-Job -Job $job -Timeout $WmiTimeoutSeconds" in script
    assert "if (-not $stoppedExactPid)" in script
    assert "foreach ($fallbackPid in @(Get-SchedulerFallbackPids))" in script
    assert script.count("Get-CimInstance Win32_Process") == 1

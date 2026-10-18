from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_5003_launcher_never_kills_every_flask_app_process():
    script = (ROOT / "scripts" / "start_flask_task.ps1").read_text(encoding="utf-8")
    assert "data\\flask_5003.pid" in script
    assert "Get-NetTCPConnection -LocalPort 5003 -State Listen" in script
    assert 'CommandLine -like "*flask_app.py*"' not in script
    assert "Stop-MarketFlowPrimaryTree -Snapshot $Snapshot" in script
    guard = (ROOT / "scripts" / "flask_process_guard.ps1").read_text(encoding="utf-8")
    assert "taskkill.exe /F /T /PID $current.ProcessId" in guard


def test_5003_watchdog_targets_pid_file_or_5003_listener_only():
    script = (ROOT / "scripts" / "flask_watchdog_v2.ps1").read_text(encoding="utf-8")
    assert "data\\flask_5003.pid" in script
    assert "Get-NetTCPConnection -LocalPort 5003 -State Listen" in script
    assert "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\"" not in script


def test_legacy_5001_watchdog_uses_bounded_health_failure_threshold():
    script = (ROOT / "scripts" / "flask_watchdog_v2.ps1").read_text(encoding="utf-8")
    assert "$LegacyHealthUrl = 'http://127.0.0.1:5001/healthz'" in script
    assert "$LegacyProbeFailureThreshold = 3" in script
    assert "$LegacyProbeDelaySeconds = 3" in script
    assert "function Confirm-LegacyProducerDown" in script
    assert "for ($attempt = 1; $attempt -le $LegacyProbeFailureThreshold; $attempt++)" in script
    assert "health recovered during recheck" in script
    assert "$LegacyRecoveryTimeoutSeconds = 60" in script
    assert "$LegacyRecoveryPollSeconds = 3" in script


def test_legacy_5001_recovery_targets_only_verified_port_owner_and_starts_hidden():
    script = (ROOT / "scripts" / "flask_watchdog_v2.ps1").read_text(encoding="utf-8")
    assert "Get-NetTCPConnection -LocalPort 5001 -State Listen" in script
    assert "function Test-IsMarketFlowLegacyProducer" in script
    guard = (ROOT / "scripts" / "flask_process_guard.ps1").read_text(encoding="utf-8")
    assert ".venv\\Scripts\\python.exe" in guard
    assert "flask_app\\.py" in guard
    assert "port owned by non-MarketFlow process" in script
    assert "taskkill.exe /F /T /PID $candidate.ProcessId" in script
    assert "$LegacyStartScript = Join-Path $Project 'run_flask.bat'" in script
    assert "Start-Process -FilePath $LegacyStartScript" in script
    assert "-WindowStyle Hidden" in script
    assert "Legacy 5001 KIS producer recovery succeeded." in script
    assert "launcher_status=$launcherStatus exit_code=$launcherExitCode" in script


def test_legacy_5001_watchdog_never_uses_screener_staleness_as_restart_signal():
    script = (ROOT / "scripts" / "flask_watchdog_v2.ps1").read_text(encoding="utf-8")
    assert "screener_leading_latest" not in script
    assert "FILE_FRESH_SECONDS" not in script
    assert "A stale screener artifact is" in script

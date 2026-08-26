from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_cloudflared_launcher_defers_to_running_windows_service():
    script = (ROOT / "deploy" / "start_cloudflared.vbs").read_text(encoding="utf-8")

    service_guard = script.index("FROM Win32_Service WHERE Name='Cloudflared'")
    running_guard = script.index('LCase(CStr(service.State)) = "running"')
    service_start = script.index("service.StartService()")

    assert service_guard < running_guard < service_start
    assert "WScript.Quit 0" in script[running_guard:service_start]
    assert "objShell.Run" not in script
    assert "--config" not in script


def test_tunnel_watchdog_is_service_only_and_scopes_duplicate_cleanup():
    script = (ROOT / "scripts" / "tunnel_watchdog.ps1").read_text(encoding="utf-8")

    assert "data\\tunnel_restart.request" in script
    assert "Get-DuplicateMarketFlowConnectors" in script
    assert "$_.ProcessId -eq $ServicePid" in script
    assert '$commandLine -like "*$MarketFlowUserConfig*"' in script
    assert "Start-ScheduledTask" not in script
    assert "Restart-CanonicalTunnel" in script

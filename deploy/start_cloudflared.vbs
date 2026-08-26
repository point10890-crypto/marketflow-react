Option Explicit
Dim objWMI, services, service, startResult
Set objWMI = GetObject("winmgmts:\\.\root\cimv2")

' The Windows service is the sole owner of the MarketFlow tunnel.  This legacy
' task wrapper may still exist on a MiniPC, so make it service-only: never start
' a second user-session cloudflared.exe connector.
Set services = objWMI.ExecQuery("SELECT State FROM Win32_Service WHERE Name='Cloudflared'")
For Each service In services
    If LCase(CStr(service.State)) = "running" Then WScript.Quit 0
    startResult = service.StartService()
    WScript.Quit CInt(startResult)
Next

' Service missing: fail closed rather than creating an unmanaged connector.
WScript.Quit 2

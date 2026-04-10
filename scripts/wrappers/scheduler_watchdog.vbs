' Silent wrapper for scheduler_watchdog.ps1
' Task Scheduler calls this via wscript.exe — no console window appears.
Dim objShell
Set objShell = CreateObject("WScript.Shell")
objShell.Run "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File ""C:\bitman_marketfloww\scripts\scheduler_watchdog.ps1""", 0, True

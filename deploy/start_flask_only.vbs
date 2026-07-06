Option Explicit
Dim objShell
Set objShell = CreateObject("WScript.Shell")
objShell.CurrentDirectory = "C:\bitman_marketfloww"
objShell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File ""C:\bitman_marketfloww\scripts\start_flask_task.ps1""", 0, False

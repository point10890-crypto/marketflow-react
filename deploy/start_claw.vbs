Option Explicit
' MarketFlow Claw - hidden launcher for Task Scheduler (mirrors start_scheduler.vbs)
Dim objShell
Set objShell = CreateObject("WScript.Shell")
objShell.Environment("Process")("PYTHONIOENCODING") = "utf-8"
objShell.Environment("Process")("HOME_SERVER") = "1"
objShell.CurrentDirectory = "C:\bitman_marketfloww"
objShell.Run "cmd /c .venv\Scripts\python.exe -m marketflow_claw start --source auto --send >> logs\claw.out 2>> logs\claw.err", 0, False

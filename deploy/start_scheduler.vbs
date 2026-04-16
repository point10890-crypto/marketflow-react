Option Explicit
Dim objShell
Set objShell = CreateObject("WScript.Shell")
objShell.Environment("Process")("PYTHONIOENCODING") = "utf-8"
objShell.Environment("Process")("HOME_SERVER") = "1"
objShell.CurrentDirectory = "C:\bitman_marketfloww"
objShell.Run "cmd /c .venv\Scripts\python.exe scheduler.py --daemon > logs\scheduler.out 2> logs\scheduler.err", 0, False

Option Explicit
Dim objShell
Set objShell = CreateObject("WScript.Shell")
objShell.Environment("Process")("PYTHONIOENCODING") = "utf-8"
objShell.Environment("Process")("HOME_SERVER") = "1"
objShell.CurrentDirectory = "C:\bitman_marketfloww"
objShell.Run "cmd /c .venv\Scripts\python.exe flask_app.py > logs\flask.out 2> logs\flask.err", 0, False

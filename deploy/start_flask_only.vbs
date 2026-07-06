Option Explicit
Dim objShell
Set objShell = CreateObject("WScript.Shell")
objShell.Environment("Process")("PYTHONIOENCODING") = "utf-8"
objShell.Environment("Process")("HOME_SERVER") = "1"
objShell.CurrentDirectory = "C:\bitman_marketfloww"
objShell.Run """C:\bitman_marketfloww\.venv\Scripts\python.exe"" flask_app.py", 0, False

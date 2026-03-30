Set objShell = CreateObject("WScript.Shell")
objShell.CurrentDirectory = "C:\bitman_marketfloww"
objShell.Environment("Process")("PYTHONIOENCODING") = "utf-8"
objShell.Run """C:\bitman_marketfloww\.venv\Scripts\python.exe"" flask_app.py", 0, True

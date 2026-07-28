Option Explicit

Dim shell, fso, root, pythonExe, apiDir, logDir, command
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

root = "C:\GoodrichTradingOS"
pythonExe = root & "\.venv\Scripts\python.exe"
apiDir = root & "\services\api"
logDir = root & "\logs"

If Not fso.FolderExists(logDir) Then
    fso.CreateFolder(logDir)
End If

shell.Environment("PROCESS")("PYTHONIOENCODING") = "utf-8"
shell.Environment("PROCESS")("GOODRICH_ENVIRONMENT") = "production"
shell.Environment("PROCESS")("GOODRICH_DATABASE_URL") = "sqlite:///" & Replace(root & "\data\goodrich.db", "\", "/")
shell.Environment("PROCESS")("GOODRICH_KIS_CREDENTIALS_FILE") = root & "\secrets\kis_credentials.txt"
shell.Environment("PROCESS")("GOODRICH_OPENAI_CREDENTIALS_FILE") = root & "\secrets\openai_credentials.txt"
shell.Environment("PROCESS")("GOODRICH_CORS_ORIGINS") = "https://bit-man.net,https://www.bit-man.net"

shell.CurrentDirectory = apiDir
command = """" & pythonExe & """ -m uvicorn goodrich.main:app --host 127.0.0.1 --port 8000" & _
    " 1>>""" & logDir & "\goodrich.out.log"" 2>>""" & logDir & "\goodrich.err.log"""
shell.Run command, 0, False

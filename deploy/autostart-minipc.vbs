' MarketFlow Mini PC user-session worker auto-start
' 로그인 시 legacy Flask(5001)만 시작한다.
' Cloudflared/Scheduler는 SYSTEM 예약 작업이 단독 관리한다.
' 설치: 이 파일의 바로가기를 시작프로그램 폴더에 배치
' C:\Users\dynas\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup

Option Explicit
Dim objShell, objFSO, objWMI, logFile, PROJECT, PYTHON

Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")
Set objWMI = GetObject("winmgmts:\\.\root\cimv2")

PROJECT = "C:\bitman_marketfloww"
PYTHON = PROJECT & "\.venv\Scripts\python.exe"

objShell.Environment("Process")("PYTHONIOENCODING") = "utf-8"
objShell.Environment("Process")("HOME_SERVER") = "1"

Dim logDir : logDir = PROJECT & "\logs"
If Not objFSO.FolderExists(logDir) Then objFSO.CreateFolder(logDir)
Set logFile = objFSO.OpenTextFile(logDir & "\autostart.log", 8, True)

Sub Log(msg)
    logFile.WriteLine Now & " | " & msg
End Sub

Function IsProcessRunning(cmdPattern)
    Dim colProcesses
    IsProcessRunning = False
    Set colProcesses = objWMI.ExecQuery("SELECT CommandLine FROM Win32_Process WHERE CommandLine LIKE '%" & cmdPattern & "%'")
    If colProcesses.Count > 0 Then IsProcessRunning = True
End Function

Function IsPortOpen(port)
    On Error Resume Next
    Dim objHTTP
    Set objHTTP = CreateObject("MSXML2.XMLHTTP")
    objHTTP.Open "GET", "http://127.0.0.1:" & port & "/", False
    objHTTP.setRequestHeader "Connection", "close"
    objHTTP.Send
    IsPortOpen = (Err.Number = 0)
    On Error GoTo 0
End Function

Log "========== MINI PC AUTO START BEGIN =========="
WScript.Sleep 15000

' ── 1. Flask API (port 5001) ──
If IsPortOpen(5001) Then
    Log "Flask: already running"
Else
    Log "Flask: starting..."
    objShell.CurrentDirectory = PROJECT
    objShell.Run """" & PYTHON & """ flask_app.py", 0, False
    Dim i
    For i = 1 To 10
        WScript.Sleep 3000
        If IsPortOpen(5001) Then
            Log "Flask: OK (port 5001)"
            Exit For
        End If
    Next
    If Not IsPortOpen(5001) Then Log "Flask: FAILED"
End If

' Cloudflared와 Scheduler는 MarketFlow SYSTEM 작업에서 관리한다.
' 여기서 다시 시작하면 동일 데이터/포트를 공유하는 중복 런타임이 생길 수 있다.

Log "========== MINI PC AUTO START END =========="
logFile.Close

' MarketFlow Auto-Start (단일 스크립트)
' 로그인 시 Flask + Next.js + Cloudflared + Scheduler 자동 시작
' 이미 실행 중이면 스킵 (중복 방지)
'
' 설치: 이 파일의 바로가기를 시작프로그램 폴더에 배치
' C:\Users\dynas\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup

Option Explicit
Dim objShell, objFSO, objWMI, logFile, PROJECT, PYTHON, FRONTEND

Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")
Set objWMI = GetObject("winmgmts:\\.\root\cimv2")

PROJECT = "C:\bitman_marketfloww"
PYTHON = PROJECT & "\.venv\Scripts\python.exe"
FRONTEND = PROJECT & "\frontend-react"

' 환경변수 설정
objShell.Environment("Process")("PYTHONIOENCODING") = "utf-8"

' 로그 파일
Dim logDir : logDir = PROJECT & "\logs"
If Not objFSO.FolderExists(logDir) Then objFSO.CreateFolder(logDir)
Set logFile = objFSO.OpenTextFile(logDir & "\autostart.log", 8, True)

Sub Log(msg)
    logFile.WriteLine Now & " | " & msg
End Sub

Function IsProcessRunning(cmdPattern)
    Dim colProcesses, objProcess
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

' ── 네트워크 대기 (15초) ──
Log "========== AUTO START BEGIN =========="
WScript.Sleep 15000

' ── 1. Flask API (port 5001) ──
If IsPortOpen(5001) Then
    Log "Flask: already running (port 5001 open)"
Else
    Log "Flask: starting..."
    objShell.CurrentDirectory = PROJECT
    objShell.Run """" & PYTHON & """ flask_app.py", 0, False
    ' 포트 오픈 대기 (최대 30초)
    Dim i
    For i = 1 To 10
        WScript.Sleep 3000
        If IsPortOpen(5001) Then
            Log "Flask: OK (port 5001)"
            Exit For
        End If
    Next
    If Not IsPortOpen(5001) Then Log "Flask: FAILED to start"
End If

' ── 2. Next.js Frontend (port 4000) ──
If IsPortOpen(4000) Then
    Log "Next.js: already running (port 4000 open)"
Else
    Log "Next.js: starting..."
    objShell.CurrentDirectory = FRONTEND
    objShell.Run "cmd /c ""cd /d " & FRONTEND & " && npm run dev""", 0, False
    Dim j
    For j = 1 To 10
        WScript.Sleep 3000
        If IsPortOpen(4000) Then
            Log "Next.js: OK (port 4000)"
            Exit For
        End If
    Next
    If Not IsPortOpen(4000) Then Log "Next.js: FAILED to start"
End If

' ── 3. Cloudflared Tunnel ──
If IsProcessRunning("cloudflared") Then
    Log "Cloudflared: already running"
Else
    Log "Cloudflared: starting Named Tunnel (bitman-api)..."
    objShell.CurrentDirectory = PROJECT
    objShell.Run """" & PROJECT & "\cloudflared.exe"" tunnel --config ""C:\Users\dynas\.cloudflared\config.yml"" run bitman-api", 0, False
    WScript.Sleep 8000
    If IsProcessRunning("cloudflared") Then
        Log "Cloudflared: OK"
    Else
        Log "Cloudflared: FAILED"
    End If
End If

' ── 4. Scheduler Daemon ──
If IsProcessRunning("scheduler.py") Then
    Log "Scheduler: already running"
Else
    Log "Scheduler: starting daemon..."
    objShell.CurrentDirectory = PROJECT
    objShell.Run """" & PYTHON & """ scheduler.py --daemon", 0, False
    WScript.Sleep 8000
    If IsProcessRunning("scheduler.py") Then
        Log "Scheduler: OK"
    Else
        Log "Scheduler: FAILED"
    End If
End If

Log "========== AUTO START END =========="
logFile.Close

' ── 5. Watchdog 루프 (5분 간격 헬스체크 + 자동 재시작) ──
' VBS는 종료되지 않고 계속 실행 — 이게 watchdog 역할
Dim restartCount
restartCount = 0

Do While True
    WScript.Sleep 300000  ' 5분 대기

    Set logFile = objFSO.OpenTextFile(logDir & "\autostart.log", 8, True)

    ' Flask 체크
    If Not IsPortOpen(5001) Then
        Log "WATCHDOG: Flask DOWN — restarting..."
        objShell.CurrentDirectory = PROJECT
        objShell.Run """" & PYTHON & """ flask_app.py", 0, False
        WScript.Sleep 10000
        If IsPortOpen(5001) Then
            Log "WATCHDOG: Flask restarted OK"
        Else
            Log "WATCHDOG: Flask restart FAILED"
        End If
        restartCount = restartCount + 1
    End If

    ' Next.js 체크
    If Not IsPortOpen(4000) Then
        Log "WATCHDOG: Next.js DOWN — restarting..."
        objShell.CurrentDirectory = FRONTEND
        objShell.Run "cmd /c ""cd /d " & FRONTEND & " && npm run dev""", 0, False
        WScript.Sleep 15000
        If IsPortOpen(4000) Then
            Log "WATCHDOG: Next.js restarted OK"
        Else
            Log "WATCHDOG: Next.js restart FAILED"
        End If
        restartCount = restartCount + 1
    End If

    ' Cloudflared 체크
    If Not IsProcessRunning("cloudflared") Then
        Log "WATCHDOG: Cloudflared DOWN — restarting..."
        objShell.CurrentDirectory = PROJECT
        objShell.Run """" & PROJECT & "\cloudflared.exe"" tunnel --config ""C:\Users\dynas\.cloudflared\config.yml"" run bitman-api", 0, False
        WScript.Sleep 8000
        Log "WATCHDOG: Cloudflared restarted"
        restartCount = restartCount + 1
    End If

    ' Scheduler 체크
    If Not IsProcessRunning("scheduler.py") Then
        Log "WATCHDOG: Scheduler DOWN — restarting..."
        objShell.CurrentDirectory = PROJECT
        objShell.Run """" & PYTHON & """ scheduler.py --daemon", 0, False
        WScript.Sleep 8000
        Log "WATCHDOG: Scheduler restarted"
        restartCount = restartCount + 1
    End If

    logFile.Close
Loop

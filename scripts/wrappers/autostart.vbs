' MarketFlow Auto-Start (단일 스크립트)
' 로그인 시 Flask + Vite React + Cloudflared + Scheduler 자동 시작
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

Function CountProcessByCmd(cmdPattern)
    Dim colProcesses
    Set colProcesses = objWMI.ExecQuery("SELECT ProcessId FROM Win32_Process WHERE CommandLine LIKE '%" & cmdPattern & "%'")
    CountProcessByCmd = colProcesses.Count
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

Function IsPortOpenLocal(port)
    ' localhost 로도 체크 (IPv6 바인딩 대응)
    On Error Resume Next
    Dim objHTTP
    Set objHTTP = CreateObject("MSXML2.XMLHTTP")
    objHTTP.Open "GET", "http://localhost:" & port & "/", False
    objHTTP.setRequestHeader "Connection", "close"
    objHTTP.Send
    IsPortOpenLocal = (Err.Number = 0)
    On Error GoTo 0
End Function

Function AnyPortOpen(port)
    AnyPortOpen = IsPortOpen(port) Or IsPortOpenLocal(port)
End Function

' ── 네트워크 대기 (15초) ──
Log "========== AUTO START BEGIN =========="
WScript.Sleep 15000

' ── 1. Flask API (port 5001) ──
If AnyPortOpen(5001) Then
    Log "Flask: already running (port 5001 open)"
Else
    Log "Flask: starting..."
    objShell.CurrentDirectory = PROJECT
    objShell.Run """" & PYTHON & """ flask_app.py", 0, False
    ' 포트 오픈 대기 (최대 30초)
    Dim i
    For i = 1 To 10
        WScript.Sleep 3000
        If AnyPortOpen(5001) Then
            Log "Flask: OK (port 5001)"
            Exit For
        End If
    Next
    If Not AnyPortOpen(5001) Then Log "Flask: FAILED to start"
End If

' ── 2. Vite React Frontend (port 4000) ──
If AnyPortOpen(4000) Then
    Log "Frontend: already running (port 4000 open)"
Else
    Log "Frontend: starting..."
    objShell.CurrentDirectory = FRONTEND
    objShell.Run "cmd /c ""cd /d " & FRONTEND & " && npm run dev""", 0, False
    Dim j
    For j = 1 To 15
        WScript.Sleep 3000
        If AnyPortOpen(4000) Then
            Log "Frontend: OK (port 4000)"
            Exit For
        End If
    Next
    If Not AnyPortOpen(4000) Then Log "Frontend: FAILED to start"
End If

' ── 3. Cloudflared Tunnel ──
' 중요: Windows 서비스(SYSTEM)로 돌아가는 cloudflared는 사용자 config 못 읽어서 530 발생
' 따라서 "bitman-api" 커맨드라인이 포함된 프로세스만 체크 (사용자 세션 터널)
If IsProcessRunning("cloudflared"" tunnel") Then
    ' 추가 확인: 실제로 bitman-api 터널인지
    If IsProcessRunning("run bitman-api") Then
        Log "Cloudflared: already running (user tunnel)"
    Else
        ' SYSTEM 서비스만 돌고 있을 수 있음 — 사용자 터널 시작
        Log "Cloudflared: SYSTEM service detected, starting user tunnel..."
        objShell.CurrentDirectory = PROJECT
        objShell.Run """" & PROJECT & "\cloudflared.exe"" tunnel --config ""C:\Users\dynas\.cloudflared\config.yml"" run bitman-api", 0, False
        WScript.Sleep 8000
        If IsProcessRunning("run bitman-api") Then
            Log "Cloudflared: OK (user tunnel started)"
        Else
            Log "Cloudflared: FAILED"
        End If
    End If
Else
    Log "Cloudflared: starting Named Tunnel (bitman-api)..."
    objShell.CurrentDirectory = PROJECT
    objShell.Run """" & PROJECT & "\cloudflared.exe"" tunnel --config ""C:\Users\dynas\.cloudflared\config.yml"" run bitman-api", 0, False
    WScript.Sleep 8000
    If IsProcessRunning("run bitman-api") Then
        Log "Cloudflared: OK"
    Else
        Log "Cloudflared: FAILED"
    End If
End If

' ── 4. Scheduler Daemon ──
' scheduler.py --daemon 커맨드라인으로 정확히 체크
If IsProcessRunning("scheduler.py --daemon") Then
    Log "Scheduler: already running"
Else
    Log "Scheduler: starting daemon..."
    objShell.CurrentDirectory = PROJECT
    objShell.Run """" & PYTHON & """ scheduler.py --daemon", 0, False
    WScript.Sleep 8000
    If IsProcessRunning("scheduler.py --daemon") Then
        Log "Scheduler: OK"
    Else
        Log "Scheduler: FAILED"
    End If
End If

Log "========== AUTO START END =========="
logFile.Close

' ── 5. Watchdog 루프 (5분 간격 헬스체크 + 자동 재시작) ──
Dim restartCount
restartCount = 0

Do While True
    WScript.Sleep 300000  ' 5분 대기

    Set logFile = objFSO.OpenTextFile(logDir & "\autostart.log", 8, True)

    ' Flask 체크
    If Not AnyPortOpen(5001) Then
        Log "WATCHDOG: Flask DOWN — restarting..."
        objShell.CurrentDirectory = PROJECT
        objShell.Run """" & PYTHON & """ flask_app.py", 0, False
        WScript.Sleep 10000
        If AnyPortOpen(5001) Then
            Log "WATCHDOG: Flask restarted OK"
        Else
            Log "WATCHDOG: Flask restart FAILED"
        End If
        restartCount = restartCount + 1
    End If

    ' Frontend 체크
    If Not AnyPortOpen(4000) Then
        Log "WATCHDOG: Frontend DOWN — restarting..."
        objShell.CurrentDirectory = FRONTEND
        objShell.Run "cmd /c ""cd /d " & FRONTEND & " && npm run dev""", 0, False
        WScript.Sleep 15000
        If AnyPortOpen(4000) Then
            Log "WATCHDOG: Frontend restarted OK"
        Else
            Log "WATCHDOG: Frontend restart FAILED"
        End If
        restartCount = restartCount + 1
    End If

    ' Cloudflared 체크 — 사용자 터널(bitman-api)만 체크
    If Not IsProcessRunning("run bitman-api") Then
        Log "WATCHDOG: Cloudflared user tunnel DOWN — restarting..."
        objShell.CurrentDirectory = PROJECT
        objShell.Run """" & PROJECT & "\cloudflared.exe"" tunnel --config ""C:\Users\dynas\.cloudflared\config.yml"" run bitman-api", 0, False
        WScript.Sleep 8000
        Log "WATCHDOG: Cloudflared restarted"
        restartCount = restartCount + 1
    End If

    ' Scheduler 체크
    If Not IsProcessRunning("scheduler.py --daemon") Then
        Log "WATCHDOG: Scheduler DOWN — restarting..."
        objShell.CurrentDirectory = PROJECT
        objShell.Run """" & PYTHON & """ scheduler.py --daemon", 0, False
        WScript.Sleep 8000
        Log "WATCHDOG: Scheduler restarted"
        restartCount = restartCount + 1
    End If

    logFile.Close
Loop

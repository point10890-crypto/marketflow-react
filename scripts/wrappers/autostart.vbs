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

' ── 3. Cloudflared Tunnel — DISABLED 2026-04-13 ──
' 미니PC 에서 터널 단독 운영. 본 PC 에서 같은 터널을 실행하면
' Cloudflare 가 로드밸런싱하여 Flask 가 없는 본 PC 로 트래픽이
' 분산되어 앱이 간헐적으로 실패함.
Log "Cloudflared: SKIPPED (mini-PC only)"

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

' ── 5. Watchdog Service — REMOVED 2026-04-08 ──
' watchdog_service.py / healthcheck.py 폐기. 사유:
'   - 2일치 로그상 유익한 동작 0건 (Flask 재시작 1회는 Task Scheduler 와 중복)
'   - Spring Boot "재시작 성공" 4건/일 false positive — JUST BUY 8080 과 충돌
'   - Cloudflared restart 는 no-op, Scheduler restart 는 대부분 실패
' Task Scheduler MarketFlow-V1-Flask + MarketFlow-Scheduler 가 모든 재시작을 처리.

Log "========== AUTO START END =========="
logFile.Close

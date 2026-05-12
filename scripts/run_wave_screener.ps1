# run_wave_screener.ps1
# Wave Pattern Screener (W/M 패턴 전 시장 스캔) 자동 실행 launcher.
# 매일 장 마감 후 Task Scheduler 가 1회 호출.
#
# 출력:
#   data/wave/wave_screener_latest.json   (갱신)
#   logs/wave_screener_YYYYMMDD.log       (실행 로그)
#
# 호출: powershell -ExecutionPolicy Bypass -File run_wave_screener.ps1

$Root = "C:\bitman_marketfloww"
$Py = "$Root\.venv\Scripts\python.exe"
$LogDir = "$Root\logs"
$DateStr = Get-Date -Format "yyyyMMdd"
$LogFile = "$LogDir\wave_screener_$DateStr.log"
$ErrFile = "$LogDir\wave_screener_$DateStr.err.log"

# 로그 디렉토리 보장
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
}

function Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $LogFile -Value "[$ts] $msg" -Encoding UTF8 -ErrorAction SilentlyContinue
}

Log "===== run_wave_screener.ps1 시작 ====="

# 동시 실행 방지 — 이미 wave_screener 가 가동 중이면 skip
$existing = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue `
    | Where-Object { $_.CommandLine -like '*engine.wave.screener*' }
if ($existing) {
    Log "이미 wave_screener 프로세스 가동 중 (PID $($existing.ProcessId -join ',')) — skip"
    exit 0
}

Set-Location $Root
$env:PYTHONIOENCODING = 'utf-8'

# Python 실행 (-m engine.wave.screener KR)
Log "Python 실행: $Py -m engine.wave.screener KR"
$started = Get-Date
try {
    $process = Start-Process -FilePath $Py `
        -ArgumentList '-m', 'engine.wave.screener', 'KR' `
        -WorkingDirectory $Root `
        -RedirectStandardOutput $LogFile `
        -RedirectStandardError $ErrFile `
        -Wait `
        -PassThru `
        -WindowStyle Hidden
    $duration = (Get-Date) - $started
    Log "완료 — exit=$($process.ExitCode), duration=$([int]$duration.TotalSeconds)s"
} catch {
    Log "ERROR: $($_.Exception.Message)"
    exit 1
}

# 결과 검증 — wave_screener_latest.json 갱신 확인
$resultJson = "$Root\data\wave\wave_screener_latest.json"
if (Test-Path $resultJson) {
    $mtime = (Get-Item $resultJson).LastWriteTime
    $ageMin = ((Get-Date) - $mtime).TotalMinutes
    Log "결과 파일 mtime=$mtime (방금 갱신 ${ageMin:N1}분 전)"
    if ($ageMin -le 30) {
        Log "===== 정상 완료 ====="
        exit 0
    } else {
        Log "WARN: 결과 파일이 30분 이상 오래됨 — 갱신 실패 가능성"
        exit 2
    }
} else {
    Log "ERROR: 결과 파일 없음 — $resultJson"
    exit 3
}

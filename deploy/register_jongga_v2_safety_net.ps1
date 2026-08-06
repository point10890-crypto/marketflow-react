# 종가베팅 V2 안전망 작업 등록 — 관리자 PowerShell 에서 1회 실행
#
# 왜 별도 태스크인가
# ------------------
# 스케줄러 데몬은 단일 스레드 루프에서 작업을 동기 실행한다. 앞선 작업이 길어지면
# 14:50 슬롯이 밀리고, 밀린 것을 되찾을 '놓친 스케줄 점검' 도 같은 루프에 있어
# 함께 멈춘다. 하트비트는 계속 갱신되므로 워치독도 장애로 보지 않는다.
# (2026-08-06 실측: 점검 간격 5분 -> 36분 -> 52분 정지, 그날 V2 미생성)
#
# 기존 MarketFlow-Jongga-Telegram-1510 은 scheduler.py 를 부르므로 데몬의 파일 락에
# 막혀 매번 즉시 실패한다 — 안전망이 되지 못한다.
#
# 이 태스크는 엔진을 직접 부르고, 오늘자 결과가 이미 있으면 아무것도 하지 않는다.

$ErrorActionPreference = 'Stop'

$Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$Role = New-Object Security.Principal.WindowsPrincipal($Identity)
if (-not $Role.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error '관리자 권한 PowerShell 에서 실행하세요.'
    exit 1
}

$Root = 'C:\bitman_marketfloww'
$TaskName = 'MarketFlow-Jongga-V2-SafetyNet'

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -MultipleInstances IgnoreNew

$Principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -RunLevel Highest

# 15:35 — 장 마감(15:30) 이후, 데몬의 14:50 시도가 실패했을 때를 메운다.
# 16:40 — 15:35 마저 놓쳤을 때의 2차. 결과가 있으면 즉시 종료하므로 중복 비용은 없다.
$Triggers = @(
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At '15:35'
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At '16:40'
)

$Action = New-ScheduledTaskAction `
    -Execute "$Root\.venv\Scripts\python.exe" `
    -Argument "scripts\ensure_jongga_v2.py" `
    -WorkingDirectory $Root

Register-ScheduledTask -TaskName $TaskName `
    -Action $Action -Trigger $Triggers -Settings $Settings -Principal $Principal -Force | Out-Null

Write-Output "등록 완료: $TaskName"
Get-ScheduledTask -TaskName $TaskName | ForEach-Object {
    $info = $_ | Get-ScheduledTaskInfo
    Write-Output ("  상태 {0}   다음 실행 {1}" -f $_.State, $info.NextRunTime)
}

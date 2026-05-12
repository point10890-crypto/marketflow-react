# start_mirofish_tunnel.ps1
# 본PC ↔ miniPC SSH 터널 (포트 8765) 가동 — mirofish-mcp 접근용
# Windows Task Scheduler 가 사용자 로그온 시 자동 실행
#
# 동작:
#   1. 기존 8765 LocalPort 포워딩 SSH 프로세스가 있으면 종료
#   2. 새 SSH 터널을 daemon 모드(-N -f)로 백그라운드 가동
#   3. ServerAliveInterval 30s + ExitOnForwardFailure → 끊김 자동 감지
#   4. 시작 흔적을 로그에 기록
#
# 호스트 변경 시 $RemoteHost / $RemoteUser 만 수정.

$LogPath  = "C:\bitman_marketfloww\logs\mirofish_tunnel.log"
$RemoteUser = "dynas"
$RemoteHost = "192.168.55.103"
$LocalPort  = 8765
$RemotePort = 8765

# 로그 디렉토리 보장
$LogDir = Split-Path $LogPath -Parent
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
}

function Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $LogPath -Value "[$ts] $msg" -Encoding UTF8 -ErrorAction SilentlyContinue
}

Log "===== start_mirofish_tunnel.ps1 ====="

# 1) 기존 8765 LocalPort listener 가 있다면 SSH 프로세스 찾아 종료
$existing = Get-NetTCPConnection -LocalPort $LocalPort -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    foreach ($conn in $existing) {
        $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
        if ($proc -and $proc.ProcessName -ieq 'ssh') {
            Log "기존 SSH tunnel PID=$($proc.Id) 종료"
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 1
        } else {
            Log "포트 $LocalPort 이 다른 프로세스($($proc.ProcessName)) 점유 중 — skip"
        }
    }
}

# 2) 새 SSH 터널 백그라운드 가동
#   -N : remote command 없이 forwarding 전용
#   -o ServerAliveInterval=30 / CountMax=3 : 90s 무응답 시 SSH 자동 종료 (재시작 트리거)
#   -o ExitOnForwardFailure=yes : 터널 fail 시 즉시 종료
#   -o StrictHostKeyChecking=accept-new : 새 호스트 자동 수락
$sshArgs = @(
    '-N',
    '-L', "${LocalPort}:127.0.0.1:${RemotePort}",
    '-o', 'ServerAliveInterval=30',
    '-o', 'ServerAliveCountMax=3',
    '-o', 'ExitOnForwardFailure=yes',
    '-o', 'StrictHostKeyChecking=accept-new',
    '-o', 'UserKnownHostsFile=' + ($env:USERPROFILE + '\.ssh\known_hosts'),
    "${RemoteUser}@${RemoteHost}"
)

Log "SSH tunnel 가동: ssh $($sshArgs -join ' ')"

# Start-Process 로 detached 가동 (이 스크립트 종료 후에도 SSH 살아있음)
$sshProc = Start-Process -FilePath 'ssh' -ArgumentList $sshArgs -PassThru -WindowStyle Hidden -RedirectStandardError ($LogDir + '\mirofish_tunnel_err.log')

if ($sshProc) {
    Log "SSH tunnel 가동 완료 (PID=$($sshProc.Id))"

    # 3) 가동 검증 (최대 8초 대기)
    $verified = $false
    for ($i = 0; $i -lt 8; $i++) {
        Start-Sleep -Seconds 1
        $listener = Get-NetTCPConnection -LocalPort $LocalPort -State Listen -ErrorAction SilentlyContinue
        if ($listener) {
            $verified = $true
            Log "포트 $LocalPort listener 확인 (PID=$($listener[0].OwningProcess))"
            break
        }
    }
    if (-not $verified) {
        Log "WARN: 8초 내 listener 미확인 — SSH 인증 또는 네트워크 문제 가능성"
    }
} else {
    Log "ERROR: SSH 프로세스 시작 실패"
    exit 1
}

Log "===== 완료 ====="
exit 0

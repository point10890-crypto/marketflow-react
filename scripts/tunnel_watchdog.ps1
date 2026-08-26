# MarketFlow tunnel watchdog
# 외부 경로(https://marketflow-api.bit-man.net/healthz)가 죽었는데 로컬 Flask 는
# 살아있는 "터널만 죽은" 상태를 감지해 Cloudflared 를 자동 복구한다.
# 2026-08-11 간헐 접속불가 사고 대응 — 기존 watchdog 은 로컬 healthz 만 봐서
# 터널 계층 장애를 전혀 감지하지 못했다.
#
# 등록: schtasks /Create /TN MarketFlow-Tunnel-Watchdog
#         /TR "powershell -NoProfile -ExecutionPolicy Bypass -File C:\bitman_marketfloww\scripts\tunnel_watchdog.ps1"
#         /SC MINUTE /MO 5 /RU SYSTEM /RL HIGHEST /F

$ErrorActionPreference = 'Continue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Root = 'C:\bitman_marketfloww'
$LogFile = Join-Path $Root 'logs\tunnel_watchdog.log'
$StateFile = Join-Path $Root 'logs\tunnel_watchdog.state'
$RestartRequestFile = Join-Path $Root 'data\tunnel_restart.request'
$ExternalUrl = 'https://marketflow-api.bit-man.net/healthz'
$LocalUrl = 'http://127.0.0.1:5003/healthz'
$RestartCooldownMinutes = 30
$MarketFlowUserConfig = 'C:\Users\dynas\.cloudflared\config.yml'

function Write-Log([string]$msg) {
    $line = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' ' + $msg
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

# 로그 5MB 초과 시 절반 롤오버
if ((Test-Path $LogFile) -and ((Get-Item $LogFile).Length -gt 5MB)) {
    $tail = Get-Content $LogFile -Tail 2000
    Set-Content -Path $LogFile -Value $tail -Encoding UTF8
}

function Test-Url([string]$url) {
    try {
        $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 15
        return ($resp.StatusCode -eq 200)
    } catch {
        return $false
    }
}

function Get-CloudflaredService {
    Get-CimInstance Win32_Service -Filter "Name='Cloudflared'" -ErrorAction SilentlyContinue |
        Select-Object -First 1
}

function Get-DuplicateMarketFlowConnectors([int]$ServicePid) {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            if ($_.Name -ne 'cloudflared.exe' -or $_.ProcessId -eq $ServicePid) {
                return $false
            }
            $commandLine = [string]$_.CommandLine
            if (-not $commandLine) {
                # Never stop a connector that cannot be attributed to this tunnel.
                return $false
            }
            return (
                $commandLine -like "*$MarketFlowUserConfig*" -or
                $commandLine -match '(?i)\brun\s+bitman-api(?:\s|$)'
            )
        }
}

function Restart-CanonicalTunnel {
    $service = Get-Service -Name 'Cloudflared' -ErrorAction SilentlyContinue
    if (-not $service) {
        Write-Log 'canonical Cloudflared service is missing; refusing user-connector fallback'
        return $false
    }
    try {
        if ($service.Status -eq 'Running') {
            Restart-Service -Name 'Cloudflared' -Force -ErrorAction Stop
            Write-Log 'canonical Cloudflared service restarted'
        } else {
            Start-Service -Name 'Cloudflared' -ErrorAction Stop
            Write-Log 'canonical Cloudflared service started'
        }
        return $true
    } catch {
        Write-Log "canonical service recovery failed: $_"
        return $false
    }
}

$forceRestart = Test-Path -LiteralPath $RestartRequestFile
if ($forceRestart) {
    Write-Log 'deployment tunnel restart requested'
    # Consume first so a failed recovery cannot create a five-minute restart loop.
    Remove-Item -LiteralPath $RestartRequestFile -Force -ErrorAction SilentlyContinue

    $serviceInfo = Get-CloudflaredService
    if (-not $serviceInfo) {
        Write-Log 'canonical Cloudflared service is missing; request aborted'
        exit 1
    }

    $servicePid = [int]$serviceInfo.ProcessId
    $duplicates = @(Get-DuplicateMarketFlowConnectors -ServicePid $servicePid)
    foreach ($process in $duplicates) {
        try {
            Stop-Process -Id ([int]$process.ProcessId) -Force -ErrorAction Stop
            Write-Log "stopped duplicate MarketFlow tunnel connector pid=$($process.ProcessId)"
        } catch {
            Write-Log "failed to stop duplicate connector pid=$($process.ProcessId): $_"
        }
    }

    if (-not (Restart-CanonicalTunnel)) { exit 1 }
    Set-Content -Path $StateFile -Value (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') -Encoding UTF8
    Start-Sleep -Seconds 20
    $after = Test-Url $ExternalUrl
    Write-Log "deployment restart external ok=$after duplicates_removed=$($duplicates.Count)"
    if ($after) { exit 0 } else { exit 1 }
}

# 외부 검사: 2회 (일시 흔들림 오탐 방지)
$externalOk = Test-Url $ExternalUrl
if (-not $externalOk) {
    Start-Sleep -Seconds 10
    $externalOk = Test-Url $ExternalUrl
}

if ($externalOk) {
    # 정상 — 조용히 종료 (성공은 로그 안 남겨 로그 오염 방지)
    exit 0
}

$localOk = Test-Url $LocalUrl
Write-Log "EXTERNAL DOWN (2 tries). local Flask ok=$localOk"

if (-not $localOk) {
    # Flask 자체가 죽음 — 이 스크립트 소관 아님 (Flask watchdog 담당). 기록만.
    Write-Log 'local Flask also down -> leaving to Flask watchdog, no tunnel restart'
    exit 0
}

# 쿨다운: 30분 내 재시작 이력 있으면 스킵
if (Test-Path $StateFile) {
    try {
        $last = [datetime]::ParseExact((Get-Content $StateFile -First 1), 'yyyy-MM-dd HH:mm:ss', $null)
        if (((Get-Date) - $last).TotalMinutes -lt $RestartCooldownMinutes) {
            Write-Log "cooldown active (last restart $last) -> skip"
            exit 0
        }
    } catch {}
}

if (-not (Restart-CanonicalTunnel)) { exit 1 }

Set-Content -Path $StateFile -Value (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') -Encoding UTF8

Start-Sleep -Seconds 20
$after = Test-Url $ExternalUrl
Write-Log "post-restart external ok=$after"

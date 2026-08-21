# Idempotently apply the MarketFlow Claw .env contract on this host. No secrets are read from git;
# every value is copied from keys that already exist in the local .env.
#
#   .\scripts\apply_claw_env.ps1                      # add CLAW_* keys (delivery stays OFF)
#   .\scripts\apply_claw_env.ps1 -EnableDelivery      # also CLAW_DELIVERY_ENABLED=1
#   .\scripts\apply_claw_env.ps1 -SwapPersonalBotToken # TELEGRAM_BOT_TOKEN := TELEGRAM_CHANNEL_BOT_TOKEN
#                                                       (old value kept as a commented backup line)
#
# What it guarantees afterwards:
#   CLAW_TELEGRAM_BOT_TOKEN_KEY=TELEGRAM_CHANNEL_BOT_TOKEN
#   CLAW_TELEGRAM_CHAT_ID=<value of TELEGRAM_CHAT_ID>
#   CLAW_DROP_CONFIRM_TICKS=3
#   CLAW_DELIVERY_ENABLED=0|1
# A timestamped backup .env.bak_claw_YYYYMMDD_HHMMSS is written before any change.

param(
    [switch]$EnableDelivery,
    [switch]$SwapPersonalBotToken,
    [string]$Project = 'C:\bitman_marketfloww'
)
$ErrorActionPreference = 'Stop'
$envFile = Join-Path $Project '.env'
if (-not (Test-Path $envFile)) { throw ".env not found: $envFile" }

$bytes = [System.IO.File]::ReadAllBytes($envFile)
$hasBom = ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)
$text = [System.Text.Encoding]::UTF8.GetString($bytes)
if ($hasBom) { $text = $text.TrimStart([char]0xFEFF) }
$nl = if ($text.Contains("`r`n")) { "`r`n" } else { "`n" }
$lines = [System.Collections.Generic.List[string]]($text -split "`r?`n")
if ($lines.Count -gt 0 -and $lines[$lines.Count - 1] -eq '') { $lines.RemoveAt($lines.Count - 1) }

function Get-Val($name) {
    foreach ($l in $lines) { if ($l -match ("^" + [regex]::Escape($name) + "=(.*)$")) { return $Matches[1].Trim() } }
    return $null
}
function Set-Val($name, $value) {
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match ("^" + [regex]::Escape($name) + "=")) { $lines[$i] = "$name=$value"; return "updated" }
    }
    $lines.Add("$name=$value"); return "added"
}

$chat = Get-Val 'TELEGRAM_CHAT_ID'
$chTok = Get-Val 'TELEGRAM_CHANNEL_BOT_TOKEN'
if (-not $chat)  { throw "TELEGRAM_CHAT_ID missing in .env - cannot derive CLAW_TELEGRAM_CHAT_ID" }
if (-not $chTok) { throw "TELEGRAM_CHANNEL_BOT_TOKEN missing in .env" }

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
Copy-Item $envFile (Join-Path $Project ".env.bak_claw_$stamp")

$report = @{}
if (-not ($lines | Where-Object { $_ -match '^# MarketFlow Claw' })) {
    $lines.Add(''); $lines.Add('# MarketFlow Claw (applied by scripts/apply_claw_env.ps1)')
}
$report['CLAW_TELEGRAM_BOT_TOKEN_KEY'] = Set-Val 'CLAW_TELEGRAM_BOT_TOKEN_KEY' 'TELEGRAM_CHANNEL_BOT_TOKEN'
$report['CLAW_TELEGRAM_CHAT_ID']       = Set-Val 'CLAW_TELEGRAM_CHAT_ID' $chat
if ($null -eq (Get-Val 'CLAW_DROP_CONFIRM_TICKS')) { $report['CLAW_DROP_CONFIRM_TICKS'] = Set-Val 'CLAW_DROP_CONFIRM_TICKS' '3' }
if ($EnableDelivery) { $report['CLAW_DELIVERY_ENABLED'] = Set-Val 'CLAW_DELIVERY_ENABLED' '1' }
elseif ($null -eq (Get-Val 'CLAW_DELIVERY_ENABLED')) { $report['CLAW_DELIVERY_ENABLED'] = Set-Val 'CLAW_DELIVERY_ENABLED' '0' }

if ($SwapPersonalBotToken) {
    $old = Get-Val 'TELEGRAM_BOT_TOKEN'
    if ($old -and $old -ne $chTok) {
        for ($i = 0; $i -lt $lines.Count; $i++) {
            if ($lines[$i] -match '^TELEGRAM_BOT_TOKEN=') {
                $lines[$i] = "TELEGRAM_BOT_TOKEN=$chTok"
                $lines.Insert($i, "# TELEGRAM_BOT_TOKEN_HERMES_OLD=$old")
                $lines.Insert($i, "# $stamp swapped: old token below was @bitmanHermes_bot (user deleted the chat -> 403)")
                break
            }
        }
        $report['TELEGRAM_BOT_TOKEN'] = 'swapped to channel bot token'
    } else {
        $report['TELEGRAM_BOT_TOKEN'] = 'already channel bot token (no change)'
    }
}

$out = ($lines -join $nl) + $nl
$enc = New-Object System.Text.UTF8Encoding($hasBom)
[System.IO.File]::WriteAllText($envFile, $out, $enc)

Write-Host "[OK] .env updated (backup .env.bak_claw_$stamp)"
foreach ($k in $report.Keys | Sort-Object) { Write-Host ("  {0,-28} {1}" -f $k, $report[$k]) }
Write-Host "Next: .venv\Scripts\python.exe -m marketflow_claw doctor"

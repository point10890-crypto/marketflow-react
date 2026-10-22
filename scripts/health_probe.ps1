# Windows PowerShell 5.1 supervisor. Never rely on IWR's stream/DNS timeout.
function Stop-BoundedHealthProbeTree {
    param($Process)
    try {
        return $Process.Stop(300)
    } catch { return $false }
}

function Invoke-BoundedHealthProbe {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [ValidateRange(0.1, 30)][double]$TimeoutSeconds = 5,
        [string]$PythonPath = 'C:\bitman_marketfloww\.venv\Scripts\python.exe',
        [string]$ProbeScript = (Join-Path $PSScriptRoot 'health_probe.py')
    )
    $clock = [System.Diagnostics.Stopwatch]::StartNew()
    $result = [ordered]@{ healthy = $false; reason = 'probe_unavailable'; status = $null; elapsed_ms = 0; child_pid = 0 }
    $process = $null
    try {
        if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf) -or
            -not (Test-Path -LiteralPath $ProbeScript -PathType Leaf)) { return [pscustomobject]$result }
        if (-not ('MarketFlowOwnedHealthProbe' -as [type])) {
            Add-Type -Path (Join-Path $PSScriptRoot 'health_probe_native.cs') -ErrorAction Stop
        }
        $timeoutText = $TimeoutSeconds.ToString('0.###', [System.Globalization.CultureInfo]::InvariantCulture)
        $arguments = @($ProbeScript, '--url', $Uri, '--timeout', $timeoutText)
        # Native CreateProcess invokes Python directly, initially suspended so
        # the forwarding launcher cannot create any child outside our own job.
        if (@($arguments | Where-Object { $_ -match '["\r\n]' }).Count -gt 0) { return [pscustomobject]$result }
        $argumentText = ($arguments | ForEach-Object { '"' + $_ + '"' }) -join ' '
        $process = [MarketFlowOwnedHealthProbe]::Start([IO.Path]::GetFullPath($PythonPath), $argumentText)
        $result.child_pid = $process.Id
        $stdout = $process.Output
        $remainingMs = [Math]::Max(1, [int]($TimeoutSeconds * 1000 - $clock.ElapsedMilliseconds))
        if (-not $process.WaitForExit($remainingMs)) {
            $result.reason = 'deadline_exceeded'
        } elseif ($process.ExitCode -eq 124) {
            $result.reason = 'deadline_exceeded'
        } elseif ($stdout.Wait(200)) {
            $body = $stdout.Result | ConvertFrom-Json -ErrorAction Stop
            if ($body.reason -in @('healthy', 'http_status', 'response_too_large', 'tls_error', 'deadline_exceeded', 'transport_error', 'invalid_url')) {
                $result.reason = [string]$body.reason
                $result.status = $body.status
                $result.healthy = ($process.ExitCode -eq 0 -and $body.healthy -eq $true -and $body.status -eq 200)
            }
        }
    } catch {
        # Do not copy arbitrary stderr, exception messages, URL, or response data.
        $result.healthy = $false
    } finally {
        if ($process) {
            try {
                # Always close the owned tree, even when its immediate parent
                # already exited while a forwarding worker remains alive.
                if (-not (Stop-BoundedHealthProbeTree -Process $process)) {
                    $result.healthy = $false
                    $result.reason = 'cleanup_failed'
                }
            } catch { }
            $process.Dispose()
        }
        $result.elapsed_ms = $clock.ElapsedMilliseconds
    }
    return [pscustomobject]$result
}

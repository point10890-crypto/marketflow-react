# Windows PowerShell 5.1 supervisor. Never rely on IWR's stream/DNS timeout.
function Stop-BoundedHealthProbeTree {
    param([System.Diagnostics.Process]$Process)
    $killer = $null
    try {
        $start = [System.Diagnostics.ProcessStartInfo]::new()
        $start.FileName = Join-Path ([Environment]::GetFolderPath('System')) 'taskkill.exe'
        $start.Arguments = "/PID $($Process.Id) /T /F"
        $start.UseShellExecute = $false
        $start.CreateNoWindow = $true
        $start.RedirectStandardOutput = $true
        $start.RedirectStandardError = $true
        $killer = [System.Diagnostics.Process]::new()
        $killer.StartInfo = $start
        if (-not $killer.Start()) { return $false }
        $out = $killer.StandardOutput.ReadToEndAsync()
        $err = $killer.StandardError.ReadToEndAsync()
        if (-not $killer.WaitForExit(1000)) {
            $killer.Kill()
            [void]$killer.WaitForExit(200)
            return $false
        }
        return $Process.WaitForExit(300)
    } catch { return $false } finally {
        if ($killer) { $killer.Dispose() }
    }
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
        $timeoutText = $TimeoutSeconds.ToString('0.###', [System.Globalization.CultureInfo]::InvariantCulture)
        $arguments = @($ProbeScript, '--url', $Uri, '--timeout', $timeoutText)
        # ProcessStartInfo invokes Python directly (no cmd/PowerShell evaluation).
        if (@($arguments | Where-Object { $_ -match '["\r\n]' }).Count -gt 0) { return [pscustomobject]$result }
        $start = [System.Diagnostics.ProcessStartInfo]::new()
        $start.FileName = $PythonPath
        $start.Arguments = ($arguments | ForEach-Object { '"' + $_ + '"' }) -join ' '
        $start.UseShellExecute = $false
        $start.CreateNoWindow = $true
        $start.RedirectStandardOutput = $true
        $start.RedirectStandardError = $true
        $process = [System.Diagnostics.Process]::new()
        $process.StartInfo = $start
        if (-not $process.Start()) { return [pscustomobject]$result }
        $result.child_pid = $process.Id
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
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
                # venv python.exe can forward to a base-Python child. Kill the
                # exact created tree, including an import-time stalled worker.
                if (-not $process.HasExited -and -not (Stop-BoundedHealthProbeTree -Process $process)) {
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

param(
    [string]$GoodrichRoot = 'C:\GoodrichTradingOS',
    [string]$PythonPath = '',
    [switch]$SkipServiceRestart
)

$ErrorActionPreference = 'Stop'

$marketFlowRoot = Split-Path -Parent $PSScriptRoot
$overlayRoot = Join-Path $PSScriptRoot 'goodrich_tradingos_overlay'
$goodrichRoot = $GoodrichRoot
$apiRoot = Join-Path $goodrichRoot 'services\api'
$sourceRoot = Join-Path $apiRoot 'src\goodrich'
$testsRoot = Join-Path $apiRoot 'tests'
$python = if ($PythonPath) {
    $PythonPath
} else {
    Join-Path $goodrichRoot '.venv\Scripts\python.exe'
}
$taskName = 'Goodrich-TradingOS'
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$backupRoot = Join-Path $goodrichRoot ("backups\marketflow-deepseek-overlay-$timestamp")
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$manifestPath = Join-Path $overlayRoot 'manifest.json'

$required = @(
    $python,
    $manifestPath,
    (Join-Path $overlayRoot 'openai_research.py'),
    (Join-Path $overlayRoot 'test_marketflow_contract.py'),
    (Join-Path $overlayRoot 'test_fund_manager.py'),
    (Join-Path $sourceRoot 'openai_research.py'),
    (Join-Path $sourceRoot 'fund_manager.py'),
    (Join-Path $sourceRoot 'main.py')
)
foreach ($path in $required) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Required Goodrich overlay file is missing: $path"
    }
}

$sdkProbe = @'
from inspect import signature
from openai import OpenAI
client = OpenAI(api_key='compatibility-check')
create = getattr(getattr(client, 'responses', None), 'create', None)
parameters = set(signature(create).parameters) if callable(create) else set()
required = {'text', 'reasoning', 'max_output_tokens', 'store'}
raise SystemExit(0 if required.issubset(parameters) else 1)
'@
$global:LASTEXITCODE = $null
& $python -c $sdkProbe
$sdkProbeSucceeded = $?
$sdkProbeExitCode = $LASTEXITCODE
if (
    -not $sdkProbeSucceeded -or
    $null -eq $sdkProbeExitCode -or
    [int]$sdkProbeExitCode -ne 0
) {
    throw 'Goodrich OpenAI SDK Responses API support is required.'
}

$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$preApplyRecords = @()
$goodrichRootPrefix = [IO.Path]::GetFullPath($goodrichRoot).TrimEnd('\') + '\'
$seenTargets = [Collections.Generic.HashSet[string]]::new(
    [StringComparer]::OrdinalIgnoreCase
)
$seenBackupLeaves = [Collections.Generic.HashSet[string]]::new(
    [StringComparer]::OrdinalIgnoreCase
)
foreach ($entry in $manifest.files) {
    $relative = ([string]$entry.target).Replace('/', '\')
    $target = [IO.Path]::GetFullPath((Join-Path $goodrichRoot $relative))
    if (-not $target.StartsWith($goodrichRootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Goodrich manifest target escapes GoodrichRoot: $relative"
    }
    if (-not $seenTargets.Add($target)) {
        throw "Goodrich manifest target is duplicated: $relative"
    }
    $exists = Test-Path -LiteralPath $target
    if (-not $exists -and -not $entry.optional_before_apply) {
        throw "Goodrich manifest target is missing: $target"
    }
    $hash = if ($exists) {
        (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
    } else {
        $null
    }
    if ($exists -and @($entry.accepted_sha256) -notcontains $hash) {
        throw "Goodrich manifest hash mismatch: $relative"
    }
    if ($exists -and -not $seenBackupLeaves.Add((Split-Path $target -Leaf))) {
        throw "Goodrich backup filename is duplicated: $relative"
    }
    $preApplyRecords += [pscustomobject]@{
        target = [string]$entry.target
        existed = $exists
        sha256 = $hash
    }
}

$overlayInputs = @{
    'services/api/src/goodrich/openai_research.py' = Join-Path $overlayRoot 'openai_research.py'
    'services/api/tests/test_fund_manager.py' = Join-Path $overlayRoot 'test_fund_manager.py'
    'services/api/tests/test_marketflow_contract.py' = Join-Path $overlayRoot 'test_marketflow_contract.py'
}
foreach ($relative in $overlayInputs.Keys) {
    $entry = @($manifest.files | Where-Object { $_.target -eq $relative })
    if ($entry.Count -ne 1) {
        throw "Goodrich overlay manifest entry is missing or duplicated: $relative"
    }
    $actual = (Get-FileHash -LiteralPath $overlayInputs[$relative] -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne ([string]$entry[0].patched_sha256).ToLowerInvariant()) {
        throw "Goodrich overlay input hash mismatch: $relative"
    }
}

function Read-NormalizedText([string]$Path) {
    return [IO.File]::ReadAllText($Path).Replace("`r`n", "`n")
}

function Write-NormalizedText([string]$Path, [string]$Content) {
    [IO.File]::WriteAllText($Path, $Content.Replace("`r`n", "`n"), $utf8NoBom)
}

function Replace-ExactBlock(
    [string]$Path,
    [string]$OldBlock,
    [string]$NewBlock,
    [int]$ExpectedCount = 1
) {
    $text = Read-NormalizedText $Path
    $old = $OldBlock.Replace("`r`n", "`n")
    $new = $NewBlock.Replace("`r`n", "`n")
    $count = [regex]::Matches($text, [regex]::Escape($old)).Count
    if ($count -eq 0 -and $text.Contains($new)) {
        return
    }
    if ($count -ne $ExpectedCount) {
        throw "Goodrich source contract drifted for $Path (match_count=$count)."
    }
    Write-NormalizedText $Path ($text.Replace($old, $new))
}

function Replace-RegexBlock(
    [string]$Path,
    [string]$Pattern,
    [string]$NewBlock
) {
    $text = Read-NormalizedText $Path
    $matches = [regex]::Matches(
        $text,
        $Pattern,
        [Text.RegularExpressions.RegexOptions]::Singleline
    )
    if ($matches.Count -ne 1) {
        throw "Goodrich source contract drifted for $Path (regex_match_count=$($matches.Count))."
    }
    $new = $NewBlock.Replace("`r`n", "`n")
    if (-not $new.EndsWith("`n")) {
        $new += "`n"
    }
    Write-NormalizedText $Path ([regex]::Replace(
        $text,
        $Pattern,
        [Text.RegularExpressions.MatchEvaluator]{ param($match) $new },
        [Text.RegularExpressions.RegexOptions]::Singleline
    ))
}

function Get-GoodrichListenerPids {
    return @(
        Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 8000 `
            -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique
    )
}

function Stop-GoodrichTaskAndWait {
    $previousPids = @(Get-GoodrichListenerPids)
    $previousStartTicks = @{}
    foreach ($processId in $previousPids) {
        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($process) {
            $previousStartTicks[[string]$processId] = $process.StartTime.ToUniversalTime().Ticks
        }
    }
    Stop-ScheduledTask -TaskName $taskName -ErrorAction Stop | Out-Null
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
        if ($task.State -ne 'Running') {
            break
        }
        Start-Sleep -Milliseconds 500
    }
    foreach ($processId in $previousPids) {
        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
        $expectedTicks = $previousStartTicks[[string]$processId]
        if (
            $process -and
            $expectedTicks -and
            $process.StartTime.ToUniversalTime().Ticks -eq $expectedTicks
        ) {
            & taskkill.exe /PID $processId /T /F | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw "Could not terminate the previous Goodrich process tree: $processId"
            }
        }
    }
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
        if ($task.State -ne 'Running' -and @(Get-GoodrichListenerPids).Count -eq 0) {
            return $previousPids
        }
        Start-Sleep -Milliseconds 500
    }
    throw 'Goodrich TradingOS task or port 8000 did not stop cleanly.'
}

function Start-GoodrichTaskAndVerify([int[]]$PreviousPids) {
    $startedAfter = Get-Date
    Start-ScheduledTask -TaskName $taskName -ErrorAction Stop
    for ($attempt = 0; $attempt -lt 90; $attempt++) {
        Start-Sleep -Milliseconds 500
        try {
            $response = Invoke-RestMethod -TimeoutSec 3 `
                -Uri 'http://127.0.0.1:8000/health'
            $listenerPids = @(Get-GoodrichListenerPids)
            $freshPids = @(
                $listenerPids | Where-Object {
                    $processId = $_
                    if ($PreviousPids -contains $processId) {
                        return $false
                    }
                    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
                    return $process -and $process.StartTime -ge $startedAfter.AddSeconds(-2)
                }
            )
            $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
            $taskInfo = Get-ScheduledTaskInfo -TaskName $taskName -ErrorAction Stop
            $confirmedPids = @(Get-GoodrichListenerPids)
            if (
                $response.status -eq 'ok' -and
                $response.environment -eq 'production' -and
                $task.State -eq 'Running' -and
                $taskInfo.LastRunTime -ge $startedAfter.AddSeconds(-2) -and
                $freshPids.Count -gt 0 -and
                @($confirmedPids | Where-Object { $freshPids -contains $_ }).Count -gt 0
            ) {
                return
            }
        } catch {
            # Continue bounded readiness polling.
        }
    }
    [void](Stop-GoodrichTaskAndWait)
    throw 'Goodrich TradingOS did not start as a fresh healthy production process.'
}

function Assert-GoodrichCurrentHealth {
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        try {
            $response = Invoke-RestMethod -TimeoutSec 3 `
                -Uri 'http://127.0.0.1:8000/health'
            if (
                $response.status -eq 'ok' -and
                $response.environment -eq 'production' -and
                @(Get-GoodrichListenerPids).Count -gt 0
            ) {
                return
            }
        } catch {
            # Continue bounded recovery polling.
        }
        Start-Sleep -Milliseconds 500
    }
    throw 'Goodrich TradingOS recovery health verification failed.'
}

$contractTest = Join-Path $testsRoot 'test_marketflow_contract.py'
$fundManagerTest = Join-Path $testsRoot 'test_fund_manager.py'

New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
foreach ($record in $preApplyRecords) {
    if ($record.existed -ne $true) {
        continue
    }
    $relative = ([string]$record.target).Replace('/', '\')
    $target = [IO.Path]::GetFullPath((Join-Path $goodrichRoot $relative))
    $backupFile = Join-Path $backupRoot (Split-Path $target -Leaf)
    Copy-Item -LiteralPath $target -Destination $backupFile -Force
    $actual = (Get-FileHash -LiteralPath $backupFile -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne ([string]$record.sha256).ToLowerInvariant()) {
        throw "Goodrich backup hash mismatch: $relative"
    }
}
$backupManifestPath = Join-Path $backupRoot 'backup-manifest.json'
$backupManifestTemp = "$backupManifestPath.tmp"
$backupManifestJson = $preApplyRecords | ConvertTo-Json -Depth 4
[IO.File]::WriteAllText($backupManifestTemp, $backupManifestJson, $utf8NoBom)
Move-Item -LiteralPath $backupManifestTemp -Destination $backupManifestPath -Force

$applied = $false
$runtimeChangeAttempted = $false
try {
    Copy-Item -LiteralPath (Join-Path $overlayRoot 'openai_research.py') `
        -Destination (Join-Path $sourceRoot 'openai_research.py') -Force
    Copy-Item -LiteralPath (Join-Path $overlayRoot 'test_marketflow_contract.py') `
        -Destination $contractTest -Force
    Copy-Item -LiteralPath (Join-Path $overlayRoot 'test_fund_manager.py') `
        -Destination $fundManagerTest -Force

    $fundManager = Join-Path $sourceRoot 'fund_manager.py'
    if (-not (Read-NormalizedText $fundManager).Contains(
        'ranked_candidates: list[dict] | None = None'
    )) {
    Replace-RegexBlock $fundManager '(?m)^def run_research_cycle\(\n    db: Session,\n    kis: KISClient,\n    researcher: OpenAIResearchAgent,\n    detected_universe: dict\[str, str\] \| None = None,\n\) -> list\[AgentPick\]:\n    # A fixed research universe[^\n]*\n    # MarketFlow must supply candidates[^\n]*\n    universe = detected_universe or \{\}\n    if len\(universe\) < 3:\n        raise ValueError\([^\n]*\)\n' @'
def run_research_cycle(
    db: Session,
    kis: KISClient,
    researcher: OpenAIResearchAgent,
    detected_universe: dict[str, str] | None = None,
    ranked_candidates: list[dict] | None = None,
) -> list[AgentPick]:
    # MarketFlow supplies candidates detected from the live KIS market scan.
    universe = detected_universe or {}
    if len(universe) < 1:
        raise ValueError("No verified research candidate was supplied.")
    ranking_by_symbol = {
        str(item.get("symbol") or ""): item
        for item in (ranked_candidates or [])
        if isinstance(item, dict)
    }
'@
    Replace-ExactBlock $fundManager @'
        quote = kis.current_price(symbol)
        researched.append(({**quote, "name": name}, _score(quote)))
'@ @'
        quote = kis.current_price(symbol)
        upstream_score = float(ranking_by_symbol[symbol]["score"])
        researched.append(({**quote, "name": name}, upstream_score))
'@
    Replace-ExactBlock $fundManager @'
    researched.sort(key=lambda row: row[1], reverse=True)

'@ ''
    Replace-ExactBlock $fundManager @'
        if verdict == "REJECT":
            continue
        verdict_adjustment = 2.0 if verdict == "BUY_CANDIDATE" else 0.0
'@ @'
        verdict_adjustment = {
            "BUY_CANDIDATE": 2.0,
            "WATCH": 0.0,
            "REJECT": -2.0,
        }.get(verdict, 0.0)
'@
    Replace-ExactBlock $fundManager @'
        conviction_adjustment = (conviction - 50) * 0.1
        final_score = round(
            rule_score + verdict_adjustment + conviction_adjustment,
            2,
        )
'@ @'
        conviction_adjustment = (conviction - 50) * 0.1
        final_score = (
            rule_score
            if ranked_candidates
            else round(rule_score + verdict_adjustment + conviction_adjustment, 2)
        )
'@
    Replace-RegexBlock $fundManager '(?m)^    agent_ranked.sort\(key=lambda row: row\[1\], reverse=True\)\n    top3 = agent_ranked\[:3\]\n    if len\(top3\) < 3:\n        raise ValueError\([^\n]*\)\n' @'
    top3 = agent_ranked[:3]
    if len(top3) != len(shortlist):
        raise ValueError("The verified candidate set was not preserved.")
'@
    Replace-ExactBlock $fundManager @'
        AgentResearchRun(
            cycle_id=cycle_id,
            model=ai_result["model"],
'@ @'
        AgentResearchRun(
            cycle_id=cycle_id,
            provider=(
                ai_result.get("storage_provider")
                or ai_result.get("provider")
                or "openai"
            ),
            model=ai_result["model"],
'@
    Replace-ExactBlock $fundManager @'
                "provider": run.provider,
'@ @'
                "provider": (
                    "openai"
                    if run.provider == "openai_fallback_from_deepseek"
                    else run.provider
                ),
                "fallback_from": (
                    "deepseek"
                    if run.provider == "openai_fallback_from_deepseek"
                    else None
                ),
'@
    }

    $main = Join-Path $sourceRoot 'main.py'
    if (-not (Read-NormalizedText $main).Contains(
        'ranked_candidates=ranked_candidates'
    )) {
    Replace-ExactBlock $main @'
import json
from contextlib import asynccontextmanager
'@ @'
import json
import math
import os
from contextlib import asynccontextmanager
'@
    Replace-ExactBlock $main @'
from goodrich.openai_research import (
    OpenAIConfigurationError,
    OpenAIResearchAgent,
    OpenAIResearchError,
)
'@ @'
from goodrich.openai_research import (
    DeepSeekFirstResearchAgent,
    OpenAIConfigurationError,
    OpenAIResearchError,
    ResearchPipelineError,
)
'@
    Replace-ExactBlock $main @'
openai_researcher = OpenAIResearchAgent(
    credentials_file=settings.openai_credentials_file,
    model=settings.openai_model,
)
'@ @'
openai_researcher = DeepSeekFirstResearchAgent(
    deepseek_api_key=os.getenv("GOODRICH_DEEPSEEK_API_KEY", ""),
    deepseek_model=os.getenv("GOODRICH_DEEPSEEK_MODEL", "deepseek-v4-pro"),
    deepseek_base_url=os.getenv(
        "GOODRICH_DEEPSEEK_BASE_URL", "https://api.deepseek.com"
    ),
    openai_credentials_file=settings.openai_credentials_file,
    openai_model=settings.openai_model,
)
'@
    Replace-ExactBlock $main @'
    alerts = db.scalars(
        select(AgentAlert).order_by(AgentAlert.created_at.desc()).limit(10)
    ).all()
    return {
'@ @'
    alerts = db.scalars(
        select(AgentAlert).order_by(AgentAlert.created_at.desc()).limit(10)
    ).all()
    stored_provider = research.provider if research else "deepseek"
    used_openai_fallback = stored_provider == "openai_fallback_from_deepseek"
    return {
'@
    Replace-ExactBlock $main @'
        "ai": {
            "provider": research.provider if research else "openai",
            "model": research.model if research else settings.openai_model,
            "status": research.status if research else "pending",
            "market_summary": research.market_summary if research else "",
        },
'@ @'
        "ai": {
            "provider": "openai" if used_openai_fallback else stored_provider,
            "fallback_from": "deepseek" if used_openai_fallback else None,
            "model": (
                research.model
                if research
                else os.getenv("GOODRICH_DEEPSEEK_MODEL", "deepseek-v4-pro")
            ),
            "status": research.status if research else "pending",
            "market_summary": research.market_summary if research else "",
        },
'@
    Replace-RegexBlock $main '(?m)^    detected_universe = None\n    if payload and isinstance\(payload.get\("candidates"\), list\):\n        detected_universe = \{\}\n        for candidate in payload\["candidates"\]\[:20\]:\n            if not isinstance\(candidate, dict\):\n                continue\n            symbol = str\(candidate.get\("symbol"\) or ""\).strip\(\)\n            name = str\(candidate.get\("name"\) or ""\).strip\(\)\n            if len\(symbol\) == 6 and symbol.isdigit\(\) and name:\n                detected_universe\[symbol\] = name\n        if len\(detected_universe\) < 3:\n            raise HTTPException\(422, [^\n]*\)\n' @'
    if not payload or not isinstance(payload.get("candidates"), list):
        raise HTTPException(422, "Verified candidates and ranks are required.")
    candidates = payload["candidates"]
    ranked_input = payload.get("ranked_candidates")
    if not 1 <= len(candidates) <= 3 or not isinstance(ranked_input, list):
        raise HTTPException(422, "One to three ranked candidates are required.")

    candidate_by_symbol = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise HTTPException(422, "Candidate format is invalid.")
        symbol = str(candidate.get("symbol") or "").strip()
        name = str(candidate.get("name") or "").strip()
        if (
            len(symbol) != 6
            or not symbol.isdigit()
            or not name
            or symbol in candidate_by_symbol
        ):
            raise HTTPException(422, "Candidate identity is invalid.")
        candidate_by_symbol[symbol] = name

    ranked_candidates = []
    for item in ranked_input:
        if not isinstance(item, dict):
            raise HTTPException(422, "Ranked candidate format is invalid.")
        symbol = str(item.get("symbol") or "").strip()
        name = str(item.get("name") or "").strip()
        rank = item.get("rank")
        raw_score = item.get("score")
        if not isinstance(rank, int) or isinstance(rank, bool):
            raise HTTPException(422, "Rank must be an integer.")
        if (
            not isinstance(raw_score, (int, float))
            or isinstance(raw_score, bool)
        ):
            raise HTTPException(422, "Ranked candidate score must be numeric.")
        score = float(raw_score)
        if not math.isfinite(score) or not 0 <= score <= 100:
            raise HTTPException(422, "Ranked candidate score must be finite and 0..100.")
        if candidate_by_symbol.get(symbol) != name:
            raise HTTPException(422, "Candidate names and ranks do not match.")
        ranked_candidates.append(
            {**item, "symbol": symbol, "name": name, "rank": rank, "score": score}
        )

    ranked_symbols = [item["symbol"] for item in ranked_candidates]
    expected_ranks = list(range(1, len(candidates) + 1))
    if (
        len(ranked_candidates) != len(candidates)
        or [item["rank"] for item in ranked_candidates] != expected_ranks
        or len(set(ranked_symbols)) != len(ranked_symbols)
        or set(ranked_symbols) != set(candidate_by_symbol)
    ):
        raise HTTPException(422, "Candidates and ranks do not match.")
    detected_universe = {
        symbol: candidate_by_symbol[symbol] for symbol in ranked_symbols
    }
'@
    Replace-ExactBlock $main @'
            openai_researcher,
            detected_universe=detected_universe,
        )
'@ @'
            openai_researcher,
            detected_universe=detected_universe,
            ranked_candidates=ranked_candidates,
        )
'@
    Replace-ExactBlock $main @'
        OpenAIResearchError,
    ) as error:
'@ @'
        OpenAIResearchError,
        ResearchPipelineError,
    ) as error:
'@ 2
    }

    foreach ($entry in $manifest.files) {
        $relative = ([string]$entry.target).Replace('/', '\')
        $target = Join-Path $goodrichRoot $relative
        $actual = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne ([string]$entry.patched_sha256).ToLowerInvariant()) {
            throw "Goodrich patched hash mismatch: $relative (actual=$actual)"
        }
    }

    Set-Location -LiteralPath $apiRoot
    $env:PYTHONPATH = if ($env:PYTHONPATH) {
        (Join-Path $apiRoot 'src') + [IO.Path]::PathSeparator + $env:PYTHONPATH
    } else {
        Join-Path $apiRoot 'src'
    }
    & $python -m pytest tests -q
    if ($LASTEXITCODE -ne 0) {
        throw "Goodrich API tests failed (exit=$LASTEXITCODE)."
    }

    if (-not $SkipServiceRestart) {
        $runtimeChangeAttempted = $true
        $previousPids = @(Stop-GoodrichTaskAndWait)
        Start-GoodrichTaskAndVerify -PreviousPids $previousPids
    }
    $applied = $true
} finally {
    if (-not $applied) {
        foreach ($record in $preApplyRecords) {
            $relative = ([string]$record.target).Replace('/', '\')
            $target = [IO.Path]::GetFullPath((Join-Path $goodrichRoot $relative))
            if ($record.existed -eq $true) {
                $backup = Join-Path $backupRoot (Split-Path $target -Leaf)
                Copy-Item -LiteralPath $backup -Destination $target -Force
            } elseif (Test-Path -LiteralPath $target) {
                Remove-Item -LiteralPath $target -Force
            }
        }
        foreach ($record in $preApplyRecords) {
            $relative = ([string]$record.target).Replace('/', '\')
            $target = [IO.Path]::GetFullPath((Join-Path $goodrichRoot $relative))
            if ($record.existed -eq $true) {
                $actual = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
                if ($actual -ne ([string]$record.sha256).ToLowerInvariant()) {
                    throw "Goodrich automatic rollback hash mismatch: $relative"
                }
            } elseif (Test-Path -LiteralPath $target) {
                throw "Goodrich automatic rollback could not remove: $relative"
            }
        }
        if (-not $SkipServiceRestart) {
            if ($runtimeChangeAttempted) {
                $rollbackPreviousPids = @(Stop-GoodrichTaskAndWait)
                Start-GoodrichTaskAndVerify -PreviousPids $rollbackPreviousPids
            } else {
                Assert-GoodrichCurrentHealth
            }
        }
    }
}

Write-Output "Goodrich DeepSeek-first overlay applied; backup=$backupRoot"

# Scheduler storage recovery

## Incident: 2026-10-08

The MiniPC C: volume reported zero free bytes. MiroFish scanner persistence
raised `OSError: [Errno 28] No space left on device`; Kiwoom theme updates and
scheduler state writes also failed. The three reported jobs recovered after
space was released. A success timestamp alone does not establish a new analysis:
check the saved source/result timestamp and the job's returned status as well.

At investigation there were 368,741 scanner-run directories. Automatic polling
creates durable scanner snapshots before deciding whether new events exist.
Completed evidence and historical decisions must remain available; do not delete
the archive or reset event/outcome state to recover storage.

## Storage boundary

`app/utils/storage_guard.py` checks free space on the actual output volumes.
The default reserve is 1 GiB. `MARKETFLOW_SCHEDULER_MIN_FREE_BYTES`, if configured,
must be a positive integer. An invalid setting or unavailable volume check blocks
collection rather than pretending the storage is healthy.

Scheduled wrappers check before collection and retry, including after retry
sleep. Disk-full OS/SQLite errors stop collection retries. Prior success records
remain unchanged and this storage path sends no extra notification. Other errors
retain the existing retry policy. Direct scanner creation performs the same
preflight before collection or directory creation.

Scanner evidence artifacts are saved atomically before `run.json` publishes the
completed header. Latest-run cache invalidation follows that final publication.
A mid-write failure does not replace the previous completed report with a partial
completed result. Failed unpublished directories are retained for diagnosis.

## Lossless archive maintenance

`scripts/compact_scanner_archives.py` defaults to a read-only inventory:

```powershell
.\.venv\Scripts\python.exe scripts\compact_scanner_archives.py `
  --root C:\bitman_marketfloww --before 2026-10-01 --target-free-gib 20
```

Add `--apply` to use Windows `compact /C /F /EXE:LZX` on eligible completed JSONs.
The cutoff must be at least seven calendar days old. `--after` optionally limits
the lower date boundary. The most recent eligible cold runs are considered first;
the newest run, recently modified files, incomplete runs, temporary writes, links,
redirects and files outside the scanner archive are excluded. Each invocation
is bounded to at most 10,000 runs. JSON paths and bytes remain unchanged. Every
batch verifies SHA-256 and file size before and after compression.

The helper stops at the requested free-space target and saves an atomic summary
under `data/operations/scanner_archive_compaction/`. Integrity or command errors
abort the invocation. Inspect the summary's `status`, `verified_files`,
`reclaimed_bytes`, and `free_bytes_after`; an exhausted bounded inventory can
finish below the requested target. Do not interpret that as recovered capacity.

The Windows `MarketFlow-Scanner-Archive-Maintenance` task runs the fixed
`scripts/maintain_scanner_archives.ps1` launcher daily at 03:10 KST with
IgnoreNew. It computes a seven-day cutoff, requests a 20 GiB reserve, validates
the helper's final manifest and propagates failure. It does not collect market
data, call APIs, change analysis rules, send messages, or remove history. Inspect
`logs/scanner_archive_maintenance.log` and the saved manifests if the task fails.
Only install this task on the production MiniPC; no account credentials are
embedded in its source or arguments.

The compression format and flags are documented by
[Microsoft](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/compact).

## Recovery verification

1. Check volume free bytes and the compression integrity summary.
2. Verify both `/healthz` and `/api/health` on Flask production port 5003 and the
   deployed API. Development port 5001 is a separate process.
3. Verify the scheduler PID and a fresh matching heartbeat after deploying.
4. Observe the next ordinary scheduled updates: Omni news fetch/keep/save counts
   and provider errors, Kiwoom's saved `updated_at` and completed condition count,
   and MiroFish's monitor result. An idle/no-new-event monitor is a valid success,
   not evidence that a new trading proposal was created.
5. Confirm no new disk-full storage errors after recovery. Do not manually replay
   notification-producing jobs merely to obtain a green timestamp.

Passive snapshot caching was evaluated and excluded from this incident release:
RS changes, CSV availability cutoffs and provider TTL boundaries can change
scores without equivalent file metadata. Production semantic ranking also
requires its normal evaluation. Space recovery must not relax freshness,
look-ahead, learning, CIO approval or live-order contracts.

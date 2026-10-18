# API availability and bounded recovery

## Incident and verified failure mechanisms

On 2026-10-18, the frontend responded while both public and MiniPC loopback API
health requests timed out. The same Flask process subsequently recovered without
a manual restart. This establishes an origin/API delay, not a frontend-only or
tunnel-only failure. No contemporaneous thread trace exists for that pause;
its original trigger is not proven.

Two independent mechanisms were reproduced before changing code:

1. Werkzeug logs a request before sending response headers. A blocked synchronous
   log stream consequently blocks otherwise trivial health requests. An isolated
   real HTTP server test reproduces this and checks that the nonblocking bounded
   logging queue still returns HTTP 200 while its sink is stopped.
2. Windows PowerShell 5.1 `Invoke-WebRequest -TimeoutSec` does not impose a reliable
   whole-response deadline when the body stalls. The old watchdog also checked
   the legacy producer before the primary API. A blocked probe or slow legacy
   recovery could defer primary recovery and cause `IgnoreNew` to skip later runs.

These reproductions justify the repair; they are not proof that one specific
historical request or news/provider caused the original pause. Scanner enumeration
has measurable CPU cost, but the isolated experiment did not reproduce the
observed 12-second health timeout. Do not optimize trading rules against this
operational incident or change stored research decisions.

## Runtime isolation

Only the `flask_app.py` entrypoint activates API logging isolation. It preserves
logger routing and uses a bounded in-memory queue with a daemon output worker.
Requests never fall back to synchronous stderr when the queue fills. The tradeoff
is deliberate: queued records can be dropped during output blockage or process
exit. Counters expose that loss without logging through the blocked sink.

Slow-request diagnostics are local, bounded artifacts under `data/api_runtime/`.
They contain route patterns, elapsed time and code locations, not URL queries,
headers, request/response bodies, locals or credentials. They are not a public API
and must not be committed. File failures do not block requests or emit recursive
logging. Use these artifacts together with OS resource observations if the
origin becomes slow again; a healthy trace after recovery does not establish
the cause of the earlier stall.

The observer covers Flask request hooks through response/teardown, not later
WSGI response transmission or Werkzeug's pre-header logging. The queue protects
that logging path separately. Startup output and arbitrary `print()` calls are
outside the stdlib logging queue; readiness and external recovery remain needed.

## Supervisor contract

- Production API: `MarketFlow-Flask`, `127.0.0.1:5003`.
- Primary recovery: `MarketFlow-Flask-Watchdog`, primary mode only.
- Legacy KIS producer recovery: independent watchdog task on 5001; it must not
  delay the primary task. The development machine also uses 5001; production
  watchdogs are MiniPC-only.
- Tunnel recovery: `MarketFlow-Tunnel-Watchdog`; recover the canonical
  `Cloudflared` service only when the origin is healthy and the public path fails.
- All health probes use `scripts/health_probe.ps1` and its disposable Python
  worker. An outer process deadline covers headers, stalled bodies and trickles.
  HTTP redirects and certificate failures are failures, not readiness.
- A foreign port owner must prevent destructive recovery. Never terminate a
  process by executable name, reboot the host, modify another tunnel's ingress,
  or use port 8080 for MarketFlow.

The five-minute schedule bounds detection cadence; it does not mean every
outage resolves in five minutes. Startup grace, probe duration, startup failures
and external OS or storage failure can extend recovery. Task execution limits
are an additional backstop, not a substitute for bounded individual probes.
All three recovery tasks have a four-minute execution limit and `StopExisting`
on overlap. Installation updates existing actions/settings without unregistering
their principal or triggers. The separate legacy task is created only if absent.
Windows PowerShell's public settings enum omits `StopExisting`. The installer
sets the native CIM `MultipleInstances` property to `uint32` value 3 instead;
the Windows regression checks verify the exported task XML before registration.

Windows can terminate the venv forwarding parent before its base-Python child.
Recovery therefore preserves the ownership proof established before stopping
the task, bound to the project and exact process incarnation. It rechecks that
identity and current 5001 protection immediately before termination; a vanished
parent does not invalidate an otherwise unchanged, previously verified child.
Changed identities and unverified or tampered proofs still refuse termination.
Recovery logs contain fixed stage names and allowlisted failure reasons only,
so a failed handoff can be diagnosed without copying raw provider exceptions.

A production forced restart also exposed an identity-check refusal after task
shutdown and before relaunch. The exact changed field was not captured; an
isolated native Task Scheduler probe did not reproduce the mismatch. Recovery
must therefore handle an expired cleanup target without assuming its cause.
The termination guard accepts incomplete metadata only when independent process
inspection confirms exit, and then performs no kill. The primary supervisor may
also skip a refused cleanup target after its own task stop, but only for the
known identity/provenance refusals and only after a successful authoritative
query proves port 5003 has no listener. It logs the skipped PID, preserves any
changed PID reference, and lets the launcher perform fresh ownership checks.
Occupied ports, inspection failures, protected owners and other failures still
prevent relaunch. This separates safe cleanup refusal from service restoration.

On the elevated MiniPC shell, apply the recovery task definitions with:

```powershell
& C:\bitman_marketfloww\scripts\install_flask_watchdog.ps1
. C:\bitman_marketfloww\scripts\health_probe.ps1
Invoke-BoundedHealthProbe -Uri http://127.0.0.1:5003/healthz -TimeoutSeconds 5
```

## Deployment and verification

Deploy an exact tested commit with a fast-forward pull on the MiniPC. Preserve
untracked data, secrets, subscription records and scheduled research. Update only
the named recovery tasks, preserving their operating principals. Restart the API
through its launcher/watchdog contract, then verify:

1. The actual listener PID starts after deployment and binds only 127.0.0.1:5003.
2. Loopback and public `/healthz`, `/api/health` and the public community board API
   return 200 with measured durations.
3. The logged-in community page loads its board cards without an API timeout.
4. A controlled termination of only the verified API process is detected and
   recovered by the primary watchdog. Record old/new PIDs and elapsed time.
5. An isolated stalled/trickling fixture cannot leave probe workers running or
   delay unrelated primary recovery. Do not deliberately stall the live API.

Keep sanitized deployment evidence in ignored `data/reviews/`. Never copy raw
logs into reports: provider exceptions may contain Telegram bot credentials.
The existing muted decision-guard notification policy remains unchanged.

## Windows regression checks

The existing GitHub workflow runs the full Python suite on Linux and frontend
lint/tests/build. The push credential does not have GitHub's `workflow` scope,
so the proposed Windows CI job was preserved separately instead of expanding
account permissions. Run the Windows-specific checks explicitly on Windows:

```powershell
python -m pytest --noconftest -o addopts='' tests/test_api_logging.py tests/test_api_request_diagnostics.py tests/test_watchdog_health_probe.py tests/test_watchdog_primary_recovery.py tests/test_flask_process_guard.py tests/test_flask_launcher_contract.py tests/test_watchdog_install_runtime.py -q
```

The repair was tested with Python 3.12 and 3.13, including real PowerShell 5.1
and undrained OS pipes. A future CI enablement should cover 3.11 and 3.13 without
changing runtime permissions or suppressing these assertions.

# API stall recovery implementation plan

> **For agentic workers:** Use subagent-driven development for the two independent runtime and supervisor changes. The operator explicitly authorized implementation, tests, deployment and final verification.

**Goal:** Keep API responses independent of logging backpressure and make health checks and recovery complete within explicit wall-clock bounds.

**Architecture:** Preserve Flask on MiniPC loopback 5003 and its existing scheduled launcher. Isolate logging I/O behind a bounded nonblocking queue; isolate each health probe in a disposable process with an outer deadline. Run legacy producer recovery independently of the primary API. Preserve authentication, subscription records, research decisions and notification settings.

**Tech stack:** Existing Python standard library/requests, Flask, Windows PowerShell 5.1 and Task Scheduler.

## Evidence and limits

- On 2026-10-18 the public frontend returned 200 while API health requests exceeded 12 seconds. A MiniPC loopback health check also timed out; the existing process subsequently responded normally. The community displayed an actual API timeout and recovered after retry.
- Runtime Git 3d46897d preceded the current Flask process; the scanner fix was already present. An old running scanner version is not the demonstrated explanation.
- A Windows PowerShell 5.1 loopback reproduction showed that `Invoke-WebRequest -TimeoutSec 1` did not return when a response body stalled; the exact disposable test process required termination after five seconds. The watchdog's configured timeout is not an overall recovery deadline.
- The primary watchdog runs legacy 5001 recovery before probing 5003. This can defer primary recovery; IgnoreNew skips later instances while that invocation is still running. The tunnel watchdog has a 72-hour task limit.
- A separate controlled reproduction showed that a blocked synchronous logging sink prevents Werkzeug from sending health response headers. Blocking an external network call without holding the logging sink did not reproduce that behavior.
- These are demonstrated failure mechanisms. The exact initial trigger of the historical MiniPC pause is not established by a contemporaneous thread trace. Do not relabel a hypothesis as a confirmed historical cause.

## Constraints and review focus

- Never print secrets, raw exception URLs, credentials, request bodies, query strings or authorization headers. Frame diagnostics contain code locations only.
- Production stays `127.0.0.1:5003`; no Spring, 8080, unrelated process termination or host reboot.
- Preserve the legacy KIS producer while separating its recovery from primary service health.
- Probe cleanup must terminate only the spawned probe, including timeout/trickle cases; TLS verification remains enabled.
- Queue saturation, broken log streams and diagnostic file failures must not block requests or recurse into stderr.
- Slow-request diagnostics are bounded, private artifacts with no public endpoint or new external transmission.
- Generated forensic artifacts under data/reviews stay untracked. No production data or environment files are replaced.

## Tasks

- [x] Runtime: reproduce blocked-sink header delay, implement nonblocking logging and test redaction, saturation, daemon lifecycle and configuration idempotence.
- [x] Diagnostics: record bounded slow-request stacks and timing without request data; test cleanup and file failure isolation.
- [x] Supervisors: reproduce header/body/trickle stalls, implement a finite outer process deadline, prioritize primary recovery and separate legacy monitoring, configure finite independent task runs.
- [ ] Run focused tests, meaningful integration probes and required wider CI; obtain an independent source review.
- [ ] Commit/push, attach the repair PR and merge only passing code.
- [ ] Deploy exact committed code to MiniPC, update task definitions while preserving principals/triggers unless intentionally changed, restart only the API runtime and verify local/public health and authenticated community.
- [ ] Verify bounded failure/recovery with a disposable loopback fixture; perform a controlled API watchdog recovery check without stopping research or other applications. Preserve sanitized evidence and report tested bounds and remaining limits.

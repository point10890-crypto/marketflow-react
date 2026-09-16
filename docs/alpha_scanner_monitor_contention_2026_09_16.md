# Alpha scanner monitor contention correction

## Evidence

MiniPC scheduler logs on 2026-09-16 repeatedly show acquisition timeouts for
`alpha_scanner_alert_state.json.delivery.lock`. The scheduler then sleeps for
120 seconds, retries and emits the reported recovery notification. Some cycles
exhaust both attempts. Flask also runs the realtime monitor at a 30-second
polling interval; both callers share the canonical delivery guard.

The monitor previously read its state before acquiring the guard, waited up to
30 seconds for a concurrent transaction, and wrote monitor state after releasing
the guard. Normal contention therefore became a job failure and stale state
could overwrite a later transaction's state.

## Change

- Acquire the existing canonical guard without waiting at the monitor entry.
- Return `busy` when another transaction owns it, without scanning, sending or
  writing either state file. The scheduler logs a deferral and returns normally;
  the next configured polling cycle can try again.
- Keep state reads, scan, delivery and state persistence within the guard.
- Handle only the initial acquisition timeout. Actual scan, file I/O and
  delivery errors retain their existing failure behavior.
- Preserve alert deduplication, send-after-success commit behavior and all
  transport opt-in settings. No real Telegram messages were sent for validation.

## Verification

The contention and scheduler-notification tests failed on the original code.
After the fix, the following suite passed (149 tests):

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_admin_mirofish_alpha_scanner.py tests/test_scheduler_with_record.py tests/test_signal_contract.py -q
```

Coverage includes a competing thread, an independently held OS file lock,
state preservation while busy, lock coverage through final persistence, no
retry notification on contention, propagation of a timeout within analysis,
existing delivery/deduplication checks and signal contracts.

This is locally verified source code. Production deployment and process restart
have not been performed for this fix. Both the Flask and scheduler processes
must load the new module for the changed behavior to apply to all callers.
An indefinitely stalled lock owner remains a separate operational fault; a
`busy` result does not claim that the owner completed a scan.

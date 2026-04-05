"""
MarketFlow Watchdog Service
- Runs health checks every 60 seconds
- Auto-restarts failed services
- Max 3 restart attempts per service per hour (prevent restart loops)
- Telegram alert on persistent failures
- Run as: python watchdog_service.py &
"""

import sys
import time
import signal
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path

from healthcheck import (
    SERVICES, notify_telegram, run_health_check,
    LOGS_DIR, logger as hc_logger,
)

# ── Config ──
CHECK_INTERVAL = 60           # seconds between checks
MAX_RESTARTS_PER_HOUR = 3     # per service
PERSISTENT_FAILURE_ALERT = 3  # alert after this many consecutive failures

# ── Logging ──
logger = logging.getLogger("watchdog")
logger.setLevel(logging.INFO)

_fh = logging.FileHandler(str(LOGS_DIR / "watchdog_service.log"), encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
logger.addHandler(_fh)

_sh = logging.StreamHandler(sys.stdout)
_sh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
logger.addHandler(_sh)

# ── State Tracking ──
# restart_history[service_name] = [datetime, datetime, ...]
restart_history: dict[str, list[datetime]] = defaultdict(list)
# consecutive_failures[service_name] = int
consecutive_failures: dict[str, int] = defaultdict(int)
# persistent_alerted[service_name] = bool (avoid spamming)
persistent_alerted: dict[str, bool] = defaultdict(bool)

_running = True


def _signal_handler(signum, frame):
    global _running
    logger.info(f"Received signal {signum}, shutting down...")
    _running = False


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


def _prune_restart_history(name: str):
    """Remove restart records older than 1 hour."""
    cutoff = datetime.now() - timedelta(hours=1)
    restart_history[name] = [
        t for t in restart_history[name] if t > cutoff
    ]


def _can_restart(name: str) -> bool:
    """Check if we haven't exceeded max restarts per hour."""
    _prune_restart_history(name)
    return len(restart_history[name]) < MAX_RESTARTS_PER_HOUR


def watchdog_cycle():
    """Run one watchdog cycle: check all services, restart if needed."""
    for name, svc in SERVICES.items():
        try:
            alive = svc["check"]()
        except Exception as e:
            logger.error(f"Check failed for {name}: {e}")
            alive = False

        if alive:
            # Service is up -- reset failure tracking
            if consecutive_failures[name] > 0:
                logger.info(f"{name}: recovered (was down for {consecutive_failures[name]} cycles)")
            consecutive_failures[name] = 0
            persistent_alerted[name] = False
            continue

        # Service is down
        consecutive_failures[name] += 1
        logger.warning(
            f"{name}: DOWN (consecutive failures: {consecutive_failures[name]})"
        )

        if _can_restart(name):
            logger.info(f"{name}: attempting restart...")
            try:
                success = svc["restart"]()
            except Exception as e:
                logger.error(f"{name}: restart exception: {e}")
                success = False

            restart_history[name].append(datetime.now())

            if success:
                logger.info(f"{name}: restart succeeded")
                consecutive_failures[name] = 0
                persistent_alerted[name] = False
                notify_telegram(f"{name} was down and restarted successfully.")
            else:
                logger.error(f"{name}: restart failed")
        else:
            restarts_in_hour = len(restart_history[name])
            logger.warning(
                f"{name}: restart skipped ({restarts_in_hour}/{MAX_RESTARTS_PER_HOUR} "
                f"restarts in last hour)"
            )

        # Persistent failure alert (only once)
        if (consecutive_failures[name] >= PERSISTENT_FAILURE_ALERT
                and not persistent_alerted[name]):
            persistent_alerted[name] = True
            msg = (
                f"<b>PERSISTENT FAILURE</b>\n"
                f"Service: {name}\n"
                f"Down for {consecutive_failures[name]} consecutive checks\n"
                f"Restarts in last hour: {len(restart_history[name])}/{MAX_RESTARTS_PER_HOUR}\n"
                f"Manual intervention may be required."
            )
            notify_telegram(msg)
            logger.error(f"{name}: persistent failure alert sent")


def main():
    logger.info("=" * 50)
    logger.info("Watchdog service started")
    logger.info(f"  Check interval: {CHECK_INTERVAL}s")
    logger.info(f"  Max restarts/hour: {MAX_RESTARTS_PER_HOUR}")
    logger.info(f"  Persistent alert after: {PERSISTENT_FAILURE_ALERT} failures")

    # Write PID file
    pid_file = LOGS_DIR / "watchdog_service.pid"
    pid_file.write_text(str(__import__("os").getpid()))

    while _running:
        try:
            watchdog_cycle()
        except Exception as e:
            logger.error(f"Watchdog cycle error: {e}")

        # Sleep in short intervals so we can respond to signals
        for _ in range(CHECK_INTERVAL):
            if not _running:
                break
            time.sleep(1)

    logger.info("Watchdog service stopped")
    # Clean up PID file
    if pid_file.exists():
        pid_file.unlink()


if __name__ == "__main__":
    main()

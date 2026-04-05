"""
MarketFlow Health Check Module
- Checks Flask (5001), Spring Boot (8080), Cloudflare Tunnel, Scheduler
- Restarts failed services
- Sends Telegram alerts on restart
- Logs to logs/healthcheck.log
"""

import os
import sys
import subprocess
import logging
import time
from datetime import datetime
from urllib import request, error as urllib_error
from pathlib import Path

# ── Paths ──
BASE_DIR = Path(__file__).resolve().parent
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

PYTHON_PATH = str(BASE_DIR / ".venv" / "Scripts" / "python.exe")
CLOUDFLARED_PATH = str(BASE_DIR / "cloudflared.exe")
CLOUDFLARED_CONFIG = r"C:\Users\dynas\.cloudflared\config.yml"
FRONTEND_DIR = str(BASE_DIR / "frontend-react")

# ── Telegram config from .env ──
def _load_env():
    env_path = BASE_DIR / ".env"
    env = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env

_ENV = _load_env()
TELEGRAM_BOT_TOKEN = _ENV.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = _ENV.get("TELEGRAM_CHAT_ID", "")

# ── Logging ──
logger = logging.getLogger("healthcheck")
logger.setLevel(logging.INFO)

_file_handler = logging.FileHandler(
    str(LOGS_DIR / "healthcheck.log"), encoding="utf-8"
)
_file_handler.setFormatter(
    logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
)
logger.addHandler(_file_handler)

_stream_handler = logging.StreamHandler(sys.stdout)
_stream_handler.setFormatter(
    logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
)
logger.addHandler(_stream_handler)


# ── Health Check Functions ──

def _http_check(url: str, timeout: int = 5) -> bool:
    """Check if an HTTP endpoint responds (any status including 404)."""
    try:
        req = request.Request(url, method="GET")
        with request.urlopen(req, timeout=timeout):
            pass
        return True
    except urllib_error.HTTPError:
        return True  # Server responded (404, 401 etc.) = alive
    except Exception:
        return False


def check_flask() -> bool:
    """Check Flask API on port 5001."""
    return _http_check("http://127.0.0.1:5001/api/community/summary") or _http_check("http://127.0.0.1:5001/")


def check_springboot() -> bool:
    """Check Spring Boot on port 8080."""
    return _http_check("http://127.0.0.1:8080/") or _http_check("http://localhost:8080/")


def check_tunnel() -> bool:
    """Check if cloudflared tunnel is running."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq cloudflared.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10
        )
        return "cloudflared.exe" in result.stdout
    except Exception:
        return False


def check_scheduler() -> bool:
    """Check if scheduler.py --daemon is running."""
    try:
        wmic = subprocess.run(
            ["wmic", "process", "where",
             "name='python.exe'", "get", "commandline"],
            capture_output=True, text=True, timeout=10
        )
        return "scheduler.py" in wmic.stdout and "--daemon" in wmic.stdout
    except Exception:
        return False


# ── Restart Functions ──

def restart_flask() -> bool:
    """Restart Flask API server."""
    logger.info("Restarting Flask...")
    try:
        subprocess.Popen(
            [PYTHON_PATH, "flask_app.py"],
            cwd=str(BASE_DIR),
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        # Wait up to 30s for port
        for _ in range(10):
            time.sleep(3)
            if check_flask():
                logger.info("Flask restarted successfully")
                return True
        logger.error("Flask restart FAILED (port 5001 not responding)")
        return False
    except Exception as e:
        logger.error(f"Flask restart exception: {e}")
        return False


def restart_springboot() -> bool:
    """Restart Spring Boot server."""
    logger.info("Restarting Spring Boot...")
    try:
        gradlew = str(BASE_DIR / "backend" / "gradlew.bat")
        subprocess.Popen(
            [gradlew, "bootRun"],
            cwd=str(BASE_DIR / "backend"),
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        for _ in range(20):
            time.sleep(3)
            if check_springboot():
                logger.info("Spring Boot restarted successfully")
                return True
        logger.error("Spring Boot restart FAILED (port 8080 not responding)")
        return False
    except Exception as e:
        logger.error(f"Spring Boot restart exception: {e}")
        return False


def restart_tunnel() -> bool:
    """Tunnel은 별도 서비스(justbuy-tunnel)로 관리 — 재시작 안 함, 알림만."""
    logger.warning("Cloudflare Tunnel down — 별도 서비스이므로 자동 재시작 안 함")
    return False


def restart_scheduler() -> bool:
    """Restart scheduler daemon."""
    logger.info("Restarting Scheduler...")
    try:
        subprocess.Popen(
            [PYTHON_PATH, "scheduler.py", "--daemon"],
            cwd=str(BASE_DIR),
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        time.sleep(8)
        alive = check_scheduler()
        if alive:
            logger.info("Scheduler restarted successfully")
        else:
            logger.error("Scheduler restart FAILED")
        return alive
    except Exception as e:
        logger.error(f"Scheduler restart exception: {e}")
        return False


SERVICES = {
    "Flask (5001)": {"check": check_flask, "restart": restart_flask},
    "Spring Boot (8080)": {"check": check_springboot, "restart": restart_springboot},
    "Cloudflare Tunnel": {"check": check_tunnel, "restart": restart_tunnel},
    "Scheduler": {"check": check_scheduler, "restart": restart_scheduler},
}


def restart_service(name: str) -> bool:
    """Restart a service by name. Returns True if restart succeeded."""
    svc = SERVICES.get(name)
    if not svc:
        logger.error(f"Unknown service: {name}")
        return False
    return svc["restart"]()


# ── Telegram Notification ──

def notify_telegram(message: str):
    """Send a Telegram alert message."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured, skipping notification")
        return
    try:
        import json
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = json.dumps({
            "chat_id": TELEGRAM_CHAT_ID,
            "text": f"[MarketFlow HealthCheck]\n{message}",
            "parse_mode": "HTML",
        }).encode("utf-8")
        req = request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with request.urlopen(req, timeout=10):
            pass
        logger.info(f"Telegram alert sent: {message[:80]}")
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")


# ── Main Entry ──

def run_health_check() -> dict:
    """
    Run all health checks. Restart down services. Notify on restarts.
    Returns dict of {service_name: {"alive": bool, "restarted": bool}}
    """
    results = {}
    restarted_services = []

    for name, svc in SERVICES.items():
        alive = svc["check"]()
        restarted = False

        if alive:
            logger.info(f"{name}: OK")
        else:
            logger.warning(f"{name}: DOWN")
            restarted = svc["restart"]()
            if restarted:
                restarted_services.append(f"{name} (restarted OK)")
            else:
                restarted_services.append(f"{name} (restart FAILED)")

        results[name] = {"alive": alive or restarted, "restarted": restarted}

    # Telegram alert if any service was restarted
    if restarted_services:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        msg = f"<b>{ts}</b>\n" + "\n".join(f"- {s}" for s in restarted_services)
        notify_telegram(msg)

    return results


def main():
    logger.info("=" * 40)
    logger.info("Health check started")
    results = run_health_check()
    logger.info("Health check complete")
    for name, r in results.items():
        status = "UP" if r["alive"] else "DOWN"
        extra = " (restarted)" if r["restarted"] else ""
        print(f"  {name}: {status}{extra}")


if __name__ == "__main__":
    main()

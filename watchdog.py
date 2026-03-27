#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MarketFlow Watchdog — 서비스 감시 + 자동 재시작

60초 간격으로 Flask / cloudflared / scheduler 생존 확인
죽은 서비스 자동 재시작 + 텔레그램 알림

PID 파일 기반 단일 인스턴스 보장 (중복 실행 방지)

실행: python watchdog.py  (auto_start_scheduler.bat에서 자동 시작)
"""
import os
import sys
import time
import socket
import subprocess
import logging
import atexit
from datetime import datetime

if sys.platform.startswith('win'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

# ── 경로 고정 ──
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = os.path.join(BASE_DIR, '.venv', 'Scripts', 'python.exe')
LOG_DIR = os.path.join(BASE_DIR, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

# ── PID 파일 (단일 인스턴스 보장) ──
PID_FILE = os.path.join(LOG_DIR, 'watchdog.pid')

# ── 로깅 ──
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [WATCHDOG] %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, 'watchdog.log'), encoding='utf-8'),
        logging.StreamHandler()
    ]
)
log = logging.getLogger('watchdog')

# ── 설정 ──
CHECK_INTERVAL = 60          # 초
FLASK_PORT = 5001
STARTUP_GRACE = 30           # 부팅 후 최초 체크까지 대기 (초)
MAX_RESTART_PER_HOUR = 3     # 시간당 최대 재시작 횟수 (무한루프 방지)

# 재시작 이력 추적
_restart_history = {'flask': [], 'cloudflared': [], 'scheduler': []}


# ============================================================
# PID 파일 기반 단일 인스턴스 잠금
# ============================================================

def _is_pid_alive(pid):
    """PID가 실제로 살아있는 프로세스인지 확인"""
    try:
        result = subprocess.run(
            ['tasklist', '/FI', f'PID eq {pid}', '/NH', '/FO', 'CSV'],
            capture_output=True, text=True, timeout=10
        )
        return str(pid) in result.stdout
    except Exception:
        return False


def _acquire_pid_lock():
    """PID 파일 잠금 획득. 이미 실행 중이면 False 반환"""
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, 'r') as f:
                old_pid = int(f.read().strip())
            if _is_pid_alive(old_pid):
                log.warning(f"⚠️ Watchdog 이미 실행 중 (PID {old_pid}). 종료합니다.")
                return False
            else:
                log.info(f"🧹 이전 PID {old_pid} 사망 확인 — PID 파일 갱신")
        except (ValueError, IOError):
            log.info("🧹 잘못된 PID 파일 — 덮어쓰기")

    # 현재 PID 기록
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))
    log.info(f"🔒 PID 파일 잠금 획득 (PID {os.getpid()})")
    return True


def _release_pid_lock():
    """PID 파일 잠금 해제 (종료 시)"""
    try:
        if os.path.exists(PID_FILE):
            with open(PID_FILE, 'r') as f:
                pid = int(f.read().strip())
            if pid == os.getpid():
                os.remove(PID_FILE)
                log.info("🔓 PID 파일 잠금 해제")
    except Exception:
        pass


def _is_port_open(port, host='127.0.0.1', timeout=3):
    """TCP 포트가 열려있는지 확인"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (ConnectionRefusedError, TimeoutError, OSError):
        return False


def _is_process_running(name):
    """프로세스 이름으로 실행 중인지 확인 (tasklist)"""
    try:
        result = subprocess.run(
            ['tasklist', '/FI', f'IMAGENAME eq {name}', '/NH', '/FO', 'CSV'],
            capture_output=True, text=True, timeout=10
        )
        return name.lower() in result.stdout.lower()
    except Exception:
        return False


def _find_python_scheduler():
    """scheduler.py를 실행 중인 python 프로세스가 있는지 확인.
    PID 파일 우선, wmic 폴백.
    """
    # 1차: PID 파일 확인 (start_scheduler.bat이 생성)
    pid_file = os.path.join(LOG_DIR, 'scheduler.pid')
    if os.path.exists(pid_file):
        try:
            with open(pid_file, 'r') as f:
                pid = int(f.read().strip())
            if _is_pid_alive(pid):
                return True
        except (ValueError, IOError):
            pass

    # 2차: PowerShell 폴백 (wmic deprecated)
    try:
        result = subprocess.run(
            ['powershell', '-Command',
             "Get-CimInstance Win32_Process | Where-Object {$_.CommandLine -like '*scheduler.py*--daemon*'} | Select-Object -ExpandProperty ProcessId"],
            capture_output=True, text=True, timeout=15
        )
        lines = [l.strip() for l in result.stdout.strip().split('\n') if l.strip().isdigit()]
        return len(lines) > 0
    except Exception:
        return False


def _count_flask_processes():
    """Flask(5001) 포트를 점유하는 프로세스 수 — 중복 감지용"""
    try:
        result = subprocess.run(
            ['netstat', '-ano'], capture_output=True, text=True, timeout=10
        )
        pids = set()
        for line in result.stdout.split('\n'):
            if f':{FLASK_PORT}' in line and 'LISTENING' in line:
                parts = line.split()
                if parts:
                    pids.add(parts[-1])
        return len(pids)
    except Exception:
        return 0


def _can_restart(service_name):
    """시간당 재시작 제한 확인"""
    now = time.time()
    history = _restart_history[service_name]
    # 1시간 이전 기록 제거
    _restart_history[service_name] = [t for t in history if now - t < 3600]
    return len(_restart_history[service_name]) < MAX_RESTART_PER_HOUR


def _record_restart(service_name):
    """재시작 기록"""
    _restart_history[service_name].append(time.time())


def _send_telegram(message):
    """텔레그램 알림"""
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(BASE_DIR, '.env'))
        import requests
        token = os.getenv('TELEGRAM_BOT_TOKEN')
        chat_id = os.getenv('TELEGRAM_CHAT_ID')
        if not token or not chat_id:
            log.warning("⚠️ TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID 미설정")
            return
        resp = requests.post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            json={'chat_id': chat_id, 'text': message, 'parse_mode': 'HTML'},
            timeout=10
        )
        if resp.status_code != 200:
            log.warning(f"⚠️ 텔레그램 발송 실패: {resp.status_code}")
    except Exception as e:
        log.warning(f"⚠️ 텔레그램 오류: {e}")


# ============================================================
# 서비스 재시작 함수
# ============================================================

def restart_flask():
    """Flask API 재시작 (중복 방지: 이미 실행 중이면 스킵)"""
    # 중복 확인: 포트가 열려있는데 감지 못했을 수 있음 — 재확인
    time.sleep(2)
    if _is_port_open(FLASK_PORT):
        log.info("💚 Flask 재확인 — 이미 실행 중. 스킵.")
        return True

    if not _can_restart('flask'):
        log.warning("⚠️ Flask 재시작 제한 초과 (시간당 %d회)", MAX_RESTART_PER_HOUR)
        return False

    log.info("🔄 Flask 재시작 시도...")

    # 기존 5001 포트 프로세스 종료 (좀비 정리)
    try:
        result = subprocess.run(
            ['netstat', '-ano'], capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.split('\n'):
            if f':{FLASK_PORT}' in line and 'LISTENING' in line:
                parts = line.split()
                if parts:
                    pid = parts[-1]
                    subprocess.run(['taskkill', '/F', '/PID', pid],
                                   capture_output=True, timeout=10)
    except Exception:
        pass

    time.sleep(3)

    # Flask 시작
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    subprocess.Popen(
        [PYTHON, 'flask_app.py'],
        cwd=BASE_DIR, env=env,
        creationflags=subprocess.CREATE_NO_WINDOW
    )

    # 포트 오픈 대기 (최대 30초)
    for i in range(15):
        time.sleep(2)
        if _is_port_open(FLASK_PORT):
            log.info("✅ Flask 재시작 성공 (port %d)", FLASK_PORT)
            _record_restart('flask')
            return True

    log.error("❌ Flask 재시작 실패 — 포트 %d 미오픈", FLASK_PORT)
    return False


def restart_cloudflared():
    """Cloudflare Named Tunnel 재시작 (api.bit-man.net → localhost:5001)"""
    if not _can_restart('cloudflared'):
        log.warning("⚠️ cloudflared 재시작 제한 초과")
        return False

    log.info("🔄 cloudflared Named Tunnel 재시작 시도...")

    # 기존 프로세스 종료
    subprocess.run(['taskkill', '/F', '/IM', 'cloudflared.exe'],
                   capture_output=True, timeout=10)
    time.sleep(2)

    # Named Tunnel로 재시작 (api.bit-man.net → localhost:5001)
    cf_exe = os.path.join(BASE_DIR, 'cloudflared.exe')
    subprocess.Popen(
        [cf_exe, 'tunnel', 'run', 'bitman-api'],
        cwd=BASE_DIR,
        creationflags=subprocess.CREATE_NO_WINDOW
    )

    time.sleep(8)
    if _is_process_running('cloudflared.exe'):
        log.info("✅ cloudflared Named Tunnel 재시작 성공 (bitman-api)")
        _record_restart('cloudflared')
        return True

    log.error("❌ cloudflared Named Tunnel 재시작 실패")
    return False


def restart_scheduler():
    """Scheduler 데몬 재시작 (중복 방지: 재확인 후 시작)"""
    # 중복 확인: wmic이 느려서 감지 못했을 수 있음 — 재확인
    time.sleep(2)
    if _find_python_scheduler():
        log.info("💚 Scheduler 재확인 — 이미 실행 중. 스킵.")
        return True

    if not _can_restart('scheduler'):
        log.warning("⚠️ Scheduler 재시작 제한 초과")
        return False

    log.info("🔄 Scheduler 재시작 시도...")

    # 기존 scheduler 프로세스 종료
    try:
        result = subprocess.run(
            ['powershell', '-Command',
             "Get-CimInstance Win32_Process | Where-Object {$_.CommandLine -like '*scheduler.py*--daemon*'} | Select-Object -ExpandProperty ProcessId"],
            capture_output=True, text=True, timeout=15
        )
        for line in result.stdout.strip().split('\n'):
            pid = line.strip()
            if pid.isdigit():
                subprocess.run(['taskkill', '/F', '/PID', pid],
                               capture_output=True, timeout=10)
    except Exception:
        pass

    time.sleep(3)

    # 재시작
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    subprocess.Popen(
        [PYTHON, 'scheduler.py', '--daemon'],
        cwd=BASE_DIR, env=env,
        creationflags=subprocess.CREATE_NO_WINDOW
    )

    time.sleep(10)
    if _find_python_scheduler():
        log.info("✅ Scheduler 재시작 성공")
        _record_restart('scheduler')
        return True

    log.error("❌ Scheduler 재시작 실패")
    return False


# ============================================================
# 메인 루프
# ============================================================

def check_and_heal():
    """전체 서비스 상태 확인 + 자동 복구"""
    issues = []

    # 1. Flask
    if not _is_port_open(FLASK_PORT):
        log.warning("🔴 Flask (port %d) 미응답", FLASK_PORT)
        if restart_flask():
            issues.append("Flask 재시작 ✅")
        else:
            issues.append("Flask 재시작 실패 ❌")

    # 2. Cloudflared
    if not _is_process_running('cloudflared.exe'):
        log.warning("🔴 cloudflared 프로세스 없음")
        # Flask가 살아있을 때만 터널 시작
        if _is_port_open(FLASK_PORT):
            if restart_cloudflared():
                issues.append("cloudflared 재시작 ✅")
            else:
                issues.append("cloudflared 재시작 실패 ❌")
        else:
            issues.append("cloudflared 대기 (Flask 미실행)")

    # 3. Scheduler
    if not _find_python_scheduler():
        log.warning("🔴 Scheduler 데몬 없음")
        if restart_scheduler():
            issues.append("Scheduler 재시작 ✅")
        else:
            issues.append("Scheduler 재시작 실패 ❌")

    # 텔레그램 알림 (이슈 있을 때만)
    if issues:
        now_str = datetime.now().strftime('%H:%M')
        msg = (
            f"<b>🔧 Watchdog 복구 ({now_str})</b>\n\n"
            + "\n".join(f"• {i}" for i in issues)
        )
        _send_telegram(msg)

    return len(issues) == 0


def main():
    # ── 단일 인스턴스 잠금 ──
    if not _acquire_pid_lock():
        print("[WATCHDOG] 이미 실행 중인 인스턴스가 있습니다. 종료.")
        sys.exit(0)
    atexit.register(_release_pid_lock)

    log.info("=" * 50)
    log.info("🐕 MarketFlow Watchdog 시작 (PID %d)", os.getpid())
    log.info(f"   BASE_DIR: {BASE_DIR}")
    log.info(f"   CHECK_INTERVAL: {CHECK_INTERVAL}초")
    log.info(f"   MAX_RESTART/HR: {MAX_RESTART_PER_HOUR}")
    log.info("=" * 50)

    # 부팅 직후라면 서비스 시작 대기
    log.info(f"⏳ 초기 대기 {STARTUP_GRACE}초 (서비스 시작 대기)...")
    time.sleep(STARTUP_GRACE)

    _send_telegram(
        "<b>🐕 Watchdog 감시 시작</b>\n\n"
        f"• Flask: localhost:{FLASK_PORT}\n"
        f"• Cloudflare Tunnel\n"
        f"• Scheduler daemon\n"
        f"• 체크 간격: {CHECK_INTERVAL}초"
    )

    # Heartbeat 파일 — 외부에서 watchdog 생존 확인용
    heartbeat_file = os.path.join(LOG_DIR, 'watchdog.heartbeat')

    consecutive_ok = 0
    while True:
        try:
            # Heartbeat 기록 (매 체크마다 갱신)
            try:
                with open(heartbeat_file, 'w') as f:
                    f.write(str(time.time()))
            except Exception:
                pass

            ok = check_and_heal()
            if ok:
                consecutive_ok += 1
                # 1시간마다 한 번 정상 로그
                if consecutive_ok % (3600 // CHECK_INTERVAL) == 0:
                    log.info("💚 전체 서비스 정상 (%d회 연속)", consecutive_ok)
            else:
                consecutive_ok = 0
        except Exception as e:
            log.error(f"❌ Watchdog 체크 오류: {e}", exc_info=True)

        time.sleep(CHECK_INTERVAL)


if __name__ == '__main__':
    main()

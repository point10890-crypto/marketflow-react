"""
MarketFlow 스케줄러 워치독 (자가복구 시스템)
=============================================
Windows Task Scheduler에서 5분마다 실행.
단 하나의 스크립트로 3가지 문제를 해결:

1. 코드 동기화: git pull로 최신 코드 자동 반영
2. 스케줄러 감시: 죽었으면 자동 재시작 + 텔레그램 알림
3. 코드 변경 감지: scheduler.py/engine/ 변경 시 스케줄러 자동 재시작

사용법:
  python scheduler_watchdog.py          # 1회 실행 (Task Scheduler용)
  python scheduler_watchdog.py --setup  # Windows Task Scheduler 자동 등록

Task Scheduler 등록:
  이름: MarketFlow-Watchdog
  트리거: 5분마다 반복, 무기한
  동작: pythonw.exe scheduler_watchdog.py
"""

import json
import os
import subprocess
import sys
import hashlib
import time
from datetime import datetime
from pathlib import Path

# ── 경로 설정 ──
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
LOG_DIR = os.path.join(BASE_DIR, 'logs')
VENV_PYTHON = os.path.join(BASE_DIR, '.venv', 'Scripts', 'python.exe')
if not os.path.exists(VENV_PYTHON):
    VENV_PYTHON = sys.executable

HEARTBEAT_FILE = os.path.join(DATA_DIR, 'scheduler_heartbeat.json')
WATCHDOG_STATE = os.path.join(DATA_DIR, 'watchdog_state.json')
WATCHDOG_LOG = os.path.join(LOG_DIR, 'watchdog.log')
LOCK_FILE = os.path.join(DATA_DIR, '.scheduler.lock')

# 감시 대상 파일 (이 파일들이 바뀌면 스케줄러 재시작)
WATCHED_FILES = [
    os.path.join(BASE_DIR, 'scheduler.py'),
    os.path.join(BASE_DIR, 'engine', 'generator.py'),
    os.path.join(BASE_DIR, 'engine', 'llm_analyzer.py'),
    os.path.join(BASE_DIR, 'engine', 'scorer.py'),
    os.path.join(BASE_DIR, 'engine', 'models.py'),
    os.path.join(BASE_DIR, 'engine', 'config.py'),
]

STALE_THRESHOLD = 180  # heartbeat 3분 이상 갱신 없으면 dead 판정


def log(msg: str):
    """워치독 로그 (파일 + stdout)"""
    os.makedirs(LOG_DIR, exist_ok=True)
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"{ts} | {msg}"
    print(line)
    try:
        with open(WATCHDOG_LOG, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
        # 로그 파일 크기 제한 (1MB 초과 시 truncate)
        if os.path.getsize(WATCHDOG_LOG) > 1_000_000:
            with open(WATCHDOG_LOG, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            with open(WATCHDOG_LOG, 'w', encoding='utf-8') as f:
                f.writelines(lines[-500:])
    except Exception:
        pass


def send_telegram(message: str):
    """텔레그램 알림 (개인봇만)"""
    import requests
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, '.env'))
    token = os.getenv('TELEGRAM_BOT_TOKEN', '')
    chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
    if not token or not chat_id or 'your_bot_token' in token:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception:
        pass


# ── 1. 코드 동기화 (git pull) ──

def sync_code() -> bool:
    """git pull로 최신 코드 반영. 변경 있으면 True."""
    git_env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
    try:
        # fetch
        r = subprocess.run(
            ['git', 'fetch', 'origin', 'main', '--quiet'],
            capture_output=True, text=True, cwd=BASE_DIR, timeout=30, env=git_env
        )
        if r.returncode != 0:
            return False  # 네트워크 불가

        # diff 확인
        diff = subprocess.run(
            ['git', 'diff', 'HEAD', 'origin/main', '--name-only'],
            capture_output=True, text=True, cwd=BASE_DIR, timeout=10, env=git_env
        ).stdout.strip()
        if not diff:
            return False  # 변경 없음

        # stash → pull → pop
        status = subprocess.run(
            ['git', 'status', '--porcelain'],
            capture_output=True, text=True, cwd=BASE_DIR, timeout=10, env=git_env
        ).stdout.strip()
        stashed = False
        if status:
            subprocess.run(['git', 'stash', '--include-untracked'],
                           capture_output=True, cwd=BASE_DIR, timeout=30, env=git_env)
            stashed = True

        pull = subprocess.run(
            ['git', 'pull', '--rebase', 'origin', 'main'],
            capture_output=True, text=True, cwd=BASE_DIR, timeout=60, env=git_env
        )
        if pull.returncode != 0:
            subprocess.run(['git', 'rebase', '--abort'],
                           capture_output=True, cwd=BASE_DIR, timeout=10, env=git_env)
            subprocess.run(['git', 'pull', '--no-rebase', 'origin', 'main'],
                           capture_output=True, cwd=BASE_DIR, timeout=60, env=git_env)

        if stashed:
            subprocess.run(['git', 'stash', 'pop'],
                           capture_output=True, cwd=BASE_DIR, timeout=30, env=git_env)

        log(f"GIT PULL: 코드 동기화 완료 ({len(diff.splitlines())}개 파일)")
        return True

    except Exception as e:
        log(f"GIT PULL 실패: {e}")
        return False


# ── 2. 스케줄러 상태 확인 ──

def is_scheduler_alive() -> bool:
    """heartbeat 파일로 스케줄러 생존 확인"""
    if not os.path.exists(HEARTBEAT_FILE):
        return False
    try:
        age = time.time() - os.path.getmtime(HEARTBEAT_FILE)
        if age > STALE_THRESHOLD:
            return False
        with open(HEARTBEAT_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        pid = data.get('pid')
        if not pid:
            return False
        # PID가 실제로 살아있는지 확인
        r = subprocess.run(
            ['tasklist', '/FI', f'PID eq {pid}', '/NH'],
            capture_output=True, text=True, timeout=10
        )
        return str(pid) in r.stdout
    except Exception:
        return False


def kill_scheduler():
    """기존 스케줄러 프로세스 종료 (PowerShell 사용 — wmic 없는 Windows 대응)"""
    try:
        r = subprocess.run(
            ['powershell', '-Command',
             "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*scheduler.py --daemon*' } | Select-Object -ExpandProperty ProcessId"],
            capture_output=True, text=True, timeout=15
        )
        for line in r.stdout.strip().splitlines():
            line = line.strip()
            if line.isdigit():
                subprocess.run(['taskkill', '/F', '/PID', line],
                               capture_output=True, timeout=10)
                log(f"KILL: 스케줄러 PID {line} 종료")
    except Exception as e:
        log(f"KILL 실패: {e}")

    # 락 파일 정리
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except Exception:
        pass


def start_scheduler():
    """스케줄러 데몬 시작"""
    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
    subprocess.Popen(
        [VENV_PYTHON, os.path.join(BASE_DIR, 'scheduler.py'), '--daemon'],
        cwd=BASE_DIR, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    )
    log("START: 스케줄러 데몬 시작")


# ── 3. 코드 변경 감지 ──

def get_files_hash() -> str:
    """감시 대상 파일들의 해시 계산"""
    h = hashlib.md5()
    for fp in sorted(WATCHED_FILES):
        if os.path.exists(fp):
            h.update(fp.encode())
            h.update(str(os.path.getmtime(fp)).encode())
    return h.hexdigest()


def load_state() -> dict:
    try:
        with open(WATCHDOG_STATE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(WATCHDOG_STATE, 'w', encoding='utf-8') as f:
        json.dump(state, f)


# ── 메인 로직 ──

def run_watchdog():
    """워치독 1회 실행 (Task Scheduler에서 5분마다 호출)"""
    state = load_state()
    restart_needed = False
    restart_reason = ""

    # Step 1: 코드 동기화
    code_changed = sync_code()

    # Step 2: 코드 변경 감지
    current_hash = get_files_hash()
    prev_hash = state.get('files_hash', '')
    if prev_hash and current_hash != prev_hash:
        restart_needed = True
        restart_reason = "코드 변경 감지"
        log(f"CODE CHANGE: 감시 파일 변경 감지 (hash: {prev_hash[:8]} → {current_hash[:8]})")
    state['files_hash'] = current_hash

    # Step 3: 스케줄러 생존 확인
    alive = is_scheduler_alive()
    if not alive:
        restart_needed = True
        if not restart_reason:
            restart_reason = "스케줄러 사망"
        log("DEAD: 스케줄러 heartbeat 없음 또는 프로세스 사망")

    # Step 4: 필요 시 재시작
    if restart_needed:
        kill_scheduler()
        time.sleep(3)
        start_scheduler()

        msg = (
            f"<b>🔄 스케줄러 자동 재시작</b>\n\n"
            f"사유: {restart_reason}\n"
            f"시각: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"호스트: {os.environ.get('COMPUTERNAME', 'unknown')}"
        )
        send_telegram(msg)
        log(f"RESTART: {restart_reason}")

        # 재시작 후 잠시 대기, 살아있는지 확인
        time.sleep(10)
        if is_scheduler_alive():
            log("VERIFY: 재시작 성공 — 스케줄러 정상 작동")
        else:
            log("VERIFY: ⚠️ 재시작 후에도 스케줄러 미응답!")
            send_telegram(
                "<b>🚨 스케줄러 재시작 실패</b>\n\n"
                "워치독이 스케줄러를 재시작했으나 응답 없음.\n"
                "수동 확인 필요!"
            )
    else:
        if alive:
            log("OK: 스케줄러 정상 작동 중")

    state['last_check'] = datetime.now().isoformat()
    state['alive'] = alive or restart_needed
    save_state(state)


# ── Task Scheduler 자동 등록 ──

def setup_task_scheduler():
    """Windows Task Scheduler에 워치독 작업 등록"""
    task_name = "MarketFlow-Watchdog"
    pythonw = os.path.join(BASE_DIR, '.venv', 'Scripts', 'pythonw.exe')
    if not os.path.exists(pythonw):
        pythonw = VENV_PYTHON
    script = os.path.join(BASE_DIR, 'scheduler_watchdog.py')

    # 기존 작업 삭제
    subprocess.run(
        ['schtasks', '/Delete', '/TN', task_name, '/F'],
        capture_output=True, timeout=10
    )

    # 새 작업 생성: 5분마다, 무기한 반복 (/RL HIGHEST 없이 — 비관리자 계정 대응)
    cmd = [
        'schtasks', '/Create',
        '/TN', task_name,
        '/TR', f'"{pythonw}" "{script}"',
        '/SC', 'MINUTE', '/MO', '5',
        '/F',
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if r.returncode == 0:
        print(f"✅ Task Scheduler 등록 완료: {task_name}")
        print(f"   5분마다 실행: {pythonw} {script}")
        print(f"   확인: schtasks /Query /TN {task_name}")
    else:
        print(f"❌ 등록 실패: {r.stderr}")
        print("   관리자 권한으로 다시 시도하세요.")


if __name__ == '__main__':
    if '--setup' in sys.argv:
        setup_task_scheduler()
    else:
        try:
            run_watchdog()
        except Exception as e:
            log(f"FATAL: 워치독 예외 — {e}")

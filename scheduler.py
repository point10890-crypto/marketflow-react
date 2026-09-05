#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MarketFlow 통합 스케줄러 — US / KR / Crypto

스케줄 (KST):
─────────────────────────────────────────────────
  04:00  US Market  전체 데이터 갱신 → Smart Money Top 5 텔레그램
  09:30  US Market  Track Record 스냅샷 + 성과 추적
  14:50  KR Market  종가베팅 V2 + 수급/AI/리포트 → 텔레그램
  16:00  KR / US    VCP 시그널 업데이트 → 텔레그램
  17:30  KR Market  로컬 전수 사전필터 → Vision 최대 20 → BUY 최대 10
  토 10:00  KR     히스토리 수집 (백업)
─────────────────────────────────────────────────
  매 4시간 (00/04/08/12/16/20 KST)  Crypto  전체 파이프라인
    → Gate Check → VCP Scan → Briefing → Prediction → Risk → Lead-Lag
    → Gate 전환 알림, VCP 시그널 알림, Briefing 텔레그램
─────────────────────────────────────────────────

환경 변수:
- KR_MARKET_DIR: 프로젝트 루트 (기본: 현재 디렉토리)
- KR_MARKET_LOG_DIR: 로그 디렉토리
- KR_MARKET_SCHEDULE_ENABLED: 스케줄 활성화 (기본: true)
- KR_MARKET_UPDATE_TIME: KR 올업데이트 시간
- KR_MARKET_PYTHON: Python 실행 경로
- MARKETFLOW_SCHEDULER_GIT_SYNC_ENABLED: 스케줄러 Git pull/push opt-in (기본: false)

실행 방법:
  python scheduler.py --daemon        # 데몬 모드 (전체 스케줄)
  python scheduler.py --now           # 즉시 전체 업데이트 (US+KR+Crypto)
  python scheduler.py --us-pro        # US Market 데이터 갱신만
  python scheduler.py --jongga-v2     # 종가베팅 V2만
  python scheduler.py --crypto        # Crypto 전체 파이프라인만
  python scheduler.py --crypto-gate   # Crypto Gate Check만
  python scheduler.py --crypto-scan   # Crypto VCP Scan만
"""
import os
import sys

# ── 경로 강제 고정 (scheduler.py 위치 = 프로젝트 루트) ──
_FIXED_BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(_FIXED_BASE)

# sys.path 오염 방지: 바탕화면 복사본, OneDrive 등 외부 경로 차단
_blocked_paths = ['kr_market_package', 'OneDrive', '바탕 화면', 'desktop',
                  'korean market', 'crypto-analytics', 'us-market-pro']
sys.path = [p for p in sys.path if not any(b.lower() in p.lower() for b in _blocked_paths)]
sys.path.insert(0, _FIXED_BASE)

from dotenv import load_dotenv
_preserve_process_env = os.getenv('MARKETFLOW_PRESERVE_ENV', '').strip().lower() in {
    '1', 'true', 'yes', 'on',
}
load_dotenv(override=not _preserve_process_env)
import time
import logging
import subprocess
import signal as signal_module
import argparse
import atexit
from datetime import datetime, timedelta
import hashlib
import re
from pathlib import Path
from typing import Optional
import json
import threading
import uuid

# Windows 환경에서 콘솔 출력 인코딩 강제 설정
if sys.platform.startswith('win'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

# 파일 동시접근 보호
try:
    from app.utils.file_lock import safe_read
except ImportError:
    from contextlib import contextmanager
    @contextmanager
    def safe_read(filepath, timeout=10):
        yield filepath

# Atomic JSON writes (crash-safe)
try:
    from app.utils.atomic_json import write_json_atomic
except ImportError:
    def write_json_atomic(path, data, **kw):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=kw.get('indent', 2))

try:
    from app.utils.freshness import build_freshness, parse_datetime_value
except ImportError:
    build_freshness = None
    parse_datetime_value = None

# 로컬 Flask API base — 포트 드리프트 방지 (5001 → 5003 이전 대응)
try:
    from app.utils.local_api import local_api_base
except ImportError:
    def local_api_base():
        port = (os.getenv('FLASK_PORT') or '').strip() or '5003'
        return f'http://127.0.0.1:{port}'

# Process-level filelock
try:
    from filelock import FileLock, Timeout as FileLockTimeout
except ImportError:
    FileLock = None
    FileLockTimeout = None


def _kr_non_trading_override_enabled() -> bool:
    """Allow a manual KR-market run on holidays only when explicitly requested."""
    return os.environ.get('ALLOW_KR_NON_TRADING_RUN', '').strip().lower() in {
        '1', 'true', 'yes', 'y', 'on',
    }


def _is_kr_trading_day_for_scheduler(now: datetime | None = None) -> bool:
    """Return whether the current KST date is an actual KRX trading day."""
    current = now or datetime.now()
    try:
        from app.services.kis_screener import _is_kr_trading_day
        return bool(_is_kr_trading_day(current))
    except Exception as exc:
        logger.warning("KR trading-day check failed, weekday fallback used: %s", exc)
        return current.weekday() < 5


def _kr_market_task_allowed(task_name: str, now: datetime | None = None) -> bool:
    """Guard KR market jobs from running on KRX holidays/non-trading days."""
    current = now or datetime.now()
    if _kr_non_trading_override_enabled():
        logger.warning("KR non-trading override enabled; running %s", task_name)
        return True
    if _is_kr_trading_day_for_scheduler(current):
        return True
    logger.info(
        "KR market task skipped on non-trading day: %s (%s)",
        task_name,
        current.strftime('%Y-%m-%d %H:%M'),
    )
    return False

# 선택적 import (배포 시 설치 필요)
try:
    import schedule
except ImportError:
    print("❌ 'schedule' 패키지가 필요합니다: pip install schedule")
    sys.exit(1)


# ============================================================
# Scheduler-owned Git pull/push (explicit opt-in only)
# ============================================================
_git_lock = threading.Lock()
_GIT_SYNC_ENABLED_ENV = 'MARKETFLOW_SCHEDULER_GIT_SYNC_ENABLED'


def _scheduler_git_sync_enabled() -> bool:
    """Return whether scheduler-owned Git mutations were explicitly enabled."""
    return os.environ.get(_GIT_SYNC_ENABLED_ENV, '').strip().lower() in {
        '1', 'true', 'yes', 'y', 'on',
    }


def _sync_code_from_remote():
    """명시적으로 활성화된 경우에만 원격 코드 변경을 자동 반영한다.

    1시간마다 실행. 소스 코드 변경(scheduler.py, engine/ 등)을 원격에서 받아온다.
    데이터 충돌 방지: unstaged changes가 있으면 stash → pull → stash pop.
    실패해도 데몬은 계속 동작 (로그만 남김).
    """
    if not _scheduler_git_sync_enabled():
        logger.info(
            "Remote Git pull intentionally skipped; set %s=true to opt in",
            _GIT_SYNC_ENABLED_ENV,
        )
        return

    if not _git_lock.acquire(timeout=120):
        logger.warning("Git sync lock timeout; remote pull intentionally skipped")
        return
    try:
        _sync_code_from_remote_unlocked()
    finally:
        _git_lock.release()


def _sync_code_from_remote_unlocked():
    """Run the opted-in remote sync while the shared Git lock is held."""
    import subprocess
    project_dir = os.path.dirname(os.path.abspath(__file__))
    git_env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}

    try:
        # 현재 브랜치 확인
        branch = subprocess.run(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            capture_output=True, text=True, cwd=project_dir, timeout=10, env=git_env
        ).stdout.strip()
        if branch != 'main':
            return  # main이 아니면 스킵

        # fetch만 먼저 (네트워크 체크)
        fetch = subprocess.run(
            ['git', 'fetch', 'origin', 'main', '--quiet'],
            capture_output=True, text=True, cwd=project_dir, timeout=30, env=git_env
        )
        if fetch.returncode != 0:
            return  # 네트워크 불가 → 조용히 스킵

        # 원격과 차이 확인
        diff_check = subprocess.run(
            ['git', 'diff', 'HEAD', 'origin/main', '--stat'],
            capture_output=True, text=True, cwd=project_dir, timeout=10, env=git_env
        )
        if not diff_check.stdout.strip():
            return  # 차이 없음

        # unstaged changes stash
        status = subprocess.run(
            ['git', 'status', '--porcelain'],
            capture_output=True, text=True, cwd=project_dir, timeout=10, env=git_env
        ).stdout.strip()
        stashed = False
        if status:
            subprocess.run(
                ['git', 'stash', '--include-untracked'],
                capture_output=True, text=True, cwd=project_dir, timeout=30, env=git_env
            )
            stashed = True

        # pull
        pull = subprocess.run(
            ['git', 'pull', '--rebase', 'origin', 'main'],
            capture_output=True, text=True, cwd=project_dir, timeout=60, env=git_env
        )
        if pull.returncode != 0:
            # rebase 실패 시 abort + merge 전략
            subprocess.run(['git', 'rebase', '--abort'], cwd=project_dir, timeout=10,
                           capture_output=True, env=git_env)
            subprocess.run(['git', 'pull', '--no-rebase', 'origin', 'main'],
                           cwd=project_dir, timeout=60, capture_output=True, env=git_env)

        if stashed:
            subprocess.run(
                ['git', 'stash', 'pop'],
                capture_output=True, text=True, cwd=project_dir, timeout=30, env=git_env
            )

        logger.info("🔄 코드 동기화 완료 (git pull)")

    except Exception as e:
        logger.debug(f"코드 동기화 스킵: {e}")


def auto_git_push(scope: str = 'all') -> bool:
    """데이터 업데이트 후 자동 git commit + push (origin만)

    Args:
        scope: 'kr', 'us', 'crypto', 'all'
    Returns:
        True if push succeeded or the opt-in is disabled intentionally
    """
    if not _scheduler_git_sync_enabled():
        logger.info(
            "Auto Git push intentionally skipped (%s); set %s=true to opt in",
            scope,
            _GIT_SYNC_ENABLED_ENV,
        )
        return True

    import subprocess
    from datetime import datetime

    if not _git_lock.acquire(timeout=120):
        logger.warning("⚠️ Git push 잠금 대기 초과 (다른 push 진행 중)")
        return False
    try:
        project_dir = os.path.dirname(os.path.abspath(__file__))
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M')

        # Git subprocess용 환경변수 (cp949 인코딩 에러 방지)
        git_env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}

        try:
            result = subprocess.run(
                ['git', 'status', '--porcelain'],
                capture_output=True, text=True, cwd=project_dir, timeout=30,
                env=git_env, encoding='utf-8', errors='replace'
            )
            if result.returncode != 0:
                logger.warning("⚠️ Git 저장소가 아닙니다. auto_git_push 스킵.")
                return False

            changes = result.stdout.strip()
            if not changes:
                logger.info("📦 변경사항 없음, git push 스킵")
                return True

            # 데이터 디렉토리만 스테이징 (소스코드 제외 → GitHub Actions 충돌 방지)
            allowed_paths = [
                'data/vcp_crypto_latest.json',
                'data/vcp_kr_latest.json',
                'data/vcp_us_latest.json',
                'data/kiwoom_ai_theme_latest.json',
                'data/screener_leading_latest.json',
                'us_market/sector_cache.json',
                'us_market/output/',
                'crypto-analytics/crypto_market/output/',
            ]
            blocked_fragments = (
                'kis_token',
                'admin_mirofish',
                'uploads/community',
                'users.db',
                '.db-wal',
                '.db-shm',
            )
            for path in allowed_paths:
                normalized = path.replace('\\', '/')
                if any(fragment in normalized for fragment in blocked_fragments):
                    logger.warning("Blocked unsafe auto-git path: %s", normalized)
                    continue
                absolute_path = os.path.join(project_dir, path)
                if not os.path.exists(absolute_path):
                    continue
                subprocess.run(['git', 'add', path], cwd=project_dir, timeout=30,
                               capture_output=True, text=True, env=git_env)

            # 스테이징된 변경사항 확인
            staged = subprocess.run(
                ['git', 'diff', '--cached', '--quiet'],
                cwd=project_dir, timeout=10, capture_output=True, env=git_env
            )
            if staged.returncode == 0:
                logger.info("📦 데이터 변경사항 없음, git push 스킵")
                return True

            msg = f"auto: {scope} data update ({now_str})"
            subprocess.run(
                ['git', 'commit', '-m', msg],
                cwd=project_dir, timeout=30, check=True,
                capture_output=True, text=True, env=git_env
            )

            # unstaged changes를 stash → rebase → stash pop (rebase 실패 방지)
            stashed = False
            stash_check = subprocess.run(
                ['git', 'diff', '--quiet'],
                cwd=project_dir, timeout=10, capture_output=True, env=git_env
            )
            if stash_check.returncode != 0:
                subprocess.run(['git', 'stash', '--keep-index'],
                               cwd=project_dir, timeout=30, capture_output=True, text=True, env=git_env)
                stashed = True

            rebase_result = subprocess.run(
                ['git', 'pull', '--rebase', 'origin', 'main'],
                cwd=project_dir, timeout=120,
                capture_output=True, text=True, env=git_env
            )
            if rebase_result.returncode != 0:
                logger.error(f"⚠️ Git rebase 실패, abort 후 merge 전략 시도: {rebase_result.stderr}")
                subprocess.run(['git', 'rebase', '--abort'], cwd=project_dir, timeout=30,
                               capture_output=True, text=True, env=git_env)
                subprocess.run(['git', 'pull', '--no-rebase', 'origin', 'main'],
                               cwd=project_dir, timeout=120, capture_output=True, text=True, env=git_env)

            if stashed:
                subprocess.run(['git', 'stash', 'pop'],
                               cwd=project_dir, timeout=30, capture_output=True, text=True, env=git_env)

            push_result = subprocess.run(
                ['git', 'push', 'origin', 'main'],
                cwd=project_dir, timeout=120,
                capture_output=True, text=True, env=git_env
            )

            if push_result.returncode == 0:
                logger.info(f"✅ Git push (origin) 완료 ({scope})")
            else:
                logger.error(f"❌ Git push (origin) 실패: {push_result.stderr}")

            return push_result.returncode == 0

        except subprocess.TimeoutExpired:
            logger.error("❌ Git 명령 타임아웃")
            return False
        except Exception as e:
            logger.error(f"❌ auto_git_push 오류: {e}")
            return False
    finally:
        _git_lock.release()


# ============================================================
# 설정
# ============================================================

def _bounded_env_int(name: str, default: int, maximum: int) -> int:
    """Read one positive integer env while preserving an operational hard cap."""
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(1, min(maximum, value))

class Config:
    """통합 스케줄러 설정"""

    # 디렉토리 - 스크립트가 있는 디렉토리를 기본값으로 사용
    _SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    BASE_DIR = os.environ.get('KR_MARKET_DIR', _SCRIPT_DIR)
    LOG_DIR = os.environ.get('KR_MARKET_LOG_DIR', os.path.join(BASE_DIR, 'logs'))
    DATA_DIR = os.path.join(BASE_DIR, 'data')

    # Crypto 디렉토리
    CRYPTO_DIR = os.path.join(BASE_DIR, 'crypto-analytics')
    CRYPTO_MARKET_DIR = os.path.join(CRYPTO_DIR, 'crypto_market')
    CRYPTO_OUTPUT_DIR = os.path.join(CRYPTO_MARKET_DIR, 'output')

    # 스케줄
    SCHEDULE_ENABLED = os.environ.get('KR_MARKET_SCHEDULE_ENABLED', 'true').lower() == 'true'
    TZ = os.environ.get('KR_MARKET_TZ', 'Asia/Seoul')

    # 스케줄 시간 (KST)
    US_UPDATE_TIME = os.environ.get('US_MARKET_UPDATE_TIME', '04:00')
    US_TRACK_TIME = os.environ.get('US_MARKET_TRACK_TIME', '09:30')
    KR_UPDATE_TIME = os.environ.get('KR_MARKET_UPDATE_TIME', '14:50')   # 종가베팅 V2 (14:50 — 장 마감 직전 선제 분석)
    VCP_UPDATE_TIME = os.environ.get('VCP_UPDATE_TIME', '16:00')         # KR·US VCP 시그널
    KR_VCP_MORNING_TIME = os.environ.get('KR_VCP_MORNING_TIME', '11:00') # 평일 오전 KR VCP refresh (주말 후 stale 방지)
    WAVE_SCAN_TIME = os.environ.get('WAVE_SCAN_TIME', '16:30')           # Wave 패턴 스캔
    # ── Alpha Position Engine (알파캐치형 완결 신호) 타임라인 ──
    # 08:30 스코어 상위 / 15:00 마감 매매신호(진입+청산) / 18:00 성과 브리핑.
    # 장중 감시는 10분 간격 — 보유 포지션의 목표가/손절 터치 즉시 신호.
    ALPHA_MORNING_TIME = os.environ.get('ALPHA_MORNING_TIME', '08:30')
    ALPHA_CLOSE_TIME = os.environ.get('ALPHA_CLOSE_TIME', '15:00')
    ALPHA_BRIEF_TIME = os.environ.get('ALPHA_BRIEF_TIME', '18:00')
    ALPHA_INTRADAY_TIMES = [
        f'{h:02d}:{m:02d}' for h in range(9, 16) for m in (5, 15, 25, 35, 45, 55)
        if not (h == 15 and m > 25)
    ]

    # AI 매수 후보 선별 — 로컬 daily_prices.csv 를 쓰므로 14:50 KR 갱신 이후,
    # 그리고 16:00 VCP / 16:05 브리핑 / 16:30 Wave 와 겹치지 않는 시각으로 둔다.
    BUY_SCREEN_TIME = os.environ.get('BUY_SCREEN_TIME', '17:30')
    BUY_SCREEN_TARGET = _bounded_env_int('BUY_SCREEN_TARGET', 10, 10)
    BUY_SCREEN_BATCH = _bounded_env_int('BUY_SCREEN_BATCH', 20, 20)
    BUY_SCREEN_MAX_UNIVERSE = _bounded_env_int('BUY_SCREEN_MAX_UNIVERSE', 1200, 1200)
    BUY_SCREEN_VISION_MAX_CALLS = _bounded_env_int(
        'BUY_SCREEN_VISION_MAX_CALLS', 20, 20,
    )
    # 기본은 개인 봇만. 구독자 채널로 내보내려면 명시적으로 켠다.
    BUY_SCREEN_TO_CHANNEL = os.environ.get('BUY_SCREEN_TO_CHANNEL', 'false').lower() == 'true'
    AI_CHART_TIME = os.environ.get('AI_CHART_TIME', '14:00')             # AI Chart Analysis KR (Gemini Vision)
    US_AI_CHART_TIME = os.environ.get('US_AI_CHART_TIME', '04:30')       # AI Chart Analysis US (Gemini Vision) — 04:00 US 마켓갱신과 분리하여 리소스 경합 회피
    HISTORY_TIME = os.environ.get('KR_MARKET_HISTORY_TIME', '10:00')
    ALPHA_SCANNER_ENABLED = os.environ.get('ALPHA_SCANNER_ENABLED', 'true').lower() == 'true'
    ALPHA_SCANNER_TELEGRAM_ENABLED = os.environ.get('ALPHA_SCANNER_TELEGRAM_ENABLED', 'false').lower() == 'true'
    ALPHA_SCANNER_TIMES = [
        item.strip()
        for item in os.environ.get('ALPHA_SCANNER_TIMES', '09:20,11:20,14:20,15:40,16:10').split(',')
        if item.strip()
    ]
    LEADING_SCREENER_TIMES = [
        item.strip()
        for item in os.environ.get('LEADING_SCREENER_TIMES', '09:07,10:07,11:07,13:07,14:07,15:07,15:35').split(',')
        if item.strip()
    ]
    ALPHA_SCANNER_LIMIT = int(os.environ.get('ALPHA_SCANNER_LIMIT', '20'))
    ALPHA_SCANNER_MIN_ALPHA = float(os.environ.get('ALPHA_SCANNER_MIN_ALPHA', '70'))
    ALPHA_SCANNER_MAX_RISK = float(os.environ.get('ALPHA_SCANNER_MAX_RISK', '45'))
    ALPHA_SCANNER_MAX_EVENTS = int(os.environ.get('ALPHA_SCANNER_MAX_EVENTS', '8'))
    ALPHA_SCANNER_RETRY_SECONDS = int(os.environ.get('ALPHA_SCANNER_RETRY_SECONDS', '300'))
    ALPHA_SCANNER_MONITOR_INTERVAL_MINUTES = int(os.environ.get('ALPHA_SCANNER_MONITOR_INTERVAL_MINUTES', '5'))
    # ── AI Brain 서비스 가드 (2026-09-01 서비스화) ──
    AIBRAIN_GUARD_ENABLED = os.environ.get('AIBRAIN_GUARD_ENABLED', 'true').lower() == 'true'
    AIBRAIN_GUARD_INTERVAL_MINUTES = int(os.environ.get('AIBRAIN_GUARD_INTERVAL_MINUTES', '10'))
    AIBRAIN_PREWARM_TIMES = [
        t.strip() for t in os.environ.get('AIBRAIN_PREWARM_TIMES', '08:25,15:05').split(',') if t.strip()
    ]
    # The canonical alert is the default single report. Current-TopN is an
    # explicit operator opt-in follow-up and is never sent for no-new-event runs.
    ALPHA_SCANNER_CURRENT_TELEGRAM_ENABLED = os.environ.get('ALPHA_SCANNER_CURRENT_TELEGRAM_ENABLED', 'false').lower() == 'true'
    ALPHA_SCANNER_CURRENT_TELEGRAM_LIMIT = int(os.environ.get('ALPHA_SCANNER_CURRENT_TELEGRAM_LIMIT', '5'))
    ALPHA_SCANNER_CURRENT_TELEGRAM_MIN_INTERVAL_MINUTES = int(os.environ.get('ALPHA_SCANNER_CURRENT_TELEGRAM_MIN_INTERVAL_MINUTES', '120'))
    ALPHA_BACKTEST_ENABLED = os.environ.get('ALPHA_BACKTEST_ENABLED', 'true').lower() == 'true'
    ALPHA_BACKTEST_TIME = os.environ.get('ALPHA_BACKTEST_TIME', '23:00')
    ALPHA_BACKTEST_HORIZON_DAYS = int(os.environ.get('ALPHA_BACKTEST_HORIZON_DAYS', '5'))
    ALPHA_BACKTEST_LIMIT_RUNS = int(os.environ.get('ALPHA_BACKTEST_LIMIT_RUNS', '8000'))
    MIROFISH_AGENT_ENABLED = os.environ.get('MIROFISH_AGENT_ENABLED', 'true').lower() == 'true'
    MIROFISH_AGENT_EVENING_TIME = os.environ.get('MIROFISH_AGENT_EVENING_TIME', '16:30')
    MIROFISH_AGENT_NIGHT_TIME = os.environ.get('MIROFISH_AGENT_NIGHT_TIME', '23:30')
    MIROFISH_WORKFLOW_ENABLED = os.environ.get('MIROFISH_WORKFLOW_ENABLED', 'true').lower() == 'true'
    MIROFISH_WORKFLOW_MIN_ALPHA = float(os.environ.get('MIROFISH_WORKFLOW_MIN_ALPHA', '50'))
    MIROFISH_WORKFLOW_MAX_RISK = float(os.environ.get('MIROFISH_WORKFLOW_MAX_RISK', '65'))
    MIROFISH_WORKFLOW_ACTIONS = os.environ.get('MIROFISH_WORKFLOW_ACTIONS', 'BUY_CANDIDATE,WATCH')
    MIROFISH_WORKFLOW_AGENT_COUNT = int(os.environ.get('MIROFISH_WORKFLOW_AGENT_COUNT', '10'))
    MIROFISH_WORKFLOW_BATCH_SIZE = int(os.environ.get('MIROFISH_WORKFLOW_BATCH_SIZE', '5'))
    MIROFISH_WORKFLOW_TOP_N = int(os.environ.get('MIROFISH_WORKFLOW_TOP_N', '3'))
    MIROFISH_WORKFLOW_MAX_PARALLEL = int(os.environ.get('MIROFISH_WORKFLOW_MAX_PARALLEL', '3'))
    MIROFISH_WORKFLOW_ALLOW_STALE_SOURCES = os.environ.get('MIROFISH_WORKFLOW_ALLOW_STALE_SOURCES', 'false').lower() == 'true'
    # The automated dashboard must surface a complete ranked TOP N with each
    # CIO opinion (BUY/HOLD/SELL).  Alert quality remains visible in the
    # workflow summary instead of silently shrinking TOP 3 to BUY-only rows.
    MIROFISH_WORKFLOW_REQUIRE_BUY = os.environ.get('MIROFISH_WORKFLOW_REQUIRE_BUY', 'false').lower() == 'true'
    MIROFISH_WORKFLOW_TELEGRAM_ENABLED = os.environ.get('MIROFISH_WORKFLOW_TELEGRAM_ENABLED', 'false').lower() == 'true'
    MIROFISH_WORKFLOW_TELEGRAM_CHANNEL = os.environ.get('MIROFISH_WORKFLOW_TELEGRAM_CHANNEL', 'false').lower() == 'true'
    CRYPTO_TIMES = ['00:00', '04:00', '08:00', '12:00', '16:00', '20:00']  # 매 4시간
    MORNING_REPORT_TIME = os.environ.get('MORNING_REPORT_TIME', '09:00')   # 일별 상태 리포트
    MORNING_BRIEFING_TIME = os.environ.get('MORNING_BRIEFING_TIME', '09:05')  # AI 조간 브리핑
    CLOSING_BRIEFING_TIME = os.environ.get('CLOSING_BRIEFING_TIME', '16:05')  # AI 마감 브리핑
    # Claw 관측 outcome은 16:30 Wave/agent와 17:30 buy screen 사이에
    # 성숙한 거래세션만 멱등 갱신한다. 검출/발송에는 관여하지 않는다.
    OMNI_NEWS_ENABLED = os.environ.get('OMNI_NEWS_ENABLED', 'true').lower() == 'true'
    OMNI_NEWS_INTERVAL_MINUTES = int(os.environ.get('OMNI_NEWS_INTERVAL_MINUTES', '15'))
    CLAW_OUTCOME_ENABLED = os.environ.get('CLAW_OUTCOME_ENABLED', 'true').lower() == 'true'
    CLAW_OUTCOME_TIME = os.environ.get('CLAW_OUTCOME_TIME', '17:15')
    LOTTO_POST_TIME = os.environ.get('LOTTO_POST_TIME', '17:00')           # 금요일 AI 로또 분석

    # 타임아웃 (초)
    PRICE_TIMEOUT = int(os.environ.get('KR_MARKET_PRICE_TIMEOUT', '600'))
    INST_TIMEOUT = int(os.environ.get('KR_MARKET_INST_TIMEOUT', '600'))
    SIGNAL_TIMEOUT = int(os.environ.get('KR_MARKET_SIGNAL_TIMEOUT', '300'))
    HISTORY_TIMEOUT = int(os.environ.get('KR_MARKET_HISTORY_TIMEOUT', '900'))
    CRYPTO_TASK_TIMEOUT = int(os.environ.get('CRYPTO_MARKET_TASK_TIMEOUT', '600'))
    CRYPTO_BRIEFING_TIMEOUT = int(os.environ.get('CRYPTO_MARKET_BRIEFING_TIMEOUT', '300'))
    CRYPTO_PIPELINE_TIMEOUT = min(
        7200,
        max(60, int(os.environ.get('CRYPTO_PIPELINE_TIMEOUT_SECONDS', '3600'))),
    )
    CRYPTO_FAILURE_RETRY_MINUTES = min(
        240,
        max(5, int(os.environ.get('CRYPTO_FAILURE_RETRY_MINUTES', '60'))),
    )

    # Python 실행 경로 (가상환경 우선) — POSIX/Windows 양쪽 호환
    _VENV_PYTHON_WIN = os.path.join(_SCRIPT_DIR, '.venv', 'Scripts', 'python.exe')
    _VENV_PYTHON_POSIX = os.path.join(_SCRIPT_DIR, '.venv', 'bin', 'python')
    _VENV_PYTHON = _VENV_PYTHON_WIN if os.name == 'nt' else _VENV_PYTHON_POSIX
    PYTHON_PATH = os.environ.get(
        'KR_MARKET_PYTHON',
        _VENV_PYTHON if os.path.exists(_VENV_PYTHON) else sys.executable
    )

    @classmethod
    def ensure_dirs(cls):
        """필요한 디렉토리 생성"""
        Path(cls.LOG_DIR).mkdir(parents=True, exist_ok=True)
        Path(cls.DATA_DIR).mkdir(parents=True, exist_ok=True)
        Path(cls.CRYPTO_OUTPUT_DIR).mkdir(parents=True, exist_ok=True)


# ============================================================
# 로깅 설정
# ============================================================

def setup_logging():
    """로깅 설정 (RotatingFileHandler: 10MB × 5개 파일)"""
    from logging.handlers import RotatingFileHandler
    Config.ensure_dirs()

    log_file = os.environ.get('MARKETFLOW_SCHEDULER_LOG_FILE') or os.path.join(
        Config.LOG_DIR, 'scheduler.log'
    )
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    file_handler = RotatingFileHandler(
        log_file, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8'
    )
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

    logging.basicConfig(
        level=logging.INFO,
        handlers=[file_handler, stream_handler]
    )
    return logging.getLogger(__name__)


logger = setup_logging()


# ============================================================
# 공통 유틸리티
# ============================================================

def run_command(cmd: list, description: str, timeout: int = 600,
                notify: bool = False, env_extra: dict = None,
                cwd: str = None) -> bool:
    """명령 실행 헬퍼 (실시간 출력 스트리밍)

    Args:
        notify: True일 때만 텔레그램 알림 전송 (기본: False → 로그만)
        env_extra: 추가 환경변수 dict (기존 환경변수에 병합)
        cwd: 작업 디렉토리 (기본: Config.BASE_DIR)
    """
    logger.info(f"🚀 시작: {description}")
    start = time.time()

    try:
        # 환경변수 클린업: PYTHONPATH를 고정 경로만 사용, 외부 경로 제거
        clean_env = {k: v for k, v in os.environ.items()}
        clean_env['PYTHONPATH'] = Config.BASE_DIR
        clean_env['PYTHONIOENCODING'] = 'utf-8'
        # 바탕화면/OneDrive 경로가 PATH에 섞이지 않도록 보호
        env = clean_env
        if env_extra:
            env.update(env_extra)

        process = subprocess.Popen(
            cmd,
            cwd=cwd or Config.BASE_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace',
            env=env,
            bufsize=1
        )

        # 별도 스레드로 stdout 읽기 (hang 방지 — readline이 무한 대기해도 타임아웃 가능)
        import threading

        def _drain_stdout():
            try:
                for line in iter(process.stdout.readline, ''):
                    clean = line.strip()
                    if clean:
                        logger.info(f"   > {clean}")
            except Exception as e:
                logger.warning(f"⚠️ stdout 읽기 오류: {e}")
            finally:
                process.stdout.close()

        reader = threading.Thread(target=_drain_stdout, daemon=True)
        reader.start()

        process.wait(timeout=timeout)
        reader.join(timeout=5)  # stdout 스레드 정리 대기

        elapsed = time.time() - start

        if process.returncode == 0:
            logger.info(f"✅ 완료: {description} ({elapsed:.1f}초)")
            return True
        else:
            logger.error(f"❌ 실패: {description} (Exit Code: {process.returncode})")
            if notify:
                send_telegram(f"❌ 실패: {description} (Error Code: {process.returncode})", channel=False)
            return False

    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
        logger.error(f"⏰ 타임아웃: {description}")
        if notify:
            send_telegram(f"⏰ 타임아웃 발생: {description}", channel=False)
        return False
    except Exception as e:
        logger.error(f"❌ 에러: {description} - {e}")
        if notify:
            send_telegram(f"❌ 예외 발생: {description}\n{str(e)}", channel=False)
        return False


def _telegram_post(bot_token: str, chat_id: str, message: str, retries: int = 5,
                   label: str = "bot") -> bool:
    """텔레그램 단건 전송 (SSL EOF 대비 — 새 세션 + 지수 백오프 재시도).

    200 응답이어도 반드시 body.ok=true + result.message_id 까지 검증해야
    "진짜 전송 성공" 으로 인정한다. 과거 silent-drop (200 OK 이지만 실제
    메시지 미수신) 재발 시 탐지 가능.

    label: 로그 식별자 (예: "personal", "channel")
    """
    import requests
    from requests.adapters import HTTPAdapter
    for attempt in range(retries):
        try:
            # 매 시도마다 새 세션 (SSL 세션 캐시 오염 방지)
            session = requests.Session()
            adapter = HTTPAdapter(max_retries=0)
            session.mount('https://', adapter)
            r = session.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
                timeout=20
            )
            session.close()
            if r.status_code == 200:
                # 200 이어도 ok=true + message_id 까지 확인 (Telegram silent-drop 방어)
                try:
                    body = r.json()
                except Exception:
                    logger.warning(f"⚠️ [tg/{label}] HTTP 200 but non-JSON body: {r.text[:200]}")
                    body = {}
                if body.get("ok") is True:
                    msg_id = body.get("result", {}).get("message_id")
                    if msg_id:
                        logger.info(f"✅ [tg/{label}] sent msg_id={msg_id} chat={chat_id}")
                        return True
                    logger.warning(f"⚠️ [tg/{label}] ok=true but no message_id: {r.text[:200]}")
                else:
                    logger.warning(f"⚠️ [tg/{label}] HTTP 200 but ok=false: {r.text[:200]}")
                # 200 이지만 검증 실패 → 재시도 루프 계속
            else:
                logger.warning(f"⚠️ [tg/{label}] HTTP {r.status_code}: {r.text[:200]}")
        except Exception as e:
            if attempt < retries - 1:
                wait = 3 * (2 ** attempt)  # 3, 6, 12, 24초
                logger.debug(f"[tg/{label}] 재시도 {attempt+1}/{retries} ({wait}초 후): {e}")
                time.sleep(wait)
            else:
                logger.error(f"❌ [tg/{label}] 전송 실패 ({retries}회 시도): {e}")
    return False


# ── 텔레그램 실패 큐 (1시간 내 재전송) ──
_telegram_queue: list = []  # [(message, timestamp)]
_TELEGRAM_QUEUE_TTL = 3600  # 1시간 후 폐기


def _try_send_telegram(message: str, channel: bool = True) -> bool:
    """실제 전송 시도 — 봇별로 독립 추적.

    channel=True  → 개인 + 채널 양쪽 (분석 결과)
    channel=False → 개인 봇만 (시스템 메시지)

    반환: 필요한 대상 봇 **모두** 성공 시 True. 하나라도 실패하면 False 로
    상위 큐 저장 유도 (과거엔 한쪽만 성공해도 True → 실패 silent 무시).
    """
    targets: list[tuple[str, str, str]] = []   # [(label, token, chat_id)]

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if token and chat_id and "your_bot_token" not in token:
        targets.append(("personal", token, chat_id))

    if channel:
        ch_token = os.getenv("TELEGRAM_CHANNEL_BOT_TOKEN")
        ch_chat_id = os.getenv("TELEGRAM_CHANNEL_CHAT_ID")
        if ch_token and ch_chat_id:
            targets.append(("channel", ch_token, ch_chat_id))

    if not targets:
        logger.warning("⚠️ 텔레그램 전송 대상 봇 없음 (TOKEN/CHAT_ID 확인 필요)")
        return False

    all_ok = True
    for label, tok, cid in targets:
        if not _telegram_post(tok, cid, message, label=label):
            all_ok = False
            logger.warning(f"⚠️ [tg/{label}] 최종 실패 — 메시지 큐 저장 대상")
    return all_ok


def _flush_telegram_queue():
    """큐에 쌓인 실패 메시지 재전송 시도"""
    if not _telegram_queue:
        return
    now = time.time()
    sent_indices = []
    for i, (msg, ts) in enumerate(_telegram_queue):
        if now - ts > _TELEGRAM_QUEUE_TTL:
            sent_indices.append(i)  # 만료 — 폐기
            logger.warning(f"⚠️ 텔레그램 큐 메시지 만료 (1h): {msg[:50]}...")
            continue
        if _try_send_telegram(msg):
            sent_indices.append(i)
            logger.info(f"✅ 텔레그램 큐 재전송 성공: {msg[:50]}...")
        else:
            continue  # 네트워크 아직 안됨 — 이 메시지는 건너뛰고 나머지 시도
    for i in reversed(sent_indices):
        _telegram_queue.pop(i)


def send_telegram(message: str, channel: bool = True, *, queue_on_failure: bool = True) -> bool:
    """텔레그램 메시지 전송 (실패 시 큐 저장 + 이전 실패 재전송)
    channel=True  → 개인+채널 (분석 결과, 기본값)
    channel=False → 개인만 (시스템 메시지)
    queue_on_failure=False → 호출자가 자체 재시도/상태 관리를 할 때 큐 저장 생략
    """
    _flush_telegram_queue()

    success = _try_send_telegram(message, channel=channel)

    if not success and queue_on_failure:
        _telegram_queue.append((message, time.time()))
        logger.warning(f"⚠️ 텔레그램 전송 실패 → 큐 저장 (대기: {len(_telegram_queue)}건)")
    return success


def send_telegram_long(message: str, channel: bool = True) -> bool:
    """긴 텔레그램 메시지를 4000자 단위로 분할 전송"""
    MAX_LEN = 4000
    if len(message) <= MAX_LEN:
        return send_telegram(message, channel=channel)

    chunks = []
    current = ""
    for paragraph in message.split("\n\n"):
        if len(current) + len(paragraph) + 2 > MAX_LEN:
            if current:
                chunks.append(current.strip())
            current = paragraph
        else:
            current = current + "\n\n" + paragraph if current else paragraph
    if current.strip():
        chunks.append(current.strip())

    ok = True
    for chunk in chunks:
        if not send_telegram(chunk, channel=channel):
            ok = False
        time.sleep(0.5)
    return ok


def _alpha_current_summary_state_path() -> str:
    return os.path.join(
        Config.DATA_DIR,
        'admin_mirofish',
        'alpha_scanner_current_summary_state.json',
    )


def _load_alpha_current_summary_state(path: str | None = None) -> dict:
    state_path = path or _alpha_current_summary_state_path()
    if not os.path.isfile(state_path):
        return {}
    try:
        with safe_read(state_path):
            with open(state_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning(
            "MiroFish alpha scanner current summary state read failed: %s: %s",
            type(exc).__name__,
            exc,
        )
        return {}


def _parse_alpha_summary_dt(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed.replace(tzinfo=None)
    except Exception:
        return None


def _alpha_current_summary_fingerprint(run: dict, *, limit: int | None = None) -> str:
    clean_limit = max(1, int(limit or Config.ALPHA_SCANNER_CURRENT_TELEGRAM_LIMIT or 5))
    candidates = [item for item in (run.get('candidates') or []) if isinstance(item, dict)]
    parts = []
    for index, candidate in enumerate(candidates[:clean_limit], start=1):
        parts.append(':'.join([
            str(index),
            str(candidate.get('symbol') or ''),
            str(candidate.get('market') or ''),
            str(candidate.get('action') or ''),
            str(candidate.get('horizon') or ''),
        ]))
    basis = '|'.join(parts) or str(run.get('id') or '')
    return hashlib.sha1(basis.encode('utf-8')).hexdigest()


def _should_send_alpha_current_summary(run: dict, *, now: datetime | None = None) -> tuple[bool, dict]:
    if not Config.ALPHA_SCANNER_CURRENT_TELEGRAM_ENABLED:
        return False, {'reason': 'disabled'}
    candidates = [item for item in (run.get('candidates') or []) if isinstance(item, dict)]
    if not candidates:
        return False, {'reason': 'no_candidates'}

    current = now or datetime.now()
    limit = max(1, int(Config.ALPHA_SCANNER_CURRENT_TELEGRAM_LIMIT or 5))
    min_interval = max(0, int(Config.ALPHA_SCANNER_CURRENT_TELEGRAM_MIN_INTERVAL_MINUTES or 0))
    fingerprint = _alpha_current_summary_fingerprint(run, limit=limit)
    state = _load_alpha_current_summary_state()
    last_sent = _parse_alpha_summary_dt(state.get('last_sent_at'))
    last_fingerprint = str(state.get('last_fingerprint') or '')
    last_sent_date = str(state.get('last_sent_date') or '')
    today = current.date().isoformat()

    if last_sent is not None and min_interval > 0:
        age_minutes = (current - last_sent).total_seconds() / 60
        if age_minutes < min_interval:
            return False, {
                'reason': 'cooldown',
                'fingerprint': fingerprint,
                'age_minutes': round(age_minutes, 2),
                'min_interval_minutes': min_interval,
            }

    if fingerprint == last_fingerprint and last_sent_date == today:
        return False, {
            'reason': 'duplicate_today',
            'fingerprint': fingerprint,
            'min_interval_minutes': min_interval,
        }

    return True, {
        'reason': 'send',
        'fingerprint': fingerprint,
        'limit': limit,
        'min_interval_minutes': min_interval,
    }


def _record_alpha_current_summary_sent(run: dict, meta: dict, *, sent_at: datetime | None = None) -> None:
    current = sent_at or datetime.now()
    state_path = _alpha_current_summary_state_path()
    state = {
        'last_sent_at': current.isoformat(),
        'last_sent_date': current.date().isoformat(),
        'last_run_id': run.get('id'),
        'last_fingerprint': meta.get('fingerprint') or _alpha_current_summary_fingerprint(run),
        'limit': meta.get('limit') or Config.ALPHA_SCANNER_CURRENT_TELEGRAM_LIMIT,
        'min_interval_minutes': meta.get('min_interval_minutes') or Config.ALPHA_SCANNER_CURRENT_TELEGRAM_MIN_INTERVAL_MINUTES,
        'candidate_count': len([item for item in (run.get('candidates') or []) if isinstance(item, dict)]),
    }
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    write_json_atomic(state_path, state, sort_keys=True)


def run_alpha_scanner_monitor() -> bool:
    """Run the file-backed MiroFish scanner and Telegram only new events."""
    try:
        from app.services.mirofish.alpha_scanner import (
            build_scanner_run_telegram_message,
            run_scanner_realtime_monitor_check,
        )
        from app.services.mirofish.agent_actions import param_value

        min_alpha = Config.ALPHA_SCANNER_MIN_ALPHA
        if os.environ.get('ALPHA_SCANNER_MIN_ALPHA') is None:
            min_alpha = param_value('min_alpha', min_alpha)
        max_risk = Config.ALPHA_SCANNER_MAX_RISK
        if os.environ.get('ALPHA_SCANNER_MAX_RISK') is None:
            max_risk = param_value('max_risk', max_risk)

        result = run_scanner_realtime_monitor_check(
            {'limit': Config.ALPHA_SCANNER_LIMIT},
            min_alpha=min_alpha,
            max_risk=max_risk,
            max_events=Config.ALPHA_SCANNER_MAX_EVENTS,
            retry_seconds=Config.ALPHA_SCANNER_RETRY_SECONDS,
            send_fn=(
                (lambda message: send_telegram_long(message, channel=False))
                if Config.ALPHA_SCANNER_TELEGRAM_ENABLED
                else None
            ),
        )
        status = result.get('status')
        run = result.get('run') or {}
        if (
            Config.ALPHA_SCANNER_TELEGRAM_ENABLED
            and Config.ALPHA_SCANNER_CURRENT_TELEGRAM_ENABLED
            and status == 'sent'
            and (run.get('candidates') or [])
        ):
            try:
                should_send_summary, summary_meta = _should_send_alpha_current_summary(run)
                if should_send_summary:
                    summary_message = build_scanner_run_telegram_message(
                        run,
                        limit=Config.ALPHA_SCANNER_CURRENT_TELEGRAM_LIMIT,
                    )
                    summary_sent = send_telegram_long(summary_message, channel=False)
                    if summary_sent:
                        _record_alpha_current_summary_sent(run, summary_meta)
                        logger.info(
                            "MiroFish alpha scanner current Top%s summary sent: run=%s",
                            Config.ALPHA_SCANNER_CURRENT_TELEGRAM_LIMIT,
                            run.get('id'),
                        )
                    else:
                        logger.warning(
                            "MiroFish alpha scanner current Top%s summary send failed: run=%s",
                            Config.ALPHA_SCANNER_CURRENT_TELEGRAM_LIMIT,
                            run.get('id'),
                        )
                else:
                    logger.info(
                        "MiroFish alpha scanner current Top%s summary skipped: reason=%s run=%s",
                        Config.ALPHA_SCANNER_CURRENT_TELEGRAM_LIMIT,
                        summary_meta.get('reason'),
                        run.get('id'),
                    )
            except Exception as summary_exc:
                logger.warning(
                    "MiroFish alpha scanner current candidate summary failed: %s: %s",
                    type(summary_exc).__name__,
                    summary_exc,
                    exc_info=True,
                )
        if status == 'sent':
            logger.info(
                "MiroFish alpha scanner alert sent: %s new events, run=%s",
                result.get('new_event_count'),
                run.get('id'),
            )
            return True
        if status == 'send_failed':
            logger.warning(
                "MiroFish alpha scanner alert send failed; state not committed, run=%s",
                run.get('id'),
            )
            return False
        if status == 'retry_wait':
            logger.warning(
                "MiroFish alpha scanner retry wait: previous send failure still cooling down"
            )
            return True
        if status == 'unchanged':
            logger.info("MiroFish alpha scanner: source unchanged, scan skipped")
            return True
        if status == 'blocked':
            logger.warning(
                "MiroFish alpha scanner alert blocked: %s",
                result.get('blocked_reason'),
            )
            return True

        logger.info(
            "MiroFish alpha scanner: %s, candidates=%s, run=%s",
            status or 'no_new_events',
            run.get('candidate_count'),
            run.get('id'),
        )
        return status in {'no_new_events', 'blocked', 'pending_send'}
    except Exception as e:
        logger.error(f"MiroFish alpha scanner monitor failed: {e}", exc_info=True)
        if Config.ALPHA_SCANNER_TELEGRAM_ENABLED:
            try:
                send_telegram(
                    f"MiroFish alpha scanner failed\n{type(e).__name__}: {e}",
                    channel=False,
                )
            except Exception:
                pass
        return False


def run_aibrain_service_guard() -> bool:
    """AI Brain 3대 서비스(스캐너·펀드매니저·판단) 지속성 가드 — 실패 진입 시 개인봇 알림."""
    try:
        from app.services.mirofish import service_guard
        result = service_guard.run_guard(
            send_fn=lambda msg: send_telegram(msg, channel=False, queue_on_failure=False)
        )
        if result.get('overall') != 'ok':
            logger.warning("AI Brain service guard: overall=%s statuses=%s",
                           result.get('overall'),
                           {k: v.get('status') for k, v in (result.get('services') or {}).items()})
        return True
    except Exception as e:
        logger.error(f"AI Brain service guard failed: {e}", exc_info=True)
        return False


def run_aibrain_prewarm() -> bool:
    """판단 캐시 프리웜 — 구독자의 '첫 조회 수십 초'를 백그라운드에서 미리 치운다."""
    try:
        from app.services.mirofish import service_guard
        result = service_guard.prewarm_decision_cache()
        logger.info("AI Brain decision prewarm: warmed=%s skipped=%s errors=%s",
                    len(result.get('warmed') or []), len(result.get('skipped') or []),
                    len(result.get('errors') or {}))
        return True
    except Exception as e:
        logger.error(f"AI Brain decision prewarm failed: {e}", exc_info=True)
        return False


def _valid_hhmm_times(raw_times, env_label: str) -> list:
    """env 시각 목록에서 'HH:MM' 형식만 통과시킨다 (잘못된 항목은 스킵 + 로그).

    검증 없이 `schedule.every().day.at(hm)` 에 넘기면 '8:25' 같은 항목 하나가
    setup_schedules() 에서 ScheduleValueError 로 데몬 전체를 죽이고,
    워치독이 5분마다 재기동하는 영구 크래시 루프가 된다.
    """
    valid = []
    for hm in raw_times or []:
        hm = str(hm).strip()
        if re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', hm):
            valid.append(hm)
        else:
            logger.error(f"⚠️ {env_label}: 잘못된 시각 형식 무시 — '{hm}' (HH:MM 형식 필요, 예: 08:25)")
    return valid


def run_leading_screener_refresh():
    """Refresh KIS leading-stock screener and persist only real non-empty results."""
    try:
        from app.services.kis_screener import run_screening

        result = run_screening(force=True)
        quality = (result or {}).get('data_quality')
        if isinstance(quality, dict) and quality.get('safe_to_replace_latest') is False:
            logger.warning(
                "leading_screener refresh rejected by quality gate: "
                "status=%s coverage=%s unresolved=%s missing_sources=%s",
                quality.get('status'),
                quality.get('resolved_candidate_coverage'),
                quality.get('unresolved_potential_codes'),
                quality.get('missing_sources'),
            )
            return False
        count = len((result or {}).get('results') or [])
        if count <= 0:
            source_counts = (result or {}).get('source_counts') or {}
            upstream_count = sum(int(v or 0) for v in source_counts.values())
            empty_reason = (result or {}).get('empty_reason')
            if not (result or {}).get('error') and upstream_count > 0 and empty_reason == 'below_grade_threshold':
                logger.info(
                    "leading_screener refresh no candidates after filters: "
                    "source_counts=%s status=%s filter_summary=%s",
                    source_counts,
                    (result or {}).get('market_status'),
                    (result or {}).get('filter_summary'),
                )
                return {
                    'ok': True,
                    'status': 'no_candidates',
                    'empty_reason': empty_reason,
                    '_scheduler_skip_verify': True,
                }
            logger.warning(
                "leading_screener refresh empty: error=%s source_counts=%s status=%s",
                (result or {}).get('error'),
                source_counts,
                (result or {}).get('market_status'),
            )
            return False

        logger.info(
            "leading_screener refresh ok: count=%s by_grade=%s status=%s source_counts=%s",
            count,
            result.get('by_grade'),
            result.get('market_status'),
            result.get('source_counts'),
        )
        return True
    except Exception as e:
        logger.error("leading_screener refresh failed: %s: %s", type(e).__name__, e, exc_info=True)
        return False


def run_alpha_backtest_daily() -> bool:
    """Run the daily Plan A alpha-scanner backtest report."""
    script = os.path.join(Config.BASE_DIR, 'scripts', 'backtest_alpha_signals.py')
    output = os.path.join(Config.DATA_DIR, 'admin_mirofish', 'alpha_backtest_daily.json')
    rolling_output = os.path.join(Config.DATA_DIR, 'admin_mirofish', 'alpha_backtest_rolling_7d.json')
    if not os.path.isfile(script):
        logger.error("Alpha backtest script not found: %s", script)
        return False
    cmd = [
        Config.PYTHON_PATH,
        script,
        '--output',
        output,
        '--rolling-output',
        rolling_output,
        '--horizon-days',
        str(Config.ALPHA_BACKTEST_HORIZON_DAYS),
        '--limit-runs',
        str(Config.ALPHA_BACKTEST_LIMIT_RUNS),
    ]
    try:
        result = subprocess.run(
            cmd,
            cwd=Config.BASE_DIR,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=300,
        )
    except Exception as exc:
        logger.error("Alpha backtest execution failed: %s", exc, exc_info=True)
        return False
    if result.returncode != 0:
        logger.error("Alpha backtest failed rc=%s stderr=%s", result.returncode, result.stderr[-1000:])
        return False
    logger.info("Alpha backtest completed: %s", (result.stdout or '').strip())
    return os.path.isfile(output) and os.path.isfile(rolling_output)


def _run_alpha_brain_agent(cycle: str) -> bool:
    """Run one Alpha Brain Agent cycle through the trusted in-process path."""
    try:
        from app.services.mirofish import alpha_brain_agent

        result = alpha_brain_agent.run_agent_cycle(cycle)
        status = result.get('status')
        logger.info("Alpha brain agent cycle=%s status=%s", cycle, status)
        return status in {'completed', 'skipped_circuit_open'}
    except Exception as exc:
        logger.error("Alpha brain agent cycle failed: %s", exc, exc_info=True)
        return False


def run_alpha_brain_agent_evening() -> bool:
    return _run_alpha_brain_agent('evening')


def run_alpha_brain_agent_night() -> bool:
    return _run_alpha_brain_agent('post_backtest')


def run_mirofish_workflow_monitor() -> bool:
    """Run scanner-event -> GraphRAG batch -> Top 3 workflow when new events appear."""
    try:
        from app.services.mirofish.workflow import (
            build_workflow_top3_telegram_message,
            commit_workflow_event_state,
            run_workflow_monitor_check,
        )
        from app.services.mirofish import alpha_scanner as alpha_scanner_service

        result = run_workflow_monitor_check({
            'limit': Config.ALPHA_SCANNER_LIMIT,
            'min_alpha': Config.MIROFISH_WORKFLOW_MIN_ALPHA,
            'max_risk': Config.MIROFISH_WORKFLOW_MAX_RISK,
            'actions': Config.MIROFISH_WORKFLOW_ACTIONS,
            'max_events': Config.MIROFISH_WORKFLOW_BATCH_SIZE,
            'agent_count': Config.MIROFISH_WORKFLOW_AGENT_COUNT,
            'top_n': Config.MIROFISH_WORKFLOW_TOP_N,
            'require_buy': Config.MIROFISH_WORKFLOW_REQUIRE_BUY,
            'max_parallel': Config.MIROFISH_WORKFLOW_MAX_PARALLEL,
            'allow_stale_sources': Config.MIROFISH_WORKFLOW_ALLOW_STALE_SOURCES,
            'mode': 'full',
            'sync': True,
            'commit_event_state': False,
        })
        status = result.get('status')
        if status == 'completed':
            top3 = result.get('top3') or []
            if Config.MIROFISH_WORKFLOW_TELEGRAM_ENABLED and top3:
                message = build_workflow_top3_telegram_message(result)
                with alpha_scanner_service.scanner_alert_delivery_guard():
                    event_candidates = result.get('event_candidates')
                    if not isinstance(event_candidates, list):
                        event_candidates = result.get('candidates')
                    delivery_check = alpha_scanner_service.revalidate_scanner_alert_delivery(
                        [item for item in (event_candidates or []) if isinstance(item, dict)],
                    )
                    result['canonical_delivery_check'] = delivery_check
                    if not delivery_check.get('ok'):
                        reason = str(delivery_check.get('status') or 'delivery_revalidation_failed')
                        result['telegram_sent'] = False
                        result['telegram_skipped_reason'] = reason
                        if reason == 'event_overlap':
                            commit_workflow_event_state(result, sync_dashboard=False)
                            logger.info(
                                "MiroFish MCP workflow Telegram skipped on canonical overlap: workflow=%s",
                                result.get('id'),
                            )
                            return True
                        logger.warning(
                            "MiroFish MCP workflow delivery revalidation failed: workflow=%s reason=%s",
                            result.get('id'),
                            reason,
                        )
                        return False
                    sent = send_telegram_long(
                        message,
                        channel=Config.MIROFISH_WORKFLOW_TELEGRAM_CHANNEL,
                    )
                    if not sent:
                        logger.warning(
                            "MiroFish MCP workflow Telegram failed; event state not committed, workflow=%s",
                            result.get('id'),
                        )
                        return False
                    result['telegram_sent'] = True
                    result['telegram_sent_at'] = datetime.now().isoformat()
                    commit_workflow_event_state(result)
                    logger.info(
                        "MiroFish MCP workflow Top %s Telegram sent: workflow=%s scanner=%s",
                        len(top3),
                        result.get('id'),
                        result.get('scanner_run_id'),
                    )
            else:
                result['telegram_sent'] = False
                result['telegram_skipped_reason'] = (
                    'disabled' if not Config.MIROFISH_WORKFLOW_TELEGRAM_ENABLED else 'no_top3'
                )
                commit_workflow_event_state(result, sync_dashboard=False)
            return True
        if status in {'queued', 'running'}:
            logger.info(
                "MiroFish MCP workflow started: workflow=%s candidates=%s scanner=%s",
                result.get('id'),
                result.get('event_count'),
                result.get('scanner_run_id'),
            )
            return True
        if status == 'no_new_events':
            logger.info("MiroFish MCP workflow: no new scanner events")
            return True
        if status == 'blocked':
            logger.warning("MiroFish MCP workflow blocked: %s", result.get('blocked_reason'))
            return True
        logger.info("MiroFish MCP workflow status=%s", status)
        return bool(result.get('ok'))
    except Exception as e:
        logger.error(f"MiroFish MCP workflow monitor failed: {e}", exc_info=True)
        if Config.MIROFISH_WORKFLOW_TELEGRAM_ENABLED:
            try:
                send_telegram(
                    f"MiroFish MCP workflow failed\n{type(e).__name__}: {e}",
                    channel=False,
                )
            except Exception:
                pass
        return False


# ============================================================
# [KR Market] 작업 함수들
# ============================================================

def _with_benchmark_tickers(tickers, names_map):
    """Ensure the index proxies are collected alongside ordinary listings.

    fdr.StockListing('KRX') returns stocks only, so without this the benchmark
    ETFs never enter daily_prices.csv and excess return stays unmeasurable.
    """
    from app.services.mirofish.goodrich_ledger import BENCHMARK_TICKERS

    tickers = list(tickers)
    names_map = dict(names_map)
    for code, label in BENCHMARK_TICKERS.items():
        if code not in names_map:
            tickers.append(code)
        names_map.setdefault(code, label)
    return tickers, names_map


def update_daily_prices():
    """일별 가격 데이터 업데이트 — FDR listing + pykrx OHLCV 수집 (벤치마크 ETF 포함)"""
    import pandas as pd
    from datetime import timedelta
    csv_path = os.path.join(Config.DATA_DIR, 'daily_prices.csv')

    # 기존 CSV에서 마지막 날짜 확인
    last_date = None
    if os.path.exists(csv_path):
        try:
            existing = pd.read_csv(csv_path, usecols=['date'], dtype={'date': str})
            if len(existing) > 0:
                last_date = existing['date'].max()
                logger.info(f"📊 daily_prices.csv 마지막 날짜: {last_date}")
        except Exception as e:
            logger.warning(f"기존 CSV 읽기 실패: {e}")

    # 시작일 결정
    if last_date:
        try:
            start_dt = datetime.strptime(last_date, '%Y-%m-%d') + timedelta(days=1)
        except ValueError:
            start_dt = datetime.now() - timedelta(days=60)
    else:
        start_dt = datetime.now() - timedelta(days=60)

    end_dt = datetime.now()
    if start_dt.date() > end_dt.date():
        logger.info("📊 daily_prices.csv 이미 최신")
        return True

    start_str = start_dt.strftime('%Y%m%d')
    end_str = end_dt.strftime('%Y%m%d')
    logger.info(f"📊 KR 가격 수집 시작: {start_str} → {end_str}")
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    all_rows = []

    # FDR로 종목 목록 가져오기 (pykrx ticker_list가 불안정)
    try:
        import FinanceDataReader as fdr
        listing = fdr.StockListing('KRX')
        tickers = listing['Code'].tolist()
        names_map = dict(zip(listing['Code'], listing['Name']))
        tickers, names_map = _with_benchmark_tickers(tickers, names_map)
        logger.info(f"📊 FDR 종목 목록: {len(tickers)}개 (벤치마크 ETF 포함)")
    except Exception as e:
        logger.error(f"FDR 종목 목록 실패: {e}")
        return False

    # FDR로 OHLCV 수집 (pykrx는 pandas 3.x 호환 문제로 폴백만)
    failed = 0
    for i, ticker in enumerate(tickers):
        try:
            df = fdr.DataReader(ticker, start_dt.strftime('%Y-%m-%d'), end_dt.strftime('%Y-%m-%d'))
            if df is None or df.empty:
                continue
            for date_idx, row in df.iterrows():
                chg = row.get('Change', 0) or 0
                all_rows.append({
                    'ticker': ticker,
                    'date': date_idx.strftime('%Y-%m-%d'),
                    'name': names_map.get(ticker, ''),
                    'current_price': float(row.get('Close', 0)),
                    'change': float(chg),
                    'change_rate': float(chg) * 100,
                    'high': float(row.get('High', 0)),
                    'low': float(row.get('Low', 0)),
                    'open': float(row.get('Open', 0)),
                    'volume': int(row.get('Volume', 0)),
                    'update_time': now_str,
                })
        except Exception as e:
            logger.warning(f"⚠️ 종목 {ticker} 데이터 수집 실패: {e}")
            failed += 1
            continue
        if (i + 1) % 500 == 0:
            logger.info(f"  진행: {i+1}/{len(tickers)} ({len(all_rows)} rows, {failed} failed)")

    logger.info(f"📊 수집 완료: {len(all_rows)} rows ({failed} 실패)")

    if not all_rows:
        logger.warning("📊 수집된 데이터 없음")
        return False

    # CSV에 추가 (append) 또는 생성
    new_df = pd.DataFrame(all_rows)
    if os.path.exists(csv_path) and last_date:
        new_df.to_csv(csv_path, mode='a', header=False, index=False, encoding='utf-8-sig')
        logger.info(f"✅ daily_prices.csv 추가: {len(all_rows)} rows")
    else:
        new_df.to_csv(csv_path, index=False, encoding='utf-8-sig')
        logger.info(f"✅ daily_prices.csv 생성: {len(all_rows)} rows")

    return True


def update_institutional_data():
    """수급 데이터 업데이트"""
    script_path = os.path.join(Config.BASE_DIR, 'all_institutional_trend_data.py')
    return run_command(
        [Config.PYTHON_PATH, script_path],
        'KR 외인/기관 수급 데이터 업데이트',
        timeout=Config.INST_TIMEOUT,
        env_extra={'DATA_DIR': Config.DATA_DIR}
    )


def run_vcp_signal_scan(send_alert: bool = False):
    """VCP 시그널 스캔"""
    success = run_command(
        [Config.PYTHON_PATH, '-m', 'signal_tracker'],
        'KR VCP + 외인매집 시그널 스캔',
        timeout=Config.SIGNAL_TIMEOUT
    )
    if success and send_alert:
        try:
            send_vcp_telegram_summary()
        except Exception as e:
            logger.error(f"❌ VCP 텔레그램 전송 실패: {e}")
    return success


def send_vcp_telegram_summary():
    """VCP 시그널 상위 10개 텔레그램 전송 (vcp_kr_latest.json 기반)"""

    json_path = os.path.join(Config.DATA_DIR, 'vcp_kr_latest.json')
    if not os.path.exists(json_path):
        logger.warning("⚠️ vcp_kr_latest.json이 없어 VCP 알림을 건너뜁니다.")
        return

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"❌ VCP JSON 로드 실패: {e}")
        return

    signals = data.get('signals', [])
    if not signals:
        logger.info("📭 VCP 시그널이 없습니다.")
        return

    # composite_score 기준 정렬
    signals.sort(key=lambda s: s.get('composite', {}).get('composite_score', 0)
                 if isinstance(s.get('composite'), dict)
                 else 0, reverse=True)

    total = len(signals)
    top_10 = signals[:10]
    gate = data.get('metadata', {}).get('gate', '?')
    gate_score = data.get('metadata', {}).get('gate_score', '?')

    today = datetime.now().strftime('%m/%d')
    msg = f"<b>📈 VCP 시그널 Top 10 ({today})</b>\n"
    msg += f"총 {total}개 종목 | Gate: {gate} ({gate_score})\n"
    msg += "────────────────────\n"

    for i, s in enumerate(top_10, 1):
        symbol = s.get('symbol', '?')
        name = s.get('name', symbol)
        comp = s.get('composite', {})
        score = comp.get('composite_score', 0) if isinstance(comp, dict) else 0
        # price 는 float (dict 아님)
        price = s.get('price', 0)
        if isinstance(price, dict):
            close = price.get('close', 0)
            change = price.get('change_pct', 0)
        else:
            close = float(price) if price else 0
            change = 0

        # 패턴 정보
        trend = s.get('trend_template', {})
        tt_pass = str(trend.get('passed', False)).lower() == 'true' if isinstance(trend, dict) else False
        vcp = s.get('vcp_pattern', {})
        vcp_pass = str(vcp.get('valid_vcp', False)).lower() == 'true' if isinstance(vcp, dict) else False

        icons = []
        if tt_pass:
            icons.append("📊")
        if vcp_pass:
            icons.append("🔺")
        icon_str = ' '.join(icons)

        msg += f"\n{i}. <b>{name}</b> ({symbol}) {icon_str}\n"
        msg += f"   점수: {score:.1f} | {close:,.0f}원\n"

    send_telegram(msg)


def collect_historical_institutional():
    """과거 수급 데이터 수집 (히스토리 축적용)"""
    module_path = os.path.join(Config.BASE_DIR, 'collect_historical_data.py')
    if not os.path.exists(module_path):
        logger.warning("⚠️ collect_historical_data.py 없음 — 히스토리 수집 스킵")
        return True
    script = (
        "from collect_historical_data import HistoricalInstitutionalCollector; "
        "import os; "
        "collector = HistoricalInstitutionalCollector(data_dir=os.environ['DATA_DIR']); "
        "df = collector.collect_all(max_stocks=None, max_workers=15); "
        "df.empty or collector.generate_signals_from_history(lookback_days=5); "
        "print(f'수집 완료: {len(df)}개 레코드')"
    )
    return run_command(
        [Config.PYTHON_PATH, '-c', script],
        'KR 과거 수급 히스토리 수집',
        timeout=Config.HISTORY_TIMEOUT,
        env_extra={'DATA_DIR': Config.DATA_DIR}
    )


def run_ai_analysis_scan():
    """AI 분석 JSON 생성 (kr_ai_analysis.json) — vcp_kr_latest.json 기반"""
    logger.info("🤖 AI 분석 JSON 생성 중 (vcp_kr_latest.json → kr_ai_analysis.json)...")
    try:
        vcp_path = os.path.join(Config.DATA_DIR, 'vcp_kr_latest.json')
        if not os.path.exists(vcp_path):
            logger.warning("⚠️ vcp_kr_latest.json이 없어 AI 분석을 건너뜁니다.")
            return True

        with open(vcp_path, 'r', encoding='utf-8') as f:
            vcp_data = json.load(f)

        vcp_signals = vcp_data.get('signals', [])
        if not vcp_signals:
            logger.info("분석할 VCP 시그널이 없습니다.")
            return True

        # 점수 상위 정렬 + 상위 20개
        vcp_signals.sort(
            key=lambda s: s.get('composite', {}).get('score', 0)
            if isinstance(s.get('composite'), dict) else 0,
            reverse=True
        )

        signals = []
        seen_tickers = set()
        for s in vcp_signals:
            ticker = str(s.get('symbol', '')).zfill(6)
            if ticker in seen_tickers:
                continue
            seen_tickers.add(ticker)

            comp = s.get('composite', {}) if isinstance(s.get('composite'), dict) else {}
            price = s.get('price', {}) if isinstance(s.get('price'), dict) else {}
            signals.append({
                'ticker': ticker,
                'name': s.get('name', ticker),
                'score': float(comp.get('score', 0)),
                'contraction_ratio': 0,
                'foreign_5d': 0,
                'inst_5d': 0,
                'entry_price': float(price.get('close', 0)),
                'current_price': float(price.get('close', 0)),
                'return_pct': 0,
                'signal_date': vcp_data.get('metadata', {}).get('generated_at', '')[:10],
                'market': '',
                'status': 'OPEN'
            })

        target_signals = signals[:20]

        result = {
            'market_indices': {},
            'signals': target_signals,
            'api_status': 'ok',
            'generated_at': datetime.now().isoformat(),
            'signal_date': datetime.now().strftime('%Y-%m-%d')
        }

        json_path = os.path.join(Config.DATA_DIR, 'kr_ai_analysis.json')
        write_json_atomic(json_path, result)

        today_str = datetime.now().strftime('%Y%m%d')
        history_dir = os.path.join(Config.DATA_DIR, 'history')
        os.makedirs(history_dir, exist_ok=True)
        history_path = os.path.join(history_dir, f'kr_ai_analysis_{today_str}.json')

        write_json_atomic(history_path, result)

        logger.info(f"✅ AI 분석 JSON 저장 완료: {len(target_signals)}개 시그널 → {json_path}")
        return True

    except Exception as e:
        logger.error(f"❌ AI 분석 실패: {e}")
        return False


def generate_daily_report():
    """일일 리포트 생성 (vcp_kr_latest.json 기반)"""
    logger.info("📊 일일 리포트 생성 중...")
    try:
        vcp_path = os.path.join(Config.DATA_DIR, 'vcp_kr_latest.json')
        today = datetime.now().strftime('%Y-%m-%d')

        total_signals = 0
        if os.path.exists(vcp_path):
            with open(vcp_path, 'r', encoding='utf-8') as f:
                vcp_data = json.load(f)
            total_signals = len(vcp_data.get('signals', []))

        report = {
            'date': today,
            'open_signals': total_signals,
            'closed_signals': 0,
            'today_new_signals': total_signals,
            'total_signals': total_signals,
            'generated_at': datetime.now().isoformat(),
            'env': {'base_dir': Config.BASE_DIR, 'python': Config.PYTHON_PATH}
        }

        report_path = os.path.join(Config.DATA_DIR, 'daily_report.json')
        write_json_atomic(report_path, report)

        logger.info(f"✅ 일일 리포트: VCP 시그널 {total_signals}개")
        return True

    except Exception as e:
        logger.error(f"❌ 리포트 생성 실패: {e}")
        return False



def send_morning_status_report():
    """매일 09:00 KST — 전날/당일 시스템 상태 텔레그램 요약"""
    logger.info("📋 아침 상태 리포트 전송 중...")
    try:
        from datetime import datetime, timedelta
        today = datetime.now().strftime('%Y-%m-%d')
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

        lines = [f"<b>📋 MarketFlow 일별 리포트</b>  ({today})"]
        lines.append("")

        # ── KR 종가베팅 ──
        jongga_path = os.path.join(Config.DATA_DIR, 'jongga_v2_latest.json')
        if os.path.exists(jongga_path):
            with open(jongga_path, 'r', encoding='utf-8') as f:
                d = json.load(f)
            sig_date = d.get('date', '')[:10]
            signals = d.get('signals', [])
            by_grade = d.get('by_grade', {})
            grade_str = ' '.join(f"{g}:{c}" for g, c in sorted(by_grade.items()) if c > 0) if by_grade else f"{len(signals)}종목"
            freshness = "✅" if sig_date >= yesterday else "⚠️"
            lines.append(f"{freshness} <b>KR 종가베팅</b>: {len(signals)}시그널 ({grade_str})")
            lines.append(f"   └ 기준일: {sig_date}")
        else:
            lines.append("❌ <b>KR 종가베팅</b>: 데이터 없음")

        # ── KR VCP ──
        vcp_kr_path = os.path.join(Config.DATA_DIR, 'vcp_kr_latest.json')
        if os.path.exists(vcp_kr_path):
            with open(vcp_kr_path, 'r', encoding='utf-8') as f:
                d = json.load(f)
            meta = d.get('metadata', {})
            gen_at = meta.get('generated_at', '')[:16].replace('T', ' ')
            vcp_count = d.get('summary', {}).get('vcp_found', len(d.get('signals', [])))
            entry_ready = d.get('summary', {}).get('entry_ready', 0)
            freshness = "✅" if gen_at[:10] >= yesterday else "⚠️"
            lines.append(f"{freshness} <b>KR VCP</b>: {vcp_count}종목 (진입대기 {entry_ready})")
            lines.append(f"   └ 갱신: {gen_at}")
        else:
            lines.append("❌ <b>KR VCP</b>: 데이터 없음")

        # ── US VCP ──
        vcp_us_path = os.path.join(Config.DATA_DIR, 'vcp_us_latest.json')
        if os.path.exists(vcp_us_path):
            with open(vcp_us_path, 'r', encoding='utf-8') as f:
                d = json.load(f)
            vcp_count = d.get('summary', {}).get('vcp_found', len(d.get('signals', [])))
            gen_at = d.get('metadata', {}).get('generated_at', '')[:16].replace('T', ' ')
            freshness = "✅" if gen_at[:10] >= yesterday else "⚠️"
            lines.append(f"{freshness} <b>US VCP</b>: {vcp_count}종목")
        else:
            lines.append("❌ <b>US VCP</b>: 데이터 없음")

        # ── Crypto ──
        vcp_crypto_path = os.path.join(Config.DATA_DIR, 'vcp_crypto_latest.json')
        if os.path.exists(vcp_crypto_path):
            with open(vcp_crypto_path, 'r', encoding='utf-8') as f:
                d = json.load(f)
            vcp_count = d.get('summary', {}).get('vcp_found', len(d.get('signals', [])))
            gen_at = d.get('metadata', {}).get('generated_at', '')[:16].replace('T', ' ')
            freshness = "✅" if gen_at[:10] >= yesterday else "⚠️"
            lines.append(f"{freshness} <b>Crypto VCP</b>: {vcp_count}종목")
        else:
            lines.append("❌ <b>Crypto VCP</b>: 데이터 없음")

        # ── US Briefing ──
        us_briefing_path = os.path.join(Config.BASE_DIR, 'us_market', 'output', 'market_briefing.json')
        if os.path.exists(us_briefing_path):
            mtime = os.path.getmtime(us_briefing_path)
            mtime_str = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M')
            freshness = "✅" if mtime_str[:10] >= yesterday else "⚠️"
            lines.append(f"{freshness} <b>US Briefing</b>: 갱신 {mtime_str}")
        else:
            lines.append("❌ <b>US Briefing</b>: 데이터 없음")

        # ── Watchdog 로그 (재시작 여부) ──
        watchdog_log = os.path.join(Config.BASE_DIR, 'logs', 'watchdog.log')
        if os.path.exists(watchdog_log):
            with open(watchdog_log, 'r', encoding='utf-8') as f:
                entries = [l.strip() for l in f.readlines() if yesterday in l or today in l]
            restarts = [l for l in entries if '🔴' in l or '재시작' in l or '❌' in l]
            if restarts:
                lines.append(f"")
                lines.append(f"⚠️ <b>Flask 재시작</b>: {len(restarts)}회")
                for r in restarts[-2:]:
                    lines.append(f"   └ {r[:60]}")
            else:
                lines.append(f"")
                lines.append(f"✅ <b>Flask 안정</b>: 재시작 없음")

        # 시스템 상태 리포트 — 개인 봇만 (채널은 분석 전용)
        send_telegram('\n'.join(lines), channel=False)
        logger.info("✅ 아침 상태 리포트 전송 완료")
        return True

    except Exception as e:
        logger.error(f"❌ 아침 리포트 실패: {e}")
        return False


def run_morning_briefing():
    """09:05 KST - AI 조간 브리핑 생성 (Gemini 2.5 Flash + Google Search)"""
    logger.info("📰 AI 조간 브리핑 생성 중...")
    try:
        from briefing_generator import generate_morning_briefing
        result = generate_morning_briefing()
        if result:
            title = result.get('title', '조간 브리핑')
            summary = result.get('summary', '')
            sentiment = result.get('market_sentiment', 'N/A')
            send_telegram(
                f"📰 <b>조간 브리핑 발행</b>\n\n"
                f"<b>{title}</b>\n\n"
                f"{summary}\n\n"
                f"감정: {sentiment}"
            )
            logger.info(f"✅ 조간 브리핑 완료: {title}")
            return True
        logger.warning("⚠️ 조간 브리핑 생성 실패 (None 반환)")
        return False
    except Exception as e:
        logger.error(f"❌ 조간 브리핑 실패: {e}")
        return False


def run_closing_briefing():
    """16:05 KST - AI 마감 브리핑 생성 (Gemini 2.5 Flash + Google Search)"""
    logger.info("📰 AI 마감 브리핑 생성 중...")
    try:
        from briefing_generator import generate_closing_briefing
        result = generate_closing_briefing()
        if result:
            title = result.get('title', '마감 브리핑')
            summary = result.get('summary', '')
            sentiment = result.get('market_sentiment', 'N/A')
            send_telegram(
                f"📰 <b>마감 브리핑 발행</b>\n\n"
                f"<b>{title}</b>\n\n"
                f"{summary}\n\n"
                f"감정: {sentiment}"
            )
            logger.info(f"✅ 마감 브리핑 완료: {title}")
            return True
        logger.warning("⚠️ 마감 브리핑 생성 실패 (None 반환)")
        return False
    except Exception as e:
        logger.error(f"❌ 마감 브리핑 실패: {e}")
        return False


def run_lotto_analysis():
    """금요일 17:00 KST — AI 로또 분석 게시"""
    logger.info("=" * 60)
    logger.info("🎱 AI 로또 분석 게시 시작")
    logger.info("=" * 60)
    try:
        scripts_dir = os.path.join(Config.BASE_DIR, 'scripts')
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from lotto_analysis import run_lotto_analysis_post
        result = run_lotto_analysis_post()
        if result:
            if isinstance(result, dict) and result.get('skipped'):
                logger.info("AI lotto analysis already posted; duplicate run skipped")
                return True
            logger.info("✅ AI 로또 분석 게시 완료")

            # 텔레그램 상세 메시지
            post_id = result.get('post_id', '')
            title = result.get('title', 'AI 로또 분석')
            candidates = result.get('candidates', {})

            lines = [f"🎱 AI 로또 분석 게시 완료", f"📋 {title}", ""]
            style_emoji = {'안정형': '🛡️', '균형형': '⚖️', '실험형': '🔥'}
            for style_name, data in candidates.items():
                emoji = style_emoji.get(style_name, '🎯')
                for s in data.get('sets', [])[:2]:
                    nums = ', '.join(str(n) for n in s['numbers'])
                    lines.append(f"{emoji} {style_name}: [{nums}] (점수: {s['score']})")
            lines.append("")
            lines.append(f"👉 커뮤니티에서 확인: /dashboard/community/post/{post_id}")
            lines.append("⚠️ 본 분석은 통계 기반 참고용이며 당첨을 보장하지 않습니다.")

            send_telegram('\n'.join(lines))
            return True
        logger.warning("⚠️ AI 로또 분석 게시 실패")
        send_telegram("⚠️ AI 로또 분석 게시 실패 — 로그를 확인하세요.", channel=False)
        return False
    except Exception as e:
        logger.error(f"❌ AI 로또 분석 실패: {e}", exc_info=True)
        send_telegram(f"❌ AI 로또 분석 실패: {str(e)[:200]}", channel=False)
        return False


def run_lotto_analysis_bounded():
    """Run lotto posting in a child process so provider hangs cannot block the scheduler."""
    logger.info("Starting bounded AI lotto analysis post")
    try:
        script_path = os.path.join(Config.BASE_DIR, 'scripts', 'lotto_analysis.py')
        timeout_sec = int(os.environ.get('LOTTO_JOB_TIMEOUT_SEC', '1200'))
        completed = subprocess.run(
            [Config.PYTHON_PATH, script_path],
            cwd=Config.BASE_DIR,
            timeout=timeout_sec,
            check=False,
        )
        if completed.returncode == 0:
            logger.info("AI lotto analysis completed or an existing post was confirmed")
            send_telegram("AI lotto analysis task completed. Check the community post.", channel=False)
            return True
        logger.warning("AI lotto analysis failed (exit=%s)", completed.returncode)
        return False
    except subprocess.TimeoutExpired:
        logger.error("AI lotto analysis timed out; the child process was terminated")
        send_telegram(
            "AI lotto analysis timed out. Automatic retry and Saturday recovery are enabled.",
            channel=False,
        )
        return False
    except Exception as e:
        logger.error("AI lotto analysis failed: %s", e, exc_info=True)
        send_telegram(f"AI lotto analysis failed: {str(e)[:200]}", channel=False)
        return False


def send_jongga_v2_telegram(max_age_sec: int = 300) -> bool:
    """최신 V2 결과를 텔레그램으로 보낸다. 전송했으면 True.

    데몬 경로와 안전망(scripts/ensure_jongga_v2.py) 이 같은 함수를 쓴다.
    분리 전에는 전송이 데몬 안에만 있어서, 안전망이나 수동 실행으로 결과를
    만들어도 알림은 나가지 않았다 — 사용자에게는 여전히 "갱신 안 됨" 이다.

    max_age_sec: 결과 파일이 이보다 오래되면 보내지 않는다. 낡은 결과를
    오늘 것처럼 알리는 쪽이 침묵보다 나쁘기 때문이다.
    """
    try:
        json_path = os.path.join(Config.DATA_DIR, "jongga_v2_latest.json")
        if not os.path.exists(json_path) or (time.time() - os.path.getmtime(json_path)) > max_age_sec:
            logger.warning("⚠️ 종가베팅 결과 파일 없거나 오래됨")
            return False

        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        date_str = data.get("date", "")
        all_signals = data.get("signals", [])
        total_count = len(all_signals)

        sa_signals = [s for s in all_signals if s.get("grade") in ["S", "A"]]
        s_count = len([s for s in all_signals if s.get("grade") == "S"])
        a_count = len([s for s in all_signals if s.get("grade") == "A"])
        b_count = len([s for s in all_signals if s.get("grade") == "B"])

        header = f"<b>🎯 종가베팅 V2 ({date_str})</b>\n\n"
        header += f"총 {total_count}개 시그널 (S:{s_count} A:{a_count} B:{b_count})\n"
        header += "────────────────────"

        if not sa_signals:
            send_telegram(header + "\n\n⚠️ S/A급 시그널 없음 (B급 제외됨)")
        else:
            seen_codes = set()
            items = []
            for s in sa_signals:
                code = s.get("stock_code", "")
                if code in seen_codes:
                    continue
                seen_codes.add(code)

                grade = s.get("grade", "B")
                icon = "🥇" if grade == "S" else "🥈"
                change_pct = s.get("change_pct", 0)

                item = f"\n{icon} <b>{s.get('stock_name')}</b> ({code}) {s.get('market', '')}\n"
                item += f"   등급: {grade} | 점수: {s.get('score', {}).get('total', 0)} | 등락: {change_pct:+.1f}%\n"
                item += f"   진입: {s.get('entry_price', 0):,}원 | 목표: {s.get('target_price', 0):,}원\n"
                if s.get("themes"):
                    item += f"   테마: {', '.join(s.get('themes')[:3])}\n"
                llm_reason = s.get('score', {}).get('llm_reason', '')
                if llm_reason:
                    item += f"   💡 {llm_reason[:60]}...\n"
                items.append(item)

            chunks = []
            current_chunk = header
            for item in items:
                if len(current_chunk) + len(item) > 3800:
                    chunks.append(current_chunk)
                    current_chunk = item
                else:
                    current_chunk += item
            if current_chunk:
                chunks.append(current_chunk)

            for i, chunk in enumerate(chunks):
                if i > 0:
                    chunk = f"<b>🎯 종가베팅 V2 계속 ({i+1}/{len(chunks)})</b>\n" + chunk
                send_telegram(chunk)
                time.sleep(0.5)

    except Exception as e:
        logger.error(f"❌ 종가베팅 결과 전송 실패: {e}")
    return True


PREFLIGHT_TIMEOUT_SEC = 180

# 놓친 스케줄 복구와 정규 스케줄이 같은 작업을 동시에 띄울 수 있다.
# 2026-08-05: 14:52(복구)와 14:56(정규)가 겹쳐 가격 수집이 2,874종목씩 두 번
# 동시에 돌았고, 그 부하가 pre-flight 를 타임아웃시켜 하루치 결과가 날아갔다.
_JONGGA_V2_LOCK = threading.Lock()


def _run_v2_preflight(timeout: int = PREFLIGHT_TIMEOUT_SEC) -> str:
    """V2 임포트 검증. 'ok' | 'import_error' | 'timeout'.

    타임아웃과 임포트 오류는 다른 사건이다. 이 검사의 목적은 코드 버그를
    미리 잡는 것이고, 타임아웃은 코드가 아니라 호스트 부하의 증상이다.
    둘을 같이 취급하면 부하가 곧 '코드 버그' 로 보고되고 실행이 막힌다.

    2026-08-05 실측: 유휴 상태 임포트 7.7초. 중복 실행으로 부하가 걸리자
    60초를 넘겨 4회 시도가 전부 차단됐고, 수동 실행에서는 엔진이 118초 만에
    19개 시그널을 정상 생성했다. 엔진에 1200초를 주면서 그것을 지키는 검사에
    60초만 준 것이 원인이다.
    """
    started = time.time()
    completed = run_command(
        [Config.PYTHON_PATH, '-c',
         'from engine.generator import run_screener; '
         'from engine.llm_analyzer import LLMAnalyzer; '
         'from engine.scorer import Scorer; '
         'import anthropic, openai; '  # V2 런타임 필수 SDK
         'print("OK")'],
        'V2 pre-flight 검증',
        timeout=timeout,
    )
    if completed:
        return 'ok'
    # run_command 는 타임아웃과 비정상 종료를 모두 False 로 돌려준다.
    # 경과 시간으로 구분한다 — 임포트 오류는 예산을 다 쓰지 않고 몇 초 만에 끝난다.
    return 'timeout' if (time.time() - started) >= timeout else 'import_error'


def update_jongga_v2():
    """종가베팅 V2 데이터 업데이트 + S/A급 텔레그램 전송

    subprocess 방식 유지 (git pull 후 디스크의 최신 코드를 항상 사용).
    pre-flight 검증으로 코드 버그 사전 탐지 + 실패 시 텔레그램 즉시 알림.
    """
    if not _kr_market_task_allowed('jongga_v2'):
        return True

    # 놓친 스케줄 복구와 정규 스케줄이 같은 작업을 동시에 띄우면 전 종목
    # 가격 수집이 두 번 겹쳐 돌고, 그 부하가 다른 단계를 타임아웃시킨다.
    if not _JONGGA_V2_LOCK.acquire(blocking=False):
        logger.info("⏭️ 종가베팅 V2: 이미 실행 중 — 중복 실행 건너뜀")
        return True
    try:
        return _update_jongga_v2_locked()
    finally:
        _JONGGA_V2_LOCK.release()


def _update_jongga_v2_locked():
    """update_jongga_v2 본체. 동시 실행 가드 안에서만 호출한다."""
    # ── Pre-flight: subprocess로 import만 테스트 (최신 디스크 코드 검증) ──
    # Keep this a true import pre-flight. Constructing LLMAnalyzer here can
    # perform slow provider initialization and turn host load into a false
    # "code import bug" alert before the engine itself is even attempted.

    status = _run_v2_preflight()
    if status == 'import_error':
        send_telegram(
            "<b>🚨 종가베팅 V2 코드 버그</b>\n\n"
            "V2 pre-flight 임포트 실패 — 코드 오류입니다.\n"
            "scheduler 로그에서 traceback 을 확인하세요.",
            channel=False
        )
        return False
    if status == 'timeout':
        # 부하 증상이지 코드 버그가 아니다. 엔진은 자체 1200초 예산을 갖고 있고,
        # 진짜 임포트 오류라면 거기서도 몇 초 만에 죽는다. 여기서 막으면
        # 일시적 부하가 하루치 결과를 통째로 날린다.
        logger.warning("⚠️ V2 pre-flight 지연 — 호스트 부하로 판단하고 엔진 실행을 계속합니다")
        send_telegram(
            "<b>⚠️ 종가베팅 V2 pre-flight 지연</b>\n\n"
            f"임포트 검증이 {PREFLIGHT_TIMEOUT_SEC}초를 넘겼습니다 (부하 추정).\n"
            "엔진 실행은 계속합니다.",
            channel=False
        )
    else:
        logger.info("✅ V2 pre-flight 임포트 검증 통과")

    # ── 메인 실행 (subprocess — 항상 디스크 최신 코드 사용) ──
    script = (
        "import asyncio; "
        "from datetime import datetime, timedelta, date; "
        "from engine.generator import run_screener; "
        "now = datetime.now(); "
        "target_date = date.today(); "
        "target_date = (target_date - timedelta(days=1)) if now.hour < 9 else target_date; "
        "target_date = (target_date - timedelta(days=2)) if target_date.weekday() == 6 else "
        "((target_date - timedelta(days=1)) if target_date.weekday() == 5 else target_date); "
        "print(f'분석 기준일: {target_date}'); "
        "asyncio.run(run_screener(capital=50_000_000, markets=['KOSPI', 'KOSDAQ'], target_date=target_date))"
    )
    success = run_command(
        [Config.PYTHON_PATH, '-c', script],
        'KR 종가베팅 V2 분석 엔진',
        timeout=1200
    )

    if not success:
        send_telegram(
            "<b>🚨 종가베팅 V2 실행 실패</b>\n\n"
            "스크리너 subprocess 비정상 종료.\n"
            "scheduler 로그에서 traceback을 확인하세요.",
            channel=False
        )
        return False

    send_jongga_v2_telegram()

    # 누적 성과 캐시 무효화
    try:
        perf_cache = os.path.join(Config.DATA_DIR, "cumulative_performance.json")
        if os.path.exists(perf_cache):
            os.remove(perf_cache)
            logger.info("🗑️ 누적 성과 캐시 삭제 (새 시그널 반영 대기)")
    except Exception as e:
        logger.warning(f"⚠️ 누적 성과 캐시 삭제 실패: {e}")

    return True


def _build_vcp_top10_text() -> str:
    """VCP 시그널 Top 10 텍스트 생성 (vcp_kr_latest.json 기반)"""
    json_path = os.path.join(Config.DATA_DIR, 'vcp_kr_latest.json')
    if not os.path.exists(json_path):
        return ""
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return ""

    signals = data.get('signals', [])
    if not signals:
        return ""

    signals.sort(key=lambda s: s.get('composite', {}).get('composite_score', 0)
                 if isinstance(s.get('composite'), dict) else 0, reverse=True)

    top_10 = signals[:10]
    today = datetime.now().strftime('%m/%d')
    text = f"<b>📈 VCP Top 10 ({today})</b>\n"

    for i, s in enumerate(top_10, 1):
        name = s.get('name', s.get('symbol', '?'))
        symbol = s.get('symbol', '?')
        comp = s.get('composite', {})
        score = comp.get('composite_score', 0) if isinstance(comp, dict) else 0
        price = s.get('price', 0)
        close = float(price) if not isinstance(price, dict) else price.get('close', 0)
        text += f"{i}. <b>{name}({symbol})</b> {score:.1f}점 {close:,.0f}원\n"

    return text


# ── KR 올업데이트 (14:50 통합) ──

def post_daily_analysis_to_community() -> bool:
    """종가베팅 V2 결과 → 커뮤니티 종목분석 게시판 자동 게시.
    주말·빈 결과·중복 → skip (exit 2). 실패해도 파이프라인 방어."""
    script_path = os.path.join(Config.BASE_DIR, 'scripts', 'post_daily_analysis.py')
    if not os.path.exists(script_path):
        logger.warning(f"post_daily_analysis.py 없음 — skip")
        return True  # 파이프라인 실패로 간주하지 않음
    try:
        return run_command(
            [Config.PYTHON_PATH, script_path],
            '커뮤니티 종목분석 게시 (자동)',
            timeout=300,  # 이미지 5장 생성 여유 (30s × 5)
            env_extra={'MARKETFLOW_API': local_api_base()},
        )
    except Exception as e:
        logger.warning(f"post_daily_analysis 예외 (무시): {e}")
        return True


def run_kr_full_update(skip_sync: bool = False):
    """KR 종가베팅 업데이트 (14:50) — 종가베팅V2 + 수급/AI/리포트 → 텔레그램
    ※ VCP 시그널은 16:00 run_vcp_all_markets()에서 별도 실행
    """
    if not _kr_market_task_allowed('kr_full_update'):
        return True

    logger.info("=" * 60)
    logger.info("🇰🇷 KR 종가베팅 업데이트 시작 (14:50)")
    logger.info("=" * 60)

    start_time = time.time()
    results = []

    # 1. 종가베팅 V2 (핵심)
    results.append(('종가베팅 V2', update_jongga_v2()))

    # 2. 가격/수급/AI/리포트 (VCP는 16:00에 분리)
    results.append(('daily_prices', update_daily_prices()))
    results.append(('institutional', update_institutional_data()))
    results.append(('ai_analysis', run_ai_analysis_scan()))
    results.append(('daily_report', generate_daily_report()))

    # 3. 커뮤니티 자동 게시 (V2 결과 기반)
    results.append(('커뮤니티 게시', post_daily_analysis_to_community()))

    elapsed = int(time.time() - start_time)
    success_count = sum(1 for _, s in results if s)
    total_count = len(results)
    summary_lines = [f"  {'✅' if s else '❌'} {n}" for n, s in results]

    logger.info(f"📋 KR 종가베팅 업데이트 완료: {success_count}/{total_count} ({elapsed}초)")

    send_telegram(
        f"<b>🇰🇷 15시 종가베팅 업데이트 완료</b>\n"
        f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')} ({elapsed}초)\n"
        f"결과: {success_count}/{total_count}\n\n"
        + "\n".join(summary_lines),
        channel=False
    )

    if not skip_sync:
        auto_git_push('kr')

    return all(r[1] for r in results)


def run_kr_vcp_morning_refresh():
    """평일 오전 KR VCP 단독 refresh (주말 후 stale 방지용).

    16:00 정식 run_vcp_all_markets 와 별개로 KR 만 갱신. signal_tracker 는 백테스트용이라 생략하고
    enhanced_scanner 로 vcp_kr_latest.json 만 빠르게 새로고침. 텔레그램 알림은 보내지 않음
    (16:00 알림과 중복 방지). 검증/재시도는 run_vcp_enhanced_scan 내부에서 처리.
    """
    logger.info("=" * 60)
    logger.info(f"📈 KR VCP 오전 Refresh 시작 ({Config.KR_VCP_MORNING_TIME}) — 단독 실행")
    logger.info("=" * 60)
    start_time = time.time()
    ok = run_vcp_enhanced_scan('KR')
    elapsed = int(time.time() - start_time)
    if ok:
        logger.info(f"✅ KR VCP 오전 Refresh 완료 ({elapsed}초)")
        try:
            auto_git_push('vcp')
        except Exception as e:
            logger.warning(f"⚠️ git push 실패: {e}")
    else:
        logger.warning(f"⚠️ KR VCP 오전 Refresh 실패 ({elapsed}초)")
    return ok


def run_vcp_all_markets(skip_sync: bool = False):
    """KR·US VCP 시그널 업데이트 (16:00).

    Crypto VCP는 4시간 주기의 전용 Crypto 파이프라인만 실행한다.
    """
    logger.info("=" * 60)
    logger.info("📈 KR·US VCP 시그널 업데이트 시작 (16:00)")
    logger.info("=" * 60)

    start_time = time.time()
    results = []

    # KR VCP (signal_tracker + vcp_enhanced_scanner 둘 다 실행)
    results.append(('KR VCP (signal)', run_vcp_signal_scan(send_alert=True)))
    results.append(('KR VCP (enhanced)', run_vcp_enhanced_scan('KR')))

    # US VCP
    results.append(('US VCP', run_vcp_enhanced_scan('US')))

    elapsed = int(time.time() - start_time)
    success_count = sum(1 for _, s in results if s)
    summary_lines = [f"  {'✅' if s else '❌'} {n}" for n, s in results]

    logger.info(f"📋 KR·US VCP 업데이트 완료: {success_count}/{len(results)} ({elapsed}초)")

    send_telegram(
        f"<b>📈 16시 KR·US VCP 업데이트 완료</b>\n"
        f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')} ({elapsed}초)\n"
        f"결과: {success_count}/{len(results)}\n\n"
        + "\n".join(summary_lines),
        channel=False
    )

    if not skip_sync:
        auto_git_push('vcp')

    return all(r[1] for r in results)


def _scan_preserved_last_good(result_file: str, max_age_sec: int = 900) -> bool:
    """이번 실행이 결과 파일을 '일부러' 안 쓴 것인지 확인.

    vcp_enhanced_scanner 는 빈 결과로 멀쩡한 결과를 덮지 않는다(last-known-good 보존).
    그때 결과 파일 mtime 은 그대로라, mtime 만 보면 '스캔이 죽어서 못 씀' 과 구분이
    안 된다. 스캐너가 매 실행마다 남기는 상태 파일이 그 둘을 가른다.

    max_age_sec: 이 시간 안에 쓰인 상태만 '이번 실행의 것' 으로 인정한다.
                 (스캔 1회는 5분 이내 — 지난주 상태가 오늘 실패를 가리면 안 된다)
    """
    status_path = result_file.replace('_latest.json', '_scan_status.json')
    if status_path == result_file:
        return False
    try:
        if time.time() - os.path.getmtime(status_path) > max_age_sec:
            return False
        with open(status_path, 'r', encoding='utf-8') as f:
            return json.load(f).get('outcome') == 'preserved'
    except (OSError, ValueError):
        return False


def run_vcp_enhanced_scan(market: str) -> bool:
    """US / Crypto / KR VCP Enhanced Scanner 실행 + 결과 검증 + 재시도"""
    script = os.path.join(Config.BASE_DIR, 'vcp_enhanced_scanner.py')
    if not os.path.exists(script):
        logger.warning(f"⚠️ vcp_enhanced_scanner.py 없음 — {market} VCP 스킵")
        return False

    market_upper = market.upper()
    file_map = {'KR': 'vcp_kr_latest.json', 'US': 'vcp_us_latest.json', 'CRYPTO': 'vcp_crypto_latest.json'}
    result_file = os.path.join(Config.DATA_DIR, file_map.get(market_upper, f'vcp_{market.lower()}_latest.json'))

    max_retries = 2
    for attempt in range(1, max_retries + 1):
        success = run_command(
            [Config.PYTHON_PATH, script, '--market', market],
            f'{market_upper} VCP Enhanced Scan (시도 {attempt}/{max_retries})',
            timeout=Config.SIGNAL_TIMEOUT
        )
        if not success:
            logger.warning(f"⚠️ {market_upper} VCP 스캔 실패 (시도 {attempt}/{max_retries})")
            if attempt < max_retries:
                time.sleep(10)
            continue

        # 결과 검증
        if os.path.exists(result_file):
            try:
                with open(result_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                signals = data.get('signals', [])
                summary = data.get('summary', {}) or {}
                stage2_passed = int(summary.get('stage2_passed', 0) or 0)
                total_screened = int(summary.get('total_screened', 0) or 0)
                mtime = os.path.getmtime(result_file)
                file_age = time.time() - mtime
                if file_age > 300:  # 5분 이상 된 파일 = 이번 실행이 안 썼다는 뜻
                    # 안 쓴 이유가 둘이다: 스캐너가 죽었거나(실패), 빈 결과로 멀쩡한
                    # 결과를 덮지 않으려고 일부러 건너뛰었거나(정상). 후자는 실패가
                    # 아니다 — 보존본이 쓸 만한지는 바로 아래 freshness 가 계속 본다.
                    if _scan_preserved_last_good(result_file):
                        logger.info(
                            f"ℹ️ {market_upper} VCP: 직전 정상 결과 유지 "
                            f"(이번 스캔은 저장 스킵, 파일 {int(file_age)}초 전)"
                        )
                    else:
                        logger.warning(f"⚠️ {market_upper} VCP 결과 파일이 오래됨 ({int(file_age)}초)")
                        if attempt < max_retries:
                            time.sleep(10)
                        continue
                if build_freshness:
                    max_age_hours = 12 if market_upper == 'CRYPTO' else 96
                    freshness = build_freshness(result_file, data, max_age_hours=max_age_hours)
                    if freshness.get('is_stale'):
                        logger.warning("%s VCP freshness verify failed: %s", market_upper, freshness)
                        if attempt < max_retries:
                            time.sleep(10)
                            continue
                        send_telegram(
                            f"🚨 {market_upper} VCP freshness 검증 실패\n"
                            f"사유: {', '.join(freshness.get('stale_reasons') or [])}\n"
                            f"content: {freshness.get('content_timestamp')}",
                            channel=False
                        )
                        return False
                # self-verify: stage2==0 또는 signals 비어있으면 이상 징후 (yfinance 일시 장애 의심)
                if total_screened > 0 and stage2_passed == 0 and len(signals) == 0:
                    logger.warning(
                        f"⚠️ {market_upper} VCP self-verify 실패: stage2=0 "
                        f"(screened={total_screened}) — yfinance 일시 장애 의심"
                    )
                    if attempt < max_retries:
                        time.sleep(30)  # yfinance 회복 대기
                        continue
                    # 최종 실패 → 알림
                    send_telegram(
                        f"⚠️ {market_upper} VCP self-verify 실패\n"
                        f"screened={total_screened}, stage2=0, signals=0\n"
                        f"yfinance 외부 장애 가능성 — 다음 스케줄 재시도",
                        channel=False
                    )
                    return False
                logger.info(
                    f"✅ {market_upper} VCP 검증 완료: {len(signals)}개 시그널 "
                    f"(stage2={stage2_passed}/{total_screened})"
                )
                return True
            except Exception as e:
                logger.warning(f"⚠️ {market_upper} VCP 결과 파일 읽기 실패: {e}")
        else:
            logger.warning(f"⚠️ {market_upper} VCP 결과 파일 없음: {result_file}")

        if attempt < max_retries:
            time.sleep(10)

    send_telegram(f"❌ {market_upper} VCP 스캔 {max_retries}회 실패", channel=False)
    return False


# ============================================================
# [US Market] 작업 함수들
# ============================================================

def run_us_market_update(skip_sync: bool = False):
    """US 마켓 전체 업데이트 (us-market-pro 파이프라인)"""
    logger.info("=" * 60)
    logger.info("🇺🇸 US Market 전체 업데이트 시작 (us_market/update_all.py)")
    logger.info("=" * 60)

    # 1. us_market/update_all.py 실행 (Parallel Pipeline v2.0)
    update_script = os.path.join(Config.BASE_DIR, 'us_market', 'update_all.py')

    if not os.path.exists(update_script):
        logger.warning(f"⚠️ US update script 없음: {update_script}")
        return False

    success = run_command(
        [Config.PYTHON_PATH, update_script, '--no-telegram'],
        'US Market Pipeline',
        timeout=1200
    )

    # 2. Track Record 스냅샷
    if success:
        save_us_track_record_snapshot()

    # 3. Smart Money Top 5 텔레그램 전송
    try:
        msg = build_us_smart_money_top5_msg()
        if msg:
            send_telegram(msg)
            logger.info("📬 US Smart Money Top 5 텔레그램 전송 완료")
    except Exception as e:
        logger.error(f"❌ US 텔레그램 전송 실패: {e}")

    # Git 자동 커밋 + 푸시 (→ Render 자동 배포)
    if not skip_sync:
        auto_git_push('us')

    return success


def build_us_smart_money_top5_msg() -> str:
    """US Smart Money Top 5 텔레그램 메시지 생성"""
    today = datetime.now().strftime('%m/%d')

    # top_picks.json 로드 (screener.py 출력)
    picks_path = os.path.join(Config.BASE_DIR, 'us_market', 'output', 'top_picks.json')
    if not os.path.exists(picks_path):
        logger.warning("⚠️ top_picks.json 없음 — Smart Money Top 5 전송 불가")
        return ""

    try:
        with open(picks_path, 'r', encoding='utf-8') as f:
            picks_data = json.load(f)
    except Exception as e:
        logger.error(f"❌ top_picks.json 로드 실패: {e}")
        return ""

    top_picks = picks_data.get('top_picks', [])[:5]
    if not top_picks:
        return f"<b>🇺🇸 US Smart Money Top 5 ({today})</b>\n\n⚠️ 데이터 없음"

    msg = f"<b>🇺🇸 US Smart Money Top 5 ({today})</b>\n"
    msg += "────────────────────\n"

    for p in top_picks:
        rank = p.get('rank', 0)
        ticker = p.get('ticker', '')
        name = p.get('name', ticker)[:20]
        score = p.get('composite_score', 0)
        grade = p.get('grade', '-')
        price = p.get('price', 0)

        msg += f"\n{rank}. <b>{ticker}</b> ({name})\n"
        msg += f"   점수: {score}점 [{grade}] | ${price:,.2f}\n"

    return msg


def save_us_track_record_snapshot():
    """Run US Smart Money track-record generation for the scheduler."""
    logger.info("US Track Record snapshot generation...")

    try:
        tracker_path = os.path.join(Config.BASE_DIR, 'us_market', 'performance_tracker.py')
        if os.path.exists(tracker_path):
            return run_command(
                [Config.PYTHON_PATH, tracker_path],
                'US Smart Money performance tracking',
                timeout=300
            )
        logger.warning("US performance tracker not found: %s", tracker_path)
        return False
    except Exception as e:
        logger.error("US Track Record failed: %s", e)
        return False


# ============================================================
# [Crypto Market] 작업 함수들
# ============================================================

# 현재 gate 상태 추적 (모듈 레벨)
_crypto_gate = "YELLOW"
_crypto_gate_score = 50


def _parse_iso_datetime(value: str) -> Optional[datetime]:
    """Parse ISO datetimes written by pipeline JSON files."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).replace(tzinfo=None)
    except Exception:
        return None


def _load_json(filepath: str) -> Optional[dict]:
    """JSON 파일 안전 로드"""
    try:
        if not os.path.exists(filepath):
            return None
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"JSON 로드 실패 ({filepath}): {e}")
        return None


def _validate_crypto_gate_output(max_age_minutes: int = 30) -> bool:
    """Ensure market_gate.json is structurally valid and freshly generated."""
    output_path = os.path.join(Config.CRYPTO_OUTPUT_DIR, 'market_gate.json')
    data = _load_json(output_path)
    if not data:
        logger.error("Crypto Gate validation failed: market_gate.json missing/unreadable")
        return False

    gate = str(data.get('gate', '')).upper()
    score = data.get('score')
    generated_at = _parse_iso_datetime(data.get('generated_at', ''))
    if gate not in {'GREEN', 'YELLOW', 'RED'}:
        logger.error(f"Crypto Gate validation failed: invalid gate={gate!r}")
        return False
    if not isinstance(score, (int, float)):
        logger.error(f"Crypto Gate validation failed: invalid score={score!r}")
        return False
    if generated_at is None:
        logger.error("Crypto Gate validation failed: generated_at missing/invalid")
        return False

    age_seconds = (datetime.now() - generated_at).total_seconds()
    if age_seconds > max_age_minutes * 60:
        logger.error(f"Crypto Gate validation failed: stale output ({age_seconds / 60:.1f}m)")
        return False
    return True


def _run_crypto_gate_subprocess() -> bool:
    """Fallback: run the crypto gate script in an isolated Python process."""
    script_path = os.path.join(Config.CRYPTO_MARKET_DIR, 'market_gate.py')
    if not os.path.exists(script_path):
        logger.error(f"Crypto Gate fallback failed: script missing {script_path}")
        return False

    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
    try:
        completed = subprocess.run(
            [Config.PYTHON_PATH, script_path],
            cwd=Config.CRYPTO_MARKET_DIR,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=180,
            env=env,
        )
    except Exception as e:
        logger.error(f"Crypto Gate fallback execution failed: {e}")
        return False

    if completed.returncode != 0:
        logger.error(f"Crypto Gate fallback failed (exit={completed.returncode})")
        if completed.stderr:
            logger.error(completed.stderr.strip()[-2000:])
        return False

    if completed.stdout:
        logger.info(completed.stdout.strip()[-1000:])
    return _validate_crypto_gate_output()


def run_crypto_gate_check() -> bool:
    """Crypto Market Gate 체크 (in-process)"""
    global _crypto_gate, _crypto_gate_score

    logger.info("🚦 Crypto Gate 체크 시작...")

    try:
        crypto_dir = Config.CRYPTO_MARKET_DIR
        path_added = crypto_dir not in sys.path
        if path_added:
            sys.path.insert(0, crypto_dir)

        # sys.modules 스냅샷 — crypto 모듈이 루트 모듈(config 등) 덮어쓰기 방지.
        # sklearn/joblib 등 C extension은 재로드 불가하므로 유지.
        _KEEP_PREFIXES = ('sklearn', 'joblib', 'scipy', 'numpy', 'pandas')
        _saved_mods = {k: v for k, v in sys.modules.items()}

        # 네임스페이스 충돌 해결: 루트 market_gate.py(KR용)는 `run_kr_market_gate`
        # 만 export 하고 `run_market_gate_sync` 는 없음. 반면 crypto_dir 의
        # market_gate.py 에 해당 심볼이 있음. sys.path 앞에 crypto_dir 을 넣어도
        # sys.modules 에 기존 루트 `market_gate` 가 이미 캐시되어 있으면 import
        # 시스템이 그걸 재사용 → ImportError 발생. 따라서 충돌 가능한 모듈을
        # 명시적으로 pop 한 뒤 import, finally 에서 원본 복원한다.
        _CONFLICT_MODS = ('market_gate', 'models', 'indicators')
        for _m in _CONFLICT_MODS:
            sys.modules.pop(_m, None)

        try:
            from market_gate import run_market_gate_sync
            result = run_market_gate_sync()
        finally:
            for k in [k for k in sys.modules if k not in _saved_mods]:
                if not k.startswith(_KEEP_PREFIXES):
                    del sys.modules[k]
            for k, v in _saved_mods.items():
                if sys.modules.get(k) is not v:
                    sys.modules[k] = v
            if path_added and crypto_dir in sys.path:
                sys.path.remove(crypto_dir)

        old_gate = _crypto_gate
        _crypto_gate = result.gate
        _crypto_gate_score = result.score

        logger.info(f"🚦 Crypto Gate: {_crypto_gate} (score: {_crypto_gate_score})")

        # JSON 저장
        gate_json = {
            'gate': result.gate,
            'score': result.score,
            'status': 'RISK_ON' if result.gate == 'GREEN' else ('RISK_OFF' if result.gate == 'RED' else 'NEUTRAL'),
            'reasons': result.reasons,
            'metrics': result.metrics,
            'generated_at': datetime.now().isoformat()
        }
        output_path = os.path.join(Config.CRYPTO_OUTPUT_DIR, 'market_gate.json')
        write_json_atomic(output_path, gate_json)
        if not _validate_crypto_gate_output():
            raise RuntimeError("market_gate.json validation failed")

        # History
        history_path = os.path.join(Config.CRYPTO_OUTPUT_DIR, 'gate_history.json')
        history = []
        if os.path.exists(history_path):
            try:
                with open(history_path, 'r', encoding='utf-8') as f:
                    history = json.load(f)
            except Exception:
                history = []

        history.append({
            'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'gate': result.gate,
            'score': result.score,
        })
        history = history[-90:]

        write_json_atomic(history_path, history)

        # Gate 전환 알림
        if old_gate != _crypto_gate:
            _notify_gate_change(_crypto_gate, _crypto_gate_score)

        return True

    except Exception as e:
        logger.error(f"❌ Crypto Gate 체크 실패: {e}")
        import traceback
        traceback.print_exc()
        logger.warning("Crypto Gate fallback 실행: 별도 Python 프로세스")
        if _run_crypto_gate_subprocess():
            data = _load_json(os.path.join(Config.CRYPTO_OUTPUT_DIR, 'market_gate.json')) or {}
            old_gate = _crypto_gate
            _crypto_gate = str(data.get('gate', 'YELLOW')).upper()
            _crypto_gate_score = int(data.get('score', 50))
            if old_gate != _crypto_gate:
                _notify_gate_change(_crypto_gate, _crypto_gate_score)
            logger.info(f"Crypto Gate fallback 성공: {_crypto_gate} (score: {_crypto_gate_score})")
            return True
        return False


def run_crypto_vcp_scan() -> bool:
    """Crypto VCP 스캔 (in-process, gate-aware) — 결과 JSON 저장 + 텔레그램"""
    global _crypto_gate

    logger.info("🔍 Crypto VCP 스캔 시작...")

    gate = _crypto_gate or "UNKNOWN"
    top_n = 50 if gate == "RED" else 200
    if gate == "RED":
        logger.info("🔴 Gate RED — 방어적 모드 스캔 (축소 유니버스 top 50)")

    try:
        crypto_dir = Config.CRYPTO_MARKET_DIR
        path_added = crypto_dir not in sys.path
        if path_added:
            sys.path.insert(0, crypto_dir)

        # sklearn/joblib 등 C extension 모듈은 프로세스 수준 싱글턴이라 삭제하면 재로드 불가
        _KEEP_PREFIXES = ('sklearn', 'joblib', 'scipy', 'numpy', 'pandas')
        _saved_mods = {k: v for k, v in sys.modules.items()}
        try:
            from run_scan import run_scan_sync
            result = run_scan_sync(top_n=top_n)
        finally:
            for k in [k for k in sys.modules if k not in _saved_mods]:
                if not k.startswith(_KEEP_PREFIXES):
                    del sys.modules[k]
            for k, v in _saved_mods.items():
                if sys.modules.get(k) is not v:
                    sys.modules[k] = v
            if path_added and crypto_dir in sys.path:
                sys.path.remove(crypto_dir)

        published = result.get('published', 0) if isinstance(result, dict) else 0
        logger.info(f"🔍 Crypto VCP: {published}개 시그널 발행")

        # 결과를 vcp_crypto_latest.json에 저장 (VCPSignal 포맷 변환)
        raw_signals = result.get('top_signals', [])
        transformed = []
        for s in raw_signals:
            comp = s.get('components', {})
            total_score = s.get('score', 0)
            valid_vcp = comp.get('valid_vcp', False)
            rating = comp.get('rating', 'Developing')
            entry_ready = s.get('signal_type') in ('BREAKOUT', 'RETEST_OK') and total_score >= 50

            # Normalize component scores to 0-100 range (from 40/25/25/10 max)
            contraction_pct = round((comp.get('contraction', 0) / 40.0) * 100, 1) if comp else 0
            trend_pct = round((comp.get('trend', 0) / 25.0) * 100, 1) if comp else 0
            trigger_pct = round((comp.get('trigger', 0) / 25.0) * 100, 1) if comp else 0
            risk_pct = round((comp.get('risk_liq', 0) / 10.0) * 100, 1) if comp else 0

            transformed.append({
                'symbol': s['symbol'],
                'name': s['symbol'].replace('/USDT', ''),
                'market': 'CRYPTO',
                'price': s.get('pivot_high'),
                'composite': {
                    'composite_score': total_score,
                    'rating': rating,
                    'entry_ready': entry_ready,
                },
                'trend_template': {
                    'score': trend_pct,
                    'passed': trend_pct >= 50,
                },
                'vcp_pattern': {
                    'score': contraction_pct,
                    'valid_vcp': valid_vcp,
                    'num_contractions': 3,
                    'pivot_price': s.get('pivot_high'),
                },
                'volume_pattern': {
                    'score': trigger_pct,
                    'dry_up_ratio': s.get('vol_ratio'),
                },
                'pivot_proximity': {
                    'score': risk_pct,
                    'distance_from_pivot_pct': s.get('breakout_close_pct'),
                    'trade_status': s.get('signal_type'),
                },
                'relative_strength': {
                    'score': round(s['ml_win_prob'], 1) if s.get('ml_win_prob') is not None else 50,
                    'rs_rank_estimate': s.get('ml_win_prob'),
                },
                'stage': {
                    'stage': 2 if trend_pct >= 50 else 1,
                    'stage_label': f"Stage 2 - {s.get('signal_type', 'Setup')}" if trend_pct >= 50 else "Stage 1 - Accumulation",
                },
                # Raw data 보존
                'timeframe': s.get('timeframe'),
                'signal_type': s.get('signal_type'),
                'liquidity_bucket': s.get('liquidity_bucket'),
                'market_regime': s.get('market_regime'),
                'c1': s.get('c1'),
                'c2': s.get('c2'),
                'c3': s.get('c3'),
                'ml_win_prob': s.get('ml_win_prob'),
            })

        vcp_found = len([s for s in transformed if s.get('vcp_pattern', {}).get('valid_vcp')])
        entry_count = len([s for s in transformed if s.get('composite', {}).get('entry_ready')])

        out = {
            'metadata': {
                'generated_at': datetime.now().isoformat(),
                'market': 'CRYPTO',
                'gate': gate,
                'gate_score': 0,
                'universe_size': result.get('universe_size', 0),
            },
            'signals': transformed,
            'summary': {
                'total_screened': result.get('universe_size', 0),
                'setups_4h': result.get('setups_4h', 0),
                'setups_1d': result.get('setups_1d', 0),
                'signals_4h': result.get('signals_4h', 0),
                'signals_1d': result.get('signals_1d', 0),
                'vcp_found': vcp_found,
                'entry_ready': entry_count,
                'published': published,
            },
        }
        out_path = os.path.join(Config.DATA_DIR, 'vcp_crypto_latest.json')
        write_json_atomic(out_path, out)
        logger.info(f"💾 Crypto VCP 결과 저장: {out_path}")

        if published > 0:
            _notify_crypto_signals(published)

        return True

    except Exception as e:
        logger.error(f"❌ Crypto VCP 스캔 실패: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_crypto_briefing() -> bool:
    """Crypto Briefing 생성 (subprocess)"""
    return run_command(
        [Config.PYTHON_PATH, os.path.join(Config.CRYPTO_MARKET_DIR, 'crypto_briefing.py')],
        'Crypto Briefing 생성',
        timeout=Config.CRYPTO_BRIEFING_TIMEOUT,
        cwd=Config.CRYPTO_DIR
    )


def run_crypto_prediction() -> bool:
    """Crypto Prediction 실행 (subprocess)"""
    return run_command(
        [Config.PYTHON_PATH, os.path.join(Config.CRYPTO_MARKET_DIR, 'crypto_prediction.py')],
        'Crypto Prediction',
        timeout=Config.CRYPTO_TASK_TIMEOUT,
        cwd=Config.CRYPTO_DIR
    )


def run_crypto_risk() -> bool:
    """Crypto Risk 분석 (subprocess)"""
    return run_command(
        [Config.PYTHON_PATH, os.path.join(Config.CRYPTO_MARKET_DIR, 'crypto_risk.py')],
        'Crypto Risk 분석',
        timeout=Config.CRYPTO_TASK_TIMEOUT,
        cwd=Config.CRYPTO_DIR
    )


def run_crypto_leadlag() -> bool:
    """Crypto Lead-Lag 분석 (subprocess)"""
    output_path = os.path.join(Config.CRYPTO_MARKET_DIR, 'lead_lag', 'results.json')
    return run_command(
        [
            Config.PYTHON_PATH,
            os.path.join(Config.CRYPTO_MARKET_DIR, 'run_lead_lag.py'),
            '--output', output_path,
            '--no-llm'
        ],
        'Crypto Lead-Lag 분석',
        timeout=Config.CRYPTO_TASK_TIMEOUT,
        cwd=Config.CRYPTO_DIR
    )


# ── Crypto 텔레그램 알림 ──

def _gate_emoji(gate: str) -> str:
    if gate == "GREEN":
        return "🟢"
    elif gate == "YELLOW":
        return "🟡"
    elif gate == "RED":
        return "🔴"
    return "⚪"


def _change_emoji(change) -> str:
    if change is None:
        return ""
    if change > 0:
        return "🔴" if change > 3.0 else "🔺"
    elif change < 0:
        return "🟢" if change < -3.0 else "🔻"
    return "➡️"


def _fear_greed_emoji(score) -> str:
    if score is None:
        return "⚪"
    if score >= 75:
        return "🔴"
    elif score >= 55:
        return "🟢"
    elif score >= 45:
        return "🟡"
    elif score >= 25:
        return "🟠"
    return "🔵"


def _notify_gate_change(gate: str, score: int) -> bool:
    """Gate 상태 전환 알림"""
    g = _gate_emoji(gate)
    now_str = datetime.now().strftime('%m/%d %H:%M')
    msg = f"{g} <b>Crypto Gate 전환</b> ({now_str})\n\nMarket Gate: <b>{gate}</b> (점수: {score})\n"
    if gate == "RED":
        msg += "⚠️ VCP 스캔 일시 중단됨"
    elif gate == "GREEN":
        msg += "✅ 공격 모드 진입"
    else:
        msg += "⚡ 주의 모드"
    # Gate 전환은 시스템 상태 변화 — 개인 봇만
    return send_telegram(msg, channel=False)


def _notify_crypto_signals(count: int) -> bool:
    """Crypto VCP 시그널 발견 알림 (종목 상세 포함)"""
    if count <= 0:
        return False
    now_str = datetime.now().strftime('%m/%d %H:%M')
    msg = f"🔍 <b>Crypto VCP Signal Alert</b> ({now_str})\n\n"

    # 시그널 상세 정보 로드
    data = _load_json(os.path.join(Config.DATA_DIR, 'vcp_crypto_latest.json'))
    signals = (data or {}).get('signals', [])
    gate = (data or {}).get('metadata', {}).get('gate', '?')
    msg += f"🚦 Gate: <b>{gate}</b> | 시그널: {len(signals)}개\n\n"

    for s in signals:
        symbol = s.get('symbol', '?')
        tf = s.get('timeframe', '?')
        sig_type = s.get('signal_type', '?')
        score = s.get('score') or 0
        ml_prob = s.get('ml_win_prob') or 0
        pivot = s.get('pivot_high') or 0
        vol_ratio = s.get('vol_ratio') or 0
        bp_pct = s.get('breakout_close_pct') or 0

        # 시그널 타입 이모지
        type_emoji = '🚀' if sig_type == 'BREAKOUT' else '⏳' if sig_type == 'APPROACHING' else '🔄'

        msg += f"{type_emoji} <b>{symbol}</b> ({tf})\n"
        msg += f"   유형: {sig_type} | 점수: {score}\n"
        msg += f"   피봇: ${pivot:,.2f} | 돌파: {bp_pct:+.1f}%\n"
        msg += f"   거래량비: {vol_ratio:.2f}x | ML승률: {ml_prob:.1f}%\n\n"

    return send_telegram_long(msg.strip())


def notify_crypto_briefing() -> bool:
    """Crypto Briefing 텔레그램 알림"""
    try:
        return _notify_crypto_briefing_impl()
    except Exception as e:
        logger.error(f"❌ Crypto Briefing 알림 실패: {e}")
        return False


def _notify_crypto_briefing_impl() -> bool:
    data = _load_json(os.path.join(Config.CRYPTO_OUTPUT_DIR, 'crypto_briefing.json'))
    if not data:
        return False

    today_str = datetime.now().strftime('%m/%d')
    msg = f"<b>🪙 Crypto Market Briefing ({today_str})</b>\n\n"

    # 시가총액 & BTC 도미넌스
    market = data.get('market_summary') or {}
    total_mcap = market.get('total_market_cap')
    btc_dom = market.get('btc_dominance')

    if total_mcap is not None:
        if isinstance(total_mcap, (int, float)) and total_mcap >= 1e12:
            msg += f"💰 시가총액: ${total_mcap / 1e12:.2f}T\n"
        elif isinstance(total_mcap, (int, float)) and total_mcap >= 1e9:
            msg += f"💰 시가총액: ${total_mcap / 1e9:.1f}B\n"
    if btc_dom is not None:
        msg += f"👑 BTC 도미넌스: {btc_dom:.1f}%\n"
    msg += "\n"

    # 주요 코인
    msg += "<b>📊 주요 코인</b>\n"
    coins = data.get('major_coins') or {}
    if isinstance(coins, list):
        coins_dict = {c.get('symbol', ''): c for c in coins}
    else:
        coins_dict = coins

    for symbol in ['BTC', 'ETH', 'SOL']:
        coin = coins_dict.get(symbol, {})
        price = coin.get('price') or coin.get('price_usd')
        change = coin.get('change_24h') or coin.get('change_24h_pct') or coin.get('change')
        if price is not None:
            emoji = _change_emoji(change)
            change_str = f" ({change:+.2f}%)" if change is not None else ""
            msg += f"{emoji} {symbol}: ${price:,.2f}{change_str}\n"
    msg += "\n"

    # Fear & Greed
    fg = data.get('fear_greed') or {}
    fg_score = fg.get('current_score') or fg.get('score') or fg.get('value')
    fg_level = fg.get('level', fg.get('classification', 'N/A'))
    if fg_score is not None:
        fg_em = _fear_greed_emoji(fg_score)
        msg += f"🧭 Fear &amp; Greed: {fg_score} ({fg_level}) {fg_em}\n"

    # Gate 상태
    gate_data = data.get('market_gate') or data.get('gate') or {}
    if not gate_data:
        gate_data = _load_json(os.path.join(Config.CRYPTO_OUTPUT_DIR, 'market_gate.json')) or {}

    gate = gate_data.get('gate', gate_data.get('gate_color'))
    gate_score = gate_data.get('score', gate_data.get('gate_score'))
    if gate is not None:
        g = _gate_emoji(gate)
        score_str = f" (점수: {gate_score})" if gate_score is not None else ""
        msg += f"{g} Market Gate: <b>{gate}</b>{score_str}\n"

    send_telegram_long(msg.strip())
    return True


# ── Crypto 전체 파이프라인 ──

_CRYPTO_WORKER_SCHEMA = 'marketflow.crypto_pipeline_worker.v1'
_CRYPTO_ATTEMPT_SCHEMA = 'marketflow.crypto_pipeline_attempt.v1'
_CRYPTO_STEP_KEYS = ('gate', 'vcp', 'briefing', 'prediction', 'risk', 'lead_lag')
_crypto_worker_thread_lock = threading.Lock()


def _crypto_worker_lock_path() -> str:
    """Return the process-wide lock path without caching a mutable Config path."""
    return os.path.join(Config.DATA_DIR, 'runtime', 'crypto_pipeline_worker.lock')


def _crypto_execution_lock_path() -> str:
    """Worker-held lock that survives an unexpected parent process exit."""
    return os.path.join(Config.DATA_DIR, 'runtime', 'crypto_pipeline_execution.lock')


def _crypto_attempt_state_path() -> str:
    return os.path.join(Config.DATA_DIR, 'runtime', 'crypto_pipeline_attempt.json')


def _record_crypto_attempt(slot: datetime, attempted_at: Optional[datetime] = None) -> None:
    """Persist an attempt separately from the last verified-success record."""
    current = attempted_at or datetime.now()
    write_json_atomic(
        _crypto_attempt_state_path(),
        {
            'schema_version': _CRYPTO_ATTEMPT_SCHEMA,
            'slot': slot.isoformat(timespec='minutes'),
            'attempted_at': current.isoformat(timespec='seconds'),
        },
    )


def _crypto_retry_allowed(slot: datetime, now: Optional[datetime] = None) -> bool:
    """Throttle repeated catch-up failures without marking the slot successful."""
    try:
        with open(_crypto_attempt_state_path(), 'r', encoding='utf-8') as handle:
            state = json.load(handle)
        if not isinstance(state, dict) or state.get('schema_version') != _CRYPTO_ATTEMPT_SCHEMA:
            return True
        if state.get('slot') != slot.isoformat(timespec='minutes'):
            return True
        attempted_at = _parse_iso_datetime(state.get('attempted_at'))
        if attempted_at is None:
            return True
        elapsed = ((now or datetime.now()).timestamp() - attempted_at.timestamp())
        return elapsed >= Config.CRYPTO_FAILURE_RETRY_MINUTES * 60
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return True


def _crypto_artifact_specs() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Return each required artifact with its contract timestamp field."""
    return (
        (os.path.join(Config.CRYPTO_OUTPUT_DIR, 'market_gate.json'), ('generated_at',)),
        (os.path.join(Config.DATA_DIR, 'vcp_crypto_latest.json'), ('metadata', 'generated_at')),
        (os.path.join(Config.CRYPTO_OUTPUT_DIR, 'crypto_briefing.json'), ('timestamp',)),
        (os.path.join(Config.CRYPTO_OUTPUT_DIR, 'btc_prediction.json'), ('timestamp',)),
        (os.path.join(Config.CRYPTO_OUTPUT_DIR, 'crypto_risk.json'), ('timestamp',)),
        (os.path.join(Config.CRYPTO_MARKET_DIR, 'lead_lag', 'results.json'), ('metadata', 'generated_at')),
    )


def _crypto_artifact_paths() -> tuple[str, ...]:
    return tuple(path for path, _ in _crypto_artifact_specs())


def _valid_crypto_artifact_shape(step: str, payload: dict) -> bool:
    """Reject fresh timestamps that contain no usable analysis result."""
    if step == 'gate':
        score = payload.get('score')
        return (
            str(payload.get('gate', '')).upper() in {'GREEN', 'YELLOW', 'RED'}
            and isinstance(score, (int, float))
            and not isinstance(score, bool)
            and isinstance(payload.get('metrics'), dict)
            and bool(payload['metrics'])
            and isinstance(payload.get('reasons'), list)
        )
    if step == 'vcp':
        metadata = payload.get('metadata')
        universe_size = metadata.get('universe_size') if isinstance(metadata, dict) else None
        return (
            isinstance(metadata, dict)
            and str(metadata.get('market', '')).upper() == 'CRYPTO'
            and isinstance(universe_size, int)
            and not isinstance(universe_size, bool)
            and universe_size > 0
            and isinstance(payload.get('signals'), list)
            and isinstance(payload.get('summary'), dict)
        )
    if step == 'briefing':
        return (
            isinstance(payload.get('market_summary'), dict)
            and bool(payload['market_summary'])
            and isinstance(payload.get('major_coins'), dict)
            and bool(payload['major_coins'])
        )
    if step == 'prediction':
        predictions = payload.get('predictions')
        return (
            isinstance(predictions, dict)
            and isinstance(predictions.get('BTC'), dict)
            and bool(predictions['BTC'])
        )
    if step == 'risk':
        summary = payload.get('portfolio_summary')
        total_coins = summary.get('total_coins') if isinstance(summary, dict) else None
        return (
            isinstance(summary, dict)
            and isinstance(total_coins, int)
            and not isinstance(total_coins, bool)
            and total_coins > 0
            and str(summary.get('risk_level', '')).upper() != 'NO_DATA'
            and isinstance(payload.get('correlation_matrix'), dict)
        )
    if step == 'lead_lag':
        return isinstance(payload.get('lead_lag'), list) and bool(payload['lead_lag'])
    return False


def _snapshot_crypto_artifacts() -> dict[str, dict[str, object]]:
    """Capture readable payloads, timestamps, and absent paths before a run."""
    snapshot: dict[str, dict[str, object]] = {}
    for artifact_path in _crypto_artifact_paths():
        try:
            artifact_stat = os.stat(artifact_path)
            with open(artifact_path, 'r', encoding='utf-8') as handle:
                payload = json.load(handle)
            snapshot[artifact_path] = {
                'existed': True,
                'payload': payload,
                'atime_ns': artifact_stat.st_atime_ns,
                'mtime_ns': artifact_stat.st_mtime_ns,
            }
        except FileNotFoundError:
            snapshot[artifact_path] = {'existed': False}
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    return snapshot


def _restore_crypto_artifacts(snapshot: dict[str, dict[str, object]]) -> None:
    """Restore the exact pre-run presence and freshness state after a failure."""
    for artifact_path, state in snapshot.items():
        try:
            if state.get('existed') is False:
                Path(artifact_path).unlink(missing_ok=True)
                continue
            write_json_atomic(artifact_path, state['payload'])
            atime_ns = state.get('atime_ns')
            mtime_ns = state.get('mtime_ns')
            if type(atime_ns) is int and type(mtime_ns) is int:
                os.utime(artifact_path, ns=(atime_ns, mtime_ns))
        except Exception as exc:
            logger.error(
                "Crypto artifact rollback failed (%s)",
                type(exc).__name__,
            )


def _run_crypto_pipeline_core() -> dict[str, bool]:
    """Run the native Crypto stages inside the short-lived worker process only."""
    logger.info("=" * 60)
    logger.info("🪙 Crypto 전체 파이프라인 시작 (4시간 주기)")
    logger.info("=" * 60)

    start_time = time.time()
    stages = (
        ('Gate Check', 'gate', run_crypto_gate_check),
        ('VCP Scan', 'vcp', run_crypto_vcp_scan),
        ('Briefing', 'briefing', run_crypto_briefing),
        ('Prediction', 'prediction', run_crypto_prediction),
        ('Risk', 'risk', run_crypto_risk),
        ('Lead-Lag', 'lead_lag', run_crypto_leadlag),
    )
    results = [(label, key, bool(task())) for label, key, task in stages]

    # 7. Briefing 텔레그램 알림
    notify_crypto_briefing()

    elapsed = time.time() - start_time
    success_count = sum(1 for _, _, ok in results if ok)
    total_count = len(results)

    for name, _, ok in results:
        status = "✅" if ok else "❌"
        logger.info(f"  {status} {name}")

    logger.info(f"🪙 Crypto 파이프라인 완료: {success_count}/{total_count} ({elapsed:.0f}초)")

    # 개별 실패 알림
    failed = [name for name, _, ok in results if not ok]
    if failed:
        send_telegram(
            f"⚠️ <b>Crypto 파이프라인 부분 실패</b>\n\n"
            f"성공: {success_count}/{len(results)}\n"
            f"실패: {', '.join(failed)}\n"
            f"시간: {datetime.now().strftime('%H:%M')}",
            channel=False
        )

    return {key: ok for _, key, ok in results}


def _validate_crypto_worker_result(
    result_path: Path,
    run_id: str,
    launch_epoch: float,
) -> tuple[bool, str]:
    """Validate the worker manifest and content timestamps without trusting mtime."""
    try:
        with result_path.open('r', encoding='utf-8') as handle:
            payload = json.load(handle)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False, 'manifest_unreadable'

    if not isinstance(payload, dict):
        return False, 'manifest_shape'
    if payload.get('schema_version') != _CRYPTO_WORKER_SCHEMA:
        return False, 'manifest_schema'
    if payload.get('run_id') != run_id:
        return False, 'manifest_run_id'
    if payload.get('status') != 'succeeded' or payload.get('ok') is not True:
        return False, 'worker_failed'

    child_pid = payload.get('pid')
    if type(child_pid) is not int or child_pid <= 0 or child_pid == os.getpid():
        return False, 'manifest_pid'

    started_at = _parse_iso_datetime(payload.get('started_at'))
    completed_at = _parse_iso_datetime(payload.get('completed_at'))
    if started_at is None or completed_at is None or completed_at < started_at:
        return False, 'manifest_time'

    steps = payload.get('steps')
    if not isinstance(steps, dict) or set(steps) != set(_CRYPTO_STEP_KEYS):
        return False, 'manifest_steps'
    if any(steps[key] is not True for key in _CRYPTO_STEP_KEYS):
        return False, 'stage_failed'

    if parse_datetime_value is None:
        return False, 'freshness_unavailable'
    for step, (artifact_path, timestamp_path) in zip(
        _CRYPTO_STEP_KEYS,
        _crypto_artifact_specs(),
    ):
        try:
            with open(artifact_path, 'r', encoding='utf-8') as handle:
                artifact = json.load(handle)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return False, 'artifact_unreadable'
        timestamp_value = artifact
        for key in timestamp_path:
            if not isinstance(timestamp_value, dict) or key not in timestamp_value:
                return False, 'artifact_timestamp_missing'
            timestamp_value = timestamp_value[key]
        content_time = parse_datetime_value(timestamp_value)
        if content_time is None or content_time.timestamp() < launch_epoch:
            return False, 'artifact_stale'
        if not isinstance(artifact, dict) or not _valid_crypto_artifact_shape(step, artifact):
            return False, 'artifact_empty'

    return True, 'ok'


def _is_trusted_crypto_worker_busy(result_path: Path, run_id: str) -> bool:
    """Recognize only this launch's fail-closed execution-lock contention."""
    try:
        with result_path.open('r', encoding='utf-8') as handle:
            payload = json.load(handle)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    child_pid = payload.get('pid')
    steps = payload.get('steps')
    started_at = _parse_iso_datetime(payload.get('started_at'))
    completed_at = _parse_iso_datetime(payload.get('completed_at'))
    return (
        payload.get('schema_version') == _CRYPTO_WORKER_SCHEMA
        and payload.get('run_id') == run_id
        and payload.get('status') == 'failed'
        and payload.get('ok') is False
        and payload.get('error_type') == 'WorkerBusy'
        and type(child_pid) is int
        and child_pid > 0
        and child_pid != os.getpid()
        and isinstance(steps, dict)
        and set(steps) == set(_CRYPTO_STEP_KEYS)
        and all(steps[key] is False for key in _CRYPTO_STEP_KEYS)
        and started_at is not None
        and completed_at is not None
        and completed_at >= started_at
    )


def _terminate_posix_process_tree_by_parentage(root_pid: int) -> bool:
    """Kill one POSIX process subtree without terminating its parent group."""
    try:
        completed = subprocess.run(
            ['ps', '-eo', 'pid=,ppid='],
            shell=False,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if completed.returncode != 0:
            return False
        children: dict[int, list[int]] = {}
        for line in completed.stdout.splitlines():
            fields = line.split()
            if len(fields) != 2:
                continue
            try:
                pid, ppid = (int(fields[0]), int(fields[1]))
            except ValueError:
                continue
            children.setdefault(ppid, []).append(pid)

        descendants: list[int] = []
        pending = list(children.get(root_pid, ()))
        while pending:
            pid = pending.pop()
            descendants.append(pid)
            pending.extend(children.get(pid, ()))

        for pid in reversed(descendants):
            try:
                os.kill(pid, signal_module.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            os.kill(root_pid, signal_module.SIGKILL)
        except ProcessLookupError:
            pass
        return True
    except Exception:
        return False


def _terminate_crypto_process_tree(process) -> None:
    """Terminate the still-running worker and every subprocess it started."""
    tree_terminated = False
    try:
        if os.name == 'nt':
            completed = subprocess.run(
                ['taskkill', '/PID', str(process.pid), '/T', '/F'],
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            tree_terminated = completed.returncode == 0
        else:
            process_group = os.getpgid(process.pid)
            if process_group == process.pid:
                os.killpg(process_group, signal_module.SIGKILL)
                tree_terminated = True
            else:
                tree_terminated = _terminate_posix_process_tree_by_parentage(process.pid)
    except Exception:
        tree_terminated = False

    if not tree_terminated:
        try:
            process.kill()
        except Exception:
            pass
    try:
        process.wait(timeout=30)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass
        try:
            process.wait(timeout=5)
        except Exception:
            pass


def _run_crypto_worker_process(
    command: list[str],
    popen_kwargs: dict,
    *,
    timeout: int,
) -> tuple[int, int]:
    """Wait for the worker and kill its process tree before releasing locks."""
    process = subprocess.Popen(command, **popen_kwargs)
    try:
        returncode = process.wait(timeout=timeout)
        if returncode != 0:
            _terminate_crypto_process_tree(process)
        return returncode, process.pid
    except BaseException:
        _terminate_crypto_process_tree(process)
        raise


def _launch_crypto_worker(*, no_notify: bool) -> Optional[bool]:
    """Return True/False for an attempt, or None for execution-lock contention."""
    run_id = uuid.uuid4().hex
    runtime_dir = Path(Config.DATA_DIR) / 'runtime'
    runtime_dir.mkdir(parents=True, exist_ok=True)
    result_path = runtime_dir / f'crypto_pipeline_worker_{run_id}.json'
    worker_script = Path(__file__).resolve().parent / 'scripts' / 'run_crypto_pipeline_worker.py'
    command = [
        Config.PYTHON_PATH,
        str(worker_script),
        '--run-id',
        run_id,
        '--result',
        str(result_path),
    ]
    if no_notify:
        command.append('--no-notify')

    worker_env = os.environ.copy()
    worker_env['KR_MARKET_DIR'] = Config.BASE_DIR
    worker_env['PYTHONPATH'] = Config.BASE_DIR
    worker_env['PYTHONIOENCODING'] = 'utf-8'
    worker_env['PYTHONUTF8'] = '1'
    worker_env['MARKETFLOW_PRESERVE_ENV'] = '1'
    if no_notify:
        telegram_keys = {
            key for key in worker_env if 'TELEGRAM' in key.upper()
        } | {
            'TELEGRAM_BOT_TOKEN',
            'TELEGRAM_CHAT_ID',
            'TELEGRAM_CHANNEL_BOT_TOKEN',
            'TELEGRAM_CHANNEL_CHAT_ID',
        }
        for key in telegram_keys:
            worker_env[key] = ''
    worker_env['MARKETFLOW_SCHEDULER_LOG_FILE'] = os.path.join(
        Config.LOG_DIR, 'crypto_pipeline_worker.log'
    )
    popen_kwargs = {
        'cwd': Config.BASE_DIR,
        'env': worker_env,
        'shell': False,
        'stdout': subprocess.DEVNULL,
        'stderr': subprocess.DEVNULL,
    }
    if os.name == 'nt':
        popen_kwargs['creationflags'] = (
            subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    elif os.getenv('MARKETFLOW_CRYPTO_INHERIT_PROCESS_GROUP', '').strip().lower() not in {
        '1', 'true', 'yes', 'on',
    }:
        popen_kwargs['start_new_session'] = True

    launch_epoch = time.time()
    try:
        returncode, _launcher_pid = _run_crypto_worker_process(
            command,
            popen_kwargs,
            timeout=Config.CRYPTO_PIPELINE_TIMEOUT,
        )
        if returncode != 0:
            if _is_trusted_crypto_worker_busy(result_path, run_id):
                logger.info("Crypto execution lock is busy; leaving live artifacts untouched")
                return None
            logger.error("Crypto worker failed (exit=%s)", returncode)
            return False
        valid, reason = _validate_crypto_worker_result(
            result_path,
            run_id,
            launch_epoch,
        )
        if not valid:
            logger.error("Crypto worker result rejected (%s)", reason)
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.error("Crypto worker timed out")
        return False
    except Exception as exc:
        logger.error("Crypto worker launch failed (%s)", type(exc).__name__)
        return False
    finally:
        try:
            result_path.unlink(missing_ok=True)
        except OSError:
            pass


def run_crypto_pipeline(skip_sync: bool = False, no_notify: bool = False) -> bool:
    """Run Crypto in a dedicated process, then optionally sync validated output."""
    if not _crypto_worker_thread_lock.acquire(blocking=False):
        logger.info("Crypto worker already running in this scheduler; skipping duplicate")
        return False

    try:
        if FileLock is None or FileLockTimeout is None:
            logger.error("Crypto worker process lock is unavailable")
            return False

        lock_path = _crypto_worker_lock_path()
        Path(lock_path).parent.mkdir(parents=True, exist_ok=True)
        try:
            with FileLock(lock_path, timeout=0):
                artifact_snapshot = _snapshot_crypto_artifacts()
                attempt_slot = _latest_crypto_slot(datetime.now(), include_current=True)
                analysis_ok = _launch_crypto_worker(no_notify=no_notify)
                if analysis_ok is None:
                    return False
                if attempt_slot is not None:
                    try:
                        _record_crypto_attempt(attempt_slot)
                    except Exception as exc:
                        logger.warning(
                            "Crypto attempt state write failed (%s)",
                            type(exc).__name__,
                        )
                if analysis_ok is False:
                    _restore_crypto_artifacts(artifact_snapshot)
                    return False

                if not skip_sync:
                    try:
                        if not auto_git_push('crypto'):
                            logger.warning("Crypto output Git sync did not complete")
                    except Exception as exc:
                        logger.warning("Crypto output Git sync failed (%s)", type(exc).__name__)
                return True
        except FileLockTimeout:
            logger.info("Crypto worker process lock is busy; skipping duplicate")
            return False
        except Exception as exc:
            logger.error("Crypto worker lock failed (%s)", type(exc).__name__)
            return False
    finally:
        _crypto_worker_thread_lock.release()


# ============================================================
# 전체 업데이트
# ============================================================

def run_full_update():
    """전체 올 업데이트 (--now) — 5개 작업 순차 실행 + 통합 sync/deploy + 텔레그램"""
    logger.info("=" * 60)
    logger.info("🌐 전체 올 업데이트 시작 — US + KR + Crypto")
    logger.info("=" * 60)

    overall_start = time.time()

    tasks = [
        ("US Market",   "🇺🇸", lambda: run_us_market_update(skip_sync=True)),
        ("KR 종가베팅",  "🇰🇷", lambda: run_kr_full_update(skip_sync=True)),
        ("VCP KR·US",    "📈", lambda: run_vcp_all_markets(skip_sync=True)),
        ("Crypto",      "🪙", lambda: run_crypto_pipeline(skip_sync=True)),
    ]

    results = []  # (label, emoji, success, elapsed)

    for label, emoji, task_fn in tasks:
        task_start = time.time()
        try:
            success = task_fn()
            if success is None:
                success = True
        except Exception as e:
            logger.error(f"❌ {label} 예외: {e}")
            success = False
        elapsed = time.time() - task_start
        results.append((label, emoji, success, elapsed))
        status = "✅" if success else "❌"
        logger.info(f"{status} {emoji} {label} ({elapsed:.0f}초)")

    # ── Git 자동 커밋 + 푸시 (→ Render 자동 배포) ──
    git_ok = auto_git_push('all')

    # ── 통합 텔레그램 요약 ──
    overall_elapsed = int(time.time() - overall_start)
    success_count = sum(1 for _, _, s, _ in results if s)
    total_count = len(results)
    hour_str = datetime.now().strftime('%H:%M')
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')

    task_lines = []
    for label, emoji, success, _ in results:
        icon = "✅" if success else "❌"
        task_lines.append(f"  {icon} {emoji} {label}")

    if not _scheduler_git_sync_enabled():
        git_text = "⏭️ Git 자동 동기화 비활성 (의도적 스킵)"
    else:
        git_text = "✅ Git 푸시 완료" if git_ok else "❌ Git 푸시 실패"

    msg = (
        f"<b>🌐 {hour_str} 전체 올 업데이트 완료</b>\n"
        f"⏰ {now_str} ({overall_elapsed}초)\n"
        f"결과: {success_count}/{total_count}\n\n"
        + "\n".join(task_lines)
        + f"\n\n📦 {git_text}"
    )

    send_telegram(msg, channel=False)
    logger.info(f"🌐 전체 업데이트 완료: {success_count}/{total_count} ({overall_elapsed}초)")

    return success_count == total_count


# ============================================================
# 마지막 실행 기록 (missed schedule recovery용)
# ============================================================

_LAST_RUN_FILE = os.path.join(Config.DATA_DIR, 'scheduler_last_run.json')
_HEARTBEAT_FILE = os.path.join(Config.DATA_DIR, 'scheduler_heartbeat.json')


def write_heartbeat():
    """데몬 살아있음 신호 파일. 외부 watchdog 가 mtime 으로 stale 판정.

    실패는 조용히 무시 (디스크 일시 오류로 데몬을 죽이지 않음).
    """
    try:
        os.makedirs(Config.DATA_DIR, exist_ok=True)
        tmp = _HEARTBEAT_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({
                'pid': os.getpid(),
                'ts': datetime.now().isoformat(timespec='seconds'),
            }, f)
        os.replace(tmp, _HEARTBEAT_FILE)
    except Exception:
        pass


def start_heartbeat_thread():
    """전용 heartbeat 스레드.

    메인 스레드가 startup catch-up (예: ai_chart 100종목, 5-15분 소요)
    같은 장시간 작업에 묶여 있어도 외부 watchdog 가 false positive 로
    데몬을 죽이지 않도록, heartbeat 만 별도 스레드에서 매 30초 갱신한다.

    Daemon thread 라 메인 프로세스 종료 시 자동 정리.
    """
    def _loop():
        while True:
            write_heartbeat()
            time.sleep(30)
    t = threading.Thread(target=_loop, name='heartbeat-writer', daemon=True)
    t.start()
    return t


_last_run_lock = threading.Lock()


def _load_last_run() -> dict:
    """scheduler_last_run.json 로드 (원자적 읽기, 손상 시 리셋)"""
    try:
        if os.path.exists(_LAST_RUN_FILE):
            with open(_LAST_RUN_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                logger.error("⚠️ scheduler_last_run.json 형식 오류, 리셋")
                return {}
            return data
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"⚠️ scheduler_last_run.json 읽기 실패 (리셋): {e}")
        # 손상된 파일 삭제
        try:
            os.remove(_LAST_RUN_FILE)
        except OSError:
            pass
    return {}


def _save_last_run(data: dict):
    """scheduler_last_run.json 원자적 저장 (임시파일 → rename)"""
    try:
        import tempfile
        dir_path = os.path.dirname(_LAST_RUN_FILE)
        with tempfile.NamedTemporaryFile(mode='w', dir=dir_path,
                                         suffix='.tmp', delete=False,
                                         encoding='utf-8') as f:
            temp_path = f.name
            json.dump(data, f, ensure_ascii=False, indent=2)
        # 원자적 교체 (Windows: os.replace가 원자적)
        os.replace(temp_path, _LAST_RUN_FILE)
    except Exception as e:
        logger.warning(f"⚠️ scheduler_last_run.json 저장 실패: {e}")
        try:
            if 'temp_path' in locals():
                os.remove(temp_path)
        except OSError:
            pass


def record_task_run(task_key: str):
    """작업 완료 후 마지막 실행 시각 기록 (스레드 안전)"""
    with _last_run_lock:
        data = _load_last_run()
        data[task_key] = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
        _save_last_run(data)
    logger.debug(f"📝 작업 기록 업데이트: {task_key}")


def _was_run_recently(task_key: str, hours: float = 4) -> bool:
    """해당 task_key가 최근 N시간 내 실행되었는지 확인 (자정 경계 안전, 락 보호)

    hours 는 float 허용 — 10분 주기 같은 짧은 쿨다운은 hours=0.17 형태로 지정.
    """
    with _last_run_lock:
        data = _load_last_run()
    last_run_str = data.get(task_key)
    if not last_run_str:
        return False
    try:
        last_run = datetime.strptime(last_run_str, '%Y-%m-%dT%H:%M:%S')
        elapsed = (datetime.now() - last_run).total_seconds()
        return elapsed < hours * 3600
    except (ValueError, TypeError):
        return False


def _latest_crypto_slot(now: datetime, *, include_current: bool) -> Optional[datetime]:
    """Return the fixed Crypto slot owned by a catch-up or scheduled invocation."""
    valid_times = _valid_hhmm_times(Config.CRYPTO_TIMES, 'CRYPTO_TIMES')
    candidates = []
    for day_offset in (0, -1):
        day = (now + timedelta(days=day_offset)).date()
        for hhmm in valid_times:
            hour, minute = (int(part) for part in hhmm.split(':', 1))
            slot = datetime(day.year, day.month, day.day, hour, minute)
            is_eligible = slot <= now if include_current else slot < now
            if is_eligible:
                candidates.append(slot)
    return max(candidates) if candidates else None


def _crypto_slot_due(
    now: datetime,
    *,
    include_current: bool,
) -> tuple[bool, Optional[datetime]]:
    """Return whether the latest fixed slot lacks a successful completion."""
    slot = _latest_crypto_slot(now, include_current=include_current)
    if slot is None:
        return False, None

    with _last_run_lock:
        last_run_raw = _load_last_run().get('crypto')
    last_run = _parse_iso_datetime(last_run_raw)
    return last_run is None or last_run < slot, slot


def _was_run_today(task_key: str) -> bool:
    """해당 task_key가 오늘 실행됐거나 최근 2시간 내 실행됐는지 (자정 경계 안전, 락 보호)"""
    with _last_run_lock:
        data = _load_last_run()
    last_run_str = data.get(task_key)
    if not last_run_str:
        return False
    try:
        last_run = datetime.strptime(last_run_str, '%Y-%m-%dT%H:%M:%S')
        # 오늘 날짜 OR 최근 2시간 이내 (자정 경계 보호)
        if last_run.date() == datetime.now().date():
            return True
        elapsed = (datetime.now() - last_run).total_seconds()
        return elapsed < 2 * 3600  # 2시간 이내면 "이미 실행됨"
    except (ValueError, TypeError):
        return False


def _jongga_artifact_is_today(now=None) -> bool:
    """Use the durable V2 artifact as an idempotency signal after restarts.

    The manifest is recorded after the entire KR follow-up pipeline. If the
    scheduler restarts after V2 persisted its result but before that later
    record, catch-up must not rerun the costly engine or resend its alerts.
    """
    current = now or datetime.now()
    path = os.path.join(Config.DATA_DIR, 'jongga_v2_latest.json')
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            payload = json.load(handle)
        raw_date = str(payload.get('date') or '').strip()
        if raw_date:
            normalized = raw_date[:10].replace('.', '-').replace('/', '-')
            return normalized == current.strftime('%Y-%m-%d')
        return datetime.fromtimestamp(os.path.getmtime(path)).date() == current.date()
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


# ============================================================
# 놓친 스케줄 복구 (Missed Schedule Recovery)
# ============================================================

_missed_check_lock = threading.Lock()

def check_and_run_missed_tasks():
    """스케줄러 시작 시 오늘 놓친 작업을 즉시 실행

    PC 재부팅/슬립으로 스케줄러가 죽었다가 재시작될 때,
    이미 지난 스케줄 시각의 작업이 오늘 실행되지 않았으면 즉시 실행한다.
    """
    if not _missed_check_lock.acquire(blocking=False):
        logger.info("⏭️ 놓친 스케줄 점검 건너뜀 (이전 복구 작업 진행 중)")
        return
    try:
        now = datetime.now()
        weekday = now.weekday()  # 0=Mon, 5=Sat, 6=Sun
        hour_min = now.hour * 60 + now.minute

        logger.info("🔍 놓친 스케줄 점검 시작...")

        # ── 평일/요일별 전용 작업 ──
        # 등록된 모든 스케줄을 빠짐없이 catch-up 대상에 포함시킨다.
        # 한 작업이라도 빠지면 데몬 사망 시점 이후 그 슬롯은 영영 놓친다.
        # weekday_filter: None → 월~금 모두, set → 해당 요일에만 (0=Mon, 4=Fri, 5=Sat)
        weekday_tasks = [
            # (예정시각_분, task_key, 실행함수, 라벨, 마감시각_분, weekday_filter)
            # 마감시각: 이 시각 이후에는 실행하지 않음 (다음 작업과 충돌 방지)
            (4 * 60,       'us_market',        run_us_market_update,        'US 마켓 전체 갱신',  14 * 60, None),
            (4 * 60 + 30,  'us_ai_chart',      _run_us_ai_chart_analysis,   'US AI Chart 분석',   14 * 60, None),  # 04:00 us_market 와 분리
            (9 * 60,       'morning_report',   send_morning_status_report,  '일별 상태 리포트',   14 * 60, None),
            (9 * 60 + 5,   'morning_briefing', run_morning_briefing,        'AI 조간 브리핑',     14 * 60, None),
            (9 * 60 + 30,  'us_track',         save_us_track_record_snapshot,'US Track Record',   14 * 60, None),
            (11 * 60,      'kr_vcp_morning',   run_kr_vcp_morning_refresh,  'KR VCP 오전 Refresh', 14 * 60, None),
            (14 * 60,      'ai_chart',         _run_ai_chart_analysis,      'KR AI Chart 분석',   23 * 60, None),
            (14 * 60 + 50, 'kr_jongga',        run_kr_full_update,          'KR 종가베팅',        23 * 60, None),
            (16 * 60,      'vcp_all',          run_vcp_all_markets,         'VCP KR·US',          23 * 60, None),
            (16 * 60 + 5,  'closing_briefing', run_closing_briefing,        'AI 마감 브리핑',     23 * 60, None),
            (16 * 60 + 30, 'wave_scan',        _run_wave_scan,              'Wave 패턴 스캔',     23 * 60, None),
            (17 * 60 + 30, 'buy_screen',       _run_buy_candidate_screen,   'AI 매수 후보 선별',  23 * 60, None),
            (8 * 60 + 30,  'alpha_morning_top', _run_alpha_morning_top,     '알파 모닝 브리핑',   14 * 60, None),
            (15 * 60,      'alpha_close_signals', _run_alpha_close_signals, '알파 매매신호',      23 * 60, None),
            (18 * 60,      'alpha_performance_brief', _run_alpha_performance_brief, '알파 성과 브리핑', 23 * 60, None),
            # ── 금요일 전용 ──
            (17 * 60,      'lotto_analysis',   run_lotto_analysis,          'AI 로또 분석 게시',  23 * 60, {4}),
            # ── 토요일 전용 ──
            (10 * 60,      'history',          collect_historical_institutional, '히스토리 수집',  23 * 60, {5}),
        ]

        # ── AI Brain 판단 캐시 프리웜 (고정시각 슬롯도 invariant 대로 catch-up 포함) ──
        # 마감은 슬롯 +90분: 그 이후엔 가드 웜업·온디맨드 캐시가 대체하므로 복구 가치가 낮다.
        if Config.AIBRAIN_GUARD_ENABLED:
            for hm in _valid_hhmm_times(Config.AIBRAIN_PREWARM_TIMES, 'AIBRAIN_PREWARM_TIMES'):
                hh, mm = hm.split(':')
                slot_min = int(hh) * 60 + int(mm)
                weekday_tasks.append(
                    (slot_min, f"aibrain_prewarm_{hm.replace(':', '')}", run_aibrain_prewarm,
                     f'AI Brain 판단 프리웜 {hm}', min(slot_min + 90, 23 * 60 + 59), None))

        recovered = []

        # 평일/요일별 작업 복구
        for sched_min, task_key, task_fn, label, deadline_min, wd_filter in weekday_tasks:
            # 요일 필터: None=월~금, set={요일번호} 에만 실행
            if wd_filter is None:
                if weekday >= 5:  # 주말 제외
                    continue
            else:
                if weekday not in wd_filter:
                    continue

            if hour_min < sched_min:
                continue  # 아직 예정 시각 전 (== 시각이면 catch-up 대상에 포함)
            if hour_min > deadline_min:
                logger.info(f"  ⏭️ {label}: 마감 지남 ({deadline_min//60}:{deadline_min%60:02d}), 스킵")
                continue
            if task_key == 'kr_jongga' and not _kr_market_task_allowed('kr_jongga_missed_recovery', now):
                continue
            if task_key == 'kr_jongga' and _jongga_artifact_is_today(now):
                logger.info("  KR closing-bet artifact already updated today; repairing manifest and skipping catch-up")
                record_task_run(task_key)
                continue
            if _was_run_today(task_key):
                logger.info(f"  ✅ {label}: 오늘 이미 실행됨, 스킵")
                continue

            logger.info(f"  ⚠️ 놓친 스케줄 감지: {label} (예정 {sched_min//60:02d}:{sched_min%60:02d}) → 즉시 실행")
            try:
                result = task_fn()
                success = result if result is not None else True
                if not success:
                    logger.error(f"  ❌ 복구 실패: {label} — 작업이 실패 결과 반환")
                    continue
                record_task_run(task_key)
                recovered.append(label)
                logger.info(f"  ✅ 복구 완료: {label}")
            except Exception as e:
                logger.error(f"  ❌ 복구 실패: {label} — {e}", exc_info=True)

        # Crypto 복구 (주말 포함): 현재 시각보다 이전인 최신 고정 슬롯만 소유한다.
        crypto_due, crypto_slot = _crypto_slot_due(now, include_current=False)
        if (
            crypto_due
            and crypto_slot is not None
            and not _crypto_retry_allowed(crypto_slot, now)
        ):
            logger.info(
                "  ⏭️ Crypto 파이프라인 실패 재시도 대기 중 (슬롯 %s, %s분 backoff)",
                crypto_slot.strftime('%Y-%m-%d %H:%M'),
                Config.CRYPTO_FAILURE_RETRY_MINUTES,
            )
        elif crypto_due and crypto_slot is not None:
            logger.info(
                "  ⚠️ 놓친 Crypto 파이프라인 감지 (최근 예정 %s) → 즉시 실행",
                crypto_slot.strftime('%Y-%m-%d %H:%M'),
            )
            try:
                if run_crypto_pipeline():
                    record_task_run('crypto')
                    recovered.append('Crypto 파이프라인')
                    logger.info("  ✅ 복구 완료: Crypto 파이프라인")
                else:
                    logger.error("  ❌ 복구 실패: Crypto 파이프라인 worker 결과 불충족")
            except Exception as exc:
                logger.error(
                    "  ❌ 복구 실패: Crypto 파이프라인 (%s)",
                    type(exc).__name__,
                )

        if recovered:
            logger.info(f"🔄 놓친 스케줄 복구: {len(recovered)}개 — {', '.join(recovered)}")
        else:
            logger.info("✅ 놓친 스케줄 없음 (모두 정상)")
    finally:
        _missed_check_lock.release()


# ============================================================
# Wave 패턴 스캔
# ============================================================

def _run_kis_token_warmup() -> bool:
    """KIS OpenAPI 토큰 예열 — 장 시작 직전 토큰 갱신 및 실패 시 텔레그램 알림.

    lazy 리프레시 구조(`get_token()`)가 있지만, 자격증명/네트워크 문제를 장 시작
    이후가 아닌 장 시작 전에 감지하기 위한 방어적 웜업 job.
    """
    logger.info("=" * 60)
    logger.info("🔑 KIS 토큰 웜업 시작")
    logger.info("=" * 60)
    try:
        from app.services.kis_screener import invalidate_token, get_token
        invalidate_token()  # 캐시 강제 만료 → 실제 API 호출 경로 검증
        tok = get_token()
        if not tok:
            logger.error("❌ KIS 토큰 웜업 실패 — 자격증명/네트워크 확인 필요")
            return False
        logger.info(f"✅ KIS 토큰 웜업 완료 (len={len(tok)})")
        return True
    except Exception as e:
        logger.error(f"❌ KIS 토큰 웜업 에러: {e}", exc_info=True)
        try:
            send_telegram(f"⚠️ KIS 토큰 웜업 에러: {type(e).__name__}: {e}", channel=False)
        except Exception:
            pass
        return False


def run_omni_news_sweep() -> bool:
    """옴니소스 O1 — 공개 뉴스 RSS 수집 → 결정론 깔때기 → 사건 원장.

    읽기전용 센서: 발송·주문·LLM 경로가 없다. 소스 장애는 격리된다.
    """
    try:
        from app.services.omni.news_sensor import run_news_sweep

        result = run_news_sweep()
        if result.get('status') == 'disabled':
            return True
        logger.info("Omni news sweep: fetched=%s kept=%s saved=%s errors=%s",
                    result.get('fetched'), result.get('kept'), result.get('saved'),
                    list(result.get('errors') or {}))
        # 전 소스 실패 = 수집 자체가 죽은 것 (프록시/DNS 장애 등).
        # 성공으로 기록하면 _with_record 의 재시도·운영 알림이 전부 막히므로 실패로 보고한다.
        sources = result.get('sources') or []
        errors = result.get('errors') or {}
        if sources and not result.get('fetched') and set(errors) >= set(sources):
            logger.error("Omni news sweep: all %d sources failed — reporting failure", len(sources))
            return False
        return True
    except Exception as e:
        logger.error("Omni news sweep failed: %s", e)
        return False


def _run_claw_outcome_update() -> bool:
    """성숙한 Claw D1/D5 관측 결과만 채운다 (shadow-only)."""
    try:
        from marketflow_claw.observation import update_mature_outcomes

        result = update_mature_outcomes()
        if result.get('ok'):
            logger.info(
                "Claw outcome shadow update complete: completed=%s missing=%s pending=%s as_of=%s",
                result.get('completed'), result.get('missing'), result.get('still_pending'),
                result.get('data_as_of'),
            )
            return True
        logger.error("Claw outcome shadow update failed: %s", result.get('error'))
        return False
    except Exception as e:
        logger.error("Claw outcome shadow update error: %s: %s", type(e).__name__, e)
        return False


def _run_kiwoom_ai_theme() -> bool:
    """키움 AI전략 테마 랭커 — 장중 15분 주기. 장외엔 자동 skip.

    성공 시 scripts/send_kiwoom_theme_telegram.py 호출 — 시간당 1회 쿨다운으로
    TOP 15 를 개인 봇에 전송. 실패해도 랭킹 업데이트 성공 판정 유지.
    """
    now = datetime.now()
    if now.weekday() >= 5:
        return True
    hm = now.hour * 60 + now.minute
    if not (9 * 60 + 10 <= hm <= 15 * 60 + 25):
        return True
    try:
        import asyncio
        from engine.kiwoom_theme_ranker import update_ai_theme_ranking
        result = asyncio.run(update_ai_theme_ranking(top_n=15))
        logger.info(f"🤖 키움 AI전략 테마: executed={result['executed']}/{result['total_conditions']} unique={result['unique_stocks']}")

        # 텔레그램 푸시 (시간당 1회 쿨다운 — 스크립트 내부에서 처리)
        try:
            import subprocess
            tg_script = os.path.join(Config.BASE_DIR, 'scripts', 'send_kiwoom_theme_telegram.py')
            subprocess.run(
                [Config.PYTHON_PATH, tg_script],
                timeout=30,
                capture_output=True,
                text=True,
                env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
            )
        except Exception as tg_err:
            logger.warning(f"키움 AI 테마 텔레그램 전송 실패(무시): {type(tg_err).__name__}: {tg_err}")

        return True
    except Exception as e:
        logger.warning(f"키움 AI전략 테마 폴백: {type(e).__name__}: {e}")
        return False


def _run_orphan_file_audit() -> bool:
    """커뮤니티 업로드 orphan 파일 일일 점검.

    DB 에 file_url 이 기록됐으나 실제 디스크에 없는 post 를 감지해 관리자 개인 봇으로
    알림. 2026-04-14 dual-tunnel 업로드 실종 사고 재발 조기 감지용.
    """
    try:
        import os as _os
        from app import create_app
        app = create_app()
        with app.app_context():
            from app.models.community import Post
            upload_dir = _os.path.join(Config.BASE_DIR, 'data', 'uploads', 'community')
            if not _os.path.isdir(upload_dir):
                return True
            existing = set(_os.listdir(upload_dir))
            orphans = []
            for p in Post.query.filter(Post.file_url.isnot(None)).all():
                stored = p.file_url.rsplit('/', 1)[-1] if p.file_url else None
                if stored and stored not in existing:
                    orphans.append((p.id, p.title, p.file_name))
            if orphans:
                lines = [f"⚠️ <b>업로드 파일 유실 감지</b>", f"", f"총 {len(orphans)}건 orphan file_url:"]
                for pid, title, fname in orphans[:10]:
                    lines.append(f"  • #{pid} {str(title or '')[:30]} — {fname or '?'}")
                if len(orphans) > 10:
                    lines.append(f"  … 외 {len(orphans) - 10}건")
                send_telegram("\n".join(lines), channel=False)
                logger.warning(f"orphan files detected: {len(orphans)}")
            else:
                logger.info("✅ 업로드 파일 무결성 OK (orphan 0건)")
            return True
    except Exception as e:
        logger.warning(f"orphan audit 실패: {type(e).__name__}: {e}")
        return False


def _run_orphan_file_audit() -> bool:
    """Run community upload orphan audit in a fresh subprocess.

    The older in-process implementation called create_app() inside the
    long-lived scheduler. On the MiniPC this can trip PyO3 reinitialization
    errors after other analytics modules have already been imported. Running
    the DB/file audit in a short-lived child process keeps the scheduler stable.
    """
    try:
        script = os.path.join(Config.BASE_DIR, 'scripts', 'orphan_file_audit.py')
        env = {**os.environ, 'PYTHONPATH': Config.BASE_DIR, 'PYTHONIOENCODING': 'utf-8'}
        result = subprocess.run(
            [Config.PYTHON_PATH, script, '--json', '--max-orphans', '10'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=180,
            cwd=Config.BASE_DIR,
            env=env,
        )
        output = (result.stdout or '').strip()
        if result.returncode != 0:
            logger.warning(
                'orphan audit subprocess failed rc=%s stdout=%s stderr=%s',
                result.returncode,
                output[-500:],
                (result.stderr or '').strip()[-500:],
            )
            return False
        try:
            payload = json.loads(output)
        except json.JSONDecodeError as exc:
            logger.warning('orphan audit JSON parse failed: %s stdout=%s', exc, output[-500:])
            return False
        if not payload.get('ok'):
            logger.warning('orphan audit payload failed: %s', payload)
            return False

        total = int(payload.get('total') or 0)
        if total:
            lines = ["⚠️ <b>업로드 파일 유실 감지</b>", "", f"총 {total}건 orphan file_url:"]
            orphan_items = payload.get('orphans', [])[:10]
            for item in orphan_items:
                pid = item.get('post_id')
                title = str(item.get('title') or '')[:30]
                fname = item.get('file_name') or item.get('stored_filename') or '?'
                lines.append(f"  • #{pid} {title} → {fname}")
            if total > len(orphan_items):
                lines.append(f"  … 외 {total - len(orphan_items)}건")
            send_telegram("\n".join(lines), channel=False)
            logger.warning('orphan files detected: %s', total)
        else:
            logger.info(
                'community upload file integrity OK: orphan 0, scanned=%s',
                payload.get('scanned', 0),
            )
        return True
    except Exception as e:
        logger.warning(f"orphan audit failed: {type(e).__name__}: {e}")
        return False


def _alpha_market_open_now() -> bool:
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return 9 * 60 <= minutes <= 15 * 60 + 30


def _run_alpha_morning_top() -> bool:
    """08:30 — 알파스코어 상위 + 시장 4국면 → 텔레그램 (개인봇)."""
    try:
        from app.services.mirofish.paper_orchestrator import morning_top_message
        msg = morning_top_message()
        if msg:
            send_telegram(msg, channel=False)
        logger.info("🌅 알파 모닝 브리핑 발송 완료")
        return True
    except Exception as e:
        logger.error(f"❌ 알파 모닝 브리핑 실패: {e}", exc_info=True)
        return False


def _run_alpha_close_signals() -> bool:
    """15:00 — 신규 가상 진입 + 만료/CIO 청산 신호 → 텔레그램 (개인봇)."""
    try:
        from app.services.mirofish.paper_orchestrator import run_close_cycle
        result = run_close_cycle()
        if result.get('message'):
            send_telegram(result['message'], channel=False)
        logger.info(
            f"🔔 알파 매매신호: 검출수집 {result.get('ingested', 0)} · "
            f"진입 {len(result.get('entered', []))} · 청산 {len(result.get('exits', []))}"
        )
        return True
    except Exception as e:
        logger.error(f"❌ 알파 매매신호 실패: {e}", exc_info=True)
        return False


def _run_alpha_performance_brief() -> bool:
    """18:00 — 보유 현황 + 30일 완결 성과 브리핑 → 텔레그램 (개인봇)."""
    try:
        from app.services.mirofish.paper_orchestrator import performance_brief_message
        send_telegram(performance_brief_message(), channel=False)
        logger.info("📊 알파 성과 브리핑 발송 완료")
        return True
    except Exception as e:
        logger.error(f"❌ 알파 성과 브리핑 실패: {e}", exc_info=True)
        return False


def _run_alpha_intraday_watch() -> bool:
    """장중 10분 간격 — 보유 포지션 목표/손절 터치 즉시 신호. 장외 시간은 스킵."""
    if not _alpha_market_open_now():
        return True
    try:
        from app.services.mirofish.paper_orchestrator import run_intraday_watch
        result = run_intraday_watch()
        if result.get('message'):
            send_telegram(result['message'], channel=False)
            logger.info(f"⚡ 알파 장중 청산 신호 {len(result.get('exits', []))}건 발송")
        return True
    except Exception as e:
        logger.error(f"❌ 알파 장중 감시 실패: {e}", exc_info=True)
        return False


def _run_buy_candidate_screen() -> bool:
    """Local OHLCV rank -> at most 20 Vision calls -> at most 10 BUY picks.

    가격은 로컬 daily_prices.csv 를 쓰므로 14:50 KR 갱신 작업이 끝난 뒤에
    돌아야 당일 데이터가 반영된다. CLI/env 값과 무관하게 비용 상한은 고정된다.
    """
    if not _kr_market_task_allowed('buy_screen'):
        return True
    logger.info("=" * 60)
    logger.info(f"🟢 AI 매수 후보 선별 시작 (목표 {Config.BUY_SCREEN_TARGET}종목)")
    logger.info("=" * 60)

    try:
        script = os.path.join(Config.BASE_DIR, 'scripts', 'screen_buy_candidates.py')
        cmd = [Config.PYTHON_PATH, script,
               '--target', str(Config.BUY_SCREEN_TARGET),
               '--batch', str(Config.BUY_SCREEN_BATCH),
               '--max-universe', str(Config.BUY_SCREEN_MAX_UNIVERSE),
               '--vision-max-calls', str(Config.BUY_SCREEN_VISION_MAX_CALLS)]
        if Config.BUY_SCREEN_TO_CHANNEL:
            cmd.append('--channel')

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=3600,
            cwd=Config.BASE_DIR,
            env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
        )
        if result.returncode != 0:
            logger.error(f"❌ 매수 후보 선별 실패:\n{(result.stderr or '')[-800:]}")
            return False

        csv_path = os.path.join(Config.DATA_DIR, 'buy_candidates_kr.csv')
        if not os.path.exists(csv_path):
            logger.error("❌ 매수 후보 CSV 미생성")
            return False
        import pandas as pd
        picks = pd.read_csv(csv_path, encoding='utf-8-sig')
        logger.info(f"🟢 매수 후보 선별 완료: {len(picks)}종목")
        if len(picks) < Config.BUY_SCREEN_TARGET:
            logger.info(f"ℹ️ 목표 {Config.BUY_SCREEN_TARGET}종목 미달 ({len(picks)}종목) "
                        "— 비용 상한 안에서 확인된 BUY만 유지")
        return True
    except subprocess.TimeoutExpired:
        logger.error("❌ 매수 후보 선별 타임아웃 (60분)")
        return False
    except Exception as e:
        logger.error(f"❌ 매수 후보 선별 실패: {e}", exc_info=True)
        return False


def _run_wave_scan() -> bool:
    """Wave 패턴 전 종목 스캔 (KR)"""
    logger.info("=" * 60)
    logger.info("🌊 Wave 패턴 스캔 시작 (KR)")
    logger.info("=" * 60)

    try:
        from engine.wave.screener import run_wave_scan
        result = run_wave_scan()
        count = result.get('signal_count', 0)
        elapsed = result.get('processing_time_sec', 0)
        logger.info(f"🌊 Wave 스캔 완료: {count}개 패턴 ({elapsed}초)")

        # DB 적재 + 시그널 추적 + 통계 갱신
        try:
            from app import create_app
            app = create_app()
            with app.app_context():
                from app.services.wave_tracker import (
                    save_screener_to_db, update_active_signals, refresh_pattern_stats
                )
                saved = save_screener_to_db(result)
                logger.info(f"🌊 DB 적재: {saved}건 신규 시그널")
                track_result = update_active_signals()
                logger.info(f"🌊 시그널 추적: {track_result}")
                refresh_pattern_stats()
                logger.info("🌊 패턴 통계 갱신 완료")
        except Exception as db_err:
            logger.warning(f"⚠️ Wave DB 처리 실패 (스캔은 성공): {db_err}")

        # S/A급 패턴 텔레그램 알림 (신뢰도 70 이상)
        top_signals = [s for s in result.get('signals', [])
                       if s['best_pattern']['confidence'] >= 70]
        if top_signals:
            lines = [f"<b>🌊 Wave 패턴 감지 ({len(top_signals)}개)</b>\n"]
            for s in top_signals[:10]:
                bp = s['best_pattern']
                emoji = '🟢' if bp['bullish_bias'] > 0 else '🔴'
                lines.append(
                    f"{emoji} <b>{s['name']}</b> ({s['ticker']}) "
                    f"| {bp['wave_label']} | 신뢰도 {bp['confidence']}점 "
                    f"| 넥라인 {bp['neckline_distance_pct']:+.1f}%"
                )
            send_telegram('\n'.join(lines))

        # Git 자동 커밋 + 푸시
        auto_git_push('wave')

        return True
    except Exception as e:
        logger.error(f"❌ Wave 스캔 실패: {e}", exc_info=True)
        return False


_AI_CHART_SIGNAL_STYLE = [
    ('BUY', '🟢', '매수'),
    ('HOLD', '🟡', '관망'),
    ('SELL', '🔴', '매도'),
]
# send_telegram_long 은 빈 줄("\n\n") 경계로만 자른다. 한 그룹이 통째로
# 4000자를 넘으면 못 자르므로, 그룹 안에서도 이 줄 수마다 경계를 넣는다.
_AI_CHART_ROWS_PER_BLOCK = 20


def format_ai_chart_message(df) -> str:
    """AI Chart 결과를 텔레그램 본문으로 — 분석한 종목을 전부 싣는다.

    예전에는 BUY 상위 10종목만 실어서 "100종목 분석"이라 써놓고 정작 목록은
    잘려 나갔다. 신호별로 묶고 확신도 내림차순으로 전부 나열한다.
    """
    counts = {sig: int((df['signal'] == sig).sum()) for sig, _, _ in _AI_CHART_SIGNAL_STYLE}
    head = [
        f"<b>🤖 AI Chart Analysis ({len(df)}종목)</b>",
        " | ".join(f"{icon} {sig}: {counts[sig]}" for sig, icon, _ in _AI_CHART_SIGNAL_STYLE),
    ]
    blocks = ["\n".join(head)]

    for sig, icon, label in _AI_CHART_SIGNAL_STYLE:
        sub = df[df['signal'] == sig].sort_values('confidence', ascending=False)
        if sub.empty:
            continue
        rows = [
            f"  {icon} <b>{r['종목명']}</b> ({r['종목코드']}) conf={r['confidence']}"
            for _, r in sub.iterrows()
        ]
        for i in range(0, len(rows), _AI_CHART_ROWS_PER_BLOCK):
            chunk = rows[i:i + _AI_CHART_ROWS_PER_BLOCK]
            title = (f"<b>{icon} {sig} · {label} ({len(sub)})</b>" if i == 0
                     else f"<b>{icon} {sig} (계속)</b>")
            blocks.append(title + "\n" + "\n".join(chunk))

    return "\n\n".join(blocks)


def _run_ai_chart_analysis() -> bool:
    """AI Chart Analysis — Gemini Vision 100종목 차트 분석"""
    logger.info("=" * 60)
    logger.info("🤖 AI Chart Analysis 시작 (Gemini Vision · KR 100종목)")
    logger.info("=" * 60)

    try:
        started_at = time.time()
        script = os.path.join(Config.BASE_DIR, 'main_kr.py')
        result = subprocess.run(
            [Config.PYTHON_PATH, script],
            capture_output=True, text=True, timeout=1800,
            cwd=Config.BASE_DIR,
            env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
        )
        if result.returncode == 0:
            # 결과 파일 확인
            csv_path = os.path.join(Config.BASE_DIR, 'gemini_chart_analysis_kr.csv')
            # 낡은 CSV 를 성공으로 오인 금지 — 이번 실행에서 갱신된 파일만 인정.
            # (2026-09-02: US 쪽에서 8/24 CSV 를 매일 '완료 98종목'으로 보고하던 거짓 성공 발견)
            if os.path.exists(csv_path) and os.path.getmtime(csv_path) < started_at:
                logger.error("❌ AI Chart CSV 미갱신 (stale, 전 회차 파일) — 분석 실패로 처리")
                return False
            if os.path.exists(csv_path):
                import pandas as pd
                df = pd.read_csv(csv_path, encoding='utf-8-sig')
                buy_count = len(df[df['signal'] == 'BUY'])
                logger.info(f"🤖 AI Chart 분석 완료: {len(df)}개 종목 (BUY: {buy_count})")

                # 텔레그램 알림 — 분석한 종목 전체 (BUY 상위 10개만 보내던 것을 교체)
                if len(df) > 0:
                    try:
                        send_telegram_long(format_ai_chart_message(df))
                    except Exception as e:
                        logger.warning(f"⚠️ KR AI Chart 텔레그램 전송 실패: {e}")

                auto_git_push('ai_chart')
                return True
            else:
                logger.error("❌ AI Chart CSV 파일 미생성")
                return False
        else:
            logger.error(f"❌ AI Chart 스크립트 실패:\n{result.stderr[-500:]}")
            return False
    except subprocess.TimeoutExpired:
        logger.error("❌ AI Chart 타임아웃 (30분)")
        return False
    except Exception as e:
        logger.error(f"❌ AI Chart 실패: {e}", exc_info=True)
        return False


def _run_us_ai_chart_analysis() -> bool:
    """US AI Chart Analysis — Gemini Vision S&P 500 Top 100"""
    logger.info("=" * 60)
    logger.info("🤖 US AI Chart Analysis 시작 (Gemini Vision · S&P 500 Top 100)")
    logger.info("=" * 60)

    try:
        started_at = time.time()
        script = os.path.join(Config.BASE_DIR, 'main_us.py')
        result = subprocess.run(
            [Config.PYTHON_PATH, script],
            capture_output=True, text=True, timeout=1800,
            cwd=Config.BASE_DIR,
            env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
        )
        if result.returncode == 0:
            csv_path = os.path.join(Config.BASE_DIR, 'gemini_chart_analysis_us.csv')
            # 낡은 CSV 를 성공으로 오인 금지 (8/24 정지를 매일 '완료'로 보고하던 버그)
            if os.path.exists(csv_path) and os.path.getmtime(csv_path) < started_at:
                logger.error("❌ US AI Chart CSV 미갱신 (stale, 전 회차 파일) — 분석 실패로 처리")
                return False
            if os.path.exists(csv_path):
                import pandas as pd
                df = pd.read_csv(csv_path, encoding='utf-8-sig')
                buy_count = len(df[df['signal'] == 'BUY'])
                logger.info(f"🤖 US AI Chart 분석 완료: {len(df)}개 종목 (BUY: {buy_count})")

                if buy_count > 0:
                    buy_df = df[df['signal'] == 'BUY'].sort_values('confidence', ascending=False)
                    lines = [f"<b>🤖 US AI Chart Analysis ({len(df)} stocks)</b>\n"]
                    lines.append(f"🟢 BUY: {buy_count} | 🟡 HOLD: {len(df[df['signal'] == 'HOLD'])} | 🔴 SELL: {len(df[df['signal'] == 'SELL'])}\n")
                    for _, row in buy_df.head(10).iterrows():
                        lines.append(f"  🟢 <b>{row['name']}</b> ({row['ticker']}) conf={row['confidence']}")
                    try:
                        send_telegram('\n'.join(lines))
                    except Exception as e:
                        logger.warning(f"⚠️ US AI Chart 텔레그램 전송 실패: {e}")

                auto_git_push('us_ai_chart')
                return True
            else:
                logger.error("❌ US AI Chart CSV 파일 미생성")
                return False
        else:
            logger.error(f"❌ US AI Chart 스크립트 실패:\n{result.stderr[-500:]}")
            return False
    except subprocess.TimeoutExpired:
        logger.error("❌ US AI Chart 타임아웃 (30분)")
        return False
    except Exception as e:
        logger.error(f"❌ US AI Chart 실패: {e}", exc_info=True)
        return False


# ============================================================
# 스케줄러
# ============================================================

class Scheduler:
    """통합 스케줄러 (US + KR + Crypto)"""

    def __init__(self):
        self.running = True
        signal_module.signal(signal_module.SIGINT, self._signal_handler)
        signal_module.signal(signal_module.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        logger.info(f"📛 종료 시그널 수신 (signal={signum})")
        self.running = False

    @staticmethod
    def _with_record(task_fn, task_key, max_retries=2, retry_delay=900, verify_fn=None):
        """작업 함수를 래핑: 실행 → 검증 → 실패 시 재시도 → 텔레그램 알림

        Args:
            task_fn: 실행할 작업 함수
            task_key: scheduler_last_run.json 키
            max_retries: 최대 재시도 횟수 (기본 2회 = 총 3회 시도)
            retry_delay: 재시도 간격 초 (기본 900초 = 15분)
            verify_fn: 결과 검증 함수 (None이면 리턴값만 체크)
        """
        def wrapper():
            def notify_ops(message: str):
                try:
                    return send_telegram(message, channel=False)
                except TypeError as exc:
                    if 'channel' not in str(exc):
                        raise
                    return send_telegram(message)

            # 중복 실행 방지 (catch-up 복구와의 충돌, 워치독 재시작 후 이중 실행 방지)
            # - crypto: Config.CRYPTO_TIMES 고정 슬롯별 1회 성공
            # - kiwoom_ai_theme: 장중 15분 주기 → 10분 쿨다운 (하루 1회 제한 해제)
            # - interval_cooldowns: 분 주기 interval job 은 주기의 0.8배 쿨다운
            #   (하루 1회 게이트에 걸리면 10~15분 주기가 하루 1회로 죽는다 — kiwoom_ai_theme 버그 재발 방지)
            # - 그 외: 하루 1회 제한
            interval_cooldowns = {
                'alpha_scanner_monitor': max(1 / 60, Config.ALPHA_SCANNER_MONITOR_INTERVAL_MINUTES / 60 * 0.8),
                'mirofish_workflow_monitor': max(1 / 60, Config.ALPHA_SCANNER_MONITOR_INTERVAL_MINUTES / 60 * 0.8),
                'omni_news_sweep': max(1 / 60, max(5, Config.OMNI_NEWS_INTERVAL_MINUTES) / 60 * 0.8),
                'aibrain_service_guard': max(1 / 60, Config.AIBRAIN_GUARD_INTERVAL_MINUTES / 60 * 0.8),
            }

            if task_key == 'crypto':
                crypto_due, crypto_slot = _crypto_slot_due(
                    datetime.now(), include_current=True
                )
                if not crypto_due:
                    slot_label = crypto_slot.isoformat(timespec='minutes') if crypto_slot else 'invalid'
                    logger.info(f"⏭️ {task_key}: 고정 슬롯 완료됨 ({slot_label}), 스킵")
                    return None
            elif task_key == 'kiwoom_ai_theme':
                # 장중 연속 갱신 허용: 10분 이내 재실행만 방지
                if _was_run_recently(task_key, hours=10/60):
                    logger.info(f"⏭️ {task_key}: 최근 10분 내 실행됨, 스킵")
                    return None
            elif task_key in interval_cooldowns:
                cooldown_hours = interval_cooldowns[task_key]
                if _was_run_recently(task_key, hours=cooldown_hours):
                    logger.info(f"??툘 {task_key}: interval cooldown active, skip")
                    return None
            elif _was_run_today(task_key):
                logger.info(f"⏭️ {task_key}: 오늘 이미 실행됨, 스킵")
                return None

            for attempt in range(1 + max_retries):
                try:
                    if attempt > 0:
                        logger.info(f"🔄 {task_key} 재시도 {attempt}/{max_retries} ({retry_delay}초 후)")
                        time.sleep(retry_delay)
                        if task_key == 'crypto':
                            retry_due, retry_slot = _crypto_slot_due(
                                datetime.now(), include_current=True
                            )
                            if not retry_due:
                                slot_label = (
                                    retry_slot.isoformat(timespec='minutes')
                                    if retry_slot else 'invalid'
                                )
                                logger.info(
                                    f"⏭️ {task_key}: 재시도 전 슬롯 완료 확인 "
                                    f"({slot_label}), 중복 실행 스킵"
                                )
                                return None

                    result = task_fn()

                    # 1차: 리턴값 체크 — 모든 task 함수는 명시적 bool 을 반환해야 함.
                    # `None` 은 "return 누락" 버그이므로 실패로 간주 (verify_fn 이 있으면 거기서 한 번 더 검증).
                    success = bool(result)
                    skip_verify = (
                        isinstance(result, dict)
                        and result.get('_scheduler_skip_verify') is True
                    )

                    # 2차: 검증 함수 체크 (파일 존재/데이터 유효성)
                    if success and verify_fn and not skip_verify:
                        try:
                            success = verify_fn()
                        except Exception as ve:
                            logger.warning(f"⚠️ {task_key} 검증 실패: {ve}")
                            success = False

                    if success:
                        record_task_run(task_key)
                        if attempt > 0:
                            notify_ops(f"✅ {task_key} 재시도 {attempt}회 만에 성공")
                        return result
                    else:
                        logger.warning(f"⚠️ {task_key} 실패 (시도 {attempt + 1}/{1 + max_retries})")

                except Exception as e:
                    logger.error(f"❌ {task_key} 예외 (시도 {attempt + 1}/{1 + max_retries}): {e}")

            # 모든 재시도 실패
            logger.error(f"🚨 {task_key} {1 + max_retries}회 시도 모두 실패!")
            notify_ops(
                f"🚨 <b>{task_key} 업데이트 실패</b>\n\n"
                f"총 {1 + max_retries}회 시도 후 실패\n"
                f"수동 확인 필요"
            )
            return False

        wrapper.__name__ = f"{task_fn.__name__}[{task_key}]"
        return wrapper

    def setup_schedules(self):
        """스케줄 등록 (실패 시 재시도 + 결과 검증 포함)"""
        weekdays = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday']

        # 검증 함수: 파일이 오늘 날짜로 갱신됐는지 확인
        def _verify_file_today(filepath):
            def check():
                if not os.path.exists(filepath):
                    return False
                mtime = os.path.getmtime(filepath)
                return datetime.fromtimestamp(mtime).date() == datetime.now().date()
            return check

        def _verify_json_recent(filepath, max_age_hours=72):
            def check():
                if not os.path.exists(filepath):
                    return False
                if not build_freshness:
                    mtime = os.path.getmtime(filepath)
                    return datetime.fromtimestamp(mtime).date() == datetime.now().date()
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    freshness = build_freshness(filepath, data, max_age_hours=max_age_hours)
                    if freshness.get('is_stale'):
                        logger.warning("freshness verify failed for %s: %s", filepath, freshness)
                        return False
                    return True
                except Exception as e:
                    logger.warning("freshness verify read failed for %s: %s", filepath, e)
                    return False
            return check

        def _verify_vcp_all_recent():
            checks = [
                _verify_json_recent(os.path.join(Config.DATA_DIR, 'vcp_kr_latest.json'), 96),
                _verify_json_recent(os.path.join(Config.DATA_DIR, 'vcp_us_latest.json'), 96),
            ]
            return all(check() for check in checks)

        def _verify_briefing_today(briefing_type):
            def check():
                today = datetime.now().strftime('%Y%m%d')
                dated_path = os.path.join(
                    Config.DATA_DIR, 'briefing', f'{briefing_type}_{today}.json'
                )
                latest_path = os.path.join(Config.DATA_DIR, 'briefing', 'latest.json')

                if not os.path.exists(dated_path) or not os.path.exists(latest_path):
                    return False

                dated_mtime = datetime.fromtimestamp(os.path.getmtime(dated_path)).date()
                latest_mtime = datetime.fromtimestamp(os.path.getmtime(latest_path)).date()
                if dated_mtime != datetime.now().date() or latest_mtime != datetime.now().date():
                    return False

                try:
                    with open(dated_path, 'r', encoding='utf-8') as f:
                        dated = json.load(f)
                    with open(latest_path, 'r', encoding='utf-8') as f:
                        latest = json.load(f)
                except Exception:
                    return False

                return (
                    dated.get('date') == today
                    and dated.get('type') == briefing_type
                    and latest.get('date') == today
                    and latest.get('type') == briefing_type
                    and bool(dated.get('sections'))
                )
            return check

        jongga_verify = _verify_file_today(os.path.join(Config.DATA_DIR, 'jongga_v2_latest.json'))
        leading_verify = _verify_json_recent(os.path.join(Config.DATA_DIR, 'screener_leading_latest.json'), 2)
        vcp_kr_verify = _verify_json_recent(os.path.join(Config.DATA_DIR, 'vcp_kr_latest.json'), 96)
        us_verify = _verify_file_today(os.path.join(Config.BASE_DIR, 'us_market', 'output', 'market_briefing.json'))
        us_track_verify = _verify_file_today(os.path.join(Config.BASE_DIR, 'us_market', 'output', 'performance_report.json'))
        crypto_verify = _verify_json_recent(os.path.join(Config.DATA_DIR, 'vcp_crypto_latest.json'), 12)
        morning_briefing_verify = _verify_briefing_today('morning')
        closing_briefing_verify = _verify_briefing_today('closing')

        if Config.ALPHA_SCANNER_ENABLED:
            interval = max(0, int(Config.ALPHA_SCANNER_MONITOR_INTERVAL_MINUTES))
            if interval:
                schedule.every(interval).minutes.do(
                    self._with_record(run_alpha_scanner_monitor, 'alpha_scanner_monitor',
                                      max_retries=1, retry_delay=120))
                if Config.MIROFISH_WORKFLOW_ENABLED:
                    schedule.every(interval).minutes.do(
                        self._with_record(run_mirofish_workflow_monitor, 'mirofish_workflow_monitor',
                                          max_retries=1, retry_delay=120))
        if Config.OMNI_NEWS_ENABLED:
            omni_interval = max(5, int(Config.OMNI_NEWS_INTERVAL_MINUTES))
            schedule.every(omni_interval).minutes.do(
                self._with_record(run_omni_news_sweep, 'omni_news_sweep',
                                  max_retries=1, retry_delay=120))
        if Config.AIBRAIN_GUARD_ENABLED:
            guard_interval = max(0, int(Config.AIBRAIN_GUARD_INTERVAL_MINUTES))
            if guard_interval:
                schedule.every(guard_interval).minutes.do(
                    self._with_record(run_aibrain_service_guard, 'aibrain_service_guard',
                                      max_retries=0, retry_delay=120))
            prewarm_times = _valid_hhmm_times(Config.AIBRAIN_PREWARM_TIMES, 'AIBRAIN_PREWARM_TIMES')
            for day in weekdays:
                for hm in prewarm_times:
                    getattr(schedule.every(), day).at(hm).do(
                        self._with_record(run_aibrain_prewarm, f"aibrain_prewarm_{hm.replace(':', '')}",
                                          max_retries=1, retry_delay=300))
        if Config.ALPHA_BACKTEST_ENABLED:
            schedule.every().day.at(Config.ALPHA_BACKTEST_TIME).do(
                self._with_record(run_alpha_backtest_daily, 'alpha_backtest_daily',
                                  max_retries=1, retry_delay=300))
        if Config.MIROFISH_AGENT_ENABLED:
            for day in weekdays:
                getattr(schedule.every(), day).at(Config.MIROFISH_AGENT_EVENING_TIME).do(
                    self._with_record(run_alpha_brain_agent_evening, 'alpha_brain_agent_evening',
                                      max_retries=1, retry_delay=300))
            schedule.every().day.at(Config.MIROFISH_AGENT_NIGHT_TIME).do(
                self._with_record(run_alpha_brain_agent_night, 'alpha_brain_agent_night',
                                  max_retries=1, retry_delay=300))

        for day in weekdays:
            # 08:55 — KIS 토큰 웜업 (장 시작 5분 전 자격증명/네트워크 사전 검증)
            getattr(schedule.every(), day).at('08:55').do(
                self._with_record(_run_kis_token_warmup, 'kis_token_warmup',
                                  max_retries=2, retry_delay=60))
            # 🤖 키움 AI전략 테마 — 장중(09:10~15:25) 15분 주기, 함수 내부에서 시간대 게이트
            for hm in ['09:10','09:25','09:40','09:55','10:10','10:25','10:40','10:55',
                       '11:10','11:25','11:40','11:55','12:10','12:25','12:40','12:55',
                       '13:10','13:25','13:40','13:55','14:10','14:25','14:40','14:55',
                       '15:10','15:25']:
                getattr(schedule.every(), day).at(hm).do(
                    self._with_record(_run_kiwoom_ai_theme, 'kiwoom_ai_theme',
                                      max_retries=1, retry_delay=60))
            for hm in Config.LEADING_SCREENER_TIMES:
                task_key = f"leading_screener_{hm.replace(':', '')}"
                getattr(schedule.every(), day).at(hm).do(
                    self._with_record(run_leading_screener_refresh, task_key,
                                      max_retries=1, retry_delay=120, verify_fn=leading_verify))
            # 04:00 — US Market 전체 데이터 갱신 + Smart Money Top 5 텔레그램
            getattr(schedule.every(), day).at(Config.US_UPDATE_TIME).do(
                self._with_record(run_us_market_update, 'us_market',
                                  max_retries=2, retry_delay=900, verify_fn=us_verify))
            # 09:00 — 일별 상태 리포트 텔레그램
            getattr(schedule.every(), day).at(Config.MORNING_REPORT_TIME).do(
                self._with_record(send_morning_status_report, 'morning_report',
                                  max_retries=1, retry_delay=300))
            # 09:30 — US Track Record 스냅샷 + 성과 추적
            getattr(schedule.every(), day).at(Config.US_TRACK_TIME).do(
                self._with_record(save_us_track_record_snapshot, 'us_track',
                                  max_retries=1, retry_delay=600, verify_fn=us_track_verify))
            # 14:50 — 종가베팅 V2 + 수급/AI/리포트 (VCP 제외)
            getattr(schedule.every(), day).at(Config.KR_UPDATE_TIME).do(
                self._with_record(run_kr_full_update, 'kr_jongga',
                                  max_retries=2, retry_delay=600, verify_fn=jongga_verify))
            # 11:00 — KR VCP 오전 Refresh (주말 후 stale 방지, 단독 실행)
            getattr(schedule.every(), day).at(Config.KR_VCP_MORNING_TIME).do(
                self._with_record(run_kr_vcp_morning_refresh, 'kr_vcp_morning',
                                  max_retries=1, retry_delay=600))
            # 16:00 — KR·US VCP 시그널 (Crypto는 전용 4시간 파이프라인 소유)
            getattr(schedule.every(), day).at(Config.VCP_UPDATE_TIME).do(
                self._with_record(run_vcp_all_markets, 'vcp_all',
                                  max_retries=1, retry_delay=600, verify_fn=_verify_vcp_all_recent))
            # 16:30 — Wave 패턴 스캔 (KR)
            getattr(schedule.every(), day).at(Config.WAVE_SCAN_TIME).do(
                self._with_record(_run_wave_scan, 'wave_scan',
                                  max_retries=1, retry_delay=600))
            # 17:15 — Claw 관측 원장 D1/D5 성숙분 갱신 (발송/스캔 없음)
            if Config.CLAW_OUTCOME_ENABLED:
                getattr(schedule.every(), day).at(Config.CLAW_OUTCOME_TIME).do(
                    self._with_record(_run_claw_outcome_update, 'claw_outcomes',
                                      max_retries=1, retry_delay=300))
            # 17:30 — 로컬 사전순위 후 비용 제한 Vision 선별 → 텔레그램.
            # 프로세스 재시도는 일일 비용 상한을 보수적으로 지키기 위해 금지한다.
            getattr(schedule.every(), day).at(Config.BUY_SCREEN_TIME).do(
                self._with_record(_run_buy_candidate_screen, 'buy_screen',
                                  max_retries=0, retry_delay=900))
            # ── Alpha Position Engine 타임라인 (알파캐치형 완결 신호) ──
            getattr(schedule.every(), day).at(Config.ALPHA_MORNING_TIME).do(
                self._with_record(_run_alpha_morning_top, 'alpha_morning_top',
                                  max_retries=1, retry_delay=300))
            getattr(schedule.every(), day).at(Config.ALPHA_CLOSE_TIME).do(
                self._with_record(_run_alpha_close_signals, 'alpha_close_signals',
                                  max_retries=1, retry_delay=300))
            getattr(schedule.every(), day).at(Config.ALPHA_BRIEF_TIME).do(
                self._with_record(_run_alpha_performance_brief, 'alpha_performance_brief',
                                  max_retries=1, retry_delay=300))
            # 장중 감시 — 함수 내부에서 장시간(09:00~15:30) 게이트, 신호 시에만 발송
            for hm in Config.ALPHA_INTRADAY_TIMES:
                getattr(schedule.every(), day).at(hm).do(_run_alpha_intraday_watch)
            # 09:05 — AI 조간 브리핑 (US 시장 중심)
            getattr(schedule.every(), day).at(Config.MORNING_BRIEFING_TIME).do(
                self._with_record(run_morning_briefing, 'morning_briefing',
                                  max_retries=1, retry_delay=300,
                                  verify_fn=morning_briefing_verify))
            # 16:05 — AI 마감 브리핑 (KR 시장 중심)
            getattr(schedule.every(), day).at(Config.CLOSING_BRIEFING_TIME).do(
                self._with_record(run_closing_briefing, 'closing_briefing',
                                  max_retries=1, retry_delay=300,
                                  verify_fn=closing_briefing_verify))
            # 14:00 — AI Chart Analysis KR (Gemini Vision 100종목)
            getattr(schedule.every(), day).at(Config.AI_CHART_TIME).do(
                self._with_record(_run_ai_chart_analysis, 'ai_chart',
                                  max_retries=1, retry_delay=600))
            # 04:00 — US AI Chart Analysis (Gemini Vision S&P 500)
            getattr(schedule.every(), day).at(Config.US_AI_CHART_TIME).do(
                self._with_record(_run_us_ai_chart_analysis, 'us_ai_chart',
                                  max_retries=1, retry_delay=600))
            if Config.ALPHA_SCANNER_ENABLED:
                for hm in Config.ALPHA_SCANNER_TIMES:
                    task_key = f"alpha_scanner_{hm.replace(':', '')}"
                    getattr(schedule.every(), day).at(hm).do(
                        self._with_record(run_alpha_scanner_monitor, task_key,
                                          max_retries=1, retry_delay=120))

        # 금요일 17:00 — AI 로또 분석 게시
        schedule.every().friday.at(Config.LOTTO_POST_TIME).do(
            self._with_record(run_lotto_analysis_bounded, 'lotto_analysis',
                              max_retries=1, retry_delay=1800))
        schedule.every().saturday.at('09:00').do(
            self._with_record(run_lotto_analysis_bounded, 'lotto_analysis_recovery',
                              max_retries=2, retry_delay=900))

        # 토요일 히스토리 수집
        schedule.every().saturday.at(Config.HISTORY_TIME).do(
            self._with_record(collect_historical_institutional, 'history',
                              max_retries=1, retry_delay=600))

        # Crypto — 매 4시간 24/7 (00/04/08/12/16/20 KST)
        for t in _valid_hhmm_times(Config.CRYPTO_TIMES, 'CRYPTO_TIMES'):
            schedule.every().day.at(t).do(
                self._with_record(run_crypto_pipeline, 'crypto',
                                  max_retries=1, retry_delay=600, verify_fn=crypto_verify))

        # Orphan file audit — 매일 09:00 KST (업로드 파일 유실 감지)
        schedule.every().day.at('09:00').do(
            self._with_record(_run_orphan_file_audit, 'orphan_audit',
                              max_retries=1, retry_delay=300))

        logger.info("📅 스케줄 등록 완료:")
        logger.info("   🔑 평일 08:55  KIS 토큰 웜업 (장 시작 전 자격증명 사전 검증)")
        logger.info(f"   🇺🇸 평일 {Config.US_UPDATE_TIME}  US Market 전체 갱신 + Smart Money Top 5")
        logger.info(f"   📋 평일 {Config.MORNING_REPORT_TIME}  일별 상태 리포트 → 텔레그램")
        logger.info(f"   🇺🇸 평일 {Config.US_TRACK_TIME}  US Track Record 스냅샷")
        logger.info(f"   🇰🇷 평일 {Config.KR_UPDATE_TIME}  종가베팅 V2 + 수급/AI/리포트 → 텔레그램")
        logger.info(f"   📈 평일 {Config.KR_VCP_MORNING_TIME}  KR VCP 오전 Refresh (주말 후 stale 방지)")
        logger.info(f"   📈 평일 {Config.VCP_UPDATE_TIME}  KR·US VCP 시그널 → 텔레그램")
        logger.info(f"   🌊 평일 {Config.WAVE_SCAN_TIME}  Wave 패턴 스캔 (KR)")
        if Config.CLAW_OUTCOME_ENABLED:
            logger.info(f"   📐 평일 {Config.CLAW_OUTCOME_TIME}  Claw D1/D5 shadow outcome 갱신")
        logger.info(f"   🤖 평일 {Config.AI_CHART_TIME}  AI Chart Analysis KR (Gemini Vision)")
        logger.info(f"   🟢 평일 {Config.BUY_SCREEN_TIME}  로컬 사전필터 → Vision 최대 "
                    f"{Config.BUY_SCREEN_VISION_MAX_CALLS}회 → BUY 최대 {Config.BUY_SCREEN_TARGET}종목"
                    " → 텔레그램"
                    f"{' (채널 포함)' if Config.BUY_SCREEN_TO_CHANNEL else ' (개인봇)'}")
        logger.info(f"   🤖 평일 {Config.US_AI_CHART_TIME}  US AI Chart Analysis (Gemini Vision)")
        logger.info(f"   📰 평일 {Config.MORNING_BRIEFING_TIME}  AI 조간 브리핑 (Gemini)")
        logger.info(f"   📰 평일 {Config.CLOSING_BRIEFING_TIME}  AI 마감 브리핑 (Gemini)")
        if Config.ALPHA_SCANNER_ENABLED:
            logger.info(
                f"   🎯 알파스캐너 {Config.ALPHA_SCANNER_MONITOR_INTERVAL_MINUTES}분 주기 변경 감시"
                f" + 지정 시각 {', '.join(Config.ALPHA_SCANNER_TIMES)}"
            )
            if Config.MIROFISH_WORKFLOW_ENABLED:
                logger.info(
                    f"   🧠 MiroFish MCP workflow {Config.ALPHA_SCANNER_MONITOR_INTERVAL_MINUTES}분 주기"
                    f" 신규 {Config.MIROFISH_WORKFLOW_BATCH_SIZE}종 다중 GraphRAG 분석 + Top {Config.MIROFISH_WORKFLOW_TOP_N}"
                    f" (alpha>={Config.MIROFISH_WORKFLOW_MIN_ALPHA:g}, risk<={Config.MIROFISH_WORKFLOW_MAX_RISK:g})"
                )
        logger.info(f"   🎱 금요일 {Config.LOTTO_POST_TIME}  AI 로또 분석 게시")
        logger.info(f"   🇰🇷 토요일 {Config.HISTORY_TIME}  히스토리 수집")
        logger.info(f"   🪙 매 4시간 {', '.join(Config.CRYPTO_TIMES)}  Crypto 전체 파이프라인")

    def run(self):
        """스케줄러 실행"""
        logger.info("⏰ 통합 스케줄러 시작... (US + KR + Crypto)")
        logger.info("   Ctrl+C / SIGTERM으로 종료")

        # 시스템 메시지는 로그만 (텔레그램 전송 안 함)
        logger.info(
            "⏰ 스케줄러 시작 — "
            f"US:{Config.US_UPDATE_TIME} KR:{Config.KR_UPDATE_TIME} "
            f"VCP:{Config.VCP_UPDATE_TIME} Crypto:{','.join(Config.CRYPTO_TIMES)}"
        )

        last_missed_check = time.time()
        last_code_sync = time.time()
        MISSED_CHECK_INTERVAL = 300  # 5분마다 놓친 스케줄 점검
        CODE_SYNC_INTERVAL = 3600   # 1시간마다 코드 동기화 (git pull)
        write_heartbeat()  # 시작 즉시 1회

        while self.running:
            try:
                schedule.run_pending()
                write_heartbeat()  # 매 루프(30s) 갱신 → watchdog 가 stale 판정 가능

                now = time.time()

                # 주기적 놓친 스케줄 복구 (Windows sleep/hibernate 대응)
                if now - last_missed_check > MISSED_CHECK_INTERVAL:
                    threading.Thread(
                        target=check_and_run_missed_tasks,
                        name="missed-task-recovery",
                        daemon=True
                    ).start()
                    last_missed_check = now

                # 주기적 코드 동기화 — 명시적으로 opt-in 된 경우에만 Git 실행
                if now - last_code_sync > CODE_SYNC_INTERVAL:
                    threading.Thread(
                        target=_sync_code_from_remote,
                        name="code-sync",
                        daemon=True
                    ).start()
                    last_code_sync = now

            except Exception as e:
                logger.error(f"❌ 스케줄 실행 중 예외 (데몬 유지): {e}", exc_info=True)
            time.sleep(30)

        logger.info("👋 스케줄러 종료")


# ============================================================
# 메인
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='MarketFlow 통합 스케줄러 (US + KR + Crypto)')

    # 전체
    parser.add_argument('--now', action='store_true', help='즉시 전체 업데이트 (US+KR+Crypto)')
    parser.add_argument('--daemon', action='store_true', help='데몬 모드 (스케줄러)')

    # KR Market
    parser.add_argument('--prices', action='store_true', help='KR 가격 데이터만')
    parser.add_argument('--inst', action='store_true', help='KR 수급 데이터만')
    parser.add_argument('--signals', action='store_true', help='KR VCP 시그널만')
    parser.add_argument('--jongga-v2', action='store_true', help='KR 종가베팅 V2만')
    parser.add_argument('--kr-update', action='store_true', help='KR 종가베팅 업데이트 (14:50)')
    parser.add_argument('--vcp', action='store_true', help='KR·US VCP 시그널 (16:00)')
    parser.add_argument('--history', action='store_true', help='KR 히스토리 수집만')

    # US Market
    parser.add_argument('--us-pro', action='store_true', help='US Market 전체 갱신 + Smart Money Top 5')
    parser.add_argument('--us-track', action='store_true', help='US Track Record 스냅샷')

    # Crypto
    parser.add_argument('--crypto', action='store_true', help='Crypto 전체 파이프라인 (4시간 주기)')
    parser.add_argument('--crypto-gate', action='store_true', help='Crypto Gate Check만')
    parser.add_argument('--crypto-scan', action='store_true', help='Crypto VCP Scan만')

    # Wave Pattern
    parser.add_argument('--wave-scan', action='store_true', help='Wave 패턴 스캔 (KR 전 종목)')
    parser.add_argument('--alpha-scanner', action='store_true', help='MiroFish Alpha Scanner alert check')
    # AI Chart Analysis
    parser.add_argument('--ai-chart', action='store_true', help='AI Chart Analysis KR (Gemini Vision 100종목)')
    parser.add_argument('--buy-screen', action='store_true', help='AI 매수 후보 선별 (BUY 목표 개수까지)')
    parser.add_argument('--us-ai-chart', action='store_true', help='US AI Chart Analysis (Gemini Vision S&P 500)')
    # 로또 분석
    parser.add_argument('--lotto', action='store_true', help='AI 로또 분석 게시 (즉시 실행)')

    args = parser.parse_args()

    # ── Process-level filelock (이중 실행 방지) ──
    lock_path = os.path.join(Config.DATA_DIR, '.scheduler.lock')
    _scheduler_lock = None
    if FileLock is not None:
        _scheduler_lock = FileLock(lock_path, timeout=5)
        try:
            _scheduler_lock.acquire()
            atexit.register(lambda: _scheduler_lock.release(force=True))
            logger.info(f"🔒 스케줄러 락 획득: {lock_path}")
        except FileLockTimeout:
            logger.error(f"❌ 스케줄러 이미 실행 중 (락 파일: {lock_path})")
            sys.exit(0)
    else:
        logger.warning("⚠️ filelock 미설치 — 프로세스 레벨 락 비활성")

    # ── PID 파일 기반 단일 인스턴스 (--daemon 모드) ──
    if args.daemon:
        pid_file = os.path.join(Config.LOG_DIR, 'scheduler.pid')
        if os.path.exists(pid_file):
            try:
                with open(pid_file, 'r') as f:
                    old_pid = int(f.read().strip())
                # PID 생존 확인 (크로스플랫폼)
                pid_alive = False
                if os.name == 'nt':
                    result = subprocess.run(
                        ['tasklist', '/FI', f'PID eq {old_pid}', '/NH', '/FO', 'CSV'],
                        capture_output=True, text=True, timeout=10
                    )
                    pid_alive = str(old_pid) in result.stdout
                else:
                    try:
                        os.kill(old_pid, 0)  # signal 0 = 존재 확인만
                        pid_alive = True
                    except (ProcessLookupError, PermissionError):
                        pid_alive = False
                if pid_alive:
                    logger.warning(f"⚠️ Scheduler 이미 실행 중 (PID {old_pid}). 종료.")
                    print(f"[SCHEDULER] 이미 실행 중 (PID {old_pid}). 종료.")
                    sys.exit(0)
            except (ValueError, IOError, subprocess.TimeoutExpired) as e:
                logger.warning(f"⚠️ 기존 PID 확인 실패 (무시하고 진행): {e}")

        # PID 기록 (atomic write: temp → rename)
        os.makedirs(Config.LOG_DIR, exist_ok=True)
        pid_tmp = pid_file + '.tmp'
        with open(pid_tmp, 'w') as f:
            f.write(str(os.getpid()))
        os.replace(pid_tmp, pid_file)
        logger.info(f"🔒 Scheduler PID 파일 생성 (PID {os.getpid()})")

        def _cleanup_pid():
            try:
                if os.path.exists(pid_file):
                    with open(pid_file, 'r') as f:
                        pid = int(f.read().strip())
                    if pid == os.getpid():
                        os.remove(pid_file)
            except Exception as e:
                logger.warning(f"⚠️ PID 파일 정리 실패: {e}")
        atexit.register(_cleanup_pid)

    logger.info("=" * 60)
    logger.info("🚀 MarketFlow 통합 스케줄러 (PID %d)", os.getpid())
    logger.info("=" * 60)
    logger.info(f"   BASE_DIR: {Config.BASE_DIR}")
    logger.info(f"   LOG_DIR:  {Config.LOG_DIR}")
    logger.info(f"   DATA_DIR: {Config.DATA_DIR}")
    logger.info(f"   CRYPTO:   {Config.CRYPTO_MARKET_DIR}")
    logger.info(f"   PYTHON:   {Config.PYTHON_PATH}")
    logger.info(f"   SCHEDULE: {Config.SCHEDULE_ENABLED}")
    logger.info("=" * 60)

    # ── 개별 작업 실행 ──
    ran_any = False

    if args.now:
        run_full_update()
        ran_any = True
        if not args.daemon:
            return

    if args.prices:
        update_daily_prices()
        ran_any = True
        if not args.daemon:
            return

    if args.inst:
        update_institutional_data()
        ran_any = True
        if not args.daemon:
            return

    if args.signals:
        run_vcp_signal_scan()
        ran_any = True
        if not args.daemon:
            return

    if args.jongga_v2:
        update_jongga_v2()
        ran_any = True
        if not args.daemon:
            return

    if args.kr_update:
        run_kr_full_update()
        ran_any = True
        if not args.daemon:
            return

    if args.vcp:
        run_vcp_all_markets()
        ran_any = True
        if not args.daemon:
            return

    if args.history:
        collect_historical_institutional()
        ran_any = True
        if not args.daemon:
            return

    if args.us_pro:
        run_us_market_update()
        ran_any = True
        if not args.daemon:
            return

    if args.us_track:
        save_us_track_record_snapshot()
        ran_any = True
        if not args.daemon:
            return

    if args.crypto:
        run_crypto_pipeline()
        ran_any = True
        if not args.daemon:
            return

    if args.crypto_gate:
        run_crypto_gate_check()
        ran_any = True
        if not args.daemon:
            return

    if args.crypto_scan:
        run_crypto_vcp_scan()
        ran_any = True
        if not args.daemon:
            return

    if args.wave_scan:
        _run_wave_scan()
        ran_any = True
        if not args.daemon:
            return

    if args.alpha_scanner:
        run_alpha_scanner_monitor()
        ran_any = True
        if not args.daemon:
            return

    if args.ai_chart:
        _run_ai_chart_analysis()
        ran_any = True
        if not args.daemon:
            return

    if args.buy_screen:
        _run_buy_candidate_screen()
        ran_any = True
        if not args.daemon:
            return

    if args.us_ai_chart:
        _run_us_ai_chart_analysis()
        ran_any = True
        if not args.daemon:
            return

    if args.lotto:
        run_lotto_analysis()
        ran_any = True
        if not args.daemon:
            return

    # ── 스케줄러 모드 ──
    if Config.SCHEDULE_ENABLED:
        scheduler = Scheduler()
        scheduler.setup_schedules()
        # heartbeat 스레드를 catch-up 전에 띄워야 함.
        # startup catch-up 이 장시간(예: ai_chart 100종목 5-15분)을 잡아도
        # 외부 watchdog 가 false positive 로 데몬을 죽이지 않도록.
        start_heartbeat_thread()
        # 놓친 스케줄 복구 (스케줄 등록 후, 데몬 루프 시작 전)
        check_and_run_missed_tasks()
        scheduler.run()
    else:
        if not ran_any:
            logger.info("⚠️ 스케줄 비활성화됨 (KR_MARKET_SCHEDULE_ENABLED=false)")


if __name__ == "__main__":
    main()

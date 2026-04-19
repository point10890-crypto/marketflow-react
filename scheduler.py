#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MarketFlow 통합 스케줄러 — US / KR / Crypto

스케줄 (KST):
─────────────────────────────────────────────────
  04:00  US Market  전체 데이터 갱신 → Smart Money Top 5 텔레그램
  09:30  US Market  Track Record 스냅샷 + 성과 추적
  14:50  KR Market  종가베팅 V2 + 수급/AI/리포트 → 텔레그램
  16:00  전 시장    VCP 시그널 업데이트 (KR + US + Crypto) → 텔레그램
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
load_dotenv(override=True)
import time
import logging
import subprocess
import signal as signal_module
import argparse
import atexit
from datetime import datetime
from pathlib import Path
from typing import Optional
import json
import threading

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

# Process-level filelock
try:
    from filelock import FileLock, Timeout as FileLockTimeout
except ImportError:
    FileLock = None
    FileLockTimeout = None

# 선택적 import (배포 시 설치 필요)
try:
    import schedule
except ImportError:
    print("❌ 'schedule' 패키지가 필요합니다: pip install schedule")
    sys.exit(1)


# ============================================================
# Git 자동 커밋 + 푸시 (→ Render 자동 배포)
# ============================================================
_git_lock = threading.Lock()

def _sync_code_from_remote():
    """원격 코드 변경 자동 반영 (git pull)

    1시간마다 실행. 소스 코드 변경(scheduler.py, engine/ 등)을 원격에서 받아온다.
    데이터 충돌 방지: unstaged changes가 있으면 stash → pull → stash pop.
    실패해도 데몬은 계속 동작 (로그만 남김).
    """
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
        True if push succeeded
    """
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
            data_dirs = [
                'data/',
                'us_market/output/',
                'crypto-analytics/crypto_market/output/',
                'us_market/sector_cache.json',
                'data/wave/',
                'data/briefing/',
            ]
            for d in data_dirs:
                subprocess.run(['git', 'add', d], cwd=project_dir, timeout=30,
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
    VCP_UPDATE_TIME = os.environ.get('VCP_UPDATE_TIME', '16:00')         # 전 시장 VCP 시그널
    WAVE_SCAN_TIME = os.environ.get('WAVE_SCAN_TIME', '16:30')           # Wave 패턴 스캔
    AI_CHART_TIME = os.environ.get('AI_CHART_TIME', '14:00')             # AI Chart Analysis KR (Gemini Vision)
    US_AI_CHART_TIME = os.environ.get('US_AI_CHART_TIME', '04:00')       # AI Chart Analysis US (Gemini Vision)
    HISTORY_TIME = os.environ.get('KR_MARKET_HISTORY_TIME', '10:00')
    CRYPTO_TIMES = ['00:00', '04:00', '08:00', '12:00', '16:00', '20:00']  # 매 4시간
    MORNING_REPORT_TIME = os.environ.get('MORNING_REPORT_TIME', '09:00')   # 일별 상태 리포트
    MORNING_BRIEFING_TIME = os.environ.get('MORNING_BRIEFING_TIME', '09:05')  # AI 조간 브리핑
    CLOSING_BRIEFING_TIME = os.environ.get('CLOSING_BRIEFING_TIME', '16:05')  # AI 마감 브리핑
    LOTTO_POST_TIME = os.environ.get('LOTTO_POST_TIME', '17:00')           # 금요일 AI 로또 분석

    # 타임아웃 (초)
    PRICE_TIMEOUT = int(os.environ.get('KR_MARKET_PRICE_TIMEOUT', '600'))
    INST_TIMEOUT = int(os.environ.get('KR_MARKET_INST_TIMEOUT', '600'))
    SIGNAL_TIMEOUT = int(os.environ.get('KR_MARKET_SIGNAL_TIMEOUT', '300'))
    HISTORY_TIMEOUT = int(os.environ.get('KR_MARKET_HISTORY_TIMEOUT', '900'))
    CRYPTO_TASK_TIMEOUT = int(os.environ.get('CRYPTO_MARKET_TASK_TIMEOUT', '600'))
    CRYPTO_BRIEFING_TIMEOUT = int(os.environ.get('CRYPTO_MARKET_BRIEFING_TIMEOUT', '300'))

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

    log_file = os.path.join(Config.LOG_DIR, 'scheduler.log')

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


def _telegram_post(bot_token: str, chat_id: str, message: str, retries: int = 5) -> bool:
    """텔레그램 단건 전송 (SSL EOF 대비 — 새 세션 + 지수 백오프 재시도)"""
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
                return True
            logger.warning(f"⚠️ 텔레그램 HTTP {r.status_code}: {r.text[:100]}")
        except Exception as e:
            if attempt < retries - 1:
                wait = 3 * (2 ** attempt)  # 3, 6, 12, 24초
                logger.debug(f"텔레그램 재시도 {attempt+1}/{retries} ({wait}초 후): {e}")
                time.sleep(wait)
            else:
                logger.error(f"❌ 텔레그램 전송 실패 ({retries}회 시도): {e}")
    return False


# ── 텔레그램 실패 큐 (1시간 내 재전송) ──
_telegram_queue: list = []  # [(message, timestamp)]
_TELEGRAM_QUEUE_TTL = 3600  # 1시간 후 폐기


def _try_send_telegram(message: str, channel: bool = True) -> bool:
    """실제 전송 시도.
    channel=True  → 개인 + 채널 양쪽 (분석 결과)
    channel=False → 개인 봇만 (시스템 메시지)
    """
    success = False

    # 1) 개인 봇 (항상)
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if token and chat_id and "your_bot_token" not in token:
        if _telegram_post(token, chat_id, message):
            success = True

    # 2) 채널 봇 — 분석 결과만 (시스템 메시지 제외)
    if channel:
        ch_token = os.getenv("TELEGRAM_CHANNEL_BOT_TOKEN")
        ch_chat_id = os.getenv("TELEGRAM_CHANNEL_CHAT_ID")
        if ch_token and ch_chat_id:
            if _telegram_post(ch_token, ch_chat_id, message):
                success = True

    return success


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


def send_telegram(message: str, channel: bool = True) -> bool:
    """텔레그램 메시지 전송 (실패 시 큐 저장 + 이전 실패 재전송)
    channel=True  → 개인+채널 (분석 결과, 기본값)
    channel=False → 개인만 (시스템 메시지)
    """
    _flush_telegram_queue()

    success = _try_send_telegram(message, channel=channel)

    if not success:
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


# ============================================================
# [KR Market] 작업 함수들
# ============================================================

def update_daily_prices():
    """일별 가격 데이터 업데이트 — FDR listing + pykrx OHLCV 수집"""
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
        logger.info(f"📊 FDR 종목 목록: {len(tickers)}개")
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


def update_jongga_v2():
    """종가베팅 V2 데이터 업데이트 + S/A급 텔레그램 전송

    subprocess 방식 유지 (git pull 후 디스크의 최신 코드를 항상 사용).
    pre-flight 검증으로 코드 버그 사전 탐지 + 실패 시 텔레그램 즉시 알림.
    """
    # ── Pre-flight: subprocess로 import만 테스트 (최신 디스크 코드 검증) ──
    # LLMAnalyzer() 실제 인스턴스화로 anthropic/google/openai 의존성까지 검증
    preflight = run_command(
        [Config.PYTHON_PATH, '-c',
         'from engine.generator import run_screener; '
         'from engine.llm_analyzer import LLMAnalyzer; '
         'from engine.scorer import Scorer; '
         'import anthropic, openai; '  # V2 런타임 필수 SDK
         'LLMAnalyzer(); '               # Claude/Gemini/OpenAI 클라이언트 초기화 확인
         'print("OK")'],
        'V2 pre-flight 검증',
        timeout=30
    )
    if not preflight:
        send_telegram(
            "<b>🚨 종가베팅 V2 코드 버그</b>\n\n"
            "엔진 import 실패 — 코드 수정 필요!\n"
            "scheduler 로그를 확인하세요.",
            channel=False
        )
        return False
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

    # ── 결과 검증 + 텔레그램 전송 ──
    try:
        json_path = os.path.join(Config.DATA_DIR, "jongga_v2_latest.json")
        if not os.path.exists(json_path) or (time.time() - os.path.getmtime(json_path)) > 300:
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
            env_extra={'MARKETFLOW_API': 'http://localhost:5001'},
        )
    except Exception as e:
        logger.warning(f"post_daily_analysis 예외 (무시): {e}")
        return True


def run_kr_full_update(skip_sync: bool = False):
    """KR 종가베팅 업데이트 (14:50) — 종가베팅V2 + 수급/AI/리포트 → 텔레그램
    ※ VCP 시그널은 16:00 run_vcp_all_markets()에서 별도 실행
    """
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


def run_vcp_all_markets(skip_sync: bool = False):
    """전 시장 VCP 시그널 업데이트 (16:00) — KR + US + Crypto → 텔레그램"""
    logger.info("=" * 60)
    logger.info("📈 전 시장 VCP 시그널 업데이트 시작 (16:00)")
    logger.info("=" * 60)

    start_time = time.time()
    results = []

    # KR VCP (signal_tracker + vcp_enhanced_scanner 둘 다 실행)
    results.append(('KR VCP (signal)', run_vcp_signal_scan(send_alert=True)))
    results.append(('KR VCP (enhanced)', run_vcp_enhanced_scan('KR')))

    # US VCP
    results.append(('US VCP', run_vcp_enhanced_scan('US')))

    # Crypto VCP
    results.append(('Crypto VCP', run_vcp_enhanced_scan('CRYPTO')))

    elapsed = int(time.time() - start_time)
    success_count = sum(1 for _, s in results if s)
    summary_lines = [f"  {'✅' if s else '❌'} {n}" for n, s in results]

    logger.info(f"📋 전 시장 VCP 업데이트 완료: {success_count}/{len(results)} ({elapsed}초)")

    send_telegram(
        f"<b>📈 16시 전 시장 VCP 업데이트 완료</b>\n"
        f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')} ({elapsed}초)\n"
        f"결과: {success_count}/{len(results)}\n\n"
        + "\n".join(summary_lines),
        channel=False
    )

    if not skip_sync:
        auto_git_push('vcp')

    return all(r[1] for r in results)


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
                if file_age > 300:  # 5분 이상 된 파일 = 갱신 안 됨
                    logger.warning(f"⚠️ {market_upper} VCP 결과 파일이 오래됨 ({int(file_age)}초)")
                    if attempt < max_retries:
                        time.sleep(10)
                    continue
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
    """US Track Record 스냅샷 저장 + 성과 추적"""
    logger.info("📊 US Track Record 스냅샷 저장...")

    try:
        import urllib.request
        req = urllib.request.Request(
            'http://localhost:5001/api/us/track-record/save-snapshot',
            method='POST',
            headers={'Content-Type': 'application/json'}
        )
        try:
            resp = urllib.request.urlopen(req, timeout=30)
            result = json.loads(resp.read().decode('utf-8'))
            logger.info(f"✅ US 스냅샷: {result.get('date', '?')} ({result.get('picks_count', 0)}종목)")
        except Exception as e:
            logger.warning(f"⚠️ US 스냅샷 API 실패: {e}")

        tracker_path = os.path.join(Config.BASE_DIR, 'us_market', 'performance_tracker.py')
        if os.path.exists(tracker_path):
            return run_command(
                [Config.PYTHON_PATH, tracker_path],
                'US Smart Money 성과 추적',
                timeout=300
            )
        return False

    except Exception as e:
        logger.error(f"❌ US Track Record 실패: {e}")
        return False


# ============================================================
# [Crypto Market] 작업 함수들
# ============================================================

# 현재 gate 상태 추적 (모듈 레벨)
_crypto_gate = "YELLOW"
_crypto_gate_score = 50


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

def run_crypto_pipeline(skip_sync: bool = False):
    """Crypto 전체 파이프라인 (4시간마다 실행)"""
    logger.info("=" * 60)
    logger.info("🪙 Crypto 전체 파이프라인 시작 (4시간 주기)")
    logger.info("=" * 60)

    start_time = time.time()
    results = []

    # 1. Gate Check
    results.append(('Gate Check', run_crypto_gate_check()))

    # 2. VCP Scan (RED 시 자동 스킵)
    results.append(('VCP Scan', run_crypto_vcp_scan()))

    # 3. Briefing
    results.append(('Briefing', run_crypto_briefing()))

    # 4. Prediction
    results.append(('Prediction', run_crypto_prediction()))

    # 5. Risk
    results.append(('Risk', run_crypto_risk()))

    # 6. Lead-Lag
    results.append(('Lead-Lag', run_crypto_leadlag()))

    # 7. Briefing 텔레그램 알림
    notify_crypto_briefing()

    elapsed = time.time() - start_time
    success_count = sum(1 for _, ok in results if ok)
    total_count = len(results)

    for name, ok in results:
        status = "✅" if ok else "❌"
        logger.info(f"  {status} {name}")

    logger.info(f"🪙 Crypto 파이프라인 완료: {success_count}/{total_count} ({elapsed:.0f}초)")

    # 개별 실패 알림
    failed = [name for name, ok in results if not ok]
    if failed:
        send_telegram(
            f"⚠️ <b>Crypto 파이프라인 부분 실패</b>\n\n"
            f"성공: {success_count}/{len(results)}\n"
            f"실패: {', '.join(failed)}\n"
            f"시간: {datetime.now().strftime('%H:%M')}",
            channel=False
        )

    # Git 자동 커밋 + 푸시 (→ Render 자동 배포)
    if not skip_sync:
        auto_git_push('crypto')

    return success_count == total_count


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
        ("VCP 전시장",   "📈", lambda: run_vcp_all_markets(skip_sync=True)),
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
            (4 * 60,       'us_ai_chart',      _run_us_ai_chart_analysis,   'US AI Chart 분석',   14 * 60, None),
            (9 * 60,       'morning_report',   send_morning_status_report,  '일별 상태 리포트',   14 * 60, None),
            (9 * 60 + 5,   'morning_briefing', run_morning_briefing,        'AI 조간 브리핑',     14 * 60, None),
            (9 * 60 + 30,  'us_track',         save_us_track_record_snapshot,'US Track Record',   14 * 60, None),
            (14 * 60,      'ai_chart',         _run_ai_chart_analysis,      'KR AI Chart 분석',   23 * 60, None),
            (14 * 60 + 50, 'kr_jongga',        run_kr_full_update,          'KR 종가베팅',        23 * 60, None),
            (16 * 60,      'vcp_all',          run_vcp_all_markets,         'VCP 전시장',         23 * 60, None),
            (16 * 60 + 5,  'closing_briefing', run_closing_briefing,        'AI 마감 브리핑',     23 * 60, None),
            (16 * 60 + 30, 'wave_scan',        _run_wave_scan,              'Wave 패턴 스캔',     23 * 60, None),
            # ── 금요일 전용 ──
            (17 * 60,      'lotto_analysis',   run_lotto_analysis,          'AI 로또 분석 게시',  23 * 60, {4}),
            # ── 토요일 전용 ──
            (10 * 60,      'history',          collect_historical_institutional, '히스토리 수집',  23 * 60, {5}),
        ]

        # ── 매일 실행 작업 (Crypto - 주말 포함) ──
        # Crypto는 4시간 간격이라 가장 최근 놓친 것만 복구
        crypto_times_min = [0, 4*60, 8*60, 12*60, 16*60, 20*60]

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
            if _was_run_today(task_key):
                logger.info(f"  ✅ {label}: 오늘 이미 실행됨, 스킵")
                continue

            logger.info(f"  ⚠️ 놓친 스케줄 감지: {label} (예정 {sched_min//60:02d}:{sched_min%60:02d}) → 즉시 실행")
            try:
                task_fn()
                record_task_run(task_key)
                recovered.append(label)
                logger.info(f"  ✅ 복구 완료: {label}")
            except Exception as e:
                logger.error(f"  ❌ 복구 실패: {label} — {e}", exc_info=True)

        # Crypto 복구 (주말 포함)
        # 현재 시각 이전의 가장 최근 crypto 시각 찾기
        past_crypto = [t for t in crypto_times_min if t < hour_min]
        if past_crypto:
            latest_crypto_min = max(past_crypto)
            if not _was_run_recently('crypto', hours=4):
                # 마지막 실행이 오늘이 아니면 복구
                logger.info(f"  ⚠️ 놓친 Crypto 파이프라인 감지 (최근 예정 {latest_crypto_min//60:02d}:00) → 즉시 실행")
                try:
                    run_crypto_pipeline()
                    record_task_run('crypto')
                    recovered.append('Crypto 파이프라인')
                    logger.info(f"  ✅ 복구 완료: Crypto 파이프라인")
                except Exception as e:
                    logger.error(f"  ❌ 복구 실패: Crypto 파이프라인 — {e}", exc_info=True)

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


def _run_ai_chart_analysis() -> bool:
    """AI Chart Analysis — Gemini Vision 100종목 차트 분석"""
    logger.info("=" * 60)
    logger.info("🤖 AI Chart Analysis 시작 (Gemini Vision · KR 100종목)")
    logger.info("=" * 60)

    try:
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
            if os.path.exists(csv_path):
                import pandas as pd
                df = pd.read_csv(csv_path, encoding='utf-8-sig')
                buy_count = len(df[df['signal'] == 'BUY'])
                logger.info(f"🤖 AI Chart 분석 완료: {len(df)}개 종목 (BUY: {buy_count})")

                # 텔레그램 알림 (BUY 종목)
                if buy_count > 0:
                    buy_df = df[df['signal'] == 'BUY'].sort_values('confidence', ascending=False)
                    lines = [f"<b>🤖 AI Chart Analysis ({len(df)}종목)</b>\n"]
                    lines.append(f"🟢 BUY: {buy_count} | 🟡 HOLD: {len(df[df['signal'] == 'HOLD'])} | 🔴 SELL: {len(df[df['signal'] == 'SELL'])}\n")
                    for _, row in buy_df.head(10).iterrows():
                        lines.append(f"  🟢 <b>{row['종목명']}</b> ({row['종목코드']}) conf={row['confidence']}")
                    try:
                        send_telegram('\n'.join(lines))
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
        script = os.path.join(Config.BASE_DIR, 'main_us.py')
        result = subprocess.run(
            [Config.PYTHON_PATH, script],
            capture_output=True, text=True, timeout=1800,
            cwd=Config.BASE_DIR,
            env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
        )
        if result.returncode == 0:
            csv_path = os.path.join(Config.BASE_DIR, 'gemini_chart_analysis_us.csv')
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
            # 중복 실행 방지 (catch-up 복구와의 충돌, 워치독 재시작 후 이중 실행 방지)
            # - crypto: 4시간 주기 → 3시간 쿨다운
            # - kiwoom_ai_theme: 장중 15분 주기 → 10분 쿨다운 (하루 1회 제한 해제)
            # - 그 외: 하루 1회 제한
            if task_key == 'crypto':
                if _was_run_recently(task_key, hours=3):
                    logger.info(f"⏭️ {task_key}: 최근 3시간 내 실행됨, 스킵")
                    return None
            elif task_key == 'kiwoom_ai_theme':
                # 장중 연속 갱신 허용: 10분 이내 재실행만 방지
                if _was_run_recently(task_key, hours=10/60):
                    logger.info(f"⏭️ {task_key}: 최근 10분 내 실행됨, 스킵")
                    return None
            elif _was_run_today(task_key):
                logger.info(f"⏭️ {task_key}: 오늘 이미 실행됨, 스킵")
                return None

            for attempt in range(1 + max_retries):
                try:
                    if attempt > 0:
                        logger.info(f"🔄 {task_key} 재시도 {attempt}/{max_retries} ({retry_delay}초 후)")
                        time.sleep(retry_delay)

                    result = task_fn()

                    # 1차: 리턴값 체크 — 모든 task 함수는 명시적 bool 을 반환해야 함.
                    # `None` 은 "return 누락" 버그이므로 실패로 간주 (verify_fn 이 있으면 거기서 한 번 더 검증).
                    success = bool(result)

                    # 2차: 검증 함수 체크 (파일 존재/데이터 유효성)
                    if success and verify_fn:
                        try:
                            success = verify_fn()
                        except Exception as ve:
                            logger.warning(f"⚠️ {task_key} 검증 실패: {ve}")
                            success = False

                    if success:
                        record_task_run(task_key)
                        if attempt > 0:
                            send_telegram(f"✅ {task_key} 재시도 {attempt}회 만에 성공", channel=False)
                        return result
                    else:
                        logger.warning(f"⚠️ {task_key} 실패 (시도 {attempt + 1}/{1 + max_retries})")

                except Exception as e:
                    logger.error(f"❌ {task_key} 예외 (시도 {attempt + 1}/{1 + max_retries}): {e}")

            # 모든 재시도 실패
            logger.error(f"🚨 {task_key} {1 + max_retries}회 시도 모두 실패!")
            send_telegram(
                f"🚨 <b>{task_key} 업데이트 실패</b>\n\n"
                f"총 {1 + max_retries}회 시도 후 실패\n"
                f"수동 확인 필요",
                channel=False
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

        jongga_verify = _verify_file_today(os.path.join(Config.DATA_DIR, 'jongga_v2_latest.json'))
        vcp_kr_verify = _verify_file_today(os.path.join(Config.DATA_DIR, 'vcp_kr_latest.json'))
        us_verify = _verify_file_today(os.path.join(Config.BASE_DIR, 'us_market', 'output', 'market_briefing.json'))
        us_track_verify = _verify_file_today(os.path.join(Config.BASE_DIR, 'us_market', 'output', 'performance_report.json'))
        crypto_verify = _verify_file_today(os.path.join(Config.DATA_DIR, 'vcp_crypto_latest.json'))

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
            # 16:00 — 전 시장 VCP 시그널 (KR + US + Crypto)
            getattr(schedule.every(), day).at(Config.VCP_UPDATE_TIME).do(
                self._with_record(run_vcp_all_markets, 'vcp_all',
                                  max_retries=1, retry_delay=600, verify_fn=vcp_kr_verify))
            # 16:30 — Wave 패턴 스캔 (KR)
            getattr(schedule.every(), day).at(Config.WAVE_SCAN_TIME).do(
                self._with_record(_run_wave_scan, 'wave_scan',
                                  max_retries=1, retry_delay=600))
            # 09:05 — AI 조간 브리핑 (US 시장 중심)
            getattr(schedule.every(), day).at(Config.MORNING_BRIEFING_TIME).do(
                self._with_record(run_morning_briefing, 'morning_briefing',
                                  max_retries=1, retry_delay=300))
            # 16:05 — AI 마감 브리핑 (KR 시장 중심)
            getattr(schedule.every(), day).at(Config.CLOSING_BRIEFING_TIME).do(
                self._with_record(run_closing_briefing, 'closing_briefing',
                                  max_retries=1, retry_delay=300))
            # 14:00 — AI Chart Analysis KR (Gemini Vision 100종목)
            getattr(schedule.every(), day).at(Config.AI_CHART_TIME).do(
                self._with_record(_run_ai_chart_analysis, 'ai_chart',
                                  max_retries=1, retry_delay=600))
            # 04:00 — US AI Chart Analysis (Gemini Vision S&P 500)
            getattr(schedule.every(), day).at(Config.US_AI_CHART_TIME).do(
                self._with_record(_run_us_ai_chart_analysis, 'us_ai_chart',
                                  max_retries=1, retry_delay=600))

        # 금요일 17:00 — AI 로또 분석 게시
        schedule.every().friday.at(Config.LOTTO_POST_TIME).do(
            self._with_record(run_lotto_analysis, 'lotto_analysis',
                              max_retries=1, retry_delay=1800))

        # 토요일 히스토리 수집
        schedule.every().saturday.at(Config.HISTORY_TIME).do(
            self._with_record(collect_historical_institutional, 'history',
                              max_retries=1, retry_delay=600))

        # Crypto — 매 4시간 24/7 (00/04/08/12/16/20 KST)
        for t in Config.CRYPTO_TIMES:
            schedule.every().day.at(t).do(
                self._with_record(run_crypto_pipeline, 'crypto',
                                  max_retries=1, retry_delay=600, verify_fn=crypto_verify))

        logger.info("📅 스케줄 등록 완료:")
        logger.info("   🔑 평일 08:55  KIS 토큰 웜업 (장 시작 전 자격증명 사전 검증)")
        logger.info(f"   🇺🇸 평일 {Config.US_UPDATE_TIME}  US Market 전체 갱신 + Smart Money Top 5")
        logger.info(f"   📋 평일 {Config.MORNING_REPORT_TIME}  일별 상태 리포트 → 텔레그램")
        logger.info(f"   🇺🇸 평일 {Config.US_TRACK_TIME}  US Track Record 스냅샷")
        logger.info(f"   🇰🇷 평일 {Config.KR_UPDATE_TIME}  종가베팅 V2 + 수급/AI/리포트 → 텔레그램")
        logger.info(f"   📈 평일 {Config.VCP_UPDATE_TIME}  전 시장 VCP 시그널 (KR+US+Crypto) → 텔레그램")
        logger.info(f"   🌊 평일 {Config.WAVE_SCAN_TIME}  Wave 패턴 스캔 (KR)")
        logger.info(f"   🤖 평일 {Config.AI_CHART_TIME}  AI Chart Analysis KR (Gemini Vision)")
        logger.info(f"   🤖 평일 {Config.US_AI_CHART_TIME}  US AI Chart Analysis (Gemini Vision)")
        logger.info(f"   📰 평일 {Config.MORNING_BRIEFING_TIME}  AI 조간 브리핑 (Gemini)")
        logger.info(f"   📰 평일 {Config.CLOSING_BRIEFING_TIME}  AI 마감 브리핑 (Gemini)")
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

                # 주기적 코드 동기화 (git pull) — 원격 코드 변경 자동 반영
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
    parser.add_argument('--vcp', action='store_true', help='전 시장 VCP 시그널 (KR+US+Crypto, 16:00)')
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
    # AI Chart Analysis
    parser.add_argument('--ai-chart', action='store_true', help='AI Chart Analysis KR (Gemini Vision 100종목)')
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

    if args.ai_chart:
        _run_ai_chart_analysis()
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

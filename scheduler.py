#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MarketFlow 통합 스케줄러 — US / KR / Crypto

스케줄 (KST):
─────────────────────────────────────────────────
  04:00  US Market  전체 데이터 갱신 → Smart Money Top 5 텔레그램
  09:30  US Market  Track Record 스냅샷 + 성과 추적
  15:00  KR Market  종가베팅 V2 + 수급/AI/리포트 → 텔레그램
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
from datetime import datetime
from pathlib import Path
from typing import Optional
import json

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

# 선택적 import (배포 시 설치 필요)
try:
    import schedule
except ImportError:
    print("❌ 'schedule' 패키지가 필요합니다: pip install schedule")
    sys.exit(1)


# ============================================================
# Git 자동 커밋 + 푸시 (→ Render 자동 배포)
# ============================================================

def auto_git_push(scope: str = 'all') -> bool:
    """데이터 업데이트 후 자동 git commit + push (origin만)

    Args:
        scope: 'kr', 'us', 'crypto', 'all'
    Returns:
        True if push succeeded
    """
    import subprocess
    from datetime import datetime

    project_dir = os.path.dirname(os.path.abspath(__file__))
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')

    try:
        result = subprocess.run(
            ['git', 'status', '--porcelain'],
            capture_output=True, text=True, cwd=project_dir, timeout=30
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
        ]
        for d in data_dirs:
            subprocess.run(['git', 'add', d], cwd=project_dir, timeout=30,
                           capture_output=True, text=True)

        # 스테이징된 변경사항 확인
        staged = subprocess.run(
            ['git', 'diff', '--cached', '--quiet'],
            cwd=project_dir, timeout=10, capture_output=True
        )
        if staged.returncode == 0:
            logger.info("📦 데이터 변경사항 없음, git push 스킵")
            return True

        msg = f"auto: {scope} data update ({now_str})"
        subprocess.run(
            ['git', 'commit', '-m', msg],
            cwd=project_dir, timeout=30, check=True,
            capture_output=True, text=True
        )

        # pull --rebase 후 push (GitHub Actions 커밋과 충돌 방지)
        rebase_result = subprocess.run(
            ['git', 'pull', '--rebase', 'origin', 'main'],
            cwd=project_dir, timeout=120,
            capture_output=True, text=True
        )
        if rebase_result.returncode != 0:
            logger.error(f"⚠️ Git rebase 실패, abort 후 merge 전략 시도: {rebase_result.stderr}")
            subprocess.run(['git', 'rebase', '--abort'], cwd=project_dir, timeout=30,
                           capture_output=True, text=True)
            subprocess.run(['git', 'pull', '--no-rebase', 'origin', 'main'],
                           cwd=project_dir, timeout=120, capture_output=True, text=True)

        push_result = subprocess.run(
            ['git', 'push', 'origin', 'main'],
            cwd=project_dir, timeout=120,
            capture_output=True, text=True
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
    KR_UPDATE_TIME = os.environ.get('KR_MARKET_UPDATE_TIME', '15:00')   # 종가베팅 V2
    VCP_UPDATE_TIME = os.environ.get('VCP_UPDATE_TIME', '16:00')         # 전 시장 VCP 시그널
    HISTORY_TIME = os.environ.get('KR_MARKET_HISTORY_TIME', '10:00')
    CRYPTO_TIMES = ['00:00', '04:00', '08:00', '12:00', '16:00', '20:00']  # 매 4시간
    MORNING_REPORT_TIME = os.environ.get('MORNING_REPORT_TIME', '09:00')   # 일별 상태 리포트

    # 타임아웃 (초)
    PRICE_TIMEOUT = int(os.environ.get('KR_MARKET_PRICE_TIMEOUT', '600'))
    INST_TIMEOUT = int(os.environ.get('KR_MARKET_INST_TIMEOUT', '600'))
    SIGNAL_TIMEOUT = int(os.environ.get('KR_MARKET_SIGNAL_TIMEOUT', '300'))
    HISTORY_TIMEOUT = int(os.environ.get('KR_MARKET_HISTORY_TIMEOUT', '900'))
    CRYPTO_TASK_TIMEOUT = int(os.environ.get('CRYPTO_MARKET_TASK_TIMEOUT', '600'))
    CRYPTO_BRIEFING_TIMEOUT = int(os.environ.get('CRYPTO_MARKET_BRIEFING_TIMEOUT', '300'))

    # Python 실행 경로 (가상환경 우선)
    _VENV_PYTHON = os.path.join(_SCRIPT_DIR, '.venv', 'Scripts', 'python.exe')
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
    """로깅 설정"""
    Config.ensure_dirs()

    log_file = os.path.join(Config.LOG_DIR, 'scheduler.log')

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler()
        ]
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

        for line in iter(process.stdout.readline, ''):
            clean = line.strip()
            if clean:
                logger.info(f"   > {clean}")

        process.wait(timeout=timeout)

        elapsed = time.time() - start

        if process.returncode == 0:
            logger.info(f"✅ 완료: {description} ({elapsed:.1f}초)")
            return True
        else:
            logger.error(f"❌ 실패: {description} (Exit Code: {process.returncode})")
            if notify:
                send_telegram(f"❌ 실패: {description} (Error Code: {process.returncode})")
            return False

    except subprocess.TimeoutExpired:
        process.kill()
        logger.error(f"⏰ 타임아웃: {description}")
        if notify:
            send_telegram(f"⏰ 타임아웃 발생: {description}")
        return False
    except Exception as e:
        logger.error(f"❌ 에러: {description} - {e}")
        if notify:
            send_telegram(f"❌ 예외 발생: {description}\n{str(e)}")
        return False


def send_telegram(message: str) -> bool:
    """텔레그램 메시지 전송 (개인 + 채널 동시)"""
    import requests
    success = False

    # 1) 개인 봇
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if token and chat_id and "your_bot_token" not in token:
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
                timeout=10
            )
            if r.status_code == 200:
                success = True
        except Exception as e:
            logger.error(f"❌ 텔레그램(개인) 전송 실패: {e}")

    # 2) 채널 봇 (style_종가매매)
    ch_token = os.getenv("TELEGRAM_CHANNEL_BOT_TOKEN")
    ch_chat_id = os.getenv("TELEGRAM_CHANNEL_CHAT_ID")
    if ch_token and ch_chat_id:
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{ch_token}/sendMessage",
                json={"chat_id": ch_chat_id, "text": message, "parse_mode": "HTML"},
                timeout=10
            )
            if r.status_code == 200:
                success = True
        except Exception as e:
            logger.error(f"❌ 텔레그램(채널) 전송 실패: {e}")

    if not success:
        logger.warning("⚠️ 텔레그램 전송 실패 또는 설정 미완료")
    return success


def send_telegram_long(message: str) -> bool:
    """긴 텔레그램 메시지를 4000자 단위로 분할 전송"""
    MAX_LEN = 4000
    if len(message) <= MAX_LEN:
        return send_telegram(message)

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
        if not send_telegram(chunk):
            ok = False
        time.sleep(0.5)
    return ok


# ============================================================
# [KR Market] 작업 함수들
# ============================================================

def update_daily_prices():
    """일별 가격 데이터 업데이트 — legacy script 제거됨, V2 엔진에서 자동 처리"""
    logger.info("⏭️ update_daily_prices: V2 엔진이 자체 수집하므로 skip")
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
    """VCP 시그널 상위 10개 텔레그램 전송 (종목 중복 제거)"""
    import pandas as pd

    signals_path = os.path.join(Config.DATA_DIR, 'signals_log.csv')
    if not os.path.exists(signals_path):
        logger.warning("⚠️ signals_log.csv가 없어 VCP 알림을 건너뜁니다.")
        return

    with safe_read(signals_path):
        df = pd.read_csv(signals_path, encoding='utf-8-sig')
    df['ticker'] = df['ticker'].astype(str).str.zfill(6)

    if 'status' in df.columns:
        df = df[df['status'] == 'OPEN']
    if df.empty:
        logger.info("📭 열린 VCP 시그널이 없습니다.")
        return

    ticker_name_map = {}
    prices_path = os.path.join(Config.DATA_DIR, 'daily_prices.csv')
    if os.path.exists(prices_path):
        try:
            prices_df = pd.read_csv(prices_path, encoding='utf-8-sig')
            if 'ticker' in prices_df.columns and 'name' in prices_df.columns:
                ticker_name_map = dict(zip(
                    prices_df['ticker'].astype(str).str.zfill(6), prices_df['name']))
        except Exception as e:
            logger.warning(f"종목명 매핑 실패: {e}")

    if 'score' in df.columns:
        df = df.sort_values('score', ascending=False)
    df = df.drop_duplicates(subset='ticker', keep='first')

    unique_count = len(df)
    top_10 = df.head(10)

    today = datetime.now().strftime('%m/%d')
    msg = f"<b>📈 VCP 시그널 Top 10 ({today})</b>\n"
    msg += f"총 {unique_count}개 종목 중 상위 10개\n"
    msg += "────────────────────\n"

    for i, (_, row) in enumerate(top_10.iterrows(), 1):
        ticker = str(row.get('ticker', '')).zfill(6)
        name = row.get('name', '') or ticker_name_map.get(ticker, ticker)
        score = row.get('score', 0)
        entry = row.get('entry_price', 0)
        foreign = row.get('foreign_5d', 0)
        inst = row.get('inst_5d', 0)

        supply_icon = ""
        if foreign > 0 and inst > 0:
            supply_icon = "🔥"
        elif foreign > 0:
            supply_icon = "🌍"
        elif inst > 0:
            supply_icon = "🏛"

        msg += f"\n{i}. <b>{name}</b> ({ticker}) {supply_icon}\n"
        msg += f"   점수: {score:.1f} | 진입: {entry:,.0f}원\n"
        if foreign != 0 or inst != 0:
            msg += f"   외인: {foreign:+,} | 기관: {inst:+,}\n"

    send_telegram(msg)


def collect_historical_institutional():
    """과거 수급 데이터 수집 (히스토리 축적용)"""
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
    """AI 분석 JSON 생성 (kr_ai_analysis.json) — signals_log.csv OPEN 시그널 기반"""
    logger.info("🤖 AI 분석 JSON 생성 중 (signals_log.csv → kr_ai_analysis.json)...")
    try:
        import pandas as pd

        signals_path = os.path.join(Config.DATA_DIR, 'signals_log.csv')
        if not os.path.exists(signals_path):
            logger.warning("⚠️ 시그널 로그가 없어 AI 분석을 건너뜁니다.")
            return True

        with safe_read(signals_path):
            df = pd.read_csv(signals_path, dtype={'ticker': str})
        df['ticker'] = df['ticker'].str.zfill(6)

        if 'status' not in df.columns:
            return True

        df = df[df['status'] == 'OPEN']
        if df.empty:
            logger.info("분석할 OPEN 시그널이 없습니다.")
            return True

        # 종목명 매핑
        name_map, market_map = {}, {}
        try:
            stocks_path = os.path.join(Config.DATA_DIR, 'korean_stocks_list.csv')
            if os.path.exists(stocks_path):
                stocks = pd.read_csv(stocks_path, dtype={'ticker': str})
                stocks['ticker'] = stocks['ticker'].str.zfill(6)
                name_map = dict(zip(stocks['ticker'], stocks['name']))
                if 'market' in stocks.columns:
                    market_map = dict(zip(stocks['ticker'], stocks['market']))
        except Exception:
            pass

        # 점수 상위 + 중복 제거
        df = df.sort_values('score', ascending=False).drop_duplicates('ticker')
        signals = []
        for _, row in df.iterrows():
            t = row['ticker']
            signals.append({
                'ticker': t,
                'name': name_map.get(t, t),
                'score': float(row.get('score', 0)),
                'contraction_ratio': float(row.get('contraction_ratio', 0)),
                'foreign_5d': int(row.get('foreign_5d', 0)),
                'inst_5d': int(row.get('inst_5d', 0)),
                'entry_price': float(row.get('entry_price', 0)),
                'current_price': float(row.get('entry_price', 0)),
                'return_pct': 0,
                'signal_date': str(row.get('signal_date', '')),
                'market': market_map.get(t, ''),
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
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        today_str = datetime.now().strftime('%Y%m%d')
        history_dir = os.path.join(Config.DATA_DIR, 'history')
        os.makedirs(history_dir, exist_ok=True)
        history_path = os.path.join(history_dir, f'kr_ai_analysis_{today_str}.json')

        with open(history_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        logger.info(f"✅ AI 분석 JSON 저장 완료: {len(target_signals)}개 시그널 → {json_path}")
        return True

    except Exception as e:
        logger.error(f"❌ AI 분석 실패: {e}")
        return False


def generate_daily_report():
    """일일 리포트 생성"""
    logger.info("📊 일일 리포트 생성 중...")
    try:
        import pandas as pd
        signals_path = os.path.join(Config.DATA_DIR, 'signals_log.csv')

        if os.path.exists(signals_path):
            with safe_read(signals_path):
                df = pd.read_csv(signals_path, encoding='utf-8-sig')

            open_signals = len(df[df['status'] == 'OPEN'])
            closed_signals = len(df[df['status'] == 'CLOSED'])
            today = datetime.now().strftime('%Y-%m-%d')
            today_signals = len(df[df['signal_date'] == today])

            report = {
                'date': today,
                'open_signals': open_signals,
                'closed_signals': closed_signals,
                'today_new_signals': today_signals,
                'total_signals': len(df),
                'generated_at': datetime.now().isoformat(),
                'env': {'base_dir': Config.BASE_DIR, 'python': Config.PYTHON_PATH}
            }

            report_path = os.path.join(Config.DATA_DIR, 'daily_report.json')
            with open(report_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)

            logger.info(f"✅ 일일 리포트: 열림 {open_signals}개, 청산 {closed_signals}개, 신규 {today_signals}개")
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
        us_briefing_path = os.path.join(Config.BASE_DIR, 'us_market', 'output', 'briefing.json')
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
            restarts = [l for l in entries if 'DOWN' in l or '재시작' in l]
            if restarts:
                lines.append(f"")
                lines.append(f"⚠️ <b>Flask 재시작</b>: {len(restarts)}회")
                for r in restarts[-2:]:
                    lines.append(f"   └ {r[:60]}")
            else:
                lines.append(f"")
                lines.append(f"✅ <b>Flask 안정</b>: 재시작 없음")

        send_telegram('\n'.join(lines))
        logger.info("✅ 아침 상태 리포트 전송 완료")
        return True

    except Exception as e:
        logger.error(f"❌ 아침 리포트 실패: {e}")
        return False


def update_jongga_v2():
    """종가베팅 V2 데이터 업데이트 + S/A급 텔레그램 전송"""
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
        timeout=600
    )

    if success:
        try:
            json_path = os.path.join(Config.DATA_DIR, "jongga_v2_latest.json")
            if os.path.exists(json_path):
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
                    # 시그널 텍스트 생성 (중복 방지: stock_code 기준 dedup)
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

                    # 메시지 분할 (4000자 제한)
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

                    # 전송 (각 chunk 1회씩만)
                    for i, chunk in enumerate(chunks):
                        if i > 0:
                            chunk = f"<b>🎯 종가베팅 V2 계속 ({i+1}/{len(chunks)})</b>\n" + chunk
                        send_telegram(chunk)
                        time.sleep(0.5)

        except Exception as e:
            logger.error(f"❌ 종가베팅 결과 전송 실패: {e}")

    return success


def _build_vcp_top10_text() -> str:
    """VCP Top10 텍스트 생성 (텔레그램 전송 없이 텍스트만)"""
    try:
        import pandas as pd
        signals_path = os.path.join(Config.DATA_DIR, 'signals_log.csv')
        if not os.path.exists(signals_path):
            return ""

        with safe_read(signals_path):
            df = pd.read_csv(signals_path, encoding='utf-8-sig')
        df['ticker'] = df['ticker'].astype(str).str.zfill(6)
        if 'status' in df.columns:
            df = df[df['status'] == 'OPEN']
        if df.empty:
            return ""

        ticker_name_map = {}
        prices_path = os.path.join(Config.DATA_DIR, 'daily_prices.csv')
        if os.path.exists(prices_path):
            try:
                prices_df = pd.read_csv(prices_path, encoding='utf-8-sig')
                if 'ticker' in prices_df.columns and 'name' in prices_df.columns:
                    ticker_name_map = dict(zip(
                        prices_df['ticker'].astype(str).str.zfill(6), prices_df['name']))
            except Exception:
                pass

        if 'score' in df.columns:
            df = df.sort_values('score', ascending=False)
        df = df.drop_duplicates(subset='ticker', keep='first')

        top_10 = df.head(10)
        today = datetime.now().strftime('%m/%d')
        text = f"<b>📈 VCP Top 10 ({today})</b>\n"

        for i, (_, row) in enumerate(top_10.iterrows(), 1):
            ticker = str(row.get('ticker', '')).zfill(6)
            name = row.get('name', '') or ticker_name_map.get(ticker, ticker)
            score = row.get('score', 0)
            foreign = row.get('foreign_5d', 0)
            inst = row.get('inst_5d', 0)

            icon = ""
            if foreign > 0 and inst > 0:
                icon = "🔥"
            elif foreign > 0:
                icon = "🌍"
            elif inst > 0:
                icon = "🏛"

            text += f"{i}. <b>{name}</b> {score:.0f}점 {icon}\n"

        return text
    except Exception as e:
        logger.error(f"VCP Top10 텍스트 생성 실패: {e}")
        return ""


# ── KR 올업데이트 (15:00 통합) ──

def run_kr_full_update(skip_sync: bool = False):
    """KR 종가베팅 업데이트 (15:00) — 종가베팅V2 + 수급/AI/리포트 → 텔레그램
    ※ VCP 시그널은 16:00 run_vcp_all_markets()에서 별도 실행
    """
    logger.info("=" * 60)
    logger.info("🇰🇷 KR 종가베팅 업데이트 시작 (15:00)")
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

    elapsed = int(time.time() - start_time)
    success_count = sum(1 for _, s in results if s)
    total_count = len(results)
    summary_lines = [f"  {'✅' if s else '❌'} {n}" for n, s in results]

    logger.info(f"📋 KR 종가베팅 업데이트 완료: {success_count}/{total_count} ({elapsed}초)")

    send_telegram(
        f"<b>🇰🇷 15시 종가베팅 업데이트 완료</b>\n"
        f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')} ({elapsed}초)\n"
        f"결과: {success_count}/{total_count}\n\n"
        + "\n".join(summary_lines)
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

    logger.info(f"📋 전 시장 VCP 업데이트 완료: {success_count}/3 ({elapsed}초)")

    send_telegram(
        f"<b>📈 16시 전 시장 VCP 업데이트 완료</b>\n"
        f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')} ({elapsed}초)\n"
        f"결과: {success_count}/3\n\n"
        + "\n".join(summary_lines)
    )

    if not skip_sync:
        auto_git_push('vcp')

    return all(r[1] for r in results)


def run_vcp_enhanced_scan(market: str) -> bool:
    """US / Crypto VCP Enhanced Scanner 실행 (vcp_enhanced_scanner.py --market {market})"""
    script = os.path.join(Config.BASE_DIR, 'vcp_enhanced_scanner.py')
    if not os.path.exists(script):
        logger.warning(f"⚠️ vcp_enhanced_scanner.py 없음 — {market} VCP 스킵")
        return False
    return run_command(
        [Config.PYTHON_PATH, script, '--market', market],
        f'{market} VCP Enhanced Scan',
        timeout=Config.SIGNAL_TIMEOUT
    )


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
    picks_path = os.path.join(Config.BASE_DIR, 'us_market_preview', 'output', 'top_picks.json')
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

        tracker_path = os.path.join(Config.BASE_DIR, 'us_market_preview', 'performance_tracker.py')
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
        if crypto_dir not in sys.path:
            sys.path.insert(0, crypto_dir)

        from market_gate import run_market_gate_sync
        result = run_market_gate_sync()

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
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(gate_json, f, ensure_ascii=False, indent=2)

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

        with open(history_path, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

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
    """Crypto VCP 스캔 (in-process, gate-aware)"""
    global _crypto_gate

    logger.info("🔍 Crypto VCP 스캔 시작...")

    if _crypto_gate == "RED":
        logger.info("🔴 Gate RED — 방어적 모드 스캔 (축소 유니버스)")
        # RED에서도 top 50 스캔 실행 (축적 기회 탐색)

    try:
        crypto_dir = Config.CRYPTO_MARKET_DIR
        if crypto_dir not in sys.path:
            sys.path.insert(0, crypto_dir)

        from run_scan import run_scan_sync
        result = run_scan_sync()

        published = result.get('published', 0) if isinstance(result, dict) else 0
        logger.info(f"🔍 Crypto VCP: {published}개 시그널 발행")

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
    return send_telegram(msg)


def _notify_crypto_signals(count: int) -> bool:
    """Crypto VCP 시그널 발견 알림"""
    if count <= 0:
        return False
    now_str = datetime.now().strftime('%m/%d %H:%M')
    return send_telegram(
        f"🔍 <b>Crypto VCP Signal Alert</b> ({now_str})\n\n"
        f"새로운 VCP 시그널 {count}개 발견!"
    )


def notify_crypto_briefing() -> bool:
    """Crypto Briefing 텔레그램 알림"""
    data = _load_json(os.path.join(Config.CRYPTO_OUTPUT_DIR, 'crypto_briefing.json'))
    if not data:
        return False

    today_str = datetime.now().strftime('%m/%d')
    msg = f"<b>🪙 Crypto Market Briefing ({today_str})</b>\n\n"

    # 시가총액 & BTC 도미넌스
    market = data.get('market_summary', {})
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
    coins = data.get('major_coins', {})
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
    fg = data.get('fear_greed', {})
    fg_score = fg.get('current_score') or fg.get('score') or fg.get('value')
    fg_level = fg.get('level', fg.get('classification', 'N/A'))
    if fg_score is not None:
        fg_em = _fear_greed_emoji(fg_score)
        msg += f"🧭 Fear &amp; Greed: {fg_score} ({fg_level}) {fg_em}\n"

    # Gate 상태
    gate_data = data.get('market_gate', data.get('gate', {}))
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

    send_telegram(msg)
    logger.info(f"🌐 전체 업데이트 완료: {success_count}/{total_count} ({overall_elapsed}초)")

    return success_count == total_count


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

    def setup_schedules(self):
        """스케줄 등록"""
        weekdays = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday']

        for day in weekdays:
            # 04:00 — US Market 전체 데이터 갱신 + Smart Money Top 5 텔레그램
            getattr(schedule.every(), day).at(Config.US_UPDATE_TIME).do(run_us_market_update)
            # 09:00 — 일별 상태 리포트 텔레그램
            getattr(schedule.every(), day).at(Config.MORNING_REPORT_TIME).do(send_morning_status_report)
            # 09:30 — US Track Record 스냅샷 + 성과 추적
            getattr(schedule.every(), day).at(Config.US_TRACK_TIME).do(save_us_track_record_snapshot)
            # 15:00 — 종가베팅 V2 + 수급/AI/리포트 (VCP 제외)
            getattr(schedule.every(), day).at(Config.KR_UPDATE_TIME).do(run_kr_full_update)
            # 16:00 — 전 시장 VCP 시그널 (KR + US + Crypto)
            getattr(schedule.every(), day).at(Config.VCP_UPDATE_TIME).do(run_vcp_all_markets)

        # 토요일 히스토리 수집
        schedule.every().saturday.at(Config.HISTORY_TIME).do(collect_historical_institutional)

        # Crypto — 매 4시간 24/7 (00/04/08/12/16/20 KST)
        for t in Config.CRYPTO_TIMES:
            schedule.every().day.at(t).do(run_crypto_pipeline)

        logger.info("📅 스케줄 등록 완료:")
        logger.info(f"   🇺🇸 평일 {Config.US_UPDATE_TIME}  US Market 전체 갱신 + Smart Money Top 5")
        logger.info(f"   📋 평일 {Config.MORNING_REPORT_TIME}  일별 상태 리포트 → 텔레그램")
        logger.info(f"   🇺🇸 평일 {Config.US_TRACK_TIME}  US Track Record 스냅샷")
        logger.info(f"   🇰🇷 평일 {Config.KR_UPDATE_TIME}  종가베팅 V2 + 수급/AI/리포트 → 텔레그램")
        logger.info(f"   📈 평일 {Config.VCP_UPDATE_TIME}  전 시장 VCP 시그널 (KR+US+Crypto) → 텔레그램")
        logger.info(f"   🇰🇷 토요일 {Config.HISTORY_TIME}  히스토리 수집")
        logger.info(f"   🪙 매 4시간 {', '.join(Config.CRYPTO_TIMES)}  Crypto 전체 파이프라인")

    def run(self):
        """스케줄러 실행"""
        logger.info("⏰ 통합 스케줄러 시작... (US + KR + Crypto)")
        logger.info("   Ctrl+C / SIGTERM으로 종료")

        send_telegram(
            "<b>⏰ MarketFlow 통합 스케줄러 시작</b>\n\n"
            f"🇺🇸 US Market: {Config.US_UPDATE_TIME} (평일)\n"
            f"🇰🇷 종가베팅: {Config.KR_UPDATE_TIME} (평일)\n"
            f"📈 VCP 전시장: {Config.VCP_UPDATE_TIME} (평일)\n"
            f"🪙 Crypto: 매 4시간 24/7 ({', '.join(Config.CRYPTO_TIMES)})\n"
            f"📍 {Config.BASE_DIR}"
        )

        while self.running:
            try:
                schedule.run_pending()
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
    parser.add_argument('--kr-update', action='store_true', help='KR 종가베팅 업데이트 (15:00)')
    parser.add_argument('--vcp', action='store_true', help='전 시장 VCP 시그널 (KR+US+Crypto, 16:00)')
    parser.add_argument('--history', action='store_true', help='KR 히스토리 수집만')

    # US Market
    parser.add_argument('--us-pro', action='store_true', help='US Market 전체 갱신 + Smart Money Top 5')
    parser.add_argument('--us-track', action='store_true', help='US Track Record 스냅샷')

    # Crypto
    parser.add_argument('--crypto', action='store_true', help='Crypto 전체 파이프라인 (4시간 주기)')
    parser.add_argument('--crypto-gate', action='store_true', help='Crypto Gate Check만')
    parser.add_argument('--crypto-scan', action='store_true', help='Crypto VCP Scan만')

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("🚀 MarketFlow 통합 스케줄러")
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

    # ── 스케줄러 모드 ──
    if Config.SCHEDULE_ENABLED:
        scheduler = Scheduler()
        scheduler.setup_schedules()
        scheduler.run()
    else:
        if not ran_any:
            logger.info("⚠️ 스케줄 비활성화됨 (KR_MARKET_SCHEDULE_ENABLED=false)")


if __name__ == "__main__":
    main()

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
    KR_UPDATE_TIME = os.environ.get('KR_MARKET_UPDATE_TIME', '15:00')   # 종가베팅 V2
    VCP_UPDATE_TIME = os.environ.get('VCP_UPDATE_TIME', '16:00')         # 전 시장 VCP 시그널
    WAVE_SCAN_TIME = os.environ.get('WAVE_SCAN_TIME', '16:30')           # Wave 패턴 스캔
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

    # pykrx로 OHLCV 수집 (per-ticker, 안정적)
    use_pykrx = True
    try:
        from pykrx import stock as pykrx_stock
    except ImportError:
        use_pykrx = False
        logger.warning("pykrx 미설치, FDR DataReader 폴백")

    failed = 0
    for i, ticker in enumerate(tickers):
        try:
            if use_pykrx:
                ohlcv = pykrx_stock.get_market_ohlcv(start_str, end_str, ticker)
                if ohlcv is None or ohlcv.empty:
                    continue
                for date_idx, row in ohlcv.iterrows():
                    all_rows.append({
                        'ticker': ticker,
                        'date': date_idx.strftime('%Y-%m-%d'),
                        'name': names_map.get(ticker, ''),
                        'current_price': float(row.get('종가', 0)),
                        'change': float(row.get('등락률', 0)),
                        'change_rate': float(row.get('등락률', 0)),
                        'high': float(row.get('고가', 0)),
                        'low': float(row.get('저가', 0)),
                        'open': float(row.get('시가', 0)),
                        'volume': int(row.get('거래량', 0)),
                        'update_time': now_str,
                    })
            else:
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
        except Exception:
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

    # composite score 기준 정��
    signals.sort(key=lambda s: s.get('composite', {}).get('score', 0)
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
        score = comp.get('score', 0) if isinstance(comp, dict) else 0
        price = s.get('price', {})
        close = price.get('close', 0) if isinstance(price, dict) else 0
        change = price.get('change_pct', 0) if isinstance(price, dict) else 0

        # 패턴 정보
        trend = s.get('trend_template', {})
        tt_pass = trend.get('passed', False) if isinstance(trend, dict) else False
        vcp = s.get('vcp_pattern', {})
        vcp_pass = vcp.get('detected', False) if isinstance(vcp, dict) else False

        icons = []
        if tt_pass:
            icons.append("📊")
        if vcp_pass:
            icons.append("🔺")
        icon_str = ' '.join(icons)

        msg += f"\n{i}. <b>{name}</b> ({symbol}) {icon_str}\n"
        msg += f"   점수: {score:.1f} | {close:,.0f}원 ({change:+.1f}%)\n"

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
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

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
            restarts = [l for l in entries if '🔴' in l or '재시작' in l or '❌' in l]
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
    """종가베팅 V2 데이터 업데이트 + S/A급 텔레그램 전송 (재시도는 _with_record 위임)"""
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

    if not success:
        return False

    if success:
        try:
            json_path = os.path.join(Config.DATA_DIR, "jongga_v2_latest.json")
            # 결과 파일 검증
            if not os.path.exists(json_path) or (time.time() - os.path.getmtime(json_path)) > 300:
                logger.warning("⚠️ 종가베팅 결과 파일 없거나 오래됨")
                return False
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

    signals.sort(key=lambda s: s.get('composite', {}).get('score', 0)
                 if isinstance(s.get('composite'), dict) else 0, reverse=True)

    top_10 = signals[:10]
    today = datetime.now().strftime('%m/%d')
    text = f"<b>📈 VCP Top 10 ({today})</b>\n"

    for i, s in enumerate(top_10, 1):
        name = s.get('name', s.get('symbol', '?'))
        symbol = s.get('symbol', '?')
        comp = s.get('composite', {})
        score = comp.get('score', 0) if isinstance(comp, dict) else 0
        price = s.get('price', {})
        close = price.get('close', 0) if isinstance(price, dict) else 0
        change = price.get('change_pct', 0) if isinstance(price, dict) else 0
        text += f"{i}. <b>{name}({symbol})</b> {score:.1f}점 {close:,.0f}원 ({change:+.1f}%)\n"

    return text


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

    logger.info(f"📋 전 시장 VCP 업데이트 완료: {success_count}/{len(results)} ({elapsed}초)")

    send_telegram(
        f"<b>📈 16시 전 시장 VCP 업데이트 완료</b>\n"
        f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')} ({elapsed}초)\n"
        f"결과: {success_count}/{len(results)}\n\n"
        + "\n".join(summary_lines)
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
                mtime = os.path.getmtime(result_file)
                file_age = time.time() - mtime
                if file_age > 300:  # 5분 이상 된 파일 = 갱신 안 됨
                    logger.warning(f"⚠️ {market_upper} VCP 결과 파일이 오래됨 ({int(file_age)}초)")
                    if attempt < max_retries:
                        time.sleep(10)
                    continue
                logger.info(f"✅ {market_upper} VCP 검증 완료: {len(signals)}개 시그널")
                return True
            except Exception as e:
                logger.warning(f"⚠️ {market_upper} VCP 결과 파일 읽기 실패: {e}")
        else:
            logger.warning(f"⚠️ {market_upper} VCP 결과 파일 없음: {result_file}")

        if attempt < max_retries:
            time.sleep(10)

    send_telegram(f"❌ {market_upper} VCP 스캔 {max_retries}회 실패")
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
    """Crypto VCP 스캔 (in-process, gate-aware) — 결과 JSON 저장 + 텔레그램"""
    global _crypto_gate

    logger.info("🔍 Crypto VCP 스캔 시작...")

    gate = _crypto_gate or "UNKNOWN"
    top_n = 50 if gate == "RED" else 200
    if gate == "RED":
        logger.info("🔴 Gate RED — 방어적 모드 스캔 (축소 유니버스 top 50)")

    try:
        crypto_dir = Config.CRYPTO_MARKET_DIR
        if crypto_dir not in sys.path:
            sys.path.insert(0, crypto_dir)

        from run_scan import run_scan_sync
        result = run_scan_sync(top_n=top_n)

        published = result.get('published', 0) if isinstance(result, dict) else 0
        logger.info(f"🔍 Crypto VCP: {published}개 시그널 발행")

        # 결과를 vcp_crypto_latest.json에 저장
        out = {
            'metadata': {
                'generated_at': datetime.now().isoformat(),
                'market': 'CRYPTO',
                'gate': gate,
                'universe_size': result.get('universe_size', 0),
            },
            'signals': result.get('top_signals', []),
            'summary': {
                'setups_4h': result.get('setups_4h', 0),
                'setups_1d': result.get('setups_1d', 0),
                'signals_4h': result.get('signals_4h', 0),
                'signals_1d': result.get('signals_1d', 0),
                'published': published,
            },
        }
        out_path = os.path.join(Config.DATA_DIR, 'vcp_crypto_latest.json')
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
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

    # 개별 실패 알림
    failed = [name for name, ok in results if not ok]
    if failed:
        send_telegram(
            f"⚠️ <b>Crypto 파이프라인 부분 실패</b>\n\n"
            f"성공: {success_count}/{len(results)}\n"
            f"실패: {', '.join(failed)}\n"
            f"시간: {datetime.now().strftime('%H:%M')}"
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

    send_telegram(msg)
    logger.info(f"🌐 전체 업데이트 완료: {success_count}/{total_count} ({overall_elapsed}초)")

    return success_count == total_count


# ============================================================
# 마지막 실행 기록 (missed schedule recovery용)
# ============================================================

_LAST_RUN_FILE = os.path.join(Config.DATA_DIR, 'scheduler_last_run.json')


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


def _was_run_recently(task_key: str, hours: int = 4) -> bool:
    """해당 task_key가 최근 N시간 내 실행되었는지 확인 (자정 경계 안전)"""
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
    """해당 task_key가 오늘 실행됐거나 최근 2시간 내 실행됐는지 (자정 경계 안전)"""
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

        # ── 평일 전용 작업 ──
        weekday_tasks = [
            # (예정시각_분, task_key, 실행함수, 라벨, 마감시각_분)
            # 마감시각: 이 시각 이후에는 실행하지 않음 (다음 작업과 충돌 방지)
            (4 * 60,  'us_market',  run_us_market_update,        'US 마켓 전체 갱신',  8 * 60),
            (9 * 60,  'morning_report', send_morning_status_report, '일별 상태 리포트', 12 * 60),
            (9 * 60 + 30, 'us_track', save_us_track_record_snapshot, 'US Track Record', 12 * 60),
            (15 * 60, 'kr_jongga',  run_kr_full_update,          'KR 종가베팅',        15 * 60 + 50),
            (16 * 60, 'vcp_all',    run_vcp_all_markets,         'VCP 전시장',         17 * 60),
        ]

        # ── 매일 실행 작업 (Crypto - 주말 포함) ──
        # Crypto는 4시간 간격이라 가장 최근 놓친 것만 복구
        crypto_times_min = [0, 4*60, 8*60, 12*60, 16*60, 20*60]

        recovered = []

        # 평일 작업 복구
        if weekday < 5:  # Mon-Fri
            for sched_min, task_key, task_fn, label, deadline_min in weekday_tasks:
                if hour_min <= sched_min:
                    continue  # 아직 예정 시각 전
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
            msg = (
                f"<b>🔄 놓친 스케줄 복구 완료</b>\n"
                f"⏰ {now.strftime('%Y-%m-%d %H:%M')}\n"
                f"복구: {len(recovered)}개\n\n"
                + "\n".join(f"  ✅ {r}" for r in recovered)
            )
            send_telegram(msg)
            logger.info(f"🔄 놓친 스케줄 복구: {len(recovered)}개 — {', '.join(recovered)}")
        else:
            logger.info("✅ 놓친 스케줄 없음 (모두 정상)")
    finally:
        _missed_check_lock.release()


# ============================================================
# Wave 패턴 스캔
# ============================================================

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

        return True
    except Exception as e:
        logger.error(f"❌ Wave 스캔 실패: {e}", exc_info=True)
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
            for attempt in range(1 + max_retries):
                try:
                    if attempt > 0:
                        logger.info(f"🔄 {task_key} 재시도 {attempt}/{max_retries} ({retry_delay}초 후)")
                        time.sleep(retry_delay)

                    result = task_fn()

                    # 1차: 리턴값 체크
                    success = (result is None or result)

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
                            send_telegram(f"✅ {task_key} 재시도 {attempt}회 만에 성공")
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

        jongga_verify = _verify_file_today(os.path.join(Config.DATA_DIR, 'jongga_v2_latest.json'))
        vcp_kr_verify = _verify_file_today(os.path.join(Config.DATA_DIR, 'vcp_kr_latest.json'))
        us_verify = _verify_file_today(os.path.join(Config.BASE_DIR, 'us_market', 'output', 'briefing.json'))
        us_track_verify = _verify_file_today(os.path.join(Config.BASE_DIR, 'us_market', 'output', 'performance_report.json'))
        crypto_verify = _verify_file_today(os.path.join(Config.DATA_DIR, 'vcp_crypto_latest.json'))

        for day in weekdays:
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
            # 15:00 — 종가베팅 V2 + 수급/AI/리포트 (VCP 제외)
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
        logger.info(f"   🇺🇸 평일 {Config.US_UPDATE_TIME}  US Market 전체 갱신 + Smart Money Top 5")
        logger.info(f"   📋 평일 {Config.MORNING_REPORT_TIME}  일별 상태 리포트 → 텔레그램")
        logger.info(f"   🇺🇸 평일 {Config.US_TRACK_TIME}  US Track Record 스냅샷")
        logger.info(f"   🇰🇷 평일 {Config.KR_UPDATE_TIME}  종가베팅 V2 + 수급/AI/리포트 → 텔레그램")
        logger.info(f"   📈 평일 {Config.VCP_UPDATE_TIME}  전 시장 VCP 시그널 (KR+US+Crypto) → 텔레그램")
        logger.info(f"   🌊 평일 {Config.WAVE_SCAN_TIME}  Wave 패턴 스캔 (KR)")
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

        last_missed_check = time.time()
        MISSED_CHECK_INTERVAL = 300  # 5분마다 놓친 스케줄 점검

        while self.running:
            try:
                schedule.run_pending()

                # 주기적 놓친 스케줄 복구 (Windows sleep/hibernate 대응)
                now = time.time()
                if now - last_missed_check > MISSED_CHECK_INTERVAL:
                    threading.Thread(
                        target=check_and_run_missed_tasks,
                        name="missed-task-recovery",
                        daemon=True
                    ).start()
                    last_missed_check = now

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

    # Wave Pattern
    parser.add_argument('--wave-scan', action='store_true', help='Wave 패턴 스캔 (KR 전 종목)')

    args = parser.parse_args()

    # ── PID 파일 기반 단일 인스턴스 (--daemon 모드) ──
    if args.daemon:
        pid_file = os.path.join(Config.LOG_DIR, 'scheduler.pid')
        if os.path.exists(pid_file):
            try:
                with open(pid_file, 'r') as f:
                    old_pid = int(f.read().strip())
                # PID 생존 확인
                result = subprocess.run(
                    ['tasklist', '/FI', f'PID eq {old_pid}', '/NH', '/FO', 'CSV'],
                    capture_output=True, text=True, timeout=10
                )
                if str(old_pid) in result.stdout:
                    logger.warning(f"⚠️ Scheduler 이미 실행 중 (PID {old_pid}). 종료.")
                    print(f"[SCHEDULER] 이미 실행 중 (PID {old_pid}). 종료.")
                    sys.exit(0)
            except (ValueError, IOError, subprocess.TimeoutExpired):
                pass

        # PID 기록
        os.makedirs(Config.LOG_DIR, exist_ok=True)
        with open(pid_file, 'w') as f:
            f.write(str(os.getpid()))
        logger.info(f"🔒 Scheduler PID 파일 생성 (PID {os.getpid()})")

        def _cleanup_pid():
            try:
                if os.path.exists(pid_file):
                    with open(pid_file, 'r') as f:
                        pid = int(f.read().strip())
                    if pid == os.getpid():
                        os.remove(pid_file)
            except Exception:
                pass
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

    # ── 스케줄러 모드 ──
    if Config.SCHEDULE_ENABLED:
        scheduler = Scheduler()
        scheduler.setup_schedules()
        # 놓친 스케줄 복구 (스케줄 등록 후, 데몬 루프 시작 전)
        check_and_run_missed_tasks()
        scheduler.run()
    else:
        if not ran_any:
            logger.info("⚠️ 스케줄 비활성화됨 (KR_MARKET_SCHEDULE_ENABLED=false)")


if __name__ == "__main__":
    main()

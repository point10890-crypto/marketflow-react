#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Crypto Market - 자동 스케줄러 + 텔레그램 알림

환경 변수:
- CRYPTO_MARKET_DIR: 프로젝트 루트 디렉토리 (기본: 자동 감지)
- CRYPTO_MARKET_LOG_DIR: 로그 디렉토리 (기본: CRYPTO_MARKET_DIR/../logs)
- CRYPTO_MARKET_SCHEDULE_ENABLED: 스케줄 활성화 (기본: true)

스케줄 (KST) - 24/7, 휴일 없음:
- 매일 00:00, 06:00, 12:00, 18:00 → gate_check (시장 게이트 체크)
- 매일 00:05, 06:05, 12:05, 18:05 → vcp_scan (VCP 스캔, RED 시 스킵)
- 매일 09:00 → briefing + prediction + risk
- 매일 09:05 → 텔레그램 브리핑 알림
- 매일 03:00 → lead-lag 분석

실행 방법:
  python3 -m crypto_market.scheduler --daemon       # 데몬 모드 (스케줄러)
  python3 -m crypto_market.scheduler --now           # 즉시 전체 파이프라인
  python3 -m crypto_market.scheduler --gate          # 게이트 체크만
  python3 -m crypto_market.scheduler --scan          # VCP 스캔만
  python3 -m crypto_market.scheduler --briefing      # 브리핑만
  python3 -m crypto_market.scheduler --prediction    # 예측만
  python3 -m crypto_market.scheduler --risk          # 리스크만
  python3 -m crypto_market.scheduler --notify        # 텔레그램 알림만 (기존 데이터)
"""

import os
import sys
import time
import logging
import subprocess
import signal
import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

# schedule 패키지
try:
    import schedule
except ImportError:
    print("'schedule' 패키지가 필요합니다: pip install schedule")
    sys.exit(1)


# ============================================================
# 설정
# ============================================================

class Config:
    """Crypto Market 스케줄러 설정"""

    # 디렉토리
    BASE_DIR = os.environ.get(
        'CRYPTO_MARKET_DIR',
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    LOG_DIR = os.environ.get('CRYPTO_MARKET_LOG_DIR', os.path.join(BASE_DIR, 'logs'))
    CRYPTO_MARKET_DIR = os.path.join(BASE_DIR, 'crypto_market')
    OUTPUT_DIR = os.path.join(CRYPTO_MARKET_DIR, 'output')

    # 스케줄
    SCHEDULE_ENABLED = os.environ.get('CRYPTO_MARKET_SCHEDULE_ENABLED', 'true').lower() == 'true'

    # 타임아웃
    TASK_TIMEOUT = int(os.environ.get('CRYPTO_MARKET_TASK_TIMEOUT', '600'))
    BRIEFING_TIMEOUT = int(os.environ.get('CRYPTO_MARKET_BRIEFING_TIMEOUT', '300'))

    # Python 실행 경로
    PYTHON_PATH = os.environ.get('CRYPTO_MARKET_PYTHON', sys.executable)

    @classmethod
    def ensure_dirs(cls):
        """필요한 디렉토리 생성"""
        Path(cls.LOG_DIR).mkdir(parents=True, exist_ok=True)
        Path(cls.OUTPUT_DIR).mkdir(parents=True, exist_ok=True)


# ============================================================
# 로깅 설정
# ============================================================

def setup_logging():
    """로깅 설정"""
    Config.ensure_dirs()

    log_file = os.path.join(Config.LOG_DIR, 'crypto_scheduler.log')

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
# 텔레그램 알림
# ============================================================

def _load_env():
    """dotenv 로드"""
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(Config.BASE_DIR, '.env'))
    except ImportError:
        pass


def send_telegram(text: str) -> bool:
    """텔레그램 메시지 전송 (Markdown 시도 후 plain text 폴백)"""
    _load_env()

    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '')

    if not token or not chat_id:
        logger.warning("텔레그램 토큰/채팅 ID가 설정되지 않았습니다.")
        return False

    try:
        import requests
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }, timeout=10)
        if resp.status_code == 200:
            return True
        # Markdown 파싱 에러 시 plain text로 재시도
        logger.warning(f"텔레그램 전송 실패 ({resp.status_code}): {resp.text[:200]}")
        resp2 = requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
        }, timeout=10)
        return resp2.status_code == 200
    except Exception as e:
        logger.error(f"텔레그램 전송 실패: {e}")
        return False


def send_telegram_long(text: str) -> bool:
    """긴 텔레그램 메시지를 4000자 단위로 분할 전송"""
    MAX_LEN = 4000

    if len(text) <= MAX_LEN:
        return send_telegram(text)

    # 단락 경계로 분할
    chunks = []
    current = ""
    for paragraph in text.split("\n\n"):
        if len(current) + len(paragraph) + 2 > MAX_LEN:
            if current:
                chunks.append(current.strip())
            current = paragraph
        else:
            current = current + "\n\n" + paragraph if current else paragraph

    if current.strip():
        chunks.append(current.strip())

    success = True
    for chunk in chunks:
        if not send_telegram(chunk):
            success = False
        time.sleep(0.5)  # rate limit 방지

    return success


# ============================================================
# 텔레그램 알림 메시지 생성
# ============================================================

def _load_json(filepath: str) -> Optional[dict]:
    """JSON 파일 로드"""
    try:
        if not os.path.exists(filepath):
            logger.warning(f"파일 없음: {filepath}")
            return None
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"JSON 로드 실패 ({filepath}): {e}")
        return None


def _format_number(n, prefix="", suffix="", decimals=2):
    """숫자 포맷팅"""
    if n is None:
        return "N/A"
    if isinstance(n, (int, float)):
        if abs(n) >= 1000:
            return f"{prefix}{n:,.{decimals}f}{suffix}"
        return f"{prefix}{n:.{decimals}f}{suffix}"
    return str(n)


def _change_emoji(change):
    """등락 이모지"""
    if change is None:
        return ""
    if change > 0:
        return "🔴" if change > 3.0 else "🔺"
    elif change < 0:
        return "🟢" if change < -3.0 else "🔻"
    return "➡️"


def _fear_greed_emoji(score):
    """Fear & Greed 이모지"""
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


def _gate_emoji(gate):
    """Gate 이모지"""
    if gate == "GREEN":
        return "🟢"
    elif gate == "YELLOW":
        return "🟡"
    elif gate == "RED":
        return "🔴"
    return "⚪"


def notify_crypto_briefing() -> bool:
    """Crypto Briefing 텔레그램 알림

    crypto_market/output/crypto_briefing.json 읽어서
    시총, BTC 도미넌스, 주요 코인(BTC/ETH/SOL), Fear & Greed, Gate 상태 전송
    """
    data = _load_json(os.path.join(Config.OUTPUT_DIR, 'crypto_briefing.json'))
    if not data:
        return False

    today_str = datetime.now().strftime('%m/%d')
    msg = f"🪙 *Crypto Market Briefing* ({today_str})\n\n"

    # 시가총액 & BTC 도미넌스
    market = data.get('market_summary', {})
    total_mcap = market.get('total_market_cap')
    btc_dom = market.get('btc_dominance')

    if total_mcap is not None:
        if isinstance(total_mcap, (int, float)) and total_mcap >= 1e12:
            msg += f"💰 *시가총액*: ${total_mcap / 1e12:.2f}T\n"
        elif isinstance(total_mcap, (int, float)) and total_mcap >= 1e9:
            msg += f"💰 *시가총액*: ${total_mcap / 1e9:.1f}B\n"
        else:
            msg += f"💰 *시가총액*: {_format_number(total_mcap, prefix='$')}\n"
    if btc_dom is not None:
        msg += f"👑 *BTC 도미넌스*: {btc_dom:.1f}%\n"
    msg += "\n"

    # 주요 코인: BTC / ETH / SOL
    msg += "📊 *주요 코인*\n"
    coins = data.get('major_coins', {})

    # Handle both dict and list formats
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

    # Fear & Greed Index
    fg = data.get('fear_greed', {})
    fg_score = fg.get('current_score') or fg.get('score') or fg.get('value')
    fg_level = fg.get('level', fg.get('classification', 'N/A'))
    if fg_score is not None:
        fg_emoji = _fear_greed_emoji(fg_score)
        msg += f"🧭 *Fear & Greed: {fg_score} ({fg_level})* {fg_emoji}\n"

    # Gate 상태
    gate_data = data.get('market_gate', data.get('gate', {}))
    if not gate_data:
        gate_data = _load_json(os.path.join(Config.OUTPUT_DIR, 'market_gate.json')) or {}

    gate = gate_data.get('gate', gate_data.get('gate_color'))
    gate_score = gate_data.get('score', gate_data.get('gate_score'))
    if gate is not None:
        g_emoji = _gate_emoji(gate)
        score_str = f" (점수: {gate_score})" if gate_score is not None else ""
        msg += f"{g_emoji} *Market Gate: {gate}*{score_str}\n"

    send_telegram_long(msg.strip())
    return True


def notify_crypto_signals(signals_count: int) -> bool:
    """VCP 시그널 발견 알림"""
    if signals_count <= 0:
        return False

    today_str = datetime.now().strftime('%m/%d %H:%M')
    msg = (
        f"🔍 *Crypto VCP Signal Alert* ({today_str})\n\n"
        f"새로운 VCP 시그널 {signals_count}개 발견!"
    )
    return send_telegram(msg)


def notify_gate_change(gate: str, score: int) -> bool:
    """Gate 상태 전환 알림"""
    g_emoji = _gate_emoji(gate)
    now_str = datetime.now().strftime('%m/%d %H:%M')
    msg = (
        f"{g_emoji} *Crypto Gate 전환* ({now_str})\n\n"
        f"Market Gate: *{gate}* (점수: {score})\n"
    )
    if gate == "RED":
        msg += "⚠️ VCP 스캔 일시 중단됨"
    elif gate == "GREEN":
        msg += "✅ 공격 모드 진입"
    else:
        msg += "⚡ 주의 모드"

    return send_telegram(msg)


# ============================================================
# 작업 함수들
# ============================================================

def run_command(cmd: list, description: str, timeout: int = 600) -> bool:
    """명령 실행 헬퍼 (실시간 출력 스트리밍)"""
    logger.info(f"시작: {description}")
    start = time.time()

    try:
        process = subprocess.Popen(
            cmd,
            cwd=Config.BASE_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            env={**os.environ, 'PYTHONPATH': Config.BASE_DIR},
            bufsize=1
        )

        for line in iter(process.stdout.readline, ''):
            clean = line.strip()
            if clean:
                logger.info(f"   > {clean}")

        process.wait(timeout=timeout)

        elapsed = time.time() - start

        if process.returncode == 0:
            logger.info(f"완료: {description} ({elapsed:.1f}초)")
            return True
        else:
            logger.error(f"실패: {description} (Exit Code: {process.returncode})")
            return False

    except subprocess.TimeoutExpired:
        process.kill()
        logger.error(f"타임아웃: {description}")
        return False
    except Exception as e:
        logger.error(f"에러: {description} - {e}")
        return False


# 현재 gate 상태를 모듈 레벨로 추적
_current_gate = "YELLOW"
_current_gate_score = 50


def run_gate_check() -> bool:
    """Market Gate 체크 (in-process, orchestrator 동일 방식)"""
    global _current_gate, _current_gate_score

    logger.info("🚦 Market Gate 체크 시작...")

    try:
        # crypto_market/ 를 sys.path에 추가 (임포트용)
        crypto_dir = Config.CRYPTO_MARKET_DIR
        if crypto_dir not in sys.path:
            sys.path.insert(0, crypto_dir)

        from market_gate import run_market_gate_sync
        result = run_market_gate_sync()

        old_gate = _current_gate
        _current_gate = result.gate
        _current_gate_score = result.score

        logger.info(f"Gate: {_current_gate} (score: {_current_gate_score})")

        # JSON 캐시 저장 (Flask API용)
        gate_json = {
            'gate': result.gate,
            'score': result.score,
            'status': 'RISK_ON' if result.gate == 'GREEN' else ('RISK_OFF' if result.gate == 'RED' else 'NEUTRAL'),
            'reasons': result.reasons,
            'metrics': result.metrics,
            'generated_at': datetime.now().isoformat()
        }
        output_path = os.path.join(Config.OUTPUT_DIR, 'market_gate.json')
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(gate_json, f, ensure_ascii=False, indent=2)

        logger.info(f"Gate JSON 저장: {output_path}")

        # Append to gate history
        history_path = os.path.join(Config.OUTPUT_DIR, 'gate_history.json')
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
        # Keep max 90 entries
        history = history[-90:]

        with open(history_path, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

        logger.info(f"Gate history 저장: {history_path}")

        # Gate 전환 시 알림
        if old_gate != _current_gate:
            notify_gate_change(_current_gate, _current_gate_score)

        return True

    except Exception as e:
        logger.error(f"Gate 체크 실패: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_vcp_scan() -> bool:
    """VCP 스캔 (in-process, gate-aware)"""
    global _current_gate

    logger.info("🔍 VCP 스캔 시작...")

    # RED 게이트면 스킵
    if _current_gate == "RED":
        logger.info("Gate RED - VCP 스캔 스킵")
        return True

    try:
        crypto_dir = Config.CRYPTO_MARKET_DIR
        if crypto_dir not in sys.path:
            sys.path.insert(0, crypto_dir)

        from run_scan import run_scan_sync
        result = run_scan_sync()

        published = result.get('published', 0) if isinstance(result, dict) else 0
        logger.info(f"VCP 스캔 완료: {published}개 시그널 발행")

        if published > 0:
            notify_crypto_signals(published)

        return True

    except Exception as e:
        logger.error(f"VCP 스캔 실패: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_briefing() -> bool:
    """Crypto Briefing 실행 (subprocess)"""
    return run_command(
        [Config.PYTHON_PATH, os.path.join(Config.CRYPTO_MARKET_DIR, 'crypto_briefing.py')],
        'Crypto Briefing 생성',
        timeout=Config.BRIEFING_TIMEOUT
    )


def run_prediction() -> bool:
    """Crypto Prediction 실행 (subprocess)"""
    return run_command(
        [Config.PYTHON_PATH, os.path.join(Config.CRYPTO_MARKET_DIR, 'crypto_prediction.py')],
        'Crypto Prediction 실행',
        timeout=Config.TASK_TIMEOUT
    )


def run_risk() -> bool:
    """Crypto Risk 분석 실행 (subprocess)"""
    return run_command(
        [Config.PYTHON_PATH, os.path.join(Config.CRYPTO_MARKET_DIR, 'crypto_risk.py')],
        'Crypto Risk 분석',
        timeout=Config.TASK_TIMEOUT
    )


def run_leadlag() -> bool:
    """Lead-Lag 분석 실행 (subprocess)"""
    output_path = os.path.join(Config.CRYPTO_MARKET_DIR, 'lead_lag', 'results.json')
    return run_command(
        [
            Config.PYTHON_PATH,
            os.path.join(Config.CRYPTO_MARKET_DIR, 'run_lead_lag.py'),
            '--output', output_path,
            '--no-llm'
        ],
        'Lead-Lag 분석',
        timeout=Config.TASK_TIMEOUT
    )


# ============================================================
# 스케줄러
# ============================================================

class CryptoScheduler:
    """Crypto Market 스케줄러 (24/7, 휴일 없음)"""

    def __init__(self):
        self.running = True
        signal.signal(signal.SIGINT, self._signal_handler)
        if hasattr(signal, 'SIGTERM'):
            signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        logger.info(f"종료 시그널 수신 (signal={signum})")
        self.running = False

    def setup_schedules(self):
        """스케줄 등록 (24/7 무휴)"""
        # 매일 00:00, 06:00, 12:00, 18:00 → gate_check
        for t in ['00:00', '06:00', '12:00', '18:00']:
            schedule.every().day.at(t).do(run_gate_check)

        # 매일 00:05, 06:05, 12:05, 18:05 → vcp_scan
        for t in ['00:05', '06:05', '12:05', '18:05']:
            schedule.every().day.at(t).do(run_vcp_scan)

        # 매일 09:00 → briefing + prediction + risk
        schedule.every().day.at('09:00').do(run_briefing)
        schedule.every().day.at('09:00').do(run_prediction)
        schedule.every().day.at('09:00').do(run_risk)

        # 매일 09:05 → 텔레그램 브리핑 알림
        schedule.every().day.at('09:05').do(notify_crypto_briefing)

        # 매일 03:00 → lead-lag 분석
        schedule.every().day.at('03:00').do(run_leadlag)

        logger.info("스케줄 등록 완료:")
        logger.info("  - 매일 00/06/12/18:00 Market Gate 체크")
        logger.info("  - 매일 00/06/12/18:05 VCP 스캔 (RED 시 스킵)")
        logger.info("  - 매일 09:00 Briefing + Prediction + Risk")
        logger.info("  - 매일 09:05 텔레그램 브리핑 알림")
        logger.info("  - 매일 03:00 Lead-Lag 분석")

    def run(self):
        """스케줄러 메인 루프 (30초 간격 체크)"""
        logger.info("Crypto Market 스케줄러 시작... (Ctrl+C / SIGTERM으로 종료)")
        send_telegram(
            f"⏰ *Crypto Market 스케줄러 시작*\n\n"
            f"🚦 Gate 체크: 매일 00/06/12/18:00\n"
            f"🔍 VCP 스캔: 매일 00/06/12/18:05\n"
            f"📊 Briefing: 매일 09:00\n"
            f"📈 Lead-Lag: 매일 03:00"
        )

        while self.running:
            schedule.run_pending()
            time.sleep(30)

        logger.info("Crypto Market 스케줄러 종료")
        send_telegram("👋 *Crypto Market 스케줄러 종료*")


# ============================================================
# 메인
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='Crypto Market 자동 스케줄러')
    parser.add_argument('--now', action='store_true', help='즉시 전체 파이프라인 실행')
    parser.add_argument('--gate', action='store_true', help='게이트 체크만')
    parser.add_argument('--scan', action='store_true', help='VCP 스캔만')
    parser.add_argument('--briefing', action='store_true', help='브리핑만')
    parser.add_argument('--prediction', action='store_true', help='예측만')
    parser.add_argument('--risk', action='store_true', help='리스크 분석만')
    parser.add_argument('--notify', action='store_true', help='텔레그램 알림만 (기존 데이터)')
    parser.add_argument('--daemon', action='store_true', help='데몬 모드 (스케줄러)')

    args = parser.parse_args()

    # 시작 시 .env 로드 (데몬 환경에서도 확실하게)
    try:
        from dotenv import load_dotenv
        env_path = os.path.join(Config.BASE_DIR, '.env')
        load_dotenv(env_path, override=True)
        logger.info(f"  .env 로드: {env_path}")
    except ImportError:
        logger.warning("  dotenv 미설치 - 환경변수 직접 설정 필요")

    logger.info("=" * 60)
    logger.info("Crypto Market 스케줄러")
    logger.info("=" * 60)
    logger.info(f"  BASE_DIR: {Config.BASE_DIR}")
    logger.info(f"  LOG_DIR: {Config.LOG_DIR}")
    logger.info(f"  OUTPUT_DIR: {Config.OUTPUT_DIR}")
    logger.info(f"  PYTHON: {Config.PYTHON_PATH}")
    logger.info(f"  SCHEDULE_ENABLED: {Config.SCHEDULE_ENABLED}")
    logger.info("=" * 60)

    # --notify: 텔레그램 알림만 (기존 데이터 기반)
    if args.notify:
        notify_crypto_briefing()
        if not args.daemon:
            return

    # --now: 즉시 전체 파이프라인
    if args.now:
        logger.info("=" * 60)
        logger.info("Crypto Market 전체 파이프라인 시작")
        logger.info("=" * 60)

        start_time = time.time()
        send_telegram("🪙 *Crypto Market 업데이트 시작*")

        # 순차 실행
        results = []
        results.append(('Gate Check', run_gate_check()))
        results.append(('VCP Scan', run_vcp_scan()))
        results.append(('Briefing', run_briefing()))
        results.append(('Prediction', run_prediction()))
        results.append(('Risk', run_risk()))
        results.append(('Lead-Lag', run_leadlag()))

        # 브리핑 알림
        notify_crypto_briefing()

        elapsed = time.time() - start_time

        for name, ok in results:
            status = "OK" if ok else "FAIL"
            logger.info(f"  [{status}] {name}")

        success_count = sum(1 for _, ok in results if ok)
        total_count = len(results)

        if success_count == total_count:
            send_telegram(f"✅ *Crypto Market 업데이트 완료* ({elapsed/60:.1f}분, {success_count}/{total_count})")
        else:
            send_telegram(f"⚠️ *Crypto Market 업데이트 부분 완료* ({elapsed/60:.1f}분, {success_count}/{total_count})")

        if not args.daemon:
            return

    # --gate: 게이트 체크만
    if args.gate:
        run_gate_check()
        if not args.daemon:
            return

    # --scan: VCP 스캔만
    if args.scan:
        run_vcp_scan()
        if not args.daemon:
            return

    # --briefing: 브리핑만
    if args.briefing:
        run_briefing()
        if not args.daemon:
            return

    # --prediction: 예측만
    if args.prediction:
        run_prediction()
        if not args.daemon:
            return

    # --risk: 리스크 분석만
    if args.risk:
        run_risk()
        if not args.daemon:
            return

    # 데몬 모드
    if Config.SCHEDULE_ENABLED:
        sched = CryptoScheduler()
        sched.setup_schedules()
        sched.run()
    else:
        logger.info("스케줄 비활성화됨 (CRYPTO_MARKET_SCHEDULE_ENABLED=false)")


if __name__ == "__main__":
    main()

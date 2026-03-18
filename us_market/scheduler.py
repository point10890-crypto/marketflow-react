#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
US Market - 자동 스케줄러 + 텔레그램 알림

환경 변수:
- US_MARKET_DIR: 프로젝트 루트 디렉토리 (기본: 자동 감지)
- US_MARKET_LOG_DIR: 로그 디렉토리 (기본: US_MARKET_DIR/logs)
- US_MARKET_TZ: 타임존 (기본: Asia/Seoul)
- US_MARKET_SCHEDULE_ENABLED: 스케줄 활성화 (기본: true)

스케줄 (KST):
- 화~토 06:30 - 전체 파이프라인 (18 scripts) + 텔레그램 (= 미국 월~금 장 마감 후)
- 월~금 22:00 - 프리마켓 브리핑 (선물/지수/VIX) (= 미국 08:00 ET)

실행 방법:
  python3 -m us_market.scheduler --daemon       # 데몬 모드 (스케줄러)
  python3 -m us_market.scheduler --now           # 즉시 전체 파이프라인
  python3 -m us_market.scheduler --quick         # 빠른 업데이트 (AI 제외)
  python3 -m us_market.scheduler --briefing      # 프리마켓 브리핑만
  python3 -m us_market.scheduler --notify        # 텔레그램 알림만 (기존 데이터)
  python3 -m us_market.scheduler --force         # 주말/휴일 무시하고 실행
"""

import os
import sys
import time
import logging
import subprocess
import signal
import argparse
import json
import glob
from datetime import datetime, date
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
    """US Market 스케줄러 설정"""

    # 디렉토리
    BASE_DIR = os.environ.get(
        'US_MARKET_DIR',
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    LOG_DIR = os.environ.get('US_MARKET_LOG_DIR', os.path.join(BASE_DIR, 'logs'))
    US_MARKET_DIR = os.path.join(BASE_DIR, 'us_market')
    OUTPUT_DIR = os.path.join(US_MARKET_DIR, 'output')
    HISTORY_DIR = os.path.join(US_MARKET_DIR, 'history')

    # 스케줄
    SCHEDULE_ENABLED = os.environ.get('US_MARKET_SCHEDULE_ENABLED', 'true').lower() == 'true'
    TZ = os.environ.get('US_MARKET_TZ', 'Asia/Seoul')

    # 스케줄 시간 (KST)
    FULL_PIPELINE_TIME = os.environ.get('US_MARKET_FULL_TIME', '06:30')
    PREMARKET_TIME = os.environ.get('US_MARKET_PREMARKET_TIME', '22:00')

    # 타임아웃
    FULL_TIMEOUT = int(os.environ.get('US_MARKET_FULL_TIMEOUT', '3600'))
    BRIEFING_TIMEOUT = int(os.environ.get('US_MARKET_BRIEFING_TIMEOUT', '300'))

    # Python 실행 경로
    PYTHON_PATH = os.environ.get('US_MARKET_PYTHON', sys.executable)

    @classmethod
    def ensure_dirs(cls):
        """필요한 디렉토리 생성"""
        Path(cls.LOG_DIR).mkdir(parents=True, exist_ok=True)


# ============================================================
# 로깅 설정
# ============================================================

def setup_logging():
    """로깅 설정"""
    Config.ensure_dirs()

    log_file = os.path.join(Config.LOG_DIR, 'us_scheduler.log')

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
    """텔레그램 메시지 전송"""
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
        return "🔴" if change > 1.5 else "🔺"
    elif change < 0:
        return "🟢" if change < -1.5 else "🔻"
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


def notify_market_briefing() -> bool:
    """Message 1: Market Briefing - 지수, VIX, Fear&Greed, 채권/환율/원자재"""
    data = _load_json(os.path.join(Config.OUTPUT_DIR, 'market_briefing.json'))
    if not data:
        return False

    market = data.get('market_data', {})
    today_str = datetime.now().strftime('%m/%d')

    msg = f"🇺🇸 *US Market Briefing* ({today_str})\n\n"

    # 주요 지수
    msg += "📊 *주요 지수*\n"
    indices = market.get('indices', {})
    for key in ['SPY', 'QQQ', 'DIA', 'IWM']:
        idx = indices.get(key, {})
        name = idx.get('name', key)
        price = idx.get('price')
        change = idx.get('change')
        if price is not None:
            emoji = _change_emoji(change)
            msg += f"{emoji} {name}: {_format_number(price)} ({change:+.2f}%)\n"
    msg += "\n"

    # 선물
    futures = market.get('futures', {})
    if futures:
        msg += "📉 *선물*\n"
        for key in ['ES=F', 'NQ=F', 'YM=F']:
            ft = futures.get(key, {})
            name = ft.get('name', key)
            price = ft.get('price')
            change = ft.get('change')
            if price is not None:
                emoji = _change_emoji(change)
                msg += f"{emoji} {name}: {_format_number(price)} ({change:+.2f}%)\n"
        msg += "\n"

    # 채권/환율/원자재
    msg += "💰 *채권/환율/원자재*\n"

    bonds = market.get('bonds', {})
    tnx = bonds.get('^TNX', {})
    if tnx.get('price') is not None:
        msg += f"10Y Treasury: {tnx['price']:.2f}% ({tnx.get('change', 0):+.2f}%)\n"

    currencies = market.get('currencies', {})
    usdkrw = currencies.get('USDKRW=X', {})
    if usdkrw.get('price') is not None:
        msg += f"USD/KRW: {usdkrw['price']:,.0f}\n"

    dxy = currencies.get('DX-Y.NYB', {})
    if dxy.get('price') is not None:
        msg += f"Dollar Index: {dxy['price']:.2f} ({dxy.get('change', 0):+.2f}%)\n"

    commodities = market.get('commodities', {})
    gold = commodities.get('GC=F', {})
    oil = commodities.get('CL=F', {})
    btc = commodities.get('BTC-USD', {})

    parts = []
    if gold.get('price') is not None:
        parts.append(f"Gold: ${gold['price']:,.0f}")
    if oil.get('price') is not None:
        parts.append(f"Oil: ${oil['price']:.2f}")
    if btc.get('price') is not None:
        parts.append(f"BTC: ${btc['price']:,.0f}")
    if parts:
        msg += " | ".join(parts) + "\n"
    msg += "\n"

    # VIX & Fear/Greed
    vix = data.get('vix', market.get('vix', {}))
    fg = data.get('fear_greed', {})

    if vix.get('value') is not None:
        msg += f"VIX: {vix['value']:.2f} ({vix.get('change', 0):+.2f}%)\n"

    if fg.get('score') is not None:
        fg_emoji = _fear_greed_emoji(fg['score'])
        msg += f"🧭 *Fear & Greed: {fg['score']} ({fg.get('level', 'N/A')})* {fg_emoji}\n"

    send_telegram(msg.strip())
    return True


def notify_top10_picks() -> bool:
    """Message 2: Smart Money Top 10 with scores, prices, AI recommendation"""
    data = _load_json(os.path.join(Config.OUTPUT_DIR, 'final_top10_report.json'))
    if not data:
        return False

    picks = data.get('top_picks', [])
    if not picks:
        return False

    today_str = datetime.now().strftime('%m/%d')
    msg = f"🏆 *Smart Money Top 10* ({today_str})\n\n"

    rank_emojis = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣', '🔟']

    for i, pick in enumerate(picks[:10]):
        ticker = pick.get('ticker', '?')
        score = pick.get('final_score', 0)
        price = pick.get('current_price', 0)
        stage = pick.get('sd_stage', '')
        inst = pick.get('inst_pct', 0)
        ai_rec = pick.get('ai_recommendation', '')
        rank_emoji = rank_emojis[i] if i < len(rank_emojis) else f"{i+1}."

        msg += f"{rank_emoji} *{ticker}* | Score: {score:.1f} | ${price:,.2f}\n"
        msg += f"   {stage} | Inst: {inst:.1f}% | AI: {ai_rec}\n"

    send_telegram_long(msg.strip())
    return True


def notify_performance() -> bool:
    """Message 3: Performance Tracking - 최근 picks 성과"""
    history_files = sorted(glob.glob(
        os.path.join(Config.HISTORY_DIR, 'picks_*.json')
    ), reverse=True)

    if not history_files:
        logger.info("성과 추적 데이터 없음")
        return False

    # 최근 5개 날짜
    recent_files = history_files[:5]
    today_str = datetime.now().strftime('%m/%d')
    msg = f"📈 *Performance Tracking* ({today_str})\n\n"

    # smart_money_current.json에서 추적 데이터 확인
    current = _load_json(os.path.join(Config.OUTPUT_DIR, 'smart_money_current.json'))
    if current and current.get('picks'):
        current_tickers = {p['ticker']: p for p in current['picks']}
    else:
        current_tickers = {}

    entries = []
    for fpath in recent_files:
        hist = _load_json(fpath)
        if not hist or not hist.get('picks'):
            continue

        analysis_date = hist.get('analysis_date', '')
        picks = hist['picks']

        # 성과 계산: 현재가 vs 분석 시점 가격
        gains = []
        for p in picks[:10]:
            ticker = p.get('ticker', '')
            price_at = p.get('price_at_analysis', 0)
            if ticker in current_tickers and price_at > 0:
                cur_price = current_tickers[ticker].get('price_at_analysis', price_at)
                gain = (cur_price - price_at) / price_at * 100
                gains.append(gain)

        if gains:
            avg_return = sum(gains) / len(gains)
            win_rate = sum(1 for g in gains if g > 0) / len(gains) * 100
            entries.append((analysis_date, avg_return, win_rate, len(gains)))

    if entries:
        for d, ret, wr, cnt in entries:
            try:
                d_fmt = datetime.strptime(d, '%Y-%m-%d').strftime('%m/%d')
            except ValueError:
                d_fmt = d
            emoji = "🟢" if ret >= 0 else "🔴"
            msg += f"{emoji} {d_fmt}: Avg {ret:+.1f}% | Win {wr:.0f}% ({cnt}종목)\n"
    else:
        msg += "추적 데이터 집계 중...\n"
        # 최근 picks 날짜만 표시
        for fpath in recent_files[:3]:
            hist = _load_json(fpath)
            if hist:
                d = hist.get('analysis_date', os.path.basename(fpath))
                n = len(hist.get('picks', []))
                msg += f"  {d}: {n}종목 추적 중\n"

    send_telegram(msg.strip())
    return True


def notify_ai_highlights() -> bool:
    """Message 4: AI Analysis highlights"""
    data = _load_json(os.path.join(Config.OUTPUT_DIR, 'market_briefing.json'))
    if not data:
        return False

    ai = data.get('ai_analysis', {})
    content = ai.get('content', '')

    if not content:
        logger.info("AI 분석 콘텐츠 없음")
        return False

    today_str = datetime.now().strftime('%m/%d')
    msg = f"🤖 *AI Analysis* ({today_str})\n\n"

    # 핵심 요약 섹션 추출 (첫 번째 ### 블록)
    lines = content.split('\n')
    summary_lines = []
    in_summary = False
    for line in lines:
        if '핵심 요약' in line or '핵심요약' in line:
            in_summary = True
            continue
        if in_summary:
            if line.startswith('### ') and summary_lines:
                break
            if line.strip():
                # Markdown 볼드/링크 정리
                clean = line.strip()
                if clean.startswith('- '):
                    clean = clean[2:]
                summary_lines.append(clean)

    if summary_lines:
        msg += '\n'.join(summary_lines[:5])
    else:
        # 핵심 요약이 없으면 첫 300자
        msg += content[:300] + "..."

    send_telegram_long(msg.strip())
    return True


def notify_full_summary() -> bool:
    """전체 알림 오케스트레이션 (Message 1~4)"""
    logger.info("텔레그램 전체 알림 전송 시작...")

    results = []

    # Message 1: Market Briefing
    results.append(('Market Briefing', notify_market_briefing()))
    time.sleep(1)

    # Message 2: Top 10 Picks
    results.append(('Top 10 Picks', notify_top10_picks()))
    time.sleep(1)

    # Message 3: Performance
    results.append(('Performance', notify_performance()))
    time.sleep(1)

    # Message 4: AI Highlights
    results.append(('AI Highlights', notify_ai_highlights()))

    for name, ok in results:
        status = "OK" if ok else "SKIP"
        logger.info(f"  [{status}] {name}")

    return any(r[1] for r in results)


def notify_premarket_summary() -> bool:
    """프리마켓 브리핑 알림 (선물/지수/VIX 경량 버전)"""
    data = _load_json(os.path.join(Config.OUTPUT_DIR, 'market_briefing.json'))
    if not data:
        return False

    market = data.get('market_data', {})
    today_str = datetime.now().strftime('%m/%d')

    msg = f"🌅 *US Pre-Market Briefing* ({today_str})\n\n"

    # 선물
    futures = market.get('futures', {})
    if futures:
        msg += "📉 *선물*\n"
        for key in ['ES=F', 'NQ=F', 'YM=F']:
            ft = futures.get(key, {})
            name = ft.get('name', key)
            price = ft.get('price')
            change = ft.get('change')
            if price is not None:
                emoji = _change_emoji(change)
                msg += f"{emoji} {name}: {_format_number(price)} ({change:+.2f}%)\n"
        msg += "\n"

    # VIX
    vix = data.get('vix', market.get('vix', {}))
    if vix.get('value') is not None:
        msg += f"VIX: {vix['value']:.2f} ({vix.get('change', 0):+.2f}%)\n"

    # Fear & Greed
    fg = data.get('fear_greed', {})
    if fg.get('score') is not None:
        fg_emoji = _fear_greed_emoji(fg['score'])
        msg += f"🧭 Fear & Greed: {fg['score']} ({fg.get('level', 'N/A')}) {fg_emoji}\n"
    msg += "\n"

    # 주요 지수 (간략)
    indices = market.get('indices', {})
    msg += "📊 *전일 종가*\n"
    for key in ['SPY', 'QQQ']:
        idx = indices.get(key, {})
        name = idx.get('name', key)
        price = idx.get('price')
        change = idx.get('change')
        if price is not None:
            msg += f"{name}: {_format_number(price)} ({change:+.2f}%)\n"

    send_telegram(msg.strip())
    return True


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


def _is_trading_day() -> bool:
    """오늘(KST 기준)이 미국 거래일 다음날인지 확인

    화~토 06:30에 실행: 미국 월~금 장 마감 후
    """
    from us_market.holidays import US_MARKET_HOLIDAYS

    now = datetime.now()
    # 06:30 실행이므로 전날이 미국 거래일이어야 함
    us_date = now.date()
    if now.hour < 7:
        from datetime import timedelta
        us_date = us_date - timedelta(days=1)

    weekday = us_date.weekday()  # 0=월 ... 6=일

    # 주말이면 스킵
    if weekday >= 5:
        return False

    # 미국 휴일이면 스킵
    if us_date.strftime('%Y-%m-%d') in US_MARKET_HOLIDAYS:
        return False

    return True


def run_full_update() -> bool:
    """전체 파이프라인: update_all.py 실행"""
    return run_command(
        [Config.PYTHON_PATH, os.path.join(Config.US_MARKET_DIR, 'update_all.py')],
        'US Market 전체 업데이트',
        timeout=Config.FULL_TIMEOUT
    )


def run_quick_update() -> bool:
    """빠른 업데이트: update_all.py --quick"""
    return run_command(
        [Config.PYTHON_PATH, os.path.join(Config.US_MARKET_DIR, 'update_all.py'), '--quick'],
        'US Market 빠른 업데이트',
        timeout=Config.FULL_TIMEOUT
    )


def run_briefing_only() -> bool:
    """시황 브리핑만: us_market_briefing.py --quick"""
    return run_command(
        [Config.PYTHON_PATH, os.path.join(Config.US_MARKET_DIR, 'us_market_briefing.py'), '--quick'],
        'US Market 브리핑',
        timeout=Config.BRIEFING_TIMEOUT
    )


def run_full_pipeline(force: bool = False) -> None:
    """전체 파이프라인 + 텔레그램 알림 (스케줄 트리거용)"""
    logger.info("=" * 60)
    logger.info("US Market 전체 파이프라인 시작")
    logger.info("=" * 60)

    # 거래일 체크
    if not force and not _is_trading_day():
        logger.info("오늘은 미국 거래일이 아닙니다. 스킵.")
        return

    start_time = time.time()
    send_telegram("🇺🇸 *US Market 업데이트 시작*")

    success = run_full_update()
    elapsed = time.time() - start_time

    if success:
        logger.info(f"전체 파이프라인 완료 ({elapsed:.0f}초). 텔레그램 알림 전송...")
        notify_full_summary()
        send_telegram(f"✅ *US Market 업데이트 완료* ({elapsed/60:.1f}분)")
    else:
        send_telegram(f"❌ *US Market 업데이트 실패* ({elapsed/60:.1f}분)")

    logger.info("=" * 60)


def run_premarket_briefing(force: bool = False) -> None:
    """프리마켓 브리핑 (스케줄 트리거용)"""
    logger.info("US Market 프리마켓 브리핑 시작")

    # 월~금만 실행 (KST 22:00 = 미국 월~금 오전)
    if not force:
        weekday = datetime.now().weekday()
        if weekday >= 5:  # 토, 일
            logger.info("주말 - 프리마켓 브리핑 스킵")
            return

    success = run_briefing_only()

    if success:
        notify_premarket_summary()
    else:
        send_telegram("⚠️ *US Pre-Market 브리핑 실패*")


# ============================================================
# 스케줄러
# ============================================================

class USMarketScheduler:
    """US Market 스케줄러"""

    def __init__(self):
        self.running = True
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        logger.info(f"종료 시그널 수신 (signal={signum})")
        self.running = False

    def setup_schedules(self):
        """스케줄 등록"""
        # 화~토 06:30 → 전체 파이프라인 (= 미국 월~금 장 마감 후)
        for day in ['tuesday', 'wednesday', 'thursday', 'friday', 'saturday']:
            getattr(schedule.every(), day).at(Config.FULL_PIPELINE_TIME).do(run_full_pipeline)

        # 월~금 22:00 → 프리마켓 브리핑 (= 미국 08:00 ET)
        for day in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday']:
            getattr(schedule.every(), day).at(Config.PREMARKET_TIME).do(run_premarket_briefing)

        logger.info("스케줄 등록 완료:")
        logger.info(f"  - 화~토 {Config.FULL_PIPELINE_TIME} 전체 파이프라인 + 텔레그램")
        logger.info(f"  - 월~금 {Config.PREMARKET_TIME} 프리마켓 브리핑")

    def run(self):
        """스케줄러 메인 루프"""
        logger.info("US Market 스케줄러 시작... (Ctrl+C / SIGTERM으로 종료)")
        send_telegram(
            f"⏰ *US Market 스케줄러 시작*\n\n"
            f"🇺🇸 전체 파이프라인: 화~토 {Config.FULL_PIPELINE_TIME}\n"
            f"🌅 프리마켓 브리핑: 월~금 {Config.PREMARKET_TIME}"
        )

        while self.running:
            schedule.run_pending()
            time.sleep(30)

        logger.info("US Market 스케줄러 종료")
        send_telegram("👋 *US Market 스케줄러 종료*")


# ============================================================
# 메인
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='US Market 자동 스케줄러')
    parser.add_argument('--now', action='store_true', help='즉시 전체 파이프라인 실행')
    parser.add_argument('--quick', action='store_true', help='빠른 업데이트 (AI 제외)')
    parser.add_argument('--briefing', action='store_true', help='프리마켓 브리핑만')
    parser.add_argument('--notify', action='store_true', help='텔레그램 알림만 (기존 데이터)')
    parser.add_argument('--daemon', action='store_true', help='데몬 모드 (스케줄러)')
    parser.add_argument('--force', action='store_true', help='주말/휴일 무시하고 실행')

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
    logger.info("US Market 스케줄러")
    logger.info("=" * 60)
    logger.info(f"  BASE_DIR: {Config.BASE_DIR}")
    logger.info(f"  LOG_DIR: {Config.LOG_DIR}")
    logger.info(f"  OUTPUT_DIR: {Config.OUTPUT_DIR}")
    logger.info(f"  PYTHON: {Config.PYTHON_PATH}")
    logger.info(f"  SCHEDULE_ENABLED: {Config.SCHEDULE_ENABLED}")
    logger.info("=" * 60)

    # --notify: 텔레그램 알림만 (기존 데이터 기반)
    if args.notify:
        notify_full_summary()
        if not args.daemon:
            return

    # --now: 즉시 전체 파이프라인
    if args.now:
        run_full_pipeline(force=args.force)
        if not args.daemon:
            return

    # --quick: 빠른 업데이트
    if args.quick:
        success = run_quick_update()
        if success:
            notify_full_summary()
        if not args.daemon:
            return

    # --briefing: 프리마켓 브리핑
    if args.briefing:
        run_premarket_briefing(force=args.force)
        if not args.daemon:
            return

    # 데몬 모드
    if Config.SCHEDULE_ENABLED:
        sched = USMarketScheduler()
        sched.setup_schedules()
        sched.run()
    else:
        logger.info("스케줄 비활성화됨 (US_MARKET_SCHEDULE_ENABLED=false)")


if __name__ == "__main__":
    main()

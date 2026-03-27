# app/utils/scheduler.py
"""통합 백그라운드 스케줄러 — Render 클라우드 + 로컬 겸용

구조:
1. start_cloud_scheduler()  → Render 배포 시 gunicorn 내부에서 스케줄러 실행
2. start_kr_price_scheduler() → KR 종가베팅 가격 실시간 업데이트 (5분 간격)

특징:
- schedule 라이브러리 기반 (무료, 유료 플랜 불필요)
- gunicorn 멀티워커에서 한 워커만 스케줄러 실행 (파일 락)
- subprocess 대신 in-process 함수 호출 (Render 호환)
- KST 시간대 기반 스케줄링
- 텔레그램 알림 지원
"""

import os
import sys
import json
import time
import logging
import subprocess
import threading
import traceback
from datetime import datetime, date, timedelta
from pathlib import Path

# .env 로드 보장 (standalone import 시에도 환경변수 사용 가능)
try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

# ── sys.path 오염 방지 (OneDrive/외부 경로 차단) ──
_blocked = ['kr_market_package', 'OneDrive', '바탕 화면', 'desktop',
            'closing_bet', 'us-market-pro', 'korean market']
sys.path = [p for p in sys.path if not any(b.lower() in p.lower() for b in _blocked)]

# ── 고정 경로 (중앙 paths.py에서 임포트) ──────────────────
from app.utils.paths import BASE_DIR, DATA_DIR, LOGS_DIR as LOG_DIR

logger = logging.getLogger('cloud_scheduler')


# ============================================================
# KST 시간 유틸리티
# ============================================================

def _get_kst_now():
    """현재 KST 시간 반환"""
    try:
        from zoneinfo import ZoneInfo
        from datetime import timezone
        return datetime.now(ZoneInfo('Asia/Seoul'))
    except ImportError:
        # Python 3.8 이하 fallback
        try:
            import pytz
            kst = pytz.timezone('Asia/Seoul')
            return datetime.now(kst)
        except ImportError:
            # UTC+9 직접 계산
            from datetime import timezone, timedelta as td
            kst = timezone(td(hours=9))
            return datetime.now(kst)


def _is_weekday_kst():
    """KST 기준 평일인지 확인 (0=월 ~ 4=금)"""
    now = _get_kst_now()
    return now.weekday() < 5


def _is_saturday_kst():
    """KST 기준 토요일인지 확인"""
    return _get_kst_now().weekday() == 5


# ============================================================
# 텔레그램 유틸리티
# ============================================================

def _send_telegram(message: str) -> bool:
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
            else:
                logger.error(f"텔레그램(개인) 응답: {r.status_code} {r.text[:500]}")
        except Exception as e:
            logger.error(f"텔레그램(개인) 전송 실패: {e}")

    # 2) 채널 봇
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
            logger.error(f"텔레그램(채널) 전송 실패: {e}")

    return success


def _send_telegram_long(message: str) -> bool:
    """긴 텔레그램 메시지를 4000자 단위로 분할 전송"""
    MAX_LEN = 4000
    if len(message) <= MAX_LEN:
        return _send_telegram(message)

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
        if not _send_telegram(chunk):
            ok = False
        time.sleep(0.5)
    return ok


# ============================================================
# 작업 함수들 (In-Process 실행)
# ============================================================

def _run_jongga_v2():
    """종가베팅 V2 — in-process 실행"""
    logger.info("🎯 종가베팅 V2 분석 시작...")
    try:
        import asyncio
        # 프로젝트 루트를 sys.path에 추가
        if BASE_DIR not in sys.path:
            sys.path.insert(0, BASE_DIR)

        from engine.generator import run_screener

        # 분석 기준일 계산 (KST 기준)
        now = _get_kst_now()
        target_date = now.date()
        if now.hour < 9:
            target_date = target_date - timedelta(days=1)
        if target_date.weekday() == 6:  # 일요일
            target_date = target_date - timedelta(days=2)
        elif target_date.weekday() == 5:  # 토요일
            target_date = target_date - timedelta(days=1)

        logger.info(f"   분석 기준일: {target_date}")

        # 새 이벤트 루프에서 실행
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                run_screener(capital=50_000_000, markets=['KOSPI', 'KOSDAQ'], target_date=target_date)
            )
        finally:
            loop.close()

        logger.info("✅ 종가베팅 V2 분석 완료")

        # S/A급 텔레그램 전송
        _send_jongga_v2_telegram()
        return True

    except Exception as e:
        logger.error(f"❌ 종가베팅 V2 실패: {e}")
        traceback.print_exc()
        _send_telegram(f"❌ 종가베팅 V2 실패: {str(e)[:500]}")
        return False


def _send_jongga_v2_telegram():
    """종가베팅 V2 결과 텔레그램 전송 (S/A급만)"""
    try:
        json_path = os.path.join(DATA_DIR, "jongga_v2_latest.json")
        if not os.path.exists(json_path):
            return

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
            _send_telegram(header + "\n\n⚠️ S/A급 시그널 없음 (B급 제외됨)")
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
                _send_telegram(chunk)
                time.sleep(0.5)

    except Exception as e:
        logger.error(f"종가베팅 텔레그램 전송 실패: {e}")


def _run_institutional_data():
    """수급 데이터 업데이트 — in-process"""
    logger.info("📊 수급 데이터 업데이트 시작...")
    try:
        if BASE_DIR not in sys.path:
            sys.path.insert(0, BASE_DIR)

        # all_institutional_trend_data.py 를 직접 import
        os.environ['DATA_DIR'] = DATA_DIR
        from all_institutional_trend_data import main as inst_main
        inst_main()
        logger.info("✅ 수급 데이터 업데이트 완료")
        return True
    except ImportError:
        logger.warning("⚠️ all_institutional_trend_data 모듈 없음 — 스킵")
        return False
    except Exception as e:
        logger.error(f"❌ 수급 데이터 실패: {e}")
        traceback.print_exc()
        return False


def _run_vcp_signal_scan():
    """VCP 시그널 스캔 — in-process"""
    logger.info("📈 VCP 시그널 스캔 시작...")
    try:
        if BASE_DIR not in sys.path:
            sys.path.insert(0, BASE_DIR)

        from signal_tracker import main as signal_main
        signal_main()
        logger.info("✅ VCP 시그널 스캔 완료")
        return True
    except ImportError:
        logger.warning("⚠️ signal_tracker 모듈 없음 — 스킵")
        return False
    except Exception as e:
        logger.error(f"❌ VCP 시그널 실패: {e}")
        traceback.print_exc()
        return False


def _run_us_market_update():
    """US Market 데이터 업데이트 — subprocess (us_market/update_all.py)"""
    logger.info("🇺🇸 US Market 업데이트 시작...")
    try:
        update_script = os.path.join(BASE_DIR, 'us_market', 'update_all.py')
        if not os.path.exists(update_script):
            logger.warning(f"⚠️ US update script 없음: {update_script}")
            return False

        python_path = os.path.join(BASE_DIR, '.venv', 'Scripts', 'python.exe')
        if not os.path.exists(python_path):
            python_path = sys.executable

        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'

        result = subprocess.run(
            [python_path, update_script, '--no-telegram'],
            capture_output=True, text=True, timeout=1200,
            cwd=BASE_DIR, env=env,
        )

        if result.returncode == 0:
            logger.info("✅ US Market 업데이트 완료")
            _send_us_smart_money_telegram()
            return True
        else:
            logger.error(f"❌ US Market 업데이트 실패 (exit={result.returncode})")
            if result.stderr:
                logger.error(f"stderr: {result.stderr[-500:]}")
            return False
    except subprocess.TimeoutExpired:
        logger.error("❌ US Market 업데이트 타임아웃 (20분)")
        return False
    except Exception as e:
        logger.error(f"❌ US Market 업데이트 실패: {e}")
        traceback.print_exc()
        return False


def _send_us_smart_money_telegram():
    """US Smart Money Top 5 텔레그램"""
    try:
        picks_path = os.path.join(BASE_DIR, 'us_market', 'output', 'top_picks.json')
        if not os.path.exists(picks_path):
            return

        with open(picks_path, 'r', encoding='utf-8') as f:
            picks_data = json.load(f)

        top_picks = picks_data.get('top_picks', [])[:5]
        if not top_picks:
            return

        today = _get_kst_now().strftime('%m/%d')
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

        _send_telegram(msg)
    except Exception as e:
        logger.error(f"US 텔레그램 전송 실패: {e}")


def _run_crypto_pipeline():
    """Crypto 전체 파이프라인 — in-process (가능한 것만)"""
    logger.info("🪙 Crypto 파이프라인 시작...")
    try:
        if BASE_DIR not in sys.path:
            sys.path.insert(0, BASE_DIR)

        crypto_dir = os.path.join(BASE_DIR, 'crypto-analytics', 'crypto_market')
        if not os.path.isdir(crypto_dir):
            logger.warning("⚠️ crypto-analytics 디렉토리 없음 — 스킵")
            return False

        if crypto_dir not in sys.path:
            sys.path.insert(0, crypto_dir)

        results = []

        # Gate Check
        try:
            from market_gate import run_market_gate_sync
            gate_result = run_market_gate_sync()
            crypto_output = os.path.join(crypto_dir, 'output')
            os.makedirs(crypto_output, exist_ok=True)

            gate_json = {
                'gate': gate_result.gate,
                'score': gate_result.score,
                'status': 'RISK_ON' if gate_result.gate == 'GREEN' else ('RISK_OFF' if gate_result.gate == 'RED' else 'NEUTRAL'),
                'reasons': gate_result.reasons,
                'metrics': gate_result.metrics,
                'generated_at': datetime.now().isoformat()
            }
            with open(os.path.join(crypto_output, 'market_gate.json'), 'w', encoding='utf-8') as f:
                json.dump(gate_json, f, ensure_ascii=False, indent=2)

            results.append(('Gate', True))
            logger.info(f"🚦 Crypto Gate: {gate_result.gate} ({gate_result.score})")
        except Exception as e:
            logger.error(f"Crypto Gate 실패: {e}")
            results.append(('Gate', False))

        # VCP Scan
        try:
            from run_scan import run_scan_sync
            scan_result = run_scan_sync()
            results.append(('VCP', True))
        except Exception as e:
            logger.error(f"Crypto VCP 실패: {e}")
            results.append(('VCP', False))

        # Briefing, Prediction, Risk — subprocess fallback
        for script_name, label in [
            ('crypto_briefing.py', 'Briefing'),
            ('crypto_prediction.py', 'Prediction'),
            ('crypto_risk.py', 'Risk'),
        ]:
            script_path = os.path.join(crypto_dir, script_name)
            if os.path.exists(script_path):
                try:
                    import subprocess
                    result = subprocess.run(
                        [sys.executable, script_path],
                        cwd=os.path.join(BASE_DIR, 'crypto-analytics'),
                        capture_output=True, text=True, timeout=600,
                        env={**os.environ, 'PYTHONPATH': BASE_DIR, 'PYTHONIOENCODING': 'utf-8'}
                    )
                    results.append((label, result.returncode == 0))
                except Exception as e:
                    logger.error(f"Crypto {label} 실패: {e}")
                    results.append((label, False))
            else:
                logger.warning(f"⚠️ {script_name} 없음")
                results.append((label, False))

        success = sum(1 for _, ok in results if ok)
        logger.info(f"🪙 Crypto 파이프라인 완료: {success}/{len(results)}")
        return success > 0

    except Exception as e:
        logger.error(f"❌ Crypto 파이프라인 실패: {e}")
        traceback.print_exc()
        return False


# ============================================================
# System Diagnostics
# ============================================================

def _run_diagnostics_check():
    """시스템 자가진단 — 30분마다 실행, CRITICAL 시 텔레그램 알림"""
    try:
        from app.utils.diagnostics import run_diagnostics_and_alert
        run_diagnostics_and_alert()
        return True
    except ImportError:
        logger.warning("diagnostics module not found — skip")
        return False
    except Exception as e:
        logger.error(f"Diagnostics failed: {e}")
        return False


# ============================================================
# KR Round 1 & 2
# ============================================================

def _run_round1():
    """1차 업데이트 (15:10 KST) — 종가베팅 V2"""
    if not _is_weekday_kst():
        logger.info("⏭️ 주말 — Round 1 스킵")
        return True

    logger.info("=" * 50)
    logger.info("🇰🇷 [1차] 종가베팅 V2 시작")
    logger.info("=" * 50)
    return _run_jongga_v2()


def _run_round2():
    """2차 업데이트 (16:00 KST) — 수급/VCP/리포트"""
    if not _is_weekday_kst():
        logger.info("⏭️ 주말 — Round 2 스킵")
        return True

    logger.info("=" * 50)
    logger.info("🇰🇷 [2차] 데이터 갱신 + VCP 시작")
    logger.info("=" * 50)

    results = []
    results.append(('institutional', _run_institutional_data()))
    results.append(('vcp_signals', _run_vcp_signal_scan()))

    success_count = sum(1 for _, s in results if s)
    total_count = len(results)

    summary_lines = []
    for name, ok in results:
        status = "✅" if ok else "❌"
        summary_lines.append(f"{status} {name}")

    now_str = _get_kst_now().strftime('%Y-%m-%d %H:%M')
    msg = (
        f"<b>📊 16시 데이터 업데이트 완료</b>\n"
        f"⏰ {now_str}\n"
        f"결과: {success_count}/{total_count}\n"
        + "\n".join(summary_lines)
    )
    _send_telegram(msg)
    return True


def _run_us_update():
    """US 업데이트 (04:00 KST)"""
    if not _is_weekday_kst():
        logger.info("⏭️ 주말 — US 업데이트 스킵")
        return True

    logger.info("=" * 50)
    logger.info("🇺🇸 US Market 전체 갱신 시작")
    logger.info("=" * 50)
    return _run_us_market_update()


# ============================================================
# 전체 데이터 업데이트 (All-in-One)
# ============================================================

def _run_all_update():
    """매일 07:00 KST — 전체 데이터 올 업데이트 (US + KR + Crypto)

    모든 시장 데이터를 한 번에 갱신.
    개별 작업 실패 시에도 나머지 작업 계속 실행.
    """
    logger.info("=" * 60)
    logger.info("🌐 [ALL UPDATE] 전체 데이터 올 업데이트 시작 (07:00 KST)")
    logger.info("=" * 60)

    start_time = time.time()
    results = []

    # 1) US Market
    logger.info("━━━ [1/4] US Market ━━━")
    try:
        ok = _run_us_market_update()
        results.append(('🇺🇸 US Market', ok))
    except Exception as e:
        logger.error(f"US Market 실패: {e}")
        results.append(('🇺🇸 US Market', False))

    # 2) KR 수급/VCP
    logger.info("━━━ [2/4] KR 수급/VCP ━━━")
    try:
        inst_ok = _run_institutional_data()
        vcp_ok = _run_vcp_signal_scan()
        results.append(('🇰🇷 KR 수급', inst_ok))
        results.append(('🇰🇷 KR VCP', vcp_ok))
    except Exception as e:
        logger.error(f"KR 수급/VCP 실패: {e}")
        results.append(('🇰🇷 KR 수급/VCP', False))

    # 3) KR 종가베팅 V2
    logger.info("━━━ [3/4] KR 종가베팅 V2 ━━━")
    try:
        ok = _run_jongga_v2()
        results.append(('🎯 종가베팅 V2', ok))
    except Exception as e:
        logger.error(f"종가베팅 V2 실패: {e}")
        results.append(('🎯 종가베팅 V2', False))

    # 4) Crypto Pipeline
    logger.info("━━━ [4/4] Crypto Pipeline ━━━")
    try:
        ok = _run_crypto_pipeline()
        results.append(('🪙 Crypto', ok))
    except Exception as e:
        logger.error(f"Crypto 실패: {e}")
        results.append(('🪙 Crypto', False))

    # 결과 요약
    elapsed = time.time() - start_time
    success_count = sum(1 for _, ok in results if ok)
    total_count = len(results)

    summary_lines = []
    for name, ok in results:
        status = "✅" if ok else "❌"
        summary_lines.append(f"  {status} {name}")

    now_str = _get_kst_now().strftime('%Y-%m-%d %H:%M')
    msg = (
        f"<b>🌐 07:00 전체 올 업데이트 완료</b>\n"
        f"⏰ {now_str} ({elapsed:.0f}초)\n"
        f"결과: {success_count}/{total_count}\n\n"
        + "\n".join(summary_lines)
    )
    _send_telegram(msg)

    logger.info(f"🌐 [ALL UPDATE] 완료: {success_count}/{total_count} ({elapsed:.0f}초)")
    return success_count > 0


# ============================================================
# 클라우드 스케줄러 (Flask 백그라운드 스레드)
# ============================================================

_scheduler_started = False
_scheduler_lock = threading.Lock()


def start_cloud_scheduler():
    """Render 클라우드용 통합 스케줄러 시작

    - gunicorn 내에서 백그라운드 스레드로 실행
    - 멀티워커 환경에서 한 번만 실행 (파일 락)
    - schedule 라이브러리로 KST 기준 스케줄링
    - 시작 시 stale 데이터 감지 → 즉시 catch-up 실행
    - keep-alive self-ping으로 Render sleep 방지
    """
    global _scheduler_started

    with _scheduler_lock:
        if _scheduler_started:
            return
        _scheduler_started = True

    # 파일 락으로 멀티워커 중복 방지
    lock_path = os.path.join(DATA_DIR, '.scheduler.lock')
    try:
        from filelock import FileLock, Timeout
        lock = FileLock(lock_path, timeout=1)
        lock.acquire(timeout=1)
    except Exception:
        logger.info("[CloudScheduler] 다른 워커가 이미 실행 중 — 스킵")
        return

    thread = threading.Thread(target=_cloud_scheduler_loop, daemon=True, name='CloudScheduler')
    thread.start()
    logger.info("[CloudScheduler] 백그라운드 스케줄러 시작됨")

    # keep-alive 스레드: Render free tier sleep 방지 (12분마다 self-ping)
    keepalive_thread = threading.Thread(target=_keep_alive_loop, daemon=True, name='KeepAlive')
    keepalive_thread.start()
    logger.info("[CloudScheduler] Keep-alive 스레드 시작됨")


def _cloud_scheduler_loop():
    """스케줄러 메인 루프"""
    import schedule as sched

    # 로깅 설정
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s [CloudSched] %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    # ── 스케줄 등록 ──
    # schedule 라이브러리는 시스템 로컬 시간 기반
    # Render는 UTC → KST 오프셋(-9h) 적용 필요

    # KST를 UTC로 변환하는 헬퍼
    def kst_to_utc(kst_time_str: str) -> str:
        """'15:10' (KST) → '06:10' (UTC) 변환"""
        h, m = map(int, kst_time_str.split(':'))
        utc_h = (h - 9) % 24
        return f"{utc_h:02d}:{m:02d}"

    # Render에서는 UTC, 로컬에서는 KST
    is_render = bool(os.getenv('RENDER'))

    def sched_time(kst_time: str) -> str:
        if is_render:
            return kst_to_utc(kst_time)
        return kst_time

    weekdays = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday']

    for day in weekdays:
        # 04:00 KST — US Market 전체 갱신
        getattr(sched.every(), day).at(sched_time('04:00')).do(
            _safe_run, _run_us_update, 'US Market Update'
        )
        # 15:10 KST — KR 종가베팅 V2
        getattr(sched.every(), day).at(sched_time('15:10')).do(
            _safe_run, _run_round1, 'KR Round 1 (종가베팅)'
        )
        # 16:00 KST — KR 수급/VCP/리포트
        getattr(sched.every(), day).at(sched_time('16:00')).do(
            _safe_run, _run_round2, 'KR Round 2 (수급/VCP)'
        )

    # 07:00 KST — 전체 올 업데이트 (매일, 주말 포함)
    sched.every().day.at(sched_time('07:00')).do(
        _safe_run, _run_all_update, 'ALL DATA UPDATE (07:00)'
    )

    # Crypto — 매 4시간 (24/7)
    crypto_times = ['00:00', '04:00', '08:00', '12:00', '16:00', '20:00']
    for ct in crypto_times:
        sched.every().day.at(sched_time(ct)).do(
            _safe_run, _run_crypto_pipeline, 'Crypto Pipeline'
        )

    # System Diagnostics — 30분마다 (24/7)
    sched.every(30).minutes.do(
        _safe_run, _run_diagnostics_check, 'System Diagnostics'
    )

    logger.info("📅 클라우드 스케줄 등록 완료:")
    logger.info(f"   환경: {'Render (UTC)' if is_render else 'Local (KST)'}")
    logger.info(f"   🌐 매일 07:00 KST → 전체 올 업데이트 (US+KR+Crypto)")
    logger.info(f"   🇺🇸 평일 04:00 KST → US Market")
    logger.info(f"   🇰🇷 평일 15:10 KST → 종가베팅 V2")
    logger.info(f"   🇰🇷 평일 16:00 KST → 수급/VCP")
    logger.info(f"   🪙 매일 4시간마다 → Crypto")
    logger.info(f"   🔍 30분마다 → 시스템 자가진단")

    # 시작 알림
    _send_telegram(
        "<b>⏰ CloudScheduler 시작</b>\n\n"
        f"🌐 매일 07:00 KST → 전체 올 업데이트\n"
        f"🇺🇸 US: 04:00 KST (평일)\n"
        f"🇰🇷 KR: 15:10, 16:00 KST (평일)\n"
        f"🪙 Crypto: 4시간마다 (24/7)\n"
        f"🔍 자가진단: 30분마다\n"
        f"📍 {'Render' if is_render else 'Local'}"
    )

    # ── 시작 시 catch-up: stale 데이터 감지 → 즉시 실행 ──
    try:
        _check_and_catchup()
    except Exception as e:
        logger.error(f"Catch-up 실패: {e}")
        traceback.print_exc()

    # ── 메인 루프 ──
    while True:
        try:
            sched.run_pending()
        except Exception as e:
            logger.error(f"스케줄 실행 에러: {e}")
            traceback.print_exc()
        time.sleep(30)


def _check_and_catchup():
    """서버 시작 시 stale 데이터 감지 → 놓친 작업 즉시 실행

    Render free tier는 15분 비활성 시 서버를 sleep시킴.
    깨어났을 때 놓친 스케줄을 catch-up하여 데이터 갱신.
    """
    now = _get_kst_now()
    today = now.date()
    is_weekday = now.weekday() < 5

    logger.info(f"🔍 Catch-up 확인 중... KST: {now.strftime('%Y-%m-%d %H:%M')} ({'평일' if is_weekday else '주말'})")

    # 1. 종가베팅 V2 — 가장 최근 영업일의 데이터가 있는지 확인
    latest_path = os.path.join(DATA_DIR, 'jongga_v2_latest.json')
    jongga_stale = False

    # 마지막 영업일 계산
    last_biz_day = today
    if last_biz_day.weekday() == 6:  # 일요일
        last_biz_day -= timedelta(days=2)
    elif last_biz_day.weekday() == 5:  # 토요일
        last_biz_day -= timedelta(days=1)
    # 오전 9시 이전이면 전일 기준
    if is_weekday and now.hour < 15:
        # 15시(종가베팅 시간) 이전이면 전 영업일 확인
        check_date = last_biz_day - timedelta(days=1)
        if check_date.weekday() >= 5:
            check_date -= timedelta(days=(check_date.weekday() - 4))
    else:
        check_date = last_biz_day

    if os.path.exists(latest_path):
        try:
            with open(latest_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            data_date = data.get('date', '')
            if data_date:
                from datetime import date as date_cls
                parts = data_date.split('-')
                file_date = date_cls(int(parts[0]), int(parts[1]), int(parts[2]))
                if file_date < check_date:
                    jongga_stale = True
                    logger.info(f"   📊 종가베팅 데이터 stale: 파일={data_date}, 기대={check_date}")
            else:
                jongga_stale = True
        except Exception as e:
            logger.warning(f"   종가베팅 파일 읽기 실패: {e}")
            jongga_stale = True
    else:
        jongga_stale = True
        logger.info("   📊 종가베팅 데이터 파일 없음")

    # 2. 평일 + 15시 이후 + 데이터 stale → 종가베팅 즉시 실행
    if is_weekday and now.hour >= 15 and jongga_stale:
        logger.info("🚀 [Catch-up] 종가베팅 V2 즉시 실행!")
        _send_telegram("🔄 <b>Catch-up 실행</b>\n서버 재시작 후 종가베팅 데이터 갱신 시작")
        threading.Thread(
            target=_safe_run, args=(_run_jongga_v2, 'Catch-up: 종가베팅 V2'),
            daemon=True
        ).start()
    elif jongga_stale:
        # 평일 오전이거나 주말 → 전체 올 업데이트
        logger.info("🚀 [Catch-up] 전체 올 업데이트 즉시 실행!")
        _send_telegram("🔄 <b>Catch-up 실행</b>\n서버 재시작 후 전체 데이터 갱신 시작")
        threading.Thread(
            target=_safe_run, args=(_run_all_update, 'Catch-up: ALL UPDATE'),
            daemon=True
        ).start()
    else:
        logger.info("✅ 데이터 최신 상태 — catch-up 불필요")


def _keep_alive_loop():
    """Render free tier sleep 방지 — 12분마다 self-ping

    Render는 15분 비활성 시 서버를 sleep시킴.
    /api/health 엔드포인트를 주기적으로 호출하여 서버를 깨어있게 함.
    """
    import requests

    # 서버 완전 시작 대기
    time.sleep(30)

    # Render 배포 URL 자동 감지
    render_url = os.getenv('RENDER_EXTERNAL_URL', '')
    if not render_url:
        # Render가 자동 설정하는 서비스 URL 시도
        service_name = os.getenv('RENDER_SERVICE_NAME', '')
        if service_name:
            render_url = f"https://{service_name}.onrender.com"

    if not render_url:
        logger.info("[KeepAlive] RENDER_EXTERNAL_URL 미설정 — self-ping 비활성")
        return

    health_url = f"{render_url}/api/health"
    logger.info(f"[KeepAlive] 시작: {health_url} (12분 간격)")

    while True:
        try:
            resp = requests.get(health_url, timeout=10)
            logger.debug(f"[KeepAlive] ping OK: {resp.status_code}")
        except Exception as e:
            logger.warning(f"[KeepAlive] ping 실패: {e}")
        time.sleep(720)  # 12분


def _safe_run(func, name: str):
    """작업을 안전하게 실행 (예외 캐치 + 로깅)"""
    try:
        logger.info(f"🚀 시작: {name}")
        start = time.time()
        result = func()
        elapsed = time.time() - start
        status = "✅" if result else "⚠️"
        logger.info(f"{status} 완료: {name} ({elapsed:.1f}초)")
    except Exception as e:
        logger.error(f"❌ 실패: {name} — {e}")
        traceback.print_exc()
        try:
            _send_telegram(f"❌ 스케줄 작업 실패: {name}\n{str(e)[:300]}")
        except Exception:
            pass


# ============================================================
# API 엔드포인트용: 스케줄러 상태 & 수동 트리거
# ============================================================

def get_scheduler_status() -> dict:
    """스케줄러 상태 반환"""
    try:
        import schedule as sched
        jobs = []
        for job in sched.get_jobs():
            jobs.append({
                'next_run': str(job.next_run) if job.next_run else None,
                'interval': str(job.interval),
                'unit': str(job.unit),
            })
        return {
            'running': _scheduler_started,
            'environment': 'render' if os.getenv('RENDER') else 'local',
            'jobs_count': len(jobs),
            'jobs': jobs[:20],
            'kst_now': _get_kst_now().strftime('%Y-%m-%d %H:%M:%S KST'),
        }
    except Exception as e:
        return {'running': _scheduler_started, 'error': str(e)}


# ============================================================
# KR 가격 실시간 업데이터 (기존 기능 유지)
# ============================================================

def start_kr_price_scheduler():
    """KR 종가베팅 V2 가격 업데이트 스케줄러 (5분 간격)

    - data/jongga_v2_latest.json 기반
    - pykrx로 현재가 갱신
    - 시그널별 수익률 재계산
    """
    def _run_scheduler():
        print(f"[Scheduler] KR Price Updater started (base={BASE_DIR})", flush=True)

        while True:
            try:
                latest_path = os.path.join(DATA_DIR, 'jongga_v2_latest.json')
                if not os.path.exists(latest_path):
                    time.sleep(60)
                    continue

                with open(latest_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                signals = data.get('signals', [])
                if not signals:
                    time.sleep(300)
                    continue

                # pykrx로 현재가 업데이트
                updated = 0
                for sig in signals:
                    code = sig.get('stock_code', '')
                    entry = sig.get('entry_price', 0)
                    if not code or entry <= 0:
                        continue

                    try:
                        from pykrx import stock as pykrx_stock
                        today = date.today().strftime("%Y%m%d")
                        df = pykrx_stock.get_market_ohlcv(today, today, code)
                        if not df.empty:
                            cur = int(df.iloc[-1]['종가'])
                            if cur > 0:
                                sig['current_price'] = cur
                                sig['return_pct'] = round(((cur - entry) / entry) * 100, 2)
                                updated += 1
                    except Exception:
                        pass

                    time.sleep(2)  # Rate limit

                if updated > 0:
                    with open(latest_path, 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    print(f"[Scheduler] {updated}/{len(signals)} prices updated", flush=True)

                time.sleep(300)  # 5분 대기

            except Exception as e:
                print(f"[Scheduler] Error: {e}", flush=True)
                time.sleep(60)

    thread = threading.Thread(target=_run_scheduler, daemon=True)
    thread.start()

# app/utils/diagnostics.py
"""MarketFlow Self-Diagnostic System

30분마다 자동 실행 → CRITICAL 발견 시 텔레그램 알림
GET /api/system/diagnostics 로 수동 조회 가능

Checks: endpoints, data freshness, scheduler, memory, telegram
Severity: OK, WARNING, CRITICAL
"""

import os
import json
import time
import logging
import traceback
from datetime import datetime, timezone, timedelta

# ── 고정 경로 ──
_UTILS_DIR = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = os.path.dirname(_UTILS_DIR)
_BASE_DIR = os.path.dirname(_APP_DIR)
_DATA_DIR = os.path.join(_BASE_DIR, 'data')
_US_OUTPUT = os.path.join(_BASE_DIR, 'us_market_preview', 'output')  # 서비스 실행경로와 동일
_CRYPTO_OUTPUT = os.path.join(_BASE_DIR, 'crypto-analytics', 'crypto_market', 'output')

logger = logging.getLogger('diagnostics')

# ── 캐시 ──
_last_result = None
_last_run_time = 0


def get_cached_or_run(max_age=120):
    """캐시된 결과 반환 (max_age초 이내), 없으면 새로 실행"""
    global _last_result, _last_run_time
    if _last_result and (time.time() - _last_run_time) < max_age:
        return _last_result
    _last_result = run_diagnostics()
    _last_run_time = time.time()
    return _last_result


def run_diagnostics(flask_port=None):
    """전체 진단 실행 → 결과 dict 반환"""
    if flask_port is None:
        flask_port = int(os.environ.get('PORT', os.environ.get('FLASK_PORT', 5001)))
    try:
        from app.utils.scheduler import _get_kst_now
        now_kst = _get_kst_now().strftime('%Y-%m-%d %H:%M:%S KST')
    except Exception:
        now_kst = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    checks = {}

    # 1. Endpoints
    checks['endpoints'] = _check_endpoints(flask_port)

    # 2. Data freshness
    checks['data_freshness'] = _check_data_freshness()

    # 3. Scheduler
    checks['scheduler'] = _check_scheduler()

    # 4. Memory
    checks['memory'] = _check_memory()

    # 5. Telegram
    checks['telegram'] = _check_telegram()

    # Overall status
    statuses = [c['status'] for c in checks.values()]
    if 'CRITICAL' in statuses:
        overall = 'CRITICAL'
    elif 'WARNING' in statuses:
        overall = 'WARNING'
    else:
        overall = 'OK'

    return {
        'timestamp': now_kst,
        'overall_status': overall,
        'checks': checks,
        'critical_count': sum(1 for s in statuses if s == 'CRITICAL'),
        'warning_count': sum(1 for s in statuses if s == 'WARNING'),
    }


def run_diagnostics_and_alert():
    """진단 실행 + CRITICAL 시 텔레그램 알림"""
    result = run_diagnostics()

    global _last_result, _last_run_time
    _last_result = result
    _last_run_time = time.time()

    if result['critical_count'] > 0 or result['warning_count'] > 0:
        _send_alert(result)

    return result


# ============================================================
# 개별 진단 함수
# ============================================================

def _check_endpoints(port=5001):
    """핵심 API 엔드포인트 셀프 테스트"""
    import requests

    endpoints = [
        '/api/health',
        '/api/us/market-briefing',
        '/api/kr/market-gate',
        '/api/crypto/dominance',
        '/api/kr/jongga-v2/latest',
    ]

    details = []
    worst = 'OK'

    for ep in endpoints:
        try:
            r = requests.get(f'http://localhost:{port}{ep}', timeout=5)
            if r.status_code == 200:
                # 데이터가 실제로 있는지 확인
                data = r.json()
                has_data = bool(data) and not (isinstance(data, dict) and data.get('error'))
                status = 'OK' if has_data else 'WARNING'
            else:
                status = 'CRITICAL'
        except Exception as e:
            status = 'CRITICAL'
            r = None

        details.append({
            'endpoint': ep,
            'status': status,
            'http_code': r.status_code if r else 0,
            'response_ms': int(r.elapsed.total_seconds() * 1000) if r else -1,
        })

        if status == 'CRITICAL':
            worst = 'CRITICAL'
        elif status == 'WARNING' and worst != 'CRITICAL':
            worst = 'WARNING'

    return {'status': worst, 'details': details}


def _check_data_freshness():
    """데이터 파일 신선도 확인"""
    try:
        from app.utils.scheduler import _get_kst_now, _is_weekday_kst
        is_weekday = _is_weekday_kst()
    except Exception:
        is_weekday = datetime.now().weekday() < 5

    # 파일별 임계값 (시간 단위)
    # us_market/output/ = 실제 업데이트 출력 경로 (update_all.py)
    _us_out = os.path.join(_BASE_DIR, 'us_market', 'output')
    files_config = [
        ('kr_jongga', os.path.join(_DATA_DIR, 'jongga_v2_latest.json'), 24 if is_weekday else 72),
        ('us_market_briefing', os.path.join(_us_out, 'market_briefing.json'), 24 if is_weekday else 72),
        ('us_sector_heatmap', os.path.join(_us_out, 'sector_heatmap.json'), 24 if is_weekday else 72),
        ('us_earnings', os.path.join(_us_out, 'earnings_impact.json'), 24 if is_weekday else 72),
        ('crypto_overview', os.path.join(_CRYPTO_OUTPUT, 'overview_snapshot.json'), 5),
    ]

    details = []
    worst = 'OK'

    is_render = bool(os.getenv('RENDER'))

    for name, path, threshold_hours in files_config:
        if not os.path.exists(path):
            # Render에서는 데이터 파일이 없을 수 있음 (스케줄러가 생성 전)
            status = 'WARNING' if is_render else 'CRITICAL'
            age_hours = -1
        else:
            mtime = os.path.getmtime(path)
            age_hours = round((time.time() - mtime) / 3600, 1)
            if age_hours > threshold_hours * 2:
                status = 'CRITICAL'
            elif age_hours > threshold_hours:
                status = 'WARNING'
            else:
                status = 'OK'

        details.append({
            'name': name,
            'path': os.path.basename(path),
            'status': status,
            'age_hours': age_hours,
            'threshold_hours': threshold_hours,
        })

        if status == 'CRITICAL':
            worst = 'CRITICAL'
        elif status == 'WARNING' and worst != 'CRITICAL':
            worst = 'WARNING'

    return {'status': worst, 'details': details}


def _check_scheduler():
    """스케줄러 실행 상태 확인"""
    try:
        from app.utils.scheduler import get_scheduler_status
        info = get_scheduler_status()
        running = info.get('running', False)
        jobs = info.get('jobs_count', 0)

        if not running:
            status = 'CRITICAL'
        elif jobs == 0:
            status = 'WARNING'
        else:
            status = 'OK'

        return {
            'status': status,
            'details': {
                'running': running,
                'jobs_count': jobs,
                'environment': info.get('environment', 'unknown'),
            }
        }
    except Exception as e:
        return {'status': 'WARNING', 'details': {'error': str(e)}}


def _check_memory():
    """프로세스 메모리 사용량 확인"""
    try:
        import psutil
        proc = psutil.Process(os.getpid())
        rss_mb = proc.memory_info().rss / (1024 * 1024)
    except ImportError:
        try:
            import subprocess
            pid = os.getpid()
            result = subprocess.run(
                ['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV', '/NH'],
                capture_output=True, text=True, timeout=5
            )
            # Parse: "python.exe","1234","Console","1","50,000 K"
            parts = result.stdout.strip().split(',')
            if len(parts) >= 5:
                mem_str = parts[-1].strip().strip('"').replace(',', '').replace(' K', '')
                rss_mb = int(mem_str) / 1024
            else:
                rss_mb = -1
        except Exception:
            rss_mb = -1

    if rss_mb < 0:
        return {'status': 'OK', 'details': {'rss_mb': 'unknown'}}

    rss_mb = round(rss_mb, 1)
    if rss_mb > 2000:
        status = 'CRITICAL'
    elif rss_mb > 1000:
        status = 'WARNING'
    else:
        status = 'OK'

    return {'status': status, 'details': {'rss_mb': rss_mb}}


def _check_telegram():
    """텔레그램 봇 연결 확인"""
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')

    if not token or not chat_id:
        return {'status': 'WARNING', 'details': {'error': 'TELEGRAM_BOT_TOKEN or CHAT_ID not set'}}

    try:
        import requests
        r = requests.get(f'https://api.telegram.org/bot{token}/getMe', timeout=5)
        if r.status_code == 200 and r.json().get('ok'):
            bot_name = r.json().get('result', {}).get('username', '?')
            return {'status': 'OK', 'details': {'bot': bot_name, 'chat_id_set': True}}
        else:
            return {'status': 'WARNING', 'details': {'error': f'getMe returned {r.status_code}'}}
    except Exception as e:
        return {'status': 'WARNING', 'details': {'error': str(e)}}


# ============================================================
# 텔레그램 알림
# ============================================================

def _send_alert(result):
    """진단 결과 텔레그램 알림 — 정상/오류 분리 포맷"""
    try:
        from app.utils.scheduler import _send_telegram
    except ImportError:
        logger.error("Cannot import _send_telegram")
        return

    # 한글 이름 + 조치 가이드 매핑
    _LABELS = {
        'endpoints': 'API 서버',
        'data_freshness': '데이터 갱신',
        'scheduler': '스케줄러',
        'memory': '메모리',
        'telegram': '텔레그램 봇',
    }
    _ACTIONS = {
        'endpoints': '→ Flask 서버 재시작 필요',
        'data_freshness': '→ 스케줄러 실행 또는 수동 업데이트 필요',
        'scheduler': '→ scheduler.py --daemon 재시작 필요',
        'memory': '→ 서버 재시작으로 메모리 확보 필요',
        'telegram': '→ .env TELEGRAM_BOT_TOKEN 확인 필요',
    }

    ok_items = []
    error_items = []

    for check_name, check_data in result['checks'].items():
        label = _LABELS.get(check_name, check_name)
        status = check_data['status']

        if status == 'OK':
            ok_items.append(label)
        else:
            # 오류 상세 정보 추출
            detail_text = ''
            details = check_data.get('details', {})
            if isinstance(details, list):
                problems = [d for d in details if d.get('status') in ('CRITICAL', 'WARNING')]
                parts = []
                for d in problems:
                    name = d.get('endpoint') or d.get('name', '?')
                    if 'age_hours' in d and d['age_hours'] > 0:
                        parts.append(f"{name} ({d['age_hours']}시간 경과)")
                    elif 'http_code' in d:
                        parts.append(f"{name} (HTTP {d['http_code']})")
                    else:
                        parts.append(name)
                if parts:
                    detail_text = ', '.join(parts)
            elif isinstance(details, dict):
                if 'error' in details:
                    detail_text = details['error']
                elif 'rss_mb' in details:
                    detail_text = f"{details['rss_mb']}MB 사용중"
                elif 'running' in details and not details['running']:
                    detail_text = '실행 안됨'

            icon = '🔴' if status == 'CRITICAL' else '🟡'
            action = _ACTIONS.get(check_name, '')
            line = f"{icon} {label}"
            if detail_text:
                line += f": {detail_text}"
            error_items.append(line)
            if action:
                error_items.append(f"   {action}")

    # 메시지 조립
    overall = result['overall_status']
    if overall == 'CRITICAL':
        header = '🚨 시스템 점검 — 조치 필요'
    elif overall == 'WARNING':
        header = '⚠️ 시스템 점검 — 주의'
    else:
        header = '✅ 시스템 점검 — 정상'

    lines = [f"<b>{header}</b>"]
    lines.append('')

    # 오류 섹션 (먼저 표시)
    if error_items:
        lines.append('<b>❌ 오류</b>')
        for item in error_items:
            lines.append(item)
        lines.append('')

    # 정상 섹션
    if ok_items:
        lines.append(f"✅ 정상: {', '.join(ok_items)}")

    lines.append(f"\n⏰ {result['timestamp']}")

    _send_telegram('\n'.join(lines))
    logger.info(f"[Diagnostics] Alert sent: {overall} "
                f"(C:{result['critical_count']}, W:{result['warning_count']})")

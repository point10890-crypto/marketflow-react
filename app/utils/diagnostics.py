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
from app.utils.paths import BASE_DIR, DATA_DIR, US_OUTPUT_DIR, CRYPTO_OUTPUT_DIR

# ── 경로 별칭 (기존 참조 호환) ──
_BASE_DIR = BASE_DIR
_DATA_DIR = DATA_DIR
_US_OUTPUT = US_OUTPUT_DIR
_CRYPTO_OUTPUT = CRYPTO_OUTPUT_DIR

logger = logging.getLogger('diagnostics')

# ── 캐시 ──
_last_result = None
_last_run_time = 0
_diag_running = False


def get_cached_or_run(max_age=120):
    """캐시된 결과 반환 (max_age초 이내), 없으면 새로 실행"""
    global _last_result, _last_run_time, _diag_running
    if _last_result and (time.time() - _last_run_time) < max_age:
        return _last_result
    # 동시 요청 방어 — 이미 진단 중이면 캐시 반환
    if _diag_running:
        return _last_result or {}
    _diag_running = True
    try:
        _last_result = run_diagnostics()
        _last_run_time = time.time()
        return _last_result
    finally:
        _diag_running = False


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

def _check_endpoints(port=None):
    """핵심 API 엔드포인트 셀프 테스트"""
    import requests

    if port is None:
        port = int(os.environ.get('PORT', os.environ.get('FLASK_PORT', 5001)))

    endpoints = [
        {'path': '/api/health', 'protected': False},
        {'path': '/api/us/market-briefing', 'protected': True},
        {'path': '/api/kr/market-gate', 'protected': True},
        {'path': '/api/crypto/dominance', 'protected': True},
        {'path': '/api/kr/jongga-v2/latest', 'protected': True},
    ]

    details = []
    worst = 'OK'

    for item in endpoints:
        ep = item['path']
        protected = bool(item.get('protected'))
        note = None
        try:
            r = requests.get(f'http://localhost:{port}{ep}', timeout=5)
            if r.status_code == 200:
                # 데이터가 실제로 있는지 확인
                data = r.json()
                has_data = bool(data) and not (isinstance(data, dict) and data.get('error'))
                status = 'OK' if has_data else 'WARNING'
            elif protected and r.status_code in (401, 403):
                # Pro/API auth gate is alive. Data freshness is checked by
                # _check_data_freshness; endpoint liveness should not mark a
                # healthy protected route as down just because diagnostics has
                # no subscriber token.
                status = 'OK'
                note = 'protected_endpoint_auth_gate'
            else:
                status = 'CRITICAL'
        except Exception as e:
            status = 'CRITICAL'
            r = None
            note = f'{type(e).__name__}: {e}'

        details.append({
            'endpoint': ep,
            'status': status,
            'http_code': r.status_code if r is not None else 0,
            'response_ms': int(r.elapsed.total_seconds() * 1000) if r is not None else -1,
            'protected': protected,
            **({'note': note} if note else {}),
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
        {'name': 'kr_jongga', 'path': os.path.join(_DATA_DIR, 'jongga_v2_latest.json'), 'threshold_hours': 24 if is_weekday else 72},
        {'name': 'us_market_briefing', 'path': os.path.join(_us_out, 'market_briefing.json'), 'threshold_hours': 24 if is_weekday else 72},
        {'name': 'us_sector_heatmap', 'path': os.path.join(_us_out, 'sector_heatmap.json'), 'threshold_hours': 24 if is_weekday else 72},
        {'name': 'us_earnings', 'path': os.path.join(_us_out, 'earnings_impact.json'), 'threshold_hours': 24 if is_weekday else 72},
        {
            'name': 'crypto_overview',
            'path': os.path.join(_CRYPTO_OUTPUT, 'overview_snapshot.json'),
            'threshold_hours': 5,
            'max_status': 'WARNING',
            'note': 'live_endpoint_refreshes_on_demand',
        },
        {'name': 'crypto_market_gate', 'path': os.path.join(_CRYPTO_OUTPUT, 'market_gate.json'), 'threshold_hours': 5},
        {'name': 'crypto_briefing', 'path': os.path.join(_CRYPTO_OUTPUT, 'crypto_briefing.json'), 'threshold_hours': 5},
        {'name': 'crypto_prediction', 'path': os.path.join(_CRYPTO_OUTPUT, 'btc_prediction.json'), 'threshold_hours': 5},
        {'name': 'crypto_risk', 'path': os.path.join(_CRYPTO_OUTPUT, 'crypto_risk.json'), 'threshold_hours': 5},
    ]

    details = []
    worst = 'OK'

    is_render = bool(os.getenv('RENDER'))

    for item in files_config:
        name = item['name']
        path = item['path']
        threshold_hours = item['threshold_hours']
        note = item.get('note')
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

        if status == 'CRITICAL' and item.get('max_status') == 'WARNING':
            status = 'WARNING'
            note = note or 'critical_downgraded_by_policy'

        detail = {
            'name': name,
            'path': os.path.basename(path),
            'status': status,
            'age_hours': age_hours,
            'threshold_hours': threshold_hours,
        }
        if note:
            detail['note'] = note
        details.append(detail)

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
        external = _check_external_scheduler_daemon()
        running = bool(info.get('running', False)) or external['healthy']
        jobs = int(info.get('jobs_count') or 0)

        if not running:
            status = 'CRITICAL'
        elif external['healthy'] and external.get('duplicate_processes', 0):
            status = 'WARNING'
        elif jobs == 0:
            status = 'OK' if external['healthy'] else 'WARNING'
        else:
            status = 'OK'

        return {
            'status': status,
            'details': {
                'running': running,
                'jobs_count': jobs,
                'environment': info.get('environment', 'unknown'),
                'mode': (
                    'cloud_scheduler' if info.get('running', False)
                    else ('external_daemon' if external['healthy'] else 'not_running')
                ),
                'internal_running': bool(info.get('running', False)),
                'external': external,
            }
        }
    except Exception as e:
        return {'status': 'WARNING', 'details': {'error': str(e)}}


def _check_external_scheduler_daemon(max_heartbeat_age_seconds=180):
    heartbeat_path = os.path.join(_DATA_DIR, 'scheduler_heartbeat.json')
    pid_path = os.path.join(_BASE_DIR, 'logs', 'scheduler.pid')
    heartbeat = _load_scheduler_heartbeat(heartbeat_path)
    pid_file_pid = _read_int_file(pid_path)
    heartbeat_pid = heartbeat.get('pid')
    heartbeat_age = heartbeat.get('age_seconds')
    heartbeat_fresh = heartbeat_age is not None and heartbeat_age <= max_heartbeat_age_seconds
    heartbeat_pid_alive = _is_pid_alive(heartbeat_pid)
    pid_file_alive = _is_pid_alive(pid_file_pid)
    processes = _scheduler_daemon_processes()
    process_count = len(processes)
    pid_consistent = (
        heartbeat_pid is None or pid_file_pid is None or int(heartbeat_pid) == int(pid_file_pid)
    )
    healthy = bool(heartbeat_fresh and (heartbeat_pid_alive or pid_file_alive or process_count > 0))

    return {
        'healthy': healthy,
        'heartbeat_path': os.path.basename(heartbeat_path),
        'heartbeat_age_seconds': heartbeat_age,
        'heartbeat_pid': heartbeat_pid,
        'heartbeat_pid_alive': heartbeat_pid_alive,
        'pid_file_path': os.path.basename(pid_path),
        'pid_file_pid': pid_file_pid,
        'pid_file_alive': pid_file_alive,
        'pid_consistent': pid_consistent,
        'process_count': process_count,
        'duplicate_processes': max(0, process_count - 1),
        'process_pids': processes[:10],
    }


def _load_scheduler_heartbeat(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        ts = data.get('ts')
        age_seconds = None
        if ts:
            parsed = datetime.fromisoformat(str(ts).replace('Z', '+00:00')).replace(tzinfo=None)
            age_seconds = round((datetime.now() - parsed).total_seconds(), 1)
        return {
            'pid': _coerce_int(data.get('pid')),
            'ts': ts,
            'age_seconds': age_seconds,
        }
    except Exception as e:
        return {'error': str(e)}


def _read_int_file(path):
    try:
        if not os.path.exists(path):
            return None
        with open(path, 'r', encoding='utf-8') as f:
            return _coerce_int(f.read().strip())
    except Exception:
        return None


def _coerce_int(value):
    try:
        if value in (None, ''):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_pid_alive(pid):
    pid = _coerce_int(pid)
    if not pid or pid <= 0:
        return False
    try:
        import psutil
        return psutil.pid_exists(pid) and psutil.Process(pid).is_running()
    except Exception:
        if os.name == 'nt':
            try:
                import subprocess
                result = subprocess.run(
                    ['tasklist', '/FI', f'PID eq {pid}', '/NH', '/FO', 'CSV'],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                return str(pid) in result.stdout
            except Exception:
                return False
        return os.path.exists(f'/proc/{pid}')


def _scheduler_daemon_processes():
    try:
        import psutil
    except Exception:
        return []

    matches = {}
    for proc in psutil.process_iter(['pid', 'cmdline']):
        try:
            cmdline = proc.info.get('cmdline') or []
            cmd = ' '.join(str(part) for part in cmdline)
            normalized = cmd.replace('\\', '/').lower()
            if 'scheduler.py' in normalized and '--daemon' in normalized:
                pid = int(proc.info['pid'])
                try:
                    parent_pid = int(proc.ppid())
                except Exception:
                    parent_pid = None
                matches[pid] = parent_pid
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, KeyError, TypeError):
            continue
    if not matches:
        return []
    return sorted(pid for pid, parent_pid in matches.items() if parent_pid not in matches)


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
            if os.name == 'nt':
                result = subprocess.run(
                    ['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV', '/NH'],
                    capture_output=True, text=True, timeout=5
                )
                parts = result.stdout.strip().split(',')
                if len(parts) >= 5:
                    mem_str = parts[-1].strip().strip('"').replace(',', '').replace(' K', '')
                    rss_mb = int(mem_str) / 1024
                else:
                    rss_mb = -1
            else:
                # Linux/macOS: /proc/<pid>/status 또는 ps
                try:
                    with open(f'/proc/{pid}/status', 'r') as f:
                        for line in f:
                            if line.startswith('VmRSS:'):
                                rss_mb = int(line.split()[1]) / 1024
                                break
                        else:
                            rss_mb = -1
                except FileNotFoundError:
                    result = subprocess.run(
                        ['ps', '-o', 'rss=', '-p', str(pid)],
                        capture_output=True, text=True, timeout=5
                    )
                    rss_kb = result.stdout.strip()
                    rss_mb = int(rss_kb) / 1024 if rss_kb.isdigit() else -1
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

    # 시스템 자가진단 알림 — 개인 봇만 (채널 오염 방지)
    _send_telegram('\n'.join(lines), channel=False)
    logger.info(f"[Diagnostics] Alert sent: {overall} "
                f"(C:{result['critical_count']}, W:{result['warning_count']})")

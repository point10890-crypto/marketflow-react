"""명시적으로 검토한 경로의 상태를 읽는 HTTP 감시."""
from __future__ import annotations

import hashlib
import http.client
import math
import hmac
import json
import os
import socket
import threading
import time
from datetime import datetime
from typing import Any

from urllib.parse import urlsplit

from app.services.control_center.contracts import allowed_http_url, safe_path, validate_api_base

from app.services.control_center.local_checks import _age_text, _parse_ts
from app.services.control_center.model import CheckResult, now_kst

DEFAULT_TIMEOUT = 10.0
MAX_BODY = 4_000_000
USER_AGENT = 'MarketFlow-ControlCenter/1.0'


def api_base(contracts: dict[str, Any]) -> str:
    return validate_api_base(
        os.environ.get('CONTROL_CENTER_API_BASE') or contracts.get('api_base') or 'http://127.0.0.1:5003'
    )


# app.auth.decorators.TOKEN_EXPIRY 와 같아야 한다 (서버는 '만료 − TOKEN_EXPIRY' 를 발급 시각으로 보고
# 비밀번호 변경 이전 발급 토큰을 거절한다). tests/test_control_center.py 가 두 값을 대조한다.
APP_TOKEN_EXPIRY = 86400 * 30


def mint_service_token() -> str | None:
    """관리자 서비스 계정 토큰 — 실행 때마다 새로 만들고 메모리에만 둔다(파일·로그·응답에 남기지 않음).
    설정이 없으면 None (deep 감시는 skipped)."""
    secret = (os.environ.get('SECRET_KEY') or '').strip()
    uid = (os.environ.get('CONTROL_CENTER_SERVICE_USER_ID') or '').strip()
    if not secret or not (uid.isascii() and uid.isdecimal() and len(uid) <= 10 and 0 < int(uid) <= 2**31 - 1):
        return None
    payload = f'{int(uid)}:{int(time.time()) + APP_TOKEN_EXPIRY}'
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return f'{payload}:{sig}'


def http_get(url: str, token: str | None = None, timeout: float = DEFAULT_TIMEOUT, *,
             read_body: bool = True, provider: bool = False) -> dict[str, Any]:
    # Direct connection: no proxy, netrc or redirect handling. Only JSON success
    # responses are read, with an identity encoding, byte cap and read deadline.
    t0 = time.monotonic()
    result = {'status': None, 'ms': 0, 'json': None, 'ctype': '', 'bytes': 0,
              'retry_after': None, 'error': None}
    if not allowed_http_url(url, authenticated=token is not None, provider=provider):
        result['error'] = 'UnsafeURL'
        return result
    parts = urlsplit(url)
    headers = {'User-Agent': USER_AGENT, 'Accept': 'application/json', 'Accept-Encoding': 'identity'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    timeout = float(timeout)
    timeout = min(12.0, timeout) if math.isfinite(timeout) and timeout > 0 else DEFAULT_TIMEOUT
    deadline = t0 + timeout
    conn_type = http.client.HTTPSConnection if parts.scheme == 'https' else http.client.HTTPConnection
    conn = conn_type(parts.hostname, parts.port, timeout=timeout)

    def set_remaining(sock) -> None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        sock.settimeout(remaining)

    abort = None
    try:
        conn.connect()
        sock = conn.sock
        set_remaining(sock)

        def abort_read() -> None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        # Socket timeouts alone permit a slow sender to keep a header read
        # open indefinitely by supplying bytes just before each timeout.
        abort = threading.Timer(max(0, deadline - time.monotonic()), abort_read)
        abort.daemon = True
        abort.start()
        target = parts.path or '/'
        if parts.query:
            target += '?' + parts.query
        conn.request('GET', target, headers=headers)
        set_remaining(sock)
        with conn.getresponse() as resp:
            result['status'] = resp.status
            ctype = (resp.getheader('Content-Type') or '').lower().split(';', 1)[0]
            if (read_body and 200 <= resp.status < 300 and
                    (ctype == 'application/json' or ctype.endswith('+json'))):
                result['ctype'] = 'application/json'
                encoding = resp.getheader('Content-Encoding') or 'identity'
                if encoding.lower() != 'identity' or (resp.length is not None and resp.length > MAX_BODY):
                    result['error'] = 'UnsupportedBody'
                    return result
                body = bytearray()
                while len(body) <= MAX_BODY:
                    set_remaining(sock)
                    chunk = resp.read1(min(65536, MAX_BODY + 1 - len(body)))
                    if not chunk:
                        break
                    body.extend(chunk)
                result['bytes'] = len(body)
                if time.monotonic() >= deadline or resp.length:
                    result['error'] = 'IncompleteBody'
                elif len(body) > MAX_BODY:
                    result['error'] = 'OversizeBody'
                elif body:
                    try:
                        result['json'] = json.loads(body)
                    except (ValueError, RecursionError):
                        result['error'] = 'InvalidJSON'
    except (OSError, http.client.HTTPException, ValueError, RecursionError) as exc:
        result['error'] = type(exc).__name__
    finally:
        if abort is not None:
            abort.cancel()
        conn.close()
        result['ms'] = int((time.monotonic() - t0) * 1000)
    return result


def _dig(data: Any, path: str, missing: Any = None) -> Any:
    cur = data
    for key in path.split('.'):
        if isinstance(cur, dict):
            cur = cur.get(key, missing)
        elif isinstance(cur, list) and key.isdigit() and int(key) < len(cur):
            cur = cur[int(key)]
        else:
            return missing
    return cur


# ─────────────────────────── auth gate sweep ───────────────────────────

def auth_gate_sweep(base: str, rows: list[dict[str, Any]], pause: float = 0.02) -> list[CheckResult]:
    out = []
    deadline = time.monotonic() + 20
    stopped = False
    for row in rows:
        target = row['rule']
        remaining = deadline - time.monotonic()
        if stopped or remaining <= 0 or not safe_path(row['probe_path']):
            out.append(CheckResult(f'gate:{target}', 'endpoint', target, 'unknown',
                                   '점검 중단 또는 점검 가능한 경로 없음', severity='info'))
            continue
        r = http_get(base + row['probe_path'], timeout=min(2, remaining), read_body=False)
        code = r['status']
        stopped = code is None or code in (429, 503) or (200 <= code < 300)
        if code in (401, 403):
            out.append(CheckResult(f'gate:{target}', 'endpoint', target, 'ok', f'미인증 요청 거절 ({code})', severity='info',
                                   latency_ms=r['ms']))
        elif code is not None and 200 <= code < 300:
            out.append(CheckResult(f'security:{target}', 'security', target, 'fail',
                                   f'토큰 없이 {code} 응답 — 인증 보호가 풀렸습니다 (기대 인증: {row["auth"]})',
                                   severity='critical', latency_ms=r['ms']))
            out.append(CheckResult(f'gate:{target}', 'endpoint', target, 'fail', '인증 회귀 (security 항목 참조)',
                                   severity='info', latency_ms=r['ms']))
        elif code == 404:
            out.append(CheckResult(f'gate:{target}', 'endpoint', target, 'warn',
                                   '실행 중인 서버에 이 경로가 없음 — 코드 갱신 뒤 재시작이 안 됐을 수 있음', severity='standard',
                                   latency_ms=r['ms']))
        elif code == 429 or code == 503:
            out.append(CheckResult(f'gate:{target}', 'endpoint', target, 'warn', f'{code} (과부하·제한)', latency_ms=r['ms']))
        elif code is None:
            out.append(CheckResult(f'gate:{target}', 'endpoint', target, 'fail', f'연결 실패 ({r["error"]})', latency_ms=r['ms']))
        else:
            out.append(CheckResult(f'gate:{target}', 'endpoint', target, 'fail' if code >= 500 else 'warn',
                                   f'예상 밖 응답 {code}', latency_ms=r['ms']))
        if pause and not stopped:
            time.sleep(min(pause, max(0, deadline - time.monotonic())))
    return out


# ─────────────────────────── 계약 기반 probe (public · deep) ───────────────────────────

def probe_contract(base: str, c: dict[str, Any], token: str | None, now: datetime | None = None) -> CheckResult:
    now = now or now_kst()
    path = c['path']
    sev = c.get('severity', 'standard')
    cid = f'endpoint:{path}'
    label = c.get('label') or path
    if not safe_path(path):
        return CheckResult(cid, 'endpoint', label, 'unknown', '안전하지 않은 점검 경로', severity=sev)
    needs_token = c.get('auth', 'admin') != 'public'
    if needs_token and not token:
        return CheckResult(cid, 'endpoint', label, 'skipped', '서비스 계정 미설정 (CONTROL_CENTER_SERVICE_USER_ID)', severity=sev,
                           data={'path': path, 'pages': c.get('pages', [])})
    r = http_get(base + path, token=token if needs_token else None, timeout=float(c.get('timeout', DEFAULT_TIMEOUT)))
    data = {'path': path, 'pages': c.get('pages', []), 'http': r['status'], 'bytes': r['bytes']}
    if r['status'] is None:
        return CheckResult(cid, 'endpoint', label, 'fail', f'연결 실패 ({r["error"]})', severity=sev, latency_ms=r['ms'], data=data)
    expect = set(c.get('expect_status', [200]))
    if r['status'] not in expect:
        st = 'warn' if r['status'] in (429, 503) and c.get('warn_on_busy', True) else 'fail'
        return CheckResult(cid, 'endpoint', label, st, f'HTTP {r["status"]}', severity=sev, latency_ms=r['ms'], data=data)
    if r['error']:
        return CheckResult(cid, 'endpoint', label, 'unknown', '응답 본문을 검증할 수 없음', severity=sev,
                           latency_ms=r['ms'], data=data)
    problems: list[str] = []
    st = 'ok'
    body = r['json']
    missing = object()
    for key in c.get('expect_keys', []):
        if not isinstance(body, dict) or _dig(body, key, missing) is missing:
            problems.append(f'필드 없음: {key}')
            st = 'fail'
    for key, expected in c.get('expect_values', {}).items():
        actual = _dig(body, key)
        if type(actual) is not type(expected) or actual != expected:
            problems.append(f'예상과 다른 필드: {key}')
            st = 'fail'
    min_items = c.get('min_items')
    if min_items and isinstance(min_items, dict):
        val = _dig(body, min_items['path'])
        if not isinstance(val, list) or len(val) < int(min_items.get('count', 1)):
            problems.append(f'{min_items["path"]} 항목 수 부족')
            st = 'warn' if st == 'ok' else st
    fresh = c.get('freshness')
    if fresh:
        ts = _parse_ts(_dig(body, fresh['field']))
        if ts is None or ts > now:
            problems.append(f'유효하지 않은 시각 필드: {fresh["field"]}')
            st = 'unknown' if st == 'ok' else st
        else:
            from app.services.control_center.local_checks import _calendar_allowance

            age_h = (now - ts).total_seconds() / 3600
            limit = float(fresh.get('max_age_hours', 26)) + _calendar_allowance(fresh.get('calendar', ''), now)
            data['age_hours'] = round(age_h, 2)
            if age_h > limit:
                problems.append(f'데이터 {_age_text(age_h * 3600)} 전 (허용 {limit:.0f}시간)')
                st = 'fail' if age_h > limit * 1.5 else ('warn' if st == 'ok' else st)
    budget = c.get('budget_ms')
    if budget and r['ms'] > budget:
        problems.append(f'응답 {r["ms"]}ms (목표 {budget}ms)')
        st = 'warn' if st == 'ok' else st
    detail = '정상' if not problems else ' · '.join(problems)
    return CheckResult(cid, 'endpoint', label, st, f'HTTP {r["status"]} {r["ms"]}ms · {detail}', severity=sev,
                       latency_ms=r['ms'], data=data)


def check_public_urls(items: list[dict[str, Any]]) -> list[CheckResult]:
    """외부에서 보이는 주소 — 터널(API)과 Cloudflare Pages(화면)."""
    out = []
    for it in items:
        url = os.environ.get(it.get('env', ''), '') or it['url']
        if not url.startswith('https://') or not allowed_http_url(url):
            out.append(CheckResult(f"public:{it['id']}", 'process', it.get('label', it['id']),
                                   'unknown', '허용되지 않은 공개 점검 URL',
                                   severity=it.get('severity', 'critical')))
            continue
        r = http_get(url, timeout=float(it.get('timeout', 12)), read_body=bool(it.get('expect_key')))
        ok = r['status'] in set(it.get('expect_status', [200]))
        if ok and it.get('expect_key'):
            ok = _dig(r['json'], it['expect_key']) is True
        st = 'ok' if ok else 'fail'
        msg = f'HTTP {r["status"]} {r["ms"]}ms' if r['status'] else f'연결 실패 ({r["error"]})'
        out.append(CheckResult(f"public:{it['id']}", 'process', it.get('label', it['id']), st, msg,
                               severity=it.get('severity', 'critical'), latency_ms=r['ms']))
    return out

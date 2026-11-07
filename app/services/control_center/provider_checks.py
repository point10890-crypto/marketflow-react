"""외부 API 의존성 — 비용·호출 한도를 아끼며 확인한다.

- 실호출은 무료·가벼운 엔드포인트 하나만, 공급자마다 최소 간격(interval_min)을 지킨다.
- LLM 은 직접 부르지 않는다: 기존 `scripts/llm_routing_health.py` 가 남긴 health.json 을 읽는다.
- KIS 는 토큰을 새로 받지 않는다(발급 횟수 제한): 토큰 캐시의 만료 시각만 본다.
- 키 값은 어디에도 남기지 않는다. 결과에는 '설정됨/없음' 만.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any

from urllib.parse import urlencode

from app.services.control_center.http_checks import http_get

from app.services.control_center.local_checks import _age_text, _parse_ts, _read_json, resolve_path
from app.services.control_center.model import KST, CheckResult, now_kst


def _configured(env_names: list[str]) -> bool:
    return any((os.environ.get(n) or '').strip() for n in env_names)


def _due(last_observed: str | None, interval_min: float, now: datetime) -> bool:
    ts = _parse_ts(last_observed)
    return ts is None or ts > now or (now - ts).total_seconds() >= max(60, interval_min) * 60


def _telegram_getme(it: dict[str, Any]) -> CheckResult:
    token = (os.environ.get(it.get('env', 'TELEGRAM_BOT_TOKEN')) or '').strip()
    cid = f"provider:{it['id']}"
    label = it.get('label', 'Telegram')
    if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]+', token):
        return CheckResult(cid, 'provider', label, 'unknown', '봇 인증 설정 형식 오류')
    resp = http_get(f'https://api.telegram.org/bot{token}/getMe', timeout=8, provider=True)
    body = resp['json']
    ok = resp['status'] == 200 and isinstance(body, dict) and body.get('ok') is True
    return CheckResult(cid, 'provider', label, 'ok' if ok else 'fail',
                       '봇 인증 정상' if ok else '봇 인증 확인 실패',
                       severity=it.get('severity', 'standard'), latency_ms=resp['ms'])


def _dart_list(it: dict[str, Any]) -> CheckResult:
    key = (os.environ.get(it.get('env', 'DART_API_KEY')) or '').strip()
    query = urlencode({'crtfc_key': key, 'page_count': 1})
    resp = http_get(f'https://opendart.fss.or.kr/api/list.json?{query}', timeout=8, provider=True)
    body = resp['json']
    ok = resp['status'] == 200 and isinstance(body, dict) and body.get('status') in ('000', '013')
    return CheckResult(f"provider:{it['id']}", 'provider', it.get('label', 'OpenDART'),
                       'ok' if ok else 'fail', '정상' if ok else 'OpenDART 인증 또는 조회 확인 실패',
                       severity=it.get('severity', 'standard'), latency_ms=resp['ms'])


def _kis_token_cache(it: dict[str, Any], now: datetime) -> CheckResult:
    data = _read_json(resolve_path(it.get('path', '{data}/kis_token_cache.json')))
    cid = f"provider:{it['id']}"
    label = it.get('label', 'KIS 토큰')
    if not isinstance(data, dict):
        return CheckResult(cid, 'provider', label, 'warn', '토큰 캐시 없음 — 첫 KIS 호출 때 발급', severity='standard')
    from app.services.kis_screener import _TOKEN_CACHE_VERSION, _TOKEN_EXPIRY_MARGIN_SECONDS, _token_namespace

    namespace = _token_namespace()
    mode, fingerprint = namespace.split(':', 1)
    tokens = data.get('tokens')
    record = tokens.get(namespace) if data.get('version') == _TOKEN_CACHE_VERSION and isinstance(tokens, dict) else None
    if (not isinstance(record, dict) or not record.get('token') or record.get('mode') != mode
            or record.get('app_key_fingerprint') != fingerprint):
        return CheckResult(cid, 'provider', label, 'unknown', '현재 KIS 환경의 토큰 캐시 확인 불가')
    try:
        exp_dt = datetime.fromtimestamp(float(record['expires_at']), KST)
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        return CheckResult(cid, 'provider', label, 'unknown', '만료 시각을 읽을 수 없음', severity='info')
    left = (exp_dt - now).total_seconds()
    if left > _TOKEN_EXPIRY_MARGIN_SECONDS:
        return CheckResult(cid, 'provider', label, 'ok', f'토큰 유효 (남은 {_age_text(left)})', value=round(left / 3600, 1))
    detail = f'캐시 토큰 만료 {_age_text(-left)} 전' if left <= 0 else f'캐시 토큰 만료까지 {_age_text(left)}'
    return CheckResult(cid, 'provider', label, 'warn', detail,
                       value=round(left / 3600, 1))


def _ai_routing_health(it: dict[str, Any], now: datetime) -> CheckResult:
    if it.get('usage_path'):
        from app.services.control_center.llm_evidence import routing_evidence

        configured = [name for name, envs in it.get('provider_envs', {}).items() if _configured(envs)]
        return routing_evidence(it, now, configured)
    data = _read_json(resolve_path(it.get('path', '{data}/ai_routing/health.json')))
    cid = f"provider:{it['id']}"
    label = it.get('label', 'LLM 라우팅')
    if not isinstance(data, dict):
        return CheckResult(cid, 'provider', label, 'unknown', 'health.json 없음 — scripts/llm_routing_health.py --live 미실행',
                           severity='info')
    checked = _parse_ts(data.get('checked_at'))
    rows = data.get('providers')
    if (data.get('mode') != 'live' or checked is None or checked > now
            or not isinstance(rows, list) or not rows or not all(isinstance(p, dict) for p in rows)):
        return CheckResult(cid, 'provider', label, 'unknown', '유효한 실점검 기준 없음')
    configured = [p for p in rows if p.get('configured') is True]
    if not configured:
        return CheckResult(cid, 'provider', label, 'unknown', '설정된 공급자의 실점검 결과 없음')
    age_h = (now - checked).total_seconds() / 3600
    ttl = data.get('ttl_seconds')
    max_age = float(it.get('max_age_hours', 26))
    if type(ttl) is int and ttl > 0:
        max_age = min(max_age, ttl / 3600)
    unhealthy = sum(p.get('available') is not True or p.get('status') != 'healthy' for p in configured)
    if age_h > max_age:
        st, msg = 'warn', f'마지막 실점검 {_age_text(age_h * 3600)} 전'
    elif unhealthy:
        st, msg = 'warn', f'공급자 {unhealthy}곳 정상 확인 실패'
    else:
        st, msg = 'ok', f'설정된 공급자 {len(configured)}곳 정상'
    return CheckResult(cid, 'provider', label, st, msg, value={'unhealthy_count': unhealthy})


def check_providers(items: list[dict[str, Any]], last_observed: dict[str, str | None],
                    now: datetime | None = None) -> list[CheckResult]:
    """외부 호출은 명시적으로 활성화한 경우에만 최소 간격을 지켜 실행한다."""
    now = now or now_kst()
    out = []
    for it in items:
        cid = f"provider:{it['id']}"
        kind = it['type']
        envs = it.get('envs') or ([it['env']] if it.get('env') else [])
        if envs and not _configured(envs):
            out.append(CheckResult(cid, 'provider', it.get('label', it['id']), 'skipped', '키 미설정', severity='info',
                                   value={'configured': False}))
            continue
        if kind in ('telegram_getme', 'dart_list'):
            if os.environ.get('CONTROL_CENTER_PROVIDER_NETWORK_ENABLED') != '1':
                out.append(CheckResult(cid, 'provider', it.get('label', it['id']), 'skipped',
                                       '외부 실호출 비활성', severity='info'))
                continue
            if not _due(last_observed.get(cid), it.get('interval_min', 60), now):
                continue
        if kind == 'telegram_getme':
            out.append(_telegram_getme(it))
        elif kind == 'dart_list':
            out.append(_dart_list(it))
        elif kind == 'kis_token_cache':
            out.append(_kis_token_cache(it, now))
        elif kind == 'ai_routing_health':
            out.append(_ai_routing_health(it, now))
        elif kind == 'env_present':
            out.append(CheckResult(cid, 'provider', it.get('label', it['id']), 'ok', '키 설정됨', severity='info',
                                   value={'configured': True}))
        else:
            out.append(CheckResult(cid, 'provider', it.get('label', it['id']), 'unknown', '지원하지 않는 점검 종류'))
    return out

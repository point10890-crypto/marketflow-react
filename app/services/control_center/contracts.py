"""관제 계약(contracts.json) 읽기·검증.

라우트 목록은 Flask URL map에서 읽고 실제 요청 대상은 검토된 계약에서 정한다.
"""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit

from app.services.control_center import CONTRACTS_PATH

REQUIRED_TOP = ('api_base', 'ports', 'heartbeats', 'data', 'jobs', 'windows_tasks', 'providers', 'endpoints', 'pages')
TIERS = ('fast', 'standard', 'deep')
API_HOST = '127.0.0.1'
API_PORTS = {5001, 5003}
LOCAL_MONITOR_PORTS = API_PORTS | {8000, 8765}
PUBLIC_PATHS = {'marketflow-api.bit-man.net': '/healthz', 'bit-man.net': '/'}
PROVIDER_HOSTS = {'api.telegram.org', 'opendart.fss.or.kr'}


class ContractError(ValueError):
    pass


def safe_path(path: str) -> bool:
    return (isinstance(path, str) and path.startswith('/') and not path.startswith('//')
            and not any(ch in path for ch in '\\?#%')
            and not any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in path)
            and not ({'.', '..'} & set(path.split('/'))))


def _local_api(parts) -> bool:
    return (parts.scheme == 'http' and parts.hostname == API_HOST
            and parts.port in API_PORTS and parts.netloc == f'{API_HOST}:{parts.port}')


def validate_api_base(url: str) -> str:
    try:
        parts = urlsplit(url)
        if isinstance(url, str) and (_local_api(parts) and parts.path in ('', '/') and url in
                (f'http://{parts.netloc}', f'http://{parts.netloc}/')):
            return f'http://{parts.netloc}'
    except (TypeError, ValueError):
        pass
    raise ContractError('관제 API 주소는 지정된 로컬 Flask 포트만 사용할 수 있습니다')


def allowed_http_url(url: str, *, authenticated: bool = False, provider: bool = False) -> bool:
    if not isinstance(url, str) or any(ord(ch) <= 32 or ord(ch) == 127 for ch in url):
        return False
    try:
        parts = urlsplit(url)
        if not safe_path(parts.path or '/') or parts.fragment or parts.username or parts.password:
            return False
        if not provider and _local_api(parts):
            return not parts.query
        if authenticated or parts.scheme != 'https' or parts.netloc != parts.hostname:
            return False
        if provider:
            return parts.hostname in PROVIDER_HOSTS
        return not parts.query and PUBLIC_PATHS.get(parts.hostname) == (parts.path or '/')
    except ValueError:
        return False


def validate(c: dict[str, Any]) -> dict[str, Any]:
    missing = [k for k in REQUIRED_TOP if k not in c]
    if missing:
        raise ContractError(f'contracts.json 에 없는 항목: {missing}')
    validate_api_base(c['api_base'])
    for item in c.get('public_urls', []):
        if not allowed_http_url(item.get('url', '')) or not item['url'].startswith('https://'):
            raise ContractError('공개 점검 URL 오류')
    seen: set[str] = set()
    for group in ('ports', 'heartbeats', 'data', 'providers', 'public_urls', 'watchdogs'):
        for it in c.get(group, []):
            key = f"{group}:{it.get('id')}"
            if not it.get('id') or key in seen:
                raise ContractError(f'id 누락 또는 중복: {key}')
            seen.add(key)
            if it.get('severity', 'standard') not in ('critical', 'standard', 'info'):
                raise ContractError(f'severity 오류: {key}')
    for p in c.get('ports', []):
        if int(p['port']) not in LOCAL_MONITOR_PORTS:
            raise ContractError('허용되지 않은 관제 포트')
    paths = set()
    for key in ('public_safe', 'public_probe_safe', 'auth_probe_safe'):
        for path in c['endpoints'].get(key, []):
            if not safe_path(path) or '<' in path or '>' in path:
                raise ContractError(f'{key} 경로 오류')
    for d in c['endpoints'].get('deep', []):
        if not safe_path(d.get('path', '')) or '<' in d['path'] or '>' in d['path']:
            raise ContractError('deep 경로 오류')
        if d['path'] in paths:
            raise ContractError(f'deep path 중복: {d["path"]}')
        if d.get('tier', 'standard') not in TIERS:
            raise ContractError(f'tier 오류: {d["path"]}')
        paths.add(d['path'])
    page_paths = {p['path'] for p in c['pages']}
    for d in c['endpoints'].get('deep', []):
        unknown = set(d.get('pages', [])) - page_paths
        if unknown:
            raise ContractError(f'{d["path"]} 의 pages 가 pages 목록에 없음: {sorted(unknown)}')
    return c


@lru_cache(maxsize=4)
def _load_cached(path: str, mtime: float) -> dict[str, Any]:
    with open(path, encoding='utf-8') as f:
        return validate(json.load(f))


def load(path: str = CONTRACTS_PATH) -> dict[str, Any]:
    import os

    return _load_cached(path, os.path.getmtime(path))


def endpoint_contract(contracts: dict[str, Any], rule: str) -> dict[str, Any]:
    ep = contracts.get('endpoints', {})
    out: dict[str, Any] = {}
    if rule in set(ep.get('exclude', [])) or 'stream' in rule:
        out['exclude'] = True
    if rule in ep.get('auth_probe_safe', []):
        out['auth_probe_safe'] = True
    if rule in ep.get('public_probe_safe', []):
        out['public_safe'] = True
    for d in ep.get('deep', []):
        allowlist = 'public_probe_safe' if d.get('auth') == 'public' else 'auth_probe_safe'
        if d['path'] == rule and rule in ep.get(allowlist, []):
            out.update({'deep': True, 'tier': d.get('tier', 'standard'), 'pages': d.get('pages', [])})
            break
    return out

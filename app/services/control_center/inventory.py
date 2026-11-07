"""Flask URL map과 인증 데코레이터를 정적으로 분류한다. 실점검은 별도 허용 목록을 사용한다."""
from __future__ import annotations

import re
from typing import Any

AUTH_DECORATORS = {
    'admin_required': 'admin',
    'admin_or_aibain_required': 'admin_or_aibain',
    '_pro_required': 'pro',
    'pro_required': 'pro',
    'pro_or_kongming_required': 'pro',
    'approved_required': 'approved',
    'login_required': 'login',
}
# 강한 것부터 — 여러 겹이면 가장 강한 것을 대표로 쓴다.
AUTH_RANK = ['admin', 'admin_or_aibain', 'pro', 'approved', 'login', 'pro_gate', 'public']
MUTATING = {'POST', 'PUT', 'PATCH', 'DELETE'}

_CONVERTER_RE = re.compile(r'<(?:(?P<conv>[a-z]+)(?:\([^)]*\))?:)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)>')
# 경로 변수 표본: 보호 라우트의 인증 게이트 확인에는 아무 값이나 충분하다(핸들러가 실행되지 않음).
SAMPLE_BY_NAME = {
    'code': '005930', 'ticker': 'AAPL', 'symbol': '005930', 'stock_code': '005930', 'market': 'kr',
    'slug': 'notice', 'board_slug': 'notice', 'date': '20260102', 'job_key': 'health', 'filename': 'x.json',
}
SAMPLE_BY_CONVERTER = {'int': '1', 'float': '1.0', 'path': 'x', 'uuid': '00000000-0000-0000-0000-000000000000'}


def decorator_chain(func: Any, limit: int = 12) -> list[str]:
    """뷰 함수에 감긴 데코레이터 이름들 (바깥부터)."""
    names: list[str] = []
    seen = 0
    while func is not None and seen < limit:
        # functools.wraps 는 __qualname__ 을 덮어쓰지만 코드 객체의 co_qualname(3.11+)은 남는다.
        code = getattr(func, '__code__', None)
        qual = (getattr(code, 'co_qualname', '') if code is not None else '') or ''
        if '.<locals>.' in qual:
            names.append(qual.split('.<locals>.')[0].split('.')[-1])
        func = getattr(func, '__wrapped__', None)
        seen += 1
    return names


def is_pro_gated(path: str) -> bool:
    from app import PRO_GATE_EXEMPT_PREFIXES, PRO_GATED_PREFIXES

    if any(path.startswith(p) for p in PRO_GATE_EXEMPT_PREFIXES):
        return False
    return any(path.startswith(p) for p in PRO_GATED_PREFIXES)


def sample_path(rule: str) -> tuple[str, bool]:
    """경로 변수를 표본 값으로 채운다. 반환: (경로, 변수가 있었는지)."""
    had = False

    def repl(m: re.Match) -> str:
        nonlocal had
        had = True
        return SAMPLE_BY_CONVERTER.get(m.group('conv') or '') or SAMPLE_BY_NAME.get(m.group('name'), 'x')

    return _CONVERTER_RE.sub(repl, rule), had


def classify(rule: str, decorators: list[str]) -> str:
    levels = [AUTH_DECORATORS[d] for d in decorators if d in AUTH_DECORATORS]
    if is_pro_gated(rule):
        levels.append('pro_gate')
    if not levels:
        return 'public'
    return min(levels, key=AUTH_RANK.index)


def build_inventory(app) -> list[dict[str, Any]]:
    """앱의 모든 /api·/healthz 라우트를 (경로, 메서드) 단위로 분류한다."""
    out: list[dict[str, Any]] = []
    for r in app.url_map.iter_rules():
        if not (r.rule.startswith('/api') or r.rule in ('/healthz',)):
            continue
        view = app.view_functions.get(r.endpoint)
        decorators = decorator_chain(view)
        auth = classify(r.rule, decorators)
        methods = sorted(m for m in (r.methods or set()) if m not in ('HEAD', 'OPTIONS'))
        probe_path, has_vars = sample_path(r.rule)
        out.append({
            'rule': r.rule, 'endpoint': r.endpoint, 'methods': methods, 'auth': auth,
            'decorators': [d for d in decorators if d in AUTH_DECORATORS],
            'mutating': bool(set(methods) & MUTATING), 'readable': 'GET' in methods,
            'has_path_vars': has_vars, 'probe_path': probe_path,
        })
    out.sort(key=lambda x: (x['rule'], ','.join(x['methods'])))
    return out


def coverage(inventory: list[dict[str, Any]], contracts: dict[str, Any]) -> dict[str, Any]:
    """계약 대비 감시 범위 — 무엇을 어떻게 찌르는지, 무엇이 아직 검토되지 않았는지."""
    from app.services.control_center.contracts import endpoint_contract

    endpoints = contracts.get('endpoints', {})
    reviewed = {rule for key in ('public_safe', 'public_reviewed', 'public_info_exposure')
                for rule in endpoints.get(key, [])}
    rows = []
    totals = {'routes': 0, 'auth_gate': 0, 'deep': 0, 'public_safe': 0, 'public_reviewed': 0, 'public_unreviewed': 0,
              'excluded': 0, 'mutating_public': 0}
    for item in inventory:
        totals['routes'] += 1
        c = endpoint_contract(contracts, item['rule'])
        mode = 'none'
        if c.get('exclude'):
            mode = 'excluded'
        elif (item['readable'] and item['auth'] != 'public' and not item['has_path_vars']
              and c.get('auth_probe_safe')):
            mode = 'auth_gate'
        elif item['readable'] and item['auth'] == 'public':
            if c.get('public_safe'):
                mode = 'public_safe'
            else:
                mode = 'public_reviewed' if item['rule'] in reviewed else 'public_unreviewed'
        if mode in totals:
            totals[mode] += 1
        deep = bool(c.get('deep') and not c.get('exclude') and item['readable'])
        if deep:
            totals['deep'] += 1
        if item['mutating'] and item['auth'] == 'public' and not c.get('public_mutation_ok'):
            totals['mutating_public'] += 1
        rows.append({**item, 'probe_mode': mode, 'deep': deep,
                     'tier': c.get('tier', 'standard'), 'pages': c.get('pages', [])})
    return {'totals': totals, 'routes': rows}

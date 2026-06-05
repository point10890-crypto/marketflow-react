"""모든 mirofish 엔드포인트 매핑 + production 헬스체크.

local Flask test_client → 33개 라우트 전부 admin token 으로 호출.
GET 만 healthcheck (POST 는 사이드이펙트 있어 명시적 검증만).
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

env_path = ROOT / '.env'
if env_path.exists():
    for line in env_path.read_text(encoding='utf-8').splitlines():
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            k, v = k.strip(), v.strip()
            if k and v:
                os.environ[k] = v


def main():
    from app import create_app
    app = create_app()
    with app.app_context():
        from app.auth.decorators import generate_token
        token = generate_token(3)
    headers = {'Authorization': f'Bearer {token}'}

    routes = []
    for rule in app.url_map.iter_rules():
        if 'mirofish' in rule.rule:
            methods = sorted(m for m in (rule.methods or []) if m not in {'HEAD', 'OPTIONS'})
            routes.append((rule.rule, methods, rule.endpoint))
    routes.sort(key=lambda r: r[0])

    # Frontend 가 노출하는 endpointDefinitions (AdminEndpointsPage.tsx:54)
    fe_endpoints = {
        '/api/admin/mirofish/status': 'status (Service Status)',
        '/api/admin/mirofish/data-sources': 'dataSources (Data Sources)',
        '/api/admin/mirofish/targets/resolve': 'resolve (Target Resolve)',
        '/api/admin/mirofish/runs': 'history/createRun (Run History / Create Run)',
        '/api/admin/mirofish/runs/{id}': 'runDetail (Run Detail)',
        '/api/admin/mirofish/runs/{id}/graph': 'graph (Graph Artifact)',
        '/api/admin/mirofish/runs/{id}/events': 'events (Event Feed)',
        '/api/admin/mirofish/runs/{id}/report': 'report (Report)',
        '/api/admin/mirofish/deepseek/scanner-summary': 'deepseek (DeepSeek V2)',
        '/api/admin/mirofish/workflow/scan-analyze': 'workflow (MCP Top 3)',
    }

    groups = {
        'Core MiroFish': [],
        'Scanner (Alpha 자동 스캐너)': [],
        'Workflow (자동화 파이프라인)': [],
        'DeepSeek (LLM 통합)': [],
        'Targets / Search': [],
    }

    for rule, methods, ep in routes:
        rule_clean = rule.replace('<run_id>', '{id}').replace('<workflow_id>', '{id}')
        if 'scanner' in rule:
            groups['Scanner (Alpha 자동 스캐너)'].append((rule_clean, methods, ep))
        elif 'workflow' in rule:
            groups['Workflow (자동화 파이프라인)'].append((rule_clean, methods, ep))
        elif 'deepseek' in rule:
            groups['DeepSeek (LLM 통합)'].append((rule_clean, methods, ep))
        elif 'targets' in rule:
            groups['Targets / Search'].append((rule_clean, methods, ep))
        else:
            groups['Core MiroFish'].append((rule_clean, methods, ep))

    print('=' * 90)
    print('MiroFish Admin Endpoints — 33 routes 통합 매핑')
    print('=' * 90)
    print(f"  base: https://marketflow-api.bit-man.net (production via Cloudflared tunnel)")
    print(f"  auth: Bearer admin token (user_id=3)")
    print(f"  frontend: https://bit-man.net/admin/endpoints (10 cards 노출)")
    print()

    for group_name, items in groups.items():
        print(f"  ┌─ {group_name} ({len(items)} routes) " + '─' * (60 - len(group_name)))
        for rule, methods, ep in items:
            in_fe = '🟢' if rule in fe_endpoints else '⚪'
            fe_label = fe_endpoints.get(rule, '')
            print(f"  │  {in_fe} [{','.join(methods):4}] {rule:55}")
            if fe_label:
                print(f"  │       └─ FE: {fe_label}")
        print(f"  └{'─' * 70}")
        print()

    # GET healthcheck (사이드이펙트 없는 것만)
    print('=' * 90)
    print('Local healthcheck (GET only, admin token)')
    print('=' * 90)
    safe_get_routes = [r for r in routes if 'GET' in r[1] and '<' not in r[0]]
    with app.test_client() as c:
        ok = 0
        fail = 0
        for rule, _, ep in safe_get_routes:
            url = rule
            if rule == '/api/admin/mirofish/targets/resolve':
                url = rule + '?target=삼성전자'
            r = c.get(url, headers=headers)
            label = '✅' if r.status_code == 200 else f'⚠️  {r.status_code}'
            print(f"  {label}  GET {rule}")
            if r.status_code == 200:
                ok += 1
            else:
                fail += 1
                err = r.get_json() if r.is_json else r.data[:100]
                print(f"        body: {str(err)[:160]}")
    print()
    print(f"  Summary: {ok} OK, {fail} fail (out of {len(safe_get_routes)})")


if __name__ == '__main__':
    main()

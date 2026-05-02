"""HTTP test_client 로 모든 mirofish 라우트 검증."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# .env 로드
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

    # admin 토큰 발급 — admin user id=3 (point10890@gmail.com)
    from app.auth.decorators import generate_token
    with app.app_context():
        token = generate_token(3)  # known admin user_id
    headers = {'Authorization': f'Bearer {token}'}
    print(f'admin user_id=3, token_len={len(token)}')

    with app.test_client() as c:
        results = []

        def req(method, url, params=None, json_body=None, expect_status=200):
            kwargs = {'headers': headers}
            if params:
                kwargs['query_string'] = params
            if json_body is not None:
                kwargs['json'] = json_body
            r = getattr(c, method)(url, **kwargs)
            ok = r.status_code == expect_status
            label = '✅' if ok else '❌'
            print(f'{label} [{method.upper()}] {url} → {r.status_code} (expected {expect_status})')
            results.append((method, url, r.status_code, expect_status))
            return r

        # 1. status
        r = req('get', '/api/admin/mirofish/status')
        if r.status_code == 200:
            data = r.get_json()
            print(f'   service: {data.get("service")}, mode: {data.get("mode")}, ready: {data.get("ready")}')
            print(f'   brain.score: {data["brain"].get("score")}, regime: {data["brain"].get("regime")}')
            print(f'   data_sources: {len(data.get("data_sources", {}).get("files", []))} files')

        # 2. data-sources
        r = req('get', '/api/admin/mirofish/data-sources')
        if r.status_code == 200:
            data = r.get_json()
            print(f'   files: {len(data.get("files", []))}')

        # 3. targets/resolve
        r = req('get', '/api/admin/mirofish/targets/resolve', params={'target': '삼성전자'})
        if r.status_code == 200:
            data = r.get_json()
            print(f'   resolved.symbol: {data["resolved"].get("symbol")}')
            print(f'   price.price: {data["price"].get("price")}')
            print(f'   signal_count: {data.get("signal_count")}')
            print(f'   source_files: {len(data.get("source_files", []))}')

        # 4. invalid resolve
        r = req('get', '/api/admin/mirofish/targets/resolve', params={'target': ''}, expect_status=400)

        # 5. POST /runs (rule mode for speed)
        r = req('post', '/api/admin/mirofish/runs',
                json_body={'target': '삼성전자', 'agent_count': 5, 'mode': 'fast'},
                expect_status=201)
        run_id = None
        if r.status_code == 201:
            run = r.get_json()
            run_id = run.get('id')
            print(f'   created run_id: {run_id}')
            print(f'   verdict: {run["verdict"].get("action")} {run["verdict"].get("confidence_pct")}%')
            print(f'   layers: {[l["label"] for l in run.get("layers", [])]}')

        # 6. GET /runs (history)
        r = req('get', '/api/admin/mirofish/runs', params={'limit': 5})
        if r.status_code == 200:
            data = r.get_json()
            print(f'   runs: {len(data.get("runs", []))}')

        # 7. GET /runs/<id>
        if run_id:
            r = req('get', f'/api/admin/mirofish/runs/{run_id}')
            if r.status_code == 200:
                data = r.get_json()
                print(f'   id matches: {data.get("id") == run_id}')

            # 8. GET /runs/<id>/graph
            r = req('get', f'/api/admin/mirofish/runs/{run_id}/graph')
            if r.status_code == 200:
                data = r.get_json()
                print(f'   nodes: {len(data.get("nodes", []))}, edges: {len(data.get("edges", []))}')

            # 9. GET /runs/<id>/report
            r = req('get', f'/api/admin/mirofish/runs/{run_id}/report')
            if r.status_code == 200:
                data = r.get_json()
                print(f'   markdown length: {len(data.get("markdown", ""))}')

            # 10. GET /runs/<id>/events
            r = req('get', f'/api/admin/mirofish/runs/{run_id}/events', params={'since': 0, 'limit': 50})
            if r.status_code == 200:
                data = r.get_json()
                print(f'   events: {len(data.get("events", []))}, total: {data.get("total")}')

        # 11. invalid run_id
        r = req('get', '/api/admin/mirofish/runs/nonexistent_xx', expect_status=404)

        # 12. unauthorized (no token)
        r = c.get('/api/admin/mirofish/status')
        unauth_ok = r.status_code == 401
        print(f"{'✅' if unauth_ok else '❌'} no-token check: {r.status_code} (expected 401)")
        results.append(('get', '/status [no-token]', r.status_code, 401))

        # 13. invalid since param
        if run_id:
            r = req('get', f'/api/admin/mirofish/runs/{run_id}/events',
                    params={'since': 'not_a_num'}, expect_status=400)

    failed = [r for r in results if r[2] != r[3]]
    total = len(results)
    print()
    print('=' * 60)
    print(f'Summary: {total - len(failed)}/{total} passed')
    if failed:
        for method, url, got, exp in failed:
            print(f'  ❌ [{method.upper()}] {url} got {got}, expected {exp}')
        sys.exit(1)
    print('✅ ALL HTTP CHECKS PASSED')


if __name__ == '__main__':
    main()

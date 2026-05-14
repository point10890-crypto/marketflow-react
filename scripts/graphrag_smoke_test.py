"""GraphRAG Phase A smoke test — entry script (encoding-safe)."""
import sys
import os

# 부모 디렉토리를 path 에 추가 (스크립트 직접 실행 대응)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import create_app  # noqa: E402
from app.services.mirofish.graphrag import get_subsystem_status  # noqa: E402


def main() -> int:
    app = create_app()
    bp_rules = [r.rule for r in app.url_map.iter_rules() if '/api/admin/mirofish/graphrag/' in r.rule]
    print(f"[1] Blueprint rules: {bp_rules}")
    print(f"[1.1] count = {len(bp_rules)}")

    status = get_subsystem_status()
    print(f"[2] state = {status['state']}")
    print(f"[3] ready = {status['ready']}")
    print(f"[4] entity_count = {status['entities'].get('entity_count', 0)}")
    print(f"[5] shadow_mode = {status['flags']['shadow_mode']}")
    print(f"[6] keys_present = {status['flags']['keys_present']}")
    print(f"[7] root dir created = {status['storage']['root']['exists']}")
    print(f"[8] asof = {status['asof']}")

    # Test client 로 admin 토큰 검증 우회 후 실제 응답 확인
    with app.test_client() as client:
        resp = client.get('/api/admin/mirofish/graphrag/status', headers={
            'Authorization': 'Bearer 3:1781219291:0e324300d1e528dd932d4c19ddec0792',
        })
        print(f"[9] HTTP {resp.status_code}")
        data = resp.get_json()
        print(f"[10] response keys = {list(data.keys()) if data else None}")
    print("OK")
    return 0


if __name__ == '__main__':
    sys.exit(main())

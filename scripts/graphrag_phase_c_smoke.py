"""Phase C + P0 #4 smoke test — import + key existence verification.

이 스크립트는 miniPC 의 cmd 환경에서 실행할 수 있는 인용 부담 없는 1-shot 검증기.
"""
import sys, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main() -> int:
    from app import create_app
    app = create_app()
    print(f"[1] app routes: {sum(1 for _ in app.url_map.iter_rules())}")

    from app.services.mirofish import store, workflow
    from app.services.mirofish.graphrag import (
        resolve_entity,
        get_subsystem_status,
    )
    print("[2] imports OK")

    # Phase C 헬퍼 존재 확인
    assert hasattr(workflow, '_workflow_graphrag_summary'), 'missing _workflow_graphrag_summary'
    assert hasattr(workflow, '_workflow_source_freshness'), 'missing _workflow_source_freshness'
    print("[3] workflow phase-C helpers present")

    # store._verdict_from_cio 시그니처 확인 (keyword args 추가됐는지)
    import inspect
    sig = inspect.signature(store._verdict_from_cio)
    params = list(sig.parameters.keys())
    for k in ('symbol', 'market', 'reference_date'):
        assert k in params, f'missing keyword arg {k} in _verdict_from_cio: {params}'
    print(f"[4] _verdict_from_cio params: {params}")

    # GraphRAG status 호출
    status = get_subsystem_status()
    print(f"[5] state={status['state']} entity_count={status['entities'].get('entity_count')}")
    assert status['phase']['B_resolver'] is True

    # Resolve 한 번 호출 (스모크)
    rs = resolve_entity('삼성전자', limit=2)
    print(f"[6] resolve('삼성전자') → matches={len(rs['matches'])}")
    assert rs['matches'][0]['entity_id'] == 'kr:005930'

    print("OK")
    return 0


if __name__ == '__main__':
    sys.exit(main())

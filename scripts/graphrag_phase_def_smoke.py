"""Phase D + E + F smoke test — import + MCP tool count + eval IC sanity."""
import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main() -> int:
    from app import create_app
    app = create_app()
    print(f"[1] app routes total: {sum(1 for _ in app.url_map.iter_rules())}")
    eval_rules = [r.rule for r in app.url_map.iter_rules() if '/graphrag/' in r.rule]
    print(f"[2] graphrag routes: {len(eval_rules)}")
    for r in sorted(eval_rules):
        print(f"    - {r}")

    # Phase E: MCP server build
    from app.services.mirofish.mcp_server import create_mcp_server
    try:
        mcp = create_mcp_server()
        print(f"[3] MCP server created: type={type(mcp).__name__}")
    except Exception as exc:
        print(f"[3] MCP create FAILED: {exc}")
        return 1

    # Phase F: eval module + outcome advisory
    from app.services.mirofish.graphrag.eval import (
        run_jongga_v2_replay,
        get_eval_history,
        _compute_ic,
    )
    from app.services.mirofish.outcome_tracker import get_advisory_feedback
    ic_identity = _compute_ic([(1, 1), (2, 2), (3, 3), (4, 4), (5, 5)])
    ic_empty = _compute_ic([])
    ic_constant = _compute_ic([(1, 1)] * 5)
    print(f"[4] _compute_ic identity={ic_identity} empty={ic_empty} constant={ic_constant}")
    assert abs(ic_identity - 1.0) < 1e-6
    assert ic_empty == 0.0
    assert ic_constant == 0.0

    history = get_eval_history(limit=2)
    print(f"[5] eval_history initially: {len(history)} entries")

    # advisory feedback smoke (운영 데이터 의존 — 에러 없이 반환만 확인)
    try:
        adv = get_advisory_feedback()
        print(f"[6] advisory_feedback evaluated_count={adv.get('evaluated_count')} keys={list(adv.keys())[:5]}")
    except Exception as exc:
        print(f"[6] advisory_feedback raised: {exc}")
        return 1

    # Phase A status — F_eval 이 eval 디렉토리 보고 자동 감지
    from app.services.mirofish.graphrag import get_subsystem_status
    status = get_subsystem_status()
    print(f"[7] phase: {status['phase']}")
    print(f"[8] endpoints_live: {status['endpoints_live']}")

    print("OK")
    return 0


if __name__ == '__main__':
    sys.exit(main())

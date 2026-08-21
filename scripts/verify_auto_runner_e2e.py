"""auto_runner 엔드투엔드 검증 스크립트 - miniPC 직접 실행.

검증 단계:
  Phase 1a: alpha_scanner.run_scanner_alert_check (no LLM) - 후보 검출
  Phase 1b: workflow_svc.start_workflow_from_scanner_events dry_run=True - 후보 필터
  Phase 2 : 실 워크플로우 분석 (LLM 호출) - --full 플래그 시
  Phase 3 : telegram message build + 길이 확인

사용:
  python scripts/verify_auto_runner_e2e.py             # Phase 1만 (안전, LLM 없음)
  python scripts/verify_auto_runner_e2e.py --full      # 실 분석 + 메시지 빌드

실제 전송은 이 진단 스크립트에서 지원하지 않습니다. 검증된 one-shot
operator(`scripts/run_verified_alpha_telegram.py`)의 preview/confirm 절차만
사용하십시오.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

def _load_local_env() -> None:
    """Load analysis credentials only after unsafe transport flags are rejected."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if k and v:
                os.environ.setdefault(k, v)


def main():
    full = "--full" in sys.argv
    if "--send" in sys.argv:
        print("[BLOCKED] 이 진단 스크립트의 직접 Telegram/AIbain 전송은 비활성화되었습니다.")
        print("먼저 scripts/run_verified_alpha_telegram.py preview를 실행한 뒤,")
        print("정확한 run_id/message_digest와 SEND_VERIFIED_ALPHA_TELEGRAM 확인 절차를 사용하십시오.")
        return 3

    _load_local_env()

    from app.services.mirofish import alpha_scanner, workflow as workflow_svc

    print("=== Phase 0: latest scanner run (no dedup) ===")
    latest = alpha_scanner.read_latest_scanner_run()
    if latest:
        cands = latest.get("candidates") or []
        print(f"  scanner_run_id  : {latest.get('id')}")
        print(f"  total candidates: {len(cands)}")
        # 상위 5개만
        for c in sorted(cands, key=lambda x: -float(x.get("alpha_score") or 0))[:5]:
            print(f"    - {c.get('display_name')} ({c.get('symbol')}) "
                  f"alpha={c.get('alpha_score')} risk={c.get('risk_score')} action={c.get('action')}")
    else:
        print("  [STOP] no scanner run found")
        return 1

    print("\n=== Phase 1a: alert_check (state=alert_state, dedup ON) ===")
    alert = alpha_scanner.run_scanner_alert_check(
        {},
        min_alpha=40.0,
        max_risk=80.0,
        max_events=8,
        commit_state=False,
        block_on_stale=False,
    )
    print(f"  alert_blocked  : {alert.get('alert_blocked')}")
    print(f"  blocked_reason : {alert.get('blocked_reason')}")
    events = alert.get("events") or []
    print(f"  new events     : {len(events)} (dedup against alert_state)")

    # workflow event state 도 확인
    from app.services.mirofish.workflow import _event_state_path
    workflow_state_path = _event_state_path()
    print(f"\n=== Phase 1a': alert_check (state=workflow event state) ===")
    print(f"  state_path     : {workflow_state_path}")
    alert_wf = alpha_scanner.run_scanner_alert_check(
        {},
        state_path=workflow_state_path,
        min_alpha=40.0,
        max_risk=80.0,
        max_events=8,
        commit_state=False,
        block_on_stale=False,
    )
    events_wf = alert_wf.get("events") or []
    print(f"  new events     : {len(events_wf)} (dedup against workflow state)")
    for e in events_wf[:5]:
        c = e.get("candidate") or {}
        print(f"    - {c.get('display_name')} ({c.get('symbol')}) "
              f"alpha={c.get('alpha_score')} risk={c.get('risk_score')}")

    print("\n=== Phase 1b: workflow dry_run=True (스캐너 → 후보 필터) ===")
    dry = workflow_svc.start_workflow_from_scanner_events(
        payload={
            "allow_stale_sources": True,
            "min_alpha": 40,
            "max_risk": 80,
            "max_events": 3,
            "top_n": 3,
            "agent_count": 3,
            "dry_run": True,
            "force": True,
        },
        async_mode=False,
        commit_event_state=False,
    )
    print(f"  status          : {dry.get('status')}")
    print(f"  candidate_count : {dry.get('candidate_count')}")
    for c in (dry.get("candidates") or [])[:3]:
        print(f"    - {c.get('display_name')} ({c.get('symbol')}) action={c.get('action')}")

    if not full:
        print("\n[OK] Phase 1 PASS. 실 분석은 --full 플래그로 실행.")
        return 0

    print("\n=== Phase 2: 실 워크플로우 분석 (LLM 호출, ~90s 소요) ===")
    print("  ⏳ start_workflow_from_scanner_events sync mode...")
    result = workflow_svc.start_workflow_from_scanner_events(
        payload={
            "allow_stale_sources": True,
            "min_alpha": 40,
            "max_risk": 80,
            "max_events": 3,
            "top_n": 3,
            "agent_count": 3,
            "force": True,
        },
        async_mode=False,
        commit_event_state=False,
    )
    status = result.get("status")
    print(f"  status          : {status}")
    print(f"  workflow_id     : {result.get('id')}")
    print(f"  analyzed_count  : {len(result.get('analysis_runs') or [])}")

    top3 = result.get("top3") or []
    print(f"  top3 count      : {len(top3)}")
    for i, item in enumerate(top3, 1):
        cand = item.get("candidate") or {}
        verdict = item.get("verdict") or {}
        print(f"    TOP {i}: {item.get('target') or cand.get('display_name')} "
              f"({item.get('symbol') or cand.get('symbol')}) "
              f"score={item.get('final_score')} "
              f"verdict={verdict.get('action')} {verdict.get('confidence_pct')}%")

    if not top3:
        print("\n[FAIL] top3 비어있음 - 분석 실패")
        return 2

    print("\n=== Phase 3: telegram message build ===")
    msg = workflow_svc.build_workflow_top3_telegram_message(result)
    print(f"  message_chars   : {len(msg)}")
    print(f"  preview:")
    print("  " + "─" * 60)
    for line in msg[:1000].split("\n")[:25]:
        print(f"  | {line}")
    print("  " + "─" * 60)

    print("\n[INFO] 실송신은 비활성화됨 - 검증된 one-shot operator만 사용")

    print("\n[OK] 전체 검증 PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())

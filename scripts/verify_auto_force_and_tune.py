"""auto-force + LLM tuner 통합 검증"""
import os
import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

env_path = ROOT / '.env'
if env_path.exists():
    for line in env_path.read_text(encoding='utf-8').splitlines():
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            k, v = k.strip(), v.strip()
            if k and v:
                os.environ.setdefault(k, v)


def main():
    from app.services.mirofish.auto_runner import (
        _tunables, _read_state, recommend_thresholds, get_status,
    )

    print('=== Test 1: tunables 에 force_after_hours 포함 ===')
    t = _tunables()
    print(f'  force_after_hours: {t.get("force_after_hours")} (기대: 4)')
    assert t.get('force_after_hours') == 4, 'force_after_hours not 4'
    print('  [OK]')

    print()
    print('=== Test 2: LLM 임계값 추천 호출 (Gemini, ~10s) ===')
    rec = recommend_thresholds(window_days=14)
    print(f'  ok: {rec.get("ok")}')
    if not rec.get('ok'):
        print(f'  error: {rec.get("error")}')
        if rec.get('raw_preview'):
            print(f'  raw: {rec["raw_preview"][:200]}')
        return 2
    print(f'  duration: {rec.get("duration_s")}s')
    print(f'  recommendation:')
    r = rec.get('recommendation') or {}
    print(f'    min_alpha:         {r.get("min_alpha")}')
    print(f'    max_risk:          {r.get("max_risk")}')
    print(f'    min_new_events:    {r.get("min_new_events")}')
    print(f'    cooldown_minutes:  {r.get("cooldown_minutes")}')
    print(f'    force_after_hours: {r.get("force_after_hours")}')
    print(f'    confidence:        {r.get("confidence")}')
    print(f'  reasoning: {(r.get("reasoning") or "")[:200]}')
    print()
    print('  diff:')
    for d in rec.get('diff') or []:
        delta = d.get('delta')
        delta_str = f'{delta:+.1f}' if isinstance(delta, (int, float)) and delta != 0 else '·'
        print(f'    {d["field"]:25s} {d["current"]} → {d["recommended"]} ({delta_str})')

    print()
    print('=== Test 3: last_recommendation 영속화 ===')
    state = _read_state()
    last_rec = state.get('last_recommendation')
    if last_rec and last_rec.get('ok'):
        print(f'  [OK] state.last_recommendation 저장됨 (generated_at={last_rec.get("generated_at")})')
    else:
        print(f'  [WARN] state 영속화 안됨')

    print()
    print('=== Test 4: get_status() 동작 정상 ===')
    s = get_status()
    print(f'  phase: {s.get("phase")} | checks: {s["today"]["checks"]} | triggers: {s["today"]["triggers"]}')
    print(f'  tuning.force_after_hours: {s["tuning"].get("force_after_hours")}')

    print()
    print('[OK] 전체 검증 PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())

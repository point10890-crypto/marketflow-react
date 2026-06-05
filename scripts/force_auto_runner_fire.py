"""auto_runner force_trigger() 직접 호출 — dedup 우회 + 실제 발사"""
import os
import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

# .env 로드
env_path = ROOT / '.env'
if env_path.exists():
    for line in env_path.read_text(encoding='utf-8').splitlines():
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            k, v = k.strip(), v.strip()
            if k and v:
                os.environ.setdefault(k, v)

print('=== force_trigger() 호출 (실제 발사 — LLM 비용 ~$0.07) ===')
from app.services.mirofish.auto_runner import force_trigger, get_status

print('--- BEFORE ---')
before = get_status()
print(f'  phase: {before["phase"]}')
print(f'  today.triggers: {before["today"]["triggers"]}')
print(f'  today.successes: {before["today"]["successes"]}')

print()
print('--- FIRING (~90s with LLM) ---')
result = force_trigger()
print(f'  fired: {result.get("fired")}')
print(f'  success: {result.get("success")}')
print(f'  workflow_id: {result.get("workflow_id")}')
print(f'  top3_count: {result.get("top3_count")}')
print(f'  telegram_ok: {result.get("telegram_ok")}')
print(f'  aibain_ok: {result.get("aibain_ok")}')
if result.get('error'):
    print(f'  error: {result.get("error")}')
if result.get('reason'):
    print(f'  reason: {result.get("reason")}')

print()
print('--- AFTER ---')
after = get_status()
print(f'  phase: {after["phase"]}')
print(f'  today.triggers: {after["today"]["triggers"]}')
print(f'  today.successes: {after["today"]["successes"]}')
print(f'  today.failures: {after["today"]["failures"]}')
print(f'  today.telegram_sent: {after["today"]["telegram_sent"]}')
print(f'  today.est_cost_usd: ${after["today"]["est_cost_usd"]:.3f}')
print(f'  last_workflow_id: {after.get("last_workflow_id")}')
print(f'  last_top3_count: {after.get("last_top3_count")}')

# 결과 판정
if result.get('success') and result.get('telegram_ok'):
    print('\n[OK] AUTO_RUNNER 발사 + 텔레그램 송신 PASS')
    sys.exit(0)
elif result.get('fired'):
    print(f'\n[PARTIAL] 발사됐으나 일부 실패')
    sys.exit(1)
else:
    print(f'\n[FAIL] 발사 자체 실패: {result.get("reason")}')
    sys.exit(2)

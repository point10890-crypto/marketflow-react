"""auto_runner env 로드 + tunables 검증"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# .env 강제 로드 (Flask 와 동일 방식)
env_path = ROOT / '.env'
if env_path.exists():
    for line in env_path.read_text(encoding='utf-8').splitlines():
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            k, v = k.strip(), v.strip()
            if k and v:
                os.environ.setdefault(k, v)

print('=== env vars (after .env load) ===')
for k in [
    'MIROFISH_AUTO_RUNNER_ENABLED',
    'MIROFISH_AUTO_RUNNER_MIN_ALPHA',
    'MIROFISH_AUTO_RUNNER_MAX_RISK',
    'MIROFISH_AUTO_RUNNER_MIN_NEW',
    'MIROFISH_AUTO_RUNNER_ALLOW_STALE',
    'MIROFISH_AUTO_RUNNER_COOLDOWN_MIN',
    'MIROFISH_AUTO_RUNNER_DAILY_CAP_USD',
]:
    print(f'  {k} = {os.getenv(k)!r}')

print()
print('=== _tunables() output ===')
from app.services.mirofish.auto_runner import _tunables
t = _tunables()
for k, v in t.items():
    print(f'  {k}: {v}')

print()
print('=== gate evaluation ===')
from app.services.mirofish.auto_runner import _evaluate_gates
gates = _evaluate_gates(force=False, tuning=t)
for g in gates['gates']:
    mark = '✓' if g['ok'] else '✗'
    print(f'  {mark} {g["name"]}: {g.get("detail")}')
print(f'all_pass={gates["all_pass"]}, failed={gates["failed_reason"]}')

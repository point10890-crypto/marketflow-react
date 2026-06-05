"""Alpha Scanner 최신 candidates 분포 확인"""
import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

env = (ROOT / '.env').read_text(encoding='utf-8')
for line in env.splitlines():
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())

from app.services.mirofish.alpha_scanner import read_latest_scanner_run, get_scanner_diagnostics

latest = read_latest_scanner_run()
if not latest:
    print('NO scanner run found')
    sys.exit(0)

print('=' * 70)
print(f'Alpha Scanner Latest Run')
print('=' * 70)
print(f'id       : {latest.get("id")}')
print(f'generated: {latest.get("generated_at") or latest.get("created_at")}')
print(f'freshness: {(latest.get("freshness") or {}).get("status")}')
print(f'source   : {latest.get("source")}')

cands = latest.get('candidates') or []
print(f'\ntotal candidates: {len(cands)}')

# alpha/risk 분포
if cands:
    alpha_scores = [float(c.get('alpha_score') or 0) for c in cands]
    risk_scores = [float(c.get('risk_score') or 0) for c in cands]
    actions = {}
    for c in cands:
        a = c.get('action', 'NONE')
        actions[a] = actions.get(a, 0) + 1
    print(f'\n분포:')
    print(f'  alpha avg/max/min: {sum(alpha_scores)/len(alpha_scores):.1f} / {max(alpha_scores):.1f} / {min(alpha_scores):.1f}')
    print(f'  risk  avg/max/min: {sum(risk_scores)/len(risk_scores):.1f} / {max(risk_scores):.1f} / {min(risk_scores):.1f}')
    print(f'  alpha ≥ 70: {sum(1 for a in alpha_scores if a >= 70)}')
    print(f'  alpha ≥ 60: {sum(1 for a in alpha_scores if a >= 60)}')
    print(f'  alpha ≥ 50: {sum(1 for a in alpha_scores if a >= 50)}')
    print(f'  action 분포: {actions}')

    print(f'\nTOP 10 (alpha 기준):')
    top = sorted(cands, key=lambda c: float(c.get('alpha_score') or 0), reverse=True)[:10]
    for i, c in enumerate(top, 1):
        print(f'  {i:2d}. {c.get("display_name", "?"):<15s} ({c.get("symbol", "?")}) alpha={c.get("alpha_score")} risk={c.get("risk_score")} action={c.get("action")}')

print()
print('=' * 70)
print('Diagnostics')
print('=' * 70)
diag = get_scanner_diagnostics()
print(f'health: {diag.get("health")}')
issues = diag.get('issues') or []
print(f'issues: {len(issues)}')
for iss in issues[:5]:
    print(f'  [{iss.get("severity")}] {iss.get("code")}: {iss.get("message")}')

"""거래정지 필터 검증 — KEC 가 jubjub 결과에 포함되는지 확인"""
import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

env = (ROOT / '.env').read_text(encoding='utf-8')
for line in env.splitlines():
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1)
        os.environ[k.strip()] = v.strip()

print('=== 1) jubjub_analyzer 거래정지 필터 단독 호출 ===')
from engine.jubjub_analyzer import _is_halted_or_invalid
for sym in ['005930', '092220', '000660', '000020']:  # 삼성/KEC/SK하이닉스/동화약품
    halted = _is_halted_or_invalid(sym)
    print(f'  {sym}: halted={halted}')

print()
print('=== 2) screener.json 의 W (Bullish) 종목 + 직접 키움 호출 ===')
import json
sj = ROOT / 'data' / 'wave' / 'wave_screener_latest.json'
data = json.loads(sj.read_text(encoding='utf-8'))
signals = data.get('signals') or []
w_signals = [s for s in signals if s.get('best_pattern', {}).get('pattern_class') == 'W']
print(f'  W 패턴 종목 수: {len(w_signals)}')

print()
print('=== 3) filter_and_sort_jubjub 호출 — KEC 결과에 있는지 ===')
from engine.jubjub_analyzer import filter_and_sort_jubjub
candidates = filter_and_sort_jubjub(signals, min_score=60, limit=200, exclude_halted=True)
print(f'  jubjub 후보 (exclude_halted=True): {len(candidates)}')

# KEC (092220) 포함 여부
kec_in_jubjub = any(c['ticker'] == '092220' for c in candidates)
print(f'  KEC (092220) 포함: {kec_in_jubjub}')

# exclude_halted=False 비교
all_cand = filter_and_sort_jubjub(signals, min_score=60, limit=200, exclude_halted=False)
print(f'  exclude_halted=False 시: {len(all_cand)} (차이 {len(all_cand) - len(candidates)} 개 제외됨)')
kec_in_all = any(c['ticker'] == '092220' for c in all_cand)
print(f'  KEC in all (no filter): {kec_in_all}')

print()
print('=== 4) 제외된 종목 리스트 ===')
candidates_set = {c['ticker'] for c in candidates}
all_set = {c['ticker'] for c in all_cand}
excluded = all_set - candidates_set
print(f'  excluded count: {len(excluded)}')
for t in list(excluded)[:10]:
    item = next((c for c in all_cand if c['ticker'] == t), None)
    if item:
        print(f'    {t} {item.get("name")} (score={item.get("jubjub_score")})')

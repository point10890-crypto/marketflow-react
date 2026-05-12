"""miniPC 키움 즉시 호출 - 본PC 토큰 발급 후 충돌 여부 확인"""
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

print(f'URL: {os.getenv("KIWOOM_BASE_URL")}')
print(f'KEY tail: ...{os.getenv("KIWOOM_APP_KEY","")[-6:]}')

from engine.kiwoom_client import get_stock_quote
q = get_stock_quote('005930')
if not q:
    print('result: None')
elif q.get('stk_nm'):
    print(f'OK - {q["stk_nm"]} {q.get("cur_prc", "?")}')
else:
    print(f'partial - keys: {list(q.keys())[:5]}')

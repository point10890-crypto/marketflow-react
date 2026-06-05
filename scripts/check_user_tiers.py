"""users.db tier 분포 + tier 명칭 사용처 확인"""
import os, sys, sqlite3
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

db_path = ROOT / 'data' / 'users.db'
c = sqlite3.connect(str(db_path))

print('=== tier 값 분포 ===')
rows = c.execute('SELECT tier, COUNT(*) FROM users GROUP BY tier').fetchall()
for tier, cnt in rows:
    print(f'  {tier!r}: {cnt}')

print()
print('=== email + tier (관리자/Pro 확인) ===')
cols = [c[1] for c in c.execute('PRAGMA table_info(users)').fetchall()]
print(f'columns: {cols}')
# 사용자 본인 (point10890@gmail.com)
rows = c.execute("SELECT * FROM users WHERE email LIKE '%point10890%' LIMIT 5").fetchall()
for row in rows:
    info = dict(zip(cols, row))
    show = {k: info.get(k) for k in ('id','email','tier','status','role','is_admin','pro_expires_at') if k in info}
    print(f'  user: {show}')

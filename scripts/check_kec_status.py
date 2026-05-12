"""KEC (092220) 실제 상태 확인 + screener json 신선도 검증"""
import os, sys, json
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
    p = ROOT / 'data' / 'wave' / 'wave_screener_latest.json'
    print(f'=== screener path: {p} ===')
    if p.exists():
        import time
        mtime = time.localtime(p.stat().st_mtime)
        print(f'  exists: True, mtime: {time.strftime("%Y-%m-%d %H:%M:%S", mtime)}')
        with open(p, 'r', encoding='utf-8') as f:
            d = json.load(f)
        print(f'  date in json: {d.get("date")}')
        print(f'  updated_at: {d.get("updated_at")}')
        print(f'  signal_count: {d.get("signal_count")}')
        kec = [s for s in d.get('signals', []) if s.get('ticker') == '092220']
        if kec:
            k = kec[0]
            print(f'  KEC found in screener: ticker={k["ticker"]} name={k["name"]} price={k.get("price")}')
            bp = k.get('best_pattern', {})
            print(f'    pattern={bp.get("pattern_class")} confidence={bp.get("confidence")}')
        else:
            print(f'  KEC not in screener')
    else:
        print(f'  exists: False')

    print()
    print('=== 키움 API 로 KEC 현재 상태 ===')
    try:
        from engine.kiwoom_client import get_stock_quote
        r = get_stock_quote('092220')
        if isinstance(r, dict):
            print(f'  type: dict, keys top 10:')
            for k in ['stk_cd', 'stk_nm', 'cur_prc', 'pred_pre', 'flu_rt', 'trde_qty', 'trde_tp', 'trde_stop_yn', 'mng_stk_yn']:
                v = r.get(k)
                if v:
                    print(f'    {k}: {v}')
        else:
            print(f'  result: {r}')
    except Exception as e:
        print(f'  ERROR: {type(e).__name__}: {e}')

    print()
    print('=== 거래정지 / 관리종목 / 거래중지 필드 탐색 (KIS 결과 dump) ===')
    try:
        from engine.kiwoom_client import get_stock_quote
        r = get_stock_quote('092220')
        if isinstance(r, dict):
            for k, v in r.items():
                kl = k.lower()
                if 'stop' in kl or 'halt' in kl or 'mng' in kl or 'sus' in kl or 'trd' in kl[:4]:
                    print(f'    {k}: {v}')
    except Exception:
        pass


if __name__ == '__main__':
    main()

"""mirofish-mcp 신규 금융 도구 실호출 검증 (miniPC 운영 환경)"""
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
    symbol = '005930'  # 삼성전자
    print(f'=== 검증 대상: {symbol} (삼성전자) ===')

    print('\n[1] get_kiwoom_quote')
    from engine.kiwoom_client import get_stock_quote
    q = get_stock_quote(symbol)
    if q:
        print(f'   OK — keys: {list(q.keys())[:8]}')
    else:
        print('   None')

    print('\n[2] get_kiwoom_daily_chart')
    from engine.kiwoom_client import get_daily_ohlcv
    c = get_daily_ohlcv(symbol)
    if c:
        print(f'   OK — keys: {list(c.keys())[:5]}')
    else:
        print('   None')

    print('\n[3] get_kiwoom_institution_trend')
    from engine.kiwoom_client import get_institution_trend
    inst = get_institution_trend(symbol, '', '')
    if inst:
        print(f'   OK — keys: {list(inst.keys())[:5]}')
    else:
        print('   None')

    print('\n[4] get_dart_disclosures')
    from engine.dart_deep_pipeline import get_cached_result
    dart = get_cached_result(symbol)
    print(f'   cached: {dart is not None}')

    print('\n[5] technical_levels (analyze_target_with_levels)')
    from app.services.mirofish.technical_analysis import analyze_target_with_levels
    tech = analyze_target_with_levels(target=symbol)
    print(f'   trend: {tech.get("trend")}')
    print(f'   entry: {tech.get("entry_price")}  target: {tech.get("target_price")}  stop: {tech.get("stop_price")}')

    print('\n[6] get_outcomes_kpi (30d)')
    from app.services.mirofish.pipeline_overview import get_outcomes_board
    board = get_outcomes_board(days=30, limit=10)
    summary = board.get('summary') or {}
    print(f'   hit_rate: {summary.get("hit_rate_pct")}%, avg_return: {summary.get("avg_forward_return_pct")}%')
    print(f'   evaluated: {summary.get("evaluated_count")}, pending: {summary.get("pending_count")}')

    print('\n[7] get_pipeline_today_snapshot')
    from app.services.mirofish.pipeline_overview import get_pipeline_today_snapshot
    snap = get_pipeline_today_snapshot()
    print(f'   KR phase: {snap["market"]["kr"]["phase"]}')
    print(f'   funnel: scanner={snap["funnel"]["scanner_pool"]} top3={snap["funnel"]["top3_ready"]}')

    print('\n[8] get_alpha_scanner_diagnostics')
    from app.services.mirofish.alpha_scanner import get_scanner_diagnostics
    diag = get_scanner_diagnostics()
    print(f'   keys: {list(diag.keys())[:8]}')

    print('\n[9] get_auto_runner_status')
    from app.services.mirofish import auto_runner
    status = auto_runner.get_status()
    print(f'   phase: {status["phase"]}, today.triggers: {status["today"]["triggers"]}')

    print('\n[OK] 신규 9개 도구 모두 호출 가능 (응답 데이터 가용성은 환경별 차이)')


if __name__ == '__main__':
    main()

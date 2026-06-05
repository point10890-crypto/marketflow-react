"""스캐닝 시스템 전체 헬스 체크 — Alpha Scanner / Wave Screener / Jongga V2 / Auto-runner"""
import os, sys, json
from pathlib import Path
from datetime import datetime, timezone

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

NOW = datetime.now(timezone.utc)


def fmt_age(iso_str):
    if not iso_str:
        return 'N/A'
    try:
        dt = datetime.fromisoformat(str(iso_str).replace('Z', '+00:00'))
        delta = NOW - dt.astimezone(timezone.utc)
        s = int(delta.total_seconds())
        if s < 60: return f'{s}s ago'
        if s < 3600: return f'{s//60}m ago'
        if s < 86400: return f'{s//3600}h ago'
        return f'{s//86400}d ago'
    except Exception:
        return str(iso_str)


def fmt_mtime(path):
    if not path.exists():
        return 'MISSING'
    mt = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    delta = NOW - mt
    s = int(delta.total_seconds())
    age = f'{s}s' if s < 60 else f'{s//60}m' if s < 3600 else f'{s//3600}h' if s < 86400 else f'{s//86400}d'
    return f'{mt.strftime("%Y-%m-%d %H:%M:%S")} ({age} ago)'


print('=' * 70)
print('스캐닝 시스템 전체 헬스 체크')
print('=' * 70)

# 1) Alpha Scanner (실시간 30s 폴링)
print('\n[1] Alpha Scanner (30s 폴링 - KR 알파/리스크)')
try:
    from app.services.mirofish.alpha_scanner import get_scanner_schedule_status, read_latest_scanner_run, read_scanner_alert_state
    sched = get_scanner_schedule_status()
    latest = read_latest_scanner_run()
    alert = read_scanner_alert_state()
    print(f'  enabled       : {sched.get("enabled")}')
    print(f'  last_run_at   : {sched.get("last_run_at")} ({fmt_age(sched.get("last_run_at"))})')
    print(f'  candidate_count: {sched.get("candidate_count")}')
    print(f'  freshness     : {sched.get("freshness_status")}')
    print(f'  next_scheduled: {sched.get("next_scheduled_at")}')
    if latest:
        print(f'  latest run id : {latest.get("id")} candidates={len(latest.get("candidates") or [])}')
    print(f'  alerts.last_sent_at: {fmt_age((alert or {}).get("last_sent_at"))}')
except Exception as e:
    print(f'  ERROR: {type(e).__name__}: {e}')

# 2) Wave Screener (W/M 패턴 일일)
print('\n[2] Wave Pattern Screener (일일 W/M 패턴)')
p = ROOT / 'data' / 'wave' / 'wave_screener_latest.json'
print(f'  file mtime    : {fmt_mtime(p)}')
if p.exists():
    try:
        d = json.loads(p.read_text(encoding='utf-8'))
        print(f'  date_in_json  : {d.get("date")}')
        print(f'  updated_at    : {d.get("updated_at")}')
        print(f'  scan_count    : {d.get("scan_count")}')
        print(f'  signal_count  : {d.get("signal_count")}')
        sigs = d.get('signals') or []
        w = sum(1 for s in sigs if s.get('best_pattern', {}).get('pattern_class') == 'W')
        m = sum(1 for s in sigs if s.get('best_pattern', {}).get('pattern_class') == 'M')
        print(f'  W (Bullish)   : {w}')
        print(f'  M (Bearish)   : {m}')
    except Exception as e:
        print(f'  parse err: {e}')

# 3) Jongga V2 (종가베팅)
print('\n[3] Jongga V2 (종가베팅 V2 - 17점 채점)')
p = ROOT / 'data' / 'jongga_v2_latest.json'
print(f'  file mtime    : {fmt_mtime(p)}')
if p.exists():
    try:
        d = json.loads(p.read_text(encoding='utf-8'))
        print(f'  date          : {d.get("date")}')
        print(f'  updated_at    : {d.get("updated_at")}')
        print(f'  total_candidates: {d.get("total_candidates")}')
        print(f'  filtered_count: {d.get("filtered_count")}')
        signals = d.get('signals') or []
        print(f'  signals       : {len(signals)}')
        if signals:
            for s in signals[:3]:
                print(f'    {s.get("grade")} {s.get("stock_name")} score={s.get("score",{}).get("total")}')
    except Exception as e:
        print(f'  parse err: {e}')

# 4) Auto-Runner (Stage 2 자동 발사)
print('\n[4] Auto-Runner (Stage 2 자동 MCP)')
try:
    from app.services.mirofish import auto_runner
    s = auto_runner.get_status()
    print(f'  phase         : {s.get("phase")}')
    print(f'  paused        : {s.get("paused")}')
    print(f'  enabled       : {s.get("enabled")}')
    print(f'  last_check_at : {fmt_age(s.get("last_check_at"))}')
    print(f'  last_check_reason: {s.get("last_check_reason")}')
    print(f'  last_success_at  : {fmt_age(s.get("last_success_at"))}')
    today = s.get('today') or {}
    print(f'  today.checks  : {today.get("checks")}, triggers: {today.get("triggers")}, successes: {today.get("successes")}, failures: {today.get("failures")}')
    print(f'  today.cost    : ${today.get("est_cost_usd", 0):.3f}')
except Exception as e:
    print(f'  ERROR: {type(e).__name__}: {e}')

# 5) Leading Stocks Screener (주도주 LIVE)
print('\n[5] Leading Stocks (주도주 LIVE)')
p = ROOT / 'data' / 'screener_leading_latest.json'
print(f'  file mtime    : {fmt_mtime(p)}')
if p.exists():
    try:
        d = json.loads(p.read_text(encoding='utf-8'))
        print(f'  scan_at       : {d.get("scan_at") or d.get("updated_at")}')
        stocks = d.get('stocks') or d.get('results') or d.get('candidates') or []
        print(f'  stocks/results: {len(stocks)}')
    except Exception as e:
        print(f'  parse err: {e}')

# 6) Workflow (MCP TOP 3)
print('\n[6] MCP Workflow (Stage 2 - 5-agent GraphRAG)')
try:
    from app.services.mirofish.workflow import read_latest_workflow
    wf = read_latest_workflow()
    if wf:
        print(f'  id            : {wf.get("id")}')
        print(f'  status        : {wf.get("status")}')
        print(f'  created_at    : {wf.get("created_at")} ({fmt_age(wf.get("created_at"))})')
        print(f'  top3 count    : {len(wf.get("top3") or [])}')
        top3 = wf.get('top3') or []
        for i, t in enumerate(top3[:3], 1):
            cand = t.get('candidate') or {}
            print(f'    TOP {i}: {t.get("target") or cand.get("display_name")} score={t.get("final_score")}')
    else:
        print('  no workflow yet')
except Exception as e:
    print(f'  ERROR: {type(e).__name__}: {e}')

# 7) Pipeline Snapshot
print('\n[7] Pipeline Today Snapshot (시장+funnel+KPI)')
try:
    from app.services.mirofish.pipeline_overview import get_pipeline_today_snapshot
    snap = get_pipeline_today_snapshot()
    mkt = snap.get('market', {}).get('kr', {})
    fun = snap.get('funnel', {})
    print(f'  KR phase      : {mkt.get("phase")}')
    print(f'  KR gate       : {mkt.get("gate_label")}')
    print(f'  funnel        : scanner={fun.get("scanner_pool")} batch={fun.get("batch_new_candidates")} graphrag={fun.get("graphrag_uploaded")} top3={fun.get("top3_ready")}')
    print(f'  scanner today : {fun.get("scanner_runs_today")} runs')
    print(f'  alerts today  : {snap.get("alerts_today", {}).get("scanner_alerts_today")}')
except Exception as e:
    print(f'  ERROR: {type(e).__name__}: {e}')

print()
print('=' * 70)
print('헬스 체크 완료')
print('=' * 70)

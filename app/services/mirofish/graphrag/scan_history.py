"""MCP 스캔 종목 히스토리 + 성과 통합 모듈 (Phase G).

목적:
    - alpha_scanner 의 모든 run.json + MCP workflow 의 top3 outcomes 를
      symbol 단위로 집계하여 "어떤 종목이 몇 번 떴고, top3 진입 시 수익률이 어땠는가" 를 표시.
    - 단일 종목 (`/scan-history/<symbol>`) 상세 + 전체 성과 (`/scan-history-performance`).

Look-ahead safety:
    - outcomes.json 의 forward_return_pct 는 outcome_tracker.evaluate_result_outcome 이
      이미 entry_date 이후 close 만 사용해 계산함. 이 모듈은 read-only 집계만 수행.

I/O 비용:
    - scanner_runs/ 디렉토리에 1900+ 디렉토리, workflows/ 는 수십 개 수준.
    - 한 번 호출에 수십 MB JSON 파싱 → 30초 메모리 캐시 + threading.Lock 필수.
    - 동시 호출자가 캐시 미스 시 중복 파싱하지 않도록 lock 으로 직렬화.

응답 구조는 admin_mirofish_graphrag.py 라우트 docstring 과 mirofishApi.ts 타입 참조.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any

from app.services.mirofish.outcome_tracker import (
    WORKFLOWS_ROOT,
    read_workflow_outcomes,
    _infer_market,
)


# ── Paths ─────────────────────────────────────────────────────────────

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
SCANNER_RUNS_ROOT = os.path.join(REPO_ROOT, 'data', 'admin_mirofish', 'scanner_runs')


# ── Cache ─────────────────────────────────────────────────────────────
#
# 7,307 scanner_runs + 64 workflows 환경에서 cold cache build 가 ~70s 소요.
# 첫 호출은 build 비용 부담, 후속 호출은 30s TTL 만료 전에 반드시 hit 해야
# UI 폴링 (60s 간격) 에서 매번 새로 build 하는 것을 막을 수 있다.
# TTL 600초 (10분) — UI 가 자주 토글 (30/60/90일) 해도 캐시 hit 가능.

_CACHE_TTL_SEC = 600.0  # 10 minutes; ~70s cold build cost amortized
_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = threading.Lock()


def _cached(key: str, builder):
    """단순 TTL 캐시. 동시 미스는 lock 으로 직렬화 (동일 build 중복 방지)."""
    now = time.time()
    with _cache_lock:
        slot = _cache.get(key)
        if slot is not None:
            ts, data = slot
            if now - ts < _CACHE_TTL_SEC:
                return data
        data = builder()
        _cache[key] = (now, data)
        return data


def invalidate_cache() -> None:
    """테스트/수동 갱신용."""
    with _cache_lock:
        _cache.clear()


# ── Date helpers ──────────────────────────────────────────────────────

_SCANNER_DIR_RE = re.compile(r'^mfas_(\d{4})(\d{2})(\d{2})\d{6}_')
_WORKFLOW_DIR_RE = re.compile(r'^mcp_(\d{4})(\d{2})(\d{2})\d{6}_')


def _scanner_dir_date(name: str) -> str | None:
    m = _SCANNER_DIR_RE.match(name)
    if not m:
        return None
    return f'{m.group(1)}-{m.group(2)}-{m.group(3)}'


def _workflow_dir_date(name: str) -> str | None:
    m = _WORKFLOW_DIR_RE.match(name)
    if not m:
        return None
    return f'{m.group(1)}-{m.group(2)}-{m.group(3)}'


def _today_kst() -> str:
    return time.strftime('%Y-%m-%d', time.localtime())


def _date_diff_days(a: str, b: str) -> int:
    """Days between YYYY-MM-DD strings (a - b). 잘못된 형식은 0 반환."""
    try:
        da = datetime.strptime(a, '%Y-%m-%d')
        db = datetime.strptime(b, '%Y-%m-%d')
        return (da - db).days
    except (TypeError, ValueError):
        return 0


def _within_days(dir_date: str | None, days: int) -> bool:
    if not dir_date:
        return False
    today = _today_kst()
    return 0 <= _date_diff_days(today, dir_date) <= max(0, int(days))


def _normalize_symbol(value: Any) -> str:
    s = str(value or '').strip()
    digits = ''.join(ch for ch in s if ch.isdigit())
    if len(digits) == 6:
        return digits
    return s.upper()


def _safe_number(value: Any) -> float:
    try:
        if value in (None, ''):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# ── Disk I/O ──────────────────────────────────────────────────────────

def _read_json(path: str) -> dict[str, Any] | None:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _iter_recent_scanner_runs(days: int, limit_runs: int = 300):
    """최근 N일 분 scanner run.json 경로 yield (최신 우선, 최대 limit_runs).

    scanner_runs/ 가 7,000+ 디렉토리로 누적된 환경에서 매 호출마다
    전체 stat + JSON read 는 100s 초과 위험. 디렉토리명이
    ``mfas_YYYYMMDDhhmmss_*`` 패턴이라 string sort reverse 만으로 최신순
    순회 가능. limit_runs (기본 300) 도달 시 break.
    """
    if not os.path.isdir(SCANNER_RUNS_ROOT):
        return
    try:
        entries = os.listdir(SCANNER_RUNS_ROOT)
    except OSError:
        return
    # 최신 디렉토리부터 처리 (string sort reverse 가 곧 날짜 reverse)
    entries.sort(reverse=True)
    yielded = 0
    for name in entries:
        if not name.startswith('mfas_'):
            continue
        dir_date = _scanner_dir_date(name)
        if not dir_date:
            continue
        if not _within_days(dir_date, days):
            # 정렬된 순회에서 처음으로 윈도우 벗어났다면 그 이후도 모두 벗어남
            # → 안전한 조기 종료 (정규식 미매치 디렉토리만 위에서 continue 됨)
            break
        path = os.path.join(SCANNER_RUNS_ROOT, name, 'run.json')
        if os.path.isfile(path):
            yield name, dir_date, path
            yielded += 1
            if yielded >= limit_runs:
                break


def _iter_recent_workflows(days: int):
    """최근 N일 분 workflow.json + outcomes.json 경로 yield."""
    if not os.path.isdir(WORKFLOWS_ROOT):
        return
    try:
        entries = os.listdir(WORKFLOWS_ROOT)
    except OSError:
        return
    for name in entries:
        if name.startswith('_'):
            continue
        if not name.startswith('mcp_'):
            continue
        dir_date = _workflow_dir_date(name)
        if not _within_days(dir_date, days):
            continue
        wf_path = os.path.join(WORKFLOWS_ROOT, name, 'workflow.json')
        if os.path.isfile(wf_path):
            yield name, dir_date, wf_path


# ── Aggregation primitives ────────────────────────────────────────────

def _scan_entry(candidate: dict[str, Any], run_id: str, run_date: str) -> dict[str, Any]:
    """scanner candidate → 표준 scan entry."""
    price = candidate.get('price') if isinstance(candidate.get('price'), dict) else {}
    return {
        'date': str(price.get('date') or run_date or '')[:10],
        'scanner_run_id': run_id,
        'run_date': run_date,
        'rank': candidate.get('rank'),
        'symbol': _normalize_symbol(candidate.get('symbol')),
        'display_name': candidate.get('display_name') or candidate.get('name') or '',
        'market': candidate.get('market') or '',
        'alpha_score': _safe_number(candidate.get('alpha_score')),
        'risk_score': _safe_number(candidate.get('risk_score')),
        'ranking_score': _safe_number(candidate.get('ranking_score')),
        'action': str(candidate.get('action') or ''),
        'signal_quality': str(candidate.get('signal_quality') or ''),
        'strategy_tags': [
            str(tag) for tag in (candidate.get('strategy_tags') or [])
            if str(tag or '').strip()
        ][:12],
    }


def _workflow_entry(top_item: dict[str, Any], wf_id: str, wf_date: str,
                    outcome_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """workflow top3 item → 표준 workflow entry (outcome 결합)."""
    cand = top_item.get('candidate') if isinstance(top_item.get('candidate'), dict) else {}
    verdict = top_item.get('verdict') if isinstance(top_item.get('verdict'), dict) else {}
    symbol = _normalize_symbol(top_item.get('symbol') or cand.get('symbol'))
    outcome = outcome_map.get(symbol) or {}

    return {
        'date': wf_date,
        'workflow_id': wf_id,
        'symbol': symbol,
        'display_name': top_item.get('target') or cand.get('display_name') or cand.get('name') or symbol,
        'market': top_item.get('market') or cand.get('market') or '',
        'rank': cand.get('rank'),
        'final_score': _safe_number(top_item.get('final_score')),
        'verdict': {
            'action': str(verdict.get('action') or ''),
            'confidence_pct': _safe_number(verdict.get('confidence_pct')),
            'target_display': verdict.get('target') or '',
        },
        'outcome': {
            'status': outcome.get('status') or 'unknown',
            'hit': outcome.get('hit'),
            'forward_return_pct': outcome.get('forward_return_pct'),
            'entry_date': outcome.get('entry_date'),
            'primary_horizon_days': outcome.get('primary_horizon_days'),
            'max_forward_return_pct': outcome.get('max_forward_return_pct'),
            'max_drawdown_pct': outcome.get('max_drawdown_pct'),
            'stopped': outcome.get('stopped'),
        },
    }


def _build_outcome_map_for_workflow(wf_id: str) -> dict[str, dict[str, Any]]:
    """워크플로우의 outcomes.json items 를 symbol → item 으로 map.

    read_workflow_outcomes 는 일부 invalid id 에서 ValueError, 또는 lazy
    recompute 로 daily_prices.csv (150MB) 재로딩 → 100s 초과 사례 있음.
    scan_history 는 best-effort aggregation 이므로 outcome 누락은 빈 dict
    으로 처리하고 계속 진행 (Cloudflare 100s timeout 회피).
    """
    try:
        outcomes = read_workflow_outcomes(wf_id)
    except (ValueError, OSError, KeyError, RuntimeError):
        return {}
    except Exception:
        return {}
    if not isinstance(outcomes, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for it in (outcomes.get('items') or []):
        if not isinstance(it, dict):
            continue
        sym = _normalize_symbol(it.get('symbol'))
        if sym:
            out[sym] = it
    return out


def _collect_raw_data(days: int):
    """디스크 read — scanner_runs + workflows + outcomes."""
    scans: list[dict[str, Any]] = []
    workflows: list[dict[str, Any]] = []
    workflow_count = 0

    # scanner candidates
    for run_id, dir_date, path in _iter_recent_scanner_runs(days):
        run = _read_json(path)
        if not run:
            continue
        candidates = run.get('candidates') if isinstance(run.get('candidates'), list) else []
        for c in candidates:
            if isinstance(c, dict):
                scans.append(_scan_entry(c, run_id, dir_date or ''))

    # workflow top3 + outcomes
    for wf_id, dir_date, path in _iter_recent_workflows(days):
        wf = _read_json(path)
        if not wf:
            continue
        workflow_count += 1
        top3 = wf.get('top3') if isinstance(wf.get('top3'), list) else []
        if not top3:
            # fall back to analysis_runs
            top3 = wf.get('analysis_runs') if isinstance(wf.get('analysis_runs'), list) else []
        outcome_map = _build_outcome_map_for_workflow(wf_id)
        wf_date = (wf.get('created_at') or '')[:10] or dir_date or ''
        for item in top3:
            if isinstance(item, dict):
                workflows.append(_workflow_entry(item, wf_id, wf_date, outcome_map))

    return scans, workflows, workflow_count


# ── Public API ────────────────────────────────────────────────────────

def get_scan_history(
    days: int = 30,
    limit_symbols: int = 100,
    min_alpha: float = 0,
) -> dict[str, Any]:
    """모든 스캐너 run + 워크플로우 outcomes 를 symbol 별 group 으로 통합.

    Args:
        days: 조회 윈도우 (기본 30일, KST 기준).
        limit_symbols: 상위 N 종목만 반환 (scan_count desc, 그 다음 alpha_avg desc).
        min_alpha: alpha_avg 가 이 값 미만이면 제외 (기본 0 = 필터 없음).

    Returns:
        items[] (종목별 집계), summary (전체 hit_rate 등), total counts.
        scan_count 가 0 인 종목 (workflow 만 있고 scanner 직접 출현 X) 도 포함.
    """
    days = max(1, min(int(days or 30), 365))
    limit_symbols = max(1, min(int(limit_symbols or 100), 1000))
    min_alpha = float(min_alpha or 0)
    cache_key = f'history:{days}:{limit_symbols}:{min_alpha}'

    def _build():
        scans, workflows, workflow_count = _collect_raw_data(days)

        # symbol 별 집계
        grouped: dict[str, dict[str, Any]] = {}
        for s in scans:
            sym = s['symbol']
            if not sym:
                continue
            slot = grouped.setdefault(sym, _empty_group(sym, s.get('display_name'), s.get('market')))
            slot['scan_count'] += 1
            d = s['date']
            if d:
                if not slot['scan_first_date'] or d < slot['scan_first_date']:
                    slot['scan_first_date'] = d
                if not slot['scan_last_date'] or d > slot['scan_last_date']:
                    slot['scan_last_date'] = d
            alpha = s['alpha_score']
            slot['_alpha_sum'] += alpha
            slot['_alpha_n'] += 1
            slot['alpha_max'] = max(slot['alpha_max'], alpha) if slot['alpha_max'] is not None else alpha
            slot['alpha_min'] = min(slot['alpha_min'], alpha) if slot['alpha_min'] is not None else alpha
            slot['_risk_sum'] += s['risk_score']
            for tag in s['strategy_tags']:
                slot['_tag_set'].add(tag)
            if s['display_name'] and not slot['display_name']:
                slot['display_name'] = s['display_name']
            if s['market'] and not slot['market']:
                slot['market'] = s['market']

        for w in workflows:
            sym = w['symbol']
            if not sym:
                continue
            slot = grouped.setdefault(sym, _empty_group(sym, w.get('display_name'), w.get('market')))
            slot['workflow_count'] += 1
            action = w['verdict']['action'] or 'UNKNOWN'
            slot['verdict_actions'][action] = slot['verdict_actions'].get(action, 0) + 1
            slot['last_target_display'] = w['verdict']['target_display'] or slot['last_target_display']

            outc = w['outcome']
            status = outc.get('status') or 'unknown'
            hit = outc.get('hit')
            ret = outc.get('forward_return_pct')

            if status in ('evaluated', 'partial'):
                slot['_outcome']['evaluated_count'] += 1
                if hit is True:
                    slot['_outcome']['hit_count'] += 1
                elif hit is False:
                    slot['_outcome']['miss_count'] += 1
                if ret is not None:
                    slot['_outcome']['_returns'].append(_safe_number(ret))
            elif status == 'pending':
                slot['_outcome']['pending_count'] += 1
            else:
                slot['_outcome']['neutral_count'] += 1

            if w['display_name'] and not slot['display_name']:
                slot['display_name'] = w['display_name']
            if w['market'] and not slot['market']:
                slot['market'] = w['market']

        # finalize items
        items: list[dict[str, Any]] = []
        eval_total = 0
        hit_total = 0
        miss_total = 0
        return_pool: list[float] = []
        for sym, slot in grouped.items():
            alpha_avg = slot['_alpha_sum'] / slot['_alpha_n'] if slot['_alpha_n'] else 0.0
            if alpha_avg < min_alpha:
                continue
            risk_avg = slot['_risk_sum'] / slot['_alpha_n'] if slot['_alpha_n'] else 0.0
            o = slot['_outcome']
            returns = o['_returns']
            evaluated = o['evaluated_count']
            outcome = {
                'hit_count': o['hit_count'],
                'miss_count': o['miss_count'],
                'pending_count': o['pending_count'],
                'neutral_count': o['neutral_count'],
                'evaluated_count': evaluated,
                'hit_rate': round(o['hit_count'] / evaluated, 4) if evaluated else None,
                'avg_forward_return_pct': round(sum(returns) / len(returns), 2) if returns else None,
                'best_return_pct': round(max(returns), 2) if returns else None,
                'worst_return_pct': round(min(returns), 2) if returns else None,
            }
            eval_total += evaluated
            hit_total += o['hit_count']
            miss_total += o['miss_count']
            return_pool.extend(returns)

            items.append({
                'symbol': sym,
                'display_name': slot['display_name'] or sym,
                'market': slot['market'],
                'scan_count': slot['scan_count'],
                'scan_first_date': slot['scan_first_date'],
                'scan_last_date': slot['scan_last_date'],
                'alpha_avg': round(alpha_avg, 2),
                'alpha_max': round(slot['alpha_max'] or 0.0, 2),
                'alpha_min': round(slot['alpha_min'] or 0.0, 2),
                'risk_avg': round(risk_avg, 2),
                'strategy_tags': sorted(slot['_tag_set'])[:8],
                'workflow_count': slot['workflow_count'],
                'verdict_actions': slot['verdict_actions'],
                'outcome': outcome,
                'last_target_display': slot['last_target_display'] or None,
            })

        # 정렬: scan_count desc → alpha_avg desc → symbol asc
        items.sort(key=lambda x: (-x['scan_count'], -x['alpha_avg'], x['symbol']))
        items = items[:limit_symbols]

        summary = {
            'evaluated_count': eval_total,
            'hit_count': hit_total,
            'miss_count': miss_total,
            'hit_rate': round(hit_total / eval_total, 4) if eval_total else None,
            'avg_return_pct': round(sum(return_pool) / len(return_pool), 2) if return_pool else None,
        }
        return {
            'window_days': days,
            'min_alpha': min_alpha,
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'total_unique_symbols': len(grouped),
            'total_scans': len(scans),
            'total_workflows': workflow_count,
            'returned_items': len(items),
            'items': items,
            'summary': summary,
            'lookahead_safe': True,
        }

    return _cached(cache_key, _build)


def get_symbol_history(symbol: str, limit_days: int = 180) -> dict[str, Any]:
    """단일 종목의 전체 출현 history.

    Args:
        symbol: 6자리 KR 코드 또는 US ticker.
        limit_days: 최근 N일 검색 (기본 180).

    Returns:
        scans[] (모든 scanner 등장), workflows[] (top3 진입), aggregate.
    """
    target = _normalize_symbol(symbol)
    if not target:
        return {
            'symbol': '',
            'error': 'invalid symbol',
            'scans': [],
            'workflows': [],
        }
    limit_days = max(1, min(int(limit_days or 180), 730))
    cache_key = f'symbol:{target}:{limit_days}'

    def _build():
        scans, workflows, _ = _collect_raw_data(limit_days)
        my_scans = [s for s in scans if s['symbol'] == target]
        my_wfs = [w for w in workflows if w['symbol'] == target]
        my_scans.sort(key=lambda x: (x['date'] or '', x.get('scanner_run_id') or ''), reverse=True)
        my_wfs.sort(key=lambda x: (x['date'] or '', x.get('workflow_id') or ''), reverse=True)

        display_name = ''
        market = ''
        for s in my_scans:
            display_name = display_name or s.get('display_name') or ''
            market = market or s.get('market') or ''
            if display_name and market:
                break
        if not display_name:
            for w in my_wfs:
                display_name = display_name or w.get('display_name') or ''
                market = market or w.get('market') or ''
                if display_name and market:
                    break

        # aggregate
        evaluated_returns = []
        hit_count = 0
        for w in my_wfs:
            outc = w['outcome']
            if outc.get('status') in ('evaluated', 'partial'):
                ret = outc.get('forward_return_pct')
                if ret is not None:
                    evaluated_returns.append(_safe_number(ret))
                if outc.get('hit') is True:
                    hit_count += 1
        evaluated_n = len(evaluated_returns)

        return {
            'symbol': target,
            'display_name': display_name or target,
            'market': market or _infer_market(target),
            'window_days': limit_days,
            'scans': my_scans,
            'workflows': my_wfs,
            'aggregate': {
                'total_scans': len(my_scans),
                'total_workflows': len(my_wfs),
                'evaluated_count': evaluated_n,
                'hit_count': hit_count,
                'outcome_hit_rate': round(hit_count / evaluated_n, 4) if evaluated_n else None,
                'avg_forward_return_pct': round(
                    sum(evaluated_returns) / evaluated_n, 2
                ) if evaluated_n else None,
            },
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'lookahead_safe': True,
        }

    return _cached(cache_key, _build)


def get_performance_summary(days: int = 60) -> dict[str, Any]:
    """전체 통계 + 그룹별 breakdown.

    Args:
        days: 조회 윈도우 (기본 60일).

    Returns:
        전체 hit_rate / avg_return / IC + by_market / by_strategy_tag /
        by_verdict_action / by_alpha_bucket / top_performers.
    """
    days = max(1, min(int(days or 60), 365))
    cache_key = f'perf:{days}'

    def _build():
        scans, workflows, workflow_count = _collect_raw_data(days)

        # symbol 별 → alpha_avg (scanner 측 평균) 와 outcome 매핑
        alpha_by_symbol: dict[str, list[float]] = {}
        strategy_tags_by_symbol: dict[str, set] = {}
        market_by_symbol: dict[str, str] = {}
        display_name_by_symbol: dict[str, str] = {}
        for s in scans:
            sym = s['symbol']
            if not sym:
                continue
            alpha_by_symbol.setdefault(sym, []).append(s['alpha_score'])
            tags = strategy_tags_by_symbol.setdefault(sym, set())
            for tag in s['strategy_tags']:
                tags.add(tag)
            if s.get('market'):
                market_by_symbol.setdefault(sym, s['market'])
            if s.get('display_name'):
                display_name_by_symbol.setdefault(sym, s['display_name'])

        # outcome aggregation
        evaluated_items: list[dict[str, Any]] = []
        pending_count = 0
        for w in workflows:
            outc = w['outcome']
            status = outc.get('status')
            ret = outc.get('forward_return_pct')
            hit = outc.get('hit')
            verdict_action = w['verdict']['action'] or 'UNKNOWN'
            sym = w['symbol']
            if not market_by_symbol.get(sym) and w.get('market'):
                market_by_symbol[sym] = w['market']
            if not display_name_by_symbol.get(sym) and w.get('display_name'):
                display_name_by_symbol[sym] = w['display_name']
            if status in ('evaluated', 'partial') and ret is not None:
                evaluated_items.append({
                    'symbol': sym,
                    'forward_return_pct': _safe_number(ret),
                    'hit': bool(hit is True),
                    'verdict_action': verdict_action,
                    'alpha_avg': sum(alpha_by_symbol.get(sym, [0.0])) / max(1, len(alpha_by_symbol.get(sym, [0.0]))),
                    'tags': list(strategy_tags_by_symbol.get(sym, set())),
                    'market': market_by_symbol.get(sym) or _infer_market(sym),
                })
            else:
                pending_count += 1

        total_signals = len(workflows)
        evaluated_n = len(evaluated_items)
        hits = [it for it in evaluated_items if it['hit']]
        returns = [it['forward_return_pct'] for it in evaluated_items]
        hit_rate = round(len(hits) / evaluated_n, 4) if evaluated_n else None
        avg_return = round(sum(returns) / evaluated_n, 2) if evaluated_n else None

        # IC (Pearson alpha vs forward_return) — 표본 3 이상일 때만 계산
        ic = None
        if evaluated_n >= 3:
            xs = [it['alpha_avg'] for it in evaluated_items]
            ys = returns
            mx = sum(xs) / len(xs)
            my = sum(ys) / len(ys)
            dx = [x - mx for x in xs]
            dy = [y - my for y in ys]
            num = sum(a * b for a, b in zip(dx, dy))
            denx = sum(a * a for a in dx) ** 0.5
            deny = sum(b * b for b in dy) ** 0.5
            if denx > 0 and deny > 0:
                ic = round(num / (denx * deny), 4)

        # by_market / by_strategy_tag / by_verdict_action / by_alpha_bucket
        by_market = _group_stats(evaluated_items, lambda it: it['market'] or 'UNKNOWN')
        by_verdict_action = _group_stats(evaluated_items, lambda it: it['verdict_action'])
        # tag: each item belongs to multiple tags
        by_tag: dict[str, list[dict[str, Any]]] = {}
        for it in evaluated_items:
            for tag in it['tags']:
                by_tag.setdefault(tag, []).append(it)
        by_strategy_tag = {
            tag: _stats_for_group(items) for tag, items in by_tag.items()
            if len(items) >= 2
        }
        # alpha buckets
        def _bucket(a: float) -> str:
            if a >= 80:
                return '80+'
            if a >= 70:
                return '70-80'
            if a >= 60:
                return '60-70'
            if a >= 50:
                return '50-60'
            return '<50'
        by_alpha_bucket = _group_stats(evaluated_items, lambda it: _bucket(it['alpha_avg']))

        # top performers (workflow 진입했고 hit_rate ≥ baseline 인 종목)
        # symbol 별 묶어서 평균
        by_symbol: dict[str, list[dict[str, Any]]] = {}
        for it in evaluated_items:
            by_symbol.setdefault(it['symbol'], []).append(it)
        top_performers = []
        for sym, items in by_symbol.items():
            n = len(items)
            if n < 1:
                continue
            sym_hits = sum(1 for x in items if x['hit'])
            sym_avg = sum(x['forward_return_pct'] for x in items) / n
            top_performers.append({
                'symbol': sym,
                'display_name': display_name_by_symbol.get(sym) or sym,
                'market': market_by_symbol.get(sym) or _infer_market(sym),
                'n': n,
                'hit_rate': round(sym_hits / n, 4),
                'avg_return_pct': round(sym_avg, 2),
            })
        top_performers.sort(
            key=lambda x: (-x['hit_rate'], -x['avg_return_pct'], -x['n']),
        )
        top_performers = top_performers[:5]

        return {
            'service': 'mirofish-graphrag-scan-performance',
            'window_days': days,
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'total_signals': total_signals,
            'evaluated': evaluated_n,
            'pending': pending_count,
            'hit_count': len(hits),
            'miss_count': evaluated_n - len(hits),
            'hit_rate': hit_rate,
            'avg_return_pct': avg_return,
            'ic_signal_to_return': ic,
            'workflow_count_scanned': workflow_count,
            'scanner_runs_scanned': len({s['scanner_run_id'] for s in scans}),
            'by_market': by_market,
            'by_strategy_tag': by_strategy_tag,
            'by_verdict_action': by_verdict_action,
            'by_alpha_bucket': by_alpha_bucket,
            'top_performers': top_performers,
            'lookahead_safe': True,
        }

    return _cached(cache_key, _build)


# ── Helpers ──────────────────────────────────────────────────────────

def _empty_group(symbol: str, display_name: str | None, market: str | None) -> dict[str, Any]:
    return {
        'symbol': symbol,
        'display_name': display_name or '',
        'market': market or '',
        'scan_count': 0,
        'scan_first_date': '',
        'scan_last_date': '',
        '_alpha_sum': 0.0,
        '_alpha_n': 0,
        '_risk_sum': 0.0,
        'alpha_max': None,
        'alpha_min': None,
        '_tag_set': set(),
        'workflow_count': 0,
        'verdict_actions': {},
        '_outcome': {
            'evaluated_count': 0,
            'hit_count': 0,
            'miss_count': 0,
            'pending_count': 0,
            'neutral_count': 0,
            '_returns': [],
        },
        'last_target_display': '',
    }


def _stats_for_group(items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        return {'n': 0, 'hit_rate': None, 'avg_return_pct': None}
    n = len(items)
    hits = sum(1 for it in items if it['hit'])
    returns = [it['forward_return_pct'] for it in items]
    return {
        'n': n,
        'hit_rate': round(hits / n, 4),
        'avg_return_pct': round(sum(returns) / n, 2),
    }


def _group_stats(items: list[dict[str, Any]], key_fn) -> dict[str, dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for it in items:
        k = key_fn(it) or 'UNKNOWN'
        buckets.setdefault(k, []).append(it)
    return {k: _stats_for_group(v) for k, v in buckets.items() if v}

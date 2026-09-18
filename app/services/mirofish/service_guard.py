# -*- coding: utf-8 -*-
"""AI Brain 서비스 가드 — 알파 스캐너 · AI 펀드매니저(Goodrich) · 판단 조회 지속성.

인프라 생존(플라스크/스케줄러 워치독, diagnostics)은 다른 층이 본다. 여기는
"구독자가 지금 이 기능을 쓸 수 있는가"만 판정한다 (2026-09-01 서비스 개시).

원칙
- 읽기전용 + 프로브. 스캔·발송·주문을 트리거하지 않는다(판단 프로브의 캐시 워밍 제외).
- 체커 하나의 예외가 가드 전체를 죽이지 않는다 — 예외는 그 서비스의 fail 로 환산.
- 알림은 실제 장애(→fail) 진입 때만 보낸다. warn/ok/복구와 동일 fail 지속은 기록만 한다.
- 발송 함수는 주입받는다(send_fn). 이 모듈은 텔레그램을 모른다.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from app.utils.atomic_json import write_json_atomic

logger = logging.getLogger(__name__)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
GUARD_ROOT = os.path.join(REPO_ROOT, 'data', 'admin_mirofish')
LATEST_PATH = os.path.join(GUARD_ROOT, 'service_guard_latest.json')
HISTORY_PATH = os.path.join(GUARD_ROOT, 'service_guard_history.jsonl')
STATE_PATH = os.path.join(GUARD_ROOT, 'service_guard_state.json')

KST = timezone(timedelta(hours=9))
SEVERITY = {'ok': 0, 'warn': 1, 'fail': 2}

SERVICE_LABEL = {'scanner': '알파 스캐너', 'goodrich': 'AI 펀드매니저', 'decision': '판단 조회'}


def _now_kst(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(KST)
    if now.tzinfo is None:
        return now.replace(tzinfo=KST)
    return now.astimezone(KST)


def _is_krx_trading_day(now: datetime) -> bool:
    """KRX 영업일 여부 — 공휴일·임시휴장(설·추석·근로자의날 등)은 주말과 동일 취급."""
    try:
        from app.services.kis_screener import _is_kr_trading_day
        return bool(_is_kr_trading_day(now))
    except Exception:  # noqa: BLE001 — 휴일 판정 실패는 평일로 간주(fail-open)
        return True


def _market_session(now: datetime) -> bool:
    """거래일 09:00~16:30 KST — 산출물이 갱신되고 있어야 하는 시간대. 휴장일은 장외."""
    if now.weekday() >= 5 or not _is_krx_trading_day(now):
        return False
    minutes = now.hour * 60 + now.minute
    return 9 * 60 <= minutes <= 16 * 60 + 30


def _age_hours(ts: float, now: datetime) -> float:
    return max(0.0, now.timestamp() - ts) / 3600.0


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, '') or default)
    except ValueError:
        return default


# ─── 체커 ───────────────────────────────────────────────────

def check_scanner(now: datetime | None = None) -> dict[str, Any]:
    """최신 run 신선도 + 모니터 상태. 장중 90분/240분, 장외 3일/7일 기준."""
    from app.services.mirofish import alpha_scanner

    now = _now_kst(now)
    paths = alpha_scanner._latest_scanner_run_paths()
    if not paths:
        return {'status': 'fail', 'detail': {'reason': 'no_scanner_runs'}}
    try:
        age_h = _age_hours(os.path.getmtime(paths[0]), now)
    except OSError as exc:
        return {'status': 'fail', 'detail': {'reason': f'latest_run_unreadable: {exc}'}}

    in_session = _market_session(now)
    if in_session:
        warn_h, fail_h = _env_float('AIBRAIN_SCANNER_WARN_H', 1.5), _env_float('AIBRAIN_SCANNER_FAIL_H', 4)
        # 개장 직후엔 전일 세션 산출물이 최신인 게 정상 — 지연은 오늘 09:00 기준으로 잰다.
        # (밤새 쌓인 나이로 매 아침 false FAIL/복구 알림 쌍이 나가는 것을 막는다)
        session_open = now.replace(hour=9, minute=0, second=0, microsecond=0)
        stale_h = min(age_h, max(0.0, (now - session_open).total_seconds() / 3600.0))
    else:
        warn_h, fail_h = _env_float('AIBRAIN_SCANNER_OFFHOURS_WARN_H', 72), _env_float('AIBRAIN_SCANNER_OFFHOURS_FAIL_H', 168)
        stale_h = age_h
    status = 'fail' if stale_h > fail_h else ('warn' if stale_h > warn_h else 'ok')

    detail: dict[str, Any] = {'latest_run_age_h': round(age_h, 2), 'stale_h': round(stale_h, 2),
                              'warn_h': warn_h, 'fail_h': fail_h, 'market_session': in_session}
    try:
        monitor = alpha_scanner.read_scanner_monitor_state()
        detail['monitor'] = {k: monitor.get(k) for k in ('last_status', 'blocked_reason', 'updated_at')
                             if monitor.get(k) is not None}
    except Exception as exc:  # noqa: BLE001 — 모니터 상태는 참고 정보다
        detail['monitor_error'] = f'{type(exc).__name__}'
    return {'status': status, 'detail': detail}


def check_goodrich(now: datetime | None = None) -> dict[str, Any]:
    """goodrich-tradingos 응답성 + 원장 신선도."""
    from app.services.mirofish import goodrich_client, goodrich_ledger

    now = _now_kst(now)
    detail: dict[str, Any] = {}
    status = 'ok'

    t0 = time.perf_counter()
    try:
        goodrich_client.get_detection_history(limit=1)
        detail['service_ms'] = int((time.perf_counter() - t0) * 1000)
    except goodrich_client.GoodrichServiceError as exc:
        detail['service_error'] = str(exc)
        detail['service_status_code'] = getattr(exc, 'status_code', None)
        status = 'fail'
    except Exception as exc:  # noqa: BLE001
        detail['service_error'] = f'{type(exc).__name__}: {exc}'
        status = 'fail'

    try:
        entries = goodrich_ledger.read_ledger() or []
        detail['ledger_entries'] = len(entries)
        last_iso = None
        if entries:
            last = entries[-1]
            # detected_at 이 실제 기록 시각 — date-only 인 entry_date 가 먼저 잡히면
            # 자정 기준으로 나이가 최대 24h 과장돼 매일 아침 거짓 warn 이 난다 (2026-09-03 실측 33.3h)
            for key in ('recorded_at', 'generated_at', 'detected_at', 'as_of', 'entry_date', 'date'):
                if last.get(key):
                    last_iso = str(last[key])
                    break
        if last_iso:
            try:
                last_dt = datetime.fromisoformat(last_iso.replace('Z', '+00:00'))
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=KST)
                ledger_age_h = (now.astimezone(timezone.utc) - last_dt.astimezone(timezone.utc)).total_seconds() / 3600
                detail['ledger_age_h'] = round(ledger_age_h, 1)
                # 주말·휴장 고려: 영업일 감각으로 3일까지는 warn 만.
                if ledger_age_h > _env_float('AIBRAIN_GOODRICH_LEDGER_FAIL_H', 96):
                    status = max_status(status, 'fail')
                elif ledger_age_h > _env_float('AIBRAIN_GOODRICH_LEDGER_WARN_H', 30):
                    status = max_status(status, 'warn')
            except ValueError:
                detail['ledger_age_h'] = None
        elif not entries:
            status = max_status(status, 'warn')
            detail['ledger_note'] = 'empty'
    except Exception as exc:  # noqa: BLE001
        detail['ledger_error'] = f'{type(exc).__name__}: {exc}'
        status = max_status(status, 'warn')

    return {'status': status, 'detail': detail}


def check_decision(now: datetime | None = None, *, probe_symbol: str | None = None) -> dict[str, Any]:
    """판단 조회 합성 프로브 — 계산 지연·최다 소요 소스·캐시 쓰기까지 실측.

    프로브 결과는 실제 캐시에 저장한다(해당 심볼의 워밍을 겸함) — 읽기전용 원칙의
    유일한 예외이며, 사용자 요청과 동일한 산출물이라 부작용이 아니다.
    """
    from app.services.mirofish import decision_brief, decision_cache

    now = _now_kst(now)
    symbol = probe_symbol or (hot_symbols(limit=1) or ['005930'])[0]
    warn_s = _env_float('AIBRAIN_DECISION_PROBE_WARN_S', 5)
    fail_s = _env_float('AIBRAIN_DECISION_PROBE_FAIL_S', 20)

    t0 = time.perf_counter()
    try:
        payload = decision_brief.build_decision_brief(symbol)
    except Exception as exc:  # noqa: BLE001
        return {'status': 'fail', 'detail': {'probe_symbol': symbol,
                                             'probe_error': f'{type(exc).__name__}: {exc}'}}
    probe_s = time.perf_counter() - t0

    timings = payload.get('timings_ms') or {}
    slowest = max(((k, v) for k, v in timings.items() if k != 'total'),
                  key=lambda kv: kv[1], default=(None, 0))
    status = 'fail' if probe_s > fail_s else ('warn' if probe_s > warn_s else 'ok')
    detail: dict[str, Any] = {'probe_symbol': symbol, 'probe_s': round(probe_s, 2),
                              'warn_s': warn_s, 'fail_s': fail_s,
                              'slowest_source': slowest[0], 'slowest_ms': slowest[1]}

    try:
        decision_cache.cache_put('brief', symbol, payload)
        detail['cache_write'] = True
    except Exception as exc:  # noqa: BLE001
        detail['cache_write'] = False
        detail['cache_error'] = f'{type(exc).__name__}: {exc}'
        status = max_status(status, 'warn')
    return {'status': status, 'detail': detail}


def max_status(a: str, b: str) -> str:
    return a if SEVERITY.get(a, 0) >= SEVERITY.get(b, 0) else b


CHECKERS: dict[str, Callable[..., dict[str, Any]]] = {
    'scanner': check_scanner,
    'goodrich': check_goodrich,
    'decision': check_decision,
}


# ─── 핫셋 / 프리웜 ──────────────────────────────────────────

def hot_symbols(limit: int = 12) -> list[str]:
    """구독자가 오늘 조회할 확률이 높은 심볼 — 스캐너 후보 + Goodrich 원장 + 주도주 S/A."""
    out: list[str] = []

    def _add(code: Any) -> None:
        c = str(code or '').strip()
        if c and c not in out:
            out.append(c)

    try:
        from app.services.mirofish.alpha_scanner import read_latest_scanner_candidates
        for cand in (read_latest_scanner_candidates(limit=10) or {}).get('candidates') or []:
            _add(cand.get('symbol'))
    except Exception:  # noqa: BLE001
        pass
    try:
        from app.services.mirofish import goodrich_ledger
        for entry in (goodrich_ledger.read_ledger() or [])[-10:]:
            for pick in entry.get('picks') or ([entry] if entry.get('symbol') else []):
                _add(pick.get('symbol') or pick.get('code'))
    except Exception:  # noqa: BLE001
        pass
    try:
        from app.services.kis_screener import load_latest
        for row in (load_latest() or {}).get('results') or []:
            if row.get('grade') in ('S', 'A'):
                _add(row.get('code'))
    except Exception:  # noqa: BLE001
        pass
    return out[: max(1, int(limit))]


def prewarm_decision_cache(limit: int = 12) -> dict[str, Any]:
    """핫셋을 미리 계산해 일간 캐시에 넣는다 — 구독자의 '첫 조회 수십 초'를 소멸시킨다."""
    from app.services.mirofish import decision_brief, decision_cache

    warmed: list[dict[str, Any]] = []
    skipped: list[str] = []
    errors: dict[str, str] = {}
    for symbol in hot_symbols(limit=limit):
        try:
            if decision_cache.cache_get('brief', symbol) is not None:
                skipped.append(symbol)
                continue
            t0 = time.perf_counter()
            payload = decision_brief.build_decision_brief(symbol)
            decision_cache.cache_put('brief', symbol, payload)
            warmed.append({'symbol': symbol, 'ms': int((time.perf_counter() - t0) * 1000)})
        except Exception as exc:  # noqa: BLE001 — 한 종목 실패가 프리웜을 멈추지 않는다
            errors[symbol] = f'{type(exc).__name__}: {exc}'
    return {'generated_at': datetime.now(KST).isoformat(timespec='seconds'),
            'warmed': warmed, 'skipped': skipped, 'errors': errors}


# ─── 가드 실행 + 실패 진입 알림 ─────────────────────────────

def _read_state() -> dict[str, Any]:
    try:
        with open(STATE_PATH, encoding='utf-8') as fp:
            data = json.load(fp)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _alert_lines(service: str, result: dict[str, Any]) -> str:
    label = SERVICE_LABEL.get(service, service)
    detail = result.get('detail') or {}
    keys = ('reason', 'probe_s', 'slowest_source', 'latest_run_age_h', 'ledger_age_h',
            'service_error', 'probe_error', 'cache_error')
    parts = [f'{k}={detail[k]}' for k in keys if detail.get(k) is not None]
    return f"{label}: {result.get('status', '?').upper()}" + (f" ({', '.join(parts)})" if parts else '')


def run_guard(send_fn: Callable[[str], Any] | None = None, *, now: datetime | None = None) -> dict[str, Any]:
    now = _now_kst(now)
    services: dict[str, dict[str, Any]] = {}
    for name, checker in CHECKERS.items():
        t0 = time.perf_counter()
        try:
            result = checker(now)
        except Exception as exc:  # noqa: BLE001 — 체커 예외 = 그 서비스 fail
            result = {'status': 'fail', 'detail': {'checker_error': f'{type(exc).__name__}: {exc}'}}
        result['checked_ms'] = int((time.perf_counter() - t0) * 1000)
        services[name] = result

    overall = 'ok'
    for result in services.values():
        overall = max_status(overall, result.get('status', 'fail'))

    payload = {'generated_at': now.isoformat(timespec='seconds'), 'overall': overall, 'services': services}
    try:
        os.makedirs(GUARD_ROOT, exist_ok=True)
        write_json_atomic(LATEST_PATH, payload)
        with open(HISTORY_PATH, 'a', encoding='utf-8') as fp:
            fp.write(json.dumps({'ts': payload['generated_at'], 'overall': overall,
                                 'statuses': {k: v.get('status') for k, v in services.items()}},
                                ensure_ascii=False) + '\n')
    except OSError as exc:
        logger.warning('service guard persist failed: %s', exc)

    _emit_transitions(services, send_fn, now)
    return payload


def _emit_transitions(services: dict[str, dict[str, Any]],
                      send_fn: Callable[[str], Any] | None, now: datetime) -> None:
    state = _read_state()
    changed = False
    lines_alert: list[str] = []
    alerted_names: list[str] = []

    for name, result in services.items():
        status = result.get('status', 'fail')
        prev = state.get(name) or {}
        prev_status = prev.get('status', 'ok')
        alerted_at = float(prev.get('alerted_at') or 0)

        if status == 'fail' and (prev_status != 'fail' or alerted_at <= 0):
            lines_alert.append(_alert_lines(name, result))
            alerted_names.append(name)
            # alerted_at 은 실제 발송 성공 후에만 찍는다 — 무발송(send_fn=None) 실행이나
            # 발송 실패가 1회성 전이 알림을 소모해 진짜 알림을 억누르면 안 된다.
            state[name] = {'status': status, 'alerted_at': alerted_at}
            changed = True
        elif status != prev_status:
            state[name] = {'status': status, 'alerted_at': 0}
            changed = True

    def _persist() -> None:
        try:
            os.makedirs(GUARD_ROOT, exist_ok=True)
            write_json_atomic(STATE_PATH, state)
        except OSError:
            pass

    if changed:
        _persist()
    if send_fn is None:
        return
    if lines_alert:
        result = send_fn('🛡 AI Brain 서비스 가드\n' + '\n'.join(lines_alert))
        if result is False:
            return
        for name in alerted_names:
            entry = dict(state.get(name) or {})
            entry['alerted_at'] = now.timestamp()
            state[name] = entry
        _persist()


def read_latest() -> dict[str, Any] | None:
    try:
        with open(LATEST_PATH, encoding='utf-8') as fp:
            data = json.load(fp)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None

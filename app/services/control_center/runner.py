"""관제 실행기 — tier 별로 감시를 돌리고, 기록하고, 사건을 판정하고, 스냅샷을 쓴다.

tier
- fast     (1분): 포트·하트비트·워치독·공개 API 터널·/api/health
- standard (10분): 검토된 인증 게이트 점검·핵심 데이터 API·데이터 신선도·스케줄 작업·Windows 작업·디스크·메모리·웹
- deep     (60분): 나머지 화면 데이터 API·외부 API·하드웨어 이벤트·보안 정적 점검(공개 쓰기 라우트)
같은 tier 가 겹쳐 돌지 않도록 잠금 파일을 쓴다. 다른 tier 는 동시에 돌 수 있다(SQLite WAL).
"""
from __future__ import annotations

import errno
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from typing import Any

if os.name == 'nt':
    import msvcrt
else:
    import fcntl

from app.services.control_center import BASE_DIR, alerts, cc_dir, contracts as contracts_mod, store
from app.services.control_center import http_checks, incidents, local_checks, provider_checks
from app.services.control_center.model import STATUS_ORDER, CheckResult, iso, now_kst, worst

TIERS = ('fast', 'standard', 'deep')
INVENTORY_FILE = 'inventory.json'
INVENTORY_MAX_AGE_SEC = 1800
TIER_MAX_AGE_SEC = {'fast': 180, 'standard': 1800, 'deep': 9000}
VERSION = '1.0'


# ─────────────────────────── 잠금 ───────────────────────────

class TierLock:
    """OS-owned lock, released automatically if the process dies."""

    def __init__(self, tier: str, base_dir: str | None = None, *, timeout: float = 0):
        self.path = os.path.join(base_dir or cc_dir(), f'run_{tier}.lock')
        self.timeout = timeout
        self.acquired = False
        self._file = None

    def __enter__(self) -> 'TierLock':
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._file = open(self.path, 'a+b')
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                if os.name == 'nt':
                    self._file.seek(0)
                    msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.acquired = True
                return self
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    self._file.close()
                    raise
                if time.monotonic() >= deadline:
                    self._file.close()
                    return self
                time.sleep(0.05)

    def __exit__(self, *exc) -> None:
        if self.acquired:
            self._file.close()
            self.acquired = False


# ─────────────────────────── 엔드포인트 목록 (디스크의 코드 기준) ───────────────────────────

def build_inventory_payload() -> dict[str, Any]:
    """이 프로세스에서 앱을 만들어 url_map 을 분류한다. 별도 프로세스에서만 부른다."""
    from app import create_route_inventory_app
    from app.services.control_center.inventory import build_inventory
    from app.utils.release_version import get_release_version

    app = create_route_inventory_app()
    return {'generated_at': iso(now_kst()), 'release': get_release_version(BASE_DIR), 'routes': build_inventory(app)}


def load_inventory(base_dir: str | None = None, refresh: bool = False) -> dict[str, Any] | None:
    from app.utils.release_version import get_release_version

    base_dir = os.path.abspath(base_dir or cc_dir())
    path = os.path.join(base_dir, INVENTORY_FILE)
    release = get_release_version(BASE_DIR)

    def read_fresh() -> dict[str, Any] | None:
        try:
            if time.time() - os.stat(path).st_mtime > INVENTORY_MAX_AGE_SEC:
                return None
        except OSError:
            return None
        cached = store.read_json(path)
        if cached and cached.get('release') == release and isinstance(cached.get('routes'), list):
            return cached
        return None

    cached = read_fresh()
    if cached and not refresh:
        return cached
    with TierLock('inventory', base_dir) as lock:
        if not lock.acquired:
            return read_fresh()
        if not refresh and (cached := read_fresh()):
            return cached
        env = dict(os.environ, CONTROL_CENTER_DIR=base_dir, PYTHONIOENCODING='utf-8')
        try:
            subprocess.run([sys.executable, '-m', 'app.services.control_center', 'inventory', '--write'],
                           cwd=BASE_DIR, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=90, check=True)
        except (OSError, subprocess.SubprocessError):
            pass
        return read_fresh()


# ─────────────────────────── tier 별 감시 ───────────────────────────

def _probe_endpoints(base: str, c: dict[str, Any], tier: str, now: datetime) -> list[CheckResult]:
    config = c['endpoints']
    allowed = {'public': set(config.get('public_probe_safe', [])),
               'protected': set(config.get('auth_probe_safe', []))}
    endpoints = [d for d in config.get('deep', []) if d.get('tier', 'standard') == tier
                 and d['path'] in allowed['public' if d.get('auth') == 'public' else 'protected']]
    token = None
    results = []
    if any(d.get('auth') != 'public' for d in endpoints):
        enabled = os.environ.get('CONTROL_CENTER_AUTH_PROBES_ENABLED') == '1'
        token = http_checks.mint_service_token() if enabled else None
        if token:
            # Confirm admin access before contacting a Pro route. A non-admin's
            # expired subscription may otherwise trigger a write in the Pro gate.
            response = http_checks.http_get(base + '/api/admin/control-center/summary', token=token, timeout=3)
            body = response['json']
            if response['status'] != 200 or not isinstance(body, dict) or body.get('schema') != 'marketflow.control_center.v1':
                token = None
                results.append(CheckResult('monitor:auth_probe_' + tier, 'monitor', '인증 점검용 관리자 확인', 'unknown',
                                           '관리자 권한을 확인하지 못해 보호된 경로 점검을 생략했습니다'))
            else:
                results.append(CheckResult('monitor:auth_probe_' + tier, 'monitor', '인증 점검용 관리자 확인', 'ok',
                                           '관리자 권한 확인', severity='info'))
        else:
            detail = '관리자 서비스 계정 미설정' if enabled else '인증을 사용하는 점검은 비활성화됨'
            results.append(CheckResult('monitor:auth_probe_' + tier, 'monitor', '인증 점검용 관리자 확인',
                                       'skipped', detail, severity='info'))
    for endpoint in endpoints:
        result = http_checks.probe_contract(base, endpoint, token, now)
        results.append(result)
        if endpoint.get('auth') != 'public' and result.data.get('http') in (401, 403):
            token = None
    return results


def run_checks(tier: str, c: dict[str, Any], states: dict[str, dict[str, Any]], base_dir: str | None = None) -> list[CheckResult]:
    now = now_kst()
    base = http_checks.api_base(c)
    results: list[CheckResult] = []
    if tier == 'fast':
        results += local_checks.check_ports(c['ports'])
        results += local_checks.check_heartbeats(c['heartbeats'], now)
        results += local_checks.check_watchdog_states(c.get('watchdogs', []), now)
        results += http_checks.check_public_urls([u for u in c.get('public_urls', []) if u.get('tier', 'standard') == 'fast'])
        results += _probe_endpoints(base, c, tier, now)
        return results

    if tier == 'standard':
        flask_up = http_checks.http_get(base + '/healthz', timeout=5)['status'] == 200
        inv = load_inventory(base_dir) if flask_up else None
        if not flask_up:
            results.append(CheckResult('monitor:gate_sweep', 'monitor', '인증 게이트 점검', 'skipped',
                                       'Flask 응답 없음 — 점검 생략 (포트 항목 참조)', severity='info'))
        elif not inv:
            results.append(CheckResult('monitor:gate_sweep', 'monitor', '인증 게이트 점검', 'unknown',
                                       '엔드포인트 목록을 만들지 못함', severity='standard'))
        else:
            candidates = [r for r in inv['routes'] if r['readable'] and r['auth'] != 'public']
            safe_paths = set(c['endpoints'].get('auth_probe_safe', []))
            rows = [r for r in candidates if r['rule'] in safe_paths and not r.get('has_path_vars')
                    and not contracts_mod.endpoint_contract(c, r['rule']).get('exclude')]
            gates = http_checks.auth_gate_sweep(base, rows)
            results += gates
            observed = sum(r.id.startswith('gate:') and r.status not in ('unknown', 'skipped') for r in gates)
            status = 'ok' if candidates and observed == len(candidates) else 'unknown'
            results.append(CheckResult('monitor:gate_sweep', 'monitor', '인증 게이트 점검', status,
                                       f'실관측 {observed}/{len(candidates)}개 · 미관측 {len(candidates) - observed}개',
                                       severity='info', value=observed, data={'observed': observed,
                                       'candidates': len(candidates), 'skipped': len(candidates) - observed}))
        results += _probe_endpoints(base, c, tier, now)
        results += http_checks.check_public_urls([u for u in c.get('public_urls', []) if u.get('tier', 'standard') == 'standard'])
        results += local_checks.check_data(c['data'], now)
        results += local_checks.check_jobs(c['jobs'], now)
        results += local_checks.check_windows_tasks(c['windows_tasks'])
        results += local_checks.check_disk(c.get('host', {}).get('disk', {}))
        results += local_checks.check_memory(c.get('host', {}).get('memory', {}))
        return results

    if tier == 'deep':
        results += _probe_endpoints(base, c, tier, now)
        last = {k: v.get('last_observed_at') for k, v in states.items() if k.startswith('provider:')}
        results += provider_checks.check_providers(c['providers'], last, now)
        results += local_checks.check_windows_events()
        results += security_static(load_inventory(base_dir), c)
        return results
    raise ValueError(tier)


def security_static(inv: dict[str, Any] | None, c: dict[str, Any]) -> list[CheckResult]:
    """인증 없이 쓰기(POST/PUT/DELETE)가 열린 라우트 — 의도된 것인지 사람이 확인해야 한다."""
    if not inv:
        return [CheckResult('security:public_mutations', 'security', '인증 없는 쓰기 라우트', 'unknown',
                            '현재 릴리스의 라우트 목록을 확인할 수 없음')]
    allowed = set(c['endpoints'].get('public_mutation_ok', []))
    risky = [r['rule'] for r in inv['routes'] if r['mutating'] and r['auth'] == 'public' and r['rule'] not in allowed]
    st = 'warn' if risky else 'ok'
    out = [CheckResult('security:public_mutations', 'security', '인증 없는 쓰기 라우트', st,
                       f'{len(risky)}개 — 의도된 공개(로그인·가입·결제 웹훅 등)면 contracts.json public_mutation_ok 에 등록'
                       if risky else '없음 (의도된 공개 쓰기만 존재)', severity='standard', value=risky[:50])]
    exposed = [r['rule'] for r in inv['routes'] if r['auth'] == 'public'
               and r['rule'] in set(c['endpoints'].get('public_info_exposure', []))]
    out.append(CheckResult('security:public_info_exposure', 'security', '공개 운영 정보 노출',
                           'warn' if exposed else 'ok', f'공개 운영 정보 라우트 {len(exposed)}개',
                           severity='info', value=exposed))
    return out


# ─────────────────────────── 스냅샷 ───────────────────────────

def build_snapshot(conn, c: dict[str, Any], base_dir: str | None = None) -> dict[str, Any]:
    states = store.all_states(conn)
    open_inc = store.open_incidents(conn)
    open_security = {i['check_id']: i for i in open_inc if i['family'] == 'security'}
    for state in states:
        if incident := open_security.get(state['check_id']):
            state.update(status='fail', severity=incident['severity'], detail=incident['last_detail'])
    by_id = {s['check_id']: s for s in states}
    families: dict[str, dict[str, Any]] = {}
    for s in states:
        f = families.setdefault(s['family'], {'counts': {k: 0 for k in STATUS_ORDER}, 'status': 'unknown'})
        f['counts'][s['status']] += 1
    for f in families.values():
        f['status'] = _coverage_status(k for k, count in f['counts'].items() if count)

    pages = []
    for p in c['pages']:
        parts = []
        for ep in p['endpoints']:
            endpoint = by_id.get(f'endpoint:{ep}')
            gate = by_id.get(f'gate:{ep}')
            security = by_id.get(f'security:{ep}')
            if security and security['status'] == 'fail':
                st = security
            elif gate and gate['status'] == 'fail':
                st = gate
            else:
                # A successful anonymous gate is evidence of auth only.
                st = endpoint
            parts.append(_page_part('endpoint', ep, st))
        for d in c['data']:
            if p['path'] in d.get('pages', []):
                parts.append(_page_part('data', d['label'], by_id.get(f"data:{d['id']}")))
        pages.append({'path': p['path'], 'label': p['label'], 'critical': p.get('critical', False),
                      'status': _coverage_status(part['status'] for part in parts), 'parts': parts})

    blocking = [s for s in states if s['status'] == 'fail' and s['severity'] == 'critical']
    failing = [s for s in states if s['status'] == 'fail']
    warning = [s for s in states if s['status'] == 'warn']
    overall = 'fail' if blocking else ('warn' if failing or warning else 'ok')
    if any(p['status'] == 'fail' and p['critical'] for p in pages):
        overall = 'fail'
    if overall == 'ok' and (
        _coverage_status(s['status'] for s in states) == 'unknown'
        or any(p['status'] == 'unknown' for p in pages)
    ):
        overall = 'unknown'
    runs = {r['tier']: dict(r) for r in conn.execute(
        'SELECT tier, started_at, finished_at, overall FROM runs WHERE id IN ('
        'SELECT MAX(id) FROM runs WHERE finished_at IS NOT NULL GROUP BY tier)')}
    for tier, entry in runs.items():
        entry['runner_status'] = by_id.get(f'monitor:runner_{tier}', {}).get('status')
    return {
        'schema': 'marketflow.control_center.v1', 'version': VERSION, 'generated_at': iso(now_kst()),
        'overall': overall, 'families': families, 'pages': pages,
        'failing': [_slim(s) for s in sorted(failing, key=lambda s: (s['severity'] != 'critical', s['check_id']))][:200],
        'warning': [_slim(s) for s in warning][:200],
        'open_incidents': open_inc[:100], 'last_runs': runs,
        'gate_coverage': by_id.get('monitor:gate_sweep', {}).get('data') or None,
        'counts': {'checks': len(states), 'fail': len(failing), 'warn': len(warning), 'critical_fail': len(blocking),
                   'open_incidents': len(open_inc), 'unknown': sum(s['status'] == 'unknown' for s in states),
                   'skipped': sum(s['status'] == 'skipped' for s in states)},
    }


def _coverage_status(statuses) -> str:
    status = worst(statuses)
    return 'unknown' if status == 'skipped' else status


def _page_part(kind: str, target: str, state: dict[str, Any] | None) -> dict[str, Any]:
    return {'kind': kind, 'target': target, 'status': state['status'] if state else 'unknown',
            'detail': state['detail'] if state else '데이터 상태 미관측',
            'tier': state['tier'] if state else None}


def _security_recovery(results: list[CheckResult], states: dict[str, dict[str, Any]]) -> list[CheckResult]:
    current_ids = {r.id for r in results}
    recovered = []
    for r in results:
        if not r.id.startswith('gate:'):
            continue
        security_id = 'security:' + r.id.removeprefix('gate:')
        previous = states.get(security_id)
        if previous and security_id not in current_ids:
            status = 'ok' if r.status == 'ok' else 'unknown'
            recovered.append(CheckResult(security_id, 'security', r.target, status, r.detail,
                                         severity=previous['severity'], observed_at=r.observed_at))
    return recovered


def _slim(s: dict[str, Any]) -> dict[str, Any]:
    return {k: s.get(k) for k in ('check_id', 'family', 'target', 'severity', 'status', 'detail', 'latency_ms',
                                  'last_change_at', 'last_observed_at')}


def run(tier: str, base_dir: str | None = None, send_alerts: bool | None = None) -> dict[str, Any]:
    if tier not in TIERS:
        raise ValueError(f'tier must be one of {TIERS}')
    base_dir = base_dir or cc_dir()
    with TierLock(tier, base_dir) as lock:
        if not lock.acquired:
            return {'tier': tier, 'skipped': 'locked'}
        c = contracts_mod.load()
        with store.connect(base_dir) as conn:
            states = {s['check_id']: s for s in store.all_states(conn)}
        started_at = iso(now_kst())
        t0 = time.perf_counter()
        runner_failed = False
        try:
            results = run_checks(tier, c, states, base_dir)
        except Exception as e:  # noqa: BLE001 — 관제 자체의 오류도 관제 결과로 남긴다
            runner_failed = True
            results = [CheckResult(f'monitor:runner_{tier}', 'monitor', f'관제 실행기 ({tier})', 'fail',
                                   f'실행 오류 {type(e).__name__}', severity='standard')]
        else:
            results.append(CheckResult(f'monitor:runner_{tier}', 'monitor', f'관제 실행기 ({tier})', 'ok',
                                       f'{len(results)}개 항목 · {time.perf_counter() - t0:.1f}초', severity='info'))
        changes = []
        # Commit and publish in one cross-process critical section. Probes and
        # external notification requests never hold the SQLite write lock.
        with TierLock('publish', base_dir, timeout=20) as publisher:
            if not publisher.acquired:
                raise TimeoutError('Control Center snapshot publication is busy')
            with store.connect(base_dir) as conn:
                run_id = store.start_run(conn, tier, started_at)
                if tier == 'standard':
                    results += _security_recovery(results, states)
                store.record_results(conn, run_id, results)
                for r in results:
                    change = incidents.apply(conn, r, tier)
                    if change:
                        changes.append(change)
                counts = {k: sum(1 for r in results if r.status == k) for k in STATUS_ORDER}
                store.finish_run(conn, run_id, _coverage_status(r.status for r in results), counts)
                if tier == 'standard':
                    store.prune(conn)
                snapshot = build_snapshot(conn, c, base_dir)
            store.write_json_atomic(os.path.join(base_dir, 'latest.json'), snapshot)
            store.write_json_atomic(os.path.join(base_dir, 'heartbeat.json'),
                                    {'ts': iso(now_kst()), 'pid': os.getpid(), 'tier': tier, 'version': VERSION})
        sent = 0
        if changes:
            with store.connect(base_dir) as conn:
                sent = alerts.dispatch(conn, changes, snapshot, enabled=send_alerts, commit_each=True)
        return {'tier': tier, 'results': len(results), 'changes': changes, 'alerts_sent': sent, 'overall': snapshot['overall'],
                'counts': snapshot['counts'], 'runner_failed': runner_failed}


def read_snapshot(base_dir: str | None = None) -> dict[str, Any]:
    """Flask·MCP 가 읽는 요약. 실행기가 멈췄으면 그 사실이 맨 위에 온다."""
    base_dir = base_dir or cc_dir()
    snap = store.read_json(os.path.join(base_dir, 'latest.json'))
    hb = store.read_json(os.path.join(base_dir, 'heartbeat.json'))
    if not snap:
        monitor = {'status': 'fail', 'detail': '관제 스냅샷이 없습니다', 'heartbeat': hb,
                   'tiers': {tier: _tier_health(None, now_kst(), maximum) for tier, maximum in TIER_MAX_AGE_SEC.items()}}
        return {'schema': 'marketflow.control_center.v1', 'overall': 'unknown', 'monitor': monitor, 'families': {},
                'pages': [], 'failing': [], 'warning': [], 'open_incidents': [], 'counts': {}}
    now = now_kst()
    runs = snap.get('last_runs') or {}
    tiers = {tier: _tier_health(runs.get(tier), now, maximum) for tier, maximum in TIER_MAX_AGE_SEC.items()}
    status = worst(t['status'] for t in tiers.values())
    affected = [tier for tier, health in tiers.items() if health['status'] != 'ok']
    snap['monitor'] = {'status': status, 'detail': '정상' if not affected else '점검 필요 · ' + ', '.join(affected),
                       'heartbeat': hb, 'tiers': tiers}
    for page in snap.get('pages', []):
        for part in page.get('parts', []):
            if part.get('tier') in affected and part['status'] in ('ok', 'skipped'):
                part.update(status='unknown', detail='해당 감시 주기의 최신 결과가 없습니다')
        page['status'] = _coverage_status(part['status'] for part in page.get('parts', []))
    snap['overall'] = worst((snap.get('overall'), status))
    return snap


def _tier_health(run: dict[str, Any] | None, now: datetime, max_age: int) -> dict[str, Any]:
    if not run or not run.get('finished_at'):
        return {'status': 'unknown', 'detail': '완료 기록 없음'}
    try:
        age = (now - datetime.fromisoformat(run['finished_at'])).total_seconds()
    except (TypeError, ValueError):
        return {'status': 'unknown', 'detail': '완료 시각을 확인할 수 없음'}
    if age < -60:
        return {'status': 'unknown', 'detail': '완료 시각이 현재 시각보다 앞섭니다'}
    if age >= max_age:
        return {'status': 'fail', 'detail': '최근 완료 기록이 오래되었습니다', 'age_seconds': round(age)}
    if run.get('runner_status') == 'fail':
        return {'status': 'fail', 'detail': '최근 실행 중 오류가 발생했습니다', 'age_seconds': max(0, round(age))}
    return {'status': 'ok', 'detail': '최근 실행 완료', 'age_seconds': max(0, round(age))}


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1, default=str)

"""로컬 감시 — 파일·하트비트·데이터 신선도·스케줄 작업·Windows 작업·포트·디스크·호스트.

전부 읽기만 한다. Windows 전용 항목(작업 스케줄러, 이벤트 로그)은 다른 OS 에서 skipped.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import time
from datetime import datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo
from typing import Any

from app.services.control_center import BASE_DIR, DATA_DIR
from app.services.control_center.contracts import API_HOST, LOCAL_MONITOR_PORTS
from app.services.control_center.model import KST, CheckResult, now_kst

IS_WINDOWS = os.name == 'nt'


# ─────────────────────────── 공통 ───────────────────────────

def resolve_path(template: str) -> str:
    from app.utils import paths

    tokens = {'{base}': paths.BASE_DIR, '{data}': paths.DATA_DIR, '{us_output}': paths.US_OUTPUT_DIR,
              '{crypto_output}': paths.CRYPTO_OUTPUT_DIR, '{logs}': paths.LOGS_DIR}
    out = template
    for k, v in tokens.items():
        out = out.replace(k, v)
    return os.path.normpath(out)


def _parse_ts(value: Any) -> datetime | None:
    if value in (None, '') or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), KST)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=KST)   # 이 앱의 naive 시각은 KST 로컬 기준


def _age_text(seconds: float) -> str:
    if seconds < 120:
        return f'{seconds:.0f}초'
    if seconds < 7200:
        return f'{seconds / 60:.0f}분'
    if seconds < 172800:
        return f'{seconds / 3600:.1f}시간'
    return f'{seconds / 86400:.1f}일'


def _read_json(path: str, max_bytes: int = 20_000_000) -> Any:
    try:
        with open(path, 'rb') as f:
            raw = f.read(max_bytes + 1)
        if len(raw) <= max_bytes:
            return json.loads(raw.decode('utf-8-sig'))
    except (OSError, ValueError, RecursionError):
        pass
    return None


# ─────────────────────────── 하트비트·워치독 상태 ───────────────────────────

def check_heartbeats(items: list[dict[str, Any]], now: datetime | None = None) -> list[CheckResult]:
    now = now or now_kst()
    out = []
    for it in items:
        path = resolve_path(it['path'])
        sev = it.get('severity', 'standard')
        data = _read_json(path)
        ts = _parse_ts(data.get(it.get('field', 'ts'))) if isinstance(data, dict) else None
        if ts is None or ts > now + timedelta(seconds=5):
            exists = os.path.exists(path)
            out.append(CheckResult(f"heartbeat:{it['id']}", 'process', it.get('label', it['id']),
                                   'unknown' if exists else 'fail',
                                   '유효한 하트비트 시각 없음' if exists else '하트비트 파일 없음', severity=sev))
            continue
        age = max(0, (now - ts).total_seconds())
        if age > it.get('max_age_sec', 180):
            status, detail = 'fail', f'마지막 하트비트 {_age_text(age)} 전'
        elif data.get('state') in ('error', 'disabled', 'halt'):
            status, detail = 'warn', '하트비트 수신 · 작업 중지 또는 오류 상태'
        else:
            status, detail = 'ok', f'마지막 하트비트 {_age_text(age)} 전'
        out.append(CheckResult(f"heartbeat:{it['id']}", 'process', it.get('label', it['id']), status,
                               detail, severity=sev, value=round(age)))
    return out


def check_watchdog_states(items: list[dict[str, Any]], now: datetime | None = None) -> list[CheckResult]:
    """워치독이 이미 자동 재시작을 한다. 관제는 '재시작이 반복되는지(복구 실패)' 를 본다."""
    now = now or now_kst()
    out = []
    for it in items:
        data = _read_json(resolve_path(it['path']))
        cid = f"watchdog:{it['id']}"
        if not isinstance(data, dict):
            out.append(CheckResult(cid, 'process', it.get('label', it['id']), 'unknown', '상태 파일 없음', severity='info'))
            continue
        fails = data.get('consecutive_failures')
        status_text = str(data.get('status') or '')
        updated = _parse_ts(data.get('updated_at'))
        age = (now - updated).total_seconds() if updated else None
        if age is None or age < -5 or type(fails) is not int or fails < 0:
            out.append(CheckResult(cid, 'process', it.get('label', it['id']), 'unknown',
                                   '워치독 상태 파일에 유효한 시각 또는 실패 횟수 없음',
                                   severity=it.get('severity', 'standard')))
            continue
        if fails >= it.get('fail_after', 3) or status_text in ('reboot_requested', 'failed'):
            st, msg = 'fail', f'연속 실패 {fails}회 — 워치독 자동 복구 실패'
        elif fails > 0:
            st, msg = 'warn', f'연속 실패 {fails}회 — 워치독이 복구 시도 중'
        elif age is not None and age > it.get('max_age_sec', 900):
            st, msg = 'warn', f'워치독 기록이 {_age_text(age)} 전에 멈춤 (워치독 작업 확인)'
        else:
            st, msg = 'ok', '연속 실패 없음'
        out.append(CheckResult(cid, 'process', it.get('label', it['id']), st, msg,
                               severity=it.get('severity', 'standard'), value={'consecutive_failures': fails}))
    return out


# ─────────────────────────── 데이터 신선도 ───────────────────────────

@lru_cache(maxsize=8)
def _nyse_holidays(year: int):
    import holidays

    return holidays.financial_holidays('XNYS', years=[year])


def _is_trading_day(calendar: str, day) -> bool:
    if day.weekday() >= 5:
        return False
    if calendar == 'kr_trading':
        from app.services.kis_screener import _is_kr_trading_day

        return _is_kr_trading_day(day)
    return day not in _nyse_holidays(day.year)


def _calendar_allowance(calendar: str, now: datetime) -> float:
    # The expected release window is 18:00 in the respective market's
    # timezone. Only intervening closed days extend the normal age budget.
    if calendar not in ('kr_trading', 'us_trading'):
        return 0
    local = now.astimezone(KST if calendar == 'kr_trading' else ZoneInfo('America/New_York'))
    candidate = local.date()
    if local.hour < 18:
        candidate -= timedelta(days=1)
    closed_days = 0
    while closed_days < 14 and not _is_trading_day(calendar, candidate):
        closed_days += 1
        candidate -= timedelta(days=1)
    return closed_days * 24


def check_data(items: list[dict[str, Any]], now: datetime | None = None) -> list[CheckResult]:
    now = now or now_kst()
    out = []
    for it in items:
        path = resolve_path(it['path'])
        sev = it.get('severity', 'standard')
        cid = f"data:{it['id']}"
        metadata = {'path': it['path'], 'pages': it.get('pages', [])}
        if not os.path.exists(path):
            out.append(CheckResult(cid, 'data', it.get('label', it['id']),
                                   'skipped' if it.get('optional') else 'fail', '파일 없음', severity=sev,
                                   data=metadata))
            continue
        field = it.get('field')
        if field or path.lower().endswith('.json'):
            payload = _read_json(path)
            if not isinstance(payload, (dict, list)) or not payload:
                out.append(CheckResult(cid, 'data', it.get('label', it['id']), 'unknown',
                                       '유효한 JSON 데이터 없음', severity=sev, data=metadata))
                continue
        if field:
            cur = payload
            for key in field.split('.'):
                cur = cur.get(key) if isinstance(cur, dict) else None
            basis = _parse_ts(cur)
        else:
            try:
                basis = datetime.fromtimestamp(os.path.getmtime(path), KST)
            except (OSError, ValueError, OverflowError):
                basis = None
        if basis is None or basis > now + timedelta(seconds=5):
            out.append(CheckResult(cid, 'data', it.get('label', it['id']), 'unknown',
                                   '유효한 데이터 시각 없음', severity=sev,
                                   data=metadata))
            continue
        age_h = max(0, (now - basis).total_seconds()) / 3600
        limit = float(it.get('max_age_hours', 26)) + _calendar_allowance(it.get('calendar', ''), now)
        if age_h <= limit:
            st = 'ok'
        elif age_h <= limit * 1.5:
            st = 'warn'
        else:
            st = 'fail'
        basis_name = '내용 시각' if field else '파일 수정 시각(메타데이터)'
        metadata['freshness_basis'] = 'content' if field else 'mtime'
        out.append(CheckResult(cid, 'data', it.get('label', it['id']), st,
                               f'{basis_name} 기준 {_age_text(age_h * 3600)} 전 (허용 {limit:.0f}시간)', severity=sev,
                               value=round(age_h, 2), data=metadata))
    return out


# ─────────────────────────── 스케줄 작업 (scheduler.py 데몬) ───────────────────────────

_TIMES = re.compile(r'(\d{1,2}):(\d{2})')
_TIME_LIST = r'\d{1,2}:\d{2}(?:\s*,\s*\d{1,2}:\d{2})*'
_WEEKDAY_NAMES = '월화수목금토일'


def parse_schedule(text: str) -> dict[str, Any]:
    """Parse the daemon's daily, weekday, weekly and intraday-window descriptions."""
    text = (text or '').strip()
    m = re.fullmatch(rf'매\s*(\d+)\s*(분|시간)(?:\s*\(({_TIME_LIST})\))?', text)
    if m:
        minutes = int(m.group(1)) * (60 if m.group(2) == '시간' else 1)
        clocks = _TIMES.findall(m.group(3) or '')
        if minutes > 0 and all(int(h) < 24 and int(mi) < 60 for h, mi in clocks):
            return {'kind': 'interval', 'minutes': minutes}
        return {'kind': 'unknown'}
    m = re.fullmatch(r'(매일|평일|[월화수목금토일]요일)\s+(.+)', text)
    if not m:
        return {'kind': 'unknown'}
    prefix, body = m.groups()
    days = {'weekdays_only': prefix == '평일'}
    post_close_suffix = ' (미국 거래일 마감 후)'
    if body.endswith(post_close_suffix):
        body = body[:-len(post_close_suffix)]
        days['calendar'] = 'us_post_close'
    if prefix.endswith('요일'):
        days['weekdays'] = [_WEEKDAY_NAMES.index(prefix[0])]
    window = re.fullmatch(r'(\d{1,2}:\d{2})\s*~\s*(\d{1,2}:\d{2})\s*\((\d+)분\)', body)
    times = [(int(h), int(mi)) for h, mi in _TIMES.findall(body)]
    if not times or any(h >= 24 or mi >= 60 for h, mi in times):
        return {'kind': 'unknown'}
    if window:
        minutes = int(window.group(3))
        if minutes > 0 and times[0] < times[1]:
            return {'kind': 'window', 'start': times[0], 'end': times[1], 'minutes': minutes, **days}
    elif re.fullmatch(_TIME_LIST, body) and len(set(times)) == len(times):
        return {'kind': 'times', 'times': times, **days}
    return {'kind': 'unknown'}


def _market_hours(market: str, now: datetime) -> bool:
    if market != 'KR':
        return True
    return _is_trading_day('kr_trading', now.date()) and (9, 0) <= (now.hour, now.minute) <= (15, 40)


def _job_day_allowed(job: dict[str, Any], sched: dict[str, Any], day) -> bool:
    if (job.get('calendar') or sched.get('calendar')) == 'us_post_close':
        session = day - timedelta(days=1)
        if not _is_trading_day('us_trading', session) or not sched.get('times'):
            return False
        close = datetime(session.year, session.month, session.day, 16, tzinfo=ZoneInfo('America/New_York'))
        h, mi = min(sched['times'])
        release = datetime(day.year, day.month, day.day, h, mi, tzinfo=KST)
        return close <= release
    # Weekly maintenance such as Saturday history collection is not restricted
    # to exchange sessions merely because its output market is KR.
    if 'weekdays' in sched:
        return day.weekday() in sched['weekdays']
    if sched.get('weekdays_only'):
        return day.weekday() < 5 and (job.get('market') != 'KR' or _is_trading_day('kr_trading', day))
    return True


def _job_slots(now: datetime, day, times: list[tuple[int, int]]) -> list[datetime]:
    return [now.replace(year=day.year, month=day.month, day=day.day, hour=h, minute=mi,
                        second=0, microsecond=0) for h, mi in times]


def evaluate_job(job: dict[str, Any], last_runs: dict[str, Any], now: datetime, grace_min: int = 45,
                 critical: set[str] | None = None) -> CheckResult:
    now = now.astimezone(KST)
    key = job.get('key', '?')
    label = job.get('label') or key
    sev = 'critical' if critical and key in critical else 'standard'
    cid = f'job:{key}'
    sched = parse_schedule(str(job.get('schedule') or ''))
    record_keys = list(job.get('record_keys') or [job.get('record_key') or key])
    runs = {rk: _parse_ts(last_runs.get(rk)) for rk in record_keys}
    latest = max((t for t in runs.values() if t and t <= now), default=None)
    if sched['kind'] in ('interval', 'window'):
        in_window = (_job_day_allowed(job, sched, now.date())
                     and sched['start'] <= (now.hour, now.minute) <= sched['end']) if sched['kind'] == 'window' else True
        if not in_window or not _market_hours(str(job.get('market')), now):
            return CheckResult(cid, 'job', label, 'skipped', '장외 시간 — 판정 안 함', severity=sev)
        if any(last_runs.get(rk) is not None and (ran is None or ran > now) for rk, ran in runs.items()):
            return CheckResult(cid, 'job', label, 'unknown', '실행 기록 시각이 잘못되었거나 미래임', severity=sev)
        if latest is None:
            return CheckResult(cid, 'job', label, 'unknown', '유효한 실행 기록 없음', severity=sev)
        age_min = (now - latest).total_seconds() / 60
        limit = max(3 * sched['minutes'], sched['minutes'] + 10)
        st = 'ok' if age_min <= limit else ('warn' if age_min <= 2 * limit else 'fail')
        return CheckResult(cid, 'job', label, st, f'마지막 성공 {_age_text(age_min * 60)} 전 (주기 {sched["minutes"]}분)',
                           severity=sev, value=round(age_min, 1))
    if sched['kind'] == 'times':
        today_allowed = _job_day_allowed(job, sched, now.date())
        if sched['weekdays_only'] and not today_allowed:
            return CheckResult(cid, 'job', label, 'skipped', '비실행일 — 판정 안 함', severity=sev)
        if any(last_runs.get(rk) is not None and (ran is None or ran > now) for rk, ran in runs.items()):
            return CheckResult(cid, 'job', label, 'unknown', '실행 기록 시각이 잘못되었거나 미래임', severity=sev)
        today_slots = _job_slots(now, now.date(), sched['times'])
        slot_keys = record_keys if len(record_keys) == len(today_slots) else [record_keys[0]] * len(today_slots)
        grace = timedelta(minutes=max(0, grace_min))
        early = timedelta(minutes=10)
        # Before today's first due deadline, the previous scheduled day still
        # needs a success baseline. Midnight must not erase yesterday's failure.
        current_evidence = any(runs.get(rk) and slot - early <= runs[rk] <= now
                               for rk, slot in zip(slot_keys, today_slots))
        day = now.date()
        if not today_allowed or not (current_evidence or any(slot + grace <= now for slot in today_slots)):
            for offset in range(1, 36):
                candidate = now.date() - timedelta(days=offset)
                if _job_day_allowed(job, sched, candidate):
                    day = candidate
                    break
            else:
                return CheckResult(cid, 'job', label, 'unknown', '최근 실행 예정일을 확인할 수 없음', severity=sev)
        missed, pending, done = [], [], []
        slots = _job_slots(now, day, sched['times'])
        # A shared record key retains only the latest run. Attribute it to the
        # latest eligible slot, and leave overwritten slots unverified.
        attributable = {}
        for rk, ran in runs.items():
            if ran and ran <= now:
                attributable[rk] = max((slot for slot, key in zip(slots, slot_keys)
                                        if key == rk and slot - early <= ran),
                                       default=None)
        unverified = []
        for idx, (h, mi) in enumerate(sched['times']):
            slot = slots[idx]
            rk = slot_keys[idx]
            ran = runs.get(rk)
            label_t = f'{h:02d}:{mi:02d}'
            shared = slot_keys.count(rk) > 1
            if ran and ran <= now and slot - early <= ran and (
                    not shared or attributable.get(rk) == slot):
                done.append(label_t)
            elif ran and (ran > now or (shared and attributable.get(rk) and attributable[rk] > slot)):
                unverified.append(label_t)
            elif now < slot + grace:
                pending.append(label_t)
            else:
                missed.append(label_t)
        if day != now.date() and today_allowed:
            pending = [slot.strftime('%H:%M') for slot in today_slots if slot + grace > now]
        value = {'basis_date': day.isoformat(), 'missed': missed, 'done': done,
                 'pending': pending, 'unverified': unverified}
        if missed:
            return CheckResult(cid, 'job', label, 'fail', f'{day.isoformat()} 기한 지난 실행 성공 미확인: {", ".join(missed)}',
                               severity=sev, value=value)
        detail = f'{day.isoformat()} 완료 {", ".join(done) or "-"} · 대기 {", ".join(pending) or "-"}'
        if unverified:
            detail += f' · 미확인 {", ".join(unverified)}'
        return CheckResult(cid, 'job', label, 'ok' if done and not unverified else 'unknown', detail,
                           severity=sev, value=value)
    if latest is None:
        return CheckResult(cid, 'job', label, 'unknown', '일정 해석 불가 · 실행 기록 없음', severity='info')
    age = (now - latest).total_seconds()
    return CheckResult(cid, 'job', label, 'unknown', f'일정 해석 불가 · 마지막 성공 {_age_text(age)} 전',
                       severity='info', value=round(age / 60, 1))


def _valid_job_record(job: Any) -> bool:
    if not isinstance(job, dict) or not isinstance(job.get('key'), str) or not job['key'].strip():
        return False
    record_keys = job.get('record_keys', [])
    return (isinstance(record_keys, list)
            and all(isinstance(key, str) and key.strip() for key in record_keys)
            and all(isinstance(job[field], str) for field in ('record_key', 'label', 'schedule', 'market', 'calendar')
                    if field in job))


def check_jobs(cfg: dict[str, Any], now: datetime | None = None) -> list[CheckResult]:
    now = now or now_kst()
    registry_path = os.path.join(DATA_DIR, 'scheduler_jobs.json')
    registry = _read_json(registry_path)
    # The daemon writes a wrapped registry. Accept a bare list for old snapshots.
    jobs = registry.get('jobs') if isinstance(registry, dict) else registry
    if not isinstance(jobs, list) or not jobs or not all(_valid_job_record(job) for job in jobs):
        detail = ('잡 목록이 비어 있거나 형식이 올바르지 않음' if os.path.exists(registry_path)
                  else '잡 목록 파일 없음')
        return [CheckResult('job:_registry', 'job', '스케줄러 잡 목록', 'unknown', detail)]
    if len({job['key'] for job in jobs}) != len(jobs):
        return [CheckResult('job:_registry', 'job', '스케줄러 잡 목록', 'unknown', '중복된 잡 키가 있음')]
    results = [CheckResult('job:_registry', 'job', '스케줄러 잡 목록', 'ok',
                           f'잡 목록 {len(jobs)}개 확인', severity='info', value=len(jobs))]
    last_runs = _read_json(os.path.join(DATA_DIR, 'scheduler_last_run.json'))
    if (not isinstance(last_runs, dict) or not last_runs
            or any(not key.strip() or (stamp := _parse_ts(value)) is None or stamp > now
                   for key, value in last_runs.items())):
        results.append(CheckResult('job:_baseline', 'job', '스케줄러 성공 기록', 'unknown',
                                   '유효한 스케줄러 성공 기록 없음'))
        return results
    results.append(CheckResult('job:_baseline', 'job', '스케줄러 성공 기록', 'ok',
                               f'실행 시각 기록 {len(last_runs)}개 확인', severity='info', value=len(last_runs)))
    critical = set(cfg.get('critical', []))
    grace = int(cfg.get('grace_minutes', 45))
    ignore = set(cfg.get('ignore', []))
    results.extend(evaluate_job(job, last_runs, now, grace, critical) for job in jobs if job['key'] not in ignore)
    return results


# ─────────────────────────── Windows 작업 스케줄러 · 이벤트 로그 ───────────────────────────

_PS_TASKS = r"""
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.Encoding]::UTF8
$prefixes = @(%s)
$rows = Get-ScheduledTask | Where-Object { $n=$_.TaskName; ($prefixes | Where-Object { $n -like ($_ + '*') }).Count -gt 0 } | ForEach-Object {
  try { $i = $_ | Get-ScheduledTaskInfo -ErrorAction Stop } catch { $i = $null }
  [pscustomobject]@{ name=$_.TaskName; state=[string]$_.State;
    last_run= if ($i.LastRunTime -and $i.LastRunTime.Year -gt 2000) { $i.LastRunTime.ToString('o') } else { $null };
    last_result= if ($i) { [int64]$i.LastTaskResult } else { $null };
    next_run= if ($i.NextRunTime -and $i.NextRunTime.Year -gt 2000) { $i.NextRunTime.ToString('o') } else { $null };
    missed= if ($i) { [int]$i.NumberOfMissedRuns } else { $null } }
}
ConvertTo-Json -InputObject @($rows) -Compress
"""
OK_RESULTS = {0, 0x41301}          # 성공, 실행 중
NEVER_RUN = 0x41303


def _powershell(script: str, timeout: int = 40) -> str | None:
    try:
        proc = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                              capture_output=True, text=True, timeout=timeout, encoding='utf-8', errors='replace')
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def evaluate_tasks(rows: list[dict[str, Any]], cfg: dict[str, Any]) -> list[CheckResult]:
    critical = set(cfg.get('critical', []))
    resident = set(cfg.get('resident', []))
    ignored = set(cfg.get('ignore', []))
    out = []
    now = now_kst()
    for r in rows:
        name = str(r.get('name'))
        if name in ignored:
            continue
        sev = 'critical' if name in critical else 'standard'
        state = str(r.get('state') or '')
        raw_result = r.get('last_result')
        res = raw_result & 0xFFFFFFFF if type(raw_result) is int else None
        last = _parse_ts(r.get('last_run'))
        next_run = _parse_ts(r.get('next_run'))
        missed = r.get('missed')
        issue = 'fail' if sev == 'critical' else 'warn'
        cid = f'task:{name}'
        if state == 'Disabled':
            out.append(CheckResult(cid, 'task', name, 'fail' if sev == 'critical' else 'warn', '작업이 비활성화됨', severity=sev))
        elif state not in ('Ready', 'Running', 'Queued'):
            out.append(CheckResult(cid, 'task', name, 'unknown', '유효한 작업 상태 없음', severity=sev))
        elif name in resident and state != 'Running':
            out.append(CheckResult(cid, 'task', name, issue, f'상주 작업이 실행 중이 아님 (상태 {state})', severity=sev))
        elif res is None or (last and last > now):
            out.append(CheckResult(cid, 'task', name, 'unknown', '유효한 작업 실행 정보 없음', severity=sev))
        elif res in OK_RESULTS:
            st, msg = 'ok', '마지막 작업 성공'
            if state == 'Running':
                st, msg = ('ok', '상주 작업 실행 중') if name in resident else ('unknown', '현재 작업 완료 대기')
            elif res != 0 or last is None:
                st, msg = 'unknown', '완료된 작업 기준 없음'
            elif type(missed) is int and missed > 0:
                st, msg = 'warn', f'놓친 실행 {missed}회'
            elif next_run and next_run < now - timedelta(minutes=5):
                st, msg = issue, '다음 예정 시각이 지났으나 실행 확인 안 됨'
            out.append(CheckResult(cid, 'task', name, st, msg, severity=sev,
                                   value={'last_run': last.isoformat() if last else None,
                                          'next_run': next_run.isoformat() if next_run else None}))
        elif res == NEVER_RUN:
            out.append(CheckResult(cid, 'task', name, 'warn', '아직 한 번도 실행되지 않음', severity=sev))
        else:
            out.append(CheckResult(cid, 'task', name, 'fail' if sev == 'critical' else 'warn',
                                   f'마지막 결과 0x{res:X} (상태 {state}, 놓친 실행 {missed if type(missed) is int else "-"})', severity=sev,
                                   value={'last_run': last.isoformat() if last else None, 'last_result': res}))
    for name in sorted((critical - ignored) - {str(r.get('name')) for r in rows}):
        out.append(CheckResult(f'task:{name}', 'task', name, 'fail', '작업 스케줄러에 등록되어 있지 않음', severity='critical'))
    return out


def check_windows_tasks(cfg: dict[str, Any]) -> list[CheckResult]:
    if not IS_WINDOWS:
        return [CheckResult('task:_scheduler', 'task', 'Windows 작업 스케줄러', 'skipped', 'Windows 가 아님', severity='info')]
    prefixes = ','.join("'" + p.replace("'", "") + "'" for p in cfg.get('prefixes', ['MarketFlow-']))
    raw = _powershell(_PS_TASKS % prefixes)
    if raw is None:
        return [CheckResult('task:_scheduler', 'task', 'Windows 작업 스케줄러', 'unknown', '작업 목록 조회 실패', severity='standard')]
    try:
        rows = json.loads(raw) if raw else None
    except ValueError:
        return [CheckResult('task:_scheduler', 'task', 'Windows 작업 스케줄러', 'unknown', '작업 목록 해석 실패', severity='standard')]
    if not isinstance(rows, list) or not all(isinstance(r, dict) and isinstance(r.get('name'), str) for r in rows):
        return [CheckResult('task:_scheduler', 'task', 'Windows 작업 스케줄러', 'unknown', '작업 목록 형식 오류')]
    if len({r['name'] for r in rows}) != len(rows):
        return [CheckResult('task:_scheduler', 'task', 'Windows 작업 스케줄러', 'unknown', '작업 이름 중복')]
    return evaluate_tasks(rows, cfg)


_PS_EVENTS = r"""
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.Encoding]::UTF8
function Read-Events($filter) {
  try { Get-WinEvent -FilterHashtable $filter -ErrorAction Stop }
  catch {
    if ($_.FullyQualifiedErrorId -notlike 'NoMatchingEventsFound,*') { throw }
  }
}
$since=(Get-Date).AddHours(-24)
$whea=@(Read-Events @{LogName='System'; ProviderName='Microsoft-Windows-WHEA-Logger'; StartTime=$since}).Count
$py=@(Read-Events @{LogName='Application'; Id=1000; StartTime=$since} | Where-Object { $_.Message -match 'python' }).Count
[pscustomobject]@{ whea=$whea; python_crash=$py } | ConvertTo-Json -Compress
"""


def check_windows_events() -> list[CheckResult]:
    """하드웨어 오류(WHEA)와 파이썬 프로세스 비정상 종료 — 이 MiniPC 의 알려진 불안정 요인."""
    if not IS_WINDOWS:
        return [CheckResult('host:events', 'host', '하드웨어·프로세스 오류', 'skipped', 'Windows 가 아님', severity='info')]
    raw = _powershell(_PS_EVENTS, timeout=60)
    try:
        data = json.loads(raw) if raw else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return [CheckResult('host:events', 'host', '하드웨어·프로세스 오류', 'unknown', '이벤트 로그 조회 실패')]
    whea, py = data.get('whea'), data.get('python_crash')
    if type(whea) is not int or type(py) is not int or whea < 0 or py < 0:
        return [CheckResult('host:events', 'host', '하드웨어·프로세스 오류', 'unknown', '유효한 이벤트 건수 없음')]
    st = 'fail' if whea >= 3 or py >= 3 else ('warn' if whea or py else 'ok')
    return [CheckResult('host:events', 'host', '하드웨어·프로세스 오류', st,
                        f'최근 24시간 WHEA 하드웨어 오류 {whea}건 · 파이썬 비정상 종료 {py}건', severity='standard',
                        value={'whea_24h': whea, 'python_crash_24h': py})]


# ─────────────────────────── 포트 · 디스크 · 메모리 ───────────────────────────

def check_ports(items: list[dict[str, Any]], host: str = API_HOST) -> list[CheckResult]:
    out = []
    for it in items:
        port = int(it['port'])
        if host != API_HOST or port not in LOCAL_MONITOR_PORTS:
            continue
        t0 = time.perf_counter()
        try:
            with socket.create_connection((host, port), timeout=float(it.get('timeout', 1.5))):
                pass
            st, msg = 'ok', f'{port} 포트 응답'
        except OSError:
            st, msg = 'fail', f'{port} 포트 응답 없음 (프로세스 꺼짐 가능)'
        out.append(CheckResult(f"port:{it['id']}", 'process', it.get('label', it['id']), st, msg,
                               severity=it.get('severity', 'standard'), latency_ms=int((time.perf_counter() - t0) * 1000)))
    return out


def check_disk(cfg: dict[str, Any]) -> list[CheckResult]:
    usage = shutil.disk_usage(BASE_DIR)
    free_gb = usage.free / 1e9
    fail_gb, warn_gb = float(cfg.get('fail_gb', 1)), float(cfg.get('warn_gb', 5))
    st = 'fail' if free_gb < fail_gb else ('warn' if free_gb < warn_gb else 'ok')
    return [CheckResult('host:disk', 'host', '디스크 여유 공간', st,
                        f'여유 {free_gb:.1f}GB ({usage.free / usage.total * 100:.0f}%)', severity='critical' if st == 'fail' else 'standard',
                        value=round(free_gb, 2))]


def check_memory(cfg: dict[str, Any]) -> list[CheckResult]:
    try:
        import psutil  # type: ignore
    except ImportError:
        return [CheckResult('host:memory', 'host', '메모리', 'skipped', 'psutil 미설치', severity='info')]
    vm = psutil.virtual_memory()
    st = 'fail' if vm.percent >= cfg.get('fail_pct', 95) else ('warn' if vm.percent >= cfg.get('warn_pct', 85) else 'ok')
    return [CheckResult('host:memory', 'host', '메모리', st, f'사용률 {vm.percent:.0f}% (여유 {vm.available / 1e9:.1f}GB)',
                        value=round(vm.percent, 1))]

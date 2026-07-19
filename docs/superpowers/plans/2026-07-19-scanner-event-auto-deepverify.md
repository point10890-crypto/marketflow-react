# 스캐너 이벤트 자동 딥검증 + 13D 캡처 + 히스토리 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 알파 스캐너가 신규 매수후보 이벤트를 검출할 때, 검출 시점 Brain 13D 스냅샷을 캡처해 TradingAgents 딥검증을 백그라운드로 자동 실행하고, 결과를 히스토리에 누적 + 스캐너 위젯 카드에 자동 표시한다.

**Architecture:** 신규 `scanner_deepverify.py` 가 (1) 히스토리 스토어(append-only, 최근 500 캡, latest-by-event_key 뷰), (2) 신규 이벤트 선정/dedupe/백그라운드 검증(13D 캡처+run_deep_analysis)을 담당. `alpha_scanner.py` 는 커밋 직후 비동기 enqueue + feed_events 요약에 latest 머지(둘 다 lazy import 로 순환 회피). 신규 GET 엔드포인트로 히스토리 조회. 프론트는 카드 행에 verdict 블록 표시.

**Tech Stack:** Python 3 / Flask, pytest, React + TS, `write_json_atomic`, threading.

**환경 (고정):**
```bash
PROJECT="/c/bitman_marketfloww"
PYTHON="$PROJECT/.venv/Scripts/python.exe"
```
pytest: `cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest ...`

**참조 스펙:** `docs/superpowers/specs/2026-07-19-scanner-event-auto-deepverify-design.md`

**핵심 사실(검증됨):**
- `alpha_scanner.commit_scanner_alert_events(result)`(≈L788): `events=result['events']`, `run=result['run']`, write 후 `_alert_state_summary` 반환.
- `alpha_scanner._alert_state_summary(state, state_file, *, latest_run=None)`(≈L4074): `feed = _merge_alert_history(recent_for_feed, [], limit=20)` 직후 return. feed 각 entry 는 `event_key` 보유.
- `alpha_scanner._candidate_event_key(candidate)`(≈L3822) = `f"{symbol}:{action}:{price_date}"`.
- 이벤트 shape: `event = {'candidate': {symbol, display_name, market, action, alpha_score, risk_score, ...}, 'event_key': str, 'sent_at'?}`.
- `store._brain_summary(target)` → `{name,target,regime,alignment_score,snapshot_at,...}` (엔진/regime 과 호환).
- `engine.run_deep_analysis(target, *, symbol=None, brain=None, ...)` → `{id, method, verdict:{verdict,confidence,strong_buy,regime,regime_adjustment,...}}`.

---

## Task 1: scanner_deepverify 히스토리 스토어

**Files:**
- Create: `app/services/mirofish/scanner_deepverify.py`
- Test: `tests/test_scanner_deepverify_store.py`

- [ ] **Step 1: 실패 테스트**

```python
# tests/test_scanner_deepverify_store.py
import os


def _rec(event_key, verified_at, verdict='BUY'):
    return {'event_key': event_key, 'symbol': '005930', 'verified_at': verified_at,
            'verdict': verdict, 'confidence': 60, 'strong_buy': False, 'regime': 'neutral_balanced'}


def test_append_and_read(monkeypatch, tmp_path):
    from app.services.mirofish import scanner_deepverify as sdv
    monkeypatch.setattr(sdv, 'HISTORY_PATH', os.path.join(str(tmp_path), 'h.json'))
    sdv.append_record(_rec('k1', '2026-07-19T01:00:00Z'))
    sdv.append_record(_rec('k2', '2026-07-19T02:00:00Z'))
    data = sdv.read_history()
    assert [r['event_key'] for r in data['records']] == ['k1', 'k2']


def test_history_cap(monkeypatch, tmp_path):
    from app.services.mirofish import scanner_deepverify as sdv
    monkeypatch.setattr(sdv, 'HISTORY_PATH', os.path.join(str(tmp_path), 'h.json'))
    monkeypatch.setattr(sdv, 'HISTORY_MAX', 3)
    for i in range(5):
        sdv.append_record(_rec(f'k{i}', f'2026-07-19T0{i}:00:00Z'))
    keys = [r['event_key'] for r in sdv.read_history()['records']]
    assert keys == ['k2', 'k3', 'k4']       # oldest dropped, newest kept


def test_latest_by_event_key(monkeypatch, tmp_path):
    from app.services.mirofish import scanner_deepverify as sdv
    monkeypatch.setattr(sdv, 'HISTORY_PATH', os.path.join(str(tmp_path), 'h.json'))
    sdv.append_record(_rec('k1', '2026-07-19T01:00:00Z', verdict='HOLD'))
    sdv.append_record(_rec('k1', '2026-07-19T03:00:00Z', verdict='BUY'))  # newer wins
    latest = sdv.latest_by_event_key()
    assert latest['k1']['verdict'] == 'BUY'


def test_history_recent_first(monkeypatch, tmp_path):
    from app.services.mirofish import scanner_deepverify as sdv
    monkeypatch.setattr(sdv, 'HISTORY_PATH', os.path.join(str(tmp_path), 'h.json'))
    sdv.append_record(_rec('k1', '2026-07-19T01:00:00Z'))
    sdv.append_record(_rec('k2', '2026-07-19T05:00:00Z'))
    recent = sdv.history(limit=10)
    assert recent[0]['event_key'] == 'k2'   # newest first


def test_read_history_missing_file(monkeypatch, tmp_path):
    from app.services.mirofish import scanner_deepverify as sdv
    monkeypatch.setattr(sdv, 'HISTORY_PATH', os.path.join(str(tmp_path), 'nope.json'))
    assert sdv.read_history() == {'version': 1, 'records': []}
    assert sdv.latest_by_event_key() == {}
```

- [ ] **Step 2: 실패 확인**

Run: `cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_scanner_deepverify_store.py -q`
Expected: FAIL (ModuleNotFoundError: scanner_deepverify).

- [ ] **Step 3: 구현 (스토어 부분만)**

```python
# app/services/mirofish/scanner_deepverify.py
"""스캐너 신규 이벤트 자동 딥검증(13D 캡처 동시) + 히스토리 누적.

검출 시점에 매수후보 상위 K개를 백그라운드로 TradingAgents 딥검증(Brain 13D 주입)하고,
결과를 append-only 히스토리에 기록한다. 스캐너 폴링 스레드는 절대 블로킹하지 않는다.
env 는 호출 시점 read. 순환 임포트 회피: alpha_scanner 는 lazy import.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any

from app.utils.atomic_json import write_json_atomic

logger = logging.getLogger(__name__)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
HISTORY_PATH = os.path.join(REPO_ROOT, 'data', 'admin_mirofish', 'scanner_tradingagents_history.json')
HISTORY_MAX = 500
BUY_ACTIONS = ('BUY_CANDIDATE', 'BUY')


# ── history store ───────────────────────────────────────────────────

def read_history() -> dict[str, Any]:
    try:
        import json
        with open(HISTORY_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get('records'), list):
            return data
    except (OSError, ValueError):
        pass
    return {'version': 1, 'records': []}


def append_record(record: dict[str, Any]) -> None:
    data = read_history()
    records = data.get('records') or []
    records.append(record)
    if len(records) > HISTORY_MAX:
        records = records[-HISTORY_MAX:]
    data['version'] = 1
    data['records'] = records
    try:
        write_json_atomic(HISTORY_PATH, data, sort_keys=False)
    except Exception as exc:  # noqa: BLE001 — persistence must not raise into caller
        logger.warning('[scanner_deepverify] history write failed: %s', exc)


def latest_by_event_key() -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for rec in read_history().get('records') or []:
        key = str(rec.get('event_key') or '')
        if not key:
            continue
        prev = latest.get(key)
        if prev is None or str(rec.get('verified_at') or '') >= str(prev.get('verified_at') or ''):
            latest[key] = _feed_summary(rec)
    return latest


def history(limit: int = 50) -> list[dict[str, Any]]:
    records = read_history().get('records') or []
    ordered = sorted(records, key=lambda r: str(r.get('verified_at') or ''), reverse=True)
    return ordered[: max(1, int(limit))]


def _feed_summary(rec: dict[str, Any]) -> dict[str, Any]:
    return {
        'verdict': rec.get('verdict'),
        'confidence': rec.get('confidence'),
        'strong_buy': bool(rec.get('strong_buy')),
        'regime': rec.get('regime'),
        'regime_adjustment': rec.get('regime_adjustment'),
        'method': rec.get('method'),
        'ta_run_id': rec.get('ta_run_id'),
        'verified_at': rec.get('verified_at'),
    }
```

- [ ] **Step 4: 통과 확인**

Run: `cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_scanner_deepverify_store.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: 커밋**

```bash
git add app/services/mirofish/scanner_deepverify.py tests/test_scanner_deepverify_store.py
git commit -m "feat(scanner): TradingAgents deep-verify history store"
```

---

## Task 2: 선정 / dedupe / 검증 로직

**Files:**
- Modify: `app/services/mirofish/scanner_deepverify.py`
- Test: `tests/test_scanner_deepverify_verify.py`

- [ ] **Step 1: 실패 테스트**

```python
# tests/test_scanner_deepverify_verify.py
import os


def _ev(symbol, action='BUY_CANDIDATE', alpha=50.0, key=None):
    return {'event_key': key or f'{symbol}:{action}:2026-07-19',
            'candidate': {'symbol': symbol, 'display_name': symbol, 'market': 'KOSPI',
                          'action': action, 'alpha_score': alpha, 'risk_score': 10.0}}


def _patch_deps(monkeypatch, sdv, tmp_path):
    monkeypatch.setattr(sdv, 'HISTORY_PATH', os.path.join(str(tmp_path), 'h.json'))
    import app.services.mirofish.store as store
    import app.services.mirofish.tradingagents.engine as engine
    monkeypatch.setattr(store, '_brain_summary',
                        lambda t: {'regime': 'constructive_bullish', 'alignment_score': 0.8,
                                   'snapshot_at': '2026-07-19T00:00:00Z'})
    calls = {'n': 0}
    def fake_deep(target, *, symbol=None, brain=None, **kw):
        calls['n'] += 1
        return {'id': f'ta_{symbol}', 'method': 'rule',
                'verdict': {'verdict': 'BUY', 'confidence': 70, 'strong_buy': False,
                            'regime': (brain or {}).get('regime'),
                            'regime_adjustment': {'direction': 'bull', 'alignment': 0.8, 'applied': 5.0}}}
    monkeypatch.setattr(engine, 'run_deep_analysis', fake_deep)
    return calls


def test_select_top_k_buy_only(monkeypatch, tmp_path):
    from app.services.mirofish import scanner_deepverify as sdv
    monkeypatch.setattr(sdv, 'HISTORY_PATH', os.path.join(str(tmp_path), 'h.json'))
    monkeypatch.setenv('MIROFISH_TA_SCAN_MAX', '2')
    events = [_ev('A', alpha=10), _ev('B', alpha=90), _ev('C', alpha=50),
              _ev('W', action='WATCH', alpha=99)]
    selected = sdv._select_events(events)
    assert [e['candidate']['symbol'] for e in selected] == ['B', 'C']  # top-2 alpha, WATCH excluded


def test_dedupe_skips_existing(monkeypatch, tmp_path):
    from app.services.mirofish import scanner_deepverify as sdv
    monkeypatch.setattr(sdv, 'HISTORY_PATH', os.path.join(str(tmp_path), 'h.json'))
    sdv.append_record({'event_key': 'B:BUY_CANDIDATE:2026-07-19', 'verified_at': '2026-07-19T01:00:00Z'})
    selected = sdv._select_events([_ev('B', alpha=90), _ev('C', alpha=50)])
    assert [e['candidate']['symbol'] for e in selected] == ['C']  # B already verified


def test_verify_new_events_writes_history(monkeypatch, tmp_path):
    from app.services.mirofish import scanner_deepverify as sdv
    calls = _patch_deps(monkeypatch, sdv, tmp_path)
    sdv._verify_new_events([_ev('B', alpha=90)], {'generated_at': '2026-07-19T00:00:00Z'})
    recs = sdv.read_history()['records']
    assert calls['n'] == 1 and len(recs) == 1
    r = recs[0]
    assert r['symbol'] == 'B' and r['verdict'] == 'BUY' and r['regime'] == 'constructive_bullish'
    assert r['ta_run_id'] == 'ta_B' and r['brain_snapshot_at'] == '2026-07-19T00:00:00Z'


def test_verify_one_isolates_failure(monkeypatch, tmp_path):
    from app.services.mirofish import scanner_deepverify as sdv
    _patch_deps(monkeypatch, sdv, tmp_path)
    import app.services.mirofish.tradingagents.engine as engine
    def boom(*a, **k): raise RuntimeError('llm down')
    monkeypatch.setattr(engine, 'run_deep_analysis', boom)
    sdv._verify_new_events([_ev('B')], {'generated_at': 'x'})  # must not raise
    assert sdv.read_history()['records'] == []


def test_enqueue_killswitch(monkeypatch, tmp_path):
    from app.services.mirofish import scanner_deepverify as sdv
    monkeypatch.setattr(sdv, 'HISTORY_PATH', os.path.join(str(tmp_path), 'h.json'))
    monkeypatch.setenv('MIROFISH_TA_SCAN_DISABLED', 'true')
    fired = {'n': 0}
    monkeypatch.setattr(sdv, '_verify_new_events', lambda ev, run: fired.__setitem__('n', fired['n'] + 1))
    sdv.enqueue_new_events([_ev('B')], {})
    assert fired['n'] == 0  # disabled → no-op
```

- [ ] **Step 2: 실패 확인**

Run: `cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_scanner_deepverify_verify.py -q`
Expected: FAIL (`_select_events`/`_verify_new_events`/`enqueue_new_events` 미정의).

- [ ] **Step 3: 구현 (append_record 아래에 추가)**

```python
# ── env ─────────────────────────────────────────────────────────────

def is_disabled() -> bool:
    return os.getenv('MIROFISH_TA_SCAN_DISABLED', '').strip().lower() in ('1', 'true', 'yes', 'on')


def _max_candidates() -> int:
    try:
        return max(1, int(str(os.getenv('MIROFISH_TA_SCAN_MAX', '3')).strip()))
    except (TypeError, ValueError):
        return 3


# ── selection / verify ──────────────────────────────────────────────

def _event_key(event: dict[str, Any]) -> str:
    key = event.get('event_key')
    if key:
        return str(key)
    from app.services.mirofish.alpha_scanner import _candidate_event_key  # lazy: avoid cycle
    return _candidate_event_key(event.get('candidate') or {})


def _select_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set(latest_by_event_key().keys())
    buy = [e for e in (events or [])
           if str((e.get('candidate') or {}).get('action') or '') in BUY_ACTIONS
           and _event_key(e) not in seen]
    buy.sort(key=lambda e: _num((e.get('candidate') or {}).get('alpha_score')), reverse=True)
    return buy[: _max_candidates()]


def enqueue_new_events(events: list[dict[str, Any]], run: dict[str, Any]) -> None:
    """검출 시점 호출. 킬스위치/무대상이면 즉시 반환. 대상 있으면 백그라운드 스레드로 검증."""
    if is_disabled():
        return
    selected = _select_events(events)
    if not selected:
        return
    threading.Thread(
        target=_verify_new_events, args=(selected, run or {}),
        name='ta-scan-verify', daemon=True,
    ).start()


def _verify_new_events(events: list[dict[str, Any]], run: dict[str, Any]) -> None:
    for event in events:
        try:
            _verify_one(event, run)
        except Exception as exc:  # noqa: BLE001 — isolate per-symbol failure
            logger.warning('[scanner_deepverify] verify failed for %s: %s',
                           (event.get('candidate') or {}).get('symbol'), exc)


def _verify_one(event: dict[str, Any], run: dict[str, Any]) -> None:
    from app.services.mirofish import store  # lazy: avoid heavy import at module load
    from app.services.mirofish.tradingagents import engine

    candidate = event.get('candidate') or {}
    name = candidate.get('display_name') or candidate.get('symbol')
    symbol = candidate.get('symbol')
    if not name:
        return
    try:
        brain = store._brain_summary(name)
    except Exception:  # noqa: BLE001 — brain optional; degrade to no regime
        brain = None
    ta = engine.run_deep_analysis(name, symbol=symbol, brain=brain)
    append_record(_build_record(event, run, brain, ta))


def _build_record(event: dict[str, Any], run: dict[str, Any],
                  brain: dict[str, Any] | None, ta: dict[str, Any]) -> dict[str, Any]:
    candidate = event.get('candidate') or {}
    v = (ta or {}).get('verdict') or {}
    adj = v.get('regime_adjustment') or {}
    return {
        'event_key': _event_key(event),
        'symbol': candidate.get('symbol'),
        'display_name': candidate.get('display_name'),
        'market': candidate.get('market'),
        'detected_at': run.get('generated_at') or event.get('sent_at'),
        'verified_at': datetime.now(timezone.utc).isoformat(),
        'verdict': v.get('verdict'),
        'confidence': v.get('confidence'),
        'strong_buy': bool(v.get('strong_buy')),
        'regime': v.get('regime'),
        'alignment': adj.get('alignment'),
        'regime_adjustment': adj,
        'method': ta.get('method'),
        'ta_run_id': ta.get('id'),
        'brain_snapshot_at': (brain or {}).get('snapshot_at'),
        'alpha_score': candidate.get('alpha_score'),
        'risk_score': candidate.get('risk_score'),
    }


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float('-inf')
```

- [ ] **Step 4: 통과 확인**

Run: `cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_scanner_deepverify_verify.py -q`
Expected: PASS.

- [ ] **Step 5: 커밋**

```bash
git add app/services/mirofish/scanner_deepverify.py tests/test_scanner_deepverify_verify.py
git commit -m "feat(scanner): auto deep-verify selection, 13D capture, dedupe, kill-switch"
```

---

## Task 3: alpha_scanner 훅 (enqueue + feed 머지)

**Files:**
- Modify: `app/services/mirofish/alpha_scanner.py` (`commit_scanner_alert_events`, `_alert_state_summary`)
- Test: `tests/test_scanner_deepverify_hooks.py`

- [ ] **Step 1: 실패 테스트**

```python
# tests/test_scanner_deepverify_hooks.py
def test_commit_enqueues(monkeypatch, tmp_path):
    import os
    from app.services.mirofish import alpha_scanner as sc
    from app.services.mirofish import scanner_deepverify as sdv
    captured = {}
    monkeypatch.setattr(sdv, 'enqueue_new_events', lambda events, run: captured.update(events=events, run=run))
    state_file = os.path.join(str(tmp_path), 'alert.json')
    result = {'state_path': state_file, 'run': {'id': 'r1', 'generated_at': 'x'},
              'events': [{'event_key': 'k1', 'candidate': {'symbol': '005930', 'action': 'BUY_CANDIDATE'}}]}
    sc.commit_scanner_alert_events(result)
    assert captured.get('events') and captured['events'][0]['event_key'] == 'k1'
    assert captured['run']['id'] == 'r1'


def test_summary_merges_tradingagents(monkeypatch):
    from app.services.mirofish import alpha_scanner as sc
    from app.services.mirofish import scanner_deepverify as sdv
    monkeypatch.setattr(sdv, 'latest_by_event_key',
                        lambda: {'005930:BUY_CANDIDATE:2026-07-19': {'verdict': 'BUY', 'confidence': 70,
                                                                     'strong_buy': True, 'regime': 'constructive_bullish'}})
    # a state whose feed entry carries the matching event_key
    state = {'version': 2, 'sent_events': {
        '005930:BUY_CANDIDATE:2026-07-19': {
            'event_key': '005930:BUY_CANDIDATE:2026-07-19', 'symbol': '005930',
            'display_name': '삼성전자', 'market': 'KOSPI', 'action': 'BUY_CANDIDATE',
            'sent_at': __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),
        }}}
    summary = sc._alert_state_summary(state, 'x')
    feed = summary.get('feed_events') or []
    hit = [e for e in feed if e.get('event_key') == '005930:BUY_CANDIDATE:2026-07-19']
    assert hit and hit[0]['tradingagents']['verdict'] == 'BUY'
```

- [ ] **Step 2: 실패 확인**

Run: `cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_scanner_deepverify_hooks.py -q`
Expected: FAIL (enqueue 미호출 / feed entry 에 tradingagents 없음).

- [ ] **Step 3: 구현**

(a) `commit_scanner_alert_events` (≈L788) 의 `write_json_atomic(state_file, updated_state, sort_keys=True)` 다음, `return` 직전에 enqueue 추가:
```python
    write_json_atomic(state_file, updated_state, sort_keys=True)
    try:
        from app.services.mirofish import scanner_deepverify  # lazy: avoid import cycle
        scanner_deepverify.enqueue_new_events(events, run)
    except Exception:  # noqa: BLE001 — enrichment must never break the commit
        pass
    return _alert_state_summary(updated_state, state_file)
```

(b) `_alert_state_summary` (≈L4074) 의 `feed = _merge_alert_history(recent_for_feed, [], limit=20)` 다음에 머지 루프 추가(그 아래 `return {...}` 의 `'feed_events': feed,` 는 그대로):
```python
    feed = _merge_alert_history(recent_for_feed, [], limit=20)
    try:
        from app.services.mirofish import scanner_deepverify  # lazy: avoid import cycle
        ta_latest = scanner_deepverify.latest_by_event_key()
        if ta_latest:
            for entry in feed:
                summary = ta_latest.get(str(entry.get('event_key') or ''))
                if summary:
                    entry['tradingagents'] = summary
    except Exception:  # noqa: BLE001 — read-only enrichment, never break the feed
        pass
```

- [ ] **Step 4: 통과 확인**

Run: `cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_scanner_deepverify_hooks.py -q`
Expected: PASS.

- [ ] **Step 5: 커밋**

```bash
git add app/services/mirofish/alpha_scanner.py tests/test_scanner_deepverify_hooks.py
git commit -m "feat(scanner): enqueue auto deep-verify on commit + merge verdict into feed"
```

---

## Task 4: 히스토리 엔드포인트

**Files:**
- Modify: `app/routes/admin_mirofish_tradingagents.py`
- Test: `tests/test_admin_mirofish_tradingagents_routes.py` (추가)

- [ ] **Step 1: 실패 테스트 추가**

```python
# tests/test_admin_mirofish_tradingagents_routes.py 하단에 추가 (admin_client 픽스처 재사용)
def test_scanner_ta_history_endpoint(monkeypatch, admin_client):
    import app.routes.admin_mirofish_tradingagents as rt
    from app.services.mirofish import scanner_deepverify as sdv
    monkeypatch.setattr(sdv, 'history', lambda limit=50: [{'event_key': 'k1', 'symbol': '005930', 'verdict': 'BUY'}])
    resp = admin_client.get('/api/admin/mirofish/scanner/tradingagents/history?limit=10')
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['count'] == 1 and body['records'][0]['symbol'] == '005930'
```

- [ ] **Step 2: 실패 확인**

Run: `cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_admin_mirofish_tradingagents_routes.py -q -k history`
Expected: FAIL (404 — route 없음).

- [ ] **Step 3: 구현**

`admin_mirofish_tradingagents.py` 상단 import 에 추가:
```python
from app.services.mirofish import scanner_deepverify
```
파일 끝에 라우트 추가:
```python
@admin_mirofish_tradingagents_bp.route('/scanner/tradingagents/history', methods=['GET'])
@admin_or_aibain_required
def scanner_history():
    """스캐너 이벤트 자동 딥검증 히스토리(최근순)."""
    try:
        limit = int(request.args.get('limit', 50))
    except (TypeError, ValueError):
        return jsonify({'error': 'limit must be an integer'}), 400
    limit = max(1, min(limit, 200))
    records = scanner_deepverify.history(limit=limit)
    return jsonify({'records': records, 'count': len(records)}), 200
```

- [ ] **Step 4: 통과 확인**

Run: `cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/test_admin_mirofish_tradingagents_routes.py -q`
Expected: PASS.

- [ ] **Step 5: 커밋**

```bash
git add app/routes/admin_mirofish_tradingagents.py tests/test_admin_mirofish_tradingagents_routes.py
git commit -m "feat(scanner): GET scanner TradingAgents deep-verify history endpoint"
```

---

## Task 5: 프론트 — 카드 행 verdict 블록

**Files:**
- Modify: `frontend-react/src/lib/mirofishApi.ts` (이벤트 타입에 `tradingagents?`)
- Modify: `frontend-react/src/components/admin/ScannerEventsCard.tsx` (`ScannerEventRow` 에 블록)

- [ ] **Step 1: 타입 추가 (`mirofishApi.ts`)**

`MiroFishScannerAlertEvent` 인터페이스를 찾아(READ 로 확인), 필드 추가:
```typescript
    tradingagents?: {
        verdict: string;
        confidence: number;
        strong_buy: boolean;
        regime?: string;
        regime_adjustment?: { direction?: string; alignment?: number | null; applied?: number };
        method?: string;
        verified_at?: string;
    };
```
(인터페이스의 기존 필드들 사이 어디든, 마지막 필드 뒤에 추가.)

- [ ] **Step 2: 카드 렌더 (`ScannerEventsCard.tsx`)**

`ScannerEventRow` 컴포넌트에서 `event.deepseek_brief` 블록(≈L396-404) 바로 위 또는 아래에 TA 블록 추가. 파일 상단(다른 상수 근처)에 verdict 스타일 맵 추가:
```tsx
const TA_VERDICT_STYLE: Record<string, string> = {
    STRONG_BUY: 'border-emerald-300/40 bg-emerald-300/10 text-emerald-200',
    BUY: 'border-sky-300/40 bg-sky-300/10 text-sky-200',
    HOLD: 'border-white/15 bg-white/[0.06] text-slate-300',
    SELL: 'border-rose-300/40 bg-rose-300/10 text-rose-200',
};
```
`ScannerEventRow` 의 return JSX 안, deepseek_brief 블록 근처에 삽입:
```tsx
{event.tradingagents && (
    <div className="mt-2 flex flex-wrap items-center gap-2 rounded-lg border border-cyan-300/15 bg-cyan-300/[0.04] px-2.5 py-2">
        <i className="fas fa-shield-halved text-[10px] text-cyan-300" aria-hidden="true" />
        <span className={`rounded-md border px-1.5 py-0.5 text-[10px] font-black ${TA_VERDICT_STYLE[event.tradingagents.verdict] || TA_VERDICT_STYLE.HOLD}`}>
            {event.tradingagents.verdict}
        </span>
        <span className="text-[10px] font-bold text-slate-400">확신 {Math.round(event.tradingagents.confidence)}%</span>
        {event.tradingagents.strong_buy && <span className="text-[10px] font-black text-orange-300">🔥 매수유력</span>}
        {event.tradingagents.regime && (
            <span className="text-[10px] font-semibold text-slate-500">
                레짐 {event.tradingagents.regime}
                {event.tradingagents.regime_adjustment?.applied
                    ? ` · 보정 ${event.tradingagents.regime_adjustment.applied > 0 ? '+' : ''}${event.tradingagents.regime_adjustment.applied}`
                    : ''}
            </span>
        )}
        <span className="ml-auto text-[9px] font-bold uppercase tracking-wider text-cyan-300/70">TradingAgents</span>
    </div>
)}
```

- [ ] **Step 3: 빌드 검증**

Run: `cd "$PROJECT/frontend-react" && npx tsc --noEmit && npm run build 2>&1 | tail -6`
Expected: 타입 에러 0, 빌드 성공.

- [ ] **Step 4: 커밋**

```bash
cd "$PROJECT"
git add frontend-react/src/lib/mirofishApi.ts frontend-react/src/components/admin/ScannerEventsCard.tsx
git commit -m "feat(ui): show auto deep-verify verdict on scanner event cards"
```

---

## Task 6: 전체 회귀 + 통합 스모크 + 배포

**Files:** (검증/배포)

- [ ] **Step 1: 전체 회귀**

Run:
```bash
cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest tests/ -q -k "scanner or tradingagents or mirofish or atomic or workflow" 2>&1 | tail -8
```
Expected: 전부 PASS.

- [ ] **Step 2: 오프라인 통합 스모크 (enqueue → history → feed 머지)**

Run:
```bash
cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -c "
import os, tempfile
os.environ['MIROFISH_TA_SCAN_MAX']='1'
from app.services.mirofish import scanner_deepverify as sdv
sdv.HISTORY_PATH = os.path.join(tempfile.mkdtemp(), 'h.json')
import app.services.mirofish.store as store, app.services.mirofish.tradingagents.engine as engine
store._brain_summary = lambda t: {'regime':'constructive_bullish','alignment_score':0.8,'snapshot_at':'t'}
engine.run_deep_analysis = lambda target, *, symbol=None, brain=None, **k: {'id':'ta1','method':'rule','verdict':{'verdict':'BUY','confidence':70,'strong_buy':False,'regime':(brain or {}).get('regime'),'regime_adjustment':{'applied':5.0,'alignment':0.8,'direction':'bull'}}}
ev=[{'event_key':'B:BUY_CANDIDATE:2026-07-19','candidate':{'symbol':'B','display_name':'B','market':'KOSPI','action':'BUY_CANDIDATE','alpha_score':90}}]
sdv._verify_new_events(ev, {'generated_at':'2026-07-19T00:00:00Z'})
print('history=', len(sdv.read_history()['records']), '| latest=', sdv.latest_by_event_key().get('B:BUY_CANDIDATE:2026-07-19',{}).get('verdict'))
"
```
Expected: `history= 1 | latest= BUY`.

- [ ] **Step 3: 배포 (사용자 승인 하에)**

> ⚠ 백엔드 변경 → miniPC 는 [[feedback_minipc_flask_restart_hazard]] 준수: kill 금지, **재부팅**으로 활성화.
> 프론트 → `cd frontend-react && npm run deploy`. git 은 이번 세션 방식(수정만 origin/main 반영)으로.

배포 절차/시점은 실행 시 사용자 확인 후.

- [ ] **Step 4: 라이브 검증 (실행 중 Flask)**

miniPC 실행 중 Flask 에서: (a) `GET /api/admin/mirofish/scanner/tradingagents/history` → 200 + records 구조,
(b) 스캐너가 신규 매수후보를 낸 사이클 이후 `read_scanner_alert_state().feed_events` 일부에 `tradingagents` 부착 확인(또는 수동으로 `scanner_deepverify.enqueue_new_events` 호출 후 히스토리·머지 확인). admin 토큰은 running Flask 시크릿으로 생성.

---

## Self-Review 결과

- **스펙 커버리지**: §2 트리거(T3 훅a) / §3.1 검증로직(T2) / §3.2 히스토리 스토어(T1) / §3.3 feed 머지(T3 훅b) / §3.4 엔드포인트(T4) / §3.5 프론트(T5) / §4 env(T2) / §5 안전장치(킬스위치·dedupe·백그라운드·격리·원자적 = T1/T2/T3) / §6 테스트(각 태스크 + T6) — 전 항목 매핑.
- **플레이스홀더**: 없음(코드 전량). FE 인터페이스/삽입 위치만 READ 확인 지시(자기완결 블록).
- **타입 일관성**: `HISTORY_PATH`/`HISTORY_MAX`/`read_history`/`append_record`/`latest_by_event_key`/`history` T1 정의 = T2/T3/T4 사용 일치. `enqueue_new_events(events, run)`/`_verify_new_events`/`_select_events` T2 정의 = T3 훅/테스트 호출 일치. `latest_by_event_key()[event_key]` 요약 키(verdict/confidence/strong_buy/regime/regime_adjustment/method/ta_run_id/verified_at) T1 `_feed_summary` = T3 머지 = T5 FE 타입 일치. 엔드포인트 `history(limit)` T1 = T4 사용 일치.

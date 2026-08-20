# Alpha Service Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 관리자 알파 스캐너 보드에 실제 저장 데이터로 채워지는 5단계 `Alpha Service Clock`을 추가하고, 이를 한 번에 제공하는 인증된 읽기 전용 API를 구현한다.

**Architecture:** Flask 서비스 조합기가 기존 스캐너·시장 국면·가상 포지션·운영 파이프라인·outcome 산출물을 독립적으로 읽어 고정된 다섯 카드 계약으로 정규화한다. React 컴포넌트는 이 단일 계약만 조회하며, 기존 운영 레인의 새로고침 remount와 화면이 보일 때만 동작하는 60초 갱신을 사용한다.

**Tech Stack:** Python 3 + Flask + pytest / React 18 + TypeScript + Vite + Vitest + Testing Library + Tailwind CSS

**Spec:** `docs/superpowers/specs/2026-08-18-alpha-service-dashboard-design.md`

## Global Constraints

- 조회 경로에서 스캐너 실행, KIS/OpenDART/KRX/LLM 호출, 주문, Telegram 발송, 파일 쓰기 또는 outcome 갱신을 실행하지 않는다.
- 수치·종목·성과는 기존 저장 산출물 또는 결정론적 계산에서만 가져온다. 알 수 없는 값은 `null`로 둔다.
- 최신 현재 입력의 신선도와 최신 비어 있지 않은 후보 실행의 신선도를 섞지 않는다.
- `admin_or_aibain_required` 권한을 유지하고 응답은 `Cache-Control: no-store`로 제공한다.
- UI 제품명은 `Alpha Service Clock`을 사용한다. AlphaCatch 상표, 비공개 산식, 원본 문구·레이아웃을 복제하지 않는다.
- 기존 관리자 보드의 다크 운영 UI를 따르되, 실제 시간 순서를 표현하는 세로 서비스 레일을 고유 시각 요소로 사용한다.
- Spring `backend/`는 수정하거나 실행하지 않는다.
- 현재 worktree의 사용자 소유 변경(`frontend-react/package-lock.json`, 생성 데이터/백업)을 수정하거나 되돌리지 않는다.
- 사용자는 commit, push, deploy를 요청하지 않았다. 모든 Task의 commit 단계는 의도적으로 생략한다.
- 모든 파일 수정은 `apply_patch`로 수행하고 RED → GREEN → REFACTOR 순서를 지킨다.

## File Structure

| 파일 | 책임 |
|---|---|
| `app/services/mirofish/alpha_scanner.py` | 최신 비어 있지 않은 실행의 provenance를 compact 응답에 보존 |
| `app/services/mirofish/paper_orchestrator.py` | 이미 읽은 로컬 종가의 기준일을 포지션 응답에 보존 |
| `app/services/mirofish/alpha_dashboard.py` | 6개 읽기 소스를 격리해 5개 서비스 카드 계약으로 정규화 |
| `app/services/mirofish/__init__.py` | 조합기 공개 export |
| `app/routes/admin_mirofish.py` | 엄격한 쿼리 검증과 인증 GET 라우트 |
| `tests/test_mirofish_alpha_dashboard.py` | 조합기·상태·무부작용·라우트 계약 |
| `tests/test_admin_mirofish_alpha_scanner.py` | latest-nonempty provenance 회귀 |
| `tests/test_paper_orchestrator.py` | `last_close_date` 회귀 |
| `frontend-react/src/lib/mirofishApi.ts` | API 응답 discriminated union 타입과 조회 메서드 |
| `frontend-react/src/components/admin/AlphaServiceDashboard.tsx` | 5단계 서비스 시계, 상태, 오류, 갱신 수명주기 |
| `frontend-react/src/test/alphaServiceDashboard.test.tsx` | 독립 컴포넌트 계약과 타이머 회귀 |
| `frontend-react/src/pages/admin/AdminEndpointsPage.tsx` | 기존 우측 운영 레인 최상단 마운트 |
| `frontend-react/src/test/adminEndpointsEnter.test.tsx` | 기존 보드와 신규 대시보드 공존 회귀 |

---

### Task 1: 기존 읽기 소스의 provenance 보존

**Files:**
- Modify: `tests/test_admin_mirofish_alpha_scanner.py:915-956`
- Modify: `app/services/mirofish/alpha_scanner.py:310-348`
- Modify: `tests/test_paper_orchestrator.py:74-80`
- Modify: `app/services/mirofish/paper_orchestrator.py:328-343`

**Interfaces:**
- Produces: `read_latest_scanner_candidates(limit)` 응답에 `source`, `freshness`, `source_files`
- Produces: `paper_overview().open_positions[].last_close_date: str | None`
- Preserves: 기존 함수 시그니처와 기존 응답 필드

- [ ] **Step 1: 후보 실행 provenance가 사라지는 회귀 테스트 작성**

`test_latest_scanner_candidates_skips_empty_run_and_returns_compact_top_five`가 만드는 과거 non-empty 실행에 다음 필드를 넣고 반환값을 검증한다.

```python
older_run.update({
    'source': 'local_marketflow_artifacts',
    'freshness': {'status': 'stale', 'stale_files': 2},
    'source_files': [
        {'file': 'daily_prices.csv', 'freshness': 'stale', 'as_of': '2026-08-17'},
    ],
})

payload = alpha_scanner.read_latest_scanner_candidates(limit=5)

assert payload['run_id'] == older_run['id']
assert payload['source'] == 'local_marketflow_artifacts'
assert payload['freshness'] == {'status': 'stale', 'stale_files': 2}
assert payload['source_files'][0]['file'] == 'daily_prices.csv'
```

이 테스트가 잡는 고장: 최신 빈 실행을 건너뛴 뒤 현재 입력 또는 다른 실행의 신선도를 후보에 붙이는 변경.

- [ ] **Step 2: RED 확인**

Run:

```powershell
python -m pytest tests/test_admin_mirofish_alpha_scanner.py::test_latest_scanner_candidates_skips_empty_run_and_returns_compact_top_five -q
```

Expected: `KeyError: 'source'` 또는 `KeyError: 'freshness'`.

- [ ] **Step 3: compact 응답에 선택된 실행의 provenance를 그대로 추가**

`read_latest_scanner_candidates()`의 반환 dict에 다음 세 필드만 추가한다.

```python
return {
    'run_id': run.get('id') or run.get('run_id'),
    'status': run.get('status'),
    'generated_at': run.get('generated_at'),
    'source': run.get('source'),
    'freshness': run.get('freshness'),
    'source_files': run.get('source_files') or [],
    'candidate_count': len(candidates),
    'candidates': compact_candidates,
}
```

`get_scanner_schedule_status()`는 호출하지 않는다.

- [ ] **Step 4: 포지션 가격 기준일의 실패 테스트 작성**

`tests/test_paper_orchestrator.py`에 ledger와 feed를 함수 경계에서 대체하는 테스트를 추가한다.

```python
def test_paper_overview_preserves_last_close_date(monkeypatch):
    ledger = {
        'pending': [],
        'open': [{
            'symbol': '005930', 'name': '삼성전자',
            'entry_date': '2026-08-18', 'entry_price': 70000,
            'target_price': 75600, 'stop_price': 65100,
        }],
        'closed': [],
    }
    rows = [
        {'date': '2026-08-18', 'open': 70000, 'high': 71000, 'low': 69500, 'close': 70500},
        {'date': '2026-08-19', 'open': 70600, 'high': 72000, 'low': 70400, 'close': 71500},
    ]
    monkeypatch.setattr(po.pp, 'load_ledger', lambda: ledger)
    monkeypatch.setattr(po.pp, 'performance_summary', lambda days: {
        'window_days': days, 'trades': 0, 'win_rate_pct': 0.0,
        'avg_return_pct': 0.0, 'cumulative_return_pct': 0.0,
        'recent': [], 'open_count': 1,
    })
    monkeypatch.setattr(po, 'load_price_feed', lambda symbols: lambda symbol: rows)
    monkeypatch.setattr(po, 'market_phase', lambda: {
        'phase': 'leader_market', 'phase_label': '주도주 장세',
        'regime': 'NEUTRAL', 'breadth': 0.51, 'as_of': '2026-08-19',
    })

    position = po.paper_overview()['open_positions'][0]

    assert position['last_close'] == 71500
    assert position['last_close_date'] == '2026-08-19'
```

빈 가격 행 케이스도 별도 테스트로 추가해 `last_close_date is None`을 확인한다.

- [ ] **Step 5: RED 확인 후 최소 구현**

Run:

```powershell
python -m pytest tests/test_paper_orchestrator.py::test_paper_overview_preserves_last_close_date -q
```

Expected: `KeyError: 'last_close_date'`.

`paper_overview()`의 position dict에 다음을 추가한다.

```python
'last_close_date': str(rows[-1].get('date') or '').strip() or None if rows else None,
```

- [ ] **Step 6: Task 1 GREEN 확인**

```powershell
python -m pytest tests/test_admin_mirofish_alpha_scanner.py::test_latest_scanner_candidates_skips_empty_run_and_returns_compact_top_five tests/test_paper_orchestrator.py -q
```

Expected: 모두 PASS.

---

### Task 2: 5단계 백엔드 조합기의 정상·빈·오래된 계약

**Files:**
- Create: `tests/test_mirofish_alpha_dashboard.py`
- Create: `app/services/mirofish/alpha_dashboard.py`

**Interfaces:**
- Consumes: Task 1의 후보 provenance와 `last_close_date`
- Produces: `get_alpha_service_dashboard(candidate_limit=5, outcome_days=30, outcome_limit=10, now=None) -> dict[str, Any]`
- Produces: 정확히 `market_brief`, `score_leaders`, `intraday_flow`, `trade_signals`, `performance_brief` 순서

- [ ] **Step 1: hand-derived 정상 소스 fixture와 실패 테스트 작성**

`tests/test_mirofish_alpha_dashboard.py`에서 실제 조합기를 호출하되 파일/외부 경계만 monkeypatch한다.

```python
from datetime import datetime, timedelta, timezone

from app.services.mirofish import alpha_dashboard

KST = timezone(timedelta(hours=9))


def _install_ready_sources(monkeypatch):
    monkeypatch.setattr(alpha_dashboard.paper_orchestrator, 'market_phase', lambda: {
        'phase': 'uptrend_broadening',
        'phase_label': '상승 추세 확산',
        'regime': 'RISK_ON',
        'breadth': 0.542,
        'breadth_change_5d': 0.031,
        'as_of': '2026-08-19',
    })
    monkeypatch.setattr(alpha_dashboard.alpha_scanner, 'get_scanner_schedule_status', lambda now=None: {
        'enabled': True,
        'freshness': {'status': 'fresh'},
        'freshness_status': 'fresh',
        'source_files': [{'file': 'daily_prices.csv', 'freshness': 'fresh'}],
        'checked_at': '2026-08-20T08:40:00+09:00',
    })
    monkeypatch.setattr(alpha_dashboard.alpha_scanner, 'read_latest_scanner_candidates', lambda limit=5: {
        'run_id': 'scan_nonempty_1',
        'status': 'completed',
        'generated_at': '2026-08-20T08:30:00+09:00',
        'source': 'local_marketflow_artifacts',
        'freshness': {'status': 'fresh'},
        'source_files': [{'file': 'daily_prices.csv', 'freshness': 'fresh'}],
        'candidate_count': 1,
        'candidates': [{
            'rank': 1, 'symbol': '005930', 'name': '삼성전자',
            'display_name': '삼성전자', 'market': 'KOSPI',
            'alpha_score': 87.4, 'risk_score': 21.0,
            'action': 'BUY_CANDIDATE', 'horizon': '5d', 'price': 71500,
        }][:limit],
    })
    monkeypatch.setattr(alpha_dashboard.paper_orchestrator, 'paper_overview', lambda: {
        'generated_at': '2026-08-20T00:01:00+00:00',
        'phase': {'phase': 'uptrend_broadening'},
        'open_positions': [{
            'symbol': '005930', 'name': '삼성전자',
            'entry_price': 70000, 'target_price': 75600, 'stop_price': 65100,
            'last_close': 71500, 'last_close_date': '2026-08-19',
            'unrealized_pct': 2.14, 'held_trading_days': 2,
        }],
        'pending': [{'symbol': '000660', 'name': 'SK하이닉스'}],
        'performance': {
            'window_days': 30, 'trades': 4, 'win_rate_pct': 75.0,
            'avg_return_pct': 2.5, 'cumulative_return_pct': 10.2,
            'recent': [], 'open_count': 1,
        },
        'rules': {'target_pct': 8.0, 'stop_pct': -7.0, 'max_hold_trading_days': 8},
        'disabled': False,
    })
    monkeypatch.setattr(alpha_dashboard.pipeline_overview, 'get_pipeline_operating_snapshot', lambda now=None: {
        'schema_version': 'mirofish.operating_workflow.v1',
        'generated_at': '2026-08-20T00:01:00+00:00',
        'date_kst': '2026-08-20',
        'workflow_id': 'wf_1',
        'workflow_status': 'completed',
        'current_stage_id': 'outcomes',
        'overall_status': 'ready',
        'stages': [{'id': 'top3', 'status': 'complete', 'count': 3, 'updated_at': '2026-08-20T06:00:00+00:00'}],
    })
    monkeypatch.setattr(alpha_dashboard.pipeline_overview, 'get_outcomes_board', lambda days=30, limit=10: {
        'window_days': days,
        'generated_at': '2026-08-20T00:02:00+00:00',
        'sample_size': 6,
        'workflow_count': 3,
        'summary': {
            'hit_count': 4, 'miss_count': 2, 'hit_rate_pct': 66.67,
            'avg_forward_return_pct': 3.1,
        },
        'items': [],
    })


def test_dashboard_normalizes_five_source_backed_services(monkeypatch):
    _install_ready_sources(monkeypatch)

    result = alpha_dashboard.get_alpha_service_dashboard(
        candidate_limit=5,
        outcome_days=30,
        outcome_limit=10,
        now=datetime(2026, 8, 20, 8, 40, tzinfo=KST),
    )

    assert result['schema_version'] == 'mirofish.alpha_service_dashboard.v1'
    assert result['date_kst'] == '2026-08-20'
    assert [service['id'] for service in result['services']] == [
        'market_brief', 'score_leaders', 'intraday_flow',
        'trade_signals', 'performance_brief',
    ]
    market = result['services'][0]
    assert [(metric['key'], metric['value'], metric['unit']) for metric in market['metrics']] == [
        ('breadth', 54.2, '%'),
        ('breadth_change_5d', 3.1, '%p'),
    ]
    leaders = result['services'][1]
    assert leaders['items'][0]['symbol'] == '005930'
    assert leaders['provenance']['sources'][0]['run_id'] == 'scan_nonempty_1'
    assert result['services'][2]['items'][0]['last_close_date'] == '2026-08-19'
    performance = result['services'][4]['items']
    assert [item['source'] for item in performance] == ['paper_30d', 'workflow_outcomes']
    assert performance[0]['sample_count'] == 4
    assert performance[1]['sample_count'] == 6
```

이 테스트가 잡는 고장: 서비스 순서 변경, 비율/% 변환 오류, 후보 실행 ID 손실, paper/outcome 성과 혼합.

- [ ] **Step 2: RED 확인**

```powershell
python -m pytest tests/test_mirofish_alpha_dashboard.py::test_dashboard_normalizes_five_source_backed_services -q
```

Expected: `ImportError` 또는 `ModuleNotFoundError` for `alpha_dashboard`.

- [ ] **Step 3: 조합기 상수·일정·공통 shape 구현**

`app/services/mirofish/alpha_dashboard.py`에 다음 공개 함수와 deterministic helpers를 만든다.

```python
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

from app.services.mirofish import alpha_scanner, paper_orchestrator, pipeline_overview

KST = ZoneInfo('Asia/Seoul')
SCHEMA_VERSION = 'mirofish.alpha_service_dashboard.v1'
STALE_AFTER_CALENDAR_DAYS = 3


def _current_kst(now: datetime | None) -> datetime:
    current = now or datetime.now(KST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=KST)
    return current.astimezone(KST)


def _point_schedule(current: datetime, hour: int, minute: int, label: str) -> dict[str, Any]:
    start = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    phase = 'upcoming' if current < start else 'due' if current < start + timedelta(minutes=15) else 'elapsed'
    return {
        'label': label,
        'time_kst': f'{hour:02d}:{minute:02d}',
        'phase': phase,
        'calendar_status': 'unverified',
    }


def _intraday_schedule(current: datetime) -> dict[str, Any]:
    start = current.replace(hour=9, minute=0, second=0, microsecond=0)
    end = current.replace(hour=15, minute=30, second=0, microsecond=0)
    phase = 'upcoming' if current < start else 'due' if current < end else 'elapsed'
    return {
        'label': '장중', 'time_kst': None,
        'phase': phase, 'calendar_status': 'unverified',
    }
```

`_safe_read(name, fn, warnings)`는 `{ok, data, error}` 형태를 반환하고 `Exception`의 클래스명만 경고 code에 사용한다. 사용자 응답에 경로·stack trace를 넣지 않는다.

- [ ] **Step 4: 다섯 카드 builder와 최상위 상태 구현**

각 builder는 공통 필드 `id/order/title/description/schedule/data_status/as_of/summary/metrics/items/warnings/provenance`를 항상 반환한다.

구현 규칙:

```python
SERVICE_IDS = (
    'market_brief', 'score_leaders', 'intraday_flow',
    'trade_signals', 'performance_brief',
)

FRESH_STATUSES = {'fresh', 'ready', 'ok'}
STALE_STATUSES = {'stale', 'missing', 'partial', 'unknown'}
```

- `market_brief`: `as_of` 없음 또는 오늘과 3일 초과 차이면 stale. `breadth`/변화는 `round(raw * 100, 1)`. `leading_sectors_unavailable`는 severity `info`이고 상태를 낮추지 않는다.
- `score_leaders`: 후보 없음이면 empty. `alpha_score`나 `risk_score`가 dict면 `.get('value')`만 사용한다. 후보 실행 `freshness.status`가 `fresh`가 아니면 stale. 현재 입력 schedule은 별도 provenance source로 둔다.
- `intraday_flow`: open position 없음이면 empty. `last_close_date` 없음/3일 초과면 stale이고 `unrealized_pct`를 `null`로 반환한다.
- `trade_signals`: `pending`, `open`, `paper_30d_closed`, pipeline stage count를 `items`로 반환한다. 두 소스가 정상이고 숫자가 실제 0인 것은 ready 운영 상태이며 거짓 성과가 아니다.
- `performance_brief`: `paper_30d`와 `workflow_outcomes` item을 분리한다. 각 sample count가 0이면 비율/수익률은 `null`; 둘 다 0이면 empty.
- 소스 예외가 있으면 관련 카드는 partial. 핵심 데이터 전무는 empty. usable card의 provenance stale/unknown은 stale.
- 최상위 우선순위: any source exception → partial, core usable data 전무 → empty, any partial card → partial, any stale card → stale, else ready.

공개 함수는 각 public source function을 조합기에서 한 번씩 직접 호출한다. 기존 source
function 내부의 read-only 하위 집계는 변경하지 않는다.

```python
def get_alpha_service_dashboard(
    candidate_limit: int = 5,
    outcome_days: int = 30,
    outcome_limit: int = 10,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = _current_kst(now)
    warnings: list[dict[str, Any]] = []
    phase = _safe_read('market_phase', paper_orchestrator.market_phase, warnings)
    schedule = _safe_read(
        'scanner_schedule',
        lambda: alpha_scanner.get_scanner_schedule_status(now=current),
        warnings,
    )
    leaders = _safe_read(
        'latest_nonempty_run',
        lambda: alpha_scanner.read_latest_scanner_candidates(limit=candidate_limit),
        warnings,
    )
    paper = _safe_read('paper_overview', paper_orchestrator.paper_overview, warnings)
    pipeline = _safe_read(
        'pipeline_operating_snapshot',
        lambda: pipeline_overview.get_pipeline_operating_snapshot(now=current),
        warnings,
    )
    outcomes = _safe_read(
        'workflow_outcomes',
        lambda: pipeline_overview.get_outcomes_board(days=outcome_days, limit=outcome_limit),
        warnings,
    )
    services = _build_services(current, phase, schedule, leaders, paper, pipeline, outcomes)
    return {
        'schema_version': SCHEMA_VERSION,
        'generated_at': current.isoformat(),
        'timezone': 'Asia/Seoul',
        'date_kst': current.date().isoformat(),
        'status': _overall_status(services, phase, leaders, paper, outcomes),
        'services': services,
        'warnings': warnings,
        'links': {
            'scanner_latest': '/api/admin/mirofish/scanner/runs/latest',
            'outcomes_board': '/api/admin/mirofish/outcomes/board',
            'paper_overview': '/api/admin/mirofish/paper/overview',
            'pipeline_today': '/api/admin/mirofish/pipeline/today',
        },
    }
```

- [ ] **Step 5: 정상 계약 GREEN 확인**

```powershell
python -m pytest tests/test_mirofish_alpha_dashboard.py::test_dashboard_normalizes_five_source_backed_services -q
```

Expected: PASS.

- [ ] **Step 6: 빈 데이터와 stale 상태의 실패 테스트 추가**

정상 fixture를 덮어써 두 독립 테스트를 만든다.

```python
def test_dashboard_marks_no_trade_samples_empty_instead_of_zero_success(monkeypatch):
    _install_ready_sources(monkeypatch)
    monkeypatch.setattr(alpha_dashboard.alpha_scanner, 'read_latest_scanner_candidates', lambda limit=5: None)
    monkeypatch.setattr(alpha_dashboard.paper_orchestrator, 'paper_overview', lambda: {
        'generated_at': '2026-08-20T00:00:00+00:00',
        'phase': {}, 'open_positions': [], 'pending': [],
        'performance': {
            'window_days': 30, 'trades': 0, 'win_rate_pct': 0.0,
            'avg_return_pct': 0.0, 'cumulative_return_pct': 0.0,
            'recent': [], 'open_count': 0,
        },
        'rules': {}, 'disabled': False,
    })
    monkeypatch.setattr(alpha_dashboard.pipeline_overview, 'get_outcomes_board', lambda days=30, limit=10: {
        'window_days': days, 'generated_at': '2026-08-20T00:00:00+00:00',
        'sample_size': 0, 'workflow_count': 0,
        'summary': {'hit_count': 0, 'miss_count': 0, 'hit_rate_pct': None, 'avg_forward_return_pct': None},
        'items': [],
    })

    result = alpha_dashboard.get_alpha_service_dashboard(now=datetime(2026, 8, 20, 19, 0, tzinfo=KST))

    assert result['status'] == 'empty'
    assert result['services'][1]['data_status'] == 'empty'
    performance = result['services'][4]
    assert performance['data_status'] == 'empty'
    assert all(item['win_rate'] is None for item in performance['items'])


def test_dashboard_keeps_latest_nonempty_run_stale_provenance(monkeypatch):
    _install_ready_sources(monkeypatch)
    stale = alpha_dashboard.alpha_scanner.read_latest_scanner_candidates()
    stale['freshness'] = {'status': 'stale'}
    monkeypatch.setattr(alpha_dashboard.alpha_scanner, 'read_latest_scanner_candidates', lambda limit=5: stale)

    result = alpha_dashboard.get_alpha_service_dashboard(now=datetime(2026, 8, 20, 8, 40, tzinfo=KST))

    leaders = next(service for service in result['services'] if service['id'] == 'score_leaders')
    assert leaders['data_status'] == 'stale'
    assert leaders['provenance']['sources'][0]['run_id'] == 'scan_nonempty_1'
    assert result['status'] == 'stale'
```

- [ ] **Step 7: RED → GREEN 반복 후 Task 2 전체 통과**

```powershell
python -m pytest tests/test_mirofish_alpha_dashboard.py -q
```

Expected: Task 2 테스트 모두 PASS.

---

### Task 3: 부분 실패 격리와 조회 무부작용 계약

**Files:**
- Modify: `tests/test_mirofish_alpha_dashboard.py`
- Modify: `app/services/mirofish/alpha_dashboard.py`

**Interfaces:**
- Preserves: Task 2의 공개 응답 계약
- Enforces: 한 읽기 소스 실패가 전체 500으로 전파되지 않음
- Enforces: 조회가 실행·갱신·쓰기 함수에 도달하지 않음

- [ ] **Step 1: 소스 하나의 예외를 격리하는 실패 테스트 작성**

```python
def test_dashboard_isolates_one_source_failure(monkeypatch):
    _install_ready_sources(monkeypatch)

    def fail_paper():
        raise ValueError('corrupt ledger path must not leak')

    monkeypatch.setattr(alpha_dashboard.paper_orchestrator, 'paper_overview', fail_paper)

    result = alpha_dashboard.get_alpha_service_dashboard(now=datetime(2026, 8, 20, 15, 20, tzinfo=KST))

    assert result['status'] == 'partial'
    assert len(result['services']) == 5
    assert next(s for s in result['services'] if s['id'] == 'score_leaders')['data_status'] == 'ready'
    assert next(s for s in result['services'] if s['id'] == 'intraday_flow')['data_status'] == 'partial'
    assert result['warnings'] == [{
        'section': 'paper_overview',
        'code': 'source_read_failed',
        'message': 'paper_overview 데이터를 읽지 못했습니다.',
        'severity': 'error',
    }]
    assert 'corrupt ledger path' not in str(result)
```

- [ ] **Step 2: RED 확인 후 `_safe_read`와 카드 partial 분기 수정**

```powershell
python -m pytest tests/test_mirofish_alpha_dashboard.py::test_dashboard_isolates_one_source_failure -q
```

Expected: 예외 전파 또는 경고 shape 불일치로 FAIL. 경고 message는 고정 문구를 사용해 내부 예외를 숨긴다.

- [ ] **Step 3: 금지 함수가 호출되지 않는 회귀 테스트 작성**

```python
def test_dashboard_read_path_never_runs_or_writes(monkeypatch):
    _install_ready_sources(monkeypatch)
    forbidden_calls = []

    def forbidden(name):
        def fail(*args, **kwargs):
            forbidden_calls.append(name)
            raise AssertionError(f'forbidden side effect: {name}')
        return fail

    monkeypatch.setattr(alpha_dashboard.alpha_scanner, 'create_scanner_run', forbidden('create_scanner_run'))
    monkeypatch.setattr(alpha_dashboard.alpha_scanner, 'run_scanner_realtime_monitor_check', forbidden('monitor_check'))
    monkeypatch.setattr(alpha_dashboard.paper_orchestrator, 'run_intraday_watch', forbidden('intraday_watch'))
    monkeypatch.setattr(alpha_dashboard.pipeline_overview, 'get_pipeline_today_snapshot', forbidden('pipeline_today'))

    result = alpha_dashboard.get_alpha_service_dashboard(now=datetime(2026, 8, 20, 12, 0, tzinfo=KST))

    assert result['services'][2]['schedule']['phase'] == 'due'
    assert forbidden_calls == []
```

outcome refresh와 atomic writer는 조합기 모듈에 import하지 않는 것으로도 차단한다. 해당 심볼을 새 모듈에 추가하지 않는다.

- [ ] **Step 4: fallback market phase와 정확한 시간 경계 테스트 작성**

고정 시각 `07:59`, `08:00`, `08:14:59`, `08:15`, 장중 `08:59`, `09:00`, `15:29:59`, `15:30`을 parametrized test로 검증한다. `as_of` 없는 phase는 다음을 만족해야 한다.

```python
assert market['data_status'] == 'stale'
assert market['provenance']['sources'][0]['fallback'] is True
assert market['provenance']['sources'][0]['freshness'] == 'unknown'
```

- [ ] **Step 5: GREEN 및 compile 확인**

```powershell
python -m pytest tests/test_mirofish_alpha_dashboard.py -q
python -m compileall app/services/mirofish/alpha_dashboard.py app/services/mirofish/alpha_scanner.py app/services/mirofish/paper_orchestrator.py
```

Expected: PASS, compile error 없음.

---

### Task 4: 공개 export와 인증 GET 라우트

**Files:**
- Modify: `tests/test_mirofish_alpha_dashboard.py`
- Modify: `tests/test_admin_mirofish_alpha_scanner.py:1546-1576`
- Modify: `app/services/mirofish/__init__.py:85-90,135-220`
- Modify: `app/routes/admin_mirofish.py:67-76`

**Interfaces:**
- Consumes: `get_alpha_service_dashboard(...)`
- Produces: `GET /api/admin/mirofish/alpha-dashboard`
- Produces: query defaults `(5, 30, 10)` and strict ranges `(1..20, 1..180, 1..50)`

- [ ] **Step 1: 실제 auth를 사용하는 라우트 fixture와 실패 테스트 작성**

`tests/test_mirofish_alpha_dashboard.py`에 다음 fixture를 추가한다.

```python
import pytest

from app import create_app
from app.auth.decorators import generate_token
from app.models import db
from app.models.user import User


@pytest.fixture()
def admin_client():
    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'MARKETFLOW_BACKGROUND_WORKERS': 'false',
        'SECRET_KEY': 'test-alpha-dashboard-secret',
    })
    client = app.test_client()
    with app.app_context():
        admin = User(
            email='alpha-dashboard-admin@test.local',
            name='Alpha Dashboard Admin',
            role='admin', status='approved', tier='premium',
        )
        admin.set_password('test-password-1234')
        db.session.add(admin)
        db.session.commit()
        token = generate_token(admin.id)
    client.environ_base['HTTP_AUTHORIZATION'] = f'Bearer {token}'
    return client
```

정상 route 테스트는 package export를 patch해 실제 query 전달을 검증한다.

```python
def test_alpha_dashboard_route_forwards_strict_query_and_disables_cache(admin_client, monkeypatch):
    captured = {}

    def fake_dashboard(**kwargs):
        captured.update(kwargs)
        return {'schema_version': 'mirofish.alpha_service_dashboard.v1', 'services': []}

    monkeypatch.setattr('app.services.mirofish.get_alpha_service_dashboard', fake_dashboard)
    response = admin_client.get(
        '/api/admin/mirofish/alpha-dashboard?candidate_limit=7&outcome_days=60&outcome_limit=12'
    )

    assert response.status_code == 200
    assert captured == {'candidate_limit': 7, 'outcome_days': 60, 'outcome_limit': 12}
    assert 'no-store' in response.headers['Cache-Control']
```

- [ ] **Step 2: 인증과 잘못된 query의 실패 테스트 작성**

인증 없는 `create_app(...).test_client()`는 401이어야 한다. 다음 값은 parametrized 400으로 검증한다.

```python
@pytest.mark.parametrize(('query', 'message'), [
    ('candidate_limit=0', 'candidate_limit must be an integer between 1 and 20'),
    ('candidate_limit=21', 'candidate_limit must be an integer between 1 and 20'),
    ('candidate_limit=1.5', 'candidate_limit must be an integer between 1 and 20'),
    ('candidate_limit=%205%20', 'candidate_limit must be an integer between 1 and 20'),
    ('candidate_limit=%2B5', 'candidate_limit must be an integer between 1 and 20'),
    ('candidate_limit=true', 'candidate_limit must be an integer between 1 and 20'),
    ('outcome_days=181', 'outcome_days must be an integer between 1 and 180'),
    ('outcome_limit=51', 'outcome_limit must be an integer between 1 and 50'),
])
def test_alpha_dashboard_route_rejects_invalid_query(admin_client, query, message):
    response = admin_client.get(f'/api/admin/mirofish/alpha-dashboard?{query}')
    assert response.status_code == 400
    assert response.get_json() == {'error': 'invalid_query', 'message': message}
```

- [ ] **Step 3: RED 확인**

```powershell
python -m pytest tests/test_mirofish_alpha_dashboard.py -q
```

Expected: 404 또는 package export 없음으로 FAIL.

- [ ] **Step 4: package export와 strict parser 구현**

`app/services/mirofish/__init__.py`에 import와 `__all__` 항목을 추가한다.

```python
from app.services.mirofish.alpha_dashboard import get_alpha_service_dashboard
```

`admin_mirofish.py`에 로컬 helper를 추가한다.

```python
def _strict_dashboard_int_arg(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = request.args.get(name)
    if raw is None:
        return default
    if not raw or not raw.isascii() or not raw.isdecimal():
        raise ValueError(f'{name} must be an integer between {minimum} and {maximum}')
    value = int(raw)
    if value < minimum or value > maximum:
        raise ValueError(f'{name} must be an integer between {minimum} and {maximum}')
    return value
```

라우트 구현:

```python
@admin_mirofish_bp.route('/alpha-dashboard', methods=['GET'])
@admin_or_aibain_required
def alpha_service_dashboard():
    try:
        candidate_limit = _strict_dashboard_int_arg('candidate_limit', 5, 1, 20)
        outcome_days = _strict_dashboard_int_arg('outcome_days', 30, 1, 180)
        outcome_limit = _strict_dashboard_int_arg('outcome_limit', 10, 1, 50)
    except ValueError as exc:
        return jsonify({'error': 'invalid_query', 'message': str(exc)}), 400

    response = jsonify(mirofish.get_alpha_service_dashboard(
        candidate_limit=candidate_limit,
        outcome_days=outcome_days,
        outcome_limit=outcome_limit,
    ))
    response.headers['Cache-Control'] = 'no-store'
    return response
```

- [ ] **Step 5: URL map 회귀 추가**

`test_admin_mirofish_scanner_routes_are_registered`에 다음 assertion을 추가한다.

```python
assert '/api/admin/mirofish/alpha-dashboard' in rules
```

- [ ] **Step 6: Task 4 GREEN 확인**

```powershell
python -m pytest tests/test_mirofish_alpha_dashboard.py tests/test_admin_mirofish_alpha_scanner.py::test_admin_mirofish_scanner_routes_are_registered -q
python -m compileall app/routes/admin_mirofish.py app/services/mirofish/__init__.py
```

Expected: PASS.

---

### Task 5: TypeScript API 계약과 서비스 시계 정상 렌더링

**Files:**
- Create: `frontend-react/src/test/alphaServiceDashboard.test.tsx`
- Modify: `frontend-react/src/lib/mirofishApi.ts:425-501,1920-2004`
- Create: `frontend-react/src/components/admin/AlphaServiceDashboard.tsx`

**Interfaces:**
- Consumes: `GET /api/admin/mirofish/alpha-dashboard`
- Produces: `mirofishApi.getAlphaServiceDashboard(options?)`
- Produces: `AlphaServiceDashboard` default export

- [ ] **Step 1: 완전한 정상 응답 mock과 실패 테스트 작성**

`alphaServiceDashboard.test.tsx`에서 `mirofishApi`의 새 메서드만 mock하고 실제 컴포넌트를 렌더링한다.

```tsx
import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import AlphaServiceDashboard from '@/components/admin/AlphaServiceDashboard';

const mockGetDashboard = vi.hoisted(() => vi.fn());

vi.mock('@/lib/mirofishApi', async () => {
  const actual = await vi.importActual<typeof import('@/lib/mirofishApi')>('@/lib/mirofishApi');
  return {
    ...actual,
    mirofishApi: { ...actual.mirofishApi, getAlphaServiceDashboard: mockGetDashboard },
  };
});

const dashboard = {
  schema_version: 'mirofish.alpha_service_dashboard.v1',
  generated_at: '2026-08-20T08:40:00+09:00',
  timezone: 'Asia/Seoul',
  date_kst: '2026-08-20',
  status: 'ready',
  warnings: [],
  links: {},
  services: [
    {
      id: 'market_brief', order: 1, title: '전일 시장 정리',
      description: '시장 국면과 시장 폭을 확인합니다.',
      schedule: { label: '오전 8시', time_kst: '08:00', phase: 'elapsed', calendar_status: 'unverified' },
      data_status: 'ready', as_of: '2026-08-19', summary: '상승 추세 확산',
      metrics: [{ key: 'breadth', label: '시장 폭', value: 54.2, unit: '%', tone: 'neutral' }],
      items: [], warnings: [], provenance: { sources: [] },
    },
    {
      id: 'score_leaders', order: 2, title: '알파스코어 상위 종목',
      description: '최근 비어 있지 않은 스캔 후보입니다.',
      schedule: { label: '오전 8시 30분', time_kst: '08:30', phase: 'due', calendar_status: 'unverified' },
      data_status: 'ready', as_of: '2026-08-20T08:30:00+09:00', summary: '1개 후보',
      metrics: [],
      items: [{ rank: 1, symbol: '005930', name: '삼성전자', market: 'KOSPI', alpha_score: 87.4, risk_score: 21, action: 'BUY_CANDIDATE', horizon: '5d', price: 71500 }],
      warnings: [], provenance: { sources: [] },
    },
    {
      id: 'intraday_flow', order: 3, title: '장중 종목 흐름 체크',
      description: '마지막 저장 종가 기준 포지션입니다.',
      schedule: { label: '장중', time_kst: null, phase: 'due', calendar_status: 'unverified' },
      data_status: 'ready', as_of: '2026-08-19', summary: '1개 포지션', metrics: [],
      items: [{ symbol: '005930', name: '삼성전자', entry_price: 70000, last_close: 71500, last_close_date: '2026-08-19', unrealized_pct: 2.14, held_trading_days: 2, target_price: 75600, stop_price: 65100 }],
      warnings: [], provenance: { sources: [] },
    },
    {
      id: 'trade_signals', order: 4, title: '당일 매매 신호',
      description: '가상 매매와 파이프라인 상태입니다.',
      schedule: { label: '오후 3시', time_kst: '15:00', phase: 'upcoming', calendar_status: 'unverified' },
      data_status: 'ready', as_of: '2026-08-20T08:40:00+09:00', summary: '대기 1건', metrics: [],
      items: [{ key: 'pending', label: '진입 대기', count: 1, window_days: null, status: 'waiting' }],
      warnings: [], provenance: { sources: [] },
    },
    {
      id: 'performance_brief', order: 5, title: '최근 성과 브리핑',
      description: '두 성과 표본을 분리해 봅니다.',
      schedule: { label: '오후 6시', time_kst: '18:00', phase: 'upcoming', calendar_status: 'unverified' },
      data_status: 'ready', as_of: '2026-08-20T08:40:00+09:00', summary: '성과 표본 10건', metrics: [],
      items: [
        { source: 'paper_30d', sample_count: 4, window_days: 30, win_rate: 75, average_return_pct: 2.5, cumulative_return_pct: 10.2, hit_count: null, miss_count: null },
        { source: 'workflow_outcomes', sample_count: 6, window_days: 30, win_rate: 66.67, average_return_pct: 3.1, cumulative_return_pct: null, hit_count: 4, miss_count: 2 },
      ],
      warnings: [], provenance: { sources: [] },
    },
  ],
} as const;

it('renders the five source-backed services in server order', async () => {
  mockGetDashboard.mockResolvedValue(dashboard);
  render(<AlphaServiceDashboard />);

  const region = await screen.findByRole('region', { name: 'Alpha Service Clock' });
  const headings = within(region).getAllByRole('heading', { level: 3 }).map(node => node.textContent);
  expect(headings).toEqual([
    '전일 시장 정리', '알파스코어 상위 종목', '장중 종목 흐름 체크',
    '당일 매매 신호', '최근 성과 브리핑',
  ]);
  expect(within(region).getByText('005930 · KOSPI')).toBeInTheDocument();
  expect(within(region).getByText('+2.14%')).toBeInTheDocument();
  expect(within(region).getByText('표본 6건')).toBeInTheDocument();
});
```

- [ ] **Step 2: RED 확인**

```powershell
Set-Location frontend-react
npm run test -- alphaServiceDashboard.test.tsx
```

Expected: component module 또는 API method 없음으로 FAIL.

- [ ] **Step 3: discriminated union 타입과 API method 구현**

`mirofishApi.ts`에 다음 공통 타입과 카드별 item 인터페이스를 추가한다.

```typescript
export type MiroFishAlphaDashboardStatus = 'ready' | 'stale' | 'partial' | 'empty';
export type MiroFishAlphaSchedulePhase = 'upcoming' | 'due' | 'elapsed';
export type MiroFishAlphaServiceId =
  | 'market_brief' | 'score_leaders' | 'intraday_flow'
  | 'trade_signals' | 'performance_brief';

export interface MiroFishAlphaMetric {
  key: string;
  label: string;
  value: number | string | null;
  unit: string | null;
  tone: 'positive' | 'neutral' | 'warning' | 'negative';
}

export interface MiroFishAlphaWarning {
  section?: string;
  code: string;
  message: string;
  severity: 'info' | 'warning' | 'error';
}

export interface MiroFishAlphaServiceBase {
  order: number;
  title: string;
  description: string;
  schedule: {
    label: string;
    time_kst: string | null;
    phase: MiroFishAlphaSchedulePhase;
    calendar_status: 'unverified';
  };
  data_status: MiroFishAlphaDashboardStatus;
  as_of: string | null;
  summary: string;
  metrics: MiroFishAlphaMetric[];
  warnings: MiroFishAlphaWarning[];
  provenance: { sources: Array<{
    source: string; run_id: string | null; as_of: string | null;
    freshness: string; fallback: boolean;
  }> };
}
```

`MiroFishMarketBriefService`, `MiroFishScoreLeadersService`, `MiroFishIntradayFlowService`, `MiroFishTradeSignalsService`, `MiroFishPerformanceBriefService`를 각 `id`와 정확한 `items` 타입으로 정의하고 union `MiroFishAlphaService`를 만든다.

```typescript
export interface MiroFishAlphaServiceDashboardResponse {
  schema_version: 'mirofish.alpha_service_dashboard.v1';
  generated_at: string;
  timezone: 'Asia/Seoul';
  date_kst: string;
  status: MiroFishAlphaDashboardStatus;
  services: MiroFishAlphaService[];
  warnings: MiroFishAlphaWarning[];
  links: Record<string, string>;
}
```

API method는 쿼리 이름을 서버 계약 그대로 사용한다.

```typescript
getAlphaServiceDashboard: async (params: {
  candidateLimit?: number;
  outcomeDays?: number;
  outcomeLimit?: number;
} = {}) => {
  const search = new URLSearchParams();
  if (params.candidateLimit !== undefined) search.set('candidate_limit', String(params.candidateLimit));
  if (params.outcomeDays !== undefined) search.set('outcome_days', String(params.outcomeDays));
  if (params.outcomeLimit !== undefined) search.set('outcome_limit', String(params.outcomeLimit));
  const query = search.toString();
  return fetchAuthAPI<MiroFishAlphaServiceDashboardResponse>(
    `/api/admin/mirofish/alpha-dashboard${query ? `?${query}` : ''}`,
    undefined,
    30000,
  );
},
```

- [ ] **Step 4: 정상 렌더링에 필요한 최소 컴포넌트 구현**

`AlphaServiceDashboard.tsx`에서 loading → ready 상태와 다섯 카드를 만든다. 최상위는 다음 접근성 계약을 지킨다.

```tsx
<section
  aria-labelledby="alpha-service-clock-title"
  className="relative min-w-0 overflow-hidden rounded-2xl border border-cyan-300/15 bg-[#10151f] p-4"
>
  <h2 id="alpha-service-clock-title">Alpha Service Clock</h2>
</section>
```

디자인 토큰은 spec의 색만 사용한다.

- 패널 `#10151F`, 내부 카드 `#151C28`
- 현재 구간 cyan `#67E8F9`
- ready mint `#6EE7B7`
- waiting/stale/partial amber `#FCD34D`
- error/negative rose `#FDA4AF`

레일은 `aria-hidden="true"`인 세로 선과 각 실제 서비스의 시간 표식으로 만들고, 카드 본문은 한 열을 유지한다. 시간·종목·수치는 `font-mono`, 한국어 제목·본문은 기존 sans font를 사용한다.

- [ ] **Step 5: GREEN 확인**

```powershell
npm run test -- alphaServiceDashboard.test.tsx
npm run build
```

Expected: 테스트와 TypeScript build PASS.

---

### Task 6: UI 상태·경고·재시도·visible-only 60초 갱신

**Files:**
- Modify: `frontend-react/src/test/alphaServiceDashboard.test.tsx`
- Modify: `frontend-react/src/components/admin/AlphaServiceDashboard.tsx`

**Interfaces:**
- Preserves: Task 5의 props 없는 default component
- Produces: loading/error/partial/stale/empty UI와 timer cleanup

- [ ] **Step 1: 상태·표본 없음·경고의 실패 테스트 작성**

정상 fixture를 복제하지 말고 구조적 clone으로 값만 바꾼 뒤 실제 UI 결과를 검증한다.

```tsx
it('distinguishes stale partial and empty without presenting zero samples as success', async () => {
  mockGetDashboard.mockResolvedValue({
    ...dashboard,
    status: 'partial',
    warnings: [{ section: 'paper_overview', code: 'source_read_failed', message: '포지션 데이터를 읽지 못했습니다.', severity: 'error' }],
    services: dashboard.services.map(service => {
      if (service.id === 'market_brief') return { ...service, data_status: 'stale' };
      if (service.id === 'intraday_flow') return { ...service, data_status: 'partial', items: [] };
      if (service.id === 'performance_brief') return {
        ...service,
        data_status: 'empty',
        items: service.items.map(item => ({
          ...item, sample_count: 0, win_rate: null,
          average_return_pct: null, cumulative_return_pct: null,
        })),
      };
      return service;
    }),
  });

  render(<AlphaServiceDashboard />);

  expect(await screen.findByText('오래됨')).toBeInTheDocument();
  expect(screen.getByText('일부만')).toBeInTheDocument();
  expect(screen.getByText('데이터 없음')).toBeInTheDocument();
  expect(screen.getAllByText('표본 없음').length).toBeGreaterThan(0);
  expect(screen.queryByText('0%')).not.toBeInTheDocument();
  expect(screen.getByRole('alert')).toHaveTextContent('포지션 데이터를 읽지 못했습니다.');
});
```

- [ ] **Step 2: 실패와 재시도 테스트 작성**

```tsx
it('retries the same endpoint after a failed request', async () => {
  mockGetDashboard
    .mockRejectedValueOnce(new Error('network unavailable'))
    .mockResolvedValueOnce(dashboard);
  render(<AlphaServiceDashboard />);

  const retry = await screen.findByRole('button', { name: '다시 불러오기' });
  expect(screen.getByRole('alert')).toHaveTextContent('서비스 현황을 불러오지 못했습니다.');
  await userEvent.click(retry);

  expect(await screen.findByText('전일 시장 정리')).toBeInTheDocument();
  expect(mockGetDashboard).toHaveBeenCalledTimes(2);
});
```

- [ ] **Step 3: visible-only timer와 cleanup 실패 테스트 작성**

```tsx
it('refreshes every sixty seconds only while visible and stops after unmount', async () => {
  vi.useFakeTimers();
  let visibility: DocumentVisibilityState = 'visible';
  Object.defineProperty(document, 'visibilityState', {
    configurable: true,
    get: () => visibility,
  });
  mockGetDashboard.mockResolvedValue(dashboard);
  const view = render(<AlphaServiceDashboard />);
  await act(async () => {
    await Promise.resolve();
  });

  expect(mockGetDashboard).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(60_000);
  expect(mockGetDashboard).toHaveBeenCalledTimes(2);

  visibility = 'hidden';
  document.dispatchEvent(new Event('visibilitychange'));
  await vi.advanceTimersByTimeAsync(60_000);
  expect(mockGetDashboard).toHaveBeenCalledTimes(2);

  view.unmount();
  visibility = 'visible';
  await vi.advanceTimersByTimeAsync(60_000);
  expect(mockGetDashboard).toHaveBeenCalledTimes(2);
  vi.useRealTimers();
});
```

테스트 cleanup은 `afterEach(() => vi.useRealTimers())`로 보장한다.

- [ ] **Step 4: RED 확인**

```powershell
npm run test -- alphaServiceDashboard.test.tsx
```

Expected: 상태 문구, retry 또는 timer 동작 부족으로 FAIL.

- [ ] **Step 5: 상태 렌더링과 request 수명주기 구현**

상태 라벨을 하나의 결정론적 map으로 둔다.

```typescript
const DATA_STATUS_LABEL = {
  ready: '준비됨', stale: '오래됨', partial: '일부만', empty: '데이터 없음',
} as const;

const SCHEDULE_LABEL = {
  upcoming: '예정', due: '현재 구간', elapsed: '경과',
} as const;
```

효과는 overlap과 unmount 업데이트를 막는다.

```tsx
useEffect(() => {
  let disposed = false;
  let inFlight = false;

  const load = async () => {
    if (inFlight || disposed) return;
    inFlight = true;
    try {
      const next = await mirofishApi.getAlphaServiceDashboard();
      if (!disposed) {
        setDashboard(next);
        setError(null);
      }
    } catch {
      if (!disposed) setError('서비스 현황을 불러오지 못했습니다.');
    } finally {
      inFlight = false;
    }
  };

  void load();
  const intervalId = window.setInterval(() => {
    if (document.visibilityState === 'visible') void load();
  }, 60_000);
  const onVisibility = () => {
    if (document.visibilityState === 'visible') void load();
  };
  document.addEventListener('visibilitychange', onVisibility);
  return () => {
    disposed = true;
    window.clearInterval(intervalId);
    document.removeEventListener('visibilitychange', onVisibility);
  };
}, [requestVersion]);
```

재시도 버튼은 `requestVersion`을 증가시킨다. 초기 loading에는 동일 높이의 5개 `animate-pulse` 스켈레톤을 렌더링한다. reduced-motion 환경에서는 Tailwind `motion-reduce:animate-none`을 붙인다.

- [ ] **Step 6: GREEN과 build 확인**

```powershell
npm run test -- alphaServiceDashboard.test.tsx
npm run build
```

Expected: PASS, act warning 및 unhandled rejection 없음.

---

### Task 7: 기존 알파 스캐너 보드에 마운트

**Files:**
- Modify: `frontend-react/src/test/adminEndpointsEnter.test.tsx:6-48,91-763,794-825`
- Modify: `frontend-react/src/pages/admin/AdminEndpointsPage.tsx:1-18,3264-3268`

**Interfaces:**
- Consumes: `AlphaServiceDashboard`
- Preserves: 기존 `opsLaneRefreshKey` remount와 모든 기존 운영 카드

- [ ] **Step 1: page API mock에 완전한 dashboard fixture 추가**

hoisted `mockApi`에 `getAlphaServiceDashboard: vi.fn()`을 추가한다. `beforeEach`에는 Task 5의 완전한 다섯 서비스 응답을 `mockResolvedValue`로 등록한다. 부분 mock이 아니라 실제 응답 필드를 모두 포함한다.

- [ ] **Step 2: 공존과 새로고침 실패 테스트 작성**

기존 `loads the latest alpha scanner board on page load` 테스트에 다음 사용자 관찰 결과를 추가한다.

```tsx
expect(await screen.findByRole('region', { name: 'Alpha Service Clock' })).toBeInTheDocument();
expect(await screen.findByText('전일 시장 정리')).toBeInTheDocument();
expect((await screen.findAllByText(/Operating Workflow/i)).length).toBeGreaterThan(0);
expect((await screen.findAllByText(/성과검증 보드/i)).length).toBeGreaterThan(0);
expect(mockApi.getAlphaServiceDashboard).toHaveBeenCalledTimes(1);
```

별도 테스트에서 `운영 현황 새로고침`을 클릭하고 dashboard 호출 수가 증가하는지 확인한다. 이 테스트는 remount 동작을 검증하며 타이머를 전진시키지 않는다.

- [ ] **Step 3: RED 확인**

```powershell
npm run test -- adminEndpointsEnter.test.tsx
```

Expected: Alpha Service Clock region 없음으로 FAIL.

- [ ] **Step 4: import와 정확한 위치에 마운트**

상단 admin card import 옆에 추가한다.

```tsx
import AlphaServiceDashboard from '@/components/admin/AlphaServiceDashboard';
```

`ops-lane-${opsLaneRefreshKey}` 내부 첫 자식으로 둔다.

```tsx
<div key={`ops-lane-${opsLaneRefreshKey}`} className="flex flex-col gap-3">
  <AlphaServiceDashboard />
  <TodaysPipelineCard />
  <ScanPerformanceCard />
  <ScanHistoryCard />
  <RecentOutcomesBoard />
</div>
```

`subscriberMode` 조건을 새로 만들지 않는다. 현재 실제 mount는 관리자 route 하나이고 백엔드 권한은 admin/AIBain 공용이므로, 기존 컴포넌트 재사용 가능성을 차단하지 않는다.

- [ ] **Step 5: 집중 프론트 테스트와 build**

```powershell
npm run test -- alphaServiceDashboard.test.tsx adminEndpointsEnter.test.tsx
npm run build
```

Expected: PASS.

---

### Task 8: 회귀·데이터 신뢰·브라우저 시각 검증

**Files:**
- Review only: 이번 계획에서 변경한 파일 전체
- No deploy, push, commit

**Interfaces:**
- Verifies: API/화면 계약, 기존 scanner/pipeline/paper 회귀, 데스크톱·모바일 시각 품질

- [ ] **Step 1: backend 집중·회귀 테스트**

```powershell
python -m pytest tests/test_mirofish_alpha_dashboard.py tests/test_paper_orchestrator.py -q
python -m pytest tests/test_mirofish_pipeline_overview.py tests/test_mirofish_aibain_overview.py tests/test_paper_positions.py tests/test_admin_mirofish_alpha_scanner.py tests/test_signal_contract.py -q
python -m compileall app/services/mirofish/alpha_dashboard.py app/services/mirofish/alpha_scanner.py app/services/mirofish/paper_orchestrator.py app/routes/admin_mirofish.py
```

- [ ] **Step 2: frontend 집중·전체 테스트와 production build**

```powershell
Set-Location frontend-react
npm run test -- alphaServiceDashboard.test.tsx adminEndpointsEnter.test.tsx
npm run test
npm run build
```

- [ ] **Step 3: 데이터 신뢰 QA**

테스트 또는 로컬 endpoint payload에서 다음을 직접 대조한다.

1. TOP 후보의 `run_id`, `freshness`, `source_files`가 동일한 non-empty 실행에서 왔는지
2. `breadth=0.542`가 `54.2%`, `breadth_change_5d=0.031`이 `3.1%p`인지
3. open position의 `last_close`와 `last_close_date`가 같은 CSV 행인지
4. paper 30일 표본과 workflow outcome 표본이 서로 다른 item/source로 표시되는지
5. sample 0의 win rate/return이 `null`이고 UI가 `표본 없음`/`—`로 표시하는지
6. market leading sector는 빈 배열과 info 경고이며 임의 업종명이 없는지

- [ ] **Step 4: 로컬 서버와 in-app browser 시각 검증**

로컬 Flask `5001`과 Vite `5173`을 실행하고 관리자 `/admin/endpoints`에서 확인한다.

- Desktop 1440px: 우측 레인 최상단, 5단계 순서, 레일/표식 정렬, 기존 카드 공존
- Narrow 390px: 단일 열, 가로 overflow 없음, 숫자/종목 줄바꿈 안정, 버튼 44px 이상
- Loading: 5개 skeleton 높이 안정
- Error: alert와 `다시 불러오기` keyboard focus
- Partial/stale/empty: 색뿐 아니라 텍스트로 구별
- Reduced motion: current marker/skeleton animation 비활성

시각 문제를 발견하면 해당 동작을 재현하는 실패 테스트를 먼저 추가한 뒤 최소 수정한다.

- [ ] **Step 5: 변경 범위와 diff 검증**

```powershell
git diff --check
git status --short
git diff -- app/services/mirofish/alpha_dashboard.py app/services/mirofish/alpha_scanner.py app/services/mirofish/paper_orchestrator.py app/services/mirofish/__init__.py app/routes/admin_mirofish.py tests/test_mirofish_alpha_dashboard.py tests/test_admin_mirofish_alpha_scanner.py tests/test_paper_orchestrator.py frontend-react/src/lib/mirofishApi.ts frontend-react/src/components/admin/AlphaServiceDashboard.tsx frontend-react/src/pages/admin/AdminEndpointsPage.tsx frontend-react/src/test/alphaServiceDashboard.test.tsx frontend-react/src/test/adminEndpointsEnter.test.tsx
```

Expected: 계획 파일과 의도한 구현 파일만 변경. 사용자 소유 변경은 그대로 유지되며 staging/commit/deploy는 하지 않는다.

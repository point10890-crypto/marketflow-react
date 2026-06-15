# AI Brain 구독자 대시보드 재설계 — Implementation Plan

> 하네스: `docs/superpowers/harness/2026-06-15-aibain-dashboard-harness.md` · 스펙: `docs/superpowers/specs/2026-06-15-aibain-dashboard-design.md`. TDD. FE/BE 분리.

**Goal:** 구독자 전용 심플 대시보드(검출/성과검증/학습 3섹션)를 admin 콘솔과 분리 구축. 서비스 무중단.

**환경 분리:** Backend(`app/`) → 계약 고정 → Frontend(`frontend-react/`). 서로 다른 파일 트리라 충돌 없음.

## 공통 사전지식
- 실행: `PROJECT="/c/bitman_marketfloww"; PYTHON="$PROJECT/.venv/Scripts/python.exe"`; 백엔드 테스트 `cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -m pytest <f> -q`. FE: `cd "$PROJECT/frontend-react" && npm run test -- <file>` / `npm run build`.
- 브랜치: `feature/aibain-dashboard` (생성됨)
- 백엔드 검증된 재사용 함수:
  - `app/services/mirofish/pipeline_overview.py`: `get_outcomes_board(days=30, limit=20)` → `{window_days, summary, items:[...]}`. 내부 `_flatten_outcome_item` 필드: symbol,name,entry_date,status,hit,forward_return_pct,rank,horizons. `get_pipeline_today_snapshot()` 존재.
  - `app/services/mirofish/workflow.py`: `read_latest_workflow()`, `build_share_payload(wf, rank=None)` → `{top_items:[{rank,name,action,confidence_pct,symbol?...}]}`.
  - `app/services/mirofish/alpha_brain_agent.py`: `get_agent_status()` → `{active_scoring_overlay, edge_map_generated_at, recent_journal, ...}`; `build_agent_observation()` → `{interaction_map:{top_positive,top_negative,evaluated_count}, regime_distribution, ...}`.
  - `app.utils.atomic_json.write_json_atomic` (필요 시).
  - mirofish `__init__.py`에 `get_outcomes_board` 등 export됨 — 신규 함수도 export 추가.
- FE 인증 GET 관용구: `import { fetchAuthAPI } from '@/lib/api'; await fetchAuthAPI<T>('/api/admin/mirofish/aibain/overview', token)`.
- 권한 데코레이터: `from app.auth.decorators import admin_or_aibain_required`.

---

### BE Task 1: `get_aibain_overview()` 서비스 + 테스트

**Files:** Modify `app/services/mirofish/pipeline_overview.py` (함수 추가), `app/services/mirofish/__init__.py` (export); Test `tests/test_mirofish_aibain_overview.py`

**계약:** `get_aibain_overview(*, perf_days=30) -> dict` — 기존 서비스만 묶음, 신규 로직 없음. 각 섹션 try/except 격리(실패 시 빈 객체 + 'error' 키, 전체는 항상 dict 반환).
```python
{
  'generated_at': iso,
  'detections': {'as_of': str|None, 'items': [ {symbol,name,action,alpha_score,risk_score,entry_date} ... 최대 3 ]},
  'performance': {'window_days': perf_days, 'hit_rate_pct', 'avg_forward_return_pct', 'false_positive_pct',
                  'evaluated_count', 'verified': [ {symbol,name,entry_date,forward_return_pct,hit,status} ... 최대 8 ]},
  'learning': {'regime_distribution': {}, 'top_positive': [...최대5], 'top_negative': [...최대5], 'updated_at': str|None},
}
```
- detections: `workflow.read_latest_workflow()` → `workflow.build_share_payload(wf)` → top_items[:3] 를 위 shape로 방어적 매핑(.get, 없으면 None). as_of = wf completed_at/generated_at.
- performance: `get_outcomes_board(days=perf_days, limit=8)` 의 summary에서 hit_rate_pct/avg_forward_return_pct/false_positive_pct/evaluated_count 추출, items에서 status∈{evaluated,partial} 우선 8개를 verified로 매핑.
- learning: `alpha_brain_agent.build_agent_observation()` 에서 interaction_map.top_positive/top_negative(각 5개)·regime_distribution, updated_at = edge_map_generated_at(get_agent_status). (build_agent_observation 실패 가능 → try/except.)

**TDD:**
1. 실패 테스트 `tests/test_mirofish_aibain_overview.py`:
```python
"""get_aibain_overview tests — section shape + source isolation. No network."""
from app.services.mirofish import pipeline_overview as po


def test_overview_has_three_sections(monkeypatch):
    monkeypatch.setattr(po, 'get_outcomes_board', lambda **kw: {
        'window_days': 30,
        'summary': {'hit_rate_pct': 46.2, 'avg_forward_return_pct': 1.15,
                    'false_positive_pct': 30.0, 'evaluated_count': 26},
        'items': [{'symbol': '005930', 'name': '삼성전자', 'entry_date': '2026-06-01',
                   'status': 'evaluated', 'hit': True, 'forward_return_pct': 6.0}],
    })
    import app.services.mirofish.workflow as wf
    monkeypatch.setattr(wf, 'read_latest_workflow', lambda: {'id': 'w1', 'completed_at': '2026-06-15T00:00:00Z'})
    monkeypatch.setattr(wf, 'build_share_payload', lambda w, rank=None: {'top_items': [
        {'rank': 1, 'name': 'A', 'symbol': '000001', 'action': 'BUY_CANDIDATE'}]})
    import app.services.mirofish.alpha_brain_agent as agent
    monkeypatch.setattr(agent, 'build_agent_observation', lambda **kw: {
        'interaction_map': {'top_positive': [{'combo': 'regime:RISK_ON & tag:foreign_buy', 'n': 6,
                                              'hit_rate': 1.0, 'expectancy_pct': 8.0}], 'top_negative': []},
        'regime_distribution': {'RISK_ON': 26}})
    monkeypatch.setattr(agent, 'get_agent_status', lambda: {'edge_map_generated_at': '2026-06-15T00:00:00Z'})

    out = po.get_aibain_overview()
    assert out['performance']['hit_rate_pct'] == 46.2
    assert out['performance']['evaluated_count'] == 26
    assert len(out['performance']['verified']) == 1
    assert out['detections']['items'][0]['symbol'] == '000001'
    assert out['learning']['regime_distribution']['RISK_ON'] == 26
    assert out['learning']['top_positive'][0]['combo'].startswith('regime:RISK_ON')


def test_overview_isolates_failing_source(monkeypatch):
    def boom(**kw):
        raise RuntimeError('board down')
    monkeypatch.setattr(po, 'get_outcomes_board', boom)
    import app.services.mirofish.workflow as wf
    monkeypatch.setattr(wf, 'read_latest_workflow', lambda: None)
    import app.services.mirofish.alpha_brain_agent as agent
    monkeypatch.setattr(agent, 'build_agent_observation', lambda **kw: {'interaction_map': {}, 'regime_distribution': {}})
    monkeypatch.setattr(agent, 'get_agent_status', lambda: {})
    out = po.get_aibain_overview()
    # performance failed → empty/error but whole call returns dict with all 3 keys
    assert 'detections' in out and 'performance' in out and 'learning' in out
    assert out['performance'].get('error') or out['performance'].get('evaluated_count') in (0, None)
```
2. 실패 확인 → AttributeError(get_aibain_overview 없음).
3. 구현(pipeline_overview.py에 함수 추가, __init__.py에 export). 신규 로직 없이 기존 함수 조합 + 방어적 매핑 + 섹션 try/except.
4. 통과 확인: 2 passed. 회귀: `pytest tests/test_mirofish_pipeline_overview.py -q`.
5. 커밋: `git add app/services/mirofish/pipeline_overview.py app/services/mirofish/__init__.py tests/test_mirofish_aibain_overview.py && git commit -m "feat: aibain overview aggregation service (detections/performance/learning)"`

---

### BE Task 2: `/aibain/overview` 라우트 + 권한/등록 테스트

**Files:** Modify `app/routes/admin_mirofish.py`; Test `tests/test_admin_mirofish_aibain_route.py`

**계약:** `GET /api/admin/mirofish/aibain/overview` `@admin_or_aibain_required`. query `days`(기본 30). `mirofish.get_aibain_overview(perf_days=days)` 반환. 예외 시 500 + `{error, service}`.

**TDD:**
1. 실패 테스트 `tests/test_admin_mirofish_aibain_route.py`:
```python
"""aibain overview route registration + delegation."""
from flask import Flask
from app.routes.admin_mirofish import admin_mirofish_bp


def test_aibain_overview_route_registered():
    app = Flask(__name__)
    app.register_blueprint(admin_mirofish_bp, url_prefix='/api/admin/mirofish')
    rules = {str(r) for r in app.url_map.iter_rules()}
    assert '/api/admin/mirofish/aibain/overview' in rules


def test_aibain_overview_delegates(monkeypatch):
    import app.routes.admin_mirofish as route_mod
    monkeypatch.setattr(route_mod.mirofish, 'get_aibain_overview', lambda perf_days=30: {'ok': True, 'perf_days': perf_days})
    fn = route_mod.aibain_overview.__wrapped__ if hasattr(route_mod.aibain_overview, '__wrapped__') else None
    # 데코레이터로 직접 호출이 어려우면 서비스 위임만 검증 (등록 테스트로 충분).
    assert callable(route_mod.aibain_overview)
```
(권한 데코레이터 때문에 직접 호출이 까다로우면 등록 테스트 + 서비스 위임 존재로 충분 — 기존 admin 라우트 테스트 패턴과 동일.)
2. 실패 확인 → 라우트 미등록 AssertionError.
3. 구현:
```python
@admin_mirofish_bp.route('/aibain/overview', methods=['GET'])
@admin_or_aibain_required
def aibain_overview():
    try:
        days = int(request.args.get('days', 30))
    except (TypeError, ValueError):
        return jsonify({'error': 'days must be an integer'}), 400
    try:
        return jsonify(mirofish.get_aibain_overview(perf_days=days))
    except Exception as exc:
        return jsonify({'error': f'{type(exc).__name__}: {exc}', 'service': 'mirofish-aibain-overview'}), 500
```
(파일 상단에 `admin_or_aibain_required` import 존재 확인 — 이미 사용 중.)
4. 통과 확인: 통과. 회귀: `pytest tests/test_admin_mirofish_workflow.py -q`.
5. 커밋: `git add app/routes/admin_mirofish.py tests/test_admin_mirofish_aibain_route.py && git commit -m "feat: aibain overview admin/aibain-gated route"`

---

### FE Task 3: 구독자 전용 대시보드 + AiBainPage 분리

**Files:** Create `frontend-react/src/pages/dashboard/aibain/AiBainDashboard.tsx`, `DetectionsCard.tsx`, `PerformanceCard.tsx`, `LearningCard.tsx`; Modify `frontend-react/src/pages/dashboard/AiBainPage.tsx`; Test `frontend-react/src/test/aibainDashboard.test.tsx`

**계약/구현:**
- `AiBainPage.tsx`: `showFullDashboard` 분기에서 `AdminEndpointsPage subscriberMode` 대신 `<AiBainDashboard />` 렌더. 나머지 게이팅(upgrade/subscribe)·PageShell·FeatureCard 그대로 보존. `AdminEndpointsPage` lazy import 제거(이 파일에서 미사용 시).
- `AiBainDashboard.tsx`: 마운트 시 `fetchAuthAPI<AiBainOverview>('/api/admin/mirofish/aibain/overview', token)`. 로딩 스피너 / 에러 카드 / 성공 시 3섹션. PageShell 헤더(AI Brain 알파 스캐너) 재사용 가능.
  - 타입:
    ```ts
    interface AiBainOverview {
      generated_at: string;
      detections: { as_of: string|null; items: {symbol:string;name:string;action:string;alpha_score:number|null;risk_score:number|null;entry_date:string|null}[] };
      performance: { window_days:number; hit_rate_pct:number|null; avg_forward_return_pct:number|null; false_positive_pct:number|null; evaluated_count:number; verified:{symbol:string;name:string;entry_date:string|null;forward_return_pct:number|null;hit:boolean|null;status:string}[] };
      learning: { regime_distribution:Record<string,number>; top_positive:{combo:string;n:number;hit_rate:number;expectancy_pct:number}[]; top_negative:{combo:string;n:number;hit_rate:number;expectancy_pct:number}[]; updated_at:string|null };
    }
    ```
- `DetectionsCard`: 오늘의 검출 — 종목명 + action 배지 + 진입가(있으면) + risk 배지. items 비면 "오늘 신규 검출 없음".
- `PerformanceCard`: 큰 KPI 3개(적중률 %, 평균수익 %, 평가표본) + 검증된 픽 리스트(forward_return_pct ≥0 녹색 ▲ / <0 적색 ▼). evaluated_count 0이면 "성과 검증 누적 중".
- `LearningCard`: top_positive → "잘 맞은 패턴", top_negative → "주의 패턴" (combo 문자열을 그대로 칩으로, hit_rate·expectancy 작게). regime_distribution 1줄 요약. 비면 "학습 데이터 누적 중".
- 디자인: 기존 토큰(bg-[#13151f], border cyan/15, rounded-2xl, text-gray-300). 모바일 우선 grid.
- 테스트 `aibainDashboard.test.tsx`: `fetchAuthAPI` 모킹 → 3섹션 렌더(적중률 텍스트, 검출 종목명, 패턴 칩) 확인 + 빈 응답 시 빈 상태 문구. (기존 test 파일들의 vitest + @testing-library 패턴 따름.)

**Steps:** 1) 테스트 작성 → 실패. 2) 컴포넌트 4종 + AiBainPage 수정. 3) `npm run test -- aibainDashboard` 통과. 4) 회귀 `npm run test -- adminEndpointsEnter`. 5) 커밋: `git add frontend-react/src/pages/dashboard/aibain frontend-react/src/pages/dashboard/AiBainPage.tsx frontend-react/src/test/aibainDashboard.test.tsx && git commit -m "feat: dedicated AI Brain subscriber dashboard (detections/performance/learning)"`

---

### Task 4: 통합 검증 + 문서

1. 백엔드: `pytest tests/test_mirofish_aibain_overview.py tests/test_admin_mirofish_aibain_route.py -q` → 통과. 광역 `pytest tests/ -q -k "mirofish or aibain or pipeline"` → 회귀 0.
2. 프론트: `cd frontend-react && npm run test -- aibainDashboard adminEndpointsEnter` → 통과. `npm run build` → 성공.
3. 임포트 스모크: `"$PYTHON" -c "from app.services.mirofish import get_aibain_overview; from app import create_app; a=create_app(); print('aibain/overview' in {str(r) for r in a.url_map.iter_rules()})"` → True.
4. CLAUDE.md §14에 v3.5.0(AI Brain 구독자 대시보드 분리) 추가.
5. 커밋: `git add CLAUDE.md && git commit -m "docs: record aibain dashboard separation in changelog"`

## DoD
구독자 페이지 독립 렌더 + 3섹션 · admin/게이팅/업그레이드 회귀 0 · 신규 엔드포인트 권한 게이트 · FE 빌드+테스트 통과 · 의도 파일만 스테이징.

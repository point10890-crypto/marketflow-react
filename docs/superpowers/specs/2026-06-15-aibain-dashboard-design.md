# AI Brain 구독자 대시보드 재설계 — 설계 문서

- 날짜: 2026-06-15
- 하네스: `docs/superpowers/harness/2026-06-15-aibain-dashboard-harness.md`
- 범위: `/dashboard/ai-bain` 구독자 전용 페이지 분리 + 심플 레이아웃 + Top3 성과검증 표면화 + 학습 피드백 가시화

## 1. 목적 / 사용자 지시
- admin 콘솔(`AdminEndpointsPage`, `/admin/endpoints`)은 **전용 페이지 그대로 보존**.
- 구독자는 admin 콘솔 재사용을 끊고 **자체 전용 심플 대시보드**.
- **서비스 무중단**: 구독 게이팅·업그레이드 플로우·권한·기존 admin 동작 보존, 회귀 0.
- 구독자가 **검출 결과 → 성과검증 → 학습 피드백**을 한눈에 파악.

## 2. 현행 (코드 리뷰 결론)
- `AiBainPage.tsx`(282): 게이팅 후 활성 사용자에게 `AdminEndpointsPage subscriberMode` 재사용 → 구독자 전용 UI 부재.
- `AdminEndpointsPage.tsx`(3088): 거대 모놀리스. subscriberMode 부정 플래그로 일부만 숨김.
- 백엔드: 성과검증 데이터(`get_outcomes_board`)·검출(`get_pipeline_today_snapshot`/`get_top3_summary`)·학습(`alpha_brain_agent.get_agent_status` + intelligence edge/interaction)이 **이미 존재**. 빠진 건 전용 UI와 표면화.

## 3. 비대상 (SCOPE)
- `AdminEndpointsPage` 재구조화/리팩터 (admin 페이지는 건드리지 않음 — 구독자 재사용 분기만 끊음)
- 신규 스코어링/학습 알고리즘 (이미 구축된 intelligence 계층 재사용만)
- 디자인 시스템/공통 레이아웃 토큰 변경
- 결제/구독 로직 변경 (업그레이드 플로우는 그대로)

## 4. 아키텍처

### 4.1 Backend — 구독자 집계 엔드포인트 (얇은 read-only)
신규: `GET /api/admin/mirofish/aibain/overview` `@admin_or_aibain_required`
기존 서비스만 묶음(신규 로직 없음). 서비스 함수 `mirofish.get_aibain_overview()` 신규(`pipeline_overview.py`에 추가):
```json
{
  "generated_at": "iso",
  "detections": {            // 오늘/최근 검출 (get_top3_summary or pipeline_today에서 단순화)
    "as_of": "iso|null",
    "items": [{"symbol","name","action","alpha_score","risk_score","entry_date"}]  // 최대 3
  },
  "performance": {           // get_outcomes_board(days=30) 요약 + 검증된 최근 픽
    "window_days": 30,
    "hit_rate_pct": 46.2,
    "avg_forward_return_pct": 1.15,
    "false_positive_pct": 30.0,
    "evaluated_count": 26,
    "verified": [{"symbol","name","entry_date","forward_return_pct","hit","status"}]  // 최대 8, evaluated 우선
  },
  "learning": {              // alpha_brain_agent 관찰에서 (read-only)
    "regime_distribution": {"RISK_ON": 26, ...},
    "top_positive": [{"combo","n","hit_rate","expectancy_pct"}],  // 최대 5
    "top_negative": [{"combo","n","hit_rate","expectancy_pct"}],  // 최대 5
    "updated_at": "iso|null"
  }
}
```
- 각 섹션 try/except 격리 — 한 소스 실패가 전체 500 금지(부분 응답 + 빈 섹션).
- 라우트는 `admin_mirofish.py`에 추가, 권한 `@admin_or_aibain_required`.

### 4.2 Frontend — 구독자 전용 대시보드
`AiBainPage.tsx` 개편:
- 게이팅 로직(admin/aibain/upgrade/subscribe 분기)은 **유지**.
- 단, `showFullDashboard`일 때 `AdminEndpointsPage subscriberMode` 대신 **새 `<AiBainDashboard />` 렌더**.
- admin은 `/admin/endpoints`에서 기존 `AdminEndpointsPage`(subscriberMode=false) 그대로 — 변경 없음.

신규 컴포넌트 `frontend-react/src/pages/dashboard/aibain/`:
- `AiBainDashboard.tsx` — 데이터 fetch(`fetchAuthAPI('/api/admin/mirofish/aibain/overview', token)`) + 3섹션 조립, 로딩/에러/빈 상태.
- `DetectionsCard.tsx` — 오늘의 검출 Top3 (심플 카드: 종목명, 진입가, 리스크 배지).
- `PerformanceCard.tsx` — 성과검증: 큰 KPI 3개(적중률/평균수익/표본) + 검증된 최근 픽 리스트(수익 +녹/−적).
- `LearningCard.tsx` — 학습 피드백: "잘 맞은 패턴 / 피해야 할 패턴"(top_positive/negative combo를 평이한 한글로), 레짐 분포 1줄.
- 기존 디자인 토큰(cyan/zinc, rounded-2xl 카드) 재사용. 모바일 우선, 정보 최소.

데이터 흐름:
```
AiBainDashboard → fetchAuthAPI(/aibain/overview) → {detections,performance,learning}
   → DetectionsCard / PerformanceCard / LearningCard
```

## 5. 피드백 루프 가시화 (성과→학습 재사용)
백엔드 루프는 이미 동작: `outcome_tracker → edge_map/dataset/interactions → alpha_brain_agent`. 본 작업은 그 루프의 **결과**(검증된 성과 + 학습된 패턴)를 `learning` 섹션으로 표면화해 "성과 데이터가 분석에 재사용되고 있음"을 사용자가 보게 한다. 신규 학습 로직은 만들지 않는다.

## 6. 에러 핸들링
- 백엔드: 섹션별 try/except, 실패 섹션은 빈 객체 + `error` 키. 전체는 200 유지.
- 프론트: fetch 실패 시 카드별 빈/에러 상태(전체 화이트스크린 금지). 로딩 스피너.
- 구독 게이팅·업그레이드 폼은 기존 그대로(회귀 0).

## 7. 테스트
- 백엔드: `get_aibain_overview` 단위 테스트(섹션 shape, 소스 실패 격리), 라우트 등록 + 권한 데코레이터 테스트.
- 프론트: `AiBainDashboard` 렌더 테스트(3섹션, 로딩/에러/빈), 기존 `adminEndpointsEnter.test.tsx` 회귀 통과, `npm run build`.

## 8. DoD
- 구독자 전용 페이지 독립 렌더(admin 콘솔 비의존) + 3섹션 동작
- admin 페이지·구독 게이팅·업그레이드 플로우 회귀 0
- 신규 엔드포인트 `@admin_or_aibain_required` + 라우트 등록 테스트 통과
- FE 빌드 + 포커스/광역 테스트 통과
- 의도 파일만 스테이징

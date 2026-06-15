# AI Brain Dashboard 재설계 — 에이전트 팀 & 하네스 규칙 (FE/BE 분리)

- 날짜: 2026-06-15
- 적용 범위: `/dashboard/ai-bain` 구독자 페이지 분리·재설계 + 성과검증 표면화
- 권위: 본 작업 최상위 실행 규율. `2026-06-15-alpha-intelligence-harness.md`의 14조 절대규칙·6단계 프로토콜을 그대로 상속하고, FE/BE 팀 분리만 추가 명시.

## 0. 미션 락
구독자가 **검출 결과 → 성과검증 → 학습 피드백**을 한눈에 쉽게 파악하게 한다. admin 콘솔은 전용 페이지로 보존, 구독자는 별도 전용 심플 페이지. **서비스 무중단**(기존 동작·엔드포인트·권한 유지).

## 1. 절대 분리 원칙 (사용자 지시)
- `admin` 전용 = 전용 페이지 그대로 (`AdminEndpointsPage` /admin/endpoints, 변경 최소).
- `구독자` 전용 = **새 전용 페이지** (`AiBainPage`가 admin 콘솔 재사용을 끊고 자체 심플 대시보드로).
- **서비스 그대로**: 기존 라우트·권한(`@admin_or_aibain_required`)·구독 게이팅·업그레이드 플로우 보존. 회귀 0.

## 2. 에이전트 팀 (FE/BE 환경 분리)

| 팀 | 환경 | 책임 | 비대상 |
|---|---|---|---|
| **Backend 팀** | `app/` (Python/Flask) | 구독자 집계 엔드포인트(읽기·기존 서비스 재사용), 권한 게이트, 테스트 | 신규 스코어링/학습 로직 발명 금지, admin 컨트롤 변경 금지 |
| **Frontend 팀** | `frontend-react/` (React/TS) | 구독자 전용 심플 대시보드 3섹션, admin 콘솔 의존 제거, 테스트 | 디자인 토큰/공통 레이아웃 임의 변경 금지, admin 페이지 변경 금지 |
| **Coordinator** | 양쪽 | 계약 고정, 라우팅, 단계 게이트, 증거 기반 검증 | 코드 직접작성(검증·조정 제외) |
| **Repair** | 해당 환경 | 검증된 실패 최소 수정 | 전체 재작성 금지 |

실행: **계약(엔드포인트 응답 shape) 먼저 고정 → Backend 팀이 엔드포인트+테스트 → 검증 → Frontend 팀이 그 계약 소비 → 검증 → 통합 검증.** FE/BE는 서로 다른 파일 트리(`app/` vs `frontend-react/`)라 충돌 없음. BE→FE 순서로 계약을 구체화한 뒤 진행.

## 3. 프로토콜·절대규칙
`2026-06-15-alpha-intelligence-harness.md` §2(Route→Scope→Plan→Implement→Verify→Repair), §3(14조), §4(자기점검 훅) 전부 상속. 추가:
- **서비스 무중단 규칙**: 기존 admin/구독 경로가 깨지지 않음을 매 단계 회귀 테스트로 증명(`adminEndpointsEnter.test.tsx`, 백엔드 라우트 등록 테스트).
- **권한 보존 규칙**: 구독자 노출 엔드포인트는 `@admin_or_aibain_required`, 컨트롤은 `@admin_required` 유지.

## 4. DoD
- 구독자 전용 페이지가 admin 콘솔 재사용 없이 독립 렌더 + 3섹션(검출/성과검증/학습) 동작
- admin 페이지·기존 구독 게이팅·업그레이드 플로우 회귀 0 (테스트 증거)
- 신규 엔드포인트 `@admin_or_aibain_required` + 라우트 등록 테스트 통과
- FE 빌드 통과(`npm run build`), 포커스+광역 테스트 통과
- 의도한 파일만 스테이징

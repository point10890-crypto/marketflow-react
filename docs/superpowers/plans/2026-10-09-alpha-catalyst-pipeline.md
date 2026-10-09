# Alpha Catalyst Pipeline Implementation Plan

**Goal:** 가격 검출과 일반 뉴스의 실제 수집·보도 시각을 연결하고 전향 대조 관측을 고정한다.

**Architecture:** 기존 뉴스 원장을 명시적 수집 단계에서 읽어 결정별 immutable sidecar를 저장한다. API GET과 프론트는 검증된 sidecar만 읽고 고정된 선정·가격·Kelly·CIO 승인 계약을 보존한다.

**Tech Stack:** Python/Flask, stdlib SQLite read-only, 기존 atomic JSON helpers, React/TypeScript/Vitest.

**Spec:** `docs/alpha_catalyst_pipeline_2026_10_09.md`.

## 책임과 실행

- [x] 백엔드 담당이 `catalyst_context.py`, `catalyst_store.py`, `scripts/run_alpha_lab_catalysts.py`와 해당 테스트를 소유한다. 먼저 실패 검사를 작성하고 기본·경계 입력을 통과시킨다.
- [x] 프론트 담당이 별도 catalyst 타입·검사기·모바일 읽기 컴포넌트와 테스트를 소유한다. AlphaLabPanel의 선택 prop 연결은 프론트 담당이 한다.
- [x] 조정자가 service와 scheduler의 저장/수집 후 연결 및 관련 회귀 검사를 소유한다.
- [x] 종목명 공백 매칭과 정책·투자·위험 표현 보존 여부를 조사하고 필요한 최소 수정만 적용한다.
- [x] 기존 기본 테스트, 관련 전체 백엔드 및 프론트 검사, build, 독립 리뷰를 수행한다.
- [x] 실제 저장 데이터로 sidecar를 만들고 과거 결정 파일의 내용·해시 불변을 검증한다.
- [ ] 테스트 통과 후 커밋·푸시·PR/CI·배포 검증을 수행한다. 기존 운영 권한과 별도 승인 계약을 유지한다.

## 가장 중요한 경계

같은 기사 반복이 독립 호재로 증가하면 안 된다. 수집 시각을 게시 시각으로 추정하지 않는다. 선택 후 새 뉴스가 최초 선정 이유가 되지 않는다. source failure는 앞의 완료 결과를 보존한다. GET·sidecar 갱신·새로고침은 Telegram 새 검출 이벤트가 아니다.

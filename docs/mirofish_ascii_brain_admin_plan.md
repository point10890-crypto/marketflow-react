# MiroFish x ASCII Brain 관리자 페이지 구현 계획 및 작업 진행 보고서

## 1. 목표

`MiroFish x ASCII Brain`은 일반 사용자에게 노출하지 않고 관리자 페이지에서만 운용하는 고급 분석/시뮬레이션 콘솔이다.

핵심 목표는 뉴스, 리포트, 공시, 시장 브리핑 같은 입력을 받아 ASCII Brain 데이터와 결합하고, GraphRAG 기반 지식 그래프, 멀티 에이전트 토론, 가상 SNS 시뮬레이션, ReACT CIO 판단, 최종 예측 그래프/리포트까지 한 화면에서 관리하는 것이다.

## 2. 관리자 화면 구성안

현재 `/admin/endpoints` 화면은 임시 엔드포인트 카드 상태다. 최종 화면은 다음 6개 영역으로 확장한다.

### 2.1 Run Console

- 뉴스/텍스트/문서 입력
- PDF, MD, TXT, CSV 업로드
- 분석 대상 시장 선택: KR, US, Crypto, Macro
- 실행 모드 선택: 빠른 분석, 전체 GraphRAG, 에이전트 토론 포함, SNS 시뮬레이션 포함
- 실행 버튼: `분석 시작`

### 2.2 Brain Data Status

- ASCII Brain 13D 데이터 로드 상태
- `sector_momentum`, `macro_regime`, `options_flow`, `earnings_catalyst`, `event_risk`, `ml_prediction` 등 핵심 지표 표시
- 최신 업데이트 시간
- 결측/오래된 데이터 경고
- 원본 JSON 파일 상태 확인

### 2.3 GraphRAG Workspace

- 입력 문서에서 추출된 엔티티 표시
- 기업, 섹터, 이벤트, 정책, 인물, 리스크, 자금 흐름 노드 구분
- 인과 관계 엣지 표시
- 기존 EKG, LLM 추론 관계, 최종 예측 관계를 색상으로 분리

### 2.4 Agent Debate

- 고정 5명 에이전트 토론 로그
- 김리스크: 매크로/위험 회피
- 박모멘텀: 모멘텀/실적 촉매
- 이퀀트: ML/옵션 플로우
- 최역발상: 역발상/센티먼트
- 정헤지: 중립 리스크 관리자
- 모든 발언에는 Brain 수치 근거를 최소 1개 포함

### 2.5 Social Simulation

- 가상 Twitter/X 스타일 피드
- 에이전트별 포스트, 댓글, 좋아요, 북마크, 팔로우, 뮤트 이벤트
- 투자자 군중심리 변화 추적
- 특정 내러티브가 확산되는 과정 표시

### 2.6 CIO Decision & Report

- ReACT CIO 판단 과정 표시
- 사용 도구 로그: `query_brain`, `search_graph`, `check_history`, `interview_agent`, `insight_forge`, `panorama_search`, `final_answer`
- 최종 판단: Bullish, Bearish, Neutral, Volatile
- 신뢰도, 핵심 근거, 반대 시나리오
- 3~5장 구조의 마크다운 리포트 생성

## 3. 프론트엔드 아키텍처

### 3.1 라우팅

현재 구조:

- `/admin`은 `AdminGuard`로 관리자만 접근 가능
- `/admin/endpoints`가 `MiroFish x ASCII Brain` 화면으로 연결됨

유지할 방향:

- 라우트는 `/admin/endpoints`를 당분간 유지
- 내부 화면명은 `MiroFish x ASCII Brain`
- 추후 필요하면 `/admin/mirofish`로 alias route 추가 가능

### 3.2 컴포넌트 분리

권장 파일 구조:

```text
frontend-react/src/pages/admin/AdminEndpointsPage.tsx
frontend-react/src/components/admin/mirofish/MiroFishRunConsole.tsx
frontend-react/src/components/admin/mirofish/BrainStatusPanel.tsx
frontend-react/src/components/admin/mirofish/GraphWorkspace.tsx
frontend-react/src/components/admin/mirofish/AgentDebatePanel.tsx
frontend-react/src/components/admin/mirofish/SocialSimulationPanel.tsx
frontend-react/src/components/admin/mirofish/CioDecisionPanel.tsx
frontend-react/src/components/admin/mirofish/ReportPreviewPanel.tsx
frontend-react/src/lib/mirofishApi.ts
```

### 3.3 UI 원칙

- 관리자 도구이므로 정보 밀도를 높인다.
- 마케팅형 히어로 대신 작업 콘솔 중심으로 구성한다.
- 카드 중첩은 피하고, 큰 영역은 탭 또는 좌우 패널로 분리한다.
- 실행 상태는 단계별 타임라인으로 보여준다.
- 결과는 그래프, 로그, 리포트를 동시에 확인할 수 있게 한다.

## 4. 백엔드 아키텍처

### 4.1 API 경로

모든 API는 관리자 전용으로 `/api/admin/mirofish/**` 아래에 둔다.

초기 API:

```text
GET  /api/admin/mirofish/status
POST /api/admin/mirofish/runs
GET  /api/admin/mirofish/runs
GET  /api/admin/mirofish/runs/{run_id}
POST /api/admin/mirofish/runs/{run_id}/cancel
GET  /api/admin/mirofish/runs/{run_id}/events
GET  /api/admin/mirofish/runs/{run_id}/graph
GET  /api/admin/mirofish/runs/{run_id}/report
```

### 4.2 Flask 레이어

현재 Vite는 `/api`를 Flask `5001`로 프록시하고 있다. 따라서 1차 구현은 Flask Blueprint로 진행한다.

권장 파일 구조:

```text
app/routes/admin_mirofish.py
app/services/mirofish/
  brain_loader.py
  document_ingestor.py
  graphrag_extractor.py
  agent_debate.py
  social_simulation.py
  cio_react.py
  report_writer.py
  run_store.py
```

### 4.3 저장소

초기 MVP는 파일 기반 저장을 권장한다.

```text
data/admin_mirofish/
  runs/
    {run_id}/input.json
    {run_id}/status.json
    {run_id}/events.jsonl
    {run_id}/brain_snapshot.json
    {run_id}/graph.json
    {run_id}/agents.json
    {run_id}/social.json
    {run_id}/report.md
```

이후 SQLite로 확장한다.

```text
data/admin_mirofish/mirofish.db
```

SQLite 테이블 후보:

- `runs`
- `run_events`
- `documents`
- `graph_nodes`
- `graph_edges`
- `agent_messages`
- `social_posts`
- `social_comments`
- `cio_steps`
- `reports`

## 5. 파이프라인 설계

### 5.1 Step 1: 입력 수집

- 관리자가 뉴스/문서/텍스트를 입력한다.
- 문서는 chunk 단위로 분리한다.
- 기본 chunk: 1500자, overlap 200자

### 5.2 Step 2: ASCII Brain 로딩

- 기존 시장 데이터 JSON을 로드한다.
- 13D 지표를 표준 스키마로 정규화한다.
- 분석 실행 시점의 snapshot을 저장한다.

### 5.3 Step 3: GraphRAG 추출

- 입력 chunk에서 엔티티와 관계를 추출한다.
- 기존 EKG와 병합한다.
- 신규 관계는 `llm_inferred`로 태깅한다.

### 5.4 Step 4: 멀티 에이전트 토론

- 5명 고정 에이전트가 각자 관점으로 해석한다.
- 발언마다 Brain 수치 근거를 포함한다.
- 라운드별 합의/불일치를 기록한다.

### 5.5 Step 5: Social Simulation

- 에이전트 또는 가상 투자자들이 포스트/댓글을 생성한다.
- 내러티브 확산과 반응을 로그화한다.
- 과열/공포/관망 지표를 산출한다.

### 5.6 Step 6: ReACT CIO 판단

- CIO 에이전트가 도구 호출 기반으로 최종 판단한다.
- 각 단계는 trace로 저장한다.
- 최종 액션과 신뢰도를 산출한다.

### 5.7 Step 7: 리포트 생성

- 3~5장 마크다운 리포트 생성
- 그래프 요약, 근거, 반대 시나리오, 실행 계획 포함

## 6. 보안 및 권한

- 프론트 라우트: `AdminGuard` 적용 완료
- 사이드 메뉴: `userRole === 'admin'` 조건에서만 표시
- 백엔드 API: `/api/admin/mirofish/**` 아래에 배치
- 입력 문서와 실행 결과는 관리자 전용 저장소에만 저장
- 추후 외부 LLM 호출 시 입력 원문과 민감 정보 필터링 필요

## 7. 단계별 구현 계획

### Phase 0: 현재 완료

- 관리자 사이드 메뉴 ACCOUNT 영역에 카드 신설
- 카드 이름을 `MiroFish x ASCII Brain`으로 변경
- `/admin/endpoints` 라우트 추가
- 관리자 전용 기본 화면 추가
- 프론트 빌드 검증 완료

### Phase 1: 관리자 콘솔 UI 골격

- 현재 엔드포인트 카드 화면을 실제 콘솔형 화면으로 교체
- 입력 패널, 상태 패널, 결과 패널 배치
- mock run 데이터로 화면 흐름 구현

### Phase 2: Flask 관리자 API 추가

- `admin_mirofish` Blueprint 추가
- `/status`, `/runs`, `/runs/{id}` 기본 API 구현
- 파일 기반 run 저장소 구현

### Phase 3: Brain Loader 연결

- 기존 데이터 파일 상태 읽기
- 13D Brain snapshot 생성
- 프론트 상태 패널에 표시

### Phase 4: GraphRAG MVP

- 텍스트 입력 기반 엔티티/관계 추출
- 초기에는 rule/mock + LLM 선택형 구조
- 그래프 JSON 생성

### Phase 5: Agent Debate MVP

- 5명 고정 에이전트 프로필 구현
- Brain 수치 근거 포함 발언 생성
- 라운드별 debate log 저장

### Phase 6: CIO Report

- ReACT trace 저장
- 최종 판단 생성
- 마크다운 리포트 미리보기와 다운로드

### Phase 7: Social Simulation

- SQLite 기반 social timeline 추가
- 포스트/댓글/좋아요/팔로우 이벤트 저장
- 내러티브 확산 표시

## 8. 현재 작업 진행 보고

### 완료된 작업

- 로컬 프론트 서버 실행: `http://localhost:4000`
- 로컬 Flask API 실행: `http://127.0.0.1:5001`
- `/api/health` 정상 응답 확인
- 관리자 사이드 메뉴 ACCOUNT 영역에 신규 카드 추가
- 카드명 `MiroFish x ASCII Brain` 적용
- 관리자 전용 라우트 `/admin/endpoints` 추가
- `AdminEndpointsPage` 생성
- TypeScript/Vite production build 성공

### 현재 화면 상태

- 화면은 아직 실제 분석 콘솔이 아니라 API 연결 지점 안내 카드 형태다.
- `Admin`, `Data`, `MiroFish Ready` 3개 그룹으로 임시 분류되어 있다.
- 다음 작업에서 이 화면을 실제 실행 콘솔로 바꾸는 것이 자연스럽다.

### 남은 작업

- 실제 관리자용 분석 콘솔 UI 구현
- Flask `/api/admin/mirofish/**` API 구현
- run 저장소 구현
- Brain 13D 데이터 로더 연결
- GraphRAG 추출기 연결
- 에이전트 토론/리포트 생성 파이프라인 연결

## 9. 다음 작업 추천

다음 작업은 Phase 1이 적합하다.

`AdminEndpointsPage`를 아래 구조의 실제 콘솔 화면으로 교체한다.

```text
상단: MiroFish x ASCII Brain 상태/실행 버튼
좌측: 뉴스/문서 입력 + 실행 옵션
우측: Brain 13D 상태 + 최근 실행 목록
하단: GraphRAG / Agent Debate / CIO Report 탭
```

이렇게 먼저 화면 골격을 완성한 뒤, Phase 2에서 Flask API를 붙이면 프론트와 백엔드가 충돌 없이 단계적으로 연결된다.

## 10. 2026-05-02 구현 완료 보고

### 완료 범위

- 관리자 전용 사이드바 카드 `MiroFish x ASCII Brain`를 `/admin/endpoints`에 연결했다.
- `/admin/endpoints` 화면을 참고 이미지 기반의 주요 대시보드 콘셉트로 구현했다.
- `분석 시작` 클릭 시 단계형 임팩트 패널, 타깃 카드, Knowledge Graph, 실시간 Feed, Analyst 카드, 최종 BUY verdict 패널이 순차적으로 표시된다.
- Flask 관리자 API Blueprint `admin_mirofish`를 추가하고 `/api/admin/mirofish/**` 경로를 등록했다.
- 파일 기반 deterministic mock run store를 추가해 run, graph, markdown report 산출물을 생성/조회한다.
- 프론트 API 어댑터 `mirofishApi.ts`를 추가해 백엔드 원본 응답(`brain_summary`, `stance`, `confidence: 0.64`, 문자열 phase 로그)을 화면용 구조로 정규화한다.
- 전체 테스트 하네스 통과를 위해 누락된 LLM/test 의존성(`google-genai`, `anthropic`, `pytest-asyncio`)을 requirements에 추가했다.
- `scheduler._with_record` 실패/재시도 알림이 기존 테스트 더블과도 호환되도록 보강했다.

### 구현 파일

```text
app/routes/admin_mirofish.py
app/services/mirofish/__init__.py
app/services/mirofish/store.py
app/routes/__init__.py
frontend-react/src/lib/mirofishApi.ts
frontend-react/src/pages/admin/AdminEndpointsPage.tsx
tests/test_admin_mirofish_service.py
requirements.txt
scheduler.py
```

### 검증 결과

```text
python -m py_compile app/routes/admin_mirofish.py app/services/mirofish/store.py app/services/mirofish/__init__.py app/routes/__init__.py
python -m pytest tests/test_admin_mirofish_service.py -q
npm run build
python -B -c "import ast, pathlib; [compile(ast.parse(p.read_text(encoding='utf-8')), str(p), 'exec') for root in ['app','tests','scripts'] for p in pathlib.Path(root).rglob('*.py')]"
python -m pytest tests/test_scheduler_with_record.py -q
python -m pytest -q
Flask test_client smoke: GET /api/admin/mirofish/status, POST /api/admin/mirofish/runs, GET graph, GET report
```

모든 검증은 통과했다.

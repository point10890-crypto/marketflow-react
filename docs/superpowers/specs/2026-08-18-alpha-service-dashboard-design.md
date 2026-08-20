# Alpha Service Dashboard — 5개 일일 서비스 플랫폼과 통합 조회 API

2026-08-18 · 사용자 승인 방향 반영. 목적: 첨부 화면의 5개 서비스 흐름을 MarketFlow의
기존 알파 스캐너 보드 안에 운영 가능한 대시보드로 구성하고, 실제 저장 데이터만 조합하는
단일 읽기 전용 엔드포인트를 연결한다.

## 1. 목표와 설계 원칙

운영자는 한 화면에서 오늘의 알파 서비스가 어느 단계까지 진행됐는지, 각 단계의 데이터가
최신인지, 추천·포지션·성과에 실제 근거가 있는지를 판단할 수 있어야 한다.

- UI는 키움/르퓨쳐 화면의 기능적 흐름만 참고한다. 제품명, 문구, 점수 산식, 시각 구성,
  비공개 결과물은 복제하지 않는다.
- 화면 명칭은 MarketFlow 고유 명칭인 `Alpha Service Clock`을 사용한다.
- 숫자는 기존 JSON/CSV 실행 산출물 또는 결정론적 계산에서만 가져온다.
- 조회 요청은 스캔, 주문, KIS 시세 갱신, 산출물 재계산을 실행하지 않는다.
- 데이터가 없거나 오래됐으면 0이나 정상 상태로 바꾸지 않고 `empty`, `stale`, `partial`로
  그대로 보여준다.
- 이 화면은 투자 권유나 자동 주문 화면이 아니라, 검출·관찰·성과 증거를 보여주는 운영
  화면이다.

## 2. 범위

### 포함

1. 기존 관리자 알파 스캐너 보드 우측 `운영·성과 모니터` 레인의 첫 카드로 대시보드 배치
2. 다섯 서비스 단계 표시
   - 전일 시장 정리 — 오전 8시
   - 알파스코어 상위 종목 — 오전 8시 30분
   - 장중 종목 흐름 체크 — 장중
   - 당일 매매 신호 — 오후 3시
   - 최근 성과 브리핑 — 오후 6시
3. 기존 파일 기반 데이터 소스를 한 번에 조합하는 인증된 읽기 전용 API
4. 단계별 예정/경과 상태와 데이터 준비/노후/부분/없음 상태의 분리 표시
5. 로딩, 재시도, 빈 데이터, 부분 실패, 오래된 데이터, 모바일 레이아웃
6. 백엔드·프론트엔드 계약 및 회귀 테스트

### 제외

- 알파캐치의 비공개 점수 산식이나 추천 알고리즘 재현
- 신규 매수·매도 주문 실행
- 대시보드 조회 시 KIS/OpenDART/KRX 외부 호출
- 08시 시장 브리핑용 신규 업종 분류·뉴스 요약 엔진
- 스케줄러 작업 시간 또는 기존 포지션 규칙 변경
- 별도 구독자 페이지, 배포, MiniPC 운영 반영

## 3. 배치와 정보 구조

신규 컴포넌트 `AlphaServiceDashboard`를
`frontend-react/src/pages/admin/AdminEndpointsPage.tsx`의 우측 운영 레인 최상단에 둔다.
기존 `TodaysPipelineCard`, `ScanPerformanceCard`, `ScanHistoryCard`,
`RecentOutcomesBoard`는 아래에 유지하고, 숨겨진 Alpha Evidence 진단 영역도 변경하지 않는다.

```text
알파 스캐너 보드
├─ 좌측: 기존 검출·분석 레인
└─ 우측: 운영·성과 모니터 레인
   ├─ Alpha Service Clock          ← 신규
   │  ├─ 08:00 전일 시장 정리
   │  ├─ 08:30 알파스코어 상위 종목
   │  ├─ 장중 종목 흐름 체크
   │  ├─ 15:00 당일 매매 신호
   │  └─ 18:00 최근 성과 브리핑
   ├─ 오늘의 파이프라인
   ├─ 스캔 성과
   ├─ 스캔 이력
   └─ 최근 결과
```

다섯 단계를 좁은 우측 레인에서 위에서 아래로 읽히는 서비스 시계로 만든다. 단계 사이의
세로 레일과 시간 표식이 하나의 거래일 흐름을 형성한다. 이는 장식용 번호가 아니라 각
서비스가 현재 시각 기준 `upcoming`, `due`, `elapsed` 중 어디에 있는지를 전달한다.

## 4. 아키텍처와 데이터 흐름

```text
기존 저장 산출물
  ├─ paper_orchestrator.market_phase()
  ├─ alpha_scanner.get_scanner_schedule_status()
  ├─ alpha_scanner.read_latest_scanner_candidates() + 실행 provenance 보존
  ├─ pipeline_overview.get_pipeline_operating_snapshot()
  ├─ paper_orchestrator.paper_overview() + 로컬 가격 기준일 보존
  └─ pipeline_overview.get_outcomes_board()
            │
            ▼
alpha_dashboard.get_alpha_service_dashboard()
  ├─ 소스별 독립 예외 격리
  ├─ KST 일정 상태 계산
  ├─ 출처·기준시각·신선도 보존
  └─ 5개 서비스 계약으로 정규화
            │
            ▼
GET /api/admin/mirofish/alpha-dashboard
            │
            ▼
mirofishApi.getAlphaServiceDashboard()
            │
            ▼
AlphaServiceDashboard
```

백엔드 조합기는 각 소스를 독립적으로 읽는다. 한 소스가 실패해도 나머지 네 카드를
반환하고, 실패한 카드와 최상위 `warnings`에 구조화된 경고를 남긴다. 조회 경로에서는
`run_intraday_watch`, 스캐너 실행, 외부 데이터 갱신, 파일 쓰기 함수를 호출하지 않는다.

`read_latest_scanner_candidates()`는 최신 비어 있지 않은 실행의 `freshness`, `source_files`,
`source`, `generated_at`을 응답에 보존하도록 확장한다. 현재 입력 파일을 보는
`get_scanner_schedule_status()`의 신선도를 과거 후보 실행에 붙이지 않는다.
`paper_overview()`는 이미 읽는 로컬 가격 행의 날짜를 버리지 않고 각 보유 종목에
`last_close_date`로 추가한다. 두 변경 모두 기존 필드에 대한 추가형 계약이며 외부 조회나
파일 쓰기를 발생시키지 않는다.

## 5. API 계약

### 경로와 권한

- `GET /api/admin/mirofish/alpha-dashboard`
- 기존 조회 API와 같은 `admin_or_aibain_required` 적용
- 쿼리
  - `candidate_limit`: 1–20, 기본 5
  - `outcome_days`: 1–180, 기본 30
  - `outcome_limit`: 1–50, 기본 10
- 범위를 벗어나거나 정수가 아닌 값은 기존 MiroFish 조회 라우트와 같은 방식으로 `400`
  응답한다. 누락된 값에만 기본값을 쓰며, 공백·실수·불리언·부호만 있는 문자열은 거부한다.
- 오류 형식은
  `{"error":"invalid_query","message":"candidate_limit must be an integer between 1 and 20"}`
  형태로 고정한다.
- 응답에 `Cache-Control: no-store`를 설정해 브라우저 캐시가 오늘 상태를 오래 유지하지
  않게 한다.

### 응답 형태

```json
{
  "schema_version": "mirofish.alpha_service_dashboard.v1",
  "generated_at": "2026-08-18T09:10:00+09:00",
  "timezone": "Asia/Seoul",
  "date_kst": "2026-08-18",
  "status": "ready",
  "services": [
    {
      "id": "market_brief",
      "order": 1,
      "title": "전일 시장 정리",
      "description": "시장 국면과 시장 폭을 확인합니다.",
      "schedule": {
        "label": "오전 8시",
        "time_kst": "08:00",
        "phase": "elapsed",
        "calendar_status": "unverified"
      },
      "data_status": "partial",
      "as_of": "2026-08-17",
      "summary": "결정론적 템플릿으로 만든 요약",
      "metrics": [
        {
          "key": "breadth",
          "label": "시장 폭",
          "value": 54.2,
          "unit": "%",
          "tone": "neutral"
        }
      ],
      "items": [],
      "warnings": [
        {
          "code": "leading_sectors_unavailable",
          "message": "검증된 업종 분류 데이터가 없어 주도 업종을 표시하지 않습니다.",
          "severity": "info"
        }
      ],
      "provenance": {
        "sources": [
          {
            "source": "market_phase",
            "run_id": null,
            "as_of": "2026-08-17",
            "freshness": "fresh",
            "fallback": false
          }
        ]
      }
    }
  ],
  "warnings": [],
  "links": {
    "scanner_latest": "/api/admin/mirofish/scanner/runs/latest",
    "outcomes_board": "/api/admin/mirofish/outcomes/board",
    "paper_overview": "/api/admin/mirofish/paper/overview",
    "pipeline_today": "/api/admin/mirofish/pipeline/today"
  }
}
```

`services`는 항상 위의 다섯 ID를 일정 순서로 반환한다.

공통 타입은 다음과 같이 고정한다.

- `status`, `data_status`: `ready | stale | partial | empty`
- `schedule.phase`: `upcoming | due | elapsed`
- `schedule.calendar_status`: v1에서는 `unverified`
- `metrics[].value`: `number | string | null`
- `metrics[].tone`: `positive | neutral | warning | negative`
- `warnings[]`: `{code, message, severity: info | warning | error}`
- `provenance.sources[]`: `{source, run_id, as_of, freshness, fallback}`
- 시간은 ISO 8601 오프셋 포함 문자열, 거래 기준일은 `YYYY-MM-DD`, 알 수 없으면 `null`

| 서비스 ID | 일정 | 실제 데이터 | 핵심 표시 |
|---|---:|---|---|
| `market_brief` | 08:00 | `market_phase()` | 4국면, regime, breadth, 5일 변화, 기준일 |
| `score_leaders` | 08:30 | 스캐너 일정 상태 + 최신 비어 있지 않은 후보 실행 | TOP 후보, alpha/risk score, 액션, 실행 ID와 신선도 |
| `intraday_flow` | 장중 | `paper_overview()`의 저장된 포지션 | 종목, 마지막 저장 가격, 미실현 수익률, 보유일, 목표/손절 상태 |
| `trade_signals` | 15:00 | paper pending/open + pipeline snapshot | 대기·보유·최근 종료 수, 파이프라인 단계 상태 |
| `performance_brief` | 18:00 | paper performance + outcomes board | 표본 수, 승률, 수익률, hit/miss, 평가 기간 |

`score_leaders`의 후보는 현재 실행을 가장하는 대신 `latest_nonempty_run`으로 명시한다.
`intraday_flow`는 외부 시세를 새로 가져오지 않으며 `마지막 저장 가격 기준`임을 표시한다.
성과 값은 거래 표본 수와 함께 보여주며, 표본이 없을 때 수익률 0을 성과 달성으로 표현하지
않는다.

카드별 `items`는 임의 객체가 아니라 다음 필드 집합으로 고정한다.

| 서비스 ID | item 필드 |
|---|---|
| `market_brief` | v1은 빈 배열. 검증된 업종 소스가 생길 때 별도 버전에서 확장 |
| `score_leaders` | `rank`, `symbol`, `name`, `market`, `alpha_score`, `risk_score`, `action`, `horizon`, `price` |
| `intraday_flow` | `symbol`, `name`, `entry_price`, `last_close`, `last_close_date`, `unrealized_pct`, `held_trading_days`, `target_price`, `stop_price` |
| `trade_signals` | `key`, `label`, `count`, `window_days`, `status` |
| `performance_brief` | `source`, `sample_count`, `window_days`, `win_rate`, `average_return_pct`, `cumulative_return_pct`, `hit_count`, `miss_count` |

`breadth`와 5일 변화는 원본 0–1 비율을 `round(value * 100, 1)`로 변환해 `%` 단위로
반환한다. `performance_brief` 안에서도 두 성과 계열을 섞지 않는다.

- `paper_30d`: 가상 청산 거래의 30일 표본, 승률, 평균/누적 수익률
- `workflow_outcomes`: forward outcome 평가 표본, hit/miss, 평균 수익률과 요청된 평가 기간

`trade_signals`의 최근 종료 수는 `paper_30d` 거래 수로 명명하고 `window_days: 30`을
붙인다. workflow 평가 수와 같은 수치로 표현하지 않는다.

### 상태 의미

일정 상태와 데이터 상태를 분리한다.

- `schedule.phase`
  - `upcoming`: 오늘 예정 시각 전
  - `due`: 고정 시각 서비스는 예정 시각부터 15분 미만, 장중 서비스는
    `09:00 <= KST < 15:30`
  - `elapsed`: 고정 시각 서비스는 예정 시각 15분 후, 장중 서비스는 15:30 이후
- `data_status`
  - `ready`: 실제 산출물과 기준 시각이 있고 신선도 조건을 충족
  - `stale`: 사용할 수 있으나 신선도 판정이 stale/missing/partial/unknown
  - `partial`: 카드의 핵심 일부는 있으나 보조 소스가 없거나 읽기 실패
  - `empty`: 표시할 실제 데이터가 없음

장중 단계는 고정 시각 대신 국내 정규장 구간을 사용한다. 비거래일 판정을 위한 신뢰 가능한
거래일 달력이 현재 조합기에 없으므로, v1은 KST 시각 구간만 표시하고 실제 데이터 준비
상태를 별도 배지로 구분한다. 주말을 거래 완료로 오인하지 않도록 UI 문구는 `예정`, `구간`,
`경과`를 사용하고 `실행 완료`를 사용하지 않는다. 모든 일정 계산 함수는 테스트 가능한
`now: datetime | None` 인자를 받고, 값이 있으면 KST로 변환하며 값이 없을 때만 현재 KST를
사용한다. `calendar_status: unverified`를 항상 함께 반환한다.

카드별 `data_status` 계산은 다음 규칙을 따른다.

1. 핵심 소스 읽기 예외가 있으면 `partial`
2. 예외 없이 핵심 데이터가 없으면 `empty`
3. 핵심 데이터는 있으나 그 provenance가 stale/unknown이면 `stale`
4. 핵심 데이터는 정상이나 카드 계산에 필요한 보조 소스가 실패하면 `partial`
5. 나머지는 `ready`

`leading_sectors_unavailable`처럼 v1에서 명시적으로 지원하지 않는 선택 필드의 `info` 경고는
카드 상태를 낮추지 않는다. `market_phase()`가 fallback 값을 반환하고 `as_of`가 없으면
`provenance.fallback: true`, `freshness: unknown`을 기록하고 카드는 `stale`로 표시한다.

최상위 `status` 계산 우선순위는 다음과 같다.

1. 하나라도 소스 읽기 예외가 있으면 `partial`
2. 예외가 없고 스캐너 실행, workflow outcome, paper open/pending/30일 거래가 모두 없으면
   `empty`
3. 데이터가 있는 카드 중 필수 보조 소스 실패로 `partial`인 카드가 있으면 `partial`
4. 사용할 수 있는 데이터 중 stale/unknown provenance가 있으면 `stale`
5. 나머지는 `ready`

`partial`과 `stale`가 동시에 있으면 최상위는 `partial`이고, 해당 카드의 `stale` 표시는
그대로 유지한다.

알 수 없는 값은 `null`로 둔다. 요약 문장은 LLM이 아니라 응답 필드에 대한 고정 템플릿으로
만든다.

## 6. 시각 디자인

첨부 화면의 명료한 5개 블록 구조는 유지하되, 현재 관리자 보드의 어두운 운영 화면에 맞춰
재해석한다. 흰색 마케팅 카드나 과도한 그라데이션은 사용하지 않는다.

- 배경: 기존 페이지 배경 유지
- 카드: `#151C28` 계열 패널, 얇은 저채도 경계선, `rounded-xl`
- 본문/헤더: Pretendard 우선의 기존 시스템 산세리프
- 시간, 종목 코드, 수치: 기존 `font-mono`
- 신호색
  - Signal Cyan `#67E8F9`: 현재 구간과 정보 강조
  - Verified Mint `#6EE7B7`: 준비된 데이터
  - Waiting Amber `#FCD34D`: 예정·부분·오래된 데이터
  - Risk Rose `#FDA4AF`: 실패·위험·손실 경고
- 한 카드의 강조색은 상태 배지, 레일 표식, 얇은 왼쪽 경계에만 사용한다.
- 레일의 현재 구간 표식에만 은은한 발광을 허용한다.

### 헤더

- 제목 `Alpha Service Clock`
- 보조 문구 `시장 정리 → 후보 → 장중 관찰 → 신호 → 성과`
- 최상위 상태 배지와 `generated_at` 표시
- 기존 보드의 새로고침 흐름과 연결해 중복 실행 버튼을 만들지 않는다.

### 카드

각 카드에는 다음 정보만 노출한다.

1. 시간/구간 라벨
2. 서비스 제목과 한 줄 설명
3. 일정 상태와 데이터 상태 배지
4. 기준 시각
5. 1–3개 핵심 지표 또는 최대 5개 종목
6. 오류·누락·신선도 경고 한 줄

세부 테이블과 전체 실행 증거는 기존 스캐너·파이프라인·성과 카드에서 확인하게 하여 중복을
피한다.

### 반응형과 접근성

- 현재 우측 레인에서는 단일 열 세로 흐름으로 표시한다.
- 좁은 화면에서도 카드 순서를 유지하며 가로 스크롤을 만들지 않는다.
- 상태는 색만으로 전달하지 않고 텍스트 배지와 아이콘 의미를 함께 제공한다.
- 시간 레일은 장식 요소로 처리하고, 스크린 리더에는 각 카드 제목과 상태를 완전한 텍스트로
  제공한다.
- 최소 터치 영역 44px, 본문 최소 12px, 핵심 수치 최소 14px를 유지한다.
- 로딩 시 카드 높이가 급변하지 않도록 5개 고정 스켈레톤을 사용한다.

## 7. 오류·빈 상태·신선도 처리

- 전체 요청 실패: 카드 영역 안에 간결한 오류 메시지와 재시도 버튼을 표시한다.
- 일부 소스 실패: 성공한 카드는 유지하고 해당 카드만 `partial` 또는 `empty`로 표시한다.
- 최신 비어 있지 않은 스캐너 실행만 존재: 실행 ID와 기준일을 명시하고 현재 실행으로
  표현하지 않는다.
- market phase가 기본 fallback이고 `as_of`가 없으면 `ready`가 아닌 `stale`로 표시한다.
- 저장 포지션은 있으나 저장 가격 시각이 없으면 미실현 수익률을 숨기고 기준 불명 경고를
  표시한다.
- 성과 표본이 0이면 승률·누적수익을 대시(`—`)로 표시하고 `표본 없음`을 노출한다.
- 주도 업종 데이터는 현재 결정론적 업종 소스가 없으므로 빈 배열과
  `leading_sectors_unavailable` 정보 경고로 반환한다. 이 경고만으로 카드 상태를 낮추지
  않으며 임의 업종명을 만들지 않는다.

## 8. 변경 파일

### 백엔드

- 신규 `app/services/mirofish/alpha_dashboard.py`
  - 다섯 소스 조합
  - KST 일정 상태 계산
  - 상태/경고/출처 정규화
- 수정 `app/services/mirofish/__init__.py`
  - 읽기 함수 export
- 수정 `app/services/mirofish/alpha_scanner.py`
  - 최신 비어 있지 않은 후보 실행의 freshness/source_files/source 보존
- 수정 `app/services/mirofish/paper_orchestrator.py`
  - 로컬 가격 행의 `last_close_date`를 open position에 추가
- 수정 `app/routes/admin_mirofish.py`
  - 쿼리 검증 및 GET 라우트
- 신규 `tests/test_mirofish_alpha_dashboard.py`
  - 서비스 계약과 실패 격리 테스트

### 프론트엔드

- 신규 `frontend-react/src/components/admin/AlphaServiceDashboard.tsx`
  - 단일 조회 상태, 5개 카드, 스켈레톤·오류·빈 상태
  - 마운트 즉시 조회, 화면이 보이는 동안만 60초 간격 갱신, unmount 시 정리
- 수정 `frontend-react/src/lib/mirofishApi.ts`
  - 응답 타입과 조회 함수
- 수정 `frontend-react/src/pages/admin/AdminEndpointsPage.tsx`
  - `ops-lane-${opsLaneRefreshKey}`의 우측 운영 레인 최상단에 마운트
  - 기존 운영 레인 새로고침 시 remount되어 즉시 재조회
- 신규 `frontend-react/src/test/alphaServiceDashboard.test.tsx`
  - 정상·부분·오류·빈 상태 렌더링
- 수정 `frontend-react/src/test/adminEndpointsEnter.test.tsx`
  - 기존 보드 진입 회귀 검증에 필요한 최소 mock 보강

## 9. 테스트 전략

### 백엔드 TDD

1. 정상 응답이 정확히 다섯 서비스를 일정 순서로 반환한다.
2. 각 지표가 소스 값과 실행 ID/기준시각을 보존한다.
3. 스캐너 없음, 성과 없음, 저장 포지션 없음이 0 성과로 위장되지 않는다.
4. stale 신선도가 카드와 최상위 상태에 반영된다.
5. 한 소스 예외가 전체 응답을 깨지 않고 `partial` 경고가 된다.
6. 쿼리 경계와 잘못된 값은 `400`을 반환한다.
7. 테스트에서 갱신·실행·파일쓰기·외부 호출 함수가 호출되지 않는다.
8. 후보 목록 provenance는 최신 비어 있지 않은 실행의 값이고 현재 입력 신선도와 섞이지
   않는다.
9. `candidate_limit`의 0/21, `outcome_days`의 181, `outcome_limit`의 51과 실수·공백 입력을
   각각 거부하고 `Cache-Control: no-store`를 검증한다.
10. `get_pipeline_operating_snapshot()`만 호출하고 비동기/캐시 갱신이 있는
    `get_pipeline_today_snapshot()`은 호출하지 않는다.
11. `create_scanner_run`, `run_scanner_realtime_monitor_check`, `run_intraday_watch`,
    outcome refresh와 atomic write 함수가 조회 경로에서 호출되지 않는다.

### 프론트엔드 TDD

1. 헤더와 다섯 서비스 카드가 응답 순서대로 보인다.
2. 후보 종목, 저장 포지션, 표본 수가 서버 값 그대로 보인다.
3. `stale`, `partial`, `empty`가 서로 다른 텍스트로 보인다.
4. 일부 카드 경고와 최상위 경고를 혼동하지 않는다.
5. 요청 실패 시 재시도가 같은 엔드포인트를 다시 호출한다.
6. 관리자 보드 진입 시 기존 카드와 신규 대시보드가 함께 렌더링된다.
7. 60초 갱신은 탭이 보일 때만 동작하고 unmount 후 중지된다.

### 검증 순서

```powershell
python -m pytest tests/test_mirofish_alpha_dashboard.py -q
python -m compileall app/services/mirofish/alpha_dashboard.py app/routes/admin_mirofish.py
python -m pytest tests/test_mirofish_pipeline_overview.py tests/test_mirofish_aibain_overview.py tests/test_paper_positions.py tests/test_admin_mirofish_alpha_scanner.py tests/test_signal_contract.py -q

Set-Location frontend-react
npm run test -- alphaServiceDashboard.test.tsx adminEndpointsEnter.test.tsx
npm run test
npm run build
```

브라우저 검증에서는 데스크톱과 모바일 폭에서 카드 순서, 레일 정렬, overflow, 로딩 높이,
부분 실패 및 빈 상태를 확인한다.

## 10. 완료 기준

- 인증된 단일 GET 요청만으로 다섯 서비스 카드가 채워진다.
- 모든 수치에 실제 데이터 출처와 기준 시각 또는 명시적 미확인 상태가 있다.
- 대시보드 조회만으로 외부 호출, 스캔, 주문, 파일 갱신이 일어나지 않는다.
- 주도 업종·실시간 시세처럼 현재 근거가 없는 항목은 허구로 채워지지 않는다.
- 기존 알파 스캐너 보드의 검출·파이프라인·성과 기능이 그대로 동작한다.
- 백엔드와 프론트엔드 집중 테스트, 전체 프론트엔드 테스트, 프로덕션 빌드가 통과한다.

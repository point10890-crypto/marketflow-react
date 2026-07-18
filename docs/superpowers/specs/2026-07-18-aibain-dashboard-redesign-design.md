# AI Brain 대시보드 리디자인 설계 (스마트 · 절제)

- 날짜: 2026-07-18
- 상태: 사용자 승인 완료 → 구현
- 대상: `https://bit-man.net/dashboard/ai-bain` (구독자용 AI Brain 대시보드)
- 성격: **순수 프론트 프레젠테이션 리디자인.** 백엔드 `/api/admin/mirofish/aibain/overview` API·데이터 구조 무변경.

## 문제

현재 5개 카드 스택이 복잡하고 핵심 파악이 어렵다:
- **검출 화면 중복**: ScannerEventsCard(실시간 신규 이벤트 최대 8개, 30초 폴링) + DetectionsCard(오늘의 검출 Top 3) — 둘 다 검출 종목 표시
- **배지 레인보우**: 종목마다 4~5개 색 배지(action/등급/리스크/알파/RS/매수유력)
- **운영성 메타 칩 다수**: 시각·최종후보·신규·상태·갱신
- **전문용어 밀도**: 레짐 분포, 기대 %, n=, false_positive
- 긴 스크롤, 명확한 우선순위 부재

## 목표

"핵심만 쉽게" — 구독자가 **① 지금 뭘 사야 하나(검출)** 와 **② AI가 믿을 만한가(성과)** 를 한눈에.

## 설계: 5카드 → 3블록

### ① 슬림 헤더 (기존 큰 그라디언트 히어로 대체)
- 한 줄 레이아웃: `AI Brain` 제목 + 라이브 pulse 점 + `마지막 검출 MM/DD HH:mm` + 우측 신뢰칩 `최근 N일 적중률 XX%`
- 제거: 로봇 아이콘 대형 블록, ALPHA SCAN 배지, 설명 문단, 우상단 장식 그라디언트
- 적중률 데이터는 `overview.performance.hit_rate_pct`, 마지막 검출은 `overview.detections.as_of`

### ② 메인 = 오늘의 검출 (Top 3) — 유일한 주인공
- **ScannerEventsCard(실시간 피드) 구독자 화면에서 제거** (관리자 콘솔 `AdminEndpointsPage` 에는 유지 — 공유 컴포넌트이므로 import 만 제거)
- 각 종목 카드:
  - 좌: 순위 pill + 종목명(크게) + 코드(mono) + 현재가·등락(등락은 녹/적)
  - 우: **판정 배지 1개만 강조** — 🔥 매수 유력(STRONG_BUY) / AI 매수(BUY). 기존 tradingAgentsBadge 재사용
  - 하단: 색 배지 대신 **무채색 mono 보조줄** `Alpha 88 · Risk 21 · RS 92 주도주` (RS 등급 라벨만 텍스트로 유지)
  - STRONG_BUY 카드: 테두리 은은한 강조(orange/rose 저채도)
- 데이터: `overview.detections.items[]` (기존 필드 + `tradingagents`, `alpha_score`, `risk_score`, `rs_rating`)
- 빈 상태: "오늘 신규 검출이 없습니다"

### ③ 성과 신뢰 스트립 (큰 타일3+리스트 → 얇게)
- 한 줄 밴드: `적중률 XX% · 평균 +Y% · 표본 Z개` (인라인, KPI 대형 타일 제거)
- 최근 검증 결과: 작은 pill 가로 wrap — 각 pill 은 `▲+5.2%` / `▼-2.1%` (녹/적), 종목명은 title 속성/생략으로 밀도 축소. 최대 8개
- 데이터: `overview.performance.{hit_rate_pct, avg_forward_return_pct, evaluated_count, verified[]}`
- 빈 상태: "성과 검증 데이터를 누적 중입니다"

### ④ 학습 신호 (전체 LearningCard 제거 → 한 줄 보존)
- 성과 스트립 하단 무채색 footer 한 줄: `AI 학습: 잘 맞은 패턴 "<top_positive[0].combo>"` (있을 때만)
- 전문용어 테이블(기대%·n=·레짐 분포) 전부 제거. "AI가 학습 중" 신호만 1줄로 유지
- 데이터: `overview.learning.top_positive[0].combo` (없으면 미표시)

## 색·타이포 규율
- 단일 액센트 = 시안. 등락·성과 = 녹(양)/적(음). 판정 = orange(매수유력)/teal(매수)
- 제거: violet(등급), amber(리스크 배지) — mono 텍스트로 대체
- 카드 배경 `#13151f`, 페이지 `#09090b` 유지(앱 표준 다크)

## 컴포넌트 구조
| 파일 | 변경 |
|------|------|
| `AiBainDashboard.tsx` | 슬림 헤더로 교체, ScannerEventsCard·LearningCard import/렌더 제거, 헤더에 적중률/마지막검출 전달 |
| `DetectionsCard.tsx` | 배지 레인보우 → 판정배지1 + mono 보조줄. tradingAgentsBadge·rsBadge 로직 유지(RS는 텍스트화) |
| `PerformanceCard.tsx` | KPI 타일3 → 인라인 밴드, 리스트 → ▲▼ pill 가로줄, 학습 footer 1줄 추가(props 확장) |
| `LearningCard.tsx` | 구독자 화면에서 미사용(파일 삭제 또는 유지하되 import 제거) |
| `aibainDashboard.test.tsx` | 새 구조에 맞게 assertion 갱신(적중률 헤더칩, 판정배지, 스캐너피드 부재) |

## 범위 제외 (YAGNI)
- 백엔드 변경 없음 (API·overview 구조 그대로)
- 관리자 콘솔(AdminEndpointsPage) 변경 없음 — ScannerEventsCard 는 거기 유지
- 접이식/탭/애니메이션 등 인터랙션 추가 없음 (정적 스택, 스트리밍 안전)

## 검증
- vitest: 새 구조 렌더 assertion (적중률 칩, Top3 판정배지, 스캐너피드 미표시, 성과 밴드)
- tsc --noEmit clean
- 빌드 후 dist grep 로 배지/구조 문자열 확인 (유령 프로세스 stale build 주의: [[feedback_vite_stale_build_process]])
- 배포 후 프로덕션 bit-man.net 번들 검증

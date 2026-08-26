# 목표 정의 + 마스터 플랜 — 설계 4편의 우선순위 확정

작성일: 2026-08-24 (KST)
성격: **사용자 확인을 거친 목표 정의**(본 문서 §1)로 기존 설계 4편의 로드맵을 단일 우선순위로 재정렬한 최상위 문서. 충돌 시 본 문서가 우선한다.
하위 문서: ① `2026-08-24-analysis-core-redesign.md`(v3) ② `2026-08-24-alphaclaw-integration-review.md` ③ `2026-08-24-omnisource-sensor-design.md`

---

## 1. 목표 정의 (2026-08-24 사용자 확인)

| 질문 | 답 |
|---|---|
| 최종 결과물 | **① 본인 매매용 시그널** (소수의 고신뢰 후보 — 검출·진입·청산 신호) + **② 구독 상품 강화** (구독자 제공 분석·검출 기능의 품질·차별성) |
| 성공 판정 기준 (단일) | **검출 정밀도** — 틀린 후보를 줄이는 것: 적중률·손익비·조기 제외 성공률. 수익 실현은 사람 몫 |
| 소비 방식 | 장중 실시간 알림 + 정기 브리핑 + 대시보드 조회 + 자동 실행 |
| 선택하지 않은 것 | **완전 자동 매매** (검출→주문 무인 실행), 시장 인텔리전스 단독 목적, 정보 우위 단독 목적 |

**해석 확정 2건** (사용자 답변 간 정합):
1. Q3의 "자동 실행"은 Q1에서 "완전 자동 매매"를 선택하지 않았으므로 **파이프라인 자동 가동**(수집→분석→검출→알림을 사람 개입 없이 24시간)으로 해석한다. 주문 실행이 아니다. → **E-게이트(주문 경로)는 닫힌 상태 유지.** 다르게 의도하셨다면 이 줄을 정정할 것.
2. "구독 상품 강화"는 매매 지시 판매가 아니라 **검출 근거·무효화 조건·성과 검증의 투명한 제공**으로 구현한다 (verdict에 buy/sell 부재 유지 — 기존 정책이자 컴플라이언스 경계).

### 성공 기준의 조작적 정의 (검출 정밀도)

| 지표 | 정의 | 현재 상태 |
|---|---|---|
| precision@K / nDCG@3 / rank IC | TOP3 검출의 순위 정확도 | **구현돼 있으나 정체·표본부족** (top3_metrics: 본PC 6/20 정지, miniPC insufficient) |
| 적중률·손익비 (비용 후) | outcome 평가된 검출의 hit rate·평균익/평균손 (왕복 0.23%+슬리피지 차감) | gross만 존재 — 비용 차감 미적용 |
| 조기 제외 성공률 | 무효화 트리거로 만기 전 버린 후보가 실제로 손실을 줄였는가 (`early_exit_saved_pct` 분포) | 미구현 (shadow 설계만) |
| 오탐 노출 | 음(-)국면·근거 미달(E1 위반) 후보가 알림으로 나간 건수 (0 목표) | 측정 안 됨 |

**따라서 1순위 작업은 "정밀도를 올리는 것"이 아니라 "정밀도를 신뢰 가능하게 측정하는 것"이다.** 지금은 정밀도가 얼마인지조차 신선한 수치로 말할 수 없다.

---

## 2. 우선순위 재정렬 (목표 기준)

기존 4편의 로드맵(R0′~R5, O1~O5)을 목표 기여도로 재배열한다.

### P1 — 정밀도 측정 기반 복구 *(이것 없이는 아무것도 판정 불가)*
- **P1-a**: outcome·top3_metrics 파이프라인 정상화 — 정체 원인(런 표본 부족) 진단, 평가 주기 재가동, freshness 필드 상시화. *(v3 R0의 확장 — Codex #7)*
- **P1-b**: R0′ 비용 차감 재현 — miniPC detection_lab 재실행, gross/net 동시 산출, 국면 게이트 근거를 가설 H-*로 소급 등록. *(AlphaClaw B1·B2)*
- 완료 판정: "현재 검출 정밀도는 (비용 후) 이렇다"를 최근 데이터로 말할 수 있음.

### P2 — 정밀도 개선 장치 *(틀린 후보 제거 = 성공 기준 직결)*
- **P2-a**: 관측 원장 — episode + RegimeContext + profitability_goal.v2(무효화·공백·cap 필드). *(v3 R1)*
- **P2-b**: 무효화 shadow 3종(DROP·만료·손절선) → `early_exit_saved_pct` 축적. *(v3 R2)*
- **P2-c**: 리스크 판정 독립성 + numbers_used verify — 낙관 편향 제거. *(AlphaClaw B3·B4)*
- 완료 판정: shadow 조기 제외가 net 기준 손실을 줄였다는 분포 확인.

### P3 — 전달 (두 소비자에게)
- **본인**: 장중 무효화 발송 활성(P2 검증 후) + 조간/마감 브리핑에 정밀도 지표 병기. *(v3 R3)*
- **구독자**: scorecards API + 품질 KPI 카드 + AiBain 검출 카드에 근거 등급·무효화 조건·검증 성적 노출 — "왜 이 후보인가 + 언제 버리는가"가 상품 차별성. *(v3 R4/G6, AlphaClaw B6)*

### P4 — 옴니소스 (정밀도 기여 범위로 축소 재정의)
- 정보 우위는 선택된 성공 기준이 아니므로, 옴니소스의 역할을 **"검출 후보의 근거 보강(evidence)과 무효화 트리거(DART 악재·정책 이벤트) 공급"**으로 한정한다. 커버리지 확대 자체는 KPI가 아니다.
- O1(뉴스 RSS+결정론 깔때기)·O2(태거)는 P3 이후 착수. O3~O5(유튜브·학술·소셜)는 P4 성과 확인 후.

### 상시 — 문서·운영
- SOUL.md + 킬스위치 레벨표 (코드 무변경, 병행). *(AlphaClaw B5)*

### 닫힘 유지
- **E-게이트(주문 실행)**: Q1에서 미선택. 재론은 사용자 명시 요청 시에만.

---

## 3. 목표가 바꾼 것 (변경 대장)

| 항목 | 목표 확인 전 | 목표 확인 후 |
|---|---|---|
| 1순위 | R0′ 재현 (근거 복구) | **P1 = R0′ + 정밀도 측정 파이프라인 정상화** — "측정 가능"이 재현보다 상위 개념 |
| 옴니소스 위치 | 독립 병행 트랙 | P4로 후순위 + 역할을 근거 보강·무효화 공급으로 한정 |
| KPI 서열 | 품질 KPI 6종 병렬 | **정밀도 4종(§1)이 최상위**, 나머지는 보조 |
| 구독 관점 | G6 부수 항목 | P3의 절반 — 근거·무효화·검증 성적의 투명 노출이 상품 차별성 |
| E-게이트 | 정의만 하고 미결 | **닫힘 확정** (사용자 미선택) |
| 성과 지표 방향 | 수익률·정밀도 혼재 | 수익률은 검증 증거로만, 판정 기준은 정밀도 |

## 4. P1 진행 상태 (2026-08-25 갱신)

### P1-a 진단 — 완료 (본PC)
**정체 원인 확정**: `top3_metrics`·`interaction_map`은 "아티팩트 파일이 없을 때만" 지연 빌드되는 구조였고, 정기 재빌드 경로가 어디에도 없었다 (agent `run_maintenance`는 backtest·outcome만 갱신). 파일이 한 번 생기면 영원히 그 시점에 고정 — 본PC 6/20 정지·miniPC insufficient의 코드 레벨 원인.

### P1-a 수정 — 구현 완료 (본PC, TDD, 커밋 대기)
- `top3_metrics_summary()`에 `generated_at`/`stale`(기본 24h, env `MIROFISH_TOP3_REFRESH_HOURS`) 노출
- `agent_actions`에 `refresh_intelligence` 액션 신설 (top3 + interaction_map 재빌드, 읽기전용 리플레이 산출물)
- `run_maintenance`가 top3 stale/부재 시 해당 액션을 결정론적으로 발행 → 기존 evening(16:30)/night(23:30) 사이클에서 자동 복구
- 실증: 본PC 로컬 실행에서 6/20 정지 아티팩트가 실제 재빌드됨 (evaluated_runs 6, insufficient 해제)

### P1-b 비용 차감 — 구현 완료 (본PC, TDD, 커밋 대기) / 재실행은 miniPC 대기
- `app/services/mirofish/costs.py` 신설 — 왕복 0.23% + 슬리피지 env `MIROFISH_SLIPPAGE_PCT`(기본 0, 실측 불가 명시)
- `detection_lab._metrics`에 `net` 블록 병기 (expectancy/win_rate/PF/cumulative + 국면별 net_expectancy) — gross 유지
- `paper_positions.performance_summary`에 `net_avg_return_pct`/`net_cumulative_return_pct`/`round_trip_cost_pct` 병기
- `scripts/detection_lab_run.py` 요약표에 net 컬럼 추가
- 테스트: 신규 14개 + 기존 회귀 갱신 1개, 영향권 전체 통과
- **miniPC 재실행(R0′ 재현 판정)은 보류** — 본PC↔miniPC LAN 단절 (프로덕션 터널은 정상, SSH 불가). 연결 복구 후: git pull → `python scripts/detection_lab_run.py` → gross/net 리포트 아카이브

### R0′ 재현 판정 (2026-08-26, miniPC 8/24 리포트 `report_20260824_031621_202004.json`, 검출 625건)

| 룰셋 | gross | net (왕복 0.23%) |
|---|---|---|
| baseline | win 36.2% · exp −1.54% · PF 0.65 | exp −1.77% · PF 0.61 |
| V1 국면 게이트 | win 51.3% · exp +0.79% · PF 1.24 | **exp +0.56% · PF 1.17** |
| V1+V2 (+Stage2) | win 52.5% · exp +0.91% · PF 1.28 | exp +0.68% · PF 1.21 |
| V1+V2+V3 (+ATR) | win 58.7% · exp +3.69% · PF 1.98 (n=46) | exp +3.46% · PF 1.90 |

**판정: 부분 재현.** ① baseline=손실 시스템은 재확인(방향성 유효). ② 그러나 기록된 게이트 강도(+2.60%/PF 2.06/승률 63%)는 재현 안 됨 — 현재 +0.79%/PF 1.24/51.3%, 비용 후 +0.56%. 주원인 후보: uptrend_broadening 국면 기대값 +3.00% → +0.47% 급락(표본 603→625 변화). ③ 과거 기각했던 V1+V2+V3 조합이 새 표본에서 최량(net +3.46%)이나 n=46으로 소표본 — 과적합 경계, 채택 논의는 원인 규명 후.

**R0′ 규칙 적용**: 국면 게이트는 유지(방향성 유효)하되 근거 강도 "재검증 중" — **E5 발송 억제 등 신규 정책 활성은 보류 유지.** 후속: 8/16(603건) vs 8/24(625건) 리포트 diff 로 악화 원인 규명(추가 22건의 국면·시기 분포), 새 코드 배포 후 재실행으로 net 네이티브 산출.

### P1 배포 (2026-08-26, 하네스 `2026-08-26-p1-deploy-harness.md` G0~G5)

- 커밋 `673e1b5` push·miniPC pull·재부팅 활성화 완료. 운영 Flask(5003)가 net 필드 서빙 실증(G5-③).
- **배포 중 발견**: miniPC 작업트리에 미커밋 작업본 23파일(+3,823줄 — claw 개편·워치독 재작성·detection_lab/regime 수정, 코덱스 추정)이 운영 중이었음 → **`stash@{0}`에 보존** (이번 배포에 미포함, 검토·정식 커밋 필요). 미확인 5001 프로세스는 재부팅 후 소멸(드리프트 실행이었음).

### R0′ 최종 판정 (2026-08-26 재실행 `report_20260826_133749.json`, 검출 642건, 커밋 코드)

- **lab-운영 게이트 정의 불일치 발견**: 커밋된 lab V1은 `downtrend`만 차단(detection_lab.py:154) → n=199, gross −0.92%/net −1.15%. 운영 paper 게이트는 `downtrend+rebound_early` 차단. 8/24 리포트(+0.79%)는 양국면 차단의 **드리프트 lab 코드** 산출물이었음.
- **운영 게이트 등가(양국면만, by_phase 근사)**: leader_market +1.26%(n=17) + uptrend_broadening +0.34%(n=58) ⇒ **gross ≈ +0.55%/건, net(−0.23%) ≈ +0.32%/건** — 양수지만 기록된 +2.60%/PF 2.06 대비 대폭 약화. 최근 30일 페이퍼 실적도 2건 평균 −7.57%로 정합.
- **결론 유지·강화**: 신규 정책(E5 발송 억제 등) 활성 보류. 게이트는 방향성만 유효(baseline −1.57% vs 양국면 +0.55%). 엣지 감쇠(decay) 또는 표본 구성 변화가 진행 중 — P2(무효화 shadow)와 표본 축적이 다음 판정 재료.

### P3 첫 슬라이스 — 마감 주도주 (2026-08-26 구현)

- `GET /api/kr/claw/close-leaders` (`@pro_required`, max-age=60, `?day=YYYYMMDD`) — 마감 기준(세션 마지막 정상 스냅샷) 주도주 전체 + 종목별 당일 전이 타임라인 + close 브리핑 발송 여부. 본체 `marketflow_claw/overview.py::build_close_leaders` (claw.db 읽기전용).
- FE: AiBain 대시보드에 `CloseLeadersCard` (ClawLiveCard 아래, claw 테마 정합 — 등급 칩·KRX 의미색·이벤트 칩 타임라인). 폴링 없음(마감 데이터, 10분 재검).
- 테스트: 백엔드 3(TDD — 오류 스냅샷 무시·정렬·타임라인 부착) + FE 가드 3 + 기존 회귀 green.

### 최종 검증 (2026-08-26 밤 — 전 게이트 통과)

- **G5-①② 통과**: 23:30:13 night 사이클이 `refresh_intelligence` 실행 → **6/20 정체 top3_metrics·interaction_map 이 23:30:14 운영에서 자동 재빌드**. P1의 목적("측정이 스스로 신선하게")이 운영 실증됨.
- **P3 마감 주도주 배포·검증 완료** (`6df05b7`): 재부팅으로 라우트 활성 → 무인증 401 정상, 로컬 토큰 실조회 = day 20260826 · 26종목 · 전이 88건 · close_brief delivered. FE는 CF Pages 배포(번들 suffix 6df05b7) — AiBain 대시보드에 카드 라이브.
- **텔레그램 전 구간 검증**: 검출 2종목(047040·317400) 검증형 발송 delivered(message_id 20916) + Claw 마감 브리핑 delivered. 당일 Claw 실적: 583틱·88이벤트·55/55 발송.

### P2 — 드리프트 통합으로 완료 (2026-08-27 `61b3bf2`)

드리프트 검토 결과, 코덱스 세션이 **P2 본체(관측 원장)를 이미 구현**해 두었음이 확인되어(관측 하네스 스펙 v3.1 + `marketflow_claw/observation.py` 1,017줄 + 테스트 11종), 신규 구현 대신 **검토·병합·배포**로 완료:

- **관측 원장**: 별도 SQLite(regime_contexts·signal_instances·state_events·signal_outcomes), record_tick fail-open, 성숙 horizon 멱등 갱신, `GET /api/kr/claw/{scorecards,quality}`. v3 스펙의 episode/RegimeContext/shadow 설계를 상회(시그널 인스턴스 단위·이중축 레짐·세로형 outcome).
- **alpha_core**: GET 전용 관측·페이퍼 운영면 5 라우트 + no-execution boundary 테스트 — E-게이트 폐쇄를 코드로 고정.
- **KIS 무결성 재작업**: 점수 조작 입력 차단, data_quality 게이트, 토큰/쿼터 filelock. 응답 additive.
- **detection_lab**: 운영 게이트 정합(`live_phase_gate_blocked` — 남은 것 #1 해소) + 재현성 manifest(git rev·입력 SHA-256 — R0b 게이트).
- **FE**: 모바일 스크롤/safe-area 개편 + AlphaCoreOpsCard·ClawObservationCard (CloseLeadersCard 와 공존). 검증: BE 전 배치 + FE 141/141 + 342 라우트 부팅.
- **보류(스태시 유지)**: 워치독 6종·autostart vbs·브랜드 리네임 — 태스크 계약 변경이라 별도 검증 릴리스 필요.

### 잔여 4항목 완결 (2026-08-27 심야)

**① 워치독·autostart·브랜드 — 릴리스·검증 완료.** (정정: "보류" 기록은 부정확 — 3-way apply 가 인덱스에 스테이징한 것을 `git checkout --`(인덱스 복원)로 되돌리지 못해 61b3bf2 에 이미 포함·배포됐음. 사후 전수 검증으로 릴리스 확정.) 실측: Claw pidfile=heartbeat.pid=7260 일치 + 태스크 커맨드 `--send` 반영 / Flask 는 "health-only restart contract" 로 부모·자식(리로더) 쌍 무해 확인, 부팅 후 4+사이클 재시작 0회 / **워치독이 레거시 5001 프로듀서 다운을 3-프로브로 감지해 자동 복구 성공**(23:55:46, 로그 증빙) / 기동 유예(startup grace) 동작 / 터널 SYSTEM 서비스 정상 / 브랜드 라이브(title "MarketFlow Claw", manifest #ff5a3c — PWA 재설치 프롬프트 발생 가능). 계약 테스트 3종(15케이스) green·커밋.

**③ shadow 성적 평가 — 파이프라인 실가동 검증, 정책은 표본 게이트 미달로 보류 유지.** updater 멱등 실행(data_as_of 8/26) → H1 55건 완료·coverage 100%·avg +0.28%·양성 52.7%, H5 미성숙(정직한 insufficient). R0c 기준 대조: 완료 30건 ✓·coverage 95% ✓·**고유 세션 3/20 ✗**(8/24~26). 17:15 자동 갱신 잡(`CLAW_OUTCOME_ENABLED` 기본 true) 가동 — 약 3.5주 후 세션 게이트 도달.

**④ 리포트 3자 대사 — 감쇠 원인 확정.** 공통 표본 366건 수익률 드리프트 0(데이터 무결). 8/17 리포트는 국면 None(게이트 무동작)이었고, 8/26 양국면 표본 분해: **8월 이전 기존 43건 = 승률 65.1%·+2.89%/건·PF 2.25 → 기록된 +2.60%/PF 2.06 재현 성공(historical claim verified)**; **8월 신규 32건 = 승률 28.1%·−2.61%·PF 0.46(8/7~13 손절 집중)**. 판정: 데이터·분류 문제가 아닌 **순수 out-of-sample 엣지 감쇠** — R3 보류가 옳았음이 수치 확정, 방어선은 ③ 의 shadow 무효화.

**② 고정 IP 복원 — 본PC 측 사용자 1클릭 대기.** 본PC 관리자 승격이 자동화 정책상 차단되어 사용자 실행 필요: 관리자 PowerShell 에서 `New-NetIPAddress -InterfaceAlias '이더넷' -IPAddress 192.168.55.102 -PrefixLength 24`. **순서 강제: 본PC 먼저** (miniPC 에 55.103 을 먼저 넣으면 APIPA 제거로 SSH 경로 상실 위험). 본PC 완료 확인 후 miniPC 55.103 추가는 SSH 로 수행 가능.

### 남은 것
1. ② 본PC 고정 IP(사용자 실행) → miniPC 55.103 추가·검증
2. 관측 원장 세션 게이트(20세션) 도달 시 shadow invalidator 성적 재판정 → R3 재개
3. 8월 구간 엣지 붕괴의 시장 특성 분석(양국면 내 급락 전환 감지 후보) — 가설 원장 등록 대상

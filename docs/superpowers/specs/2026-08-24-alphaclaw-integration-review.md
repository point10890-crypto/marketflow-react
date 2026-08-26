# AlphaClaw Blueprint v1.0 검토 + MarketFlow 통합 설계

작성일: 2026-08-24 (KST)
성격: 외부 설계서 "AlphaClaw — 자율 투자 운영체제 Blueprint v1.0" 검토 및 기존 시스템 통합안
선행 문서: `2026-08-24-analysis-core-redesign.md` (v3, 교차검증판 — 이하 "v3"), `2026-08-21-marketflow-claw-intraday-automation-design.md`
전제: 본 문서는 시스템 아키텍처이며 투자 권유·자문이 아니다. 수익은 보장되지 않는다. 법률·세무 판단은 전문가 확인 필요.

---

## 0. 검토 결론 (한 페이지)

AlphaClaw는 지금까지 검토한 3개 외부 설계서 중 **가장 완성도가 높다**. 특히 v3까지의 설계가 놓친 것을 정확히 4개 짚었다: **비용 후 기대값 · 가설 원장 · 리스크 거부권의 독립성 · verify 단계(numbers_used)**. 이 4개는 채택한다.

그러나 전체 청사진의 **약 60%는 MarketFlow에 이미 구현**되어 있고(§2 매핑표), 스택 제안(Postgres/Redis/TS Gateway/Docker/k8s)과 실행(주문) 경로는 **현행 운영 현실·하드 불변조건과 충돌**하여 기각 또는 명시적 결정 게이트로 보낸다.

가장 중요한 실증 발견:
> **비용 모델은 저장소에 이미 존재하지만(왕복 0.23%, `goodrich_ledger.py:49` — 거래세+양방향 수수료) Goodrich 레인에만 적용 중이다.** 주력 검출 성과(detection_lab의 국면 게이트 +2.60%/건, paper 엔진 30일 원장)는 전부 **비용 미차감(gross)** 수치다. 0.23%를 차감해도 산술적으로 양수이지만 슬리피지는 어디에도 모델링돼 있지 않다. → 채택 A1이 최우선이며, v3의 R0(근거 재현성 복구)에 "비용 차감 재계산"을 병합한다.

실행(주문)에 대한 입장: **현행 저장소의 "매매 실행 경로 코드 부재" 불변조건을 유지한다.** KIS MCP도 조회 전용이고, 테스트가 이를 고정한다. AlphaClaw Phase 5(소액 실전)는 사용자의 명시적 결정 없이는 설계·코드 착수 자체를 하지 않는 **E-게이트**로 정의한다(§4). 결정하더라도 AlphaClaw 자신의 §13 논리("두 세계를 한 프로세스에 넣으면 프롬프트 인젝션이 주문이 된다")에 따라 **이 저장소 밖의 격리 프로세스**여야 한다.

---

## 1. 세 설계서의 위치 (계보 정리)

| 문서 | 초점 | 처리 |
|---|---|---|
| 외부 제안서 v1.0 (OpenClaw형) | 게이트웨이·스킬 골격 | v3에서 철학 채택·아키텍처 기각 완료 |
| Codex v2 리뷰 | v1 재설계안의 결함 7건 | v3에서 6건 실증 채택 완료 (재현성·시점 안전·shadow) |
| **AlphaClaw v1.0 (본 검토)** | 투자 OS 전체(수집→학습→분석→토론→리스크→실행→회고) + 수익화 | **분석·검증 규율 채택, 실행·스택·수익화 확장 기각/보류** |

v3의 골격(R0 재현성 → 관측 원장 → shadow 검증 → 정책 → 표면)은 **유지**하고, AlphaClaw 채택분을 그 위에 삽입한다.

---

## 2. AlphaClaw ↔ MarketFlow 매핑 — "이미 있는 60%"

| AlphaClaw 구성요소 | MarketFlow 현물 | 격차 |
|---|---|---|
| Gateway·Cron·Heartbeat | `scheduler.py` + Task Scheduler(SYSTEM·AtStartup) + watchdog 3종 + Claw `gateway.py`(PID·heartbeat 180s) | 없음 |
| Collector 군(시세·공시·뉴스·매크로) | KIS 스크리너·DART collector·뉴스 수집기·market_gate·sector_rs·credit_balance·KIND blacklist | 소셜(X·종토방)만 부재 — **의도적 보류** (§3-C7) |
| 품질 게이트(신선도·이상치) | `SOURCE_FILE_POLICIES`·Claw stale/HALT·partial 스냅샷 DROP 금지 | known_ts 형식화만 부분 (§3-B4) |
| PIT 피처·누수 방지 | `intelligence/dataset.py`(L0, lookahead_safe 필드)·`hypothesis_replay`(lookahead-safe 리플레이) | CI 강제 없음 — 리플레이 게이트가 대체 중 |
| Analyst Council·불/베어 토론 | `tradingagents/`: analysts 4종 → `research_debate.py`(bull/bear) → `trader_risk.py`, 결정론 폴백 | **거부권 독립성 부재** (§3-B3) |
| 레짐(규칙 우선 + LLM 설명) | 4국면 타임라인 + market_gate + v3 RegimeContext | v3에서 해소 |
| 메타러너·학습 게이트·n-1 롤백 | 5중 브레이크 체인: edge_map → hypothesis_replay(IC 게이트) → agent_actions(바운드·**자동 rollback**) → learning_policy(표본·연속악화 가드) → 킬스위치 | AlphaClaw의 학습 게이트 5항목과 사실상 동형. 없음 |
| 워킹포워드 | detection_lab A/B 리플레이 + backtest_alpha_signals | 폴드 분할·홀드아웃 형식화 부재 (§3-B4) |
| 페이퍼 루프 | `paper_positions`(다음날 시가 진입·+8/-7/8일·30일 원장·국면 게이트 LIVE) + 타임라인 브리핑 4회/일 | **비용 미차감** (§3-B1), 트래킹에러 지표 부재 (§3-B6) |
| 저널·회고 | `agent_journal.jsonl`·outcome 원장·tradingagents `learning.py`(lessons) | 가설 원장 부재 (§3-B2) |
| 채널(Telegram)·승인 | 개인/채널 봇 분리·verified_delivery(run_id+digest 확인 게이트) | 없음 |
| 콘솔 | AiBain 대시보드·admin 콘솔·Claw overview | v3 G6에서 증분 |
| 킬스위치 | env 킬스위치 10+종 (`MIROFISH_*_DISABLED`, `CLAW_*`) | **레벨 체계(L1~L5) 미정리** (§3-B5) |
| MCP | mirofish MCP 19 읽기전용 + KIS MCP(조회 전용, 주문 도구 없음) | 없음 — AlphaClaw ACL 원칙("없는 도구는 호출 불가")과 이미 동형 |
| SOUL/헌법 | `llm_system_prompt.py`·"LLM은 숫자를 소유하지 않는다" 규칙 산재 | 단일 헌법 문서 부재 (§3-B5) |

---

## 3. 채택 / 기각 판정

### 3-B. 채택 (v3 로드맵에 삽입)

**B1. 비용 후 기대값 (최우선, R0에 병합)**
- 현황: `goodrich_ledger.DEFAULT_ROUND_TRIP_COST_PCT = 0.23`(%)이 존재하나 Goodrich 레인 전용. detection_lab·paper_positions·outcome_tracker는 gross.
- 반영: ① 상수를 공용 모듈로 승격(`app/services/mirofish/costs.py`, 왕복 0.23% + 슬리피지 파라미터 기본 0 → 추정치 확보 시 갱신). ② detection_lab 리포트·paper `performance_summary`·episode_outcomes에 `net_*` 필드 병기(gross 유지, 대체 아님). ③ **R0 재현 실행 시 gross/net 동시 산출** — 국면 게이트의 근거가 비용 후에도 성립하는지가 R0의 판정 기준에 추가된다.
- 슬리피지: 실체결이 없으므로 v1은 스프레드 프록시(체결가 대비 보수적 가산) 상수로 시작, 실측 불가 항목임을 `data_gaps`에 명시. AlphaClaw의 "내부 호가 재생" 시뮬레이터는 보류(§3-C2).

**B2. 가설 원장 (Hypothesis Registry)**
- 현황: `hypothesis_replay`는 태그 델타 검증기일 뿐, 가설의 등록·생애주기(research→paper→live→retired)·무효화 조건을 담는 원장이 없다.
- 반영: `data/admin_mirofish/hypotheses.json` (`mirofish.hypothesis.v1`): `{id: "H-YYYYMMDD-slug", title, rationale, universe, invalidation(필수), status, registered_at, metrics{gross, net}, linked: {detection_lab_reports[], replay_ids[]}}`.
- v3와 결합: `profitability_goal.v2`와 episode 원장에 `hypothesis_id` 참조 필드 추가. **무효화 조건 없는 가설은 등록 거부** — AlphaClaw 원칙을 스키마 검증으로 강제. 국면 게이트 자체를 첫 가설(H-2026-08-16-phase-gate)로 소급 등록해 R0 재현 결과를 metrics에 기입한다.

**B3. 리스크 판정의 독립성**
- 현황: `trader_risk.py`가 검토 역할을 하지만 분석 에이전트와 같은 LLM 클라이언트·폴백 체인을 공유 — AlphaClaw의 경고("같은 모델·프롬프트로 둘 다 돌리면 거부권이 붕괴")가 정확히 적용된다.
- 반영: trader_risk 전용 설정 분리 — ① 모델: 분석 체인과 다른 provider 우선순위(env `MIROFISH_TA_RISK_MODEL`), ② 프롬프트: 반박·거절 중심으로 분리, 실패 시 **결정론 규칙만으로 판정**(이미 있는 폴백을 리스크 쪽 기본으로 승격), ③ 산출: `approve|reject|shrink`만 허용하고 상향 조정 언어 금지. 거부는 최종 — 재호출 재설득 금지(AlphaClaw SOUL §3)를 코드로: 동일 target에 대한 리스크 재평가는 새 증거 필드 없이는 거부 결과 캐시 반환.

**B4. verify 단계 + numbers_used 형식화**
- 현황: "LLM은 숫자를 소유하지 않는다" 규칙이 Claw analyst·tradingagents에 개별 구현("packet 밖 숫자 나오면 폐기").
- 반영: LLM 산출 스키마에 `numbers_used: [{name, value, src}]` 필수화 — 본문에 등장하는 수치가 numbers_used에 없으면 산출 폐기 후 결정론 템플릿 사용. 기존 폐기 규칙의 형식화이므로 회귀 리스크 낮음. 워킹포워드 형식화: detection_lab 재현 시 기간 폴드(예: 검출 이력 전반부/후반부 분리)와 홀드아웃 구간을 리포트에 명시하는 것부터 시작 — 통계 검정 확장(Deflated Sharpe 등)은 표본이 커진 뒤.
- 생존편향 점검 항목 신설: `daily_prices.csv`·유니버스 재구축(2026-08-13, 상폐 108행 제거)이 **백테스트 시점 유니버스**를 왜곡하지 않는지 R0에서 1회 점검(검출 이력의 종목이 현재 CSV에 없으면 그 outcome이 조용히 탈락하는지 확인).

**B5. 헌법(SOUL) + 킬스위치 레벨 체계 문서화**
- 반영: `docs/SOUL.md` 신설 — AlphaClaw §21 초안을 MarketFlow 실정으로 수정(주문 관련 조항은 "실행 경로는 존재하지 않는다"로 대체). 기존 env 킬스위치 10+종을 L1(신선도/HALT) ~ L4(전면 정지) 레벨표로 정리해 SOUL에 부록화. **코드 변경 없음, 문서·운영 정리 작업.** LLM 시스템 프롬프트가 SOUL을 참조하도록 후속 정렬.

**B6. 페이퍼 트래킹에러 지표**
- 반영: paper 엔진 가정(다음날 시가 진입·목표/손절 체결) 대비 실제 daily_prices 재현치의 괴리를 월간 산출 — 모델 가정이 낙관적인지 측정. `quality/kpi`(v3 G6)에 편입.

### 3-C. 기각 / 보류 (사유)

| # | 항목 | 판정 | 사유 |
|---|---|---|---|
| C1 | Postgres+Timescale·Redis Streams·TS Gateway·Docker Compose·OTel·pgvector·k8s | **기각(v1)** | 운영 기반은 miniPC 단일 호스트 + Flask + SQLite/JSON + Task Scheduler. 현 규모에서 스택 교체는 리스크만 추가. 원장 성격 데이터(JSON+atomic write+schema_version)가 이미 append 지향. 규모가 요구할 때 재검토 |
| C2 | 내부 호가 재생 시뮬레이터·VWAP 분할 실행 | **보류** | 실행 경로가 없으므로 대상 부재. B1의 슬리피지 상수가 현 단계 대체물 |
| C3 | 주문·브로커 어댑터·멀티시그·orders/positions 테이블 (Phase 5) | **E-게이트** (§4) | 하드 불변조건 충돌. 사용자 명시 결정 전 착수 금지 |
| C4 | 수익화 §10-B (스크리너 SaaS·교육·자문) | **보류** | MarketFlow는 이미 구독 서비스 운영 중(정보 제공 + 면책, verdict에 buy/sell 부재). AlphaClaw 자신의 시퀀스("A가 12개월 살아남은 뒤 B")를 따르면 현 단계 신규 상품화 없음. 제품 문구 금지 목록(수익 보장·리딩 표현)은 기존 정책과 일치 — 유지 |
| C5 | OpenClaw 하이브리드(채널·메모리는 OpenClaw) | **기존 결정 유지(Phase 2 보류)** | Docker·모델 인증 미비로 이미 별도 스펙 보류 상태. AlphaClaw의 분리 논리는 그 스펙과 동일 방향 |
| C6 | 미국 시장(Polygon·Alpaca·IBKR) | **기각(v1)** | US 레인은 읽기전용 대시보드로 기존재. 브로커 연동은 E-게이트 이후에도 별도 결정 |
| C7 | 소셜 수집(X·종토방·Reddit) | **보류** | AlphaClaw 스스로 경고한 프롬프트 인젝션 표면 + C등급 근거. E1 규칙(B 이하 단독 통과 불가)상 기여도 낮음. 봇 필터·집계 설계가 준비되기 전 도입 금지 |
| C8 | 일 단위 신경망 재학습·딥RL·LLM 가중치 직결 | **기각** | AlphaClaw 자신도 금지(§7.3). 현행 체인과 동일 입장 — 확인만 |
| C9 | NAV·VaR·업종 한도 등 포트폴리오 규칙 | **보류** | 페이퍼 원장에 포지션 수 상한(10)만 존재. 나머지는 실행 결정(E-게이트) 이후에만 의미 |

---

## 4. E-게이트 — 실행(주문) 결정 게이트

현행 불변조건: **이 저장소에는 주문·잔고 변경 API 경로가 존재하지 않으며 테스트가 이를 고정한다.** KIS MCP도 조회 전용이다. 이 조건은 본 통합 설계에서도 유지된다.

AlphaClaw Phase 5(소액 실전)로 가려면 다음이 **순서대로 전부** 충족되어야 하며, 첫 항목은 코드가 아니라 사용자의 명시적 서면 결정이다:

1. **사용자 결정**: 실행 경로 구축 여부·계좌·자본 한도. (이 결정 전에는 설계 문서 이상을 만들지 않는다)
2. **격리 원칙**: 구축하더라도 이 저장소 밖 별도 프로세스(가칭 alpha-core)로 분리 — AlphaClaw §13("프롬프트 인젝션이 주문이 된다")과 기존 "매매·배포·재시작 금지" 운영 규칙의 공통 귀결. MarketFlow는 읽기전용 신호 공급자 역할만.
3. **선행 성과 게이트**: R0 비용 차감 재현 통과 + 페이퍼 원장 6개월(AlphaClaw §10.1 자금 곡선 0~2단계에 대응) + 트래킹에러(B6) 허용 범위.
4. 킬스위치·리스크 독립성(B3)·가설 원장(B2)이 페이퍼에서 무사고 검증 완료.

본 문서는 E-게이트를 **정의**할 뿐 개방하지 않는다.

---

## 5. 통합 로드맵 (v3 + AlphaClaw 채택분)

| 단계 | 내용 | 출처 |
|---|---|---|
| **R0′** | 근거 재현성 복구 **+ 비용 차감**: miniPC detection_lab 재실행 → gross/net(왕복 0.23%+슬리피지 상수) 동시 산출·아티팩트 보존, 생존편향 1회 점검, 국면 게이트를 가설 H-2026-08-16-phase-gate로 소급 등록 | v3 R0 + B1·B2·B4 |
| **R1** | 관측 원장: episode 테이블(17:15 잡)·RegimeContext·profitability_goal.v2(+`hypothesis_id`) | v3 R1 + B2 |
| **R2** | shadow 검증: 무효화 3종 shadow·`early_exit_saved_pct`(net 기준) 축적·1일 dry-run 육안 | v3 R2 |
| **R2.5** | 리스크 독립성·verify: trader_risk 모델/프롬프트 분리·numbers_used 스키마·거부 캐시 | B3·B4 |
| **R3** | 정책 적용: E5 발송 억제·무효화 발송 활성 (R0′ net 재현 + R2 분포 확인 후) | v3 R3 |
| **R4** | 표면: scorecards/quality-kpi API·AiBain 카드·트래킹에러 지표 | v3 R4 + B6 |
| **R5** | 문서·운영: SOUL.md + 킬스위치 레벨표 (코드 무변경, 병행 가능) | B5 |
| **(E)** | 실행 경로 — §4 게이트 충족 전 착수 금지 | C3 |

각 단계 독립 배포. miniPC 반영은 기존 배포 게이트·런북. 커밋·활성화는 사용자 승인 후.

---

## 6. 결정 필요 사항

1. **R0′ 착수 승인** — miniPC detection_lab 재실행(장 마감 후) + 비용 차감 재계산. 이것이 이후 모든 정책의 전제.
2. 슬리피지 상수 초기값 — 0(순수 거래비용만) vs 보수적 프록시(예: 편도 0.10%p 가산). 어느 쪽이든 `data_gaps`에 실측 불가 명시.
3. B3 리스크 모델 분리에 사용할 provider — 현재 계정 가용 모델 제약(OpenAI는 gpt-5.5만) 내에서 분석 체인과 다른 우선순위 지정 필요.
4. E-게이트 §4-1 (실행 경로 구축 여부) — 본 설계는 결정을 요구하지 않으며, 결정 전까지 페이퍼·신호 시스템으로 유지.
5. v3 문서의 기존 결정 사항 4건(R0 시점·R1 레인 순서·USD/KRW·scorecards 인증 티어) 병행 확인.

---

## 부록. AlphaClaw에서 채택하되 표현만 바꾼 원칙

- "리스크가 알파보다 윗길" → trader_risk 거부는 최종, 재설득 금지 (B3)
- "모든 신호는 가설이다" → 무효화 조건 없는 가설 등록 거부 (B2)
- "학습은 워킹포워드다" → 기존 hypothesis_replay·detection_lab 리플레이 규율 + 폴드 명시 (B4)
- "비용 후 기대값이 양수일 때만" → 모든 성과 지표 net 병기, R0′ 판정 기준 (B1)
- "감사 가능성" → 기존 schema_version·journal·아티팩트 보존 + 가설 원장 링크 (B2)
- "현금은 포지션이다 / 기회 없음이 기본값" → 기존 HALT·합의 실패 시 보류 원칙과 동일 — 확인만

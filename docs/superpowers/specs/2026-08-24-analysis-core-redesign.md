# 국내 주식 자율 학습·분석·종목검출 시스템 — 재설계안 v3 (교차검증판)

작성일: 2026-08-24 (KST)
버전: v3 — v1(Claude 초안) + Codex v2 리뷰 7건을 **저장소 실증 대조 후** 반영
성격: 외부 제안서("OpenClaw형 자율 시스템 설계서 v1.0") 검토 + 실제 구현 기준 재설계
선행 문서: `2026-08-21-marketflow-claw-intraday-automation-design.md`, `2026-08-22-claw-dashboard-design.md`
원칙: 실데이터만 · 조건부 추론 · 매매 실행 경로 부재 · 출처 등급과 확인 불가 명시 · **정책 적용 전 근거 재현**

---

## 0. 결론 요약

- 외부 제안서(v1.0)의 **철학(팩트 밀도·검출 정밀도 우선)은 채택, 아키텍처(신규 게이트웨이·weights.json 학습기·에이전트 재구축·네이버 스크래핑)는 기각**. 전부 저장소에 상위호환이 존재하거나 운영 규칙과 충돌한다. (§2)
- Codex v2 리뷰 7건 중 **6건 채택(사실 확인), 1건 조건부 채택**. 특히 두 가지가 v1의 결함이었다: ① v1이 근거로 삼은 국면 성과(+2.60%/PF 2.06)가 **본PC 저장 데이터로 재현 불가**, ② 신규 스코어카드 스키마 제안이 기존 `mirofish.profitability_goal.v1`과 중복. (§1)
- 이에 따라 구현 순서를 **R0 재현성 복구 → R1 관측 원장 → R2 shadow 검증 → R3 정책 적용 → R4 API/UI**로 재배열한다. 어떤 발송·억제 정책도 자기 근거가 재현되기 전에는 켜지 않는다. (§9)

---

## 1. 교차 검증 결과 (Codex v2 리뷰 7건)

> **선행 참고**: Codex가 산출했다는 v2 MD 파일(`Documents\Codex\2026-08-23\ek\outputs\...`)은 해당 경로·`docs/superpowers/specs` 어디에도 존재하지 않았다 (`Documents\Codex\`에는 07-30/08-18/08-21 폴더만 존재). 아래 검증은 사용자가 전달한 **요약 7개 항목**을 대상으로 저장소·데이터를 직접 대조한 결과다.

| # | Codex 지적 | 검증 결과 | 근거 (2026-08-24 본PC 실측) | 판정 |
|---|---|---|---|---|
| 1 | `+2.60%/PF 2.06` 국면 성과가 현재 저장 리포트에서 재현 안 됨 | **사실** | `data/admin_mirofish/detection_lab/` 디렉토리 자체가 본PC에 없음. 수치 출처는 miniPC 1회 실행(2026-08-16, `2b6bf69`)과 메모리 기록뿐, 리포트 아티팩트는 git에 없음. 본PC `daily_prices.csv`는 구본이라 재실행해도 동일 결과 보장 불가 | **채택 → G0/R0 신설**. 단, 국면 게이트 자체는 `paper_positions.PHASE_GATE_BLOCKED`로 이미 LIVE — 재현 실패 시에도 게이트를 끄는 게 아니라 근거 재산출이 우선 |
| 2 | 신규 scorecard 대신 기존 `mirofish.profitability_goal` 확장 | **사실 — v1의 결함** | `alpha_research.py:400` `mirofish.profitability_goal.v1` 실존: `goal_fit_score`, `goal_verdict`(prime/needs_confirmation/watch_only/reject), `hard_blockers`, `missing_confirmations`, `ranking_effect` — v1이 제안한 스코어카드와 개념 중복 | **채택**. `mirofish.scorecard.v1` 신설 철회 → `profitability_goal.v2`로 확장 (§6.1) |
| 3 | 4국면 단일 정본 대신 시점 안전한 `RegimeContext` | **타당** | `intelligence/regime.py` 타임라인은 EOD `daily_prices.csv` 재빌드형 — 당일 라벨은 장중에 존재하지 않고, 데이터 백필 시 과거 라벨이 드리프트할 수 있음. v1의 "정본 승격"은 장중 소비자(Claw)에 시점 문제를 만든다 | **채택**. 결정 시점 스냅샷 `RegimeContext`로 대체 (§6.2) |
| 4 | Claw 후보 episode·발생 당시 가격·outcome 원장 | **타당·실현 가능** | Claw 스냅샷 행에 `price` 이미 수집 중(`collectors.py:28`) — 이벤트 시점 기준가 캡처 가능. v1의 `outcomes(d1,d5)` 단일 테이블보다 episode 단위가 전이·무효화 이력을 보존 | **채택** (§6.3) |
| 5 | 무효화는 `LEADER_DROP`·만료·손절선부터 shadow 검증 | **타당** | 이 3종은 기존 Claw 데이터만으로 계산 가능. SUPPLY_REVERSAL/DART/CREDIT는 외부 조인·신선도 의존 → 후순위가 맞음 | **채택**. 무효화 8종 전면 도입(v1) 철회 → 3종 shadow 우선 (§6.4) |
| 6 | 16:30 Scheduler 충돌 | **사실** | `scheduler.py`: `WAVE_SCAN_TIME=16:30` + `MIROFISH_AGENT_EVENING_TIME=16:30` 기점유. v1의 R2가 16:30에 Claw outcome 잡을 제안했었음. Claw는 별도 프로세스지만 miniPC에서 API·CPU 경합 | **채택**. Claw outcome 채움은 **17:15**로 이동 (16:00 VCP / 16:05 브리핑 / 16:30 Wave·agent 회피) |
| 7 | stale Top3 KPI | **사실** | 본PC `intelligence/top3_metrics.json` mtime 2026-06-20, `interaction_map.json` 06-15. miniPC도 "런 부족(insufficient)" 기록. v1이 이를 "후보 정밀도 KPI"로 그대로 노출하려 했음 | **채택**. KPI는 `freshness`/`insufficient` 필드 동반 필수, 표본 미달 시 수치 대신 상태 표기 (§8) |

Codex 요약의 "구현 순서 변경" 제안은 위 1·5·7의 귀결로서 **채택** — §9에 반영.

---

## 2. 외부 제안서(v1.0) 검토 — 채택/기각 (v1에서 유지)

### 채택
1. 우선순위 전도: 팩트 밀도 > 검출 정밀도 > 의사결정 연결 > 자동화.
2. 후보 출력에 무효화 조건·데이터 공백·신뢰 상한을 1급 필드로.
3. 근거 등급 명문화: S(KRX·DART) / A(KIS 시세·수급, daily_prices) / B(LLM 뉴스 해석·컨센서스) / C(미검증). **B 단독으로 후보 확정 금지.**
4. 품질 KPI(근거 완비율·공백 명시율·과신 사고 0). 실계좌 수익률은 시스템 KPI로 걸지 않음.
5. 매매 실행 경로 부재 원칙 (이미 코드·테스트로 고정, 유지).

### 기각 (사유)
| 기각 항목 | 사유 |
|---|---|
| FastAPI 게이트웨이 신설(:18790) | Flask 단일 백엔드 규칙. 표면·프로세스·워치독 증가는 miniPC 무인 운영 리스크. `/api/kr/claw/overview`, `/api/admin/mirofish/*` 기존재 |
| `weights.json` + 학습률 α 학습기 | 현행 5중 브레이크 체인(edge_map → hypothesis_replay 게이트 → agent_actions 바운드·rollback → learning_policy 가드 → 킬스위치) 대비 명백한 퇴행 |
| `agents/*.yaml` 4역할 재구축 | `tradingagents/` 계층(analysts→debate→trader_risk, 결정론 폴백)이 동일 목적 수행 중 |
| 네이버 HTML 스크래핑 | KIS 인증 소스 보유. 파서 취약성 자초 금지 |
| 일 3~7개 후보 수 하드캡 | 다층 게이트(CIO BUY만·phase gate·TA SELL 제외·TOP3)가 이미 수행. confidence_cap 미달 시 watch 강등이 정보 손실 없이 동일 효과 |
| `POST /v1/learn/tick` 외부 노출 | 학습 트리거는 스케줄러·agent cycle 내부 전용. mutation 엔드포인트 금지 |

---

## 3. 재설계 원칙

1. **신규 시스템 0, 기존 시스템 보강만.** 새 프로세스·포트·저장소 계층 금지.
2. **근거 재현이 정책에 선행한다.** 어떤 억제·발송·게이트 정책도 그 근거 수치가 현재 데이터로 재산출되기 전에는 신설하지 않는다 (기존 LIVE 게이트는 유지하되 근거 재산출을 병행). — Codex #1의 일반화.
3. **검증이 검출을 이긴다.** 검출 로직 변경은 `detection_lab` 리플레이 또는 `hypothesis_replay` 게이트 통과 필수.
4. **시점 안전 기록.** 결정에 쓰인 레짐·근거는 결정 시점에 본 그대로 불변 저장한다. 사후 재빌드 산출물로 과거 결정을 소급 설명하지 않는다. — Codex #3의 일반화.
5. **LLM은 숫자를 소유하지 않는다.** 모든 수치는 결정론 계층에서. LLM은 서술만, confidence_cap은 하향 제안만 가능.
6. **읽기전용 우선.** 신규 엔드포인트는 전부 GET, 기존 데코레이터 재사용.

---

## 4. 목표 아키텍처 — 5계층 매핑

```
[팩트 계층]   KIS(시세·수급·순위) · DART · daily_prices.csv · market_gate
              · sector_rs · credit_balance · KIND blacklist
                └ 신선도 정책: SOURCE_FILE_POLICIES / Claw stale 규칙 (기존)

[분석 계층]   intelligence/ L0 dataset · L1 regime(breadth) · L2 interactions
              · edge_map · 4국면 타임라인(detection_lab)
                └ G4: RegimeContext — 결정 시점 다중 소스 스냅샷 (§6.2)

[검출 계층]   alpha_scanner(일간, TOP3=CIO BUY) · marketflow_claw(장중 이벤트)
                └ G1: profitability_goal.v2 확장 (§6.1)
                └ G2: 무효화 shadow 감시 3종 (§6.4)

[검증 계층]   outcome_tracker(5/10/20d) · paper_positions(국면 게이트 LIVE)
              · detection_lab(A/B 리플레이) · top3_metrics · tradingagents/learning
                └ G0: 근거 재현성 복구 (§5)
                └ G3: Claw episode 원장 (§6.3)

[전달 계층]   Claw reporter/delivery · Flask API · AiBain 대시보드
                └ G6: freshness 동반 KPI·스코어카드 노출 (§8)
```

학습 되먹임 경로는 기존 5중 브레이크 체인이 유일하며, 킬스위치(`MIROFISH_LEARNING_DISABLED`, `MIROFISH_AGENT_DRY_RUN`, `MIROFISH_PAPER_PHASE_GATE`, `CLAW_*`) 전부 유지.

---

## 5. 공백 재정의 (G0~G6)

- **G0 (신설, 최우선) 근거 재현성 복구**: 국면 게이트의 근거 수치(+2.60%/PF 2.06)를 miniPC 최신 데이터로 재실행(`scripts/detection_lab_run.py`)해 리포트 아티팩트를 산출·보존(git 또는 지정 아카이브)하고, 본 문서에 리포트 파일명·생성일·핵심 수치를 갱신 기입한다. 재현 실패 시: 게이트는 유지하되 "근거 재검증 중" 상태를 대시보드에 표기하고, 차이 원인(표본 확대·데이터 수정·버그)을 규명하기 전 신규 정책(E5 발송 억제 등)을 켜지 않는다.
- **G1 스코어카드**: `profitability_goal.v1` → **v2 확장** (신규 스키마 아님). 추가 필드: `evidence[](grade 포함)`, `invalidators[]`, `data_gaps[]`(기존 `missing_confirmations` 승계·개명), `confidence_cap`, `cap_reasons[]`, `expiry`. Claw 레인도 동일 스키마로 발행.
- **G2 무효화 shadow 감시**: `LEADER_DROP`(3틱 확정, 기존)·`EXPIRY`·`STOP_LEVEL(-7%)` 3종만 우선. DB 기록만 하고 발송하지 않는 shadow 모드로 시작 (§6.4).
- **G3 Claw episode 원장**: 이벤트 시점 기준가 포함 episode 단위 관측·성과 기록 (§6.3). 채움 잡은 **17:15** (16:30 회피).
- **G4 RegimeContext**: 단일 정본 승격안 철회. 결정 시점의 다중 소스 스냅샷 (§6.2).
- **G5 근거 등급·공백 명시**: `evidence[].grade` + `data_gaps[]` 필드화. 통과 규칙 §7.
- **G6 전달 증분**: `GET /api/kr/claw/scorecards`(`@pro_required`), `GET /api/admin/mirofish/quality/kpi`(`@admin_or_aibain_required`), AiBain detections 섹션 병기. 신규 서버·mutation 없음.

---

## 6. 분석 코어 명세

### 6.1 `mirofish.profitability_goal.v2` (v1 확장, 하위호환)

기존 v1 필드(`goal_fit_score`, `goal_verdict`, `hard_blockers`, `missing_confirmations`, `ranking_effect`)는 전부 유지. 추가:

```json
{
  "schema_version": "mirofish.profitability_goal.v2",
  "lane": "scanner|claw",
  "evidence": [
    {"k": "trading_value_eok", "v": 5200, "src": "KIS", "grade": "A", "ts": "..."},
    {"k": "dart_disclosure", "v": "자사주 취득", "src": "DART", "grade": "S", "ts": "..."}
  ],
  "invalidators": [
    {"type": "LEADER_DROP", "cond": "S/A 이탈 3틱 연속", "mode": "shadow"},
    {"type": "STOP_LEVEL", "cond": "episode 기준가 대비 -7%", "mode": "shadow"},
    {"type": "EXPIRY", "cond": "만료일 경과", "mode": "shadow"}
  ],
  "data_gaps": ["investor_flow"],
  "confidence_cap": 0.60,
  "cap_reasons": ["edge bucket insufficient (n=3)", "regime sources conflict"],
  "expiry": "2026-08-26",
  "regime_context_ref": "rc_20260824_1410_005930"
}
```

- `goal_verdict`에 buy/sell 부재 (v1과 동일) — 외부 제안서의 "action에 매수/매도 금지" 규칙과 정합.
- `confidence_cap` 산출(결정론): 기본 0.75 — S/A 근거 2개 미만 −0.15 / data_gap 항목당 −0.10 / RegimeContext `conflicts` 존재 −0.10 / edge 버킷 insufficient −0.10 / 음(-)국면 0.40 상한(G0 재현 후 활성). LLM은 상향 불가.
- `expiry` 경과 시 자동 watch 해제 (좀비 후보 방지).

### 6.2 `RegimeContext` (시점 안전 레짐 기록)

```json
{
  "schema_version": "mirofish.regime_context.v1",
  "id": "rc_20260824_1410_005930",
  "captured_at": "2026-08-24T14:10:00+09:00",
  "sources": {
    "phase_timeline": {"as_of_date": "2026-08-22", "label": "leader_market",
                        "file_mtime": "...", "stale": false},
    "market_gate": {"status": "GREEN", "age_hours": 6.2, "stale": false},
    "breadth_live": {"sa_count": 11, "advance_ratio": 0.63, "src": "claw_snapshot"}
  },
  "resolved_label": "leader_market",
  "conflicts": [],
  "resolution_rule": "phase_timeline(D-1) 우선, stale 시 market_gate, 둘 다 stale 시 unknown+HALT 검토"
}
```

- 장중에는 4국면 타임라인의 당일 라벨이 없으므로 `as_of_date = 직전 거래일`을 명시 기록 — 당일치인 척하지 않는다.
- 소스 간 충돌(예: timeline 양국면 vs gate RED)은 라벨 강제 통일이 아니라 `conflicts[]` 기록 + confidence_cap 하향으로 표현.
- 후보·이벤트·episode는 `regime_context_ref`로 이 스냅샷을 참조하며, 스냅샷은 불변 — 타임라인이 재빌드되어도 과거 결정의 근거는 보존된다.
- 검증 계층(`detection_lab` 등)의 사후 분석은 종전대로 재빌드 타임라인을 쓸 수 있다(lookahead-safe 리플레이 목적) — 결정 기록과 사후 분석의 소스를 구분하는 것이 이 설계의 요점.

### 6.3 Claw episode 원장 (SQLite, `data/claw/claw.db` 확장)

```sql
CREATE TABLE IF NOT EXISTS episodes (
  id INTEGER PRIMARY KEY,
  day TEXT, code TEXT, name TEXT,
  opened_ts TEXT, opened_event_id INTEGER REFERENCES events(id),
  ref_price REAL,                    -- 발생 당시 스냅샷 price (collectors가 이미 수집)
  regime_context_json TEXT,          -- §6.2 스냅샷 (불변)
  closed_ts TEXT, close_reason TEXT, -- drop_confirmed | expiry | stop_shadow | eod
  UNIQUE(day, code)
);
CREATE TABLE IF NOT EXISTS episode_outcomes (
  episode_id INTEGER PRIMARY KEY REFERENCES episodes(id),
  d1_ret REAL, d5_ret REAL,          -- ref_price 대비, 이벤트 ts 이후 가격만 (lookahead-safe)
  invalidated_before INTEGER DEFAULT 0,
  early_exit_saved_pct REAL,         -- shadow 무효화 시점가 대비 만기 보유 수익 차
  computed_at TEXT
);
```

- 채움 잡: **17:15** (Claw 내부 스케줄 — 16:00 VCP/16:05 브리핑/16:30 Wave·agent evening 회피, Codex #6).
- 버킷 통계(이벤트 타입×resolved_label×등급)는 edge_map 패턴(n<5 = insufficient)으로 관찰 전용 산출. 스코어 반영은 `learning_policy`·`hypothesis_replay` 게이트 통과 후에만 — **신규 학습기 없음.**

### 6.4 무효화 — shadow 우선 3종 (Codex #5)

| 단계 | 타입 | 데이터 의존 | 모드 |
|---|---|---|---|
| 1차 (즉시 가능) | `LEADER_DROP`(3틱 확정) · `EXPIRY` · `STOP_LEVEL`(-7%) | Claw DB 내부만 | **shadow**: episode close_reason 기록만, 발송 없음 |
| 2차 (shadow 성적 확인 후) | 위 3종 발송 활성 (`INVALIDATED` 이벤트 → 개인봇) | 동일 | `early_exit_saved_pct` 분포가 양(+)임을 확인 후 |
| 3차 (외부 조인) | `SUPPLY_REVERSAL` · `DART_ADVERSE` · `CREDIT_WARNING` · `BLACKLIST_HIT` | KIS 수급·DART·credit_balance·blacklist 신선도 | 각각 별도 shadow → 검증 → 활성 |
| 보류 | `FX_SHOCK` | USD/KRW 수집(선택 기능) 자체가 미활성 | 수집 결정 전 도입 금지 |

신규 타입 추가·활성 전환은 전부 outcome 표본으로 유효성 입증 후에만.

---

## 7. 최소 근거 규칙 (통과/탈락)

| # | 규칙 | 미충족 시 |
|---|---|---|
| E1 | grade S 또는 A 근거 ≥ 2 (서로 다른 소스) | verdict `candidate_needs_confirmation` 이하로 강등, 발송 금지 |
| E2 | 가격·거래대금은 A 이상 소스 필수 (LLM·뉴스 대체 불가) | 후보 탈락 |
| E3 | B등급(LLM 해석·컨센서스)은 가점만, 단독 통과 불가 | 해당 근거 무시 |
| E4 | 수급 근거 없으면 수급 관련 가설·무효화 생성 금지 + data_gaps 명시 | cap −0.10 |
| E5 | 음(-)국면 신규 watch 발송 억제 | **G0 재현 완료 후 활성** (그 전에는 paper 엔진의 기존 LIVE 게이트만 유지) |
| E6 | HALT 중 신규 스코어카드 발행 금지 (기존 Claw 불변조건 확대) | 보류 보고만 |

---

## 8. 품질 KPI — freshness 동반 필수 (Codex #7)

모든 KPI 응답은 `{value, n, freshness: {generated_at, age_hours, stale}, insufficient}` 형태. 표본 미달·정체 시 수치 대신 상태를 노출한다 (본PC top3_metrics 2개월 정체, miniPC insufficient 실측이 근거).

| KPI | 정의 | 소스 |
|---|---|---|
| 근거 완비율 | watch 후보 중 E1 충족 비율 | profitability_goal.v2 |
| 공백 명시율 | data_gaps 채움/은닉 비율 (은닉 0 목표) | 동상 |
| 조기 제외 성적 | shadow/실 무효화의 `early_exit_saved_pct` 분포 | episode_outcomes |
| 후보 정밀도 | precision@1/3/5, nDCG@3, rank IC | 기존 top3_metrics — **freshness·insufficient 그대로 표기** |
| 국면 정합 | 음(-)국면 발송 건수 (E5 활성 후 0 목표) | 위반 카운터 |
| 과신 사고 | confidence_cap 초과 단정 출력 건수 (0 목표) | reporter 테스트 + 런타임 카운터 |

실계좌 수익률은 KPI로 걸지 않는다. 페이퍼 성과는 `paper_positions` 30일 원장이 담당.

---

## 9. 로드맵 (Codex 순서 채택: 재현성 → 관측 → 검증 → 정책 → 표면)

| 단계 | 내용 | 게이트 |
|---|---|---|
| **R0** | 근거 재현성 복구 — miniPC에서 `detection_lab_run.py` 재실행, 리포트 아티팩트 보존, 본 문서에 수치·파일명 기입. top3_metrics/interaction_map 재생성 시도 및 insufficient 사유 기록 | 리포트 존재 + 수치 대사(±허용오차 명시). 불일치 시 원인 규명이 후속 단계 선행 조건 |
| **R1** | 관측 원장 — episode 테이블 + 17:15 채움 잡 + RegimeContext 기록 + profitability_goal.v2 필드 병기 (동작 무변경, 기록만) | lookahead 리플레이 검증 + 단위 테스트 |
| **R2** | shadow 검증 — 무효화 3종 shadow 가동, `early_exit_saved_pct` 축적, 장중 1일 dry-run 육안 검증(기존 관례) | shadow 정밀도 리뷰 (사람) |
| **R3** | 정책 적용 — E5 발송 억제 활성, 무효화 3종 발송 활성, cap 기반 watch 강등 | R0 재현 + R2 분포 양(+) 확인 |
| **R4** | API/UI — `GET /api/kr/claw/scorecards`, `GET /api/admin/mirofish/quality/kpi`, AiBain 카드 | 기존 엔드포인트 회귀 |

각 단계 독립 배포 가능. miniPC 반영은 기존 배포 게이트·런북 절차. 커밋·활성화는 사용자 승인 후.

---

## 10. 비범위 (재확인)

- 증권사 주문·출금·키 사용 코드 경로: 계속 부재 (테스트 고정 유지)
- 신규 상주 프로세스/포트/게이트웨이: 없음
- OpenClaw 브리지: Phase 2 별도 스펙 보류 (Docker·모델 인증 선행)
- verdict/status에 buy/sell: 구조적으로 불가 유지

## 11. 결정 필요 사항

1. R0의 detection_lab 재실행을 miniPC에서 수행할 시점 (장 마감 후 권장) 및 리포트 아티팩트 보존 위치 (git 포함 여부)
2. R1 도입 레인 순서 — Claw 먼저(원장 신설이라 회귀 리스크 최소) vs 스캐너 동시
3. `FX_SHOCK`용 USD/KRW 수집 활성화 여부 (미활성 시 해당 무효화 영구 보류)
4. `GET /api/kr/claw/scorecards` 인증 티어 — `@pro_required`(overview와 정합) vs `@admin_or_aibain_required`

---

## 부록 A. v1 → v3 변경 대장

| v1 | v3 | 사유 |
|---|---|---|
| `mirofish.scorecard.v1` 신설 | `profitability_goal.v2` 확장 | 기존 스키마 중복 (Codex #2, 실증) |
| 4국면 타임라인 "정본 승격" | `RegimeContext` 시점 스냅샷 | 장중 당일 라벨 부재·재빌드 드리프트 (Codex #3) |
| `outcomes(d1,d5)` 단일 테이블, 16:30 잡 | episode 원장 + 17:15 잡 | 기준가·전이 이력 보존, 16:30 기점유 (Codex #4·#6, 실증) |
| 무효화 8종 일괄 도입 | 3종 shadow → 단계 활성 | 외부 조인 의존·검증 미비 (Codex #5) |
| top3_metrics 즉시 KPI 노출 | freshness/insufficient 동반 필수 | 2개월 정체 실측 (Codex #7) |
| R1 스코어카드부터 | R0 재현성 복구부터 | +2.60%/PF 2.06 본PC 재현 불가 (Codex #1, 실증) |

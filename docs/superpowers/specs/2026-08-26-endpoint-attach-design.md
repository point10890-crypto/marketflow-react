# 운영 엔드포인트 실사 + 마스터 플랜 부착 설계

작성일: 2026-08-26 (KST)
성격: miniPC 운영 표면 실측(SSH + 프로덕션 스폿체크) → 마스터 플랜 P1~P4를 어느 지점에 어떻게 붙일지 확정
선행: `2026-08-24-goal-definition-master-plan.md` (성공 기준=검출 정밀도)

---

## 1. 운영 표면 실사 (2026-08-26 실측)

### 1.1 프로세스·포트·터널 (miniPC MINIPC-NQYLP)

| 포트 | 바인드 | 프로세스 | 역할 |
|---|---|---|---|
| **5003** | 127.0.0.1 | python (PID 17332) | **운영 Flask** — cloudflared `marketflow-api.bit-man.net → localhost:5003` 의 유일 타깃 |
| 5001 | 0.0.0.0 | python (PID 31980) | **정체 미확인 Flask 추정** — flask_app.py 기본 포트. 터널에 연결 안 됨. ⚠ 중복/레거시 가능성, 후속 확인 항목 (§5) |
| 8765 | 127.0.0.1 | python (PID 24256) | mirofish MCP (읽기전용 19도구) |
| 8080 | — | (별도 프로젝트) | `api.bit-man.net → localhost:8080` = **JUST BUY. 절대 불가침** |

- 터널: http2, `MarketFlow-Tunnel-Watchdog` 5분 감시. healthz 200 (0.26s) 확인.
- Task Scheduler 등록 22개: Flask/Scheduler/Claw/MCP/Cloudflared + 각 Watchdog, Goodrich-30Min, Jongga-Telegram-1510, Jongga-V2-SafetyNet, Wave-Screener, Durable-Backup, FlaskOneShot.

### 1.2 Flask URL 맵 (334 rules — 운영 코드는 origin/main과 동일함을 확인)

| prefix | 수 | 플랜 관련성 |
|---|---|---|
| `/api/admin/mirofish` | **108** | 핵심 부착면 — agent/paper/outcomes/learning/scanner/workflows/runs/tradingagents |
| `/api/kr` | 36 | `claw/overview` 포함 — 본인용 장중 표면 |
| `/api/us` 41 · `/api/crypto` 29 · `/api/community` 19 · `/api/admin/users` 15 · `/api/econ` 12 · `/api/manual-stock-analysis` 11 · `/api/wave` 10 · 기타 | — | 플랜 무관 (무변경 보장 대상) |

미푸시 6커밋(`79cd83d..c431e66`)의 `app/`·`flask_app.py`·`scheduler.py`·`marketflow_claw/` diff = **0** → 운영 백엔드는 origin/main과 동일. 본PC P1 커밋과 충돌 없음.

### 1.3 실소비자 매핑 (프론트 grep + 프로덕션 401 게이트 확인)

| 엔드포인트 | 인증(실측) | 소비자 |
|---|---|---|
| `GET /api/admin/mirofish/aibain/overview` | 401 게이트 정상 (`@admin_or_aibain_required`) | **구독자 대시보드** `AiBainDashboard.tsx` (검출/성과/학습 3카드) |
| `GET /api/kr/claw/overview` | 401 (`@pro_required`) | ClawLiveCard + `/dashboard/kr/claw` (2곳) |
| `GET /api/admin/mirofish/paper/overview` | 401 | admin 엔드포인트 콘솔 |
| `GET /api/admin/mirofish/learning/readiness` | 401 | admin 콘솔 (2곳) |
| runs/scanner/workflows/chat/graphrag/deepseek 계열 | 401 | admin 콘솔 (다수) |
| `agent/status`, `agent/journal` | — | FE 미소비 (MCP/운영자 전용) |
| 텔레그램 | — | scheduler 잡 + Claw delivery (엔드포인트 아님, 별도 발송 경로) |

---

## 2. 플랜 부착 설계 — 원칙: 기존 표면에 additive, 신규는 GET 2개뿐

### 2.1 P1 (구현 완료분) — 엔드포인트 신설 0, 기존 응답에 필드만 추가

| 부착점 | 변화 | 소비자 영향 |
|---|---|---|
| scheduler 잡 `alpha_brain_agent_evening(16:30)`/`night(23:30)` | `run_maintenance`가 top3 stale 시 `refresh_intelligence` 자동 발행 → **miniPC 6/20 정체 아티팩트 자동 복구** | 없음 (백그라운드) |
| `GET .../paper/overview` 응답 `performance` | `round_trip_cost_pct`/`net_avg_return_pct`/`net_cumulative_return_pct` 병기 | additive — FE는 기존 필드만 읽어 무영향 |
| `GET .../agent/status`, `.../learning/readiness` 의 top3 요약 | `generated_at`/`stale` 병기 | additive |
| `scripts/detection_lab_run.py` | net 컬럼 — 수동 CLI만 | 없음 |

### 2.2 P2 (관측 원장) — 엔드포인트 신설 0

- Claw SQLite(`data/claw/claw.db`)에 episodes/episode_outcomes 테이블 — **MarketFlow-Claw 프로세스 내부**에만 부착. 17:15 채움 잡은 Claw 자체 스케줄 표에 추가 (scheduler.py 무변경). 활성화는 `scripts/restart_claw.ps1`(miniPC 기존재, f23c805).
- scorecard(profitability_goal.v2)·RegimeContext 필드는 scanner/claw 산출물 JSON에만 — API 응답으로는 P3에서 노출.

### 2.3 P3 (전달) — 신규 GET 2개 + 기존 1개 확장

| 항목 | 부착 위치 | 인증 | 소비자 |
|---|---|---|---|
| `GET /api/kr/claw/scorecards` 신설 | `app/routes/kr_claw.py` (기존 Blueprint, no-cache 패턴 동일) | `@pro_required` (overview와 정합 — 마스터 플랜 결정 #4) | ClawLiveCard 확장 + `/dashboard/kr/claw` |
| `GET /api/admin/mirofish/quality/kpi` 신설 | `app/routes/admin_mirofish.py` | `@admin_or_aibain_required` | AiBain 대시보드 4번째 카드(품질 KPI: 근거 완비율·공백 명시율·조기 제외 성적·top3 freshness) + admin 콘솔 |
| `GET .../aibain/overview` 확장 | `pipeline_overview.get_aibain_overview` — performance 섹션에 net 병기, detections 에 무효화·cap 병기 | 기존 | AiBainDashboard (**구독 상품 강화의 실체**: "왜 이 후보 + 언제 버리나 + 비용 후 성적") |

FE 변경은 P3에서만 발생: 본PC `frontend-react` 수정 → `npm run deploy` (CF Pages, miniPC와 독립 배포).

### 2.4 P4 (옴니소스) — scheduler.py 잡 편입 + 사건 원장, API는 P3 패턴 재사용 (별도 스펙 §7 로드맵 준수)

### 2.5 명시적 비부착 (불가침)

- 8080 (JUST BUY) · 5001 미확인 프로세스(정체 규명 전 무접촉) · `/api/us`·`/api/crypto`·커뮤니티·회원 계열 전체 · E-게이트(주문) 폐쇄 유지 · MCP mutation 0 유지.

---

## 3. 배포 시퀀스 (충돌·다운타임 없는 순서)

1. **miniPC 미푸시 6커밋 push** (사용자 승인; FE/ops/data뿐이라 안전)
2. 본PC P1 커밋(백엔드+테스트+스펙 문서) → push
3. miniPC `git pull` (autostash)
4. **재부팅으로 활성화** (Flask SSH 재시작 금지 — phantom socket boot-loop 이력. 재부팅이 확립된 안전 경로. 장외 시간 권장) → Flask(5003)·Scheduler·Claw 가 새 코드 로드
5. 검증(순서대로):
   - `agent_journal.jsonl`에 `refresh_intelligence` applied 기록 (당일 16:30 또는 23:30 사이클 후)
   - miniPC `intelligence/top3_metrics.json` mtime 갱신 + `insufficient` 실값 (1,228 workflow 코퍼스 기준)
   - `paper/overview` 응답에 `net_*` 필드 (admin 토큰)
   - 기존 표면 회귀: healthz 200, aibain/overview 200(인증), FE 대시보드 정상
6. P2 구현 완료 시: 동일 시퀀스 + `restart_claw.ps1`
7. P3 구현 완료 시: 백엔드 pull(+재부팅) 후 FE `npm run deploy`

## 4. 검증 게이트 (배포 후 정밀도 측정이 "살아있음"의 정의)

- top3_metrics `generated_at`이 매일 갱신되고, `qualified_runs`가 miniPC 코퍼스 기준 실값을 보고
- detection_lab 재실행(새 코드) 리포트에 net 블록 네이티브 포함 → R0′ 판정 문서 갱신
- 30일 후: KPI freshness 규칙 위반(24h 초과 정체) 0건

## 5. 후속 확인 항목 (이번 실사에서 발견)

1. **5001 (0.0.0.0 바인드) Flask 정체** — 어느 태스크가 띄우는지, 중복 Flask면 정리 대상 (외부 바인드라 보안 관점에서도 확인 가치). 규명 전 무접촉.
2. 이더넷 고정 IP(192.168.55.x) 복원 — 현재 APIPA(169.254.144.42) 임시 경로, 재부팅 시 변동 가능. 시스템 설정 변경이라 사용자 수행/승인 필요. **§3-4 재부팅 전에 복원해 두는 것을 권장** (재부팅 후 SSH 경로 유실 방지).
3. `MarketFlowFlaskOneShot`·중복 Watchdog 등록(동일 태스크 2행) — 태스크 정리 여지.

# MarketFlow Claw — 장중 주도주 수집·분석 로컬 자동화 설계

작성일: 2026-08-21 (KST)
상태: Phase 1 최소 구현 완료·본PC 검증(2026-08-22). miniPC 적용 대기 — 런북 `docs/superpowers/plans/2026-08-22-claw-minipc-handoff.md`
범위: Phase 1 = OpenClaw 의존 없는 로컬 자동화 코어. Phase 2 = OpenClaw 게이트웨이 브리지 (별도 스펙).

---

## 0. 한 줄 요약

`C:\bitman_marketfloww`에는 이미 OpenClaw가 하는 일의 **결정론적 절반**(KIS 5초 폴링 스크리너, 알파 스캐너 감시, 스케줄러, 텔레그램 발송, MCP 19개 읽기전용 도구)이 구현돼 있다. 없는 것은 **(1) 장중 틱 단위 메모리, (2) 상태 전이 이벤트 검출, (3) 하나의 CLI/게이트웨이 표면, (4) HALT 규칙이 있는 레짐 판단, (5) 이벤트→분석→보고를 잇는 루프**다. 이 다섯 가지를 `marketflow_claw/` 패키지로 추가하고, 기존 엔진은 **호출만** 한다. 매매·지갑 실행 경로는 코드 자체를 두지 않는다.

---

## 1. 딥리서치 결과

### 1.1 OpenClaw 실체 (2026.7.1-2, 이 PC에 설치됨)

| 구성요소 | 내용 | 출처 |
|---|---|---|
| Gateway | 호스트당 1개 장기 실행 데몬, `ws://127.0.0.1:18789` WebSocket 컨트롤플레인. 채널(Telegram/WhatsApp/Discord/…) 세션을 게이트웨이가 소유 | docs.openclaw.ai/concepts/architecture |
| Cron | `--cron/--every/--at` 시간 기반 + `--on-exit/--stream-command` 이벤트 기반. 페이로드 4종: system-event(모델 없음) / agent message(LLM 턴) / `--command`(호스트 셸, `sh -lc`) / script. 세션 `main|isolated`. `--announce --channel telegram --to <chatId>`로 결과 배달 | docs.openclaw.ai/automation/cron-jobs, `openclaw cron add --help` |
| Heartbeat | 기본 30분 주기 에이전트 턴, `HEARTBEAT.md` 체크리스트, `activeHours`, `HEARTBEAT_OK` 억제. 가벼운 상시 감시용 | docs.openclaw.ai/gateway/heartbeat |
| Webhooks | `hooks.enabled` + 전용 토큰. `POST /hooks/wake`(메인 세션 이벤트), `POST /hooks/agent`(격리 에이전트 턴, `deliver/channel/to` 지정) | docs.openclaw.ai/automation/cron-jobs#webhooks |
| Skills | 마크다운 `SKILL.md` + 도구 allow/deny. 에이전트별 workspace 텍스트 파일(AGENTS/SOUL/IDENTITY/HEARTBEAT)이 매 세션 주입 | 저장소 `integrations/openclaw/workspace/` |
| Sandbox | `off|non-main|all`. 기본 백엔드 **Docker** (`openclaw-sandbox:bookworm-slim`). Docker 없으면 SSH/Podman/OpenShell 대체 또는 샌드박스 해제 | docs.openclaw.ai/gateway/sandboxing |
| Telegram | 봇 토큰당 long-polling 1개만 허용(409 Conflict). `dmPolicy: pairing` 기본. 인바운드는 결정론적으로 같은 채널로 회신 | docs.openclaw.ai/channels/telegram |

### 1.2 이 PC의 OpenClaw 실측 상태 (2026-08-21)

- `openclaw daemon status`: **Scheduled Task 없음, 게이트웨이 미기동** (`ECONNREFUSED 127.0.0.1:18789`).
- `openclaw models status`: 기본 모델 `openai/gpt-5.5`, **인증 missing**.
- Docker: **미설치**. `marketflow` 에이전트는 `sandbox.mode=all` → 현재 에이전트 턴 실행 불가 (의도된 보안 프로파일이며 완화 금지가 기존 운영 규칙).
- `marketflow` 에이전트: 19개 `marketflow__*` 읽기전용 MCP 도구, 바인딩 0, `workspaceAccess: none`, runtime/fs/browser/cron/gateway/message 전부 deny. `MIROFISH_MCP_ALLOW_MUTATION=false`.
- 기존 운영 규칙(`skills/marketflow-openclaw-ops`): **OpenClaw는 읽기전용, Telegram/OpenClaw 결합 금지, 매매·배포·재시작 금지.**

### 1.3 저장소에 이미 있는 자동화 자산 (재사용 대상)

| 자산 | 위치 | Claw에서의 역할 |
|---|---|---|
| KIS 주도주 스크리너 (100점, 장중 3~5초 폴링, S/A/B 등급) | `app/services/kis_screener.py` `run_screening/load_latest/load_history/is_market_open` | **유일한 주도주 소스** |
| Flask ScreenerWorker (5초 폴링, S등급 텔레그램 5분 쿨다운, 1시간 요약) | `app/__init__.py:_start_screener_worker` | 실행 중이면 Claw는 그 결과 파일을 **소비**(단일 폴러 원칙) |
| Layer-2 보강 (15분) | `app/services/leading_enricher.py` | 그대로 사용 |
| KR 시장 레짐 (RISK_ON/OFF/NEUTRAL) | `market_gate.py:run_kr_market_gate` | 레짐 입력 (일 1회, 무거움) |
| 알파 스캐너 + 신선도 정책 + 이벤트 dedupe | `app/services/mirofish/alpha_scanner.py` (`SOURCE_FILE_POLICIES`, `ALERT_BLOCKING_FRESHNESS`) | HALT 규칙 원형 |
| 섹터 RS, 신용잔고, KIND 블랙리스트, DART 이벤트 | `sector_rs.py`, `credit_balance.py`, `blacklist.py`, `dart_event_latest.json` | 이벤트 리스크 태그 |
| 텔레그램 발송기 (개인/채널 분리) | `app/utils/scheduler._send_telegram(_long)(message, channel=)` | 유일한 발송 경로 |
| LLM 클라이언트 (provider 순서/폴백/메타데이터) | `app/services/mirofish/llm_client.py` | 서술문 생성 (숫자 소유 금지) |
| 스케줄러 데몬 + 하트비트 + 워치독 | `scheduler.py`, `scripts/scheduler_watchdog.ps1` | 운영 패턴 참조 |
| MCP 서버 (stdio/HTTP 8765) | `mirofish_mcp_server.py` | Phase 2에서 Claw 상태 노출 |
| 검증형 텔레그램 원샷 (run_id+digest 확인 게이트) | `app/services/mirofish/verified_delivery.py` | 훅 대상 예시 |

### 1.4 확인된 공백 (Claw가 메울 것)

1. **장중 틱 이력 부재**: `screener_leading_YYYYMMDD.json`은 그날 **마지막 스냅샷만 덮어씀**. 09:31 S등급 진입 → 10:10 이탈 같은 전이가 남지 않는다. 리플레이·학습 불가.
2. **이벤트 개념 부재**: 현재 알림은 "지금 S등급인 종목"(쿨다운 5분). "신규 진입 / 승격 / 이탈 / 섹터 군집 형성" 같은 **상태 전이**가 없다.
3. **HALT 규칙 부재(주도주 경로)**: 알파 스캐너는 신선도로 차단하지만, 주도주 경로는 KIS 실패 시 빈 결과를 조용히 보존한다. 환율·지수·스크리너가 동시에 죽으면 "결론 금지"를 선언하는 주체가 없다.
4. **표면 분산**: 상태 확인이 scheduler.py(4,000줄), Flask 워커, 개별 스크립트에 흩어져 있어 `status/brief/regime` 한 줄 명령이 없다.
5. **이벤트→분석→보고 루프 부재**: 주도주 이벤트가 발생해도 레짐·섹터·수급·공시 맥락을 붙여 서술하는 단계가 없다(알파 스캐너 쪽의 `scanner_deepverify`만 존재).

---

## 2. 접근법 비교

| | A. OpenClaw를 게이트웨이로 직접 사용 | **B. 네이티브 Python Claw 코어 (권장, Phase 1)** | C. 하이브리드 (B + OpenClaw 브리지, Phase 2) |
|---|---|---|---|
| 구성 | OpenClaw cron `--command`로 기존 스크립트 호출, `/hooks/agent`로 LLM 턴, Telegram 채널로 회신 | `marketflow_claw/` 패키지: 수집→메모리→이벤트→분석→보고 + CLI, Task Scheduler로 상주 | B를 코어로 두고 OpenClaw는 읽기전용 Q&A/하트비트 프런트만 담당 |
| 전제조건 | Docker(또는 샌드박스 해제), 모델 인증, 게이트웨이 데몬, 별도 봇 토큰 | `.venv`만 | B 완료 후 A의 전제조건 |
| 기존 보안 규칙 | `sandbox all` 완화 또는 Telegram 결합 필요 → **기존 운영 규칙과 충돌** | 충돌 없음 | OpenClaw는 계속 읽기전용 → 충돌 없음 |
| 호스트 부담 | Node 게이트웨이 + Docker 상주. 본PC는 WHEA/Python 크래시 **HIGH 리스크** 상태 | 경량 단일 프로세스 | B와 동일 + 선택적 |
| 장중 실시간성 | cron 최소 단위·LLM 턴 지연 → 틱 단위 부적합 | 3~5초 틱 소비, 이벤트 즉시 | B와 동일 |
| 대화형 질의 | 강함 (Telegram DM) | 없음 (CLI만) | OpenClaw가 제공 |
| 위험 | 토큰/채널 표면 확대, 409 폴링 충돌 | OpenClaw 기능 일부 재구현 | 두 시스템 동기화 |

**권고**: **B를 Phase 1로 먼저 구축**한다. 장중 실시간 수집·이벤트 검출은 결정론적 파이썬 루프가 맞고, 기존 19개 읽기전용 MCP·Telegram 분리 규칙을 건드리지 않는다. OpenClaw는 Docker·모델 인증이 준비되면 Phase 2에서 **읽기전용 대화 프런트**로 얹는다 (Claw 메모리를 MCP로 읽어 답하기만 함).

---

## 3. Phase 1 설계 — `marketflow_claw/`

### 3.1 디렉토리

```
marketflow_claw/                 # 최상위 패키지 (engine/, backtest/, chatbot/ 와 같은 관례)
├── __main__.py                  # CLI 진입: python -m marketflow_claw <cmd>
├── cli.py                       # brief | regime | leaders | events | status | start | skill | replay
├── config.py                    # claw.yaml 로드 + env 오버라이드 + 불변 안전값
├── clock.py                     # KST 시장 세션 (kis_screener.is_market_open / 휴장일 재사용)
├── collectors/
│   ├── leaders.py               # 주도주 스냅샷 소스: file(Flask 워커 산출물) | kis(직접) | auto
│   ├── regime_inputs.py         # market_gate 결과 캐시, 지수, USD/KRW (선택), breadth
│   └── context.py               # 섹터RS / 신용잔고 / 블랙리스트 / DART 이벤트 태그 (파일 읽기만)
├── regime.py                    # 레짐 분류 + HALT 판정
├── events.py                    # 연속 스냅샷 diff → 이벤트 (dedupe/쿨다운)
├── memory.py                    # SQLite data/claw/claw.db
├── analyst.py                   # 이벤트 컨텍스트 조립 + (선택) LLM 서술, 일일 예산
├── reporter.py                  # 메시지 빌더 (조간/장중/정오/마감/HALT)
├── delivery.py                  # app.utils.scheduler._send_telegram 래퍼 (개인봇 기본, dry-run)
├── gateway.py                   # `start` 상주 루프: 틱 → 이벤트 → 보고, 하트비트, PID 락
├── hooks.py                     # 브리핑 후 외부 훅 실행 (run_flow.py / BITMAN_HOOK 계약 호환)
└── skills/
    ├── registry.py              # SKILL.md + run(ctx) 로더
    ├── leaders_live/SKILL.md, skill.py
    ├── regime_check/...
    ├── sector_cluster/...
    ├── fx_watch/...
    ├── morning_brief/...
    └── close_wrap/...
claw.yaml                        # 저장소 루트, 비밀값 없음 (토큰은 .env)
data/claw/                       # claw.db, heartbeat.json, claw.pid, reports/YYYYMMDD/*.md
tests/test_claw_*.py
deploy/register_claw_task.ps1    # Task `MarketFlow-Claw` (운영자 계정, AtLogon/AtStartup)
```

### 3.2 데이터 흐름

```
[KIS]  ──(Flask ScreenerWorker 5s)──▶ data/screener_leading_latest.json
                                             │  (age ≤ 30s 이면 소비)
                                             ▼
                       collectors/leaders.py ──▶ Snapshot(ts, results[], by_grade, market_status)
         (파일 stale & Flask 락 없음 → kis_screener.run_screening 직접 호출: 단일 폴러 보장)
                                             │
           memory.snapshots (압축 행, 틱마다) ◀┤
                                             ▼
                 events.diff(prev, cur) ──▶ [LEADER_NEW, LEADER_UPGRADE, LEADER_DROP,
                                            SECTOR_CLUSTER, VOLUME_SURGE, NEW_HIGH_BREAK]
                                             │  dedupe(symbol,type, cooldown) → memory.events
                                             ▼
                 regime.evaluate(inputs) ──▶ {regime, breadth, fx_state, halt: bool, reasons[]}
                                             │  halt=True → 방향성 결론 금지, "검출 보류"만
                                             ▼
                 analyst.enrich(event, regime, context) ──▶ EvidencePacket (숫자 전부 소스 태깅)
                                             │  (선택) llm narrative ≤ N회/일, 실패 시 템플릿
                                             ▼
                 reporter.build(...) ──▶ 텍스트  ──▶ delivery.send(channel=False) ──▶ 개인 텔레그램
                                             │
                                             └──▶ memory.briefs + data/claw/reports/ + hooks.run()
```

### 3.3 컴포넌트 계약

**collectors/leaders.py**
- `fetch(mode: "auto"|"file"|"kis") -> Snapshot | None`
- `auto`: `screener_leading_latest.json`의 `timestamp`가 `now-30s` 이내면 파일 사용. 아니면 `data/claw/kis_poller.lock`(filelock)을 잡고 `run_screening()` 직접 호출. Flask 워커가 같은 PC에서 돌면 파일이 항상 신선하므로 직접 호출은 발생하지 않는다 → **KIS 호출 수가 늘지 않는다.**
- 장외(`is_market_open()==False`)는 `None` 반환, 루프는 60초 대기.

**memory.py (SQLite, WAL 모드)**
- `snapshots(id, ts, market_status, by_grade_json, top_json)` — `top_json`은 상위 30개의 `code,name,grade,score,change_pct,trading_value,sector` 만 (행당 수 KB).
- `events(id, ts, type, code, name, grade_from, grade_to, score, sector, payload_json, reported_at)` — `UNIQUE(date, type, code)`.
- `regimes(id, ts, regime, breadth, fx_rate, fx_state, halt, reasons_json)`.
- `briefs(id, ts, kind, digest, text_path, delivered, delivery_error)`.
- `outcomes(event_id, d1_ret, d5_ret, computed_at)` — 다음 거래일 이후 `daily_prices.csv`로 채움 (look-ahead 안전: 이벤트 ts 이후 가격만 사용).
- 보존: snapshots 30일, events/outcomes 영구. `VACUUM` 주 1회.

**events.py**
- 입력: 직전/현재 Snapshot. 출력: `list[Event]`.
- 규칙 (모두 claw.yaml에서 조정):
  - `LEADER_NEW`: 현재 S 또는 A, 직전 스냅샷과 **당일 events**에 없음.
  - `LEADER_UPGRADE`: 등급 상승 (B→A, A→S). `LEADER_DROP`: S/A → 목록 이탈 또는 C.
  - `SECTOR_CLUSTER`: 같은 섹터 S/A ≥ 3개가 **새로** 형성될 때 1회.
  - `VOLUME_SURGE`: `volume_ratio ≥ 3.0` 최초 도달. `NEW_HIGH_BREAK`: 52주 신고가 최초 (enricher 필드).
  - 쿨다운: 동일 `(type, code)` 당일 1회; `LEADER_DROP` 후 재진입은 `LEADER_NEW` 허용(재진입 플래그).
  - 개장 직후 09:00~09:05는 이벤트 억제(노이즈), 15:20 이후 신규 `LEADER_NEW` 억제(기존 15:30 컷오프와 정합).

**regime.py**
- 입력: `market_gate` 최신 결과(일 1회 08:10 갱신, 파일 캐시 `data/claw/market_gate_latest.json`), 스냅샷 breadth(S+A 수, 상승 종목 비율), USD/KRW(선택; yfinance `KRW=X` → 실패 시 None), 소스 신선도.
- 출력 `Regime(label ∈ {RISK_ON, NEUTRAL, RISK_OFF}, fx_state ∈ {calm, weak_krw_watch, weak_krw_alert, unknown}, halt, reasons)`.
- **HALT 조건** (하나라도 참이면 `halt=True`): 주도주 소스 `missing/stale`(5분 초과) **그리고** 레짐 입력(market_gate 또는 지수)도 실패; 또는 KIS 토큰 실패 3회 연속; 또는 `daily_prices.csv`가 `alpha_scanner.SOURCE_FILE_POLICIES` 기준 stale. HALT 중에는 `검출 보류` 보고만 가능, 종목 방향성 문구 금지 (verified_delivery와 같은 원칙).
- 환율 단독 실패는 HALT가 아니라 `fx_state=unknown`으로 표기.

**analyst.py**
- `enrich(event, regime, ctx) -> EvidencePacket`: 스냅샷 필드(점수 분해, 거래대금, 수급), 섹터 RS 등급, 신용잔고 경고, 블랙리스트/DART 악재 태그, 당일 같은 섹터 이벤트 수.
- `narrate(packet) -> str`: 기본은 **템플릿**. `claw.yaml: llm.enabled=true`이고 일일 예산(기본 20회) 남았을 때만 `llm_client`로 3문장 이내 한국어 서술. 프롬프트에 숫자는 packet에서만 주입, 응답에서 새 숫자/종목이 나오면 폐기하고 템플릿 사용 (multi-MCP 아키텍처 문서의 "LLM은 숫자를 소유하지 않는다" 규칙).

**reporter.py / delivery.py**
- 보고 종류: `morning`(08:20, 레짐+어제 이벤트 성과+감시 섹터), `event`(즉시, 쿨다운 내 묶음 발송 최대 5건), `midday`(11:30 요약), `close`(15:45 마감 요약 + 당일 이벤트 표), `halt`(HALT 진입/해제 시 1회).
- 발송은 `_send_telegram_long(msg, channel=False)` 고정(개인봇). 채널 발송은 `claw.yaml: delivery.channel_kinds: []` 기본 빈 목록 — 명시적으로 `close`를 넣을 때만 채널 동시 발송 (기존 "분석 결과는 채널도" 정책과 호환, 기본은 보수적).
- `--dry-run`이면 stdout + `data/claw/reports/`만 기록. 메시지 digest로 동일 메시지 재발송 차단.

**gateway.py (`start`)**
- PID 락 `data/claw/claw.pid`, 하트비트 `data/claw/heartbeat.json` 10초마다 갱신 (기존 watchdog 패턴과 동일 계약 → `scripts/scheduler_watchdog.ps1` 복제로 감시 가능).
- 루프: 장중 5초 틱(설정), 장외 60초. 예외 3회 연속 시 30초 백오프, 10회 연속 시 HALT 선언 + 알림 1회.
- 스케줄 표(KST): 08:10 market_gate 갱신 → 08:20 morning → 장중 틱 → 11:30 midday → 15:45 close → 16:30 outcomes 갱신(전일 이벤트 d1/d5 수익률).
- Windows 원자적 쓰기는 `app.utils.atomic_json.write_json_atomic` 재사용 (리더 경합 재시도 포함).

**hooks.py**
- `claw.yaml: hooks.after_brief: ["<cmd>", ...]` 또는 `BITMAN_HOOK` env. 각 훅은 subprocess, 타임아웃 120초, 실패해도 루프 지속. 브리핑 JSON을 stdin으로 전달. 예: `scripts/run_verified_alpha_telegram.py`(프리뷰 전용) 연결 가능. 훅은 **절대 자동 send 플래그를 붙이지 않는다.**

**skills/**
- `SKILL.md`(목적·입력·출력·금지) + `skill.py: run(ctx) -> dict`. `claw skill list|run <name> [--json]`. 스킬은 collectors/memory만 읽고 delivery는 호출 불가(보고는 reporter만).

**CLI**
```
python -m marketflow_claw status          # 하트비트, 마지막 스냅샷 age, 오늘 이벤트 수, HALT 여부, KIS 토큰 상태
python -m marketflow_claw leaders [--top 10] [--json]
python -m marketflow_claw regime [--json]
python -m marketflow_claw events [--today|--date YYYYMMDD]
python -m marketflow_claw brief [--kind morning|midday|close] [--dry-run] [--send]
python -m marketflow_claw start [--once]  # --once: 한 틱만 실행 후 종료 (테스트/Task 검증)
python -m marketflow_claw skill list|run <name>
python -m marketflow_claw replay --date YYYYMMDD [--from-db]  # 저장된 틱으로 이벤트 재생
```
`brief`는 기본 `--dry-run`. `--send`가 있어야 발송. 발송은 개인봇만.

### 3.4 안전 불변조건 (테스트로 고정)

1. 패키지 어디에도 주문/잔고 변경 API 경로 없음 (`grep`로 `order`, `tokenP` 외 KIS 주문 tr_id 미존재 테스트).
2. 발송 함수 호출은 `delivery.py` 한 곳, `channel=False` 기본, 채널 발송은 설정 명시 필요.
3. HALT 중 `reporter`는 종목 코드를 포함한 방향성 문구를 생성할 수 없다 (템플릿 단위 테스트).
4. LLM 출력에 packet 밖 숫자·종목이 있으면 폐기.
5. 단일 폴러: Flask 워커 산출물이 신선하면 KIS 직접 호출 0회 (모킹 테스트).
6. 비밀값은 로그/DB/리포트에 저장 금지 (`alpha_scanner`의 SENSITIVE 키 목록 재사용).
7. `claw.yaml`에 토큰·chat id 필드 없음 (스키마 검증).

### 3.5 테스트 전략

- 단위: `events.diff` 픽스처(연속 스냅샷 2~3개 → 기대 이벤트), `regime` HALT 진리표, `reporter` 골든 메시지, `memory` 라운드트립·보존, `analyst` LLM 폐기 규칙.
- 통합: `start --once`를 `data/screener_leading_latest.json` 픽스처로 실행 → DB 행/리포트 파일 생성 확인.
- 리플레이: `replay --date`로 DB 틱 재생 시 동일 이벤트 집합 재현 (결정론).
- 수동 육안 검증(필수, 메모리 `feedback_inspect_the_output_not_just_stats`): 첫 라이브 장중 1일 dry-run 후 이벤트 목록을 사람이 읽고 노이즈 임계치 조정.
- 회귀: 기존 `tests/`(131개 파일) 영향 없음 — Claw는 기존 모듈을 import만 하고 수정하지 않는다.

### 3.6 배포·운영

- 개발: 본PC에서 `start --once` / dry-run. **본PC는 현재 Python 크래시·WHEA HIGH 리스크** → 장시간 상주 테스트는 짧게, 라이브 상주는 miniPC.
- 운영(miniPC): Task `MarketFlow-Claw`(운영자 계정, AtStartup, 재시작 정책), 워치독은 기존 `scheduler_watchdog.ps1` 패턴 복제(`heartbeat.json` 180초). **단, miniPC 배포는 현재 별도 게이트(자격 redaction/rotation, FK 위반, 백업 증빙)로 차단 중** — 이 설계의 구현은 차단과 무관하게 진행 가능하나 miniPC 활성화는 그 게이트 해소 후.
- 포트: 없음(프로세스 단독). Flask 5001/5003, MCP 8765, 8080 금지 규칙 무관.
- 킬스위치: `CLAW_ENABLED=false`, `CLAW_DELIVERY_ENABLED=false`, `CLAW_LLM_ENABLED=false`.

### 3.7 사용자 프로토타입(`bitman_marketflow_claw`)과의 대응

| 프로토타입 | 이 설계 |
|---|---|
| `brief/regime/start/status/skill` | 동일 CLI + `leaders/events/replay` 추가 |
| USD/KRW + 네이버 지수·관심종목 | 환율은 `fx_watch`(선택), 지수·종목은 **KIS**(이미 인증된 소스)로 대체, 네이버 스크래핑 미사용 |
| HALT (환율·시장 동시 실패) | `regime.py` HALT 규칙 (3.3) |
| 08:20 / 15:45 / 주기 레짐 | 08:10/08:20/11:30/15:45/16:30 + 장중 틱 |
| SQLite 메모리 | `data/claw/claw.db` (틱·이벤트·성과까지 확장) |
| `run_flow.py` 훅 | `hooks.py` (`BITMAN_HOOK` 호환) |
| 매매·지갑 차단 | 주문 경로 코드 부재 + 테스트 고정 |
| `config.yaml` universe | `claw.yaml` (universe 대신 KIS 순위 유니버스; 관심종목 핀 목록 선택) |

---

## 4. Phase 2 스케치 — OpenClaw 브리지 (별도 스펙에서 확정)

전제: Docker Desktop/WSL2(또는 승인된 대체 샌드박스), `openclaw models auth`, 게이트웨이 `openclaw daemon install`(schtasks), **MarketFlow 발송봇과 다른 전용 봇 토큰**.

1. `mirofish_mcp_server.py`에 읽기전용 도구 3개 추가: `get_claw_status`, `get_claw_leaders_live`, `list_claw_events` → `scripts/setup_openclaw_mcp.py`의 `READ_ONLY_TOOLS`에 편입(19→22, 검증기·테스트 동반 갱신). 여전히 mutation 0.
2. OpenClaw cron: `--command-argv ["C:\\bitman_marketfloww\\.venv\\Scripts\\python.exe","-m","marketflow_claw","brief","--kind","close","--json"]` 처럼 **argv 형식**으로 등록(Windows에서 `sh -lc` 회피).
3. Claw `hooks.after_event` → `POST http://127.0.0.1:18789/hooks/agent`(전용 hook 토큰, `agentId=marketflow`, `deliver=true, channel=telegram, to=<전용봇 DM>`) → 격리 에이전트 턴이 MCP로 Claw 메모리를 읽고 **서술만** 회신. 스캔·발송 도구는 계속 deny.
4. 사용자 DM 질의("지금 주도주 뭐야?")는 OpenClaw Telegram 채널 → `marketflow` 에이전트 → MCP 읽기 → 회신. Claw 코어와 발송봇은 무관하게 유지(결합 금지 규칙 준수).

---

## 5. 결정 필요 사항 (사용자 확인)

1. Phase 1만 먼저 진행하는 데 동의하는지 (OpenClaw 브리지는 Docker·모델 인증 후 별도).
2. 상주 방식: **별도 프로세스 `MarketFlow-Claw`(권장)** vs `scheduler.py` 내부 잡으로 편입.
3. 발송 정책: 기본 **개인봇만**, `close` 요약만 채널 동시 발송 옵션 — 기본값을 개인봇 전용으로 둘지.
4. LLM 서술: Phase 1에 포함(예산 20회/일, 기본 off) vs 템플릿만.
5. USD/KRW 수집(yfinance, 선택 기능) 포함 여부.

---

## 6-A. 배포 준비 완료 항목 (2026-08-22 01:30 KST 기준)

- **연속 N틱 이탈 확정**: `events.confirmed_drops()` + `CLAW_DROP_CONFIRM_TICKS`(기본 3). 창 안에 오류 스냅샷·복귀가 있으면 미확정. 당일 스냅샷끼리만 비교.
- **단일 폴러 락**: `data/claw/kis_poller.lock`(filelock, timeout 0) — 다른 프로세스가 KIS를 부르는 중이면 파일로 폴백.
- **PID 락·하트비트**: `claw.pid`(죽은 PID는 덮어씀), `heartbeat.json`(장외 60초 idle 갱신) → 워치독 180초.
- **doctor**: env 키 존재·발송 경로·파일 신선도·DB 쓰기·KIS 토큰·텔레그램 getMe 점검(비밀값 미출력).
- **배포 키트**: `deploy/start_claw.vbs`, `deploy/register_claw_task.ps1`(SYSTEM·AtStartup·MINIPC 호스트 가드), `scripts/claw_watchdog.ps1`, `scripts/apply_claw_env.ps1`(멱등 .env 적용, 백업, 토큰 교체 옵션), 런북 `docs/superpowers/plans/2026-08-22-claw-minipc-handoff.md`.
- `.gitignore`에 `data/claw/` 추가. 기존 모듈 무수정(import만).
- 미구현(후속): `claw.yaml` 설정 파일(현재 env), SECTOR_CLUSTER, LLM 서술, 환율 수집, outcomes(D1/D5) 채움, 정오 요약 스케줄. 장중 5초 틱 실측은 다음 거래일.

## 6. 실행 가능성 스파이크 결과 (2026-08-22 00:54~00:59 KST, 본PC, 토요일)

시안이 아니라 **실제 코드**(`marketflow_claw/` v0.1.0-spike, 약 550줄 + 테스트 7개)를 붙여 실데이터로 돌린 결과다.

| 증명 항목 | 결과 | 근거 |
|---|---|---|
| KIS 실호출 (장외) | **동작** — 전일(08-21) 세션 기준 S2/A9/B4, 15종목, 53~73초, api_calls 53 (모의서버) | `start --once --source kis` |
| 스냅샷 → SQLite 메모리 | **동작** — `snapshots 2 · events 2 · regimes 2 · briefs 3` | `data/claw/claw.db` |
| 이벤트 diff (실데이터) | **동작** — 07-26→07-30→08-21 리플레이에서 NEW/UPGRADE/DROP 37건 검출(일 단위 diff) | `replay --dates …,latest` |
| 연속 틱 diff | **동작** — 틱1(file) → 틱2(kis) 사이 LEADER_DROP 2건(져스텍·알트 A→B) 검출, dedupe/reported 기록 | `events --date 20260822` |
| 레짐/HALT | **동작** — gate RED(102h stale)→RISK_OFF, 소스 정상이라 HALT 아님(사유만 기록) | `regime` |
| 브리핑 템플릿 (조간/마감/이벤트) | **동작** — 실종목명으로 생성, dry-run 파일 저장 + digest | `data/claw/reports/20260822/*.md` |
| 텔레그램 | **실발송 성공** (01:09 KST) — `@bitman75_bot` 토큰 → 사용자 개인 DM, HTTP 200 + ok + message_id, 원장 delivered=1. 동일 본문 재발송은 `duplicate_digest`로 차단 확인. 경로는 `CLAW_TELEGRAM_BOT_TOKEN_KEY`/`CLAW_TELEGRAM_CHAT_ID`(.env 신규 키), 기존 `TELEGRAM_*` 라우팅 무변경 | `brief --kind close --send` |
| 단위 테스트 | 7/7 통과 (diff 전이, already 억제, 오류 스냅샷 무발행, HALT 진리표, HALT 시 종목명 미포함) | `tests/test_claw_events.py` |

### 텔레그램 경로 정정
- 어제 기록의 "수신자가 봇을 차단해 403"은 **@bitmanHermes_bot(개인봇) 대화방이 사용자 쪽에서 삭제된 상태**를 API가 그렇게 표현한 것. 사용자는 차단한 적 없음.
- 사용자가 인지하는 봇은 **@bitman75_bot**(`TELEGRAM_CHANNEL_BOT_TOKEN`, 채널 발송용). 사용자 개인 채팅 ID는 기존 `TELEGRAM_CHAT_ID`와 동일("master" = 본인).
- 결정(B): Claw 개인 알림은 @bitman75_bot → 사용자 DM. 이어서 사용자 지시로 **본PC `.env`의 `TELEGRAM_BOT_TOKEN`을 @bitman75_bot 토큰으로 교체**(01:15 KST, 구 토큰은 주석 보존) → 기존 개인봇 경로 `_send_telegram(channel=False)` 실발송 성공. 본PC에는 Flask/스케줄러가 떠 있지 않아 재시작 불필요. **miniPC(운영) `.env`는 미교체** — 운영 개인 알림 복구는 miniPC 교체가 별도로 필요(배포 게이트·명시적 승인 대상).

### 스파이크에서 드러난 실제 문제 (설계 반영 필요)
0. **실발송 직후 잡힌 결함 2건 (수정 완료, 회귀 테스트 추가).** ① dry-run이 같은 digest를 `delivered=0`으로 먼저 기록하면 실발송 후 `INSERT OR IGNORE`가 갱신하지 않아 중복 차단이 영영 성립하지 않았고, 그 결과 **마감 요약이 사용자 DM에 2회 발송**됐다 → `save_brief`를 upsert(delivered는 단조 증가)로 교체. ② 테스트가 `memory.connect(path=DB_PATH)`의 기본 인자 바인딩 때문에 **운영 claw.db에 3행을 남겼다** → 호출 시점에 경로 해석 + 격리 검증 테스트 추가, 샌 행은 삭제.
1. **KIS 모의서버 타임아웃이 가짜 이탈 이벤트를 만든다.** 틱2에서 `inquire-investor` 2건이 read timeout → 수급 점수 0 → 져스텍·알트가 A→B로 "이탈". 실제 시장 변화가 아니다. → 규칙 추가: 등급 하락은 **연속 N틱(기본 3) 지속 시에만 확정**, 부분 실패(`api_calls` 대비 timeout 수)가 있는 스냅샷은 `partial=True`로 표시하고 DROP 발행 금지.
2. **`volume_ratio` 필드 의미가 섞여 있다.** 대형주는 평균 대비 %(97.2), 일부는 원시 거래량(4.4억). 스파이크는 300%~100,000 구간만 VOLUME_SURGE로 인정. → Phase 1에서 `kis_screener` 쪽 필드 정규화 또는 Claw 수집기에서 거래량/평균거래량 재계산.
3. **섹터 필드 부재** → SECTOR_CLUSTER는 섹터 맵(`korean_stocks_list.csv` 등) 조인 후에만 가능.
4. **장중 틱 증명은 평일에만 가능.** 다음 거래일 09:00~15:30 `start` 상주로 5초 틱 누적·이벤트 실측이 Phase 1 첫 검증 게이트.
5. 모의서버(`KIS_PAPER`)는 틱당 53~73초 → 5초 틱 불가. 장중 실시간은 Flask ScreenerWorker 산출물(단일 폴러) 소비가 전제이며, 직접 호출은 실서버 전환 또는 호출 수 축소가 필요.

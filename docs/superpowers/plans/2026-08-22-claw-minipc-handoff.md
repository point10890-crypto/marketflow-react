# MarketFlow Claw — MiniPC 적용 런북

작성: 2026-08-22 (본PC에서 구현·검증 완료, miniPC는 현재 분리 상태)
전제: 본PC와 miniPC가 다시 연결되면 **아래 순서 그대로** 실행한다. 모든 단계는 멱등이며 비밀값을 git에 두지 않는다.

## 0. 이 변경이 miniPC에 하는 일

| 항목 | 내용 |
|---|---|
| 코드 | `marketflow_claw/` 패키지 (장중 주도주 틱 메모리 · 이벤트 · 레짐/HALT · 브리핑 · 개인 DM 발송) |
| 데이터 | `data/claw/` (gitignore) — `claw.db`, `heartbeat.json`, `claw.pid`, `reports/` |
| Task | `MarketFlow-Claw` (SYSTEM, AtStartup, `deploy/start_claw.vbs`) + `MarketFlow-Claw-Watchdog` (5분) |
| `.env` | `CLAW_TELEGRAM_BOT_TOKEN_KEY`, `CLAW_TELEGRAM_CHAT_ID`, `CLAW_DROP_CONFIRM_TICKS`, `CLAW_DELIVERY_ENABLED` (+선택: `TELEGRAM_BOT_TOKEN` 교체) |
| 기존 시스템 영향 | **없음.** 기존 모듈을 수정하지 않고 import만 한다. Flask/스케줄러 재시작 불필요. KIS 호출은 Flask ScreenerWorker 산출물이 30초 이내면 0회(단일 폴러). |

## 1. 코드 동기화 (miniPC, 운영자 계정 PowerShell)

```powershell
cd C:\bitman_marketfloww
git fetch origin
git pull --ff-only origin main      # reset/clean/autostash 금지 (ops 규칙)
.\.venv\Scripts\python.exe -c "import filelock, dotenv, requests; print('deps ok')"
```

## 2. `.env` 적용 (비밀값은 로컬 .env 안에서만 복사)

```powershell
# Claw 키만 추가 (발송 OFF 상태로 시작)
.\scripts\apply_claw_env.ps1

# 개인봇(@bitmanHermes_bot) 경로가 403인 상태를 운영에서도 해소하려면 — 본PC와 동일하게 교체
.\scripts\apply_claw_env.ps1 -SwapPersonalBotToken
```
- 스크립트는 실행 전 `.env.bak_claw_<timestamp>` 백업을 남기고, 구 토큰은 `# TELEGRAM_BOT_TOKEN_HERMES_OLD=` 주석으로 보존한다.
- `-SwapPersonalBotToken`은 **스케줄러/Flask가 .env를 다시 읽어야 반영**된다 (프로세스 시작 시 load_dotenv). 다음 재부팅에 자연 반영되며, 즉시 반영하려면 재부팅을 택한다 — miniPC Flask의 SSH 재시작은 phantom-socket 위험이 있어 재시작 대신 **재부팅**이 규칙(`feedback_minipc_flask_restart_hazard`).

## 3. 점검 (네트워크 포함)

```powershell
.\.venv\Scripts\python.exe -m marketflow_claw doctor
```
기대: `env:*` 5개 ok · `delivery:route direct-dm via TELEGRAM_CHANNEL_BOT_TOKEN` ok · `file:leaders_latest` ok · `db:writable` ok · `kis:token` ok · `telegram:getMe @bitman75_bot` ok · `RESULT: ok`.
`delivery:enabled`가 WARN이면 아직 발송 OFF(의도된 초기 상태).

## 4. 1틱 스모크 (발송 없음)

```powershell
.\.venv\Scripts\python.exe -m marketflow_claw start --once --source auto
.\.venv\Scripts\python.exe -m marketflow_claw status
```
장중이면 Flask 산출물(age ≤30s)을 소비해 `source: file`로 끝나야 한다. 장외면 KIS 직접 호출(모의서버 53~73초)로 끝난다.

## 5. Task 등록 (관리자 PowerShell, 1회)

```powershell
Start-Process powershell -Verb RunAs -ArgumentList '-ExecutionPolicy Bypass -File C:\bitman_marketfloww\deploy\register_claw_task.ps1'
Get-ScheduledTask | Where-Object TaskName -like 'MarketFlow-Claw*' | Select TaskName, State
Get-Content data\claw\heartbeat.json
```
호스트명이 `MINIPC-NQYLP`가 아니면 스크립트가 스스로 건너뛴다(다른 PC 오등록 방지). 워치독은 `heartbeat.json`이 180초 넘게 멈추면 `MarketFlow-Claw`만 재기동한다(Flask/스케줄러는 건드리지 않음).

## 6. 발송 ON (dry-run 하루 관찰 후 권장)

```powershell
.\scripts\apply_claw_env.ps1 -EnableDelivery
# 루프는 .env를 시작 시 읽으므로 Claw만 재기동:
Stop-ScheduledTask -TaskName MarketFlow-Claw; Start-ScheduledTask -TaskName MarketFlow-Claw
.\.venv\Scripts\python.exe -m marketflow_claw brief --kind close --send   # 수신 확인용 1건
```
동일 본문은 `duplicate_digest`로 재발송되지 않는다.

## 7. 롤백

```powershell
Stop-ScheduledTask -TaskName MarketFlow-Claw
Unregister-ScheduledTask -TaskName MarketFlow-Claw -Confirm:$false
Unregister-ScheduledTask -TaskName MarketFlow-Claw-Watchdog -Confirm:$false
Copy-Item .env.bak_claw_<timestamp> .env     # .env 원복이 필요할 때만
```
코드는 기존 모듈을 건드리지 않으므로 Task 해제만으로 운영 영향이 사라진다.

## 8. 본PC에서 이미 검증된 것 (2026-08-22)

- KIS 실호출 → 스냅샷 → SQLite → 이벤트 → 브리핑 → **@bitman75_bot DM 실발송 성공**(HTTP 200 + message_id).
- 가짜 이탈(모의서버 타임아웃) 방지: `LEADER_DROP`은 **연속 3틱 확정**(`CLAW_DROP_CONFIRM_TICKS`) 후에만 발행, 창 안에 오류 스냅샷이 있으면 미확정.
- 중복 발송 차단(upsert 원장), 테스트 격리, PID 락, 단일 폴러 락, 워치독 계약.
- 테스트: `tests/test_claw_events.py`, `tests/test_claw_delivery.py`.
- 미검증: **평일 장중 5초 틱 실측**(다음 거래일 첫 게이트), SECTOR_CLUSTER(섹터 필드 부재), LLM 서술(미포함).

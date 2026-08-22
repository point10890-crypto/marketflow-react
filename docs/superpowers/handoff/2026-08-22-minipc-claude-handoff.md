# miniPC 인수인계 — MarketFlow Claw + 대시보드 테마 (2026-08-22)

> **이 문서는 miniPC에서 새로 여는 Claude Code 세션이 가장 먼저 읽는 인수인계서입니다.**
> 본PC(ROG Strix 노트북, `192.168.110.128`)에서 구현·검증한 내용을 miniPC(`MINIPC-NQYLP`, `192.168.55.103`)에 적용하기 위한 것입니다.
> 코드는 전부 `origin/main`(`3afe957` 이후)에 있으므로 `git pull`로 그대로 전달됩니다. 전달되지 **않는** 것은 §3을 보세요.

---

## 0. miniPC Claude Code 첫 프롬프트 (복사해서 붙여넣기)

```
docs/superpowers/handoff/2026-08-22-minipc-claude-handoff.md 를 읽고, 이 PC가 miniPC(MINIPC-NQYLP)인지 hostname 으로 확인한 뒤,
§4 적용 순서를 한 단계씩 실행해줘. 각 단계 결과를 보고하고, 재부팅·Task 등록처럼 되돌리기 어려운 단계 전에는 나에게 확인을 받아.
절대 규칙: 8080 포트/JUST BUY 건드리지 말 것, Flask 를 SSH 로 재시작하지 말고 재부팅으로 반영할 것, git reset/clean 금지(pull --ff-only 만).
```

---

## 1. 무엇이 새로 구현됐나 (커밋 순)

| 커밋 | 내용 |
|---|---|
| `68b4035` | **MarketFlow Claw Phase 1** — `marketflow_claw/` (KIS 주도주 틱 메모리 SQLite · 상태전이 이벤트 NEW/UP/DROP/VOL/HIGH · DROP 3틱 확정 · 레짐/HALT · 브리핑 · 텔레그램 개인 DM 발송 · PID/단일폴러 락 · `doctor` CLI) + 배포 키트(`deploy/register_claw_task.ps1`, `deploy/start_claw.vbs`, `scripts/claw_watchdog.ps1`, `scripts/apply_claw_env.ps1`) + 런북 |
| `a030586` | `.gitignore`에 `.env.bak*` (apply 스크립트가 만드는 백업, 토큰 포함) |
| `1c19596` | **Claw LIVE 대시보드** — `GET /api/kr/claw/overview`(`@pro_required`, 읽기전용) + AI Brain 페이지 `ClawLiveCard` + `/dashboard/kr/claw` 전체 화면 + 사이드바 KR→Claw LIVE |
| `fe543fa` | 원본 마스코트(SVG 크랩) · ASCII 집게 캔버스 · 헤드라인 "진짜 주식 분석하는 인공지능 에이전트." · 신뢰 칩 |
| `da2eeca` | 마스코트/아우라 **브랜드 레드**, 전 페이지 브랜드 바(`useClawState` 60초 공유 폴링), 셸 레드 테마, BitMan 로고 레드 |
| `5184fab` | **셸 레벨 전역 리스킨**(`.claw-theme` CSS 레이어: 카드 표면·악센트 단어·활성 내비·스크롤바) + **모바일 세로** |
| `3afe957` | 고정 타이틀 = **중앙 마스코트 배너**(172px) → 스크롤 시 64px 한 줄로 접힘(모바일 132/56) |

설계·검증 기록: `docs/superpowers/specs/2026-08-21-marketflow-claw-intraday-automation-design.md`(§6 실측), `docs/superpowers/specs/2026-08-22-claw-dashboard-design.md`(§9~§11).

## 2. 본PC에서 이미 검증된 것

- KIS 실호출 → 스냅샷 → SQLite → 이벤트 → 브리핑 → **@bitman75_bot 개인 DM 실발송 성공**(HTTP 200 + message_id).
- pytest(Claw 18개) · vitest 97/97 · `tsc`·`vite build` 통과. 로컬 Flask 5001 + Vite 4000에서 AI Brain 카드·Claw 전체 화면·브랜드 배너·모바일 375px 확인.
- 가짜 이탈 방지(KIS 모의서버 타임아웃 → 3틱 확정), 중복 발송 차단(upsert 원장), 테스트 DB 격리 — 전부 실사고를 겪고 고친 것.

## 3. git으로 전달되지 않는 것 (miniPC에서 별도 처리)

| 항목 | 처리 |
|---|---|
| `.env`의 Claw 키 4개 + `TELEGRAM_BOT_TOKEN` 교체 | `scripts/apply_claw_env.ps1 -SwapPersonalBotToken` — **miniPC 로컬 `.env` 안의 값끼리 복사**(비밀값 전송 없음). 구 토큰은 `# TELEGRAM_BOT_TOKEN_HERMES_OLD=` 주석으로 보존 |
| `data/claw/` (DB·하트비트·리포트) | gitignore. miniPC에서 첫 틱이 새로 만든다 |
| 본PC Claude Code 메모리(`~/.claude/projects/C--bitman-marketfloww/memory/`) | 전달 안 됨. 핵심은 이 문서 §5에 옮겨 적음. 원하면 LAN으로 폴더 복사 가능 |
| Cloudflare Pages 프론트 배포 | 어느 PC에서든 `cd frontend-react && npm run deploy` (wrangler 로그인 필요). **아직 미배포** |

## 4. miniPC 적용 순서 (런북 `docs/superpowers/plans/2026-08-22-claw-minipc-handoff.md`의 요약)

```powershell
# 0) 여기가 miniPC인지
hostname            # MINIPC-NQYLP 여야 함

# 1) 코드
cd C:\bitman_marketfloww
git fetch origin; git pull --ff-only origin main      # reset/clean/autostash 금지
.\.venv\Scripts\python.exe -c "import filelock, dotenv, requests; print('deps ok')"

# 2) .env (비밀값은 로컬 .env 안에서만 복사)
.\scripts\apply_claw_env.ps1 -SwapPersonalBotToken    # CLAW_* 4키 추가 + 개인봇 토큰을 @bitman75_bot 으로

# 3) 점검
.\.venv\Scripts\python.exe -m marketflow_claw doctor  # RESULT: ok 여야 함 (delivery:enabled WARN 은 정상=발송 OFF)

# 4) 1틱 스모크 (발송 없음)
.\.venv\Scripts\python.exe -m marketflow_claw start --once --source auto
.\.venv\Scripts\python.exe -m marketflow_claw status

# 5) Flask 에 /api/kr/claw/overview 반영 — SSH 재시작 금지, **재부팅**으로 (phantom-socket 규칙)
#    재부팅 후: Invoke-WebRequest http://127.0.0.1:5003/healthz ; 공개 https://marketflow-api.bit-man.net/healthz

# 6) Task 등록 (관리자 PowerShell, 1회) — 사용자 확인 후
Start-Process powershell -Verb RunAs -ArgumentList '-ExecutionPolicy Bypass -File C:\bitman_marketfloww\deploy\register_claw_task.ps1'
Get-ScheduledTask | Where-Object TaskName -like 'MarketFlow-Claw*' | Select TaskName, State
Get-Content data\claw\heartbeat.json

# 7) 발송 ON (dry-run 하루 관찰 후 권장)
.\scripts\apply_claw_env.ps1 -EnableDelivery
Stop-ScheduledTask -TaskName MarketFlow-Claw; Start-ScheduledTask -TaskName MarketFlow-Claw
.\.venv\Scripts\python.exe -m marketflow_claw brief --kind close --send     # 수신 확인 1건

# 8) 프론트 배포 (wrangler 가 있는 PC에서)
cd frontend-react; npm run deploy
```

롤백: `Unregister-ScheduledTask MarketFlow-Claw / MarketFlow-Claw-Watchdog` + `.env.bak_claw_<ts>` 원복. 기존 모듈은 무수정이라 Task 해제만으로 영향이 사라짐.

## 5. 반드시 알아야 할 사실 (본PC 메모리에서 옮김)

- **텔레그램 봇 2개**: `TELEGRAM_CHANNEL_BOT_TOKEN` = **@bitman75_bot**(사용자가 쓰는 봇, 채널+개인 DM). 구 `TELEGRAM_BOT_TOKEN` = **@bitmanHermes_bot**(사용자가 대화방을 삭제해 403 — "차단"이 아니라 삭제). 본PC는 이미 교체됨, miniPC는 위 2)에서 교체. 사용자 개인 채팅 ID = 기존 `TELEGRAM_CHAT_ID`(표시명 "master").
- **포트**: 운영 Flask **5003**(5001은 개발용), MCP 8765, **8080은 JUST BUY — 절대 건드리지 말 것**.
- **운영 규칙**: miniPC Flask는 SSH 재시작 금지(phantom socket) → 재부팅. `git pull --ff-only`만. 커밋은 `git push origin main`. CF Pages는 push와 무관하게 `npm run deploy` 필요.
- **Claw 안전장치**: 매매 코드 경로 없음 · 발송은 `--send` + `CLAW_DELIVERY_ENABLED=1` 둘 다 필요 · 동일 digest 재발송 차단 · DROP은 `CLAW_DROP_CONFIRM_TICKS`(3) 연속 확정 · Flask ScreenerWorker 산출물이 30초 이내면 KIS 직접호출 0회 · 킬스위치 `CLAW_ENABLED / CLAW_DELIVERY_ENABLED / CLAW_LLM_ENABLED`.
- **실측 함정**: KIS 모의서버(`KIS_PAPER`)는 틱당 53~73초 + `inquire-investor` 타임아웃이 가짜 DROP을 만든다. `kis_screener.volume_ratio`는 %와 원시 거래량이 섞인 필드. 스크리너 결과에 섹터 필드 없음(SECTOR_CLUSTER 미구현).
- **OpenClaw**: 본PC에 2026.7.1-2 설치돼 있으나 게이트웨이 미기동·모델 인증 없음·Docker 없음. Claw는 OpenClaw를 쓰지 않는 순수 Python. OpenClaw 브리지는 Phase 2(선택). 마스코트는 OpenClaw 자산이 아닌 원본.
- **대시보드 테마**: 페이지 JSX 무수정, `.claw-theme` CSS 레이어. 등급(S/A/B)·KRX 등락·경고 의미색은 의도적으로 유지.

## 6. 남은 결정·다음 단계

1. 평일 장중 `start` 상주 실측(5초 틱·실이벤트) — Phase 1 첫 게이트. 마스코트가 빨간 LIVE 표정으로 바뀌는지 확인.
2. Cloudflare Pages 배포 시점 (miniPC Flask 반영 후 권장; 먼저 해도 카드·배너는 안전하게 degrade).
3. 후속: `claw.yaml`, SECTOR_CLUSTER(섹터 맵), LLM 서술, 환율, outcomes D1/D5, 정오 요약, 페이지 내부 개별 리스킨, OpenClaw 브리지.

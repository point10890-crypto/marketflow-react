# MarketFlow Infrastructure — Single Source of Truth

> **이 문서가 인프라의 단일 진실 소스(Single Source of Truth)입니다.**
> 어떤 코드/문서가 이 파일과 충돌하면 **이 파일이 옳고**, 코드를 이 파일에 맞춰 수정합니다.
> 변경 시 반드시 이 파일을 먼저 갱신하고 PR/커밋합니다.

Last updated: 2026-08-21

> **2026-04-08 정정**: 라이브 프로세스 검사 결과, 8080 포트는 MarketFlow 가 아닌 별도 프로젝트 JUST BUY (`C:\bitman_justbuy_project`) 의 `justbuy-api-1.0.0.jar` 가 점유하며 `api.bit-man.net` 도 JUST BUY 로 라우팅됨이 확인되었습니다. MarketFlow `backend/` 디렉토리는 dead code 로 분류하고, 8080 / Spring Boot 관련 항목을 SSOT 에서 제거했습니다. **Future Linux design only**에서 systemd를 채택할 경우에도 MarketFlow unit은 `marketflow-flask.service`, `marketflow-scheduler.service` 두 개만 설계하며, 이는 현행 Windows MiniPC 운영 지시가 아닙니다.

> **2026-08-21 운영 정정**: Windows MiniPC production은
> `C:\bitman_marketfloww` + Task Scheduler이며 Flask는
> `127.0.0.1:5003`이다. `5001`은 Local development only이다. Linux
> `/srv/marketflow`와 systemd는 Future Linux design only이며 현재 운영값이
> 아니다. 이 구분과 충돌하는 예전 helper는 배포에 사용하지 않는다.

---

## 1. 절대 경로 (FIXED — 변경 금지)

### 1.1 Windows (현 운영 호스트)

| 항목 | 절대 경로 (Windows) | MINGW 경로 |
|---|---|---|
| 프로젝트 루트 | `C:\bitman_marketfloww` | `/c/bitman_marketfloww` |
| Python venv | `C:\bitman_marketfloww\.venv\Scripts\python.exe` | `/c/bitman_marketfloww/.venv/Scripts/python.exe` |
| 데이터 디렉토리 | `C:\bitman_marketfloww\data` | `/c/bitman_marketfloww/data` |
| 로그 디렉토리 | `C:\bitman_marketfloww\logs` | `/c/bitman_marketfloww/logs` |
| 프론트엔드 | `C:\bitman_marketfloww\frontend-react` | `/c/bitman_marketfloww/frontend-react` |
| ~~백엔드 (Spring)~~ | `C:\bitman_marketfloww\backend` (**DEAD CODE — 운영 배포 없음**) | 동일 |
| Cloudflared 설정 | 운영자 프로필의 `.cloudflared\config.yml` | 운영자 프로필 아래 동일 파일 |
| Cloudflared 자격 | 운영자 프로필의 비추적 자격 파일 | 비추적; 문서/출력/커밋 금지 |
| Crypto 분석 | `C:\bitman_marketfloww\crypto-analytics\crypto_market` | 동일 |

### 1.2 Future Linux design only (현재 배포 대상 아님)

| 항목 | 절대 경로 (Linux) |
|---|---|
| 프로젝트 루트 | `/srv/marketflow` |
| Python venv | `/srv/marketflow/.venv/bin/python` |
| 데이터 디렉토리 | `/srv/marketflow/data` |
| 로그 디렉토리 | `/srv/marketflow/logs` |
| 프론트엔드 | `/srv/marketflow/frontend-react` |
| Cloudflared 설정 | `/etc/cloudflared/config.yml` |
| Cloudflared 자격 | `/etc/cloudflared/<operator-managed-credential>.json` |
| Crypto 분석 | `/srv/marketflow/crypto-analytics/crypto_market` |
| systemd unit | `/etc/systemd/system/marketflow-{flask,scheduler}.service` |
| logrotate | `/etc/logrotate.d/marketflow` |

**OS 분기 패턴**:
- Python: `Path(__file__).resolve().parent` 기준 상대 계산 (모든 모듈)
- `scheduler.py` `Config.PYTHON_PATH`: `os.name == 'nt'` 분기 (`.venv/Scripts/python.exe` vs `.venv/bin/python`)
- Cloudflared: 사용자 홈 의존 제거, `/etc/cloudflared/`로 시스템 영역 이동
- `diagnostics.py`: `tasklist` → `/proc/status` + `ps` 크로스플랫폼 분기 (2026-04-11 수정)
- `production_utils.py`: `msvcrt`/`fcntl` 독립 임포트 (2026-04-11 수정)
- `flask_app.py`: `RENDER` 환경변수 없으면 `127.0.0.1` 바인딩 (홈서버 보안)
- `backend/` (Spring Boot): **운영 배포 없음**. 코드는 repo에 남아있지만 어떤 호스트에서도 실행되지 않음. 미니PC 이전 시 systemd unit 만들지 말 것.

**규칙**:
- 모든 코드에서 경로는 **`os.path.dirname(__file__)` 기반 상대 계산** 또는 **이 표의 절대 경로**만 사용
- 하드코딩한 다른 경로 발견 시 즉시 이 표 기준으로 수정
- 새 디렉토리 추가 시 이 표에 먼저 등록

---

## 2. Windows MiniPC production 네트워크 (FIXED)

### 2.1 로컬 서비스 포트 (LAN/Localhost only)

| 포트 | 서비스 | 프로세스 | 시작 명령 | 외부 노출 |
|---|---|---|---|---|
| **5003** | Flask API (Windows MiniPC production) | `flask_app.py` | Task `MarketFlow-Flask` → `scripts\start_flask_task.ps1` | 터널 경유 (`marketflow-api.bit-man.net`) |
| **5001** | Flask API (Local development only) | `flask_app.py` | `FLASK_PORT=5001` 또는 기본 로컬 실행 | 로컬만 |
| **5173** | Vite dev (Local development only) | `frontend-react` | `npm run dev` | 로컬만 |
| **N/A** | Scheduler 데몬 (Windows MiniPC production) | `scheduler.py --daemon` | Task `MarketFlow-Scheduler` | 없음 (백그라운드 잡) |

**금지/외부 점유 포트**:
- `5002`: 구 cloudflared 잘못된 라우팅의 흔적, 사용 안 함
- `8080`: **MarketFlow가 사용하지 않음**. 이 PC에서는 별도 프로젝트(JUST BUY, `C:\bitman_justbuy_project`)의 Spring Boot JAR이 점유 중. MarketFlow `backend/` 디렉토리는 dead code이며, 실수로라도 `gradlew bootRun`을 띄우지 말 것 (JUST BUY와 충돌). JUST BUY의 `autostart.vbs`는 침범 시 자동 종료시키는 방어 로직(`KillStrayMarketflowOn8080`) 보유.

### 2.2 포트 점유 확인

```powershell
# Windows MiniPC production 확인: 5003만 Flask production 계약이다.
Get-NetTCPConnection -State Listen -LocalPort 5003 -ErrorAction SilentlyContinue

# 개발 PC 확인: 5001/5173은 Local development only이다.
Get-NetTCPConnection -State Listen -LocalPort 5001,5173 -ErrorAction SilentlyContinue
```

### 2.3 단일 인스턴스 보장

| 서비스 | PID 파일 | 락 메커니즘 |
|---|---|---|
| Scheduler | `logs/scheduler.pid` | PID 파일 + 포트 락 |
| Flask production | Task `MarketFlow-Flask` | OS `127.0.0.1:5003` 바인딩 |
| Cloudflared | Task/서비스 운영 계약 | 구성된 tunnel 단일 |

---

## 3. Cloudflare Tunnel (FIXED)

### 3.1 터널 정보

| 항목 | 값 |
|---|---|
| Tunnel Name | `bitman-api` |
| Tunnel ID | 운영자 비추적 구성에서만 조회; 문서/출력/커밋 금지 |
| Config | 운영자 프로필의 `.cloudflared\config.yml` (비추적) |
| Credentials | 운영자 프로필의 자격 파일 (비추적; rotation 확인 전 배포 차단) |
| 연결 수 | 4 (icn05 ×2, icn06 ×2) |

> **참고**: 같은 PC에 별도 프로젝트(JUST BUY)가 자기 터널(`justbuy-tunnel`)을 함께 운영합니다. MarketFlow 운영상 무관하므로 이 SSOT는 추적하지 않습니다.

### 3.2 라우팅 매트릭스 (MarketFlow 소속만)

| 외부 호스트 | → | 로컬 서비스 | 용도 |
|---|---|---|---|
| `https://marketflow-api.bit-man.net` | → | `http://127.0.0.1:5003` | Windows MiniPC production Flask API |
| (그 외 MarketFlow 호스트) | → | `http_status:404` | 차단 |

> `api.bit-man.net` 은 동일 config.yml 에 ingress 로 남아있지만 **JUST BUY 프로젝트의 :8080 JAR 로 라우팅** 됩니다. MarketFlow 코드/문서/배포에서 이 호스트를 호출하거나 재정의하지 마세요. config.yml 상의 의존성은 JUST BUY 측 변경 권한에 둡니다.

### 3.3 config.yml 계약 (민감값을 제거한 설명용 예시)

```yaml
tunnel: <operator-managed-tunnel-id>
credentials-file: <operator-managed-untracked-credential-file>

ingress:
  - hostname: marketflow-api.bit-man.net
    service: http://127.0.0.1:5003
  - service: http_status:404
```

이 블록은 자격 파일에 복사할 수 있는 완전한 설정이 아니다. 같은 호스트의
JUST BUY ingress는 그 프로젝트 소유이며 MarketFlow가 수정하지 않는다.

### 3.4 운영 명령

```powershell
# 로컬 Flask health (Windows MiniPC production)
Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 http://127.0.0.1:5003/healthz
Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 http://127.0.0.1:5003/api/health

# 공개 tunnel health
Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 https://marketflow-api.bit-man.net/healthz
Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 https://marketflow-api.bit-man.net/api/health
```

현행 파일/작업 계약:

- Flask launcher: Task `MarketFlow-Flask` → `scripts\start_flask_task.ps1` →
  `FLASK_HOST=127.0.0.1`, `FLASK_PORT=5003`.
- Flask watchdog: Task `MarketFlow-Flask-Watchdog` →
  `scripts\flask_watchdog_v2.ps1` → local `/healthz` on 5003.
- Tunnel watchdog: Task `MarketFlow-Tunnel-Watchdog` →
  `scripts\tunnel_watchdog.ps1` → public `/healthz` plus local 5003 isolation.
- Tunnel connector: Task `MarketFlow-Cloudflared` and its operator-owned,
  untracked config. Do not print or copy config/credential contents.

---

## 4. 프론트엔드 배포 (FIXED)

### 4.1 호스팅

| 환경 | URL | 호스팅 | 빌드 산출물 |
|---|---|---|---|
| **Production** | `https://bit-man.net`, `https://www.bit-man.net` | **Cloudflare Pages** project `bitman-marketflow` | `frontend-react/dist/` |
| **Local dev** | `http://localhost:5173` | Vite | (메모리) |

> **중요**: 현재 `wrangler.toml`은 Workers 형식이지만 실제 서빙은 **Pages** project에서 합니다. 동일 이름이라 혼동 주의.

### 4.2 배포 명령 (정본 — 이 명령만 사용)

```bash
cd /c/bitman_marketfloww/frontend-react
npm run build
npx wrangler pages deploy dist --project-name=bitman-marketflow --branch=main --commit-dirty=true
```

### 4.3 환경 변수

`frontend-react/.env.production` (정본):
```
VITE_API_BASE_URL=https://marketflow-api.bit-man.net
```

> 프론트엔드는 **모든 production API 호출을
> `marketflow-api.bit-man.net`(Flask) 로** 보냅니다. 터널 뒤 Windows MiniPC
> production Flask는 `127.0.0.1:5003`이며, 개발 PC의 직접 실행만
> `127.0.0.1:5001`을 사용합니다. MarketFlow에는 자체 Spring Boot 백엔드가
> 없고 `api.bit-man.net`은 별도 프로젝트(JUST BUY) 소속이므로 호출 금지입니다.

### 4.4 CI/CD

- **GitHub Actions 자동 배포**: **DISABLED** (`.github/workflows/deploy-frontend.yml` `workflow_dispatch`만)
- **로컬 수동 배포만**: 위 4.2 명령으로 통일

### 4.5 캐시 무효화

큰 변경 후 사용자 SW/캐시가 오염되면 `frontend-react/index.html`의 `CACHE_VER` 상수를 bump (예: `v3.0.2` → `v3.0.3`).

---

## 5. 스케줄러 (FIXED)

### 5.1 단일 데몬 원칙

- `scheduler.py --daemon` 인스턴스는 **PC당 정확히 1개**
- PID 파일: `logs/scheduler.pid`
- Watchdog: `logs/scheduler_watchdog.log` 가 살아있어야 함

### 5.2 현행 상태 확인

Windows MiniPC production은 Task `MarketFlow-Scheduler`만 사용한다. 아래는
읽기 전용 확인이며, 시작/종료/재등록은 별도 승인이 필요하다.

```powershell
Get-ScheduledTask -TaskName MarketFlow-Scheduler -ErrorAction SilentlyContinue
Get-ScheduledTaskInfo -TaskName MarketFlow-Scheduler -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*scheduler.py*--daemon*' } |
    Select-Object ProcessId,CreationDate
```

### 5.3 잡 스케줄 (KST)

| 시각 | Job Key | 명령 |
|---|---|---|
| 평일 04:00 | `us_market` | `--us-pro` |
| 평일 09:00 | `morning_report` | (텔레그램 모닝 리포트) |
| 평일 09:05 | `morning_briefing` | AI 조간 브리핑 (Gemini) |
| 평일 09:30 | `us_track` | `--us-track` |
| 평일 14:00 | `ai_chart` / `us_ai_chart` | `--ai-chart` / `--us-ai-chart` |
| 평일 15:00 | `kr_jongga` | `--kr-update` (종가베팅 V2) |
| 평일 16:00 | `vcp_all` | `--vcp` |
| 평일 16:00 | `wave_scan` | `--wave-scan` |
| 평일 17:00 | `closing_briefing` | (마감 브리핑) |
| 4시간마다 | `crypto` | `--crypto` |

### 5.4 Manifest

- 파일: `data/scheduler_last_run.json`
- 잡 완료 시 `_with_record()` 가 자동 기록 (daemon 모드만)
- **주의**: CLI `--us-pro` 등으로 직접 실행 시 manifest 갱신 안 됨 → 수동 sync 필요

---

## 6. Windows MiniPC production 검증 체크리스트

아래는 상태 확인만 수행한다. 재시작, task 재등록, tunnel 변경은 별도 승인이
필요하다.

```powershell
# 1. 경로
Test-Path C:\bitman_marketfloww\.venv\Scripts\python.exe
Test-Path C:\bitman_marketfloww\data\scheduler_last_run.json

# 2. 로컬 production Flask: 반드시 5003
Get-NetTCPConnection -State Listen -LocalAddress 127.0.0.1 -LocalPort 5003 -ErrorAction SilentlyContinue
Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 http://127.0.0.1:5003/healthz
Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 http://127.0.0.1:5003/api/health

# 3. Task Scheduler 계약
Get-ScheduledTask -TaskName MarketFlow-Flask,MarketFlow-Flask-Watchdog,MarketFlow-Scheduler,MarketFlow-Cloudflared,MarketFlow-Tunnel-Watchdog -ErrorAction SilentlyContinue

# 4. 프로세스와 공개 tunnel health
Get-Process -Name cloudflared -ErrorAction SilentlyContinue
Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 https://marketflow-api.bit-man.net/healthz
Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 https://marketflow-api.bit-man.net/api/health

# 5. 로그/manifest 신선도는 내용을 노출하지 않고 파일 metadata로 확인
Get-Item C:\bitman_marketfloww\logs\flask_task.control.log,C:\bitman_marketfloww\logs\flask_watchdog.log,C:\bitman_marketfloww\logs\tunnel_watchdog.log,C:\bitman_marketfloww\data\scheduler_last_run.json -ErrorAction SilentlyContinue | Select-Object FullName,LastWriteTime,Length
```

Local development only 확인은 별도로 수행한다:

```powershell
$env:FLASK_HOST='127.0.0.1'
$env:FLASK_PORT='5001'
.\.venv\Scripts\python.exe flask_app.py
```

---

## 7. 검증 알파 / OpenClaw 운영 핸드오프

- OpenClaw, 메인 PC 검증 Telegram, 향후 MiniPC 핸드오프의 커밋된 운영 정본은
  `skills/marketflow-openclaw-ops/`이다. 실제 사용자 스킬 설치는 해당 safe
  junction installer를 명시적으로 요청받은 경우에만 수행한다.
- 개발 Flask 기본 포트는 `5001`이다. 현행 Windows MiniPC launcher/watchdog
  계약은 `127.0.0.1:5003`이며, 기존 `5001` MiniPC helper script는 조정 전까지
  안전하지 않다. MCP HTTP는 `8765`이다.
- 현행 운영은 `C:\bitman_marketfloww` + Task Scheduler인 Windows이다.
  `/srv/marketflow`와 systemd는 future Linux target일 뿐이며, MarketFlow는
  Spring/`8080`을 절대 사용하지 않는다.

## 8. 변경 절차

이 문서를 변경할 때:

1. **이 파일을 먼저 수정**
2. 코드/설정을 이 파일에 맞춰 수정
3. 6번 검증 체크리스트 실행
4. `git commit -m "infra: <변경 요약>"`
5. 배포 영향과 남은 gate를 기록한다. 배포는 사용자가 별도로 명시적으로
   승인한 경우에만 해당 배포 절차를 실행한다.

이 파일과 다른 곳(CLAUDE.md, README, .env)이 충돌하면 **이 파일이 우선**이며 다른 곳을 이 파일에 맞춰 수정합니다.

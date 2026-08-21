# MarketFlow Infrastructure — Single Source of Truth

> **이 문서가 인프라의 단일 진실 소스(Single Source of Truth)입니다.**
> 어떤 코드/문서가 이 파일과 충돌하면 **이 파일이 옳고**, 코드를 이 파일에 맞춰 수정합니다.
> 변경 시 반드시 이 파일을 먼저 갱신하고 PR/커밋합니다.

Last updated: 2026-04-08

> **2026-04-08 정정**: 라이브 프로세스 검사 결과, 8080 포트는 MarketFlow 가 아닌 별도 프로젝트 JUST BUY (`C:\bitman_justbuy_project`) 의 `justbuy-api-1.0.0.jar` 가 점유하며 `api.bit-man.net` 도 JUST BUY 로 라우팅됨이 확인되었습니다. MarketFlow `backend/` 디렉토리는 dead code 로 분류하고, 8080 / Spring Boot 관련 항목을 SSOT 에서 제거했습니다. 미니PC 이전 시 MarketFlow 측 systemd unit 은 `marketflow-flask.service`, `marketflow-scheduler.service` 두 개만 만듭니다.

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
| Cloudflared 설정 | `C:\Users\dynas\.cloudflared\config.yml` | `/c/Users/dynas/.cloudflared/config.yml` |
| Cloudflared 자격 | `C:\Users\dynas\.cloudflared\678e9c60-9f8d-4f49-9fba-a49400ef4ca0.json` | 동일 |
| Crypto 분석 | `C:\bitman_marketfloww\crypto-analytics\crypto_market` | 동일 |

### 1.2 Linux (홈서버 이전 후 — 미니PC)

| 항목 | 절대 경로 (Linux) |
|---|---|
| 프로젝트 루트 | `/srv/marketflow` |
| Python venv | `/srv/marketflow/.venv/bin/python` |
| 데이터 디렉토리 | `/srv/marketflow/data` |
| 로그 디렉토리 | `/srv/marketflow/logs` |
| 프론트엔드 | `/srv/marketflow/frontend-react` |
| Cloudflared 설정 | `/etc/cloudflared/config.yml` |
| Cloudflared 자격 | `/etc/cloudflared/678e9c60-9f8d-4f49-9fba-a49400ef4ca0.json` |
| Crypto 분석 | `/srv/marketflow/crypto-analytics/crypto_market` |
| systemd unit | `/etc/systemd/system/marketflow-{flask,scheduler,backup}.service` |
| systemd timer | `/etc/systemd/system/marketflow-backup.timer` |
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

## 2. 홈서버 네트워크 (FIXED)

### 2.1 로컬 서비스 포트 (LAN/Localhost only)

| 포트 | 서비스 | 프로세스 | 시작 명령 | 외부 노출 |
|---|---|---|---|---|
| **5001** | Flask API (메인) | `flask_app.py` | `cd /c/bitman_marketfloww && PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe flask_app.py` | 터널 경유 (`marketflow-api.bit-man.net`) |
| **5173** | Vite dev (개발용) | `frontend-react` | `cd /c/bitman_marketfloww/frontend-react && npm run dev` | 로컬만 |
| **N/A** | Scheduler 데몬 | `scheduler.py --daemon` | `cd /c/bitman_marketfloww && PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scheduler.py --daemon` | 없음 (백그라운드 잡) |

**금지/외부 점유 포트**:
- `5002`: 구 cloudflared 잘못된 라우팅의 흔적, 사용 안 함
- `8080`: **MarketFlow가 사용하지 않음**. 이 PC에서는 별도 프로젝트(JUST BUY, `C:\bitman_justbuy_project`)의 Spring Boot JAR이 점유 중. MarketFlow `backend/` 디렉토리는 dead code이며, 실수로라도 `gradlew bootRun`을 띄우지 말 것 (JUST BUY와 충돌). JUST BUY의 `autostart.vbs`는 침범 시 자동 종료시키는 방어 로직(`KillStrayMarketflowOn8080`) 보유.

### 2.2 포트 점유 확인 / 종료

```bash
# 확인 (MarketFlow는 5001/5173만; 8080은 외부 프로젝트 점유라 무시)
netstat -ano | grep -E "LISTENING.*:(5001|5173) "

# 종료 (예: 5001)
netstat -ano | grep ":5001" | grep LISTEN | awk '{print $5}' | sort -u | xargs -I{} taskkill //F //PID {}
```

### 2.3 단일 인스턴스 보장

| 서비스 | PID 파일 | 락 메커니즘 |
|---|---|---|
| Scheduler | `logs/scheduler.pid` | PID 파일 + 포트 락 |
| Flask | (없음 — taskkill로 정리) | OS 포트 바인딩 |
| Cloudflared | (없음) | tunnel UUID 단일 |

---

## 3. Cloudflare Tunnel (FIXED)

### 3.1 터널 정보

| 항목 | 값 |
|---|---|
| Tunnel Name | `bitman-api` |
| Tunnel UUID | `678e9c60-9f8d-4f49-9fba-a49400ef4ca0` |
| Config | `C:\Users\dynas\.cloudflared\config.yml` |
| Credentials | `C:\Users\dynas\.cloudflared\678e9c60-9f8d-4f49-9fba-a49400ef4ca0.json` |
| 연결 수 | 4 (icn05 ×2, icn06 ×2) |

> **참고**: 같은 PC에 별도 프로젝트(JUST BUY)가 자기 터널(`justbuy-tunnel`)을 함께 운영합니다. MarketFlow 운영상 무관하므로 이 SSOT는 추적하지 않습니다.

### 3.2 라우팅 매트릭스 (MarketFlow 소속만)

| 외부 호스트 | → | 로컬 서비스 | 용도 |
|---|---|---|---|
| `https://marketflow-api.bit-man.net` | → | `http://localhost:5001` | Flask API (메인 전체) |
| (그 외 MarketFlow 호스트) | → | `http_status:404` | 차단 |

> `api.bit-man.net` 은 동일 config.yml 에 ingress 로 남아있지만 **JUST BUY 프로젝트의 :8080 JAR 로 라우팅** 됩니다. MarketFlow 코드/문서/배포에서 이 호스트를 호출하거나 재정의하지 마세요. config.yml 상의 의존성은 JUST BUY 측 변경 권한에 둡니다.

### 3.3 config.yml (현행 — JUST BUY 라인 포함)

```yaml
tunnel: 678e9c60-9f8d-4f49-9fba-a49400ef4ca0
credentials-file: C:\Users\dynas\.cloudflared\678e9c60-9f8d-4f49-9fba-a49400ef4ca0.json

ingress:
  - hostname: api.bit-man.net               # JUST BUY 소유 (MarketFlow 무관)
    service: http://localhost:8080
  - hostname: marketflow-api.bit-man.net    # MarketFlow Flask
    service: http://localhost:5001
  - service: http_status:404
```

### 3.4 운영 명령

```bash
# 시작
cloudflared tunnel --config "C:\Users\dynas\.cloudflared\config.yml" run 678e9c60-9f8d-4f49-9fba-a49400ef4ca0

# 종료 (전부)
taskkill //F //IM cloudflared.exe

# 헬스체크
curl -s -o /dev/null -w "Flask:  %{http_code}\n" https://marketflow-api.bit-man.net/api/kr/jongga-v2/latest
```

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

> 프론트엔드는 **모든 API 호출을 `marketflow-api.bit-man.net`(Flask) 로** 보냅니다. MarketFlow 에는 자체 Spring Boot 백엔드가 없으며, 모든 엔드포인트(KR/US/Crypto/Wave/Briefing 전부)는 Flask `:5001` 한 곳에서 서빙됩니다. `api.bit-man.net` 은 별도 프로젝트(JUST BUY) 소속이므로 호출 금지.

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
- Watchdog: `logs/watchdog_service.log` 가 살아있어야 함

### 5.2 시작/종료

```bash
# 시작
cd /c/bitman_marketfloww && PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scheduler.py --daemon &

# 종료
cat logs/scheduler.pid | xargs -I{} taskkill //F //PID {}
# 또는
taskkill //F //IM python.exe //FI "WINDOWTITLE eq scheduler*"
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

## 6. 검증 체크리스트 (5분 안에 인프라 상태 점검)

```bash
# 1. 경로
ls /c/bitman_marketfloww/.venv/Scripts/python.exe && echo "[OK] Python venv"
ls /c/bitman_marketfloww/data/scheduler_last_run.json && echo "[OK] Manifest"

# 2. 로컬 포트
netstat -ano | grep -q ":5001.*LISTENING" && echo "[OK] Flask 5001" || echo "[FAIL] Flask 5001"

# 3. 스케줄러
test -f /c/bitman_marketfloww/logs/scheduler.pid && echo "[OK] Scheduler PID" || echo "[FAIL] Scheduler PID"
PID=$(cat /c/bitman_marketfloww/logs/scheduler.pid 2>/dev/null)
tasklist | grep -q "$PID" && echo "[OK] Scheduler alive" || echo "[FAIL] Scheduler dead"

# 4. 터널
tasklist | grep -qi cloudflared && echo "[OK] Cloudflared running" || echo "[FAIL] Cloudflared dead"

# 5. 외부 도달
curl -s -o /dev/null -w "[%{http_code}] Flask via tunnel\n" https://marketflow-api.bit-man.net/api/kr/jongga-v2/latest
curl -s -o /dev/null -w "[%{http_code}] Frontend\n" https://bit-man.net/

# 6. Manifest 신선도 (24h 이내)
node -e "const d=require('/c/bitman_marketfloww/data/scheduler_last_run.json');const now=Date.now();for(const[k,v]of Object.entries(d)){const age=(now-new Date(v).getTime())/3600e3;console.log(\`\${age>24?'[STALE]':'[OK]'} \${k}: \${age.toFixed(1)}h\`)}"
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
5. 변경된 것이 배포 영향 있으면 4.2 명령으로 재배포

이 파일과 다른 곳(CLAUDE.md, README, .env)이 충돌하면 **이 파일이 우선**이며 다른 곳을 이 파일에 맞춰 수정합니다.

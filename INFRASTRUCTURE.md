# MarketFlow Infrastructure — Single Source of Truth

> **이 문서가 인프라의 단일 진실 소스(Single Source of Truth)입니다.**
> 어떤 코드/문서가 이 파일과 충돌하면 **이 파일이 옳고**, 코드를 이 파일에 맞춰 수정합니다.
> 변경 시 반드시 이 파일을 먼저 갱신하고 PR/커밋합니다.

Last updated: 2026-04-07

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
| 백엔드 (Spring) | `C:\bitman_marketfloww\backend` | `/c/bitman_marketfloww/backend` |
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
| 백엔드 (Spring) | `/srv/marketflow/backend` |
| Cloudflared 설정 | `/etc/cloudflared/config.yml` |
| Cloudflared 자격 | `/etc/cloudflared/678e9c60-9f8d-4f49-9fba-a49400ef4ca0.json` |
| Crypto 분석 | `/srv/marketflow/crypto-analytics/crypto_market` |
| systemd unit | `/etc/systemd/system/marketflow-{flask,scheduler,spring}.service` |

**OS 분기 패턴**:
- Python: `Path(__file__).resolve().parent` 기준 상대 계산 (모든 모듈)
- `scheduler.py` `Config.PYTHON_PATH`: `os.name == 'nt'` 분기 (`.venv/Scripts/python.exe` vs `.venv/bin/python`)
- Spring Boot: `application.yml`의 `${APP_BASE_DIR:C:/bitman_marketfloww}` env var로 오버라이드 (Linux는 systemd unit에서 `Environment=APP_BASE_DIR=/srv/marketflow`)
- Cloudflared: 사용자 홈 의존 제거, `/etc/cloudflared/`로 시스템 영역 이동
- `healthcheck.py`: **Windows 전용** (`tasklist`/`wmic`/`CREATE_NO_WINDOW`). Linux에서는 systemd `Restart=on-failure`가 동일 역할 수행 — Linux에서 호출 금지

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
| **8080** | Spring Boot API (Summary 3종) | `backend/` | `cd /c/bitman_marketfloww/backend && ./gradlew bootRun` | 터널 경유 (`api.bit-man.net`) |
| **5173** | Vite dev (개발용) | `frontend-react` | `cd /c/bitman_marketfloww/frontend-react && npm run dev` | 로컬만 |
| **N/A** | Scheduler 데몬 | `scheduler.py --daemon` | `cd /c/bitman_marketfloww && PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scheduler.py --daemon` | 없음 (백그라운드 잡) |

**금지 포트**: `5002` (구 cloudflared 잘못된 라우팅의 흔적, 이제 사용 안 함)

### 2.2 포트 점유 확인 / 종료

```bash
# 확인
netstat -ano | grep -E "LISTENING.*:(5001|8080|5173) "

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

### 3.2 라우팅 매트릭스 (FIXED)

| 외부 호스트 | → | 로컬 서비스 | 용도 |
|---|---|---|---|
| `https://api.bit-man.net` | → | `http://localhost:8080` | Spring Boot (Summary 대시보드 3 엔드포인트) |
| `https://marketflow-api.bit-man.net` | → | `http://localhost:5001` | Flask API (메인 전체) |
| (그 외) | → | `http_status:404` | 차단 |

### 3.3 config.yml (정본)

```yaml
tunnel: 678e9c60-9f8d-4f49-9fba-a49400ef4ca0
credentials-file: C:\Users\dynas\.cloudflared\678e9c60-9f8d-4f49-9fba-a49400ef4ca0.json

ingress:
  - hostname: api.bit-man.net
    service: http://localhost:8080
  - hostname: marketflow-api.bit-man.net
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
curl -s -o /dev/null -w "Spring: %{http_code}\n" https://api.bit-man.net/api/us/market-briefing
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

> 프론트엔드는 **모든 API 호출을 `marketflow-api.bit-man.net`(Flask) 로** 보냅니다. Spring Boot의 3개 엔드포인트는 Flask가 프록시하거나, 별도 분기 시 `api.bit-man.net`으로 보내야 합니다.

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
netstat -ano | grep -q ":8080.*LISTENING" && echo "[OK] Spring 8080" || echo "[FAIL] Spring 8080"

# 3. 스케줄러
test -f /c/bitman_marketfloww/logs/scheduler.pid && echo "[OK] Scheduler PID" || echo "[FAIL] Scheduler PID"
PID=$(cat /c/bitman_marketfloww/logs/scheduler.pid 2>/dev/null)
tasklist | grep -q "$PID" && echo "[OK] Scheduler alive" || echo "[FAIL] Scheduler dead"

# 4. 터널
tasklist | grep -qi cloudflared && echo "[OK] Cloudflared running" || echo "[FAIL] Cloudflared dead"

# 5. 외부 도달
curl -s -o /dev/null -w "[%{http_code}] Flask via tunnel\n" https://marketflow-api.bit-man.net/api/kr/jongga-v2/latest
curl -s -o /dev/null -w "[%{http_code}] Spring via tunnel\n" https://api.bit-man.net/api/us/market-briefing
curl -s -o /dev/null -w "[%{http_code}] Frontend\n" https://bit-man.net/

# 6. Manifest 신선도 (24h 이내)
node -e "const d=require('/c/bitman_marketfloww/data/scheduler_last_run.json');const now=Date.now();for(const[k,v]of Object.entries(d)){const age=(now-new Date(v).getTime())/3600e3;console.log(\`\${age>24?'[STALE]':'[OK]'} \${k}: \${age.toFixed(1)}h\`)}"
```

---

## 7. 변경 절차

이 문서를 변경할 때:

1. **이 파일을 먼저 수정**
2. 코드/설정을 이 파일에 맞춰 수정
3. 6번 검증 체크리스트 실행
4. `git commit -m "infra: <변경 요약>"`
5. 변경된 것이 배포 영향 있으면 4.2 명령으로 재배포

이 파일과 다른 곳(CLAUDE.md, README, .env)이 충돌하면 **이 파일이 우선**이며 다른 곳을 이 파일에 맞춰 수정합니다.

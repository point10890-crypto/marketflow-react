# MarketFlow 홈서버 이전(Migration) 전수 조사 보고서

> 작성일: 2026-04-08 (1차) / 정정: 2026-04-08 (2차)
> 대상: 현 운영 호스트 → 전용 로컬 홈서버(미니PC) 교체
> 목적: 24/7 안정 운용 + 전력 효율 + 노트북 해방
>
> **⚠ 2026-04-08 정정**: 1차 작성 시 8080 / Spring Boot / `api.bit-man.net` 이 MarketFlow 소속이라 잘못 가정했습니다. 라이브 프로세스 검사 결과 **8080 은 별도 프로젝트(JUST BUY) 소속**이며, MarketFlow `backend/` 디렉토리는 운영 배포된 적 없는 dead code 입니다. MarketFlow 의 실제 운영 컴포넌트는 **Flask(5001) + scheduler.py + cloudflared(`marketflow-api.bit-man.net`) + Vite(개발만)** 4가지입니다. 본 문서 §2 표 / §4 systemd unit / §6 헬스체크 등에서 8080·Spring Boot 가정은 무효화되었으므로 미니PC 이전 시 따르지 마세요.

---

## 0. 결론 한 줄

현재 시스템은 **노트북(ROG Strix G18)** 위에서 12개+ 프로세스로 24/7 돌아가는 구조입니다. **Linux 미니PC(N100/N305 또는 i5-13500급)** 로 옮기면 전력 1/4·소음 0·배터리 손상 0·재부팅 안정성 ↑ 가 가능합니다. **단, 코드·설정 곳곳에 박혀 있는 Windows 절대 경로(`C:\bitman_marketfloww\...`)와 `cloudflared` 사용자 홈 의존이 1차 장애물**이라 코드 수정 없이는 그대로 옮길 수 없습니다. 본 보고서는 그 1차 장애물을 포함한 모든 마이그레이션 항목을 전수 정리합니다.

---

## 1. 현 운영 환경 (As-Is) 실측

### 1.1 호스트 하드웨어
| 항목 | 값 |
|---|---|
| 제조사/모델 | ASUSTeK ROG Strix G18 G814JVR |
| CPU | Intel Core i9-14900HX (24c / 32t) |
| RAM | 32 GB |
| OS | Windows 11 Home (10.0.26200) |
| 형태 | **노트북** (배터리·발열·이동성 → 24/7 서버 부적합) |

### 1.2 디스크 사용량
| 경로 | 크기 | 비고 |
|---|---|---|
| `C:\bitman_marketfloww\` (전체) | **1.9 GB** | 코드+데이터+venv |
| `data/` | 294 MB | 운영 데이터 |
| `data/daily_prices.csv` | 136 MB | KR 일별 가격 (단일 파일) |
| `data/prices/` | 117 MB | 종목별 가격 캐시 |
| `data/wave/` | 15 MB | W 패턴 추적 |
| `data/users.db` (+wal) | 2.5 + 3.2 MB | SQLite 유저 DB |
| `data/marketflow.mv.db` | 1.7 MB | H2 (구 Spring Boot 시도의 잔재 — dead, 이전 불필요) |
| `logs/` | 40 MB | 런타임 로그 |
| `crypto-analytics/` | 8.2 MB | 크립토 분석 산출물 |
| `frontend-react/dist/` | 2.1 MB | 빌드 산출물 (배포용) |

→ **이전해야 할 실데이터는 약 350 MB.** 코드·venv·node_modules는 새로 설치하면 됨.

### 1.3 살아 있는 프로세스 (현재 시점)
| 프로세스 | 개수 | 역할 |
|---|---|---|
| `cloudflared.exe` | **12+** | Cloudflare Tunnel 커넥터 (icn05·icn06 ×4 + 자식) |
| `python.exe / python3.13.exe` | 4 | Flask 5001 + scheduler 데몬 |
| `node.exe` | 4 | Vite dev / wrangler |
| ~~`java` (Spring Boot 8080)~~ | — | **MarketFlow 와 무관** — 같은 호스트의 별도 프로젝트(JUST BUY)가 8080 점유 |

### 1.4 서비스 매트릭스
| 포트 | 서비스 | 진입점 | 외부 노출 |
|---|---|---|---|
| 5001 | Flask API (메인) | `flask_app.py` | `marketflow-api.bit-man.net` (Cloudflare Tunnel) |
| 5173 | Vite dev | `frontend-react/` | 로컬만 |
| - | Scheduler 데몬 | `scheduler.py --daemon` | 없음 (cron-like) |
| - | Cloudflared | `C:\Users\dynas\.cloudflared\config.yml` | UUID `678e9c60-...` |

> 8080 / `api.bit-man.net` 은 같은 호스트의 별도 프로젝트(JUST BUY) 점유. 미니PC 이전 작업에서는 MarketFlow 만 옮기고 8080 자산은 손대지 마세요.

### 1.5 외부 의존성
- **API 키 19종** (`.env`): GEMINI / GOOGLE / OPENAI / PERPLEXITY / ANTHROPIC / XAI / DART / FMP / KIS(4종) / TELEGRAM(4종) / GITHUB(2종)
- **Python 패키지** 49 라인 (`requirements.txt`)
- **외부 도메인 (MarketFlow 소속만)**: `bit-man.net`, `www.bit-man.net`, `marketflow-api.bit-man.net` (Cloudflare 관리). `api.bit-man.net` 은 JUST BUY 소속이므로 본 마이그레이션 범위 외.
- **프론트엔드**: Cloudflare Pages 프로젝트 `bitman-marketflow` (이전 시 영향 없음 — 호스트 외부)

### 1.6 스케줄러 잡 (KST)
| 시각 | Job | 수단 |
|---|---|---|
| 평일 04:00 | `us_market` (--us-pro) | scheduler.py 데몬 |
| 평일 09:00 | `morning_report` (텔레그램) | 〃 |
| 평일 09:05 | `morning_briefing` (Gemini) | 〃 |
| 평일 09:30 | `us_track` | 〃 |
| 평일 14:00 | `ai_chart` / `us_ai_chart` | 〃 |
| 평일 15:00 | `kr_jongga` (--kr-update) | 〃 |
| 평일 16:00 | `vcp_all` + `wave_scan` | 〃 |
| 평일 17:00 | `closing_briefing` | 〃 |
| 4시간마다 | `crypto` | 〃 |

→ **단일 PC당 정확히 1개의 데몬 인스턴스** 원칙 (PID 파일 `logs/scheduler.pid`).

---

## 2. 왜 옮겨야 하는가 (Why)

| 항목 | 현재 (노트북) | 미니PC 홈서버 |
|---|---|---|
| **전력 (idle)** | 50~80 W | 8~25 W (N100 ~10W, i5-T 25W) |
| **전력 (peak)** | 150~200 W | 35~65 W |
| **연 전기료(24h, 280 W·h 평균 가정)** | ≈ 60,000 원 | ≈ 15,000 원 |
| **소음** | 팬 RPM 가변, 작업시 큼 | 팬리스(N100) 또는 저소음 |
| **배터리** | 24/7 충전 → 1년 내 스웰링/수명↓ | 없음 |
| **재부팅 안정성** | Windows Update 강제 재부팅 → 스케줄러·터널 장애 | Linux unattended-upgrades + 의도된 리부트 |
| **단일 인스턴스 격리** | 일반 데스크탑 작업과 혼재 | 헤드리스 전용기 |
| **물리 보안** | 노트북 휴대·도난 위험 | 고정 |
| **이동/출장 시** | 서비스 중단 | 무관 |
| **부팅 시 자동 기동** | 작업스케줄러+vbs (현재도 일부) | systemd unit (정석) |
| **노트북 본업 영향** | RAM 32GB 중 ~10GB 고정 점유 | 노트북은 개발 전용으로 해방 |

→ **결정적 트리거**: 노트북 배터리·OS Update·이동성 충돌 3가지가 운영 사고의 70%를 차지함.

---

## 3. 1차 장애물 — 코드 수준 Windows 의존

INFRASTRUCTURE.md가 절대 경로를 **FIXED**로 못박고 있어, 그대로 Linux로 옮기면 **전혀 동작하지 않습니다**. 다음 항목 전부 손봐야 합니다.

### 3.1 하드코딩 절대 경로
| 위치 | 현재 | Linux 대응 |
|---|---|---|
| `INFRASTRUCTURE.md` | `C:\bitman_marketfloww` | `/srv/marketflow` (제안) |
| Python venv | `C:\bitman_marketfloww\.venv\Scripts\python.exe` | `/srv/marketflow/.venv/bin/python` |
| Cloudflared config | `C:\Users\dynas\.cloudflared\config.yml` | `/etc/cloudflared/config.yml` |
| Cloudflared 자격 | `C:\Users\dynas\.cloudflared\<UUID>.json` | `/etc/cloudflared/<UUID>.json` |
| `app/utils/paths.py` | `BASE_DIR`, `DATA_DIR` 등 | `__file__` 기준 (이미 일부 적용됨 — 검증 필요) |
| `scheduler.py` `Config` | `__file__` 기반 + env 오버라이드 | OK (POSIX 호환 확인만) |
| `engine/` 모듈 | `os.path.dirname(os.path.abspath(__file__))` | OK |

### 3.2 인코딩·플랫폼 차이
- `PYTHONIOENCODING=utf-8` 강제 → Linux는 기본 utf-8이라 불필요하지만 명시 유지 OK
- 경로 구분자: `os.path.join` / `pathlib.Path` 강제, 슬래시 하드코딩 검사 필요
- `taskkill //F //PID` 류 Windows 전용 → systemd/`kill`로 교체
- `cp949` 관련 워크어라운드 코드 → 유지(데이터 자체에 한자/CP949가 끼어 있을 수 있음)

### 3.3 사용자 홈 의존
- Cloudflared가 `C:\Users\dynas\.cloudflared\`에 자격증명 두는 패턴 → Linux는 `/etc/cloudflared/` 시스템 영역으로 옮기고 systemd 유닛으로 운영하는 게 정석.

### 3.4 Windows 작업 스케줄러·vbs·bat
- `tools/start_v1_flask.bat` 등 → systemd unit으로 1:1 대응
- `autostart.vbs` 워치독 → systemd `Restart=on-failure`로 흡수
- `taskkill` 의존 종료 → `systemctl stop`

### 3.5 ~~Spring Boot~~ (제외)
MarketFlow `backend/` Spring Boot 디렉토리는 운영 배포된 적이 없는 dead code 입니다. 미니PC 이전 시 빌드/배포/Java 설치 모두 불필요. 같은 호스트의 8080 자산은 별도 프로젝트(JUST BUY) 소속이므로 본 마이그레이션 범위 외.

---

## 4. 권장 하드웨어 (3 옵션)

### 옵션 A — 초저전력 / 팬리스 (★ 가성비 최강 추천)
**Intel N100 또는 N305 미니PC** (Beelink S12 Pro / Mini PC EQ12 / GMKtec G3 등)
| 항목 | 값 |
|---|---|
| CPU | Intel N100 (4c/4t, 6W TDP) 또는 N305 (8c/8t, 15W) |
| RAM | DDR4/DDR5 16 GB (32GB 권장) |
| 저장 | NVMe 512 GB + SATA 1 TB (백업) |
| 전력 idle/peak | **6/20 W** |
| 가격대 | 25~40만원 |
| 장점 | 팬리스(N100) 또는 초저소음, 손바닥 크기, 24/7 적합 |
| 단점 | 단일 코어 성능 낮음 (Python/Vite 런타임에는 무리 없음) |

→ **MarketFlow 워크로드(scheduler.py + Flask + cloudflared)** 는 평시 1~2 vCPU 활용. N100으로 충분.

### 옵션 B — 균형 (개발도 같이 할 거면)
**Intel i5-13500T / i5-12500T 미니PC** (Beelink SEi13 / NUC 13 Pro / Minisforum UM773)
| 항목 | 값 |
|---|---|
| CPU | i5-13500T (14c/20t, 35W TDP) |
| RAM | 32 GB DDR5 |
| 저장 | NVMe 1 TB + SATA 2 TB |
| 전력 idle/peak | 15/65 W |
| 가격대 | 60~90만원 |
| 장점 | Gradle/Vite 빌드 빠름, 헤드리스+가벼운 데스크탑 겸용 가능 |
| 단점 | 팬 있음 (대부분 저소음) |

### 옵션 C — 확장형 (NAS 통합 + DB 분리 미래 대응)
**미니ITX 자작 / Synology DS923+ + 별도 미니PC**
| 항목 | 값 |
|---|---|
| 구성 | DS923+(NAS, RAID) + N100 미니PC (앱) |
| 가격 | 100만원+ |
| 장점 | RAID 데이터 보호, Docker 컨테이너 분리 운영 |
| 단점 | 비용·복잡도↑, 현 단계 과투자 |

**최종 권장: 옵션 A (N305 16GB+512GB NVMe).** 현 데이터 350MB·평시 부하 낮음·전력 최우선.

---

## 5. 권장 OS·런타임 스택

| 레이어 | 선택 | 이유 |
|---|---|---|
| **OS** | **Debian 12 / Ubuntu Server 24.04 LTS** | 5년 보안 업데이트, 한국 미러 빠름, systemd 표준 |
| **방화벽** | `ufw` | 포트 5001 LAN-only, 22 SSH key-only (8080 은 MarketFlow 와 무관) |
| **자동 패치** | `unattended-upgrades` | 보안 패치만 자동, 커널 재부팅은 새벽 4:30 사전예약 |
| **프로세스 매니저** | **systemd unit** | Restart=on-failure, journalctl 로그 통합 |
| **Python** | **3.13** + `uv` (또는 venv) | uv가 pip 대비 10~100배 빠름 |
| **Node** | **20 LTS** (nvm) | Vite 5 호환 (Java 는 MarketFlow 운영에 불필요 — backend/ dead code) |
| **Cloudflared** | apt repo 정식 | systemd 통합, 자동 업데이트 |
| **모니터링** | journalctl + Telegram 알림 (기존 유지) | 추가 인프라 0 |
| **백업** | `restic` → 외장 USB or 클라우드 | 증분 백업, 암호화 |
| **컨테이너** | (선택) Docker Compose | docker-compose.yml 이미 존재(postgres+redis 정의됨, 현재 unused) |

---

## 6. 타깃 디렉토리 레이아웃 (Linux)

```
/srv/marketflow/                  ← 프로젝트 루트 (BASE_DIR)
├── .venv/                        ← uv venv
├── .env                          ← 600 권한, marketflow:marketflow 소유
├── flask_app.py
├── scheduler.py
├── app/  engine/  frontend-react/  ...   (backend/ 는 dead code, 이전 시 빌드/실행 안 함)
├── data/                         ← 750 권한, 백업 대상
└── logs/                         ← journalctl 외 보조 로그

/etc/cloudflared/
├── config.yml
└── 678e9c60-9f8d-4f49-9fba-a49400ef4ca0.json   ← 600 권한, root:cloudflared

/etc/systemd/system/
├── marketflow-flask.service
├── marketflow-scheduler.service
└── cloudflared.service           ← 패키지 설치 시 자동
```

전용 시스템 사용자 `marketflow` (UID 1500, no-login) 생성 후 `/srv/marketflow` 소유.

---

## 7. systemd 유닛 정본 (예시)

### 7.1 Flask
```ini
# /etc/systemd/system/marketflow-flask.service
[Unit]
Description=MarketFlow Flask API
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=marketflow
Group=marketflow
WorkingDirectory=/srv/marketflow
EnvironmentFile=/srv/marketflow/.env
Environment=PYTHONIOENCODING=utf-8
ExecStart=/srv/marketflow/.venv/bin/python flask_app.py
Restart=on-failure
RestartSec=5
StandardOutput=append:/srv/marketflow/logs/flask.log
StandardError=append:/srv/marketflow/logs/flask.err

[Install]
WantedBy=multi-user.target
```

### 7.2 Scheduler
```ini
# /etc/systemd/system/marketflow-scheduler.service
[Unit]
Description=MarketFlow Scheduler Daemon
After=marketflow-flask.service
Requires=marketflow-flask.service

[Service]
Type=simple
User=marketflow
WorkingDirectory=/srv/marketflow
EnvironmentFile=/srv/marketflow/.env
ExecStart=/srv/marketflow/.venv/bin/python scheduler.py --daemon
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### 7.3 ~~Spring Boot~~ (제외)

**MarketFlow 는 Spring Boot 백엔드를 운영하지 않습니다.** repo 안의 `backend/` 디렉토리는 dead code 이며 미니PC 에 systemd unit 을 만들지 마세요. 같은 호스트의 8080 자산은 별도 프로젝트(JUST BUY) 가 점유하므로 본 마이그레이션 범위 외입니다.

→ `systemctl enable --now marketflow-flask marketflow-scheduler` (2 unit 만)

---

## 8. 마이그레이션 절차 (T-day 플레이북)

### Phase 0 — 사전 준비 (D-7 ~ D-1, 노트북 위에서)
1. 미니PC 발주·수령·OS 설치 (Debian 12 minimal)
2. SSH key 등록, `ufw` 설정 (22/LAN, 5001/LAN — 8080 은 MarketFlow 가 사용하지 않으므로 열지 않음)
3. 사용자 `marketflow` 생성 + `/srv/marketflow` 디렉토리
4. Python 3.13 / Node 20 / cloudflared 설치 (Java 는 MarketFlow 운영에 불필요)
5. **코드 수정 PR**: `INFRASTRUCTURE.md`에 Linux 경로 섹션 추가, `paths.py` 검증, batch/vbs 의존 제거 — **이 단계에서 노트북에서 동작 회귀 테스트** (POSIX/Windows 동시 호환 유지)

> **⚠ 절대 복사 금지 (per-machine 로컬 파일)** — 다음 파일들은 새 호스트에서 자연스럽게 재생성되어야 함. 복사하면 구 PC 경로 참조로 깨짐:
> - `.claude/settings.local.json` — Claude Code 로컬 권한 allowlist (호스트별 하드코딩 경로 포함)
> - `.venv/` — 심링크/절대경로 의존. 반드시 미니PC에서 `uv venv` 로 새로 생성
> - `logs/scheduler.pid` — PID 파일. 없는 상태에서 daemon 기동해야 정상 싱글톤 락 동작
> - `data/kis_token_cache.json` — 복사해도 무방하나, 첫 기동 시 lazy refresh 로 재발급되므로 필수 아님

### Phase 1 — 데이터 베이스라인 동기 (D-day, 1시간)
1. 노트북에서 **`scheduler.py` 일시 정지** (`taskkill //F //IM cloudflared.exe`는 아직 X)
2. `git fetch && git status` 깨끗한지 확인 → 더티 파일 커밋
3. `data/` 압축: `tar czf marketflow_data_$(date +%Y%m%d).tgz data/ logs/ .env`
4. `scp` 로 미니PC `/srv/marketflow/`에 전송
5. 미니PC에서 `git clone` (또는 위 tarball에 코드 포함) → `uv venv && uv pip install -r requirements.txt`
6. 권한: `chown -R marketflow:marketflow /srv/marketflow && chmod 600 .env`

### Phase 2 — 평행 가동 (D-day, 30분)
1. 미니PC: Flask·Scheduler systemd 유닛 enable → start
2. **localhost 헬스체크**:
   ```
   curl http://localhost:5001/api/kr/jongga-v2/latest
   ```
3. 노트북은 계속 살려둠 — Cloudflare Tunnel은 아직 노트북 향해 있음

### Phase 3 — 터널 전환 (D-day, 5분 윈도)

> ⚠ 주의: 같은 호스트에서 별도 프로젝트(JUST BUY)도 같은 cloudflared 터널을 공유할 가능성이 높습니다. JUST BUY 도 미니PC 로 함께 이전하지 않는 한 노트북측 cloudflared 를 끄면 JUST BUY 까지 끊깁니다. 본 문서는 MarketFlow 단독 이전을 다루므로, 터널 전환 전 JUST BUY 측 영향과 ingress 분리 방안을 별도 검토하세요.

1. 노트북: `taskkill //F //IM cloudflared.exe` → 터널 끊김 (5초) — **JUST BUY 에 영향 줄 수 있음**
2. 미니PC: `systemctl start cloudflared` (config.yml + UUID json은 사전 복사됨, ingress 는 `marketflow-api.bit-man.net` 만 포함)
3. **외부 헬스체크**:
   ```
   curl https://marketflow-api.bit-man.net/api/kr/jongga-v2/latest
   curl https://bit-man.net/
   ```
4. 21개 dashboard 라우트 PC + 모바일 walk

### Phase 4 — 노트북 정리 (D-day +1)
1. 노트북: 모든 marketflow 작업 스케줄러 항목 Disable
2. `.venv` 보존(개발용), 데이터·로그는 ro 마운트로만
3. 노트북 `git pull` 가능하게 두되 push는 미니PC가 정본

### Phase 5 — 백업·모니터링 (D-day +1 ~)
1. `restic init` → 외장 USB or B2 버킷
2. 일 1회 `restic backup /srv/marketflow/data /srv/marketflow/.env`
3. `journalctl -u marketflow-* --since "1 hour ago"` 알림 텔레그램 푸시 스크립트
4. `unattended-upgrades` 활성 (보안만)

### 롤백 (5분 내)
1. 미니PC: `systemctl stop cloudflared`
2. 노트북: `cloudflared tunnel run 678e9c60-...` 재기동
3. 미니PC marketflow systemd 정지
4. 외부 헬스체크 → 노트북 복귀 확인

---

## 9. 위험·완화

| 위험 | 영향 | 완화 |
|---|---|---|
| 코드 내 Windows 경로 누락 | 서비스 기동 실패 | Phase 0에서 grep 전수 + 노트북 회귀 테스트 |
| `.env` 누락/오탈자 | API 401, 텔레그램 침묵 | Phase 1 전송 후 `python -c "import os; from dotenv import load_dotenv; load_dotenv(); [print(k, bool(os.getenv(k))) for k in [...]]"` 검증 |
| Cloudflared UUID 충돌 (이중 기동) | 터널 라우팅 오락가락 | Phase 3 전환 시 노트북 cloudflared 100% 종료 후 미니PC 기동 |
| 시간대(KST) 미설정 | 스케줄러 9시간 어긋남 | `timedatectl set-timezone Asia/Seoul` |
| 한글 로케일 미설치 | 한자/한글 깨짐 | `locale-gen ko_KR.UTF-8` |
| sqlite WAL 손상 | 유저 로그인 깨짐 | Phase 1에서 Flask 정지 후 복사, `users.db-wal` 동시 복사 |
| FinanceDataReader 외부 호출 차단 | KR market-gate 500 | 이미 stale-fallback 적용됨 |
| KIS API IP 화이트리스트 | KIS 호출 거부 | 모의/실전 둘 다 IP 등록 필요 — KIS 개발자센터에서 미니PC 공인IP 추가 |
| 미니PC 디스크 단일 (RAID 없음) | 디스크 사망 시 데이터 손실 | restic 외장 백업 + git 정본 |
| Windows Update 노트북 → 자동 재부팅 | 롤백 시 5분 윈도 깨짐 | D-day 직전 일시 일시정지 |
| 정전 | 서비스 다운 | UPS(APC BE600M1, 5만원대) 또는 미니PC 자동 부팅 BIOS 옵션 |
| 공유기 포트포워딩 변경 | 영향 없음 (Cloudflare Tunnel 사용 — outbound only) | - |

---

## 10. 메트릭 목표 (이전 후 4주 관측)

| 지표 | 현재 (노트북) | 목표 (미니PC) |
|---|---|---|
| **uptime** | 주 1~2회 재부팅 | **30일+ 무중단** |
| **idle 전력** | 50~80 W | **< 25 W** |
| **스케줄러 잡 누락률** | 약 5% (Update/슬립) | **< 0.5%** |
| **외부 헬스체크 24h 성공률** | ~98% | **> 99.9%** |
| **수동 개입 빈도** | 주 1회+ | **월 1회 미만** |
| **노트북 RAM 점유 해방** | ~10 GB | **0 GB** |
| **노트북 배터리 사이클** | 매일 충전 | **사용 시에만** |

---

## 11. 비용 요약 (옵션 A 기준)

| 항목 | 비용 |
|---|---|
| Beelink/GMKtec N100/N305 미니PC (16GB+512GB) | 30만원 |
| RAM 16GB 추가 (총 32GB, 선택) | 5만원 |
| 외장 SSD 1TB (백업) | 10만원 |
| UPS APC 600VA | 5만원 |
| 랜케이블·전원어댑터 등 | 1만원 |
| **합계** | **약 51만원** |
| 회수 기간 (전기료 절감만, 60→15천원/년) | 약 11년 ← **금전 회수가 목적이 아님** |
| **진짜 ROI** | 노트북 해방 + 운영 사고↓ + 24/7 안정성 |

---

## 12. 결정 지점 (사용자 승인 필요)

1. **하드웨어 옵션 선택**: A(N100/N305 30만원, 추천) / B(i5-T 70만원) / C(NAS 통합 100만+)
2. **OS 선택**: Debian 12 (안정) vs Ubuntu Server 24.04 LTS (한국 자료 많음) — 기본 추천 **Debian 12**
3. **프로젝트 경로**: `/srv/marketflow` (제안) vs `/opt/marketflow` vs `/home/marketflow/app`
4. **백업 대상**: 외장 USB SSD 단독 vs Backblaze B2 클라우드 vs 양쪽
5. **D-day 윈도**: 주말 새벽(권장) vs 평일 장 마감 후
6. **코드 수정 우선**: 본 보고서 §3 항목들을 별도 PR로 먼저 정리할지, D-day 당일 일괄 처리할지

승인 주시면 **Phase 0 코드 수정 PR (Windows/Linux 동시 호환)** 부터 즉시 착수합니다.

---

## 13. 부록 — 즉시 실행 가능한 사전 점검 명령

미니PC 받기 전에 노트북에서 미리 돌려볼 수 있는 사전 검사:

```bash
# A. Windows 절대 경로 하드코딩 grep
cd /c/bitman_marketfloww
grep -rn "C:\\\\bitman_marketfloww\|C:/bitman_marketfloww" --include="*.py" --include="*.md" --include="*.json" --include="*.yml" .

# B. cloudflared 사용자 홈 의존 grep
grep -rn "Users\\\\dynas\|.cloudflared" --include="*.py" --include="*.md" .

# C. taskkill / .bat / .vbs 의존 위치
grep -rn "taskkill\|\.bat\|\.vbs" --include="*.py" --include="*.md" .

# D. .env 키 누락 체크
.venv/Scripts/python.exe -c "
from dotenv import dotenv_values
keys = ['GEMINI_API_KEY','OPENAI_API_KEY','PERPLEXITY_API_KEY','ANTHROPIC_API_KEY','DART_API_KEY','FMP_API_KEY','XAI_API_KEY','KIS_APP_KEY','KIS_APP_SECRET','KIS_CANO','TELEGRAM_BOT_TOKEN','TELEGRAM_CHAT_ID']
v = dotenv_values('.env')
for k in keys: print(f'{k:30} {\"OK\" if v.get(k) else \"MISSING\"}')"

# E. 데이터 백업 사이즈 미리 계산
tar czf - data logs .env 2>/dev/null | wc -c | awk '{printf \"%.1f MB\\n\", $1/1024/1024}'
```

이 5개를 미리 돌려서 문제 항목을 잡아두면 D-day 윈도가 깨질 위험이 줄어듭니다.

---

*— 보고서 끝 —*

# MarketFlow systemd units (Linux 홈서버용)

이 디렉토리의 `.service` 파일은 **Linux 미니PC 홈서버** 이전 시 사용합니다.
Windows 운영 환경에는 영향 없음 (참고용 파일).

## 포함된 유닛

| 파일 | 설명 | 의존성 |
|---|---|---|
| `marketflow-flask.service` | Flask API (port 5001) | network-online |
| `marketflow-scheduler.service` | Scheduler 데몬 | marketflow-flask |
| `marketflow-spring.service` | Spring Boot (port 8080) | network-online |

> Cloudflared는 `apt install cloudflared` 시 자동 생성되는 `cloudflared.service` 사용.

## 설치 (D-day 플레이북)

```bash
# 1. 사용자/디렉토리 준비
sudo useradd --system --home /srv/marketflow --shell /usr/sbin/nologin marketflow
sudo mkdir -p /srv/marketflow/logs
sudo chown -R marketflow:marketflow /srv/marketflow

# 2. 코드/데이터 배치 (rsync 또는 git clone + tar 복원)
sudo -u marketflow git clone <repo> /srv/marketflow
# .env, data/ 는 별도 안전 전송

# 3. Python venv (uv 권장)
sudo -u marketflow bash -c "
  cd /srv/marketflow
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
"

# 4. Spring Boot 빌드
sudo -u marketflow bash -c "
  cd /srv/marketflow/backend
  ./gradlew bootJar
"

# 5. systemd 유닛 설치
sudo cp deploy/systemd/marketflow-*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now marketflow-flask marketflow-scheduler marketflow-spring

# 6. 헬스체크
systemctl status marketflow-flask marketflow-scheduler marketflow-spring
curl http://localhost:5001/api/kr/jongga-v2/latest
curl http://localhost:8080/api/us/market-briefing
```

## 운영 명령

```bash
# 상태
systemctl status marketflow-flask
journalctl -u marketflow-flask -f --since "1 hour ago"

# 재시작
sudo systemctl restart marketflow-flask
sudo systemctl restart marketflow-scheduler

# 정지
sudo systemctl stop marketflow-flask marketflow-scheduler marketflow-spring

# 자동 부팅 해제
sudo systemctl disable marketflow-flask
```

## 주의 사항

- `.env`는 `chmod 600 /srv/marketflow/.env` (마운트 권한 600)
- `data/`는 `chmod 750`
- Flask/Spring은 `EnvironmentFile=/srv/marketflow/.env`로 키 주입
- Spring Boot는 `Environment=APP_BASE_DIR=/srv/marketflow`로 application.yml 경로 오버라이드
- 시간대: `sudo timedatectl set-timezone Asia/Seoul`
- 로케일: `sudo locale-gen ko_KR.UTF-8`

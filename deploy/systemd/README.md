# MarketFlow systemd units (Linux 홈서버용)

## 유닛 목록

| 파일 | 설명 | 의존성 |
|---|---|---|
| `marketflow-flask.service` | Flask API (port 5001, 127.0.0.1) | network-online |
| `marketflow-scheduler.service` | Scheduler 데몬 | marketflow-flask |
| `cloudflared.service` | Cloudflare Tunnel | network-online |
| `marketflow-notify@.service` | 장애 시 텔레그램 알림 | (OnFailure 트리거) |
| `marketflow-backup.service` | restic 일일 백업 | (타이머 트리거) |
| `marketflow-backup.timer` | 백업 타이머 (매일 03:00) | - |

## 설치

```bash
# 1. setup.sh가 자동으로 모든 유닛을 /etc/systemd/system/에 복사
sudo bash deploy/setup.sh

# 수동 설치 시:
sudo cp deploy/systemd/*.service deploy/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable marketflow-flask marketflow-scheduler
sudo systemctl enable --now marketflow-backup.timer  # 백업 활성화 (선택)
```

## 운영 명령

```bash
# 상태
systemctl status marketflow-flask marketflow-scheduler cloudflared

# 로그 (실시간)
journalctl -u marketflow-flask -f --since "1 hour ago"

# 재시작
sudo systemctl restart marketflow-flask
sudo systemctl restart marketflow-scheduler

# 전체 중지
sudo systemctl stop marketflow-flask marketflow-scheduler cloudflared

# 백업 수동 실행
sudo systemctl start marketflow-backup
```

## 장애 알림

Flask/Scheduler 서비스 실패 시 `OnFailure=marketflow-notify@%n.service`가 트리거되어
`deploy/notify-failure.sh`를 실행합니다. `.env`의 `TELEGRAM_BOT_TOKEN`과 `TELEGRAM_CHAT_ID`가 필요합니다.

## 보안

- Flask는 `127.0.0.1:5001`에만 바인딩 (Cloudflare Tunnel 경유 외부 접근)
- systemd 하드닝: `NoNewPrivileges`, `ProtectSystem=full`, `ProtectHome`, `PrivateTmp`
- `.env`는 `chmod 600`, `marketflow:marketflow` 소유
- ufw로 SSH만 외부 허용

## 주의사항

- 8080 포트는 별도 프로젝트(JUST BUY) — MarketFlow와 무관
- `backend/` Spring Boot는 dead code — systemd unit 없음
- 타임존: `TZ=Asia/Seoul` (systemd unit에 명시)

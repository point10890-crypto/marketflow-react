#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# systemd 서비스 실패 시 텔레그램 알림
# 사용법: systemd unit의 OnFailure=에 연결
#
# [Unit]
# OnFailure=marketflow-notify@%n.service
#
# 별도 유닛 (/etc/systemd/system/marketflow-notify@.service):
# [Service]
# Type=oneshot
# ExecStart=/srv/marketflow/deploy/notify-failure.sh %i
# EnvironmentFile=/srv/marketflow/.env
# ─────────────────────────────────────────────────────────────────────
set -uo pipefail

SERVICE_NAME="${1:-unknown}"
HOSTNAME=$(hostname)
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S KST')

# .env에서 텔레그램 토큰 로드
ENV_FILE="/srv/marketflow/.env"
if [[ -f "$ENV_FILE" ]]; then
    BOT_TOKEN=$(grep '^TELEGRAM_BOT_TOKEN=' "$ENV_FILE" | cut -d= -f2)
    CHAT_ID=$(grep '^TELEGRAM_CHAT_ID=' "$ENV_FILE" | cut -d= -f2)
fi

if [[ -z "${BOT_TOKEN:-}" ]] || [[ -z "${CHAT_ID:-}" ]]; then
    echo "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set"
    exit 1
fi

# 최근 로그 (마지막 10줄)
RECENT_LOG=$(journalctl -u "$SERVICE_NAME" -n 10 --no-pager 2>/dev/null || echo "로그 조회 실패")

MESSAGE="🚨 *서비스 장애 알림*

서비스: \`${SERVICE_NAME}\`
호스트: \`${HOSTNAME}\`
시각: ${TIMESTAMP}

최근 로그:
\`\`\`
${RECENT_LOG}
\`\`\`

복구: \`sudo systemctl restart ${SERVICE_NAME}\`"

curl -sf -X POST \
    "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
    -d chat_id="${CHAT_ID}" \
    -d parse_mode="Markdown" \
    -d text="${MESSAGE}" \
    > /dev/null 2>&1

echo "알림 전송: $SERVICE_NAME → Telegram"

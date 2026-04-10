#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# MarketFlow 롤백 스크립트
# 미니PC에서 문제 발생 시 → 노트북으로 되돌리기
# 실행: sudo bash deploy/rollback.sh
# ─────────────────────────────────────────────────────────────────────
set -uo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

echo "═══════════════════════════════════════════════════════"
echo -e " ${YELLOW}MarketFlow 롤백 — 미니PC → 노트북 복귀${NC}"
echo "═══════════════════════════════════════════════════════"
echo ""
echo "이 스크립트는 미니PC의 서비스를 중지하고"
echo "노트북에서 다시 운영할 수 있도록 합니다."
echo ""
read -p "진행하시겠습니까? (y/N): " confirm
[[ "$confirm" != "y" && "$confirm" != "Y" ]] && echo "취소됨" && exit 0

echo ""
echo "▶ 1. 서비스 중지"
systemctl stop marketflow-scheduler 2>/dev/null && echo "  scheduler 중지" || echo "  scheduler 이미 중지됨"
systemctl stop marketflow-flask 2>/dev/null && echo "  flask 중지" || echo "  flask 이미 중지됨"
systemctl stop cloudflared 2>/dev/null && echo "  cloudflared 중지" || echo "  cloudflared 이미 중지됨"

echo ""
echo "▶ 2. 서비스 비활성화 (부팅 시 자동시작 해제)"
systemctl disable marketflow-flask marketflow-scheduler 2>/dev/null
echo "  자동시작 해제 완료"

echo ""
echo "▶ 3. 최신 데이터 백업"
BACKUP_DIR="/srv/marketflow/rollback_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
cp -r /srv/marketflow/data "$BACKUP_DIR/" 2>/dev/null && echo "  data/ → $BACKUP_DIR" || echo "  data/ 복사 실패"
cp /srv/marketflow/.env "$BACKUP_DIR/" 2>/dev/null && echo "  .env → $BACKUP_DIR" || echo "  .env 복사 실패"
cp -r /srv/marketflow/logs "$BACKUP_DIR/" 2>/dev/null && echo "  logs/ → $BACKUP_DIR" || echo "  logs/ 복사 실패"

echo ""
echo "═══════════════════════════════════════════════════════"
echo -e " ${GREEN}롤백 완료${NC}"
echo ""
echo " 미니PC 서비스 중지됨. 다음 단계:"
echo ""
echo " 1. 노트북에서 최신 데이터 가져오기:"
echo "    scp -r root@<미니PC>:$BACKUP_DIR/data/ C:/bitman_marketfloww/data/"
echo ""
echo " 2. 노트북에서 서비스 재시작:"
echo "    cd /c/bitman_marketfloww"
echo "    .venv/Scripts/python.exe flask_app.py &"
echo "    .venv/Scripts/python.exe scheduler.py --daemon &"
echo ""
echo " 3. 노트북에서 Cloudflare 터널 재시작:"
echo "    cloudflared tunnel --config ~/.cloudflared/config.yml run &"
echo "═══════════════════════════════════════════════════════"

#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# MarketFlow 마이그레이션 스크립트 (노트북 → 홈서버)
# 실행 위치: 노트북 (Windows Git Bash / MINGW)
# 사용법: bash deploy/migrate.sh <서버IP> [SSH유저]
#
# 예시:
#   bash deploy/migrate.sh 192.168.0.100
#   bash deploy/migrate.sh 192.168.0.100 root
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; exit 1; }
step() { echo -e "\n${CYAN}▶ $1${NC}"; }

# ── 인자 검증 ──
SERVER_IP="${1:-}"
SSH_USER="${2:-root}"
[[ -z "$SERVER_IP" ]] && fail "사용법: bash deploy/migrate.sh <서버IP> [SSH유저]"

PROJECT="/c/bitman_marketfloww"
REMOTE_DIR="/srv/marketflow"
REMOTE="$SSH_USER@$SERVER_IP"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

echo "═══════════════════════════════════════════════════════"
echo " MarketFlow 마이그레이션: 노트북 → $SERVER_IP"
echo "═══════════════════════════════════════════════════════"

# ── Phase 0: SSH 연결 확인 ──
step "Phase 0: SSH 연결 확인"
ssh -o ConnectTimeout=5 -o BatchMode=yes "$REMOTE" "echo 'SSH OK'" 2>/dev/null \
    || fail "SSH 연결 실패. ssh-copy-id $REMOTE 로 키 등록 먼저 하세요."
ok "SSH 연결 ($REMOTE)"

# ── Phase 1: 코드 동기화 (rsync) ──
step "Phase 1: 코드 동기화"
rsync -avz --progress \
    --exclude='.venv/' \
    --exclude='node_modules/' \
    --exclude='.git/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='backend/' \
    --exclude='archive/' \
    --exclude='frontend-react/dist/' \
    --exclude='frontend-react/.next/' \
    --exclude='logs/*.log' \
    --exclude='logs/*.err' \
    --exclude='*.db-wal' \
    --exclude='*.db-shm' \
    "$PROJECT/" "$REMOTE:$REMOTE_DIR/"
ok "코드 동기화 완료"

# ── Phase 1.5: SQLite DB 안전 복사 ──
step "Phase 1.5: SQLite DB 안전 복사 (WAL 체크포인트)"
cd "$PROJECT"
# WAL 체크포인트 후 복사 (데이터 무결성 보장)
PYTHON="$PROJECT/.venv/Scripts/python.exe"
"$PYTHON" -c "
import sqlite3, os
db_path = 'data/users.db'
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    conn.close()
    print('WAL checkpoint done')
else:
    print('No users.db found')
"
scp "$PROJECT/data/users.db" "$REMOTE:$REMOTE_DIR/data/" 2>/dev/null && ok "users.db 복사" || warn "users.db 없음 (스킵)"

# ── Phase 2: .env 복사 ──
step "Phase 2: 환경변수 (.env)"
scp "$PROJECT/.env" "$REMOTE:$REMOTE_DIR/.env"
ssh "$REMOTE" "chmod 600 $REMOTE_DIR/.env && chown marketflow:marketflow $REMOTE_DIR/.env"
ok ".env 복사 + 권한 설정"

# ── Phase 3: Cloudflared 자격증명 ──
step "Phase 3: Cloudflared 자격증명"
CRED_DIR="/c/Users/dynas/.cloudflared"
if [[ -f "$CRED_DIR/config.yml" ]]; then
    ssh "$REMOTE" "mkdir -p /etc/cloudflared"
    scp "$CRED_DIR/config.yml" "$REMOTE:/etc/cloudflared/config.yml"
    scp "$CRED_DIR/678e9c60-9f8d-4f49-9fba-a49400ef4ca0.json" "$REMOTE:/etc/cloudflared/"
    ssh "$REMOTE" "chmod 600 /etc/cloudflared/*.json"
    ok "Cloudflared 자격증명 복사"
else
    warn "Cloudflared config.yml 없음 — 수동 복사 필요"
fi

# ── Phase 4: Cloudflared config.yml Linux 경로로 갱신 ──
step "Phase 4: Cloudflared config.yml 경로 수정"
ssh "$REMOTE" "
if [[ -f /etc/cloudflared/config.yml ]]; then
    sed -i 's|C:\\\\Users\\\\dynas\\\\.cloudflared|/etc/cloudflared|g' /etc/cloudflared/config.yml
    sed -i 's|C:/Users/dynas/.cloudflared|/etc/cloudflared|g' /etc/cloudflared/config.yml
    echo 'config.yml 경로 수정 완료'
    cat /etc/cloudflared/config.yml
fi
"
ok "Cloudflared config 업데이트"

# ── Phase 5: 원격 서버 셋업 확인 ──
step "Phase 5: 원격 서버 환경 확인"
ssh "$REMOTE" "
echo '── 디렉토리 ──'
ls -la $REMOTE_DIR/ | head -20
echo ''
echo '── .env ──'
[[ -f $REMOTE_DIR/.env ]] && echo 'EXISTS ($(wc -l < $REMOTE_DIR/.env) lines)' || echo 'MISSING'
echo ''
echo '── systemd 유닛 ──'
systemctl is-enabled marketflow-flask 2>/dev/null || echo 'flask: NOT ENABLED'
systemctl is-enabled marketflow-scheduler 2>/dev/null || echo 'scheduler: NOT ENABLED'
echo ''
echo '── Python ──'
[[ -f $REMOTE_DIR/.venv/bin/python ]] && $REMOTE_DIR/.venv/bin/python --version || echo 'venv 없음 — 생성 필요'
echo ''
echo '── Cloudflared ──'
cloudflared --version 2>/dev/null || echo 'cloudflared 미설치'
"

# ── 요약 ──
echo ""
echo "═══════════════════════════════════════════════════════"
echo -e " ${GREEN}마이그레이션 데이터 전송 완료!${NC}"
echo ""
echo " venv 미생성 시:"
echo "   ssh $REMOTE"
echo "   sudo -u marketflow python3.13 -m venv $REMOTE_DIR/.venv"
echo "   sudo -u marketflow $REMOTE_DIR/.venv/bin/pip install -r $REMOTE_DIR/requirements.txt"
echo ""
echo " 서비스 시작:"
echo "   ssh $REMOTE 'systemctl start marketflow-flask && systemctl start marketflow-scheduler'"
echo ""
echo " 헬스 체크:"
echo "   ssh $REMOTE 'curl -s http://localhost:5001/api/kr/jongga-v2/latest | head -c 200'"
echo ""
echo " Cloudflared 터널 시작 (노트북 터널 종료 후):"
echo "   ssh $REMOTE 'systemctl start cloudflared'"
echo ""
echo -e " ${YELLOW}⚠ 주의: 노트북의 cloudflared를 먼저 종료하세요!${NC}"
echo "   taskkill //F //IM cloudflared.exe"
echo "═══════════════════════════════════════════════════════"

#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# MarketFlow 홈서버 초기 셋업 스크립트
# 대상: Debian 12 / Ubuntu 24.04 LTS (x86_64)
# 실행: sudo bash setup.sh
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── 색상 ──
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; exit 1; }

# ── 루트 확인 ──
[[ $EUID -ne 0 ]] && fail "root 권한 필요: sudo bash setup.sh"

PROJECT_DIR="/srv/marketflow"
SERVICE_USER="marketflow"

echo "═══════════════════════════════════════════════════════"
echo " MarketFlow 홈서버 초기 셋업"
echo "═══════════════════════════════════════════════════════"

# ── 1. 시스템 패키지 ──
echo ""
echo "▶ 1/7  시스템 패키지 설치"
apt-get update -qq
apt-get install -y -qq \
    python3.13 python3.13-venv python3.13-dev \
    build-essential git curl wget ufw \
    fonts-noto-cjk \
    sqlite3 \
    > /dev/null 2>&1 || {
    # Python 3.13 미존재 시 deadsnakes PPA (Ubuntu)
    warn "Python 3.13 없음 — deadsnakes PPA 추가 시도"
    apt-get install -y -qq software-properties-common > /dev/null 2>&1
    add-apt-repository -y ppa:deadsnakes/ppa > /dev/null 2>&1
    apt-get update -qq
    apt-get install -y -qq python3.13 python3.13-venv python3.13-dev > /dev/null 2>&1
}
ok "시스템 패키지"

# ── 2. Node.js 20 LTS ──
echo ""
echo "▶ 2/7  Node.js 20 LTS"
if ! command -v node &>/dev/null || [[ $(node -v | cut -d. -f1 | tr -d v) -lt 20 ]]; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - > /dev/null 2>&1
    apt-get install -y -qq nodejs > /dev/null 2>&1
fi
ok "Node.js $(node -v)"

# ── 3. Cloudflared ──
echo ""
echo "▶ 3/7  Cloudflared"
if ! command -v cloudflared &>/dev/null; then
    curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | \
        tee /usr/share/keyrings/cloudflare-main.gpg > /dev/null
    echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared $(lsb_release -cs) main" | \
        tee /etc/apt/sources.list.d/cloudflared.list > /dev/null
    apt-get update -qq
    apt-get install -y -qq cloudflared > /dev/null 2>&1
fi
ok "cloudflared $(cloudflared --version 2>&1 | head -1)"

# ── 4. 시스템 사용자 생성 ──
echo ""
echo "▶ 4/7  시스템 사용자 (${SERVICE_USER})"
if ! id "$SERVICE_USER" &>/dev/null; then
    useradd -r -s /usr/sbin/nologin -d "$PROJECT_DIR" -m "$SERVICE_USER"
    ok "사용자 생성: $SERVICE_USER"
else
    ok "사용자 이미 존재: $SERVICE_USER"
fi

# ── 5. 프로젝트 디렉토리 ──
echo ""
echo "▶ 5/7  프로젝트 디렉토리"
mkdir -p "$PROJECT_DIR"/{data,logs}
chown -R "$SERVICE_USER":"$SERVICE_USER" "$PROJECT_DIR"
chmod 750 "$PROJECT_DIR"
ok "$PROJECT_DIR 준비 완료"

# ── 6. 방화벽 (ufw) ──
echo ""
echo "▶ 6/7  방화벽 설정"
ufw allow OpenSSH > /dev/null 2>&1
# Flask는 Cloudflare Tunnel 경유 — localhost만 바인딩이므로 외부 포트 불필요
# 필요 시 LAN 전용: ufw allow from 192.168.0.0/24 to any port 5001
ufw --force enable > /dev/null 2>&1
ok "ufw 활성화 (SSH 허용)"

# ── 7. systemd 유닛 설치 ──
echo ""
echo "▶ 7/7  systemd 유닛"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -d "$SCRIPT_DIR/systemd" ]]; then
    cp "$SCRIPT_DIR/systemd/marketflow-flask.service" /etc/systemd/system/
    cp "$SCRIPT_DIR/systemd/marketflow-scheduler.service" /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable marketflow-flask marketflow-scheduler
    ok "systemd 유닛 설치 + enable"
else
    warn "systemd/ 디렉토리 없음 — 수동 복사 필요"
fi

# ── 완료 ──
echo ""
echo "═══════════════════════════════════════════════════════"
echo -e " ${GREEN}셋업 완료!${NC}"
echo ""
echo " 다음 단계:"
echo "   1. 노트북에서 migrate.sh 실행 (데이터 이전)"
echo "   2. $PROJECT_DIR/.env 확인 (chmod 600)"
echo "   3. Python venv 생성:"
echo "      sudo -u $SERVICE_USER python3.13 -m venv $PROJECT_DIR/.venv"
echo "      sudo -u $SERVICE_USER $PROJECT_DIR/.venv/bin/pip install -r $PROJECT_DIR/requirements.txt"
echo "   4. Cloudflared 자격증명 복사:"
echo "      cp <cred>.json /etc/cloudflared/"
echo "      cp config.yml /etc/cloudflared/"
echo "   5. 서비스 시작:"
echo "      systemctl start marketflow-flask"
echo "      systemctl start marketflow-scheduler"
echo "═══════════════════════════════════════════════════════"

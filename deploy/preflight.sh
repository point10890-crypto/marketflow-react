#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# MarketFlow 이전 전 사전점검 (Pre-flight Check)
# 실행 위치: 노트북 (Git Bash / MINGW)
# 사용법: bash deploy/preflight.sh [서버IP]
# ─────────────────────────────────────────────────────────────────────
set -uo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
PASS=0; FAIL=0; WARN=0

check() {
    local name="$1"; shift
    if "$@" > /dev/null 2>&1; then
        echo -e "  ${GREEN}✓${NC} $name"; ((PASS++))
    else
        echo -e "  ${RED}✗${NC} $name"; ((FAIL++))
    fi
}
warn_check() {
    local name="$1"; shift
    if "$@" > /dev/null 2>&1; then
        echo -e "  ${GREEN}✓${NC} $name"; ((PASS++))
    else
        echo -e "  ${YELLOW}⚠${NC} $name (권장)"; ((WARN++))
    fi
}

PROJECT="/c/bitman_marketfloww"
SERVER_IP="${1:-}"

echo "═══════════════════════════════════════════════════════"
echo " MarketFlow 이전 사전점검 $(date '+%Y-%m-%d %H:%M')"
echo "═══════════════════════════════════════════════════════"

# ── 1. 코드 상태 ──
echo ""
echo -e "${CYAN}▶ 1. 코드 상태${NC}"
cd "$PROJECT"
# data/, logs/ 등 런타임 변경은 무시 — 소스 코드만 체크
check "소스코드 커밋 완료" git diff --quiet HEAD -- '*.py' '*.tsx' '*.ts' '*.service' '*.sh' '*.yml'
check "main 브랜치" test "$(git branch --show-current)" = "main"
warn_check "원격과 동기화" git diff --quiet origin/main..HEAD -- '*.py' '*.tsx' '*.ts'

# ── 2. 필수 파일 존재 ──
echo ""
echo -e "${CYAN}▶ 2. 필수 파일${NC}"
check ".env 존재" test -f "$PROJECT/.env"
check "requirements.txt" test -f "$PROJECT/requirements.txt"
check "flask_app.py" test -f "$PROJECT/flask_app.py"
check "scheduler.py" test -f "$PROJECT/scheduler.py"
check "deploy/setup.sh" test -f "$PROJECT/deploy/setup.sh"
check "deploy/migrate.sh" test -f "$PROJECT/deploy/migrate.sh"
check "deploy/healthcheck.sh" test -f "$PROJECT/deploy/healthcheck.sh"
check "systemd/flask.service" test -f "$PROJECT/deploy/systemd/marketflow-flask.service"
check "systemd/scheduler.service" test -f "$PROJECT/deploy/systemd/marketflow-scheduler.service"
check "systemd/cloudflared.service" test -f "$PROJECT/deploy/systemd/cloudflared.service"
check "cloudflared-config-linux.yml" test -f "$PROJECT/deploy/cloudflared-config-linux.yml"

# ── 3. 데이터 무결성 ──
echo ""
echo -e "${CYAN}▶ 3. 데이터 파일${NC}"
check "data/users.db" test -f "$PROJECT/data/users.db"
check "data/jongga_v2_latest.json" test -f "$PROJECT/data/jongga_v2_latest.json"
check "data/daily_prices.csv" test -f "$PROJECT/data/daily_prices.csv"
warn_check "data/scheduler_last_run.json" test -f "$PROJECT/data/scheduler_last_run.json"

DATA_SIZE=$(du -sh "$PROJECT/data/" 2>/dev/null | awk '{print $1}')
echo -e "  📦 data/ 크기: $DATA_SIZE"

# ── 4. Linux 호환성 체크 ──
echo ""
echo -e "${CYAN}▶ 4. Linux 호환성${NC}"
PYTHON="$PROJECT/.venv/Scripts/python.exe"

# Windows-only 코드 잔여 확인 (tasklist가 os.name=='nt' 분기 안에 있는지)
# scheduler.py, diagnostics.py 에서 tasklist는 이미 os.name 분기 안에 있으므로 OK
UNGUARDED=$(grep -rn "tasklist" "$PROJECT"/*.py "$PROJECT"/app/ "$PROJECT"/engine/ 2>/dev/null | grep -v "__pycache__" | grep -v "Binary" | wc -l)
GUARDED=$(grep -rn "os.name == 'nt'" "$PROJECT"/scheduler.py "$PROJECT"/app/utils/diagnostics.py 2>/dev/null | wc -l)
if [ "$GUARDED" -ge "$UNGUARDED" ] || [ "$UNGUARDED" -le 2 ]; then
    echo -e "  ${GREEN}✓${NC} tasklist 사용: OS 분기 처리됨 (${UNGUARDED}건, 모두 nt 가드)"
    ((PASS++))
else
    echo -e "  ${RED}✗${NC} tasklist 미분기 발견 (total:$UNGUARDED, guarded:$GUARDED)"
    ((FAIL++))
fi

check "flask_app.py 127.0.0.1 분기" grep -q "127.0.0.1" "$PROJECT/flask_app.py"
check "scheduler.py os.kill 분기" grep -q "os.kill(old_pid, 0)" "$PROJECT/scheduler.py"
check "production_utils.py msvcrt 안전" grep -q "msvcrt = None" "$PROJECT/crypto-analytics/crypto_market/operations/production_utils.py"

# ── 5. API 키 확인 ──
echo ""
echo -e "${CYAN}▶ 5. API 키 (.env)${NC}"
for key in GEMINI_API_KEY OPENAI_API_KEY DART_API_KEY TELEGRAM_BOT_TOKEN; do
    if grep -q "^${key}=" "$PROJECT/.env" 2>/dev/null; then
        VAL=$(grep "^${key}=" "$PROJECT/.env" | cut -d= -f2 | head -c3)
        echo -e "  ${GREEN}✓${NC} $key (${VAL}...)"
        ((PASS++))
    else
        echo -e "  ${RED}✗${NC} $key 누락"
        ((FAIL++))
    fi
done

# ── 6. Cloudflared 자격증명 ──
echo ""
echo -e "${CYAN}▶ 6. Cloudflared${NC}"
CRED_DIR="/c/Users/dynas/.cloudflared"
check "config.yml 존재" test -f "$CRED_DIR/config.yml"
check "자격증명 JSON 존재" test -f "$CRED_DIR/678e9c60-9f8d-4f49-9fba-a49400ef4ca0.json"

# ── 7. 서버 연결 (IP 지정 시) ──
if [[ -n "$SERVER_IP" ]]; then
    echo ""
    echo -e "${CYAN}▶ 7. 서버 연결 ($SERVER_IP)${NC}"
    check "SSH 연결" ssh -o ConnectTimeout=5 -o BatchMode=yes "root@$SERVER_IP" "echo ok"
    warn_check "rsync 설치됨" ssh -o ConnectTimeout=5 "root@$SERVER_IP" "which rsync"
    warn_check "Python 3.13" ssh -o ConnectTimeout=5 "root@$SERVER_IP" "python3.13 --version"
    warn_check "cloudflared 설치됨" ssh -o ConnectTimeout=5 "root@$SERVER_IP" "which cloudflared"
fi

# ── 요약 ──
echo ""
echo "═══════════════════════════════════════════════════════"
TOTAL=$((PASS + FAIL + WARN))
if [[ $FAIL -eq 0 ]]; then
    echo -e " ${GREEN}PRE-FLIGHT PASSED${NC} ✓  (pass:$PASS warn:$WARN total:$TOTAL)"
    echo ""
    echo " 이전 준비 완료! 다음 명령어로 진행:"
    if [[ -n "$SERVER_IP" ]]; then
        echo "   bash deploy/migrate.sh $SERVER_IP"
    else
        echo "   bash deploy/migrate.sh <서버IP>"
    fi
else
    echo -e " ${RED}PRE-FLIGHT FAILED${NC}  (pass:$PASS fail:$FAIL warn:$WARN)"
    echo ""
    echo " 위 실패 항목을 수정한 후 다시 실행하세요."
fi
echo "═══════════════════════════════════════════════════════"

#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# MarketFlow 홈서버 헬스체크
# 실행: bash deploy/healthcheck.sh  (서버에서 직접 또는 ssh로)
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
PASS=0; FAIL=0

check() {
    local name="$1" cmd="$2"
    if eval "$cmd" > /dev/null 2>&1; then
        echo -e "  ${GREEN}✓${NC} $name"
        ((PASS++))
    else
        echo -e "  ${RED}✗${NC} $name"
        ((FAIL++))
    fi
}

echo "═══════════════════════════════════════════════════════"
echo " MarketFlow 헬스체크 $(date '+%Y-%m-%d %H:%M:%S KST')"
echo "═══════════════════════════════════════════════════════"

echo ""
echo "▶ systemd 서비스"
check "Flask (active)"     "systemctl is-active marketflow-flask"
check "Scheduler (active)" "systemctl is-active marketflow-scheduler"
check "Cloudflared (active)" "systemctl is-active cloudflared"

echo ""
echo "▶ 포트 바인딩"
check "Port 5001 (Flask)"  "ss -tlnp | grep -q ':5001'"

echo ""
echo "▶ API 엔드포인트"
check "KR 종가베팅"  "curl -sf http://localhost:5001/api/kr/jongga-v2/latest | grep -q 'signals'"
check "KR Market Gate" "curl -sf http://localhost:5001/api/kr/market-gate | grep -q 'regime'"
check "US Briefing"    "curl -sf http://localhost:5001/api/us/market-briefing | grep -q 'ai_analysis'"
check "US Heatmap"     "curl -sf http://localhost:5001/api/us/heatmap-data | grep -q 'series'"

echo ""
echo "▶ 데이터 파일"
check "jongga_v2_latest.json" "test -f /srv/marketflow/data/jongga_v2_latest.json"
check "users.db"               "test -f /srv/marketflow/data/users.db"
check "daily_prices.csv"       "test -f /srv/marketflow/data/daily_prices.csv"
check ".env"                   "test -f /srv/marketflow/.env"

echo ""
echo "▶ 스케줄러"
check "scheduler.pid 존재" "test -f /srv/marketflow/logs/scheduler.pid"
check "PID 생존" "kill -0 \$(cat /srv/marketflow/logs/scheduler.pid 2>/dev/null) 2>/dev/null"

echo ""
echo "▶ 외부 터널"
check "marketflow-api.bit-man.net" "curl -sf --max-time 10 https://marketflow-api.bit-man.net/api/kr/market-gate | grep -q 'regime'"

echo ""
echo "▶ 디스크/메모리"
DISK_USED=$(df -h /srv/marketflow 2>/dev/null | awk 'NR==2{print $5}' || echo "N/A")
MEM_AVAIL=$(free -m 2>/dev/null | awk '/Mem:/{print $7}' || echo "N/A")
echo "  디스크 사용: $DISK_USED"
echo "  가용 메모리: ${MEM_AVAIL}MB"

# ── 요약 ──
echo ""
echo "═══════════════════════════════════════════════════════"
TOTAL=$((PASS + FAIL))
if [[ $FAIL -eq 0 ]]; then
    echo -e " ${GREEN}ALL PASS${NC} ($PASS/$TOTAL)"
else
    echo -e " ${RED}FAIL: $FAIL${NC} / PASS: $PASS / TOTAL: $TOTAL"
fi
echo "═══════════════════════════════════════════════════════"

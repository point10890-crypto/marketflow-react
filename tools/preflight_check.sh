#!/usr/bin/env bash
# MarketFlow 홈서버 사전 점검 (Linux 미니PC 첫 부팅 시 1회 실행)
# 의도: D-day 플레이북 진입 전에 OS/패키지/네트워크/권한이 준비되었는지 자동 검증
# 사용: bash tools/preflight_check.sh
set -u

PROJECT="${PROJECT:-/srv/marketflow}"
PASS=0
FAIL=0

ok()   { echo "  [OK]   $1"; PASS=$((PASS+1)); }
fail() { echo "  [FAIL] $1"; FAIL=$((FAIL+1)); }
hr()   { echo "── $1 ──"; }

hr "1. OS / 시간대 / 로케일"
[ -f /etc/os-release ] && ok "/etc/os-release ($(. /etc/os-release; echo "$PRETTY_NAME"))" || fail "OS info"
TZ_NOW=$(timedatectl 2>/dev/null | awk -F': ' '/Time zone/ {print $2}' | awk '{print $1}')
[ "$TZ_NOW" = "Asia/Seoul" ] && ok "timezone Asia/Seoul" || fail "timezone is '$TZ_NOW' (expected Asia/Seoul)"
locale -a 2>/dev/null | grep -qi 'ko_KR.utf' && ok "ko_KR.UTF-8 locale" || fail "ko_KR.UTF-8 locale missing"

hr "2. 필수 패키지"
for cmd in python3 java node npm git curl rsync tar systemctl; do
  command -v "$cmd" >/dev/null 2>&1 && ok "$cmd present" || fail "$cmd missing"
done

PYV=$(python3 --version 2>&1 | awk '{print $2}')
case "$PYV" in
  3.1[0-9].*|3.[2-9][0-9].*) ok "python3 $PYV (>= 3.10)" ;;
  *) fail "python3 $PYV too old (need >= 3.10)" ;;
esac

JAVAV=$(java -version 2>&1 | head -1 | awk -F'"' '{print $2}')
case "$JAVAV" in
  21.*|22.*|23.*) ok "java $JAVAV (>= 21)" ;;
  *) fail "java $JAVAV (need 21+)" ;;
esac

NODEV=$(node --version 2>&1 | tr -d 'v')
case "$NODEV" in
  20.*|21.*|22.*) ok "node $NODEV (>= 20)" ;;
  *) fail "node $NODEV (need 20+)" ;;
esac

command -v cloudflared >/dev/null 2>&1 && ok "cloudflared present" || fail "cloudflared missing (apt install cloudflared)"

hr "3. 사용자 / 디렉토리 / 권한"
id marketflow >/dev/null 2>&1 && ok "user 'marketflow' exists" || fail "user 'marketflow' missing"
[ -d "$PROJECT" ] && ok "$PROJECT exists" || fail "$PROJECT missing"
[ -d "$PROJECT/data" ] && ok "$PROJECT/data exists" || fail "$PROJECT/data missing"
[ -d "$PROJECT/logs" ] && ok "$PROJECT/logs exists" || fail "$PROJECT/logs missing"
[ -f "$PROJECT/.env" ] && ok "$PROJECT/.env exists" || fail "$PROJECT/.env missing"

if [ -f "$PROJECT/.env" ]; then
  PERM=$(stat -c '%a' "$PROJECT/.env" 2>/dev/null)
  [ "$PERM" = "600" ] && ok ".env permissions 600" || fail ".env permissions $PERM (must be 600)"
  OWN=$(stat -c '%U' "$PROJECT/.env" 2>/dev/null)
  [ "$OWN" = "marketflow" ] && ok ".env owner marketflow" || fail ".env owner $OWN"
fi

hr "4. Python venv"
if [ -x "$PROJECT/.venv/bin/python" ]; then
  ok ".venv/bin/python executable"
  VENVV=$("$PROJECT/.venv/bin/python" --version 2>&1 | awk '{print $2}')
  echo "         (venv python $VENVV)"
else
  fail ".venv/bin/python missing — run: cd $PROJECT && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
fi

hr "5. Spring Boot jar"
JAR=$(ls "$PROJECT/backend/build/libs/"*.jar 2>/dev/null | head -1)
if [ -n "$JAR" ]; then
  ok "Spring Boot jar: $(basename "$JAR")"
else
  fail "Spring Boot jar missing — run: cd $PROJECT/backend && ./gradlew bootJar"
fi

hr "6. .env 키 존재성"
if [ -f "$PROJECT/.env" ]; then
  REQUIRED_KEYS=(
    GEMINI_API_KEY OPENAI_API_KEY ANTHROPIC_API_KEY DART_API_KEY FMP_API_KEY
    KIS_APP_KEY KIS_APP_SECRET KIS_CANO
    TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID
  )
  for k in "${REQUIRED_KEYS[@]}"; do
    if grep -q "^$k=" "$PROJECT/.env" 2>/dev/null; then
      ok "$k set"
    else
      fail "$k missing in .env"
    fi
  done
fi

hr "7. Cloudflared 설정"
[ -f /etc/cloudflared/config.yml ] && ok "/etc/cloudflared/config.yml" || fail "/etc/cloudflared/config.yml missing"
CRED=$(ls /etc/cloudflared/*.json 2>/dev/null | head -1)
[ -n "$CRED" ] && ok "credentials json: $(basename "$CRED")" || fail "tunnel credentials json missing in /etc/cloudflared/"

hr "8. systemd unit 파일"
for u in marketflow-flask marketflow-scheduler marketflow-spring; do
  [ -f "/etc/systemd/system/$u.service" ] && ok "$u.service installed" || fail "$u.service not installed (cp deploy/systemd/$u.service /etc/systemd/system/)"
done

hr "9. 방화벽 (ufw)"
if command -v ufw >/dev/null 2>&1; then
  ufw status 2>/dev/null | grep -q "Status: active" && ok "ufw active" || fail "ufw inactive (sudo ufw enable)"
else
  fail "ufw not installed"
fi

hr "10. 디스크 여유"
FREE_GB=$(df -BG --output=avail "$PROJECT" 2>/dev/null | tail -1 | tr -d 'G ')
if [ -n "$FREE_GB" ] && [ "$FREE_GB" -ge 50 ]; then
  ok "disk free ${FREE_GB}G (>= 50G)"
else
  fail "disk free ${FREE_GB:-?}G (need >= 50G)"
fi

echo ""
echo "════════════════════════════════════════"
echo "  PASS: $PASS    FAIL: $FAIL"
echo "════════════════════════════════════════"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1

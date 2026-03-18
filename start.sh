#!/bin/bash
# MarketFlow - Local Server Startup
# Usage: cd /c/bitman_service && bash start.sh

PROJECT="/c/bitman_service"
PYTHON="$PROJECT/.venv/Scripts/python.exe"
FRONTEND="$PROJECT/frontend"
BACKEND="$PROJECT/backend"

echo "============================================"
echo "  BitMan MarketFlow Service Launcher"
echo "  Project: $PROJECT"
echo "============================================"
echo ""

# 1. Kill existing processes
echo "[0/4] Cleaning ports 5001, 8080, 4000..."
netstat -ano | grep -E ':5001|:8080|:4000' | grep LISTENING | awk '{print $5}' | sort -u | while read pid; do
    [ "$pid" != "0" ] && taskkill //F //PID "$pid" 2>/dev/null
done
sleep 2
echo "  Done"
echo ""

# 2. Start Flask backend
echo "[1/4] Starting Flask API (port 5001)..."
cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" flask_app.py &
sleep 4
if netstat -ano | grep ':5001' | grep LISTENING > /dev/null 2>&1; then
    echo "  Flask API: http://localhost:5001 OK"
else
    echo "  Flask API: FAILED"
    exit 1
fi
echo ""

# 3. Start Spring Boot backend
echo "[2/4] Starting Spring Boot (port 8080)..."
cd "$BACKEND" && ./gradlew bootRun &
sleep 10
if netstat -ano | grep ':8080' | grep LISTENING > /dev/null 2>&1; then
    echo "  Spring Boot: http://localhost:8080 OK"
else
    echo "  Spring Boot: FAILED (continuing...)"
fi
echo ""

# 4. Start Next.js frontend (production)
echo "[3/4] Starting Next.js (port 4000)..."
cd "$FRONTEND" && npm start &
sleep 6
if netstat -ano | grep ':4000' | grep LISTENING > /dev/null 2>&1; then
    echo "  Next.js: http://localhost:4000 OK"
else
    echo "  Next.js: FAILED"
    exit 1
fi
echo ""

# 5. Start Scheduler daemon
echo "[4/4] Starting Scheduler daemon..."
cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" scheduler.py --daemon &
sleep 2
echo "  Scheduler: daemon mode OK"
echo ""

# 6. Health check
echo "[CHECK] Verifying services..."
sleep 2
FLASK=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:5001/api/health)
SPRING=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/api/health)
FRONT=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:4000)
echo ""
echo "============================================"
echo "  BitMan MarketFlow - All Services"
echo "============================================"
echo "  [$FLASK]  Flask:       http://localhost:5001"
echo "  [$SPRING]  Spring Boot: http://localhost:8080"
echo "  [$FRONT]  Next.js:     http://localhost:4000"
echo "  [OK]  Scheduler:   daemon mode"
echo "============================================"

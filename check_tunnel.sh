#!/bin/bash
# Cloudflared tunnel health check + auto-restart
if ! tasklist 2>/dev/null | grep -qi cloudflared; then
    echo "[$(date)] cloudflared is DOWN — restarting..."
    cloudflared tunnel run &
    sleep 3
    if tasklist 2>/dev/null | grep -qi cloudflared; then
        echo "[$(date)] cloudflared restarted OK"
    else
        echo "[$(date)] cloudflared restart FAILED"
    fi
else
    echo "[$(date)] cloudflared is running"
fi

#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# MarketFlow 일일 백업 (restic → 로컬 USB or 원격)
# 크론: 0 3 * * * /srv/marketflow/deploy/backup.sh
# 첫 실행 전: restic init -r /mnt/backup/marketflow
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

BACKUP_REPO="${MARKETFLOW_BACKUP_REPO:-/mnt/backup/marketflow}"
PROJECT="/srv/marketflow"
LOG="/srv/marketflow/logs/backup.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG"; }

# restic 설치 확인
if ! command -v restic &>/dev/null; then
    log "ERROR: restic 미설치 — sudo apt install restic"
    exit 1
fi

# 백업 대상: data/ + .env + logs/ (코드는 git으로 관리)
log "백업 시작 → $BACKUP_REPO"

# SQLite WAL 체크포인트 (무결성 보장)
if [[ -f "$PROJECT/data/users.db" ]]; then
    "$PROJECT/.venv/bin/python" -c "
import sqlite3
conn = sqlite3.connect('$PROJECT/data/users.db')
conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
conn.close()
print('SQLite WAL checkpoint done')
" 2>/dev/null && log "SQLite WAL 체크포인트 완료" || log "WARN: WAL 체크포인트 실패 (계속 진행)"
fi

restic backup \
    --repo "$BACKUP_REPO" \
    --tag daily \
    --exclude="*.pyc" \
    --exclude="__pycache__" \
    --exclude="*.db-wal" \
    --exclude="*.db-shm" \
    "$PROJECT/data" \
    "$PROJECT/.env" \
    "$PROJECT/logs" \
    2>&1 | tee -a "$LOG"

# 30일 이상 된 스냅샷 정리
restic forget \
    --repo "$BACKUP_REPO" \
    --keep-daily 7 \
    --keep-weekly 4 \
    --keep-monthly 3 \
    --prune \
    2>&1 | tee -a "$LOG"

log "백업 완료"

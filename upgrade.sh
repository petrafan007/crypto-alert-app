#!/bin/bash
# upgrade.sh - Crypto & Securities Dashboard in-app upgrade.
#
# Safe by design: it never discards local changes. If the checkout has
# uncommitted edits to tracked files, it stops and says so instead of
# resetting them away.
set -euo pipefail
export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
LOG_FILE="$PROJECT_DIR/upgrade.log"
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOG_FILE"; }

TARGET_VERSION="${1:-}"
cd "$PROJECT_DIR"
log "Starting Crypto & Securities Dashboard upgrade${TARGET_VERSION:+ to $TARGET_VERSION}..."

if ! git diff --quiet || ! git diff --cached --quiet; then
    log "ERROR: tracked files have local changes; refusing to upgrade over them. Commit or stash them first."
    git status --short | tee -a "$LOG_FILE"
    exit 1
fi

git fetch origin --tags --force
if [ -n "$TARGET_VERSION" ]; then
    git rev-parse --verify --quiet "refs/tags/$TARGET_VERSION" >/dev/null || { log "ERROR: tag $TARGET_VERSION not found."; exit 1; }
    git checkout --quiet main
    git merge --ff-only "refs/tags/$TARGET_VERSION"
else
    git checkout --quiet main
    git merge --ff-only origin/main
fi
log "Checked out $(git describe --tags --always)."

PY="$PROJECT_DIR/venv/bin/python3"
[ -x "$PY" ] || PY="$PROJECT_DIR/.venv/bin/python3"
[ -x "$PY" ] || { log "ERROR: no virtual environment found (venv or .venv)."; exit 1; }

log "Installing Python dependencies..."
"$PY" -m pip install -r requirements.txt | tee -a "$LOG_FILE"

log "Installing Node dependencies and rebuilding the frontend..."
(cd frontend && npm ci | tee -a "$LOG_FILE" && npm run build | tee -a "$LOG_FILE")

log "Applying database migrations..."
"$PY" runtime.py init-db | tee -a "$LOG_FILE"
"$PY" update_db_prompts.py | tee -a "$LOG_FILE"

log "Restarting services..."
sudo systemctl restart crypto-dashboard.service crypto-dashboard-worker.service
log "Upgrade complete: $(git describe --tags --always)."

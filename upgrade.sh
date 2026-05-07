#!/bin/bash
# upgrade.sh - Crypto Alert App Auto-Upgrade Script

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
LOG_FILE="$PROJECT_DIR/upgrade.log"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOG_FILE"
}

log "Starting Crypto Alert App Upgrade..."

# 1. Navigate to the local app directory (the live instance, not the source!)
cd "$PROJECT_DIR"

# 2. Pull the latest code from GitHub
log "Pulling latest changes from petrafan007/crypto-alert-app..."
# Assuming remote is already set, or we can force it
git fetch origin main || log "Warning: Git fetch failed."
git reset --hard origin/main || log "Warning: Git reset failed."

# 3. Update Python dependencies
log "Updating Python dependencies..."
if [ -d ".venv" ]; then
    source .venv/bin/activate
elif [ -d "venv" ]; then
    source venv/bin/activate
fi
pip install -r requirements.txt | tee -a "$LOG_FILE"

# 4. Update Node dependencies & rebuild frontend
log "Updating Node dependencies and rebuilding frontend..."
cd frontend
npm install | tee -a "$LOG_FILE"
npm run build | tee -a "$LOG_FILE"
cd ..

# 5. Run any database migrations (Optional)
# If using alembic or similar in the future:
# flask db upgrade

# 6. Restart the application service
log "Restarting application..."
if systemctl is-active --quiet crypto-dashboard.service; then
    log "Restarting crypto-dashboard.service..."
    sudo systemctl restart crypto-dashboard.service
fi

# If running manually via python3 main.py (test environment), restart it
if pgrep -f "python3 main.py" > /dev/null; then
    log "Restarting manual python3 main.py instance..."
    pkill -f "python3 main.py" || true
    sleep 2
    nohup python3 main.py > /dev/null 2>&1 &
fi

log "Upgrade Complete! System is back online."

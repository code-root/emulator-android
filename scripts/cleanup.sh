#!/usr/bin/env bash
# =============================================================================
# cleanup.sh — Emergency cleanup (works on both macOS and Linux)
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info() { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }

OS=$(uname -s)

# ---------------------------------------------------------------------------
# 1. Kill orphaned QEMU processes
# ---------------------------------------------------------------------------
info "Killing QEMU processes…"
if [[ "$OS" == "Darwin" ]]; then
    pkill -f "qemu-system-" 2>/dev/null && info "Killed QEMU processes." || info "No QEMU processes running."
    sleep 2
    pkill -9 -f "qemu-system-" 2>/dev/null || true
else
    QEMU_PIDS=$(pgrep -f "qemu-system-" 2>/dev/null || true)
    if [[ -n "$QEMU_PIDS" ]]; then
        echo "$QEMU_PIDS" | xargs kill -TERM 2>/dev/null || true
        sleep 3
        pgrep -f "qemu-system-" | xargs kill -KILL 2>/dev/null || true
        info "QEMU processes killed."
    else
        info "No QEMU processes found."
    fi

    # ---------------------------------------------------------------------------
    # 2. Linux only: detach NBD devices
    # ---------------------------------------------------------------------------
    info "Detaching NBD devices…"
    for i in $(seq 0 7); do
        DEV="/dev/nbd$i"
        [[ -b "$DEV" ]] && qemu-nbd --disconnect "$DEV" 2>/dev/null && info "Disconnected $DEV" || true
    done

    # Clean up stale mount points
    for mp in /tmp/android_fp_*; do
        [[ -d "$mp" ]] || continue
        mountpoint -q "$mp" && umount "$mp" 2>/dev/null && info "Unmounted $mp" || true
        rmdir "$mp" 2>/dev/null || true
    done
fi

# ---------------------------------------------------------------------------
# 3. Remove stale pidfiles
# ---------------------------------------------------------------------------
info "Removing stale pidfiles…"
find "$PROJECT_DIR/instances" -name "qemu.pid" -exec rm -f {} \; 2>/dev/null || true

# ---------------------------------------------------------------------------
# 4. Mark running/booting devices as error in DB
# ---------------------------------------------------------------------------
[[ -d venv ]] && source venv/bin/activate

DB_PATH=$(python3 -c "
import yaml
c = yaml.safe_load(open('config.yaml'))
import os
p = c.get('database', {}).get('path', 'farm.db')
print(os.path.expanduser(p))
" 2>/dev/null || echo "farm.db")

if [[ -f "$DB_PATH" ]]; then
    sqlite3 "$DB_PATH" "
        UPDATE devices
        SET status='error', qemu_pid=NULL, updated_at=datetime('now')
        WHERE status IN ('running','booting');
    " && info "DB updated — running devices marked as error."
fi

info "Cleanup complete."

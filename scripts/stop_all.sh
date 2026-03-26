#!/usr/bin/env bash
# =============================================================================
# stop_all.sh — Stop all running devices
#
# Usage:  ./scripts/stop_all.sh [--force]
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

FORCE=""
[[ "${1:-}" == "--force" ]] && FORCE="--force"

[[ -d venv ]] && source venv/bin/activate

DB_PATH=$(python3 -c "
import yaml
c = yaml.safe_load(open('config.yaml'))
print(c.get('database', {}).get('path', 'farm.db'))
")

# Get all running/booting device IDs
RUNNING_IDS=$(sqlite3 "$DB_PATH" "SELECT device_id FROM devices WHERE status IN ('running','booting');")

if [[ -z "$RUNNING_IDS" ]]; then
    echo "No running devices found."
    exit 0
fi

COUNT=0
for device_id in $RUNNING_IDS; do
    echo "Stopping $device_id…"
    # shellcheck disable=SC2086
    python3 main.py stop $FORCE "$device_id" &
    (( COUNT++ )) || true
done

wait
echo "Stopped $COUNT device(s)."

#!/usr/bin/env bash
# =============================================================================
# start_all.sh — Start all stopped devices
#
# Usage:  ./scripts/start_all.sh [--concurrency N]
#         N = how many devices to start in parallel (default: 4)
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

CONCURRENCY=4
[[ "${1:-}" == "--concurrency" ]] && CONCURRENCY="${2:-4}"

[[ -d venv ]] && source venv/bin/activate

DB_PATH=$(python3 -c "
import yaml
c = yaml.safe_load(open('config.yaml'))
print(c.get('database', {}).get('path', 'farm.db'))
")

# Get all stopped device IDs
STOPPED_IDS=$(sqlite3 "$DB_PATH" "SELECT device_id FROM devices WHERE status='stopped';")

if [[ -z "$STOPPED_IDS" ]]; then
    echo "No stopped devices found."
    exit 0
fi

COUNT=0
RUNNING=0

for device_id in $STOPPED_IDS; do
    # Throttle concurrency
    while (( RUNNING >= CONCURRENCY )); do
        wait -n 2>/dev/null || sleep 1
        RUNNING=$(jobs -r | wc -l)
    done

    echo "Starting $device_id…"
    python3 main.py start "$device_id" &
    (( RUNNING++ )) || true
    (( COUNT++ )) || true
done

# Wait for all background starts to complete
wait

echo "Issued start for $COUNT device(s)."
echo "Poll GET /devices to track boot progress."

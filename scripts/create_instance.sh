#!/usr/bin/env bash
# =============================================================================
# create_instance.sh — Create a new Android emulator instance
#
# Usage:
#   ./scripts/create_instance.sh <name> [profile] [ram_mb] [cpu_cores]
#
# Examples:
#   ./scripts/create_instance.sh bot-01
#   ./scripts/create_instance.sh bot-02 pixel_6
#   ./scripts/create_instance.sh bot-03 samsung_s21 2048 2
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

NAME="${1:-}"
PROFILE="${2:-samsung_s21}"
RAM="${3:-}"
CPUS="${4:-}"

[[ -n "$NAME" ]] || { echo "Usage: $0 <name> [profile] [ram_mb] [cpu_cores]"; exit 1; }

# Activate venv if present
[[ -d venv ]] && source venv/bin/activate

ARGS="--name $NAME --profile $PROFILE"
[[ -n "$RAM" ]]  && ARGS="$ARGS --ram $RAM"
[[ -n "$CPUS" ]] && ARGS="$ARGS --cpus $CPUS"

# shellcheck disable=SC2086
python3 main.py create $ARGS

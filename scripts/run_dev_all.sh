#!/usr/bin/env bash
# تشغيل الباكند + الفرونت معاً (تطوير محلي). إيقاف: Ctrl+C
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

"${ROOT}/scripts/run_dev_local.sh" &
UV_PID=$!
cleanup() {
  kill "${UV_PID}" 2>/dev/null || true
  wait "${UV_PID}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

sleep 2
cd "${ROOT}/frontend"
exec npm run dev

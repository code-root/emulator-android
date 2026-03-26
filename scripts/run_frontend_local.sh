#!/usr/bin/env bash
# واجهة Vite — البروكسي يوجّه /api و /ws إلى localhost:8000 (vite.config.ts)
set -euo pipefail
cd "$(dirname "$0")/../frontend"
exec npm run dev

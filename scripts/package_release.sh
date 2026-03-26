#!/usr/bin/env bash
# بناء الواجهة + تجميع أرشيف توزيع (بدون venv/node_modules وحزم firmware الضخمة)
#
# الاستخدام من جذر المشروع أو:
#   ./scripts/package_release.sh
# اختياري: RELEASE_VERSION=1.0.0 ./scripts/package_release.sh
#
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# RELEASE_VERSION may be git tag e.g. v1.2.0 — strip leading "v"
_raw="${RELEASE_VERSION:-}"
if [[ -n "${_raw}" ]]; then
  VERSION="${_raw#v}"
else
  VERSION="$(tr -d ' \n\r' < "${ROOT}/VERSION" 2>/dev/null || true)"
  if [[ -z "${VERSION}" ]]; then
    VERSION="$(date +%Y%m%d-%H%M)"
  fi
fi
OUT_DIR="${RELEASE_OUT_DIR:-$ROOT/dist}"
mkdir -p "$OUT_DIR"
ARCHIVE="$OUT_DIR/emulator-android-${VERSION}.tar.gz"
TMP_ARCHIVE="$(mktemp "${TMPDIR:-/tmp}/emulator-android-pack.XXXXXX.tar.gz")"
trap 'rm -f "$TMP_ARCHIVE"' EXIT

echo "[package_release] Frontend build…"
cd "$ROOT/frontend"
if [[ ! -d node_modules ]]; then
  npm install
fi
npm run build

echo "[package_release] Creating archive (excluding heavy/local-only paths)…"
cd "$ROOT"
# ملاحظة: حزم firmware/*.zip كبيرة جداً — تُستثنى؛ انسخها يدوياً إلى firmware/ على السيرفر
# الأرشيف يُنشأ في /tmp ثم يُنقل لتفادي تضمين ملف الأرشيف نفسه أثناء المسح
tar -czf "$TMP_ARCHIVE" \
  --exclude='.git' \
  --exclude='frontend/node_modules' \
  --exclude='backend/.venv' \
  --exclude='venv' \
  --exclude='firmware/*.zip' \
  --exclude='firmware/*.ZIP' \
  --exclude='.android-sdk-farm' \
  --exclude='__pycache__' \
  --exclude='.pytest_cache' \
  --exclude='uploads/*.apk' \
  --exclude='uploads/*.tmp' \
  --exclude='dist/*.tar.gz' \
  --exclude='.DS_Store' \
  .

mv -f "$TMP_ARCHIVE" "$ARCHIVE"
trap - EXIT

echo "[package_release] Done: $ARCHIVE"
ls -lh "$ARCHIVE"

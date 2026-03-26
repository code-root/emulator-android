#!/usr/bin/env bash
# تشغيل الباكند محلياً بدون Docker/Postgres — قاعدة SQLite تحت backend/data/
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DB_DIR="${ROOT}/backend/data"
DB_FILE="${DB_DIR}/dev.sqlite"
mkdir -p "${DB_DIR}"
export DATABASE_URL="sqlite+aiosqlite:////${DB_FILE}"
export DEBUG="${DEBUG:-1}"
# أول تشغيل: يُنشئ admin تلقائياً إن كانت القاعدة فارغة
export DEV_SEED_ADMIN_USERNAME="${DEV_SEED_ADMIN_USERNAME:-dev}"
export DEV_SEED_ADMIN_PASSWORD="${DEV_SEED_ADMIN_PASSWORD:-devlocal123}"
export DEV_SEED_ADMIN_EMAIL="${DEV_SEED_ADMIN_EMAIL:-dev@localhost}"

# avdmanager / sdkmanager يحتاجان JDK 17+ — حتى لو كان JAVA_HOME=JDK11 من shell أو IDE.
_java_major() {
  local jb="$1"
  "$jb" -version 2>&1 | head -1 | sed -En 's/.* version "([0-9]+).*/\1/p'
}
_find_java_home_17_plus() {
  if [[ "$(uname -s)" == "Darwin" ]]; then
    local c
    for c in \
      "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home" \
      "/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home" \
      "/opt/homebrew/opt/openjdk@25/libexec/openjdk.jdk/Contents/Home" \
      "/usr/local/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home" \
      "/usr/local/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home"; do
      if [[ -x "${c}/bin/java" ]]; then
        echo "${c}"
        return 0
      fi
    done
    if [[ -x /usr/libexec/java_home ]]; then
      local jh
      jh="$(/usr/libexec/java_home -v 17 2>/dev/null || /usr/libexec/java_home -v 21 2>/dev/null || /usr/libexec/java_home -v 22 2>/dev/null || true)"
      if [[ -n "${jh}" ]]; then
        echo "${jh}"
        return 0
      fi
    fi
  elif [[ "$(uname -s)" == "Linux" ]]; then
    local d
    for d in /usr/lib/jvm/java-25-openjdk-amd64 /usr/lib/jvm/java-21-openjdk-amd64 \
      /usr/lib/jvm/java-17-openjdk-amd64 /usr/lib/jvm/java-17-openjdk; do
      if [[ -x "${d}/bin/java" ]]; then
        echo "${d}"
        return 0
      fi
    done
  fi
  return 1
}
_pick_dev_java_home() {
  local major="" have_ok=0
  if [[ -n "${JAVA_HOME:-}" && -x "${JAVA_HOME}/bin/java" ]]; then
    major="$(_java_major "${JAVA_HOME}/bin/java")"
    if [[ -n "${major}" && "${major}" -ge 17 ]]; then
      have_ok=1
    fi
  fi
  if [[ "${have_ok}" -eq 1 ]]; then
    return 0
  fi
  local found
  found="$(_find_java_home_17_plus || true)"
  if [[ -n "${found}" && -x "${found}/bin/java" ]]; then
    export JAVA_HOME="${found}"
  fi
}
_warn_java_for_android_cli() {
  local jbin
  if [[ -n "${JAVA_HOME:-}" && -x "${JAVA_HOME}/bin/java" ]]; then
    jbin="${JAVA_HOME}/bin/java"
  elif command -v java >/dev/null 2>&1; then
    jbin="$(command -v java)"
  else
    echo "⚠️  لا يوجد java في PATH — ثبّت JDK 17+ (مثلاً: brew install openjdk@17) لإنشاء AVD." >&2
    return
  fi
  local major
  major="$("${jbin}" -version 2>&1 | head -1 | sed -En 's/.* version "([0-9]+).*/\1/p')"
  if [[ -z "${major}" || "${major}" -lt 17 ]]; then
    echo "⚠️  Java للـ AVD: الإصدار الحالي (${major:-غير معروف}) أقل من 17 — avdmanager لن ينجح ولن يُنشأ AVD من التطبيق." >&2
    echo "   macOS: brew install openjdk@17 && export JAVA_HOME=\"\$(/usr/libexec/java_home -v 17)\"" >&2
    echo "   ثم أعد تشغيل هذا السكربت، وثبّت صورة النظام إن لزم:" >&2
    echo "   sdkmanager \"system-images;android-35;google_apis;arm64-v8a\"  # حسب api_level للجهاز" >&2
  else
    echo "✓ Java ${major} لأدوات Android CLI (JAVA_HOME=${JAVA_HOME:-${jbin%/bin/java}})" >&2
  fi
}
_pick_dev_java_home
_warn_java_for_android_cli

cd "${ROOT}/backend"
if [[ ! -d .venv ]]; then
  echo "أنشئ venv أولاً: cd backend && python3.12 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt" >&2
  exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate
echo "=== تسجيل الدخول المحلي (بعد أول إقلاع) ==="
echo "  username: ${DEV_SEED_ADMIN_USERNAME}"
echo "  password: ${DEV_SEED_ADMIN_PASSWORD}"
echo "  POST /api/auth/login  أو واجهة http://localhost:5173"
echo "==========================================="
exec uvicorn main:app --reload --host 0.0.0.0 --port "${APP_PORT:-8000}"

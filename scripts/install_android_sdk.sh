#!/usr/bin/env bash
# =============================================================================
# تثبيت Android SDK + emulator + صورة Android 15 (API 35) لـ AVD
#
# نفس سلسلة الأدوات التي يعتمدها Android Studio (cmdline-tools + emulator + system-images)
# — حزم جاهزة من Google، وليست استنساخاً من GitHub. لشفرة المصدر (QEMU/AOSP) انظر:
#   ./scripts/clone_aosp_emulator_sources.sh
#
# المتغيرات:
#   ANDROID_HOME / ANDROID_SDK_ROOT — الهدف (افتراضي: /opt/android-sdk أو ~/Android/Sdk)
#
# الاستخدام:
#   ./scripts/install_android_sdk.sh
#   ANDROID_HOME="$HOME/android-sdk" ./scripts/install_android_sdk.sh
# =============================================================================
set -euo pipefail

ANDROID_HOME="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}"
if [[ -z "${ANDROID_HOME}" ]]; then
  if [[ -w /opt ]]; then
    ANDROID_HOME="/opt/android-sdk"
  else
    ANDROID_HOME="${HOME}/android-sdk-farm"
  fi
fi
export ANDROID_HOME
export ANDROID_SDK_ROOT="${ANDROID_HOME}"

echo "[install_android_sdk] ANDROID_HOME=${ANDROID_HOME}"

mkdir -p "${ANDROID_HOME}"

need_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "Missing: $1" >&2; exit 1; }; }
need_cmd unzip
if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then
  echo "Missing: curl or wget (لتنزيل command-line tools)" >&2
  exit 1
fi

download_to() {
  local url="$1" dest="$2"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "${url}" -o "${dest}"
  else
    wget -q "${url}" -O "${dest}"
  fi
}

# sdkmanager يتطلب Java 17+ — نتحقق قبل تنزيل الـ zip
_pick_java_17_plus() {
  if [[ -n "${JAVA_HOME:-}" && -x "${JAVA_HOME}/bin/java" ]]; then
    export PATH="${JAVA_HOME}/bin:${PATH}"
    return 0
  fi
  if [[ "$(uname -s)" == "Darwin" ]]; then
    local c
    for c in \
      "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home" \
      "/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home" \
      "/usr/local/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"; do
      if [[ -x "${c}/bin/java" ]]; then
        export JAVA_HOME="${c}"
        export PATH="${JAVA_HOME}/bin:${PATH}"
        return 0
      fi
    done
    if command -v /usr/libexec/java_home >/dev/null 2>&1; then
      local jh
      jh="$(/usr/libexec/java_home -v 17 2>/dev/null || /usr/libexec/java_home -v 21 2>/dev/null || /usr/libexec/java_home -v 25 2>/dev/null || true)"
      if [[ -n "${jh}" && -x "${jh}/bin/java" ]]; then
        export JAVA_HOME="${jh}"
        export PATH="${JAVA_HOME}/bin:${PATH}"
        return 0
      fi
    fi
  fi
  return 1
}

_java_major() {
  java -version 2>&1 | head -1 | sed -En 's/.* version "([0-9]+).*/\1/p'
}

_pick_java_17_plus || true
need_cmd java
jm="$(_java_major)"
if [[ -z "${jm}" || "${jm}" -lt 17 ]]; then
  echo "sdkmanager يتطلب Java 17 أو أحدث. الحالي: $(java -version 2>&1 | head -1)" >&2
  echo "macOS: brew install openjdk@17 && export JAVA_HOME=\"\$(/usr/libexec/java_home -v 17)\"" >&2
  exit 1
fi
echo "[install_android_sdk] JAVA_HOME=${JAVA_HOME:-}"

CLT_ZIP="${TMPDIR:-/tmp}/cmdline-tools-android.zip"
# أداة سطر الأوامر — يُحدَّث الرقم عند الحاجة من: https://developer.android.com/studio#command-line-tools-only
SDK_TOOLS_URL="${ANDROID_CMDLINE_TOOLS_URL:-https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip}"

if [[ "$(uname -s)" == "Darwin" ]]; then
  SDK_TOOLS_URL="${ANDROID_CMDLINE_TOOLS_URL:-https://dl.google.com/android/repository/commandlinetools-mac-11076708_latest.zip}"
fi

echo "[install_android_sdk] Downloading command-line tools…"
download_to "${SDK_TOOLS_URL}" "${CLT_ZIP}"

rm -rf "${ANDROID_HOME}/cmdline-tools/latest"
mkdir -p "${ANDROID_HOME}/cmdline-tools"
unzip -q -o "${CLT_ZIP}" -d "${ANDROID_HOME}/cmdline-tools"
# المحتوى: cmdline-tools/bin → ننقله إلى latest/
if [[ -d "${ANDROID_HOME}/cmdline-tools/cmdline-tools" ]]; then
  mv "${ANDROID_HOME}/cmdline-tools/cmdline-tools" "${ANDROID_HOME}/cmdline-tools/latest"
else
  echo "Unexpected cmdline-tools zip layout" >&2
  exit 1
fi

export PATH="${ANDROID_HOME}/cmdline-tools/latest/bin:${ANDROID_HOME}/platform-tools:${ANDROID_HOME}/emulator:${PATH}"

echo "[install_android_sdk] Accepting licenses…"
yes | sdkmanager --sdk_root="${ANDROID_HOME}" --licenses >/dev/null 2>&1 || true

HOST_ARCH="$(uname -m)"
if [[ "${HOST_ARCH}" == "aarch64" || "${HOST_ARCH}" == "arm64" ]]; then
  SYSIMG="system-images;android-35;google_apis;arm64-v8a"
else
  SYSIMG="system-images;android-35;google_apis;x86_64"
fi

echo "[install_android_sdk] Installing platform-tools, emulator, android-35, ${SYSIMG}…"
yes | sdkmanager --sdk_root="${ANDROID_HOME}" \
  "platform-tools" \
  "emulator" \
  "platforms;android-35" \
  "${SYSIMG}"

echo ""
echo "Done. أضف إلى shell:"
echo "  export ANDROID_HOME=\"${ANDROID_HOME}\""
echo "  export ANDROID_SDK_ROOT=\"\${ANDROID_HOME}\""
echo "  export PATH=\"\${ANDROID_HOME}/cmdline-tools/latest/bin:\${ANDROID_HOME}/platform-tools:\${ANDROID_HOME}/emulator:\${PATH}\""
echo ""
echo "للتحقق: avdmanager list device && sdkmanager --list_installed | head"

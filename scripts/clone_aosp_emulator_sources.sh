#!/usr/bin/env bash
# =============================================================================
# استنساخ شفرة AOSP المرتبطة بالمحاكي / QEMU / النظام من مرآة GitHub (aosp-mirror)
#
# هذا لـ **القراءة، التطوير، أو بناء مخصص** — وليس بديلاً تلقائياً عن ثنائي
# `emulator` الذي يثبّته install_android_sdk.sh (نفس مسار Android Studio).
#
# المتغيرات:
#   AOSP_EMULATOR_SRC_DIR — مجلد الوجهة (افتراضي: ~/aosp-emulator-sources)
#   AOSP_MIRROR_ORG       — منظمة المرآة (افتراضي: aosp-mirror)
#   CLONE_DEPTH           — عمق clone الضحل (افتراضي: 1)
#   CLONE_KERNEL_COMMON=1 — يضيف kernel_common (ضخم جداً؛ اختياري)
#
# الاستخدام:
#   ./scripts/clone_aosp_emulator_sources.sh
#   CLONE_KERNEL_COMMON=1 ./scripts/clone_aosp_emulator_sources.sh
# =============================================================================
set -euo pipefail

need_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "Missing: $1" >&2; exit 1; }; }
need_cmd git

AOSP_EMULATOR_SRC_DIR="${AOSP_EMULATOR_SRC_DIR:-${HOME}/aosp-emulator-sources}"
AOSP_MIRROR_ORG="${AOSP_MIRROR_ORG:-aosp-mirror}"
CLONE_DEPTH="${CLONE_DEPTH:-1}"

# مستودعات مركّزة على طبقة المحاكي + أدوات النظام الأساسية (ADB يأتي من platform-tools الجاهزة)
DEFAULT_REPOS=(
  platform_external_qemu
  platform_system_core
)

REPOS=("${DEFAULT_REPOS[@]}")
if [[ "${CLONE_KERNEL_COMMON:-0}" == "1" ]]; then
  REPOS+=(kernel_common)
  echo "[clone_aosp_emulator_sources] WARNING: kernel_common كبير جداً وسيستغرق وقتاً ومساحة."
fi

mkdir -p "${AOSP_EMULATOR_SRC_DIR}"
echo "[clone_aosp_emulator_sources] Target: ${AOSP_EMULATOR_SRC_DIR}"
echo "[clone_aosp_emulator_sources] Mirror: https://github.com/${AOSP_MIRROR_ORG}/<repo>"

clone_or_update() {
  local name="$1"
  local url="https://github.com/${AOSP_MIRROR_ORG}/${name}.git"
  local dest="${AOSP_EMULATOR_SRC_DIR}/${name}"

  if [[ -d "${dest}/.git" ]]; then
    echo "[clone_aosp_emulator_sources] Updating ${name}…"
    git -C "${dest}" pull --ff-only || echo "  (pull skipped or failed — يمكنك git pull يدوياً داخل ${dest})"
  else
    echo "[clone_aosp_emulator_sources] Cloning ${name} (depth=${CLONE_DEPTH})…"
    git clone --depth "${CLONE_DEPTH}" "${url}" "${dest}"
  fi
}

for repo in "${REPOS[@]}"; do
  clone_or_update "${repo}"
done

echo ""
echo "تم. للمسار الرسمي لبناء AOSP كاملاً استخدم أداة repo ودليل source.android.com"
echo "ولتشغيل المحاكي في هذا المشروع: ./scripts/install_android_sdk.sh ثم ضبط ANDROID_HOME."

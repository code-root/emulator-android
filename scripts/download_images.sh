#!/usr/bin/env bash
# =============================================================================
# download_images.sh — Download Android ARM64 images for Apple Silicon Mac
#                      (also works on Intel Mac with x86_64 images)
#
# For Apple Silicon (arm64):
#   Downloads Android emulator ARM64 system image via Android SDK Manager.
#   These are the exact images used by Android Studio — optimised for QEMU.
#
# For Intel Mac (x86_64):
#   Downloads Android-x86 9.0-r2 ISO and extracts kernel + initrd.
#
# Usage:
#   ./scripts/download_images.sh
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
step()  { echo -e "${CYAN}[STEP]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

ARCH=$(uname -m)
IMAGES_DIR="$HOME/android-images"
mkdir -p "$IMAGES_DIR"

# Activate venv
[[ -d venv ]] && source venv/bin/activate

echo ""
echo -e "${CYAN}=====================================================${NC}"
echo -e "${CYAN}  Android Image Download  (arch: $ARCH)${NC}"
echo -e "${CYAN}=====================================================${NC}"
echo ""

# =============================================================================
# Apple Silicon (arm64) — use Android SDK emulator images
# =============================================================================
if [[ "$ARCH" == "arm64" ]]; then

    step "ARM64 path — downloading via Android SDK cmdline-tools…"

    # ---------------------------------------------------------------------------
    # 1. Install cmdline-tools via Homebrew or direct download
    # ---------------------------------------------------------------------------
    SDK_DIR="$HOME/android-sdk"
    SDKMANAGER="$SDK_DIR/cmdline-tools/latest/bin/sdkmanager"

    if ! command -v sdkmanager &>/dev/null && [[ ! -f "$SDKMANAGER" ]]; then
        info "Downloading Android SDK cmdline-tools…"
        # Latest cmdline-tools for macOS (Apple Silicon)
        CMDTOOLS_ZIP="$IMAGES_DIR/cmdline-tools.zip"
        curl -L --progress-bar \
            "https://dl.google.com/android/repository/commandlinetools-mac-11076708_latest.zip" \
            -o "$CMDTOOLS_ZIP"

        mkdir -p "$SDK_DIR/cmdline-tools"
        unzip -q "$CMDTOOLS_ZIP" -d "$SDK_DIR/cmdline-tools"
        # The zip extracts as 'cmdline-tools/', rename to 'latest'
        if [[ -d "$SDK_DIR/cmdline-tools/cmdline-tools" ]]; then
            mv "$SDK_DIR/cmdline-tools/cmdline-tools" "$SDK_DIR/cmdline-tools/latest"
        fi
        rm -f "$CMDTOOLS_ZIP"
        info "SDK cmdline-tools installed at $SDK_DIR"
    fi

    SDKMANAGER=$(command -v sdkmanager 2>/dev/null || echo "$SDKMANAGER")
    export ANDROID_SDK_ROOT="$SDK_DIR"
    export ANDROID_HOME="$SDK_DIR"

    # ---------------------------------------------------------------------------
    # 2. Accept licenses
    # ---------------------------------------------------------------------------
    info "Accepting Android SDK licenses…"
    yes | "$SDKMANAGER" --licenses >/dev/null 2>&1 || true

    # ---------------------------------------------------------------------------
    # 3. Download ARM64 system image (Android 12 / API 31, Google APIs, arm64-v8a)
    # ---------------------------------------------------------------------------
    SYSTEM_IMAGE_PKG="system-images;android-31;google_apis;arm64-v8a"
    info "Downloading system image: $SYSTEM_IMAGE_PKG (~1.5 GB)…"
    "$SDKMANAGER" "$SYSTEM_IMAGE_PKG" "platform-tools" "emulator"

    # ---------------------------------------------------------------------------
    # 4. Create an AVD and export its disk images for QEMU
    # ---------------------------------------------------------------------------
    AVD_NAME="farm_base"
    AVDMANAGER=$(dirname "$SDKMANAGER")/avdmanager

    info "Creating AVD: $AVD_NAME…"
    echo "no" | "$AVDMANAGER" create avd \
        -n "$AVD_NAME" \
        -k "$SYSTEM_IMAGE_PKG" \
        --force 2>/dev/null || true

    # Android emulator images live in ~/.android/avd/<name>.avd/
    AVD_DIR="$HOME/.android/avd/${AVD_NAME}.avd"
    SDK_IMG_DIR="$SDK_DIR/system-images/android-31/google_apis/arm64-v8a"

    # ---------------------------------------------------------------------------
    # 5. Convert system.img + userdata.img to qcow2
    # ---------------------------------------------------------------------------
    info "Converting system.img to qcow2…"
    SYSTEM_IMG="$SDK_IMG_DIR/system.img"
    [[ -f "$SYSTEM_IMG" ]] || error "system.img not found at $SYSTEM_IMG"

    qemu-img convert -f raw -O qcow2 "$SYSTEM_IMG" "$IMAGES_DIR/android-arm64.qcow2"

    info "Converting userdata.img…"
    USERDATA_IMG="$SDK_IMG_DIR/userdata.img"
    if [[ -f "$USERDATA_IMG" ]]; then
        qemu-img convert -f raw -O qcow2 "$USERDATA_IMG" "$IMAGES_DIR/android-arm64-data.qcow2"
    else
        qemu-img create -f qcow2 "$IMAGES_DIR/android-arm64-data.qcow2" 8G
    fi

    # ---------------------------------------------------------------------------
    # 6. Copy kernel and ramdisk
    # ---------------------------------------------------------------------------
    info "Copying kernel and ramdisk…"
    for KNAME in kernel-ranchu kernel-qemu-armv7; do
        [[ -f "$SDK_IMG_DIR/$KNAME" ]] && cp "$SDK_IMG_DIR/$KNAME" "$IMAGES_DIR/kernel-ranchu" && break
    done
    [[ -f "$SDK_IMG_DIR/ramdisk.img" ]] && cp "$SDK_IMG_DIR/ramdisk.img" "$IMAGES_DIR/ramdisk.img"

    [[ -f "$IMAGES_DIR/kernel-ranchu" ]] || error "Kernel not found in $SDK_IMG_DIR"
    [[ -f "$IMAGES_DIR/ramdisk.img"  ]] || error "ramdisk.img not found in $SDK_IMG_DIR"

    info "ARM64 images ready in $IMAGES_DIR"

    # ---------------------------------------------------------------------------
    # 7. Store encryptionkey if present (needed for some Android versions)
    # ---------------------------------------------------------------------------
    [[ -f "$SDK_IMG_DIR/encryptionkey.img" ]] && \
        cp "$SDK_IMG_DIR/encryptionkey.img" "$IMAGES_DIR/" || true

    # ---------------------------------------------------------------------------
    # 8. Test boot (optional — press Ctrl-C to skip)
    # ---------------------------------------------------------------------------
    echo ""
    echo "  Images are ready.  Press ENTER to do a quick 30-second test boot,"
    echo "  or Ctrl-C to skip (you can always start via: python3 main.py serve)."
    read -r -t 10 || true

    echo "  Launching test boot (30s)… close the window or wait."
    timeout 30 qemu-system-aarch64 \
        -machine virt,highmem=off \
        -accel hvf \
        -cpu host \
        -m 2048 \
        -smp 2 \
        -kernel "$IMAGES_DIR/kernel-ranchu" \
        -initrd "$IMAGES_DIR/ramdisk.img" \
        -drive "file=$IMAGES_DIR/android-arm64.qcow2,format=qcow2,if=virtio" \
        -netdev "user,id=net0,hostfwd=tcp::5560-:5555" \
        -device "virtio-net-pci,netdev=net0" \
        -display none -nographic \
        -append "console=ttyAMA0 androidboot.hardware=ranchu androidboot.selinux=permissive" \
        2>/dev/null || true

# =============================================================================
# Intel Mac (x86_64) — Android-x86 ISO
# =============================================================================
else

    step "x86_64 path — downloading Android-x86 9.0-r2 ISO…"

    ISO_PATH="$IMAGES_DIR/android-x86_64-9.0-r2.iso"
    QCOW2_PATH="$IMAGES_DIR/android-x86-9.0.qcow2"
    ISO_URL="https://sourceforge.net/projects/android-x86/files/Release%209.0/android-x86_64-9.0-r2.iso/download"

    # Download ISO
    if [[ ! -f "$ISO_PATH" ]]; then
        info "Downloading Android-x86 9.0-r2 ISO (~900 MB)…"
        curl -L --progress-bar -o "$ISO_PATH" "$ISO_URL"
    else
        info "ISO already exists — skipping download."
    fi

    # Create base qcow2
    if [[ ! -f "$QCOW2_PATH" ]]; then
        qemu-img create -f qcow2 "$QCOW2_PATH" 16G
        info "Created base qcow2: $QCOW2_PATH"
    fi

    # Extract kernel + initrd (bsdtar is built into macOS)
    info "Extracting kernel and initrd from ISO…"
    TMP=$(mktemp -d)
    bsdtar -C "$TMP" -xf "$ISO_PATH" 2>/dev/null || true
    find "$TMP" -name "kernel" | head -1 | xargs -I{} cp {} "$IMAGES_DIR/kernel" 2>/dev/null || true
    find "$TMP" -name "initrd.img" | head -1 | xargs -I{} cp {} "$IMAGES_DIR/initrd.img" 2>/dev/null || true
    rm -rf "$TMP"

    [[ -f "$IMAGES_DIR/kernel" ]] || warn "Could not extract kernel — try manual extraction."

    # One-time install
    echo ""
    echo "  Press ENTER to open the Android-x86 installer (GUI window),"
    echo "  or Ctrl-C to skip."
    read -r
    qemu-system-x86_64 \
        -accel hvf -cpu host -m 2048 -smp 2 \
        -drive "file=$QCOW2_PATH,format=qcow2,if=virtio" \
        -cdrom "$ISO_PATH" -boot d \
        -display cocoa \
        -netdev user,id=net0 -device virtio-net-pci,netdev=net0 || true
fi

# ---------------------------------------------------------------------------
# Update config.yaml with actual image paths
# ---------------------------------------------------------------------------
info "Updating config.yaml with image paths…"
python3 - <<PYEOF
import yaml, os
home = os.path.expanduser("~")
arch = os.uname().machine
cfg_path = "config.yaml"
with open(cfg_path) as f:
    cfg = yaml.safe_load(f)

images = f"{home}/android-images"
if arch == "arm64":
    cfg["emulator"]["base_image"]  = f"{images}/android-arm64.qcow2"
    cfg["emulator"]["kernel_path"] = f"{images}/kernel-ranchu"
    cfg["emulator"]["initrd_path"] = f"{images}/ramdisk.img"
else:
    cfg["emulator"]["base_image"]  = f"{images}/android-x86-9.0.qcow2"
    cfg["emulator"]["kernel_path"] = f"{images}/kernel"
    cfg["emulator"]["initrd_path"] = f"{images}/initrd.img"

with open(cfg_path, "w") as f:
    yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)
print("  config.yaml updated.")
PYEOF

echo ""
echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}  Images ready!${NC}"
echo ""
echo "  Arch   : $ARCH"
echo "  Images : $IMAGES_DIR"
echo ""
echo "  Generate an API key then start:"
echo ""
echo -e "    ${CYAN}source venv/bin/activate${NC}"
echo -e "    ${CYAN}python3 main.py genkey --label default${NC}"
echo -e "    ${CYAN}python3 main.py serve${NC}"
echo -e "${GREEN}============================================================${NC}"

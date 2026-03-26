#!/usr/bin/env bash
# =============================================================================
# setup.sh — One-time environment setup for the Android Emulator Farm
#
# Run once as root (or with sudo) on a fresh Linux host.
# Safe to re-run; all operations are idempotent.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 1. Check Linux + root
# ---------------------------------------------------------------------------
[[ "$(uname -s)" == "Linux" ]] || error "This script requires Linux."
[[ "$EUID" -eq 0 ]] || error "Please run as root: sudo $0"

# ---------------------------------------------------------------------------
# 2. KVM support
# ---------------------------------------------------------------------------
info "Checking KVM support…"
if [[ ! -e /dev/kvm ]]; then
    if grep -qE '(vmx|svm)' /proc/cpuinfo; then
        modprobe kvm
        modprobe kvm_intel 2>/dev/null || modprobe kvm_amd 2>/dev/null || true
    else
        error "CPU does not support hardware virtualisation (no vmx/svm in /proc/cpuinfo)."
    fi
fi
[[ -e /dev/kvm ]] || error "/dev/kvm still missing after modprobe."
info "KVM OK ($(ls -la /dev/kvm | awk '{print $1, $3, $4}'))"

# ---------------------------------------------------------------------------
# 3. Install system packages
# ---------------------------------------------------------------------------
info "Installing required packages…"

# Detect package manager
if command -v apt-get &>/dev/null; then
    apt-get update -qq
    apt-get install -y --no-install-recommends \
        qemu-system-x86 \
        qemu-utils \
        qemu-kvm \
        adb \
        android-tools-adb \
        nbd-client \
        qemu-nbd \
        redsocks \
        sqlite3 \
        python3 \
        python3-pip \
        python3-venv \
        util-linux \
        parted \
        fdisk
elif command -v dnf &>/dev/null; then
    dnf install -y \
        qemu-system-x86 \
        qemu-img \
        qemu-kvm \
        android-tools \
        nbd \
        redsocks \
        sqlite \
        python3 \
        python3-pip \
        util-linux
else
    warn "Unknown package manager — install packages manually."
fi

# ---------------------------------------------------------------------------
# 4. Load NBD kernel module
# ---------------------------------------------------------------------------
info "Loading NBD kernel module…"
modprobe nbd max_part=8
echo "nbd" >> /etc/modules-load.d/nbd.conf 2>/dev/null || true
# Persist the option
echo "options nbd max_part=8" > /etc/modprobe.d/nbd.conf
info "NBD module loaded (max_part=8)"

# ---------------------------------------------------------------------------
# 5. Verify qemu-nbd is available
# ---------------------------------------------------------------------------
command -v qemu-nbd >/dev/null || error "qemu-nbd not found in PATH after installation."
info "qemu-nbd: $(command -v qemu-nbd)"

# ---------------------------------------------------------------------------
# 6. Create directory structure
# ---------------------------------------------------------------------------
info "Creating directory structure…"
mkdir -p \
    "$PROJECT_DIR/instances" \
    "$PROJECT_DIR/logs" \
    /opt/android-images

# ---------------------------------------------------------------------------
# 7. Python virtualenv and dependencies
# ---------------------------------------------------------------------------
info "Setting up Python virtualenv…"
cd "$PROJECT_DIR"
if [[ ! -d venv ]]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
info "Python dependencies installed."

# ---------------------------------------------------------------------------
# 8. Initialise the database
# ---------------------------------------------------------------------------
info "Initialising SQLite database…"
python3 main.py migrate
info "Database ready."

# ---------------------------------------------------------------------------
# 9. Generate initial API key
# ---------------------------------------------------------------------------
info "Generating initial API key…"
INITIAL_KEY=$(python3 main.py genkey --label "default" 2>&1 | grep -A1 "API Key" | tail -1 | tr -d ' ')
echo ""
echo "============================================================"
echo "  INITIAL API KEY (copy now — shown only once)"
echo "  $INITIAL_KEY"
echo "============================================================"
echo ""

# ---------------------------------------------------------------------------
# 10. Android image instructions
# ---------------------------------------------------------------------------
echo ""
info "--------- ANDROID IMAGE SETUP (manual step) ---------"
echo ""
echo "Download an Android-x86 9.0 ISO from https://www.android-x86.org/download"
echo "then run the following to prepare the base image:"
echo ""
echo "  # Create a base qcow2 image (16 GB)"
echo "  qemu-img create -f qcow2 /opt/android-images/android-x86-9.0.qcow2 16G"
echo ""
echo "  # Boot from ISO to install Android (one-time):"
echo "  qemu-system-x86_64 -enable-kvm -m 2048 -smp 2 -cpu host \\"
echo "    -drive file=/opt/android-images/android-x86-9.0.qcow2,format=qcow2 \\"
echo "    -cdrom android-x86_64-9.0-r2.iso \\"
echo "    -boot d -display sdl"
echo ""
echo "  # After installation, extract kernel and initrd from the installed image:"
echo "  scripts/extract_kernel.sh  (see that script for instructions)"
echo ""
echo "  # Set base image as read-only to protect it:"
echo "  chmod 444 /opt/android-images/android-x86-9.0.qcow2"
echo ""

info "Setup complete!  Start the server with:  python3 main.py serve"

#!/usr/bin/env bash
# =============================================================================
# setup_mac.sh — One-time setup for macOS (Intel & Apple Silicon)
#
# Installs all dependencies via Homebrew, initialises the DB, generates
# an API key, and prints next steps.
#
# Usage:  ./scripts/setup_mac.sh
#         (does NOT require sudo — Homebrew handles permissions)
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

ARCH=$(uname -m)   # arm64 or x86_64

echo ""
echo -e "${CYAN}=====================================================${NC}"
echo -e "${CYAN}  Android Emulator Farm — macOS Setup${NC}"
echo -e "${CYAN}  Architecture: $ARCH${NC}"
echo -e "${CYAN}=====================================================${NC}"
echo ""

# ---------------------------------------------------------------------------
# 1. Homebrew
# ---------------------------------------------------------------------------
step "1/8  Checking Homebrew…"
if ! command -v brew &>/dev/null; then
    info "Installing Homebrew…"
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Add brew to PATH for Apple Silicon
    if [[ "$ARCH" == "arm64" ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    fi
fi
info "Homebrew: $(brew --version | head -1)"

# ---------------------------------------------------------------------------
# 2. QEMU
# ---------------------------------------------------------------------------
step "2/8  Installing QEMU…"
brew install qemu 2>/dev/null || brew upgrade qemu 2>/dev/null || true
QEMU_BIN=""
if [[ "$ARCH" == "arm64" ]]; then
    QEMU_BIN="qemu-system-aarch64"
else
    QEMU_BIN="qemu-system-x86_64"
fi
command -v "$QEMU_BIN" >/dev/null || error "$QEMU_BIN not found after brew install qemu"
info "QEMU: $(qemu-img --version | head -1)"

# ---------------------------------------------------------------------------
# 3. ADB
# ---------------------------------------------------------------------------
step "3/8  Installing ADB (android-platform-tools)…"
brew install android-platform-tools 2>/dev/null || brew upgrade android-platform-tools 2>/dev/null || true
command -v adb >/dev/null || error "adb not found"
info "ADB: $(adb --version | head -1)"

# ---------------------------------------------------------------------------
# 4. e2fsprogs (for ext4 filesystem tools: debugfs, e2fsck)
#    Used for offline build.prop patching inside Android images
# ---------------------------------------------------------------------------
step "4/8  Installing e2fsprogs (ext4 tools)…"
brew install e2fsprogs 2>/dev/null || brew upgrade e2fsprogs 2>/dev/null || true
E2FS_PREFIX=$(brew --prefix e2fsprogs)
export PATH="$E2FS_PREFIX/sbin:$E2FS_PREFIX/bin:$PATH"
command -v debugfs >/dev/null && info "debugfs: $(debugfs 2>&1 | head -1 || true)" || warn "debugfs not in PATH — fingerprint patching will use ADB fallback"

# ---------------------------------------------------------------------------
# 5. Python dependencies
# ---------------------------------------------------------------------------
step "5/8  Installing Python dependencies…"
if ! command -v python3 &>/dev/null; then
    brew install python@3.11
fi
PYTHON=$(command -v python3.11 2>/dev/null || command -v python3)
info "Python: $($PYTHON --version)"

if [[ ! -d "$PROJECT_DIR/venv" ]]; then
    $PYTHON -m venv "$PROJECT_DIR/venv"
fi
source "$PROJECT_DIR/venv/bin/activate"
pip install --quiet --upgrade pip
pip install --quiet -r "$PROJECT_DIR/requirements.txt"
info "Python packages installed."

# ---------------------------------------------------------------------------
# 6. HVF check (Hypervisor.framework — macOS equivalent of KVM)
# ---------------------------------------------------------------------------
step "6/8  Checking HVF (Hypervisor.framework)…"
if sysctl kern.hv_support 2>/dev/null | grep -q "1"; then
    info "HVF supported — QEMU will use hardware acceleration."
else
    warn "HVF not available — QEMU will run in software emulation (TCG, slower)."
fi

# ---------------------------------------------------------------------------
# 7. Directories and config
# ---------------------------------------------------------------------------
step "7/8  Creating directories and updating config…"
mkdir -p "$PROJECT_DIR/instances" "$PROJECT_DIR/logs" "$HOME/android-images"

# Patch config.yaml for macOS paths and architecture
python3 - <<'PYEOF'
import yaml, os, sys

cfg_path = "config.yaml"
with open(cfg_path) as f:
    cfg = yaml.safe_load(f)

arch = os.uname().machine  # arm64 or x86_64
home = os.path.expanduser("~")

cfg["emulator"]["base_image"]    = f"{home}/android-images/android-arm64.qcow2"
cfg["emulator"]["kernel_path"]   = f"{home}/android-images/kernel-ranchu"
cfg["emulator"]["initrd_path"]   = f"{home}/android-images/ramdisk.img"
cfg["emulator"]["instances_dir"] = os.path.abspath("instances")
cfg["database"]["path"]          = os.path.abspath("farm.db")
cfg["logging"]["dir"]            = os.path.abspath("logs")
cfg["qemu"]["kvm_enabled"]       = False
cfg["qemu"]["hvf_enabled"]       = True
cfg["qemu"]["arch"]              = arch
if arch == "arm64":
    cfg["qemu"]["binary"] = "qemu-system-aarch64"
else:
    cfg["qemu"]["binary"] = "qemu-system-x86_64"

with open(cfg_path, "w") as f:
    yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)

print(f"  config.yaml updated (arch={arch})")
PYEOF

# ---------------------------------------------------------------------------
# 8. DB init + API key
# ---------------------------------------------------------------------------
step "8/8  Initialising database and generating API key…"
source "$PROJECT_DIR/venv/bin/activate"
python3 main.py migrate

echo ""
echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}  Setup complete!${NC}"
echo ""
echo "  Architecture : $ARCH"
echo "  Acceleration : HVF (Hypervisor.framework)"
echo ""
echo "  Next step — download the Android ARM64 image:"
echo ""
echo -e "    ${CYAN}./scripts/download_images.sh${NC}"
echo ""
echo "  Then start the server:"
echo ""
echo -e "    ${CYAN}source venv/bin/activate && python3 main.py serve${NC}"
echo -e "${GREEN}============================================================${NC}"

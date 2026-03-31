"""
Samsung System Image Preparation for AVD.

Extracts a usable system.img (or unpacks APKs) from Samsung AP firmware,
then configures the emulator to boot with the real Samsung One UI system partition.

How it works:
  1. Samsung AP tar.md5 → super.img (dynamic) or system.img (legacy)
  2. super.img → system.img via lpunpack (Android dynamic partitions tool)
  3. system.img (sparse ext4) → raw ext4 via simg2img
  4. Raw ext4 → mount + copy Samsung APKs  (requires root / loop mount)
     OR use the raw image directly with `emulator -system`

Emulator flag:  emulator -avd NAME -system /path/to/samsung_system.img
  - This replaces the AOSP system partition with Samsung's real system
  - Kernel + vendor stay AOSP for hardware compatibility
  - Result: Samsung One UI apps boot on AOSP kernel

Requirements (host tools):
  - simg2img   (android-tools / android-sdk)
  - lpunpack   (from AOSP build tools, or prebuilt)
  - Both are optional — fall back to APK extraction mode if unavailable.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import struct
import tarfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── tool detection ────────────────────────────────────────────────────────────

def _find_tool(name: str) -> Optional[str]:
    return shutil.which(name)


def _has_simg2img() -> bool:
    return bool(_find_tool("simg2img") or _find_tool("img2simg"))


def _has_lpunpack() -> bool:
    return bool(_find_tool("lpunpack"))


# ── Samsung AP tar structure ──────────────────────────────────────────────────

# Members inside AP_*.tar.md5 that we care about (case-insensitive prefix match)
_AP_IMAGES_OF_INTEREST = (
    "super.img",           # Android 10+ dynamic partitions (contains system+vendor+...)
    "system.img",          # Legacy / some AP tars include system.img directly
    "system.img.lz4",      # LZ4-compressed system image
    "super.img.lz4",
    "vendor.img",
    "vendor.img.lz4",
    "boot.img",
)

_SAMSUNG_APP_DIRS = (
    "system/app",
    "system/priv-app",
    "system/framework",
    "system/lib",
    "system/lib64",
)

# Samsung APKs worth extracting and sideloading on AOSP
_SAMSUNG_PRIORITY_APKS: List[Tuple[str, str]] = [
    # (path-fragment-inside-system, friendly-name)
    ("SBrowser",           "Samsung Internet"),
    ("SamsungHealth",      "Samsung Health"),
    ("SamsungNotes",       "Samsung Notes"),
    ("SamsungClock",       "Samsung Clock"),
    ("SamsungCalculator",  "Samsung Calculator"),
    ("SamsungContacts",    "Samsung Contacts"),
    ("SamsungGallery",     "Samsung Gallery"),
    ("SamsungMessages",    "Samsung Messages"),
    ("SamsungCamera",      "Samsung Camera"),
    ("SamsungKeyboard",    "Samsung Keyboard"),
    ("GalaxyStore",        "Galaxy Store"),
    ("ThemeCenter",        "Theme Center"),
    ("Bixby",              "Bixby"),
    ("SecureFolder",       "Secure Folder"),
    ("SmartThings",        "SmartThings"),
]


# ── Main class ────────────────────────────────────────────────────────────────

class SamsungSystemImagePrep:
    """
    Prepares Samsung system image components for use with the Android emulator.

    Usage:
        prep = SamsungSystemImagePrep(firmware_dir=Path("firmware/SM-G996B"))
        result = await prep.prepare()
        if result["system_img"]:
            # Pass to emulator: -system result["system_img"]
        if result["apks"]:
            # Sideload result["apks"] after boot
    """

    def __init__(self, firmware_dir: Path, work_dir: Optional[Path] = None):
        self.firmware_dir = Path(firmware_dir)
        self.work_dir = Path(work_dir) if work_dir else self.firmware_dir / "_prep"
        self.work_dir.mkdir(parents=True, exist_ok=True)

    # ── public API ────────────────────────────────────────────────────────────

    async def prepare(self) -> Dict:
        """
        Full pipeline: AP tar → system.img (or APK list).

        Returns:
          {
            "system_img":  str | None,   # path to system.img ready for -system flag
            "vendor_img":  str | None,
            "boot_img":    str | None,
            "apks":        [{path, name, package}],  # extracted APKs
            "mode":        "system_image" | "apk_sideload" | "none",
            "error":       str | None,
          }
        """
        result = {
            "system_img": None,
            "vendor_img": None,
            "boot_img":   None,
            "apks":       [],
            "mode":       "none",
            "error":      None,
        }

        ap_tar = self._find_ap_tar()
        if not ap_tar:
            result["error"] = "No AP_*.tar.md5 found in firmware_dir"
            return result

        logger.info("Preparing Samsung system image from %s", ap_tar.name)

        # Step 1: extract images from AP tar
        images = await self._extract_images_from_tar(ap_tar)
        if not images:
            result["error"] = "Could not extract images from AP tar"
            return result

        # Step 2: decompress .lz4 images if present
        for key, path in list(images.items()):
            if path.suffix == ".lz4":
                decompressed = await self._decompress_lz4(path)
                if decompressed:
                    images[key] = decompressed

        # Step 3: handle super.img (dynamic partitions) → system.img
        if "super.img" in images and _has_lpunpack():
            unpacked = await self._lpunpack_super(images["super.img"])
            images.update(unpacked)

        # Step 4a: if we have system.img — convert sparse → raw if needed
        if "system.img" in images:
            raw = await self._ensure_raw_ext4(images["system.img"])
            if raw:
                images["system.img"] = raw
                result["system_img"] = str(raw)
                result["mode"] = "system_image"
                logger.info("Samsung system.img ready: %s", raw)

        if "vendor.img" in images:
            raw_v = await self._ensure_raw_ext4(images["vendor.img"])
            if raw_v:
                result["vendor_img"] = str(raw_v)

        if "boot.img" in images:
            result["boot_img"] = str(images["boot.img"])

        # Step 4b: extract APKs from system.img (always — even if system_image mode works)
        if "system.img" in images:
            apks = await self._extract_apks_from_image(images["system.img"])
            result["apks"] = apks
            if apks and result["mode"] == "none":
                result["mode"] = "apk_sideload"

        return result

    async def extract_apks_only(self) -> List[Dict]:
        """
        Lighter pipeline: extract Samsung APKs from AP tar without preparing system.img.
        Useful when simg2img/lpunpack are unavailable.
        """
        ap_tar = self._find_ap_tar()
        if not ap_tar:
            return []
        return await self._extract_apks_directly_from_tar(ap_tar)

    # ── internal helpers ──────────────────────────────────────────────────────

    def _find_ap_tar(self) -> Optional[Path]:
        for f in self.firmware_dir.iterdir():
            if f.name.upper().startswith("AP_") and f.suffix in (".md5", ".tar", ".lz4"):
                return f
        return None

    async def _extract_images_from_tar(self, tar_path: Path) -> Dict[str, Path]:
        """Extract .img files from AP tar into work_dir."""
        images: Dict[str, Path] = {}
        try:
            with tarfile.open(tar_path, "r:*") as tf:
                for member in tf.getmembers():
                    bname = Path(member.name).name.lower()
                    for candidate in _AP_IMAGES_OF_INTEREST:
                        if bname == candidate or bname == candidate.replace(".lz4", ""):
                            dest = self.work_dir / Path(member.name).name
                            if not dest.exists():
                                logger.info("Extracting %s from AP tar ...", member.name)
                                tf.extract(member, self.work_dir)
                            key = candidate.replace(".lz4", "")
                            images[key] = dest
                            break
        except Exception as e:
            logger.error("Failed to extract AP tar %s: %s", tar_path, e)
        return images

    async def _extract_apks_directly_from_tar(self, tar_path: Path) -> List[Dict]:
        """
        Directly read APK files from nested tars inside AP_*.tar.md5.
        Samsung AP tars sometimes contain a nested system.tar with /system/app/ entries.
        """
        apks: List[Dict] = []
        apk_dir = self.work_dir / "apks"
        apk_dir.mkdir(exist_ok=True)

        try:
            with tarfile.open(tar_path, "r:*") as outer:
                for member in outer.getmembers():
                    if not member.isfile():
                        continue
                    name_lower = member.name.lower()
                    # Direct APK in the tar
                    if name_lower.endswith(".apk"):
                        for frag, friendly in _SAMSUNG_PRIORITY_APKS:
                            if frag.lower() in name_lower:
                                dest = apk_dir / Path(member.name).name
                                if not dest.exists():
                                    f = outer.extractfile(member)
                                    if f:
                                        dest.write_bytes(f.read())
                                apks.append({
                                    "path": str(dest),
                                    "name": friendly,
                                    "package": _guess_package(name_lower),
                                })
                                break
        except Exception as e:
            logger.warning("Direct APK extraction failed: %s", e)
        return apks

    async def _decompress_lz4(self, lz4_path: Path) -> Optional[Path]:
        """Decompress .lz4 file using lz4 CLI tool."""
        out = lz4_path.with_suffix("")  # remove .lz4
        if out.exists():
            return out
        lz4_bin = _find_tool("lz4") or _find_tool("lz4c")
        if not lz4_bin:
            logger.warning("lz4 tool not found — cannot decompress %s", lz4_path.name)
            return None
        try:
            proc = await asyncio.create_subprocess_exec(
                lz4_bin, "-d", str(lz4_path), str(out),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=300)
            if proc.returncode == 0 and out.exists():
                logger.info("Decompressed %s → %s", lz4_path.name, out.name)
                return out
        except Exception as e:
            logger.warning("lz4 decompress failed: %s", e)
        return None

    async def _lpunpack_super(self, super_img: Path) -> Dict[str, Path]:
        """Unpack super.img (dynamic partitions) → individual system/vendor/... images."""
        out_dir = self.work_dir / "super_unpacked"
        out_dir.mkdir(exist_ok=True)
        lpunpack = _find_tool("lpunpack")
        if not lpunpack:
            logger.warning("lpunpack not found — cannot unpack super.img")
            return {}
        try:
            proc = await asyncio.create_subprocess_exec(
                lpunpack, str(super_img), str(out_dir),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=600)
        except Exception as e:
            logger.warning("lpunpack failed: %s", e)
            return {}
        images = {}
        for img in out_dir.glob("*.img"):
            images[img.name] = img
        logger.info("lpunpack produced: %s", list(images.keys()))
        return images

    async def _ensure_raw_ext4(self, img_path: Path) -> Optional[Path]:
        """Convert Android sparse image to raw ext4 using simg2img."""
        if not _is_sparse_image(img_path):
            return img_path  # already raw
        raw_path = img_path.with_suffix(".raw.img")
        if raw_path.exists():
            return raw_path
        simg2img = _find_tool("simg2img")
        if not simg2img:
            logger.warning("simg2img not found — cannot convert sparse image")
            return img_path  # return sparse; emulator may handle it
        try:
            proc = await asyncio.create_subprocess_exec(
                simg2img, str(img_path), str(raw_path),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=600)
            if proc.returncode == 0 and raw_path.exists():
                logger.info("Converted sparse → raw: %s", raw_path.name)
                return raw_path
        except Exception as e:
            logger.warning("simg2img failed: %s", e)
        return img_path

    async def _extract_apks_from_image(self, system_img: Path) -> List[Dict]:
        """
        Mount system.img (raw ext4) and copy Samsung APKs out.
        Requires: Linux + root for loop mount, OR debugfs (no root).
        Falls back to debugfs if available.
        """
        apks: List[Dict] = []
        apk_dir = self.work_dir / "apks"
        apk_dir.mkdir(exist_ok=True)

        debugfs = _find_tool("debugfs")
        if debugfs:
            apks = await self._extract_apks_via_debugfs(system_img, apk_dir, debugfs)
        else:
            logger.warning(
                "debugfs not found — APK extraction from system.img unavailable. "
                "Install e2fsprogs (brew install e2fsprogs / apt install e2fsprogs)."
            )
        return apks

    async def _extract_apks_via_debugfs(
        self, system_img: Path, apk_dir: Path, debugfs: str
    ) -> List[Dict]:
        """Use debugfs to list and extract APKs from ext4 image without mounting."""
        apks: List[Dict] = []
        # List all APK paths in /app and /priv-app
        for subdir in ("app", "priv-app"):
            try:
                proc = await asyncio.create_subprocess_exec(
                    debugfs, "-R", f"ls -l /{subdir}", str(system_img),
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
                entries = stdout.decode(errors="replace").splitlines()
                for entry in entries:
                    parts = entry.split()
                    if not parts:
                        continue
                    dname = parts[-1]
                    # Each app lives in its own dir; APK inside is base.apk
                    for frag, friendly in _SAMSUNG_PRIORITY_APKS:
                        if frag.lower() in dname.lower():
                            apk_remote = f"/{subdir}/{dname}/base.apk"
                            dest = apk_dir / f"{dname}.apk"
                            if not dest.exists():
                                await self._debugfs_dump(debugfs, system_img, apk_remote, dest)
                            if dest.exists():
                                apks.append({
                                    "path": str(dest),
                                    "name": friendly,
                                    "package": _guess_package(dname.lower()),
                                })
                            break
            except Exception as e:
                logger.warning("debugfs list %s failed: %s", subdir, e)
        return apks

    async def _debugfs_dump(
        self, debugfs: str, img: Path, remote: str, dest: Path
    ) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                debugfs, "-R", f"dump {remote} {dest}", str(img),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=120)
        except Exception as e:
            logger.warning("debugfs dump %s failed: %s", remote, e)


# ── helpers ───────────────────────────────────────────────────────────────────

_SPARSE_MAGIC = 0xED26FF3A

def _is_sparse_image(path: Path) -> bool:
    """Check if image is Android sparse format (not raw ext4)."""
    try:
        with open(path, "rb") as f:
            magic = struct.unpack("<I", f.read(4))[0]
            return magic == _SPARSE_MAGIC
    except Exception:
        return False


def _guess_package(name_lower: str) -> str:
    """Best-effort package name from APK filename."""
    _MAP = {
        "sbrowser":          "com.sec.android.app.sbrowser",
        "samsunghealth":     "com.sec.android.app.shealth",
        "samsungnotes":      "com.sec.android.app.notes",
        "samsungclock":      "com.sec.android.app.clockpackage",
        "samsungcalculator": "com.sec.android.app.popupcalculator",
        "samsungcontacts":   "com.samsung.android.contacts",
        "samsunggallery":    "com.sec.android.gallery3d",
        "samsungmessages":   "com.samsung.android.messaging",
        "samsungcamera":     "com.sec.android.app.camera",
        "samsungkeyboard":   "com.samsung.android.inputmethod",
        "galaxystore":       "com.sec.android.app.samsungapps",
        "themecenter":       "com.samsung.android.themestore",
        "bixby":             "com.samsung.android.bixby.agent",
        "securefolder":      "com.samsung.knox.securefolder",
        "smartthings":       "com.samsung.android.oneconnect",
    }
    for k, v in _MAP.items():
        if k in name_lower:
            return v
    return "com.samsung.android.unknown"


# ── Emulator integration helpers ──────────────────────────────────────────────

def get_system_image_flags(system_img_path: str, vendor_img_path: Optional[str] = None) -> List[str]:
    """
    Return extra emulator CLI flags to boot with Samsung system image.
    Usage: emulator -avd NAME [flags] ...
    """
    flags = ["-system", system_img_path]
    if vendor_img_path:
        flags += ["-vendor", vendor_img_path]
    # Keep kernel/ramdisk from the AOSP system image for hardware compatibility
    return flags

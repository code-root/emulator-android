"""
Samsung Galaxy Emulator Skin manager.

Supports:
  - Auto-generation of AVD skin directories (dimensions + hardware buttons)
    matching real Samsung device screen specs.
  - Optional download of official Samsung Galaxy Emulator Skins from
    developer.samsung.com (ZIP format) when internet is available.
  - Applies skin.path to AVD config.ini so the emulator renders with
    correct Samsung screen geometry.

References:
  - developer.samsung.com/galaxy-emulator-skin
  - mwolfson/AndroidAVDRepo  (AVD config.ini patterns)
  - Official Samsung skin ZIP structure documentation
"""
from __future__ import annotations

import asyncio
import logging
import zipfile
from pathlib import Path
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Samsung device skin specs ─────────────────────────────────────────────────
# (width_px, height_px, density, has_spen, form_factor)
# form_factor: "bar" | "fold" | "flip" | "tablet"

_SAMSUNG_SKIN_DB: Dict[str, Tuple[int, int, int, bool, str]] = {
    # Galaxy S25 series
    "SM-S931B": (1080, 2340, 416, False, "bar"),
    "SM-S931U": (1080, 2340, 416, False, "bar"),
    "SM-S936B": (1080, 2340, 416, False, "bar"),
    "SM-S936U": (1080, 2340, 416, False, "bar"),
    "SM-S938B": (1440, 3120, 505, True,  "bar"),
    "SM-S938U": (1440, 3120, 505, True,  "bar"),
    # Galaxy S24 series
    "SM-S921B": (1080, 2340, 416, False, "bar"),
    "SM-S921U": (1080, 2340, 416, False, "bar"),
    "SM-S926B": (1080, 2340, 416, False, "bar"),
    "SM-S926U": (1080, 2340, 416, False, "bar"),
    "SM-S928B": (1440, 3088, 501, True,  "bar"),
    "SM-S928U": (1440, 3088, 501, True,  "bar"),
    "SM-S741B": (1080, 2340, 416, False, "bar"),
    # Galaxy S23 series
    "SM-S911B": (1080, 2340, 393, False, "bar"),
    "SM-S916B": (1080, 2340, 393, False, "bar"),
    "SM-S918B": (1440, 3088, 501, True,  "bar"),
    "SM-S718B": (1080, 2340, 393, False, "bar"),
    "SM-S721B": (1080, 2340, 393, False, "bar"),
    "SM-S711B": (1080, 2340, 393, False, "bar"),
    # Galaxy S22 series
    "SM-S901B": (1080, 2340, 425, False, "bar"),
    "SM-S906B": (1080, 2340, 425, False, "bar"),
    "SM-S908B": (1440, 3088, 500, True,  "bar"),
    # Galaxy S21 series
    "SM-G991B": (1080, 2400, 421, False, "bar"),
    "SM-G991U": (1080, 2400, 421, False, "bar"),
    "SM-G996B": (1080, 2400, 421, False, "bar"),
    "SM-G996U": (1080, 2400, 421, False, "bar"),
    "SM-G998B": (1440, 3200, 515, True,  "bar"),
    "SM-G990B": (1080, 2400, 421, False, "bar"),
    # Galaxy Note 20 series
    "SM-N980F": (1080, 2400, 393, True,  "bar"),
    "SM-N985F": (1080, 2400, 393, True,  "bar"),
    "SM-N986B": (1440, 3088, 489, True,  "bar"),
    "SM-N986U": (1440, 3088, 489, True,  "bar"),
    # Galaxy Z Fold series
    "SM-F926B": (1768, 2208, 373, False, "fold"),  # Z Fold 3 inner
    "SM-F936B": (1812, 2176, 374, False, "fold"),  # Z Fold 4
    "SM-F946B": (1812, 2176, 374, False, "fold"),  # Z Fold 5
    "SM-F956B": (1856, 2176, 374, False, "fold"),  # Z Fold 6
    # Galaxy Z Flip series
    "SM-F711B": (1080, 2636, 425, False, "flip"),  # Z Flip 3
    "SM-F721B": (1080, 2640, 425, False, "flip"),  # Z Flip 4
    "SM-F731B": (1080, 2640, 425, False, "flip"),  # Z Flip 5
    "SM-F741B": (1080, 2640, 425, False, "flip"),  # Z Flip 6
    # Galaxy A series
    "SM-A556B": (1080, 2340, 390, False, "bar"),
    "SM-A546B": (1080, 2340, 390, False, "bar"),
    "SM-A536B": (1080, 2408, 390, False, "bar"),
    "SM-A346B": (1080, 2340, 390, False, "bar"),
    "SM-A256B": (1080, 2340, 390, False, "bar"),
    "SM-A155F": (720,  1600, 270, False, "bar"),
    "SM-A256F": (1080, 2340, 405, False, "bar"),
    # Galaxy Tab S series
    "SM-X810":  (2560, 1600, 274, True,  "tablet"),
    "SM-X910":  (2960, 1848, 290, True,  "tablet"),
    "SM-X916B": (2960, 1848, 290, True,  "tablet"),
    "SM-T870":  (2560, 1600, 274, True,  "tablet"),
}

# Official Samsung Galaxy Emulator Skin ZIP URLs from developer.samsung.com
# These are published under Apache-2.0. Update URLs when Samsung releases new versions.
_OFFICIAL_SKIN_URLS: Dict[str, str] = {
    "galaxy_s25_ultra":    "https://developer.samsung.com/galaxy-emulator-skin/dist/Galaxy_S25_Ultra_Skin.zip",
    "galaxy_s25_plus":     "https://developer.samsung.com/galaxy-emulator-skin/dist/Galaxy_S25_Plus_Skin.zip",
    "galaxy_s25":          "https://developer.samsung.com/galaxy-emulator-skin/dist/Galaxy_S25_Skin.zip",
    "galaxy_z_fold6":      "https://developer.samsung.com/galaxy-emulator-skin/dist/Galaxy_Z_Fold6_Skin.zip",
    "galaxy_z_flip6":      "https://developer.samsung.com/galaxy-emulator-skin/dist/Galaxy_Z_Flip6_Skin.zip",
    "galaxy_tab_s10_ultra": "https://developer.samsung.com/galaxy-emulator-skin/dist/Galaxy_Tab_S10_Ultra_Skin.zip",
}

# Map device models → official skin key (closest match)
_MODEL_TO_SKIN_KEY: Dict[str, str] = {
    "SM-S938B": "galaxy_s25_ultra",
    "SM-S938U": "galaxy_s25_ultra",
    "SM-S936B": "galaxy_s25_plus",
    "SM-S936U": "galaxy_s25_plus",
    "SM-S931B": "galaxy_s25",
    "SM-S931U": "galaxy_s25",
    "SM-F956B": "galaxy_z_fold6",
    "SM-F741B": "galaxy_z_flip6",
    "SM-X916B": "galaxy_tab_s10_ultra",
    "SM-X910":  "galaxy_tab_s10_ultra",
}

# Skins base directory inside ~/.android/skins/
_SKINS_BASE = Path.home() / ".android" / "skins"


def _skin_dir_for_model(device_model: str) -> Path:
    model = (device_model or "").upper()
    return _SKINS_BASE / f"samsung_{model.replace('-', '_').lower()}"


def _generate_skin_layout(skin_dir: Path, w: int, h: int) -> None:
    """Generate a minimal AVD skin (layout file + background) for given dimensions."""
    skin_dir.mkdir(parents=True, exist_ok=True)

    layout = f"""\
parts {{
    device {{
        display {{
            width   {w}
            height  {h}
            x       0
            y       0
        }}
    }}
    portrait {{
        background {{
            image   background.png
        }}
        display {{
            width   {w}
            height  {h}
            x       0
            y       0
        }}
    }}
    landscape {{
        background {{
            image   background_land.png
        }}
        display {{
            width   {h}
            height  {w}
            x       0
            y       0
        }}
    }}
}}
"""
    (skin_dir / "layout").write_text(layout, encoding="utf-8")

    # Create minimal 1×1 PNG stubs so the emulator doesn't crash on missing assets.
    # Minimal valid PNG (1×1 white pixel)
    _STUB_PNG = bytes([
        0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
        0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,
        0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
        0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53,
        0xDE, 0x00, 0x00, 0x00, 0x0C, 0x49, 0x44, 0x41,
        0x54, 0x08, 0xD7, 0x63, 0xF8, 0xCF, 0xC0, 0x00,
        0x00, 0x00, 0x02, 0x00, 0x01, 0xE2, 0x21, 0xBC,
        0x33, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4E,
        0x44, 0xAE, 0x42, 0x60, 0x82,
    ])
    for name in ("background.png", "background_land.png"):
        p = skin_dir / name
        if not p.exists():
            p.write_bytes(_STUB_PNG)


async def _download_official_skin(skin_key: str, dest_dir: Path) -> bool:
    """Download official Samsung skin ZIP and extract to dest_dir."""
    url = _OFFICIAL_SKIN_URLS.get(skin_key)
    if not url:
        return False
    try:
        import urllib.request
        import tempfile
        import os

        dest_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp_path = tmp.name

        logger.info("Downloading Samsung skin %s from %s", skin_key, url)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: urllib.request.urlretrieve(url, tmp_path),
        )
        with zipfile.ZipFile(tmp_path, "r") as zf:
            zf.extractall(dest_dir)
        os.unlink(tmp_path)
        logger.info("Samsung skin %s extracted to %s", skin_key, dest_dir)
        return True
    except Exception as e:
        logger.warning("Could not download Samsung skin %s: %s", skin_key, e)
        return False


async def ensure_samsung_skin(device_model: str) -> Optional[str]:
    """
    Return an absolute path to a skin directory for device_model.
    1. Use official downloaded skin if already present.
    2. Try to download official skin from developer.samsung.com.
    3. Generate a minimal skin from known dimensions.
    Returns None if device_model is not in the database.
    """
    model = (device_model or "").upper()
    specs = _SAMSUNG_SKIN_DB.get(model)
    if not specs:
        # Try prefix fallback for unknown variants (e.g. SM-S928N → SM-S928B)
        for known in _SAMSUNG_SKIN_DB:
            if known[:7] == model[:7]:
                specs = _SAMSUNG_SKIN_DB[known]
                break
    if not specs:
        return None

    w, h, _density, _spen, _form = specs
    skin_dir = _skin_dir_for_model(model)

    # 1. Already have a valid skin (layout file exists)
    if (skin_dir / "layout").exists():
        return str(skin_dir)

    # 2. Try downloading official skin
    skin_key = _MODEL_TO_SKIN_KEY.get(model)
    if skin_key:
        downloaded = await _download_official_skin(skin_key, skin_dir)
        if downloaded and (skin_dir / "layout").exists():
            return str(skin_dir)

    # 3. Generate minimal skin from specs
    _generate_skin_layout(skin_dir, w, h)
    logger.info("Generated Samsung skin for %s (%dx%d) at %s", model, w, h, skin_dir)
    return str(skin_dir)


def get_samsung_hw_config(device_model: str) -> Dict[str, str]:
    """
    Return a dict of config.ini keys that reflect real Samsung hardware.
    Covers: display, sensors, NFC, fingerprint, camera, S-Pen, Samsung DEX.
    Based on mwolfson/AndroidAVDRepo and KnoxPatch research.
    """
    model = (device_model or "").upper()
    specs = _SAMSUNG_SKIN_DB.get(model)
    if not specs:
        for known in _SAMSUNG_SKIN_DB:
            if known[:7] == model[:7]:
                specs = _SAMSUNG_SKIN_DB[known]
                break

    if not specs:
        # Generic Samsung fallback
        w, h, density, has_spen, form = 1080, 2340, 420, False, "bar"
    else:
        w, h, density, has_spen, form = specs

    cfg: Dict[str, str] = {
        # Display
        "hw.lcd.width":    str(w),
        "hw.lcd.height":   str(h),
        "hw.lcd.density":  str(density),
        # Samsung device identity
        "hw.device.manufacturer": "Samsung",
        "hw.device.name":          _resolve_device_name(model),
        # CPU / RAM (will be overridden by emulator flags, but set here too)
        "hw.cpu.arch":     "arm64",
        "hw.cpu.model":    "cortex-a55",
        "tag.id":          "google_apis",
        # Sensors — all real Samsung phones have these
        "hw.accelerometer":          "yes",
        "hw.gyroscope":              "yes",
        "hw.gps":                    "yes",
        "hw.sensors.proximity":      "yes",
        "hw.sensors.light":          "yes",
        "hw.sensors.magnetic_field": "yes",
        "hw.sensors.orientation":    "yes",
        "hw.sensors.temperature":    "yes",
        "hw.sensors.humidity":       "yes",
        "hw.sensors.pressure":       "yes",
        # Cameras
        "hw.camera.back":  "virtualscene",
        "hw.camera.front": "emulated",
        # NFC — present on all Galaxy S/Note/Z
        "hw.nfc":          "yes",
        "hw.nfc.hce":      "yes",
        # Fingerprint (under-display or side-mounted)
        "hw.fingerprint":  "yes",
        # Audio / haptics
        "hw.audioInput":   "yes",
        "hw.audioOutput":  "yes",
        "hw.vibrator":     "yes",
        # Battery
        "hw.battery":      "yes",
        # SD card
        "hw.sdCard":       "yes",
        # Keyboard — Samsung uses virtual only
        "hw.keyboard":     "yes",
        "hw.dPad":         "no",
        "hw.trackBall":    "no",
        # Network
        "hw.gsmModem":     "yes",
        "hw.bluetooth":    "yes",
    }

    # S-Pen support (Note, S Ultra, Z Fold 3+)
    if has_spen:
        cfg["hw.stylus"] = "yes"

    # Samsung DEX (desktop mode) — enabled on S8+ and newer flagships
    if form in ("bar", "fold") and density >= 420:
        cfg["hw.dex"] = "yes"

    # Foldable-specific
    if form == "fold":
        cfg["hw.sensors.hinge_angle"] = "yes"

    return cfg


def _resolve_device_name(model: str) -> str:
    _NAMES = {
        "SM-S938B": "Galaxy S25 Ultra",
        "SM-S936B": "Galaxy S25+",
        "SM-S931B": "Galaxy S25",
        "SM-S928B": "Galaxy S24 Ultra",
        "SM-S926B": "Galaxy S24+",
        "SM-S921B": "Galaxy S24",
        "SM-S741B": "Galaxy S24 FE",
        "SM-S918B": "Galaxy S23 Ultra",
        "SM-S916B": "Galaxy S23+",
        "SM-S911B": "Galaxy S23",
        "SM-S711B": "Galaxy S23 FE",
        "SM-S721B": "Galaxy S23",
        "SM-S908B": "Galaxy S22 Ultra",
        "SM-S906B": "Galaxy S22+",
        "SM-S901B": "Galaxy S22",
        "SM-G998B": "Galaxy S21 Ultra",
        "SM-G996B": "Galaxy S21+",
        "SM-G991B": "Galaxy S21",
        "SM-G990B": "Galaxy S21 FE",
        "SM-N986B": "Galaxy Note 20 Ultra",
        "SM-N985F": "Galaxy Note 20+",
        "SM-N980F": "Galaxy Note 20",
        "SM-F956B": "Galaxy Z Fold6",
        "SM-F946B": "Galaxy Z Fold5",
        "SM-F936B": "Galaxy Z Fold4",
        "SM-F926B": "Galaxy Z Fold3",
        "SM-F741B": "Galaxy Z Flip6",
        "SM-F731B": "Galaxy Z Flip5",
        "SM-F721B": "Galaxy Z Flip4",
        "SM-F711B": "Galaxy Z Flip3",
        "SM-A556B": "Galaxy A55",
        "SM-A546B": "Galaxy A54",
        "SM-A536B": "Galaxy A53",
        "SM-A346B": "Galaxy A34",
        "SM-A256B": "Galaxy A25",
        "SM-X916B": "Galaxy Tab S10 Ultra",
        "SM-X910":  "Galaxy Tab S10 Ultra",
        "SM-X810":  "Galaxy Tab S9+",
    }
    return _NAMES.get(model, "Samsung Galaxy")


def get_skin_specs(device_model: str) -> Optional[Dict]:
    """Return skin specs dict for use in API/dashboard."""
    model = (device_model or "").upper()
    specs = _SAMSUNG_SKIN_DB.get(model)
    if not specs:
        for known in _SAMSUNG_SKIN_DB:
            if known[:7] == model[:7]:
                specs = _SAMSUNG_SKIN_DB[known]
                break
    if not specs:
        return None
    w, h, density, has_spen, form = specs
    return {
        "width": w,
        "height": h,
        "density": density,
        "has_spen": has_spen,
        "form_factor": form,
        "device_name": _resolve_device_name(model),
    }

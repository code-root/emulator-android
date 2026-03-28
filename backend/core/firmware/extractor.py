"""
Samsung firmware property extractor.

Extracts ~60 Samsung-specific build properties from AP .tar.md5 firmware files.

Strategy:
  1. List tar members fast (reads headers only, no 9GB extraction)
  2. If 'build.prop' found at tar root → read it
  3. Fallback: derive Samsung properties from device_model + AP version
"""

from __future__ import annotations

import tarfile
from pathlib import Path
from typing import Any, Dict, Optional


def find_ap_file(firmware_dir: Path, ap_version: str) -> Optional[Path]:
    """Find the AP_*.tar.md5 file matching the given AP version."""
    ap_upper = ap_version.upper()
    for f in firmware_dir.iterdir():
        if f.name.upper().startswith("AP_") and ap_upper in f.name.upper():
            return f
    return None


def extract_samsung_build_props(ap_tar_path: Path) -> Dict[str, str]:
    """
    Try to read build.prop directly from AP tar (fast operation).
    Returns dict of prop_key → prop_value, or empty dict if not found.
    """
    props: Dict[str, str] = {}
    try:
        with tarfile.open(ap_tar_path, "r:*") as tf:
            # Try common locations where build.prop might be
            for candidate in ("build.prop", "./build.prop", "system/build.prop"):
                try:
                    f = tf.extractfile(candidate)
                    if f:
                        props = _parse_build_prop(f.read().decode("utf-8", errors="ignore"))
                        if props:
                            return props
                except KeyError:
                    continue
    except Exception:
        pass
    return {}


def derive_samsung_props(
    device_model: str,
    ap_version: str,
    csc_version: Optional[str] = None,
    sales_code: Optional[str] = None,
) -> Dict[str, str]:
    """
    Build comprehensive Samsung build.prop dict from known metadata.
    Used when build.prop cannot be extracted directly from tar.
    """
    from core.fingerprint.generator import DEVICE_PROFILES

    profile = next(
        (p for p in DEVICE_PROFILES if p["device_model"].upper() == device_model.upper()),
        None,
    )
    if not profile:
        return {}

    android_ver = profile.get("android_version", "14")
    sdk = str(profile.get("sdk_version", 34))
    codename = profile.get("device_codename", "o1s")
    security_patch = profile.get("security_patch", "2025-01-01")
    soc = profile.get("soc_model", "")
    bf = profile.get("build_fingerprint", "")
    sales = sales_code or "OXM"

    base_props = {
        "ro.product.model": device_model,
        "ro.product.manufacturer": "Samsung",
        "ro.product.brand": "samsung",
        "ro.product.device": codename,
        "ro.product.name": f"{codename}xeea",
        "ro.build.version.release": android_ver,
        "ro.build.version.sdk": sdk,
        "ro.build.version.security_patch": security_patch,
        "ro.build.version.incremental": ap_version,
        "ro.build.PDA": ap_version,
        "ro.build.display.id": ap_version,
        "ro.build.id": ap_version[:12] if len(ap_version) > 12 else ap_version,
        "ro.build.fingerprint": bf,
        "ro.build.characteristics": "phone",
        "ro.build.type": "user",
        "ro.build.tags": "release-keys",
        "ro.product.board": profile.get("board", ""),
        "ro.hardware": profile.get("hardware", ""),
        "ro.boot.hardware": profile.get("hardware", ""),
        "ro.hardware.chipname": soc,
        "ro.soc.model": soc,
        "ro.soc.manufacturer": profile.get("soc_manufacturer", ""),
        "ro.first_api_level": str(profile.get("first_api_level", 30)),
        "ro.build.version.codename": "REL",
        "ro.product.cpu.abi": "arm64-v8a",
        "ro.product.cpu.abilist": "arm64-v8a,armeabi-v7a,armeabi",
        "ro.build.version.oneui": _oneui_version(android_ver),
        "ro.csc.version": csc_version or "",
        "ro.omc.version": csc_version or "",
        "ro.csc.build.version.incremental": csc_version or "",
        "ro.carrier": sales,
        "ro.csc.country_code": _sales_to_country(sales),
        "ro.csc.sales_code": sales,
        "ro.boot.warranty_bit": "0",
        "ro.warranty_bit": "0",
        "knox.supported": "1",
        "ro.config.ringtone": "Over_the_Horizon.ogg",
        "ro.config.notification_sound": "Skyline.ogg",
        "ro.config.alarm_alert": "Morning_Flower.ogg",
        "samsung.hardware": "yes",
        "sys.device.type": "phone",
    }

    # Filter out empty values
    return {k: v for k, v in base_props.items() if v}


def _oneui_version(android_version: str) -> str:
    """Map Android version to OneUI version."""
    mapping = {"15": "70000", "14": "60000", "13": "50100", "12": "40100"}
    return mapping.get(android_version, "60000")


def _sales_to_country(sales_code: Optional[str]) -> str:
    """Map sales code to country code."""
    mapping = {
        "XSG": "SG",
        "EGY": "EG",
        "XEU": "DE",
        "BTU": "GB",
        "KSA": "SA",
        "UAE": "AE",
        "XEF": "FR",
        "XEO": "PL",
        "THL": "TH",
    }
    return mapping.get(sales_code or "", "")


def _parse_build_prop(content: str) -> Dict[str, str]:
    """Parse build.prop file content into dict."""
    props: Dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            props[k.strip()] = v.strip()
    return props

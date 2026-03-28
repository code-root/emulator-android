"""مسح مجلد حزم السوفتوير (*.zip, *.tar, *.tar.md5) واستخراج تعريفات SAMFW."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from core.fingerprint.generator import DEVICE_CREATION_PRESETS
from core.firmware.samfw import (
    parse_samfw_filename,
    parse_samsung_tar_filename,
    parse_samsung_bundle_dirname,
)


def suggested_presets_for_model(device_model: str) -> List[str]:
    """مفاتيح presets من DEVICE_CREATION_PRESETS التي تطابق device_model."""
    dm = device_model.upper()
    keys: List[str] = []
    for key, cfg in DEVICE_CREATION_PRESETS.items():
        if str(cfg.get("device_model", "")).upper() == dm:
            keys.append(key)
    return keys


def iter_firmware_packages(scan_root: Path) -> List[Dict[str, Any]]:
    if not scan_root.is_dir():
        return []

    out: List[Dict[str, Any]] = []
    seen: set[str] = set()

    # مسح ملفات ZIP (SAMFW)
    for p in sorted(scan_root.glob("*.zip")):
        meta = parse_samfw_filename(p.name)
        if not meta:
            continue
        row = dict(meta)
        row["kind"] = "file"
        row["absolute_path"] = str(p.resolve())
        device_model = meta.get("device_model")
        if device_model:
            row["suggested_presets"] = suggested_presets_for_model(device_model)
        seen.add(p.name)
        out.append(row)

    # مسح ملفات TAR و TAR.MD5 (Samsung)
    for pattern in ["*.tar.md5", "*.tar"]:
        for p in sorted(scan_root.glob(pattern)):
            if p.name in seen:
                continue
            meta = parse_samsung_tar_filename(p.name)
            if not meta:
                continue
            row = dict(meta)
            row["kind"] = "file"
            row["absolute_path"] = str(p.resolve())
            device_model = meta.get("device_model")
            if device_model:
                row["suggested_presets"] = suggested_presets_for_model(device_model)
            seen.add(p.name)
            out.append(row)

    try:
        for p in sorted(scan_root.iterdir()):
            if not p.is_dir() or p.name.startswith("."):
                continue
            meta = parse_samsung_bundle_dirname(p.name)
            if not meta:
                continue
            row = dict(meta)
            row["kind"] = "directory"
            row["absolute_path"] = str(p.resolve())
            row["suggested_presets"] = suggested_presets_for_model(meta["device_model"])
            if p.name not in seen:
                out.append(row)
    except OSError:
        pass

    out.sort(key=lambda r: r.get("filename", ""))
    return out


def iter_firmware_families(scan_root: Path) -> List[Dict[str, Any]]:
    """
    Group firmware packages by device_model + AP version into families.
    Each family groups AP, BL, CSC, HOME_CSC, etc. files for the same device/version.
    Returns one entry per family with paths to AP and CSC files.
    """
    if not scan_root.is_dir():
        return []

    all_packages = iter_firmware_packages(scan_root)
    families: Dict[str, Dict[str, Any]] = {}

    for pkg in all_packages:
        ap = pkg.get("ap_version")
        if not ap:
            continue

        # Family key is based on device model + AP version
        family_key = (pkg.get("device_model"), ap)
        if family_key not in families:
            families[family_key] = {
                "device_model": pkg.get("device_model"),
                "ap_version": ap,
                "sales_code": pkg.get("sales_code"),
                "csc_version": pkg.get("csc_version"),
                "ap_file": None,
                "csc_file": None,
                "files": [],
                "suggested_presets": pkg.get("suggested_presets", []),
                "source": pkg.get("source", ""),
            }

        filename = pkg.get("filename", "")
        if filename:
            families[family_key]["files"].append(filename)

        # Track which file is AP and which is CSC
        if filename.upper().startswith("AP_"):
            families[family_key]["ap_file"] = filename
        elif (
            filename.upper().startswith("CSC_")
            and "HOME" not in filename.upper()
        ):
            families[family_key]["csc_file"] = filename

    # Sort by AP version (newest first)
    result = sorted(
        families.values(),
        key=lambda x: x.get("ap_version", ""),
        reverse=True,
    )
    return result

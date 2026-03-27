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

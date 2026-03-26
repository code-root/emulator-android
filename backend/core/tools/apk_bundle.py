"""Extract split APK sets from .apkm (ZIP) archives for install-multiple."""

from __future__ import annotations

import logging
import shutil
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)


def safe_extract_apks_from_zip(archive: Path, dest: Path) -> list[Path]:
    """
    Extract every .apk member into dest, blocking path traversal.
    Returns absolute paths to extracted APK files (may be nested under dest).
    """
    if not zipfile.is_zipfile(archive):
        raise ValueError("File is not a valid ZIP archive (some .apkm builds are encrypted — use a ZIP of split APKs)")

    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    found: list[Path] = []

    with zipfile.ZipFile(archive, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            if not info.filename.lower().endswith(".apk"):
                continue
            rel = Path(info.filename)
            if rel.is_absolute() or ".." in rel.parts:
                logger.warning("Skipping unsafe zip member: %s", info.filename)
                continue
            target = (dest / rel).resolve()
            try:
                target.relative_to(dest)
            except ValueError:
                logger.warning("Skipping zip member outside dest: %s", info.filename)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info, "r") as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            found.append(target)

    if not found:
        raise ValueError("No .apk files found inside the archive")

    return found


def sort_apk_paths_for_install(paths: list[str]) -> list[str]:
    """Put base/master APK first for adb install-multiple."""

    def sort_key(p: str) -> tuple[int, str]:
        n = Path(p).name.lower()
        if n == "base.apk":
            return (0, n)
        if n.startswith("base-") or n.startswith("base."):
            return (1, n)
        if "split_" in n and "base" in n and "config" not in n:
            return (2, n)
        if "split_" not in n:
            return (3, n)
        return (4, n)

    return sorted(paths, key=sort_key)

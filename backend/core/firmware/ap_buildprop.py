"""
قراءة خصائص بناء سامسونغ من داخل حزمة AP (.tar / .tar.md5).

لا تُستخدم الملفات كـ system.img للمحاكي — Google AVD لا يقلع روم Odin.
الهدف: ملء البصمة من build.prop الفعلي داخل system (أو ما يعادله) قدر الإمكان.

يتطلب أداة ``lz4`` في PATH عندما تحتوي الحزمة على ‎.img.lz4 (الوضع الشائع لسامسونغ).
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tarfile
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.fingerprint.importer import map_props_to_fingerprint
from core.firmware.samfw import parse_samsung_tar_filename

logger = logging.getLogger(__name__)

# أول N بايت مفكوكة/خام تُمسح بحثاً عن سلاسل build.prop
_SCAN_MAX_DECOMPRESSED = 220 * 1024 * 1024
_CHUNK = 4 * 1024 * 1024

# مفاتيح نعتبرها كافية لاعتبار المسح ناجحاً
_SUCCESS_KEYS = frozenset(
    {
        "ro.build.fingerprint",
        "ro.bootimage.build.fingerprint",
        "ro.vendor.build.fingerprint",
    }
)

_PROP_RE = re.compile(
    rb"(ro\.(?:build|product|bootimage|vendor|odm|system|bootloader|hardware|csc)(?:\.[a-zA-Z0-9._]+)?)=([^\x00\n\r]{1,520})"
)


def find_ap_tar_path(fw_path: Path) -> Optional[Path]:
    """
    إن كان المسار ملف AP_*.tar(.md5) يُعاد كما هو.
    إن كان مجلد حزمة Odin يُبحث عن أول AP_*.tar.md5 ثم AP_*.tar.
    """
    if not fw_path.exists():
        return None
    if fw_path.is_file():
        name = fw_path.name.upper()
        if name.startswith("AP_") and (
            fw_path.suffix.lower() == ".tar" or fw_path.name.lower().endswith(".tar.md5")
        ):
            if parse_samsung_tar_filename(fw_path.name):
                return fw_path
        return None
    candidates = sorted(fw_path.glob("AP_*.tar.md5")) + sorted(fw_path.glob("AP_*.tar"))
    for c in candidates:
        if c.is_file() and parse_samsung_tar_filename(c.name):
            return c
    return None


def _props_from_binary(blob: bytes) -> Dict[str, str]:
    """يستخرج أزواج مفتاح=قيمة لخصائص ro.* من بايتات (صورة ext4 خام/مفرغة جزئياً)."""
    out: Dict[str, str] = {}
    for m in _PROP_RE.finditer(blob):
        try:
            k = m.group(1).decode("ascii", errors="strict")
            v = m.group(2).decode("utf-8", errors="ignore").strip()
        except Exception:
            continue
        if not v or len(v) > 500:
            continue
        if k not in out:
            out[k] = v
    if "ro.build.fingerprint" not in out and "ro.bootimage.build.fingerprint" in out:
        out["ro.build.fingerprint"] = out["ro.bootimage.build.fingerprint"]
    return out


def _member_sort_key(name: str) -> Tuple[int, str]:
    n = name.replace("./", "").lower()
    if "system" in n and n.endswith(".lz4"):
        return (0, n)
    if n.endswith("system.img") or n.endswith("system.img.sparse"):
        return (1, n)
    if "system" in n and n.endswith(".img"):
        return (2, n)
    if "vendor" in n and n.endswith(".lz4"):
        return (3, n)
    if "vendor" in n and n.endswith(".img"):
        return (4, n)
    if "super" in n:
        return (9, n)
    if n.endswith(".lz4"):
        return (6, n)
    if n.endswith(".img"):
        return (7, n)
    return (8, n)


def _tar_img_members(tf: tarfile.TarFile) -> List[tarfile.TarInfo]:
    members: List[tarfile.TarInfo] = []
    for m in tf.getmembers():
        if not m.isfile():
            continue
        name = m.name.replace("./", "")
        low = name.lower()
        if low.endswith(".img") or low.endswith(".img.lz4") or low.endswith(".lz4"):
            if any(x in low for x in ("cache", "userdata", "modem", "radio", "efs")):
                continue
            members.append(m)
    members.sort(key=lambda x: _member_sort_key(x.name))
    return members


def _read_plain_member(tf: tarfile.TarFile, member: tarfile.TarInfo, limit: int) -> bytes:
    f = tf.extractfile(member)
    if not f:
        return b""
    return f.read(limit)


def _decompress_lz4_member(tf: tarfile.TarFile, member: tarfile.TarInfo, limit: int) -> Optional[bytes]:
    if not shutil.which("lz4"):
        return None

    proc = subprocess.Popen(
        ["lz4", "-d", "-c"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    assert proc.stdin and proc.stdout
    feed_error: List[Optional[Exception]] = [None]

    def feed() -> None:
        try:
            raw = tf.extractfile(member)
            if not raw:
                return
            while True:
                chunk = raw.read(_CHUNK)
                if not chunk:
                    break
                proc.stdin.write(chunk)
        except Exception as e:
            feed_error[0] = e
        finally:
            try:
                proc.stdin.close()
            except Exception:
                pass

    t = threading.Thread(target=feed, daemon=True)
    t.start()
    out = bytearray()
    try:
        while len(out) < limit:
            block = proc.stdout.read(min(_CHUNK, limit - len(out)))
            if not block:
                break
            out.extend(block)
    finally:
        proc.kill()
        t.join(timeout=3.0)
    if feed_error[0]:
        logger.debug("lz4 feed thread: %s", feed_error[0])
    return bytes(out) if out else None


def scan_samsung_ap_tar_for_build_props(ap_tar: Path, warnings: List[str]) -> Dict[str, str]:
    """
    يفتح أرشيف AP ويمسح أقسام system/vendor (أو غيرها) بحثاً عن سلاسل خصائص البناء.
    """
    if not ap_tar.is_file():
        warnings.append(f"ap_buildprop: not a file: {ap_tar}")
        return {}

    try:
        tf = tarfile.open(ap_tar, "r:*")
    except (tarfile.TarError, OSError) as e:
        warnings.append(f"ap_buildprop: cannot open tar {ap_tar.name}: {e}")
        return {}

    try:
        members = _tar_img_members(tf)
        if not members:
            warnings.append(f"ap_buildprop: no .img/.lz4 members in {ap_tar.name}")
            return {}

        for mem in members:
            name = mem.name.replace("./", "")
            low = name.lower()
            try:
                if low.endswith(".lz4"):
                    blob = _decompress_lz4_member(tf, mem, _SCAN_MAX_DECOMPRESSED)
                    if blob is None:
                        warnings.append(
                            "ap_buildprop: lz4 CLI not found or failed — install lz4 (brew install lz4) "
                            f"to scan {name}"
                        )
                        continue
                else:
                    blob = _read_plain_member(tf, mem, _SCAN_MAX_DECOMPRESSED)
            except Exception as e:
                warnings.append(f"ap_buildprop: read {name}: {e}")
                continue
            if not blob:
                continue
            props = _props_from_binary(blob)
            if props and _SUCCESS_KEYS.intersection(props.keys()):
                logger.info(
                    "ap_buildprop: matched props from %s in %s (%d keys)",
                    name,
                    ap_tar.name,
                    len(props),
                )
                return props
    finally:
        tf.close()

    warnings.append(
        f"ap_buildprop: no ro.build.fingerprint found in scanned members of {ap_tar.name} "
        "(try installing lz4, or verify archive is Samsung AP)"
    )
    return {}


def merge_ap_tar_build_props_into_fp_data(fp_data: Dict[str, Any], ap_tar: Path) -> List[str]:
    """
    يحدّث fp_data (من المولّد + دمج SAMFW) بخصائص مستخرجة من AP.
    يعيد قائمة تحذيرات لغير الأعطال.
    """
    warnings: List[str] = []
    raw = scan_samsung_ap_tar_for_build_props(ap_tar, warnings)
    if not raw:
        return warnings

    flat, ext_patch, w2 = map_props_to_fingerprint(raw)
    warnings.extend(w2)

    for k, v in flat.items():
        if v is not None and v != "":
            fp_data[k] = v

    if ext_patch:
        from core.fingerprint.extended_defaults import empty_extended, merge_extended

        base = fp_data.get("extended") if isinstance(fp_data.get("extended"), dict) else empty_extended()
        fp_data["extended"] = merge_extended(base, ext_patch)

    return warnings


def enrich_fp_data_from_firmware_disk_path(fp_data: Dict[str, Any], fw_path: Path) -> List[str]:
    """نقطة دخول: مسار الحزمة كما في FIRMWARE_PACKAGES_DIR (ملف أو مجلد)."""
    ap = find_ap_tar_path(fw_path)
    if not ap:
        return []
    return merge_ap_tar_build_props_into_fp_data(fp_data, ap)

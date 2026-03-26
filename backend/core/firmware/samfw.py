"""
تحليل أسماء حزم SAMFW (مثل SAMFW.COM_SM-G996B_EGY_G996BXXSJHZC2_fac.zip) لاستخراج:
الموديل، كود المبيعات (CSC)، رقم البناء (AP/PDA)، ونوع الحزمة.

هذه الحزم مخصّصة عادةً للفلاش عبر Odin وليست system.img لمحاكي Google AVD.
الاستخدام هنا: مواءمة بصمة الجهاز (AP/CSC/build fingerprint) مع ملف السوفتوير الذي لديك.
"""

from __future__ import annotations

import re
from pathlib import PurePath
from typing import Any, Dict, Optional

# مثال: SAMFW.COM_SM-G996B_EGY_G996BXXSJHZC2_fac.zip
_SAMFW_ZIP = re.compile(
    r"^(?:SAMFW\.COM_)?(SM-[A-Z0-9]+)_([A-Z0-9]{2,4})_([A-Z0-9]+)_([a-z0-9]+)\.zip$",
    re.IGNORECASE,
)

# مجلد أو اسم حزمة مستخرجة: AP_CSC_SALES — مثال: G996BXXSJHZA6_G996BOXMJHZA6_XSG
_SAMSUNG_AP_CSC_SALES = re.compile(
    r"^(?P<ap>G996B[A-Z0-9]+)_(?P<csc>G996B[A-Z0-9]+)_(?P<sales>[A-Z]{2,4})$",
    re.IGNORECASE,
)

# كود مبيعات Samsung → (country, language) لمواءمة خفيفة في البصمة
_SALES_LOCALE: dict[str, tuple[str, str]] = {
    "XSG": ("SG", "en"),  # Singapore
    "EGY": ("EG", "ar"),
    "XEU": ("DE", "en"),
    "BTU": ("GB", "en"),
    "XEF": ("FR", "fr"),
    "XEO": ("PL", "pl"),
    "THL": ("TH", "th"),
    "KSA": ("SA", "ar"),
    "UAE": ("AE", "ar"),
}


def parse_samfw_filename(filename: str) -> Optional[Dict[str, Any]]:
    """إرجاع قاموس تعريف إذا وافق الاسم النمط الشائع لـ SAMFW، وإلا None."""
    name = PurePath(filename.strip()).name
    m = _SAMFW_ZIP.match(name)
    if not m:
        return None
    model, sales, build_id, variant = (
        m.group(1).upper(),
        m.group(2).upper(),
        m.group(3).upper(),
        m.group(4).lower(),
    )
    return {
        "source": "samfw",
        "filename": name,
        "device_model": model,
        "sales_code": sales,
        "ap_version": build_id,
        "package_variant": variant,
    }


def parse_samsung_bundle_dirname(dirname: str) -> Optional[Dict[str, Any]]:
    """
    يطابق مجلدات Odin/SamFw المسمّاة: {AP}_{CSC_full}_{SALES}
    مثال: G996BXXSJHZA6_G996BOXMJHZA6_XSG → SM-G996B، AP، CSC كامل، XSG.
    """
    name = PurePath(dirname.strip()).name
    m = _SAMSUNG_AP_CSC_SALES.match(name)
    if not m:
        return None
    ap = m.group("ap").upper()
    csc = m.group("csc").upper()
    sales = m.group("sales").upper()
    loc = _SALES_LOCALE.get(sales, (None, None))
    row: Dict[str, Any] = {
        "source": "samsung_bundle_dir",
        "filename": name,
        "device_model": "SM-G996B",
        "sales_code": sales,
        "ap_version": ap,
        "csc_version": csc,
    }
    if loc[0]:
        row["country"] = loc[0]
    if loc[1]:
        row["language"] = loc[1]
    return row


def resolve_firmware_meta(basename: str) -> Optional[Dict[str, Any]]:
    """ZIP بصيغة SAMFW أو مجلد/اسم بصيغة AP_CSC_SALES لـ G996B."""
    return parse_samfw_filename(basename) or parse_samsung_bundle_dirname(basename)


def _guess_csc_version(device_model: str, sales_code: str, ap_version: str) -> Optional[str]:
    """
    تخمين تنسيق Samsung الشائع: {رمز_موديل}{CSC}{ذيل_من_AP}.
    مثال: SM-G996B + EGY + G996BXXSJHZC2 → G996BEGYSJHZC2 (تقريبي؛ راجع سجل SW إن لزم).
    """
    mid = device_model.upper().replace("SM-", "")
    apu = ap_version.upper()
    if not apu.startswith(mid):
        return None
    tail = apu[-6:] if len(apu) >= 6 else None
    if not tail:
        return None
    return f"{mid}{sales_code}{tail}"


def _patch_build_fingerprint(build_fp: str, new_build_id: str) -> str:
    """يستبدل آخر مقطع build قبل ':user/release-keys' إن وُجد."""
    return re.sub(
        r"/([^/:]+)(:user/release-keys)$",
        f"/{new_build_id}\\2",
        build_fp,
        count=1,
    )


def merge_firmware_into_fingerprint(
    fp_data: Dict[str, Any],
    meta: Dict[str, Any],
) -> Dict[str, Any]:
    """ينسخ fp_data ويحدّث ap_version / csc_version / build_fingerprint / locale حسب meta."""
    out = dict(fp_data)
    ap = meta.get("ap_version")
    model = meta.get("device_model")
    sales = meta.get("sales_code")

    if ap:
        out["ap_version"] = ap
    if meta.get("csc_version"):
        out["csc_version"] = str(meta["csc_version"]).upper()
    elif model and sales and ap:
        guessed = _guess_csc_version(model, sales, ap)
        if guessed:
            out["csc_version"] = guessed

    bf = out.get("build_fingerprint")
    if isinstance(bf, str) and ap and ":user/release-keys" in bf:
        out["build_fingerprint"] = _patch_build_fingerprint(bf, ap)

    if meta.get("country"):
        out["country"] = meta["country"]
    elif sales == "EGY":
        out["country"] = "EG"
        out.setdefault("language", "ar")
    if meta.get("language"):
        out["language"] = meta["language"]

    return out

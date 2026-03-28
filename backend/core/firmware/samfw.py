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

# Samsung AP/BL/CSC TAR files: AP_S721BXXS3AYB8_S721BXXS3AYB8_MQB93088282_REV00_...tar.md5
# Pattern: {COMPONENT}_{AP_VERSION}_{CSC_VERSION}_...tar.md5 or .tar
_SAMSUNG_TAR = re.compile(
    r"^(AP|BL|CSC|MODEM)_([A-Z0-9]+)_([A-Z0-9]+)_(.+)\.(tar\.md5|tar)$",
    re.IGNORECASE,
)

# مجلد أو اسم حزمة مستخرجة: AP_CSC_SALES — مثال: G996BXXSJHZA6_G996BOXMJHZA6_XSG أو S921BXXU3CXJ1_S921BOXM3CXJ1_XEU
# Fixed: Now works for all Samsung models (G996B, S921B, S721B, A556B, etc.)
# Model code format: Letter + 3 digits + Letter (e.g., G996B, S921B, S721B, A556B)
_SAMSUNG_AP_CSC_SALES = re.compile(
    r"^(?P<ap>(?P<model>[A-Z]\d{3}[A-Z])[A-Z0-9]+)_(?P<csc>[A-Z0-9]+)_(?P<sales>[A-Z]{2,4})$",
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


def parse_samsung_tar_filename(filename: str) -> Optional[Dict[str, Any]]:
    """
    تحليل ملفات Samsung TAR/TAR.MD5.

    مثال: AP_S721BXXS3AYB8_S721BXXS3AYB8_MQB93088282_REV00_user_low_ship_MULTI_CERT_meta_OS14.tar.md5

    يستخرج:
    - component: AP (Application Processor)
    - ap_version: S721BXXS3AYB8
    - csc_version: S721BXXS3AYB8 (إذا كانت مختلفة)
    - device_model: يتم استخراجه من AP version (S721B → SM-S721B)
    """
    name = PurePath(filename.strip()).name
    m = _SAMSUNG_TAR.match(name)
    if not m:
        return None

    component = m.group(1).upper()  # AP, BL, CSC, MODEM
    ap_version = m.group(2).upper()
    csc_version = m.group(3).upper()
    metadata = m.group(4)  # e.g., MQB93088282_REV00_user_low_ship_...
    file_ext = m.group(5)  # tar.md5 or tar

    # استخراج الموديل من AP version
    # مثال: S721BXXS3AYB8 → SM-S721B
    # نمط: {Letter}{Digits}{Letter} = S721B
    device_model = None
    model_match = re.match(r"^([A-Z]+\d+[A-Z])([A-Z0-9]+)", ap_version)
    if model_match:
        device_model = f"SM-{model_match.group(1)}"

    result = {
        "source": "samsung_tar",
        "filename": name,
        "ap_version": ap_version,
        "csc_version": csc_version if csc_version != ap_version else None,
        "package_variant": f"{component.lower()}_{file_ext}",
    }

    if device_model:
        result["device_model"] = device_model

    # محاولة استخراج كود المبيعات من metadata أو CSC
    # مثال من CSC: S721BXXS3AYB8 قد تحتوي على hints
    if len(csc_version) >= 5:
        result["csc_version"] = csc_version

    return result


def parse_samsung_bundle_dirname(dirname: str) -> Optional[Dict[str, Any]]:
    """
    يطابق مجلدات Odin/SamFw المسمّاة: {AP}_{CSC_full}_{SALES}
    مثال: G996BXXSJHZA6_G996BOXMJHZA6_XSG → SM-G996B، AP، CSC كامل، XSG.
    مثال آخر: S921BXXU3CXJ1_S921BOXM3CXJ1_XEU → SM-S921B
    """
    name = PurePath(dirname.strip()).name
    m = _SAMSUNG_AP_CSC_SALES.match(name)
    if not m:
        return None
    ap = m.group("ap").upper()
    csc = m.group("csc").upper()
    sales = m.group("sales").upper()
    model_code = m.group("model").upper()  # G996B, S921B, S721B, A556B, etc.
    device_model = f"SM-{model_code}"  # SM-G996B, SM-S921B, etc.
    loc = _SALES_LOCALE.get(sales, (None, None))
    row: Dict[str, Any] = {
        "source": "samsung_bundle_dir",
        "filename": name,
        "device_model": device_model,
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
    """
    تحليل ملفات firmware بصيغ مختلفة:
    - SAMFW ZIP: SAMFW.COM_SM-G996B_EGY_*.zip
    - Samsung TAR: AP_S721BXXS3AYB8_*.tar.md5
    - Bundle DIR: G996BXXSJHZA6_G996BOXMJHZA6_XSG/
    """
    return (
        parse_samfw_filename(basename)
        or parse_samsung_tar_filename(basename)
        or parse_samsung_bundle_dirname(basename)
    )


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


# مقطع المنتج في fingerprint (بين samsung و codename) — EEA الافتراضي في DEVICE_PROFILES هو o1sxeea.
# لبعض أكواد المبيعات نستبدله بنمط أقرب لبناء غير EEA (راجع build.prop إن لزم التصحيح الدقيق).
G996B_FINGERPRINT_PRODUCT_BY_SALES: dict[str, str] = {
    "XSG": "o1sxxx",
}


def _patch_fingerprint_samsung_product(
    build_fp: str, new_product: str, device_codename: str
) -> str:
    """يستبدل المقطع الثاني في samsung/<product>/<codename>:..."""
    codename_esc = re.escape(device_codename.strip())
    return re.sub(
        rf"^(samsung)/([^/]+)/({codename_esc})(:)",
        rf"\1/{new_product}/\3\4",
        build_fp,
        count=1,
        flags=re.IGNORECASE,
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
    if isinstance(bf, str) and ":user/release-keys" in bf:
        codename = (out.get("device_codename") or "o1s").strip()
        if (
            str(model or "").upper() == "SM-G996B"
            and sales
            and bf.lower().startswith("samsung/")
        ):
            prod = G996B_FINGERPRINT_PRODUCT_BY_SALES.get(str(sales).upper())
            if prod:
                bf = _patch_fingerprint_samsung_product(bf, prod, codename)
        if ap:
            bf = _patch_build_fingerprint(bf, ap)
        out["build_fingerprint"] = bf

    if meta.get("country"):
        out["country"] = meta["country"]
    elif sales == "EGY":
        out["country"] = "EG"
        out.setdefault("language", "ar")
    if meta.get("language"):
        out["language"] = meta["language"]

    return out

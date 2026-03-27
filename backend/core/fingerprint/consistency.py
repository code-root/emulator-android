"""تحققات تناسق بسيطة — لا تضمن تجاوز كل كشف تطبيقات، لكن تقلل الأخطاء الواضحة."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


def _luhn_ok(imei: str) -> bool:
    if not imei or not imei.isdigit() or len(imei) != 15:
        return False
    digits = [int(c) for c in imei]
    s = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        s += d
    return s % 10 == 0


# بصمة شكل: brand/product/device:version/id/incremental:type/tags
_FP_RE = re.compile(
    r"^([A-Za-z0-9_]+)/([A-Za-z0-9_.]+)/([A-Za-z0-9_.]+):"
    r"([^/]+)/([^/]+)/([^:]+):([^/]+)/([^/]+)$"
)


def check_build_fingerprint_format(fp_str: Optional[str]) -> Tuple[bool, str]:
    if not fp_str or not str(fp_str).strip():
        return False, "empty fingerprint"
    if _FP_RE.match(fp_str.strip()):
        return True, "ok"
    return False, "fingerprint does not match /.../...:ver/id/inc:type/tags pattern"


def validate_mcc_mnc(mcc: Any, mnc: Any) -> Tuple[bool, str]:
    if mcc is None and mnc is None:
        return True, "skip"
    try:
        mcci = int(mcc) if mcc is not None else None
        mnci = int(mnc) if mnc is not None else None
    except (TypeError, ValueError):
        return False, "mcc/mnc must be integers"
    if mcci is not None and not (100 <= mcci <= 999):
        return False, "MCC must be 3 digits (100–999)"
    if mnci is not None and not (0 <= mnci <= 999):
        return False, "MNC out of range"
    return True, "ok"


def model_in_fingerprint(device_model: Optional[str], build_fp: Optional[str]) -> Tuple[bool, str]:
    if not device_model or not build_fp:
        return True, "skip"
    # الجزء بعد آخر / غالباً يحتوي اسم جهاز أو قريب — تحقق ضعيف لكن يكشف أخطاء فادحة
    parts = build_fp.split("/")
    if len(parts) < 3:
        return True, "skip"
    blob = build_fp.lower()
    dm = device_model.lower().replace(" ", "")
    if dm in blob.replace("_", "").replace("-", ""):
        return True, "ok"
    # لا نفشل صارم — أجهزة كثيرة تختلف التسمية
    return True, "weak_match"


def run_consistency_checks(data: Dict[str, Any]) -> Dict[str, Any]:
    """يرجع { ok: bool, errors: [], warnings: [] }"""
    errors: List[str] = []
    warnings: List[str] = []

    imei = data.get("imei")
    if imei and not _luhn_ok(str(imei)):
        errors.append("imei fails Luhn check")

    imei2 = data.get("imei_slot2")
    if imei2 and not _luhn_ok(str(imei2)):
        errors.append("imei_slot2 fails Luhn check")

    ok_fp, msg_fp = check_build_fingerprint_format(data.get("build_fingerprint"))
    if not ok_fp:
        warnings.append(f"build_fingerprint: {msg_fp}")

    ok_mcc, msg_mcc = validate_mcc_mnc(data.get("mcc"), data.get("mnc"))
    if not ok_mcc:
        errors.append(f"mcc/mnc: {msg_mcc}")

    ok_mod, msg_mod = model_in_fingerprint(data.get("device_model"), data.get("build_fingerprint"))
    if msg_mod == "weak_match":
        warnings.append("device_model not obviously contained in build_fingerprint — verify manually")

    return {"ok": len(errors) == 0, "errors": errors, "warnings": warnings}

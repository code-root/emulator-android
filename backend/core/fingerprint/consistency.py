"""
Simple consistency checks for fingerprint data.

Rules fall into two categories:
- **errors** — hard failures that block apply (e.g. bad IMEI checksum, invalid MCC range)
- **warnings** — soft mismatches that the caller should surface but not block on
  (e.g. carrier name does not match MCC country, missing expected sensors)

None of these checks guarantee detection bypass; they reduce obvious mistakes.
"""
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


# ---------------------------------------------------------------------------
# MCC → country code (partial, major operators — expand as needed)
# ---------------------------------------------------------------------------
_MCC_COUNTRY: Dict[str, str] = {
    "202": "GR", "204": "NL", "206": "BE", "208": "FR", "212": "MC",
    "213": "AD", "214": "ES", "216": "HU", "218": "BA", "219": "HR",
    "220": "RS", "222": "IT", "226": "RO", "228": "CH", "230": "CZ",
    "231": "SK", "232": "AT", "234": "GB", "235": "GB", "238": "DK",
    "240": "SE", "242": "NO", "244": "FI", "246": "LT", "247": "LV",
    "248": "EE", "250": "RU", "255": "UA", "257": "BY", "259": "MD",
    "260": "PL", "262": "DE", "266": "GI", "268": "PT", "270": "LU",
    "272": "IE", "274": "IS", "276": "AL", "278": "MT", "280": "CY",
    "282": "GE", "283": "AM", "284": "BG", "286": "TR", "288": "FO",
    "290": "GL", "292": "SM", "293": "SI", "294": "MK", "295": "LI",
    "297": "ME", "302": "CA", "310": "US", "311": "US", "312": "US",
    "313": "US", "314": "US", "315": "US", "316": "US", "334": "MX",
    "338": "JM", "340": "GP", "342": "BB", "344": "AG", "346": "KY",
    "348": "VG", "350": "BM", "352": "GD", "354": "MS", "356": "KN",
    "358": "LC", "360": "VC", "362": "CW", "363": "AW", "364": "BS",
    "365": "AI", "366": "DM", "368": "CU", "370": "DO", "372": "HT",
    "374": "TT", "376": "TC", "400": "AZ", "401": "KZ", "402": "BT",
    "404": "IN", "405": "IN", "406": "IN", "410": "PK", "412": "AF",
    "413": "LK", "414": "MM", "415": "LB", "416": "JO", "417": "SY",
    "418": "IQ", "419": "KW", "420": "SA", "421": "YE", "422": "OM",
    "424": "AE", "425": "IL", "426": "BH", "427": "QA", "428": "MN",
    "429": "NP", "430": "AE", "431": "AE", "432": "IR", "434": "UZ",
    "436": "TJ", "437": "KG", "438": "TM", "440": "JP", "441": "JP",
    "450": "KR", "452": "VN", "454": "HK", "455": "MO", "456": "KH",
    "457": "LA", "460": "CN", "461": "CN", "466": "TW", "467": "KP",
    "470": "BD", "472": "MV", "502": "MY", "505": "AU", "510": "ID",
    "514": "TL", "515": "PH", "520": "TH", "525": "SG", "528": "BN",
    "530": "NZ", "536": "NR", "537": "PG", "539": "TO", "540": "SB",
    "541": "VU", "542": "FJ", "544": "AS", "545": "KI", "546": "NC",
    "547": "PF", "548": "CK", "549": "WS", "550": "FM", "551": "MH",
    "552": "PW", "602": "EG", "603": "DZ", "604": "MA", "605": "TN",
    "606": "LY", "607": "GM", "608": "SN", "609": "MR", "610": "ML",
    "611": "GN", "612": "CI", "613": "BF", "614": "NE", "615": "TG",
    "616": "BJ", "617": "MU", "618": "LR", "619": "SL", "620": "GH",
    "621": "NG", "622": "TD", "623": "CF", "624": "CM", "625": "CV",
    "626": "ST", "627": "GQ", "628": "GA", "629": "CG", "630": "CD",
    "631": "AO", "632": "GW", "633": "SC", "634": "SD", "635": "RW",
    "636": "ET", "637": "SO", "638": "DJ", "639": "KE", "640": "TZ",
    "641": "UG", "642": "BI", "643": "MZ", "645": "ZM", "646": "MG",
    "647": "RE", "648": "ZW", "649": "NA", "650": "MW", "651": "LS",
    "652": "BW", "653": "SZ", "654": "KM", "655": "ZA", "657": "ER",
    "702": "BZ", "704": "GT", "706": "SV", "708": "HN", "710": "NI",
    "712": "CR", "714": "PA", "716": "PE", "722": "AR", "724": "BR",
    "730": "CL", "732": "CO", "734": "VE", "736": "BO", "738": "GY",
    "740": "EC", "742": "GF", "744": "PY", "746": "SR", "748": "UY",
    "750": "FK",
}

# Carrier name keywords → expected MCC country (very heuristic, warnings only)
_CARRIER_COUNTRY_HINTS: Dict[str, str] = {
    "verizon": "US", "at&t": "US", "t-mobile": "US", "sprint": "US",
    "vodafone": None,   # multinational — skip
    "orange": None,     # multinational — skip
    "o2": None,         # multinational — skip
    "stc": "SA", "mobily": "SA", "zain": "SA",
    "etisalat": "AE", "du": "AE",
    "ooredoo": None,    # multinational
    "mtn": None,        # multinational
    "airtel": "IN", "jio": "IN", "vi": "IN",
    "singtel": "SG", "starhub": "SG", "m1": "SG",
    "docomo": "JP", "au": "JP", "softbank": "JP",
    "sk telecom": "KR", "kt": "KR", "lg uplus": "KR",
    "china mobile": "CN", "china unicom": "CN", "china telecom": "CN",
    "three": None,      # multinational
    "telstra": "AU", "optus": "AU",
    "rogers": "CA", "bell": "CA", "telus": "CA",
    "claro": None,      # multinational LATAM
    "movistar": None,   # multinational
    "turkcell": "TR", "vodafone tr": "TR",
    "mts": "RU", "beeline": "RU", "megafon": "RU",
    "kyivstar": "UA",
}


def check_carrier_mcc_consistency(
    carrier_name: Optional[str], mcc: Any
) -> Tuple[bool, str]:
    """Warn (never hard-error) if carrier name and MCC appear to be from different countries."""
    if not carrier_name or mcc is None:
        return True, "skip"
    mcc_str = str(mcc).strip().zfill(3)
    mcc_country = _MCC_COUNTRY.get(mcc_str)
    if mcc_country is None:
        return True, "skip"  # unknown MCC — can't verify
    carrier_lower = carrier_name.lower()
    for keyword, country in _CARRIER_COUNTRY_HINTS.items():
        if keyword in carrier_lower:
            if country is None:
                return True, "skip"  # multinational, ambiguous
            if country != mcc_country:
                return False, (
                    f"carrier_name {carrier_name!r} suggests country {country!r} "
                    f"but MCC {mcc_str} maps to {mcc_country!r}"
                )
            return True, "ok"
    return True, "skip"


def check_sensor_completeness(
    manufacturer: Optional[str], device_model: Optional[str], extended: Optional[Dict[str, Any]]
) -> Tuple[bool, str]:
    """
    For Samsung SM-G* / SM-S* devices (which all ship with full sensor suites),
    warn if the ``extended.sensors`` block is missing or obviously incomplete.
    Returns (True, message) — always a warning, never a hard error.
    """
    if not manufacturer and not device_model:
        return True, "skip"
    mfr = (manufacturer or "").lower()
    model = (device_model or "").upper()
    is_samsung_flagship = mfr == "samsung" or model.startswith("SM-G") or model.startswith("SM-S")
    if not is_samsung_flagship:
        return True, "skip"
    sensors = (extended or {}).get("sensors") or {}
    expected = {"accelerometer", "gyroscope", "magnetometer"}
    missing = expected - set(sensors.keys())
    if missing:
        return False, (
            f"Samsung device {model!r} expected sensors {sorted(missing)} "
            f"in extended.sensors — add or confirm absent"
        )
    return True, "ok"


def run_consistency_checks(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return ``{ ok: bool, errors: [], warnings: [] }``."""
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

    # Extended-aware checks (soft warnings only)
    extended = data.get("extended") or {}
    network = extended.get("network") or {}
    ext_mcc = network.get("mcc") or data.get("mcc")
    carrier = network.get("carrier_name")
    ok_carrier, msg_carrier = check_carrier_mcc_consistency(carrier, ext_mcc)
    if not ok_carrier:
        warnings.append(f"carrier/mcc mismatch: {msg_carrier}")

    ok_sensor, msg_sensor = check_sensor_completeness(
        data.get("manufacturer"), data.get("device_model"), extended
    )
    if not ok_sensor:
        warnings.append(f"sensor completeness: {msg_sensor}")

    return {"ok": len(errors) == 0, "errors": errors, "warnings": warnings}

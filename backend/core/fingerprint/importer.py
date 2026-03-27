"""
Parse raw ``getprop`` output or ``build.prop`` text from a real Android device
and map it to DeviceFingerprint fields + extended_json patch.

Supported input formats
-----------------------
getprop format (adb shell getprop):
    [ro.product.model]: [SM-G996B]

build.prop format:
    ro.product.model=SM-G996B

Usage
-----
    from core.fingerprint.importer import parse_prop_text, map_props_to_fingerprint

    props = parse_prop_text(raw_text)
    flat, extended_patch, warnings = map_props_to_fingerprint(props)
    # flat → set on DeviceFingerprint row columns
    # extended_patch → deep-merge into extended_json
    # warnings → surface to caller as non-fatal notices
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

# ---------------------------------------------------------------------------
# prop → (fingerprint_column_or_private_key, cast)
# Keys starting with "_" are redirected into extended_json, not flat columns.
# ---------------------------------------------------------------------------
_PROP_MAP: Dict[str, Tuple[str, str]] = {
    # flat columns
    "ro.product.model":                  ("device_model",        "str"),
    "ro.product.manufacturer":           ("manufacturer",        "str"),
    "ro.product.brand":                  ("brand",               "str"),
    "ro.product.device":                 ("device_codename",     "str"),
    "ro.product.board":                  ("board",               "str"),
    "ro.hardware":                       ("hardware",            "str"),
    "ro.build.fingerprint":              ("build_fingerprint",   "str"),
    "ro.build.version.sdk":              ("sdk_version",         "int"),
    "ro.build.version.release":          ("android_version",     "str"),
    "ro.boot.serialno":                  ("serial_number",       "str"),
    "persist.sys.timezone":              ("timezone",            "str"),
    "persist.sys.language":              ("language",            "str"),
    "persist.sys.country":               ("country",             "str"),
    "ro.csc.version":                    ("csc_version",         "str"),
    # ap_version — try PDA first, fall back to changelist
    "ro.build.PDA":                      ("ap_version",          "str"),
    # extended → device
    "ro.product.name":                   ("_product_name",       "str"),
    "ro.bootloader":                     ("_bootloader",         "str"),
    "ro.baseband":                       ("_radio_version",      "str"),
    # extended → system
    "ro.build.id":                       ("_build_id",           "str"),
    "ro.build.version.security_patch":   ("_security_patch",     "str"),
    "ro.build.type":                     ("_build_type",         "str"),
    "ro.build.tags":                     ("_build_tags",         "str"),
    # extended → network
    "gsm.operator.alpha":                ("_carrier_name",       "str"),
    "gsm.operator.numeric":              ("_mcc_mnc",            "str"),
    "gsm.sim.operator.numeric":          ("_sim_mcc_mnc",        "str"),
    # locale helper (e.g. "en-US")
    "ro.product.locale":                 ("_locale",             "str"),
}

_GETPROP_LINE = re.compile(r"^\[(.+?)]\s*:\s*\[(.*?)]\s*$")
_BUILDPROP_LINE = re.compile(r"^([A-Za-z0-9._\-/]+)=(.*)$")


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def parse_prop_text(text: str) -> Dict[str, str]:
    """Return raw ``{prop: value}`` from getprop or build.prop text.

    Empty or comment lines are silently skipped.
    """
    result: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _GETPROP_LINE.match(line)
        if m:
            result[m.group(1).strip()] = m.group(2).strip()
            continue
        m = _BUILDPROP_LINE.match(line)
        if m:
            result[m.group(1).strip()] = m.group(2).strip()
    return result


def map_props_to_fingerprint(
    props: Dict[str, str],
) -> Tuple[Dict[str, Any], Dict[str, Any], List[str]]:
    """Map raw props to fingerprint fields.

    Returns
    -------
    flat : dict
        Fields to set directly on ``DeviceFingerprint`` row columns.
    extended_patch : dict
        Nested dict to deep-merge into ``extended_json`` via
        ``extended_defaults.merge_extended``.
    warnings : list[str]
        Non-fatal consistency notices (should be surfaced to the caller,
        not treated as hard errors).
    """
    flat: Dict[str, Any] = {}
    ext_device: Dict[str, Any] = {}
    ext_system: Dict[str, Any] = {}
    ext_network: Dict[str, Any] = {}
    warnings: List[str] = []

    for prop, raw_value in props.items():
        if not raw_value or prop not in _PROP_MAP:
            continue
        field, cast = _PROP_MAP[prop]

        # Cast value
        value: Any = raw_value
        if cast == "int":
            try:
                value = int(raw_value)
            except ValueError:
                warnings.append(f"{prop}: expected int, got {raw_value!r} — skipped")
                continue
        elif cast == "float":
            try:
                value = float(raw_value)
            except ValueError:
                warnings.append(f"{prop}: expected float, got {raw_value!r} — skipped")
                continue

        # Route to destination
        if field == "_product_name":
            ext_device["product_name"] = value
        elif field == "_bootloader":
            ext_device["bootloader"] = value
        elif field == "_radio_version":
            ext_device["radio_version"] = value
        elif field == "_build_id":
            ext_system["build_id"] = value
        elif field == "_security_patch":
            ext_system["security_patch"] = value
        elif field == "_build_type":
            ext_system["build_type"] = value
        elif field == "_build_tags":
            ext_system["build_tags"] = value
        elif field == "_carrier_name":
            ext_network["carrier_name"] = value
        elif field == "_mcc_mnc":
            if len(raw_value) >= 5:
                ext_network.setdefault("mcc", raw_value[:3])
                ext_network.setdefault("mnc", raw_value[3:])
        elif field == "_sim_mcc_mnc":
            # Fill only if gsm.operator.numeric wasn't already present
            if len(raw_value) >= 5:
                ext_network.setdefault("mcc", raw_value[:3])
                ext_network.setdefault("mnc", raw_value[3:])
        elif field == "_locale":
            # e.g. "en-US" or "en_US"
            parts = re.split(r"[-_]", raw_value, 1)
            if len(parts) == 2:
                flat.setdefault("language", parts[0])
                flat.setdefault("country", parts[1].upper())
            else:
                flat.setdefault("language", raw_value)
        else:
            flat[field] = value

    # Build extended_patch (omit empty sub-dicts)
    extended_patch: Dict[str, Any] = {}
    if ext_device:
        extended_patch["device"] = ext_device
    if ext_system:
        extended_patch["system"] = ext_system
    if ext_network:
        extended_patch["network"] = ext_network

    # --- Consistency warnings (non-fatal) ------------------------------------
    dm = flat.get("device_model", "")
    bp = flat.get("build_fingerprint", "")
    if dm and bp:
        dm_norm = dm.lower().replace("-", "").replace("_", "")
        bp_norm = bp.lower().replace("-", "").replace("_", "")
        if dm_norm not in bp_norm:
            warnings.append(
                f"device_model {dm!r} not found in build_fingerprint — verify manually"
            )

    mcc = ext_network.get("mcc")
    sdk = flat.get("sdk_version")
    if sdk and isinstance(sdk, int) and sdk < 21:
        warnings.append(f"sdk_version={sdk} is very old (<21); verify this is intentional")

    if flat.get("manufacturer", "").lower() == "samsung" and not flat.get("csc_version"):
        warnings.append("Samsung device detected but ro.csc.version not found in props")

    if mcc and not re.match(r"^\d{3}$", str(mcc)):
        warnings.append(f"MCC {mcc!r} is not a 3-digit string — double-check gsm.operator.numeric")

    return flat, extended_patch, warnings

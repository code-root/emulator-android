"""دمج صف SQL + extended_json إلى dict واحد لتطبيق الـ spoofer أو التحقق."""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from db.models import DeviceFingerprint
from core.fingerprint.extended_defaults import empty_extended, merge_extended


def parse_extended(raw: Optional[str]) -> Dict[str, Any]:
    if not raw or not str(raw).strip():
        return empty_extended()
    try:
        data = json.loads(raw)
        return merge_extended(empty_extended(), data) if isinstance(data, dict) else empty_extended()
    except json.JSONDecodeError:
        return empty_extended()


def fingerprint_row_to_apply_dict(
    fp: DeviceFingerprint,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    ext = parse_extended(fp.extended_json)
    out: Dict[str, Any] = {
        "imei": fp.imei,
        "android_id": fp.android_id,
        "mac_address": fp.mac_address,
        "device_model": fp.device_model,
        "manufacturer": fp.manufacturer,
        "brand": fp.brand,
        "device_codename": fp.device_codename,
        "build_fingerprint": fp.build_fingerprint,
        "sdk_version": fp.sdk_version,
        "android_version": fp.android_version,
        "board": fp.board,
        "hardware": fp.hardware,
        "serial_number": fp.serial_number,
        "latitude": fp.latitude,
        "longitude": fp.longitude,
        "altitude": fp.altitude,
        "network_type": fp.network_type,
        "ip_address": fp.ip_address,
        "timezone": fp.timezone,
        "language": fp.language,
        "country": fp.country,
        "ap_version": fp.ap_version,
        "csc_version": fp.csc_version,
    }
    # مسطّح من JSON الموسّع (أسماء متوقعة من الـ spoofer)
    dev = ext.get("device") or {}
    sys_ = ext.get("system") or {}
    ids = ext.get("identifiers") or {}
    net = ext.get("network") or {}
    sim = ext.get("sim") or {}
    loc = ext.get("location") or {}
    bat = ext.get("battery") or {}

    if dev.get("product_name"):
        out["product_name"] = dev["product_name"]
    if dev.get("bootloader"):
        out["bootloader_override"] = dev["bootloader"]
    if sys_.get("build_id"):
        out["build_id"] = sys_["build_id"]
    if sys_.get("security_patch"):
        out["security_patch"] = sys_["security_patch"]
    if ids.get("imei_slot2"):
        out["imei_slot2"] = ids["imei_slot2"]
    if ids.get("imsi_slot2"):
        out["imsi_slot2"] = ids["imsi_slot2"]
    if ids.get("imsi"):
        out["imsi"] = ids["imsi"]
    if ids.get("meid"):
        out["meid"] = ids["meid"]
    if net.get("wifi_mac"):
        out["wifi_mac"] = net["wifi_mac"]
    if net.get("bluetooth_mac"):
        out["bluetooth_mac"] = net["bluetooth_mac"]
    if net.get("carrier_name"):
        out["carrier_name"] = net["carrier_name"]
    if net.get("mcc") is not None:
        out["mcc"] = net["mcc"]
    if net.get("mnc") is not None:
        out["mnc"] = net["mnc"]
    if sim.get("iccid"):
        out["iccid"] = sim["iccid"]
    if sim.get("operator"):
        out["operator"] = sim["operator"]
    if sim.get("country_iso"):
        out["country_iso"] = sim["country_iso"]
    if loc.get("accuracy_m") is not None:
        out["location_accuracy_m"] = loc["accuracy_m"]
    if loc.get("speed_m_s") is not None:
        out["location_speed_m_s"] = loc["speed_m_s"]
    if bat.get("level_percent") is not None:
        out["battery_level"] = bat["level_percent"]
    if bat.get("status"):
        out["battery_status"] = bat["status"]

    out["_extended_raw"] = ext
    if extra:
        out.update(extra)
    return {k: v for k, v in out.items() if v is not None or k == "_extended_raw"}

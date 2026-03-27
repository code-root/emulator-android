"""
هيكل البصمة الموسّع (JSON في device_fingerprints.extended_json).
الحقول المسطّحة الأساسية تبقى في أعمدة SQL؛ الباقي هنا للتوسعة دون ترحيل مستمر.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def empty_extended() -> Dict[str, Any]:
    return {
        "device": {
            "product_name": None,
            "bootloader": None,
            "radio_version": None,
        },
        "system": {
            "build_id": None,
            "security_patch": None,
            "build_type": "user",
            "build_tags": "release-keys",
        },
        "identifiers": {
            "imei_slot2": None,
            "imsi": None,
            "imsi_slot2": None,
            "meid": None,
        },
        "network": {
            "wifi_mac": None,
            "bluetooth_mac": None,
            "carrier_name": None,
            "mcc": None,
            "mnc": None,
        },
        "sim": {
            "iccid": None,
            "iccid_slot2": None,
            "operator": None,
            "country_iso": None,
        },
        "sensors": {
            "accelerometer": {"noise_rms": 0.02},
            "gyroscope": {"noise_rms": 0.01},
            "magnetometer": {"noise_rms": 0.5},
            "light": {"lux_ambient": 120.0},
        },
        "battery": {
            "level_percent": 82,
            "status": "discharging",
            "temp_c": 32.5,
            "voltage_mv": 3900,
        },
        "location": {
            "accuracy_m": 12.0,
            "speed_m_s": 0.0,
            "bearing": None,
        },
        "meta": {
            "profile_key": None,
            "generator": "emulator-android",
        },
    }


def merge_extended(base: Optional[Dict[str, Any]], patch: Dict[str, Any]) -> Dict[str, Any]:
    out = empty_extended()
    if base:
        _deep_merge(out, base)
    _deep_merge(out, patch)
    return out


def _deep_merge(dst: Dict[str, Any], src: Dict[str, Any]) -> None:
    for k, v in src.items():
        if k in dst and isinstance(dst[k], dict) and isinstance(v, dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v

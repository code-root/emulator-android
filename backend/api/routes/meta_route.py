from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_current_user
from config import settings
from core.fingerprint.generator import DEVICE_PROFILES, DEVICE_CREATION_PRESETS
from core.fingerprint.geo_database import COUNTRY_DB, list_countries
from core.firmware.scan import iter_firmware_packages
from core.firmware.samsung_fota import fetch_latest_firmware
from db.models import User

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/device-profiles")
async def list_device_profiles(_user: User = Depends(get_current_user)) -> List[Dict[str, Any]]:
    """Device silhouettes for fingerprint UI (authenticated)."""
    return [
        {
            "device_model": p["device_model"],
            "manufacturer": p["manufacturer"],
            "brand": p["brand"],
            "device_codename": p["device_codename"],
            "build_fingerprint": p["build_fingerprint"],
            "sdk_version": p["sdk_version"],
            "android_version": p["android_version"],
            "ap_version": p.get("ap_version"),
            "csc_version": p.get("csc_version"),
        }
        for p in DEVICE_PROFILES
    ]


@router.get("/countries")
async def list_gps_countries(_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """
    Geographic database for GPS/IP/carrier selection.
    Returns countries with cities, carriers (MCC/MNC), IP prefixes.
    """
    countries = list_countries()
    country_details = {}
    for code in [c["code"] for c in countries]:
        if code in COUNTRY_DB:
            db = COUNTRY_DB[code]
            country_details[code] = {
                "name": db["name"],
                "country_iso": db["country_iso"],
                "timezone": db["timezone"],
                "language": db["language"],
                "cities": [
                    {"name": city, "latitude": lat, "longitude": lng, "altitude_m": alt}
                    for city, lat, lng, alt in db["cities"]
                ],
                "carriers": [
                    {"name": c["name"], "mcc": c["mcc"], "mnc": c["mnc"], "apn": c.get("apn", "")}
                    for c in db["carriers"]
                ],
                "ip_prefixes": db.get("ip_prefixes", []),
            }
    return {"countries": country_details}


@router.get("/firmware-packages")
async def list_firmware_packages(_user: User = Depends(get_current_user)) -> List[Dict[str, Any]]:
    """
    يمسح `FIRMWARE_PACKAGES_DIR` (افتراضي: مجلد `firmware/` في جذر المشروع) ويعيد حزم `.zip`
    بصيغة اسم SAMFW الشائعة (مثل SAMFW.COM_SM-G996B_EGY_G996BXXSJHZC2_fac.zip).

    **تنبيه:** هذه الملفات لا تُحمَّل كصورة نظام AVD؛ تُستخدم لاستخراج AP/CSC/الموديل لمواءمة البصمة عند الإنشاء.
    """
    root = Path(settings.FIRMWARE_PACKAGES_DIR)
    return iter_firmware_packages(root)


@router.get("/device-presets")
async def list_device_presets(_user: User = Depends(get_current_user)) -> List[Dict[str, Any]]:
    """Presets لإنشاء جهاز + AVD بمستوى API وبنية مناسبة (مثل G996B + Android 15)."""
    return [
        {
            "key": key,
            "label": cfg.get("label", key),
            "api_level": cfg["api_level"],
            "arch": cfg["arch"],
            "device_model": cfg["device_model"],
            "ram_mb": cfg.get("ram_mb"),
            "cpu_cores": cfg.get("cpu_cores"),
        }
        for key, cfg in DEVICE_CREATION_PRESETS.items()
    ]


@router.get("/samsung-firmware")
async def get_samsung_firmware(
    model: str,
    csc: str = "XEU",
    _user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Fetch latest Samsung firmware versions from FOTA servers.

    Query params:
    - model: Samsung model code (e.g. "SM-S921B", "SM-A556B")
    - csc: Customer Service Center / region code (default: "XEU"). Examples: "XEU", "BTU", "KSA", "UAE", "EGY", "XSP"

    Returns: {"model", "csc", "ap_version", "csc_version", "full_version"}

    Note: This is a public API call to Samsung's FOTA server. Firmware versions are verified real from the live server.
    """
    try:
        result = await fetch_latest_firmware(model, csc)
        return result
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        raise HTTPException(500, detail=f"Firmware fetch failed: {e}")

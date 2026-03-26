from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends

from api.deps import get_current_user
from config import settings
from core.fingerprint.generator import DEVICE_PROFILES, DEVICE_CREATION_PRESETS
from core.firmware.scan import iter_firmware_packages
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

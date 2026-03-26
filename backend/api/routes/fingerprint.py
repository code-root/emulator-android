from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from api.deps import get_db, get_current_user
from db.models import Device, DeviceFingerprint, User, DeviceStatus
from core.fingerprint.generator import FingerprintGenerator
from core.fingerprint.spoofer import FingerprintSpoofer
from core.fingerprint.samsung_enhanced import is_samsung_fingerprint, merge_profile_defaults_for_apply
from core.tools.adb import ADBTool

router = APIRouter(prefix="/devices", tags=["fingerprint"])
fp_generator = FingerprintGenerator()
fp_spoofer = FingerprintSpoofer()
adb_tool = ADBTool()


class FingerprintResponse(BaseModel):
    id: int
    device_id: int
    imei: Optional[str]
    android_id: Optional[str]
    mac_address: Optional[str]
    device_model: Optional[str]
    manufacturer: Optional[str]
    brand: Optional[str]
    device_codename: Optional[str]
    build_fingerprint: Optional[str]
    sdk_version: Optional[int]
    android_version: Optional[str]
    board: Optional[str]
    hardware: Optional[str]
    serial_number: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    altitude: Optional[float]
    network_type: Optional[str]
    ip_address: Optional[str]
    timezone: Optional[str]
    language: Optional[str]
    country: Optional[str]
    ap_version: Optional[str]
    csc_version: Optional[str]
    updated_at: datetime

    class Config:
        from_attributes = True


class FingerprintUpdateRequest(BaseModel):
    imei: Optional[str] = None
    android_id: Optional[str] = None
    mac_address: Optional[str] = None
    device_model: Optional[str] = None
    manufacturer: Optional[str] = None
    brand: Optional[str] = None
    device_codename: Optional[str] = None
    build_fingerprint: Optional[str] = None
    sdk_version: Optional[int] = None
    android_version: Optional[str] = None
    board: Optional[str] = None
    hardware: Optional[str] = None
    serial_number: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude: Optional[float] = None
    network_type: Optional[str] = None
    ip_address: Optional[str] = None
    timezone: Optional[str] = None
    language: Optional[str] = None
    country: Optional[str] = None
    ap_version: Optional[str] = None
    csc_version: Optional[str] = None


async def _get_device_and_fp(device_id: int, db: AsyncSession, user: User):
    result = await db.execute(select(Device).where(Device.id == device_id))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if device.owner_id != user.id and user.role.value != "admin":
        raise HTTPException(status_code=403, detail="Access denied")

    fp_result = await db.execute(select(DeviceFingerprint).where(DeviceFingerprint.device_id == device_id))
    fp = fp_result.scalar_one_or_none()
    return device, fp


@router.get("/{device_id}/fingerprint", response_model=FingerprintResponse)
async def get_fingerprint(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device, fp = await _get_device_and_fp(device_id, db, current_user)
    if not fp:
        raise HTTPException(status_code=404, detail="Fingerprint not found")
    return fp


@router.put("/{device_id}/fingerprint", response_model=FingerprintResponse)
async def update_fingerprint(
    device_id: int,
    data: FingerprintUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device, fp = await _get_device_and_fp(device_id, db, current_user)
    if not fp:
        # Create one
        fp = DeviceFingerprint(device_id=device_id)
        db.add(fp)

    update_data = data.model_dump(exclude_none=True)
    for key, value in update_data.items():
        setattr(fp, key, value)

    await db.flush()
    await db.refresh(fp)
    return fp


@router.post("/{device_id}/fingerprint/apply")
async def apply_fingerprint(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device, fp = await _get_device_and_fp(device_id, db, current_user)
    if not fp:
        raise HTTPException(status_code=404, detail="Fingerprint not configured")
    if device.status != DeviceStatus.running or not device.adb_serial:
        raise HTTPException(status_code=400, detail="Device must be running to apply fingerprint")

    fp_data = {
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
        "console_port": device.console_port,
    }
    fp_merged = merge_profile_defaults_for_apply(fp_data)

    try:
        result = await fp_spoofer.apply(adb_tool, device.adb_serial, fp_merged)
        deep = is_samsung_fingerprint(fp_merged)
        return {
            "success": True,
            "report": result,
            "samsung_extended_spoof": deep,
            "note": (
                "تمت محاولة عشرات خصائص ro.product/ro.vendor/ro.csc و settings السطحية. "
                "ما زال النظام AOSP وليس روم Samsung؛ المفاتيح المرفوضة في report.failed."
                if deep
                else None
            ),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Apply failed: {e}")


@router.post("/{device_id}/fingerprint/randomize", response_model=FingerprintResponse)
async def randomize_fingerprint(
    device_id: int,
    apply: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device, fp = await _get_device_and_fp(device_id, db, current_user)

    new_fp_data = fp_generator.generate()

    if not fp:
        fp = DeviceFingerprint(device_id=device_id)
        db.add(fp)

    for key, value in new_fp_data.items():
        if hasattr(fp, key):
            setattr(fp, key, value)

    await db.flush()
    await db.refresh(fp)

    if apply and device.status == DeviceStatus.running and device.adb_serial:
        try:
            fp_data = new_fp_data.copy()
            fp_data["console_port"] = device.console_port
            await fp_spoofer.apply(adb_tool, device.adb_serial, fp_data)
        except Exception as e:
            # Don't fail the randomize if apply fails
            pass

    return fp

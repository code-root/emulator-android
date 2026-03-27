"""
Live device control endpoints — GPS, battery, network type, proxy.

These apply instantly to a running emulator via the emulator console (telnet)
or ADB shell, without touching the stored fingerprint.  To persist a change,
use PUT /api/fingerprint/{id} afterwards.

Routes
------
POST /api/devices/{id}/gps          — set GPS coordinates live
POST /api/devices/{id}/battery      — set battery level + charging state live
POST /api/devices/{id}/network-type — set simulated network type live
POST /api/devices/{id}/proxy/apply  — re-apply current proxy settings to device
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db, get_current_user
from db.models import Device, DeviceStatus, User
from core.fingerprint.spoofer import FingerprintSpoofer
from core.tools.adb import ADBTool

router = APIRouter(prefix="/devices", tags=["device-controls"])
adb_tool = ADBTool()
spoofer = FingerprintSpoofer()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _running_device(device_id: int, db: AsyncSession, user: User) -> Device:
    r = await db.execute(select(Device).where(Device.id == device_id))
    device = r.scalar_one_or_none()
    if not device:
        raise HTTPException(404, "Device not found")
    if device.owner_id != user.id and user.role.value != "admin":
        raise HTTPException(403, "Access denied")
    if device.status != DeviceStatus.running or not device.adb_serial:
        raise HTTPException(400, "Device must be running with ADB serial")
    return device


# ---------------------------------------------------------------------------
# GPS
# ---------------------------------------------------------------------------

class GpsBody(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    altitude: float = Field(0.0)
    accuracy: float = Field(12.0, ge=0)
    persist: bool = Field(
        False,
        description="If true, also update the stored fingerprint latitude/longitude/altitude",
    )


@router.post("/{device_id}/gps")
async def set_gps_live(
    device_id: int,
    body: GpsBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Set the device GPS location instantly via the emulator console (`geo fix`).

    Works on Google AVD only (requires `console_port`).  Does NOT require root.
    The coordinate is applied at the emulator-hardware level, so all apps that
    read GPS via `LocationManager` will see it immediately.

    Pass ``persist=true`` to also update the fingerprint row in the database.
    """
    device = await _running_device(device_id, db, user)
    if not device.console_port:
        raise HTTPException(400, "Device has no console_port — GPS control requires AVD emulator")

    ok = await spoofer._telnet_command(
        device.console_port,
        f"geo fix {body.longitude} {body.latitude} {body.altitude}",
    )
    if not ok:
        raise HTTPException(502, "geo fix command failed — check emulator console connectivity")

    if body.persist:
        from db.models import DeviceFingerprint
        r2 = await db.execute(select(DeviceFingerprint).where(DeviceFingerprint.device_id == device_id))
        fp = r2.scalar_one_or_none()
        if fp:
            fp.latitude = body.latitude
            fp.longitude = body.longitude
            fp.altitude = body.altitude
            await db.flush()

    return {
        "success": True,
        "applied": f"geo fix {body.longitude} {body.latitude} {body.altitude}",
        "persisted": body.persist,
    }


# ---------------------------------------------------------------------------
# Battery
# ---------------------------------------------------------------------------

class BatteryBody(BaseModel):
    level: int = Field(..., ge=0, le=100, description="Battery percentage 0–100")
    charging: bool = Field(False, description="True = AC charging; False = discharging")
    temperature_celsius: float = Field(32.0, ge=0, le=60)


@router.post("/{device_id}/battery")
async def set_battery_live(
    device_id: int,
    body: BatteryBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Set battery level, charging state, and temperature via emulator console.
    """
    device = await _running_device(device_id, db, user)
    if not device.console_port:
        raise HTTPException(400, "Device has no console_port")

    cmds = [
        f"power capacity {body.level}",
        "power status ac" if body.charging else "power status discharging",
        f"power health good",
        f"power temp {int(body.temperature_celsius * 10)}",
    ]
    applied = []
    failed = []
    for cmd in cmds:
        ok = await spoofer._telnet_command(device.console_port, cmd)
        (applied if ok else failed).append(cmd)

    return {
        "success": len(failed) == 0,
        "applied": applied,
        "failed": failed,
    }


# ---------------------------------------------------------------------------
# Network type
# ---------------------------------------------------------------------------

_NETWORK_SPEED_MAP = {
    "WIFI": "full",
    "LTE": "lte",
    "5G": "5g",
    "3G": "umts",
    "2G": "gprs",
    "EDGE": "edge",
    "HSPA": "hsdpa",
    "NONE": "full",
}


class NetworkTypeBody(BaseModel):
    network_type: str = Field(
        ...,
        description="One of: WIFI, LTE, 5G, 3G, 2G, EDGE, HSPA",
    )
    persist: bool = False


@router.post("/{device_id}/network-type")
async def set_network_type_live(
    device_id: int,
    body: NetworkTypeBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Change the simulated network type/speed via emulator console.
    Also updates ``ro.telephony.default_network_type`` via setprop for label spoofing.
    """
    device = await _running_device(device_id, db, user)
    nt = body.network_type.upper()
    if nt not in _NETWORK_SPEED_MAP:
        raise HTTPException(400, f"Unknown network_type {nt!r}. Valid: {sorted(_NETWORK_SPEED_MAP)}")

    results: dict = {"applied": [], "failed": []}

    if device.console_port:
        speed = _NETWORK_SPEED_MAP[nt]
        ok = await spoofer._telnet_command(device.console_port, f"network speed {speed}")
        (results["applied"] if ok else results["failed"]).append(f"network speed {speed}")

    # Also spoof the label via setprop
    label_map = {"WIFI": "1", "LTE": "11", "5G": "20", "3G": "3", "2G": "1"}
    label = label_map.get(nt, "11")
    try:
        await adb_tool.shell(device.adb_serial, f"setprop ro.telephony.default_network_type {label}")
        results["applied"].append(f"setprop ro.telephony.default_network_type={label}")
    except Exception as exc:
        results["failed"].append(f"setprop: {exc}")

    if body.persist:
        from db.models import DeviceFingerprint
        r2 = await db.execute(select(DeviceFingerprint).where(DeviceFingerprint.device_id == device_id))
        fp = r2.scalar_one_or_none()
        if fp:
            fp.network_type = nt
            await db.flush()

    return {"success": len(results["failed"]) == 0, **results, "persisted": body.persist}

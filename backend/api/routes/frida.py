"""
Frida dynamic instrumentation management endpoints.

Exposes FridaTool for attaching/detaching from processes, injecting scripts,
and managing anti-emulator-detection hooks at runtime.

Routes
------
GET    /api/devices/{id}/frida/status         — session status (active, pid, version)
GET    /api/devices/{id}/frida/processes      — list processes on device
POST   /api/devices/{id}/frida/attach         — attach to process with script
POST   /api/devices/{id}/frida/detach         — stop session
POST   /api/devices/{id}/frida/inject         — inject script by PID
GET    /api/devices/{id}/frida/script         — render anti_detect.js for device fingerprint
POST   /api/devices/{id}/frida/push-script    — push anti_detect.js to /data/local/tmp/
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db, get_current_user
from db.models import Device, DeviceStatus, DeviceFingerprint, User
from core.tools.frida_tool import FridaTool
from core.fingerprint.anti_detect import anti_detect, _render_frida_script

router = APIRouter(prefix="/devices", tags=["frida"])
frida_tool = FridaTool()
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _running_device(device_id: int, db: AsyncSession, user: User) -> Device:
    """Fetch device, check ownership and running status."""
    r = await db.execute(select(Device).where(Device.id == device_id))
    device = r.scalar_one_or_none()
    if not device:
        raise HTTPException(404, "Device not found")
    if device.owner_id != user.id and user.role.value != "admin":
        raise HTTPException(403, "Access denied")
    if device.status != DeviceStatus.running or not device.adb_serial:
        raise HTTPException(400, "Device must be running with ADB serial")
    return device


async def _get_fingerprint(device_id: int, db: AsyncSession) -> Optional[DeviceFingerprint]:
    """Fetch fingerprint for device."""
    r = await db.execute(select(DeviceFingerprint).where(DeviceFingerprint.device_id == device_id))
    return r.scalar_one_or_none()


# ─────────────────────────────────────────────────────────────────────────────
# Status
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{device_id}/frida/status")
async def get_frida_status(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Check if a Frida session is active on this device.
    """
    device = await _running_device(device_id, db, user)
    is_active = device_id in frida_tool._active_sessions
    pid = None
    if is_active:
        proc = frida_tool._active_sessions.get(device_id)
        if proc:
            pid = proc.pid

    return {
        "device_id": device_id,
        "active": is_active,
        "pid": pid,
        "serial": device.adb_serial,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Processes
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{device_id}/frida/processes")
async def list_frida_processes(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    List processes on the device via frida-ps.
    Requires frida-tools installed on host.
    """
    device = await _running_device(device_id, db, user)
    try:
        processes = await frida_tool.list_processes(device.adb_serial)
        return {"processes": processes}
    except Exception as e:
        raise HTTPException(500, f"Failed to list processes: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Attach / Detach
# ─────────────────────────────────────────────────────────────────────────────

class FridaAttachBody(BaseModel):
    process_name: str = Field(..., description="Process name or package (e.g. 'zygote', 'com.example.app')")
    script_type: str = Field(
        ...,
        description="'anti_detect' → render from fingerprint, 'custom' → use script_code"
    )
    script_code: Optional[str] = Field(None, description="Custom Frida script (required if script_type='custom')")


@router.post("/{device_id}/frida/attach")
async def attach_frida(
    device_id: int,
    body: FridaAttachBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Attach Frida to a process and inject a script.

    script_type='anti_detect': generates and injects anti-emulator hooks based on device fingerprint
    script_type='custom': injects the provided script_code
    """
    device = await _running_device(device_id, db, user)

    if body.script_type == "anti_detect":
        # Render anti_detect.js from fingerprint
        fp = await _get_fingerprint(device_id, db)
        if not fp:
            raise HTTPException(400, "No fingerprint found for device")

        # Convert ORM row to dict
        fp_dict = {
            "device_model": fp.device_model,
            "manufacturer": fp.manufacturer,
            "brand": fp.brand,
            "device_codename": fp.device_codename,
            "build_fingerprint": fp.build_fingerprint,
            "imei": fp.imei,
            "android_id": fp.android_id,
            "mac_address": fp.mac_address,
            "serial_number": fp.serial_number,
            "sdk_version": fp.sdk_version,
            "android_version": fp.android_version,
            "ap_version": fp.ap_version,
            "build_id": fp.build_id,
            "hardware": getattr(fp, "hardware", None) or "qcom",
            "board": getattr(fp, "board", None) or "lahaina",
            "cpu_abi_list_spoof": getattr(fp, "cpu_abi_list_spoof", None) or "arm64-v8a,armeabi-v7a,armeabi",
        }
        script_code = _render_frida_script(fp_dict)

    elif body.script_type == "custom":
        if not body.script_code:
            raise HTTPException(400, "script_code required for script_type='custom'")
        script_code = body.script_code

    else:
        raise HTTPException(400, f"Unknown script_type: {body.script_type}")

    # Attach
    try:
        result = await frida_tool.attach(
            device_id,
            device.adb_serial,
            body.process_name,
            script_code,  # pass code directly; attach will write to temp file
        )

        # Note: current attach() takes script_path, not script_code
        # We need to write to temp file first
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".js", delete=False, prefix="frida_inject_"
        ) as f:
            f.write(script_code)
            tmp_path = f.name

        try:
            result = await frida_tool.attach(
                device_id,
                device.adb_serial,
                body.process_name,
                tmp_path,
            )
            return result
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    except Exception as e:
        raise HTTPException(500, f"Attach failed: {e}")


@router.post("/{device_id}/frida/detach")
async def detach_frida(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Detach and stop the Frida session for this device.
    """
    device = await _running_device(device_id, db, user)
    try:
        ok = await frida_tool.detach(device_id)
        return {"success": ok, "message": "Detached"}
    except Exception as e:
        raise HTTPException(500, f"Detach failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Inject Script
# ─────────────────────────────────────────────────────────────────────────────

class FridaInjectBody(BaseModel):
    pid: int = Field(..., description="Process ID")
    script_code: str = Field(..., description="Frida script to inject")


@router.post("/{device_id}/frida/inject")
async def inject_frida_script(
    device_id: int,
    body: FridaInjectBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Inject a Frida script into a specific process by PID.
    """
    device = await _running_device(device_id, db, user)
    try:
        result = await frida_tool.inject_script(
            device.adb_serial,
            body.pid,
            body.script_code,
        )
        return result
    except Exception as e:
        raise HTTPException(500, f"Inject failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Get/Push Anti-Detect Script
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{device_id}/frida/script")
async def get_frida_script(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Get the rendered anti_detect.js script for this device's fingerprint.
    """
    device = await _running_device(device_id, db, user)
    fp = await _get_fingerprint(device_id, db)
    if not fp:
        raise HTTPException(400, "No fingerprint found for device")

    # Convert ORM to dict
    fp_dict = {
        "device_model": fp.device_model,
        "manufacturer": fp.manufacturer,
        "brand": fp.brand,
        "device_codename": fp.device_codename,
        "build_fingerprint": fp.build_fingerprint,
        "imei": fp.imei,
        "android_id": fp.android_id,
        "mac_address": fp.mac_address,
        "serial_number": fp.serial_number,
        "sdk_version": fp.sdk_version,
        "android_version": fp.android_version,
        "ap_version": fp.ap_version,
        "build_id": fp.build_id,
        "hardware": getattr(fp, "hardware", None) or "qcom",
        "board": getattr(fp, "board", None) or "lahaina",
        "cpu_abi_list_spoof": getattr(fp, "cpu_abi_list_spoof", None) or "arm64-v8a,armeabi-v7a,armeabi",
    }

    script = _render_frida_script(fp_dict)
    return {
        "device_id": device_id,
        "script": script,
        "mime_type": "application/javascript",
    }


@router.post("/{device_id}/frida/push-script")
async def push_frida_script(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Push the anti_detect.js script to /data/local/tmp/ via ADB.
    Does NOT inject; just writes the file so user can inject manually.
    """
    device = await _running_device(device_id, db, user)
    fp = await _get_fingerprint(device_id, db)
    if not fp:
        raise HTTPException(400, "No fingerprint found for device")

    # Convert ORM to dict
    fp_dict = {
        "device_model": fp.device_model,
        "manufacturer": fp.manufacturer,
        "brand": fp.brand,
        "device_codename": fp.device_codename,
        "build_fingerprint": fp.build_fingerprint,
        "imei": fp.imei,
        "android_id": fp.android_id,
        "mac_address": fp.mac_address,
        "serial_number": fp.serial_number,
        "sdk_version": fp.sdk_version,
        "android_version": fp.android_version,
        "ap_version": fp.ap_version,
        "build_id": fp.build_id,
        "hardware": getattr(fp, "hardware", None) or "qcom",
        "board": getattr(fp, "board", None) or "lahaina",
        "cpu_abi_list_spoof": getattr(fp, "cpu_abi_list_spoof", None) or "arm64-v8a,armeabi-v7a,armeabi",
    }

    try:
        # Use anti_detect's write method (pushes via ADB)
        from core.tools.adb import ADBTool
        adb = ADBTool()

        script = _render_frida_script(fp_dict)
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".js", delete=False, prefix="anti_detect_"
        ) as f:
            f.write(script)
            tmp_path = f.name

        try:
            remote_path = "/data/local/tmp/anti_detect.js"
            await adb.push_file(device.adb_serial, tmp_path, remote_path)
            await adb.shell(device.adb_serial, f"chmod 644 {remote_path}")
            return {
                "success": True,
                "remote_path": remote_path,
                "message": "Script pushed. Inject with: frida -U -n <package> -l /data/local/tmp/anti_detect.js",
            }
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    except Exception as e:
        raise HTTPException(500, f"Push failed: {e}")

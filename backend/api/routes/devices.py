import logging
import os
import platform
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from config import settings
from api.deps import get_db, get_current_user
from db.models import Device, DeviceStatus, User, OperationLog, OperationStatus, DeviceFingerprint, ProxyConfig
from core.emulator.manager import EmulatorManager
from core.emulator.avd import normalize_system_image_arch
from core.tools.adb import ADBTool
from core.fingerprint.generator import FingerprintGenerator, DEVICE_CREATION_PRESETS, DEVICE_PROFILES
from core.firmware.samfw import merge_firmware_into_fingerprint, resolve_firmware_meta
from services.ws_manager import ws_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/devices", tags=["devices"])

emulator_manager = EmulatorManager()
adb_tool = ADBTool()
fp_generator = FingerprintGenerator()


def _default_device_arch() -> str:
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        return "arm64-v8a"
    return "x86_64"


class DeviceCreateRequest(BaseModel):
    name: str
    ram_mb: int = 2048
    cpu_cores: int = 2
    api_level: int = 31
    arch: str = _default_device_arch()
    # مثال: samsung_sm_g996b_android15 — يفعّل Android 15 + صورة google_apis + بصمة SM-G996B و AP/CSC
    preset: Optional[str] = None
    # اسم ملف ZIP أو مجلد حزمة Odin (تحت FIRMWARE_PACKAGES_DIR)، مثل: ...zip أو G996BXXSJHZA6_G996BOXMJHZA6_XSG
    firmware_package: Optional[str] = None


class DeviceResponse(BaseModel):
    id: int
    name: str
    status: str
    avd_name: Optional[str]
    adb_port: Optional[int]
    adb_serial: Optional[str]
    scrcpy_port: Optional[int]
    qmp_port: Optional[int]
    console_port: Optional[int]
    pid: Optional[int]
    ram_mb: int
    cpu_cores: int
    api_level: int
    arch: str
    owner_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ShellRequest(BaseModel):
    cmd: str


class ShellResponse(BaseModel):
    output: str
    exit_code: int = 0


class LogEntry(BaseModel):
    id: int
    action: str
    status: str
    detail: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


async def _get_device_or_404(device_id: int, db: AsyncSession, user: User) -> Device:
    result = await db.execute(
        select(Device).where(Device.id == device_id)
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if device.owner_id != user.id and user.role.value != "admin":
        raise HTTPException(status_code=403, detail="Access denied")
    return device


async def _log_operation(db: AsyncSession, device_id: int, user_id: int, action: str, status: OperationStatus, detail: str = ""):
    log = OperationLog(
        device_id=device_id,
        user_id=user_id,
        action=action,
        status=status,
        detail=detail,
    )
    db.add(log)
    await db.flush()


@router.get("", response_model=List[DeviceResponse])
async def list_devices(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role.value == "admin":
        result = await db.execute(select(Device).order_by(Device.created_at.desc()))
    else:
        result = await db.execute(
            select(Device).where(Device.owner_id == current_user.id).order_by(Device.created_at.desc())
        )
    return result.scalars().all()


@router.post("", response_model=DeviceResponse, status_code=status.HTTP_201_CREATED)
async def create_device(
    data: DeviceCreateRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Check device limit
    count_result = await db.execute(select(Device).where(Device.owner_id == current_user.id))
    existing = count_result.scalars().all()
    if len(existing) >= settings.MAX_INSTANCES:
        raise HTTPException(status_code=400, detail=f"Maximum instances ({settings.MAX_INSTANCES}) reached")

    preset_cfg = DEVICE_CREATION_PRESETS.get(data.preset) if data.preset else None
    if data.preset and not preset_cfg:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown preset '{data.preset}'. Use GET /api/meta/device-presets for valid keys.",
        )

    fw_meta = None
    if data.firmware_package:
        safe_name = os.path.basename(data.firmware_package.strip())
        fw_path = Path(settings.FIRMWARE_PACKAGES_DIR) / safe_name
        if not fw_path.is_file() and not fw_path.is_dir():
            raise HTTPException(
                status_code=400,
                detail=f"firmware_package not found: {safe_name} (place it under {settings.FIRMWARE_PACKAGES_DIR})",
            )
        fw_meta = resolve_firmware_meta(safe_name)
        if not fw_meta:
            raise HTTPException(
                status_code=400,
                detail="firmware_package name does not match SAMFW ZIP or AP_CSC_SALES folder pattern (see GET /api/meta/firmware-packages)",
            )
        # بدون preset صريح: إن وُجد تعريف جاهز لنفس الموديل نطبّقه تلقائياً (مثل SM-G996B)
        if not preset_cfg:
            for key, cfg in DEVICE_CREATION_PRESETS.items():
                if str(cfg.get("device_model", "")).upper() == fw_meta["device_model"].upper():
                    preset_cfg = cfg
                    break
        if preset_cfg and str(preset_cfg.get("device_model", "")).upper() != fw_meta["device_model"].upper():
            raise HTTPException(
                status_code=400,
                detail=f"preset device_model mismatch with firmware (preset={preset_cfg.get('device_model')}, firmware={fw_meta['device_model']})",
            )
        prof = next(
            (p for p in DEVICE_PROFILES if p["device_model"].upper() == fw_meta["device_model"].upper()),
            None,
        )
        if not prof:
            raise HTTPException(
                status_code=400,
                detail=f"No fingerprint profile for {fw_meta['device_model']}; add it to DEVICE_PROFILES or omit firmware_package.",
            )

    if preset_cfg:
        api_level = int(preset_cfg["api_level"])
        arch = str(preset_cfg["arch"])
        ram_mb = max(data.ram_mb, int(preset_cfg.get("ram_mb", data.ram_mb)))
        cpu_cores = max(data.cpu_cores, int(preset_cfg.get("cpu_cores", data.cpu_cores)))
        fp_data = fp_generator.generate(device_model=preset_cfg["device_model"])
    else:
        api_level = data.api_level
        arch = data.arch
        ram_mb = data.ram_mb
        cpu_cores = data.cpu_cores
        dm = fw_meta["device_model"] if fw_meta else None
        fp_data = fp_generator.generate(device_model=dm) if dm else fp_generator.generate()

    if fw_meta:
        fp_data = merge_firmware_into_fingerprint(fp_data, fw_meta)

    arch = normalize_system_image_arch(arch)

    avd_name = f"emulator_{data.name.replace(' ', '_').lower()}_{current_user.id}"

    device = Device(
        name=data.name,
        status=DeviceStatus.created,
        avd_name=avd_name,
        ram_mb=ram_mb,
        cpu_cores=cpu_cores,
        api_level=api_level,
        arch=arch,
        owner_id=current_user.id,
    )
    db.add(device)
    await db.flush()
    await db.refresh(device)

    fp = DeviceFingerprint(
        device_id=device.id,
        imei=fp_data["imei"],
        android_id=fp_data["android_id"],
        mac_address=fp_data["mac_address"],
        device_model=fp_data["device_model"],
        manufacturer=fp_data["manufacturer"],
        brand=fp_data["brand"],
        device_codename=fp_data["device_codename"],
        build_fingerprint=fp_data["build_fingerprint"],
        sdk_version=fp_data["sdk_version"],
        android_version=fp_data["android_version"],
        board=fp_data["board"],
        hardware=fp_data["hardware"],
        serial_number=fp_data["serial_number"],
        latitude=fp_data["latitude"],
        longitude=fp_data["longitude"],
        altitude=fp_data["altitude"],
        network_type=fp_data["network_type"],
        ip_address=fp_data["ip_address"],
        timezone=fp_data["timezone"],
        language=fp_data["language"],
        country=fp_data["country"],
        ap_version=fp_data.get("ap_version"),
        csc_version=fp_data.get("csc_version"),
    )
    db.add(fp)

    # Create default proxy config
    proxy = ProxyConfig(device_id=device.id, enabled=False)
    db.add(proxy)

    await db.flush()
    await db.refresh(device)

    # Create AVD in background
    background_tasks.add_task(_create_avd_background, device.id, avd_name, api_level, arch)
    log_detail = f"Device {data.name} created"
    if fw_meta:
        log_detail += f" | firmware={fw_meta.get('filename')} AP={fw_meta.get('ap_version')} CSC={fw_meta.get('sales_code')}"
    await _log_operation(db, device.id, current_user.id, "create_device", OperationStatus.success, log_detail)

    return device


async def _create_avd_background(device_id: int, avd_name: str, api_level: int, arch: str):
    from db.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        try:
            avd = emulator_manager.avd_backend
            success = await avd.create_avd(avd_name, api_level=api_level, arch=arch)
            result = await db.execute(select(Device).where(Device.id == device_id))
            device = result.scalar_one_or_none()
            if device:
                if not success:
                    device.status = DeviceStatus.error
                await db.commit()
        except Exception as e:
            logger.error(f"AVD creation failed for device {device_id}: {e}")


@router.get("/{device_id}", response_model=DeviceResponse)
async def get_device(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _get_device_or_404(device_id, db, current_user)


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device = await _get_device_or_404(device_id, db, current_user)
    # Stop if running
    if device.status in (DeviceStatus.running, DeviceStatus.booting):
        try:
            await emulator_manager.stop(device)
        except Exception as e:
            logger.warning(f"Error stopping device {device_id} during delete: {e}")
    # Delete AVD
    try:
        if device.avd_name:
            await emulator_manager.avd_backend.delete_avd(device.avd_name)
    except Exception as e:
        logger.warning(f"Error deleting AVD for device {device_id}: {e}")
    await _log_operation(db, device_id, current_user.id, "delete_device", OperationStatus.success)
    await db.delete(device)
    await db.flush()


@router.post("/{device_id}/start", response_model=DeviceResponse)
async def start_device(
    device_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device = await _get_device_or_404(device_id, db, current_user)
    if device.status == DeviceStatus.running:
        raise HTTPException(status_code=400, detail="Device is already running")

    device.status = DeviceStatus.booting
    await db.flush()
    await db.refresh(device)
    await ws_manager.broadcast(device_id, {"type": "status", "status": "booting", "device_id": device_id})

    background_tasks.add_task(_start_device_background, device_id)
    await _log_operation(db, device_id, current_user.id, "start_device", OperationStatus.pending, "Starting emulator")
    return device


async def _start_device_background(device_id: int):
    from db.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(select(Device).where(Device.id == device_id))
            device = result.scalar_one_or_none()
            if not device:
                return
            success, info = await emulator_manager.start(device)
            if success:
                device.status = DeviceStatus.running
                device.pid = info.get("pid")
                device.adb_port = info.get("adb_port")
                device.adb_serial = info.get("adb_serial")
                device.console_port = info.get("console_port")
            else:
                device.status = DeviceStatus.error
            await db.commit()
            await ws_manager.broadcast(
                device_id,
                {"type": "status", "status": device.status.value, "device_id": device_id, "adb_serial": device.adb_serial}
            )
        except Exception as e:
            logger.error(f"Start device {device_id} failed: {e}")
            async with AsyncSessionLocal() as db2:
                result = await db2.execute(select(Device).where(Device.id == device_id))
                dev = result.scalar_one_or_none()
                if dev:
                    dev.status = DeviceStatus.error
                    await db2.commit()


@router.post("/{device_id}/stop", response_model=DeviceResponse)
async def stop_device(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device = await _get_device_or_404(device_id, db, current_user)
    if device.status == DeviceStatus.stopped:
        raise HTTPException(status_code=400, detail="Device is already stopped")

    try:
        await emulator_manager.stop(device)
    except Exception as e:
        logger.error(f"Error stopping device {device_id}: {e}")

    device.status = DeviceStatus.stopped
    device.pid = None
    await db.flush()
    await db.refresh(device)
    await ws_manager.broadcast(device_id, {"type": "status", "status": "stopped", "device_id": device_id})
    await _log_operation(db, device_id, current_user.id, "stop_device", OperationStatus.success)
    return device


@router.post("/{device_id}/restart", response_model=DeviceResponse)
async def restart_device(
    device_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device = await _get_device_or_404(device_id, db, current_user)
    # Stop first
    try:
        await emulator_manager.stop(device)
    except Exception as e:
        logger.warning(f"Stop during restart failed: {e}")

    device.status = DeviceStatus.booting
    device.pid = None
    await db.flush()
    await db.refresh(device)
    background_tasks.add_task(_start_device_background, device_id)
    await _log_operation(db, device_id, current_user.id, "restart_device", OperationStatus.pending)
    return device


@router.post("/{device_id}/shell", response_model=ShellResponse)
async def run_shell(
    device_id: int,
    body: ShellRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device = await _get_device_or_404(device_id, db, current_user)
    if device.status != DeviceStatus.running or not device.adb_serial:
        raise HTTPException(status_code=400, detail="Device is not running")

    try:
        output = await adb_tool.shell(device.adb_serial, body.cmd)
        await _log_operation(db, device_id, current_user.id, "shell", OperationStatus.success, body.cmd[:200])
        return ShellResponse(output=output)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{device_id}/screenshot")
async def get_screenshot(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device = await _get_device_or_404(device_id, db, current_user)
    if device.status != DeviceStatus.running or not device.adb_serial:
        raise HTTPException(status_code=400, detail="Device is not running")

    try:
        png_bytes = await adb_tool.screenshot(device.adb_serial)
        return Response(content=png_bytes, media_type="image/png")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Screenshot failed: {e}")


@router.get("/{device_id}/logs", response_model=List[LogEntry])
async def get_device_logs(
    device_id: int,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_device_or_404(device_id, db, current_user)
    result = await db.execute(
        select(OperationLog)
        .where(OperationLog.device_id == device_id)
        .order_by(OperationLog.created_at.desc())
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/{device_id}/logcat")
async def get_logcat(
    device_id: int,
    lines: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device = await _get_device_or_404(device_id, db, current_user)
    if device.status != DeviceStatus.running or not device.adb_serial:
        raise HTTPException(status_code=400, detail="Device is not running")
    try:
        output = await adb_tool.logcat(device.adb_serial, num_lines=lines)
        return {"lines": output.split("\n"), "total": len(output.split("\n"))}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

import json
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
from core.emulator.samsung.exynos_emulator import ExynsosCPUEmulator
from core.tools.adb import ADBTool
from core.fingerprint.generator import FingerprintGenerator, DEVICE_CREATION_PRESETS, DEVICE_PROFILES
from core.firmware.ap_buildprop import enrich_fp_data_from_firmware_disk_path
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


def _get_exynos_for_device(device_model: str) -> Optional[str]:
    """تحديد معالج Exynos بناءً على موديل الجهاز"""
    model_upper = device_model.upper()

    # خريطة الموديلات إلى معالجات Exynos
    model_to_soc = {
        "SM-G960": "Exynos8895",   # Galaxy S9
        "SM-G965": "Exynos8895",   # Galaxy S9+
        "SM-G973": "Exynos9810",   # Galaxy S10
        "SM-G975": "Exynos9810",   # Galaxy S10+
        "SM-G977": "Exynos9810",   # Galaxy S10 5G
        "SM-G996": "Exynos9810",   # Galaxy S21
        "SM-S901": "Exynos8895",   # Galaxy S22 (variant)
        "SM-S921": "Exynos8895",   # Galaxy S22
        "SM-S926": "Exynos8895",   # Galaxy S22 Ultra
        "SM-S721": "Exynos8895",   # Galaxy S24
    }

    # ابحث عن أول 5 أحرف من الموديل
    for model_prefix, soc in model_to_soc.items():
        if model_upper.startswith(model_prefix):
            return soc

    # القيمة الافتراضية
    return "Exynos8895"


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
    # physical = هاتف سامسونغ حقيقي (One UI) عبر USB أو adb connect — يتطلب host_adb_serial
    emulator_kind: str = "avd"
    host_adb_serial: Optional[str] = None


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
    emulator_kind: str = "avd"
    host_adb_serial: Optional[str] = None
    owner_id: int
    created_at: datetime
    updated_at: datetime
    # populated separately from fingerprint
    device_model: Optional[str] = None

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


def _attach_device_model(device: Device, fp_map: dict) -> DeviceResponse:
    """Build DeviceResponse with device_model populated from fingerprint map."""
    resp = DeviceResponse.model_validate(device)
    fp = fp_map.get(device.id)
    if fp:
        resp.device_model = fp.device_model
    return resp


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
    devices = result.scalars().all()
    if not devices:
        return []
    device_ids = [d.id for d in devices]
    fp_result = await db.execute(
        select(DeviceFingerprint).where(DeviceFingerprint.device_id.in_(device_ids))
    )
    fp_map = {fp.device_id: fp for fp in fp_result.scalars().all()}
    return [_attach_device_model(d, fp_map) for d in devices]


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

    ek = (data.emulator_kind or "avd").strip().lower()
    if ek not in ("avd", "physical"):
        raise HTTPException(status_code=400, detail="emulator_kind must be 'avd' or 'physical'")
    if ek == "physical":
        if not (data.host_adb_serial or "").strip():
            raise HTTPException(
                status_code=400,
                detail="host_adb_serial is required for physical devices (adb devices → serial)",
            )

    fw_meta = None
    fw_path: Optional[Path] = None
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

        # استخراج خصائص Samsung الحقيقية من AP tar (أو اشتقاقها من البيانات المعروفة)
        from core.firmware.extractor import find_ap_file, extract_samsung_build_props, derive_samsung_props
        fw_dir = Path(settings.FIRMWARE_PACKAGES_DIR)
        ap_file = find_ap_file(fw_dir, fw_meta.get("ap_version", ""))
        extracted_props = {}
        if ap_file:
            extracted_props = extract_samsung_build_props(ap_file)
        if not extracted_props:
            extracted_props = derive_samsung_props(
                fw_meta.get("device_model", ""),
                fw_meta.get("ap_version", ""),
                fw_meta.get("csc_version"),
                fw_meta.get("sales_code"),
            )
        if extracted_props:
            fw_meta["extracted_props"] = extracted_props

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

    ap_prop_warnings: List[str] = []
    if fw_path is not None:
        ap_prop_warnings = enrich_fp_data_from_firmware_disk_path(fp_data, fw_path)

    arch = normalize_system_image_arch(arch)

    avd_name: Optional[str] = None
    if ek == "avd":
        avd_name = f"emulator_{data.name.replace(' ', '_').lower()}_{current_user.id}"

    device = Device(
        name=data.name,
        status=DeviceStatus.created,
        avd_name=avd_name,
        ram_mb=ram_mb,
        cpu_cores=cpu_cores,
        api_level=api_level,
        arch=arch,
        emulator_kind=ek,
        host_adb_serial=(data.host_adb_serial or "").strip() if ek == "physical" else None,
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
        extended_json=(
            json.dumps(fp_data["extended"], ensure_ascii=False)
            if isinstance(fp_data.get("extended"), dict)
            else None
        ),
    )
    db.add(fp)

    # Create default proxy config
    proxy = ProxyConfig(device_id=device.id, enabled=False)
    db.add(proxy)

    await db.flush()
    await db.refresh(device)

    # إنشاء AVD في الخلفية فقط للمحاكي
    if ek == "avd" and avd_name:
        # إذا كان جهاز Samsung، أضف Exynos emulator
        soc_model = None
        if fw_meta and "SM-" in fw_meta.get("device_model", ""):
            # حدد معالج Exynos بناءً على الموديل
            device_model = fw_meta.get("device_model", "")
            soc_model = _get_exynos_for_device(device_model)

        background_tasks.add_task(_create_avd_background, device.id, avd_name, api_level, arch, soc_model)
    log_detail = f"Device {data.name} created"
    if fw_meta:
        log_detail += f" | firmware={fw_meta.get('filename')} AP={fw_meta.get('ap_version')} CSC={fw_meta.get('sales_code')}"
    if ap_prop_warnings:
        log_detail += " | ap_buildprop=" + "; ".join(ap_prop_warnings[:3])
        if len(ap_prop_warnings) > 3:
            log_detail += f" (+{len(ap_prop_warnings) - 3} more)"
    await _log_operation(db, device.id, current_user.id, "create_device", OperationStatus.success, log_detail)

    return device


async def _create_avd_background(
    device_id: int,
    avd_name: str,
    api_level: int,
    arch: str,
    soc_model: Optional[str] = None
):
    """إنشاء AVD في الخلفية مع محاكاة Exynos إذا كان جهاز Samsung"""
    from db.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        try:
            # إذا كان جهاز Samsung، هيّأ محاكي Exynos
            exynos_info = None
            if soc_model:
                logger.info(f"Initializing Exynos emulator for device {device_id}: {soc_model}")
                try:
                    exynos = ExynsosCPUEmulator(soc_model)
                    init_result = await exynos.initialize()

                    if init_result:
                        exynos_info = {
                            "soc": soc_model,
                            "cores": exynos.get_cpu_count(),
                            "specs": exynos.get_specs(),
                            "status": "initialized"
                        }
                        logger.info(f"Exynos {soc_model} initialized successfully for device {device_id}")
                    else:
                        logger.warning(f"Failed to initialize Exynos {soc_model} for device {device_id}")
                except Exception as e:
                    logger.error(f"Error initializing Exynos: {e}")

            # Store Exynos info in fingerprint extended_json
            if exynos_info:
                fp_row = await db.execute(
                    select(DeviceFingerprint).where(DeviceFingerprint.device_id == device_id)
                )
                fp = fp_row.scalar_one_or_none()
                if fp:
                    extended = {}
                    if fp.extended_json:
                        try:
                            extended = json.loads(fp.extended_json)
                        except:
                            pass
                    extended["exynos"] = exynos_info
                    fp.extended_json = json.dumps(extended, ensure_ascii=False)
                    await db.flush()

            avd = emulator_manager.avd_backend
            fp_row = await db.execute(
                select(DeviceFingerprint).where(DeviceFingerprint.device_id == device_id)
            )
            fp = fp_row.scalar_one_or_none()
            success = await avd.create_avd(
                avd_name,
                api_level=api_level,
                arch=arch,
                manufacturer=fp.manufacturer if fp else None,
                brand=fp.brand if fp else None,
                device_model=fp.device_model if fp else None,
            )
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
    device = await _get_device_or_404(device_id, db, current_user)
    fp_result = await db.execute(
        select(DeviceFingerprint).where(DeviceFingerprint.device_id == device_id)
    )
    fp = fp_result.scalar_one_or_none()
    resp = DeviceResponse.model_validate(device)
    if fp:
        resp.device_model = fp.device_model
    return resp


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
    device.adb_serial = None
    await db.flush()
    await db.refresh(device)
    await ws_manager.broadcast(device_id, {"type": "status", "status": "booting", "device_id": device_id})

    background_tasks.add_task(_start_device_background, device_id)
    await _log_operation(db, device_id, current_user.id, "start_device", OperationStatus.pending, "Starting emulator")
    return device


async def _start_device_background(device_id: int):
    from db.database import AsyncSessionLocal
    from core.fingerprint.spoofer import FingerprintSpoofer
    from core.fingerprint.merge import fingerprint_row_to_apply_dict
    from core.fingerprint.samsung_enhanced import merge_profile_defaults_for_apply

    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(select(Device).where(Device.id == device_id))
            device = result.scalar_one_or_none()
            if not device:
                return
            owner_id = device.owner_id

            # Fetch Samsung props to inject at boot via -prop (sets ro.* properties)
            samsung_boot_props = None
            fp_row = await db.execute(
                select(DeviceFingerprint).where(DeviceFingerprint.device_id == device_id)
            )
            fp_pre = fp_row.scalar_one_or_none()
            if fp_pre and fp_pre.device_model and fp_pre.device_model.startswith("SM-"):
                from core.firmware.extractor import derive_samsung_props
                samsung_boot_props = derive_samsung_props(
                    fp_pre.device_model,
                    fp_pre.ap_version or "",
                    fp_pre.csc_version,
                )
                logger.info(f"Will inject {len(samsung_boot_props)} Samsung props at boot for device {device_id}")

            success, info = await emulator_manager.start(device, samsung_props=samsung_boot_props)
            adb_serial = None
            console_port = None
            if success:
                device.status = DeviceStatus.running
                device.pid = info.get("pid")
                device.adb_port = info.get("adb_port")
                device.adb_serial = info.get("adb_serial")
                device.console_port = info.get("console_port")
                adb_serial = device.adb_serial
                console_port = device.console_port
            else:
                device.status = DeviceStatus.error
            await db.commit()
            await ws_manager.broadcast(
                device_id,
                {"type": "status", "status": device.status.value, "device_id": device_id, "adb_serial": device.adb_serial}
            )

            # بعد الإقلاع: تطبيق البصمة + طبقة إخفاء المحاكي تلقائياً (يتطلب adb root كالمعتاد)
            if success and adb_serial:
                fp_row = await db.execute(
                    select(DeviceFingerprint).where(DeviceFingerprint.device_id == device_id)
                )
                fp = fp_row.scalar_one_or_none()
                if fp:
                    try:
                        raw = fingerprint_row_to_apply_dict(
                            fp, {"console_port": console_port}
                        )
                        raw.pop("_extended_raw", None)
                        merged = merge_profile_defaults_for_apply(raw)

                        # استخراج خصائص Samsung من firmware إذا كانت متاحة
                        if fp.ap_version:
                            from core.firmware.extractor import derive_samsung_props
                            extra_props = derive_samsung_props(
                                fp.device_model,
                                fp.ap_version,
                                fp.csc_version,
                            )
                            merged["extracted_props"] = extra_props

                        spoofer = FingerprintSpoofer()
                        adb_tool = ADBTool()
                        report = await spoofer.apply(adb_tool, adb_serial, merged)
                        n_ok, n_fail = len(report.get("applied", [])), len(report.get("failed", []))
                        await _log_operation(
                            db,
                            device_id,
                            owner_id,
                            "fingerprint_auto_apply",
                            OperationStatus.success,
                            f"applied={n_ok} failed={n_fail}",
                        )
                        await db.commit()
                    except Exception as ex:
                        logger.warning("fingerprint_auto_apply device=%s: %s", device_id, ex)
                        try:
                            await _log_operation(
                                db,
                                device_id,
                                owner_id,
                                "fingerprint_auto_apply",
                                OperationStatus.failure,
                                str(ex)[:500],
                            )
                            await db.commit()
                        except Exception:
                            pass
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
    device.adb_serial = None
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
    device.adb_serial = None
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
        err = str(e).lower()
        if "not found" in err and ("device" in err or "adb:" in err):
            raise HTTPException(
                status_code=503,
                detail="ADB device not connected — emulator may have stopped or serial is stale.",
            )
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

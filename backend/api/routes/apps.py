import logging
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from api.deps import get_db, get_current_user
from db.models import Device, DeviceStatus, User, OperationLog, OperationStatus
from core.tools.adb import ADBTool
from core.tools.apk_bundle import safe_extract_apks_from_zip, sort_apk_paths_for_install
from config import settings

router = APIRouter(prefix="/devices", tags=["apps"])
adb_tool = ADBTool()
logger = logging.getLogger(__name__)


class PackageListResponse(BaseModel):
    packages: list[str]
    count: int


class InstallResponse(BaseModel):
    success: bool
    message: str
    package: str = ""


async def _get_device_or_404(device_id: int, db: AsyncSession, user: User) -> Device:
    result = await db.execute(select(Device).where(Device.id == device_id))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if device.owner_id != user.id and user.role.value != "admin":
        raise HTTPException(status_code=403, detail="Access denied")
    return device


@router.post("/{device_id}/install", response_model=InstallResponse)
async def install_apk(
    device_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device = await _get_device_or_404(device_id, db, current_user)
    if device.status != DeviceStatus.running or not device.adb_serial:
        raise HTTPException(status_code=400, detail="Device must be running to install APK")

    safe_name = Path(file.filename or "").name
    lower = safe_name.lower()
    if not lower.endswith(".apk") and not lower.endswith(".apkm"):
        raise HTTPException(
            status_code=400,
            detail="File must be .apk or .apkm (APKM = ZIP of split APKs, e.g. from APKMirror export)",
        )

    upload_dir = Path(settings.UPLOADS_DIR) / str(device_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    saved_path = upload_dir / safe_name
    extract_dir: str | None = None

    try:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Empty file")
        saved_path.write_bytes(content)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")

    try:
        if lower.endswith(".apkm"):
            extract_dir = tempfile.mkdtemp(prefix="apkm_install_")
            apks = safe_extract_apks_from_zip(saved_path, Path(extract_dir))
            ordered = sort_apk_paths_for_install([str(p) for p in apks])
            output = await adb_tool.install_multiple_apks(device.adb_serial, ordered)
        else:
            output = await adb_tool.install_apk(device.adb_serial, str(saved_path))
        success = "Success" in output or "success" in output.lower()
        message = output.strip()

        log = OperationLog(
            device_id=device_id,
            user_id=current_user.id,
            action="install_apk",
            status=OperationStatus.success if success else OperationStatus.failure,
            detail=f"File: {safe_name}, Result: {message[:200]}",
        )
        db.add(log)
        await db.flush()

        return InstallResponse(success=success, message=message, package=safe_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"APK install failed: {e}")
        raise HTTPException(status_code=500, detail=f"Install failed: {e}")
    finally:
        if extract_dir:
            shutil.rmtree(extract_dir, ignore_errors=True)
        try:
            saved_path.unlink(missing_ok=True)
        except Exception:
            pass


@router.get("/{device_id}/packages", response_model=PackageListResponse)
async def list_packages(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device = await _get_device_or_404(device_id, db, current_user)
    if device.status != DeviceStatus.running or not device.adb_serial:
        raise HTTPException(status_code=400, detail="Device must be running")

    try:
        packages = await adb_tool.list_packages(device.adb_serial)
        return PackageListResponse(packages=packages, count=len(packages))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{device_id}/packages/{pkg}")
async def uninstall_package(
    device_id: int,
    pkg: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device = await _get_device_or_404(device_id, db, current_user)
    if device.status != DeviceStatus.running or not device.adb_serial:
        raise HTTPException(status_code=400, detail="Device must be running")

    try:
        output = await adb_tool.uninstall_pkg(device.adb_serial, pkg)
        success = "Success" in output
        log = OperationLog(
            device_id=device_id,
            user_id=current_user.id,
            action="uninstall_pkg",
            status=OperationStatus.success if success else OperationStatus.failure,
            detail=f"Package: {pkg}",
        )
        db.add(log)
        await db.flush()
        return {"success": success, "message": output.strip()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

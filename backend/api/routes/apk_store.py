import logging
import shutil
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db, get_current_user
from config import settings
from core.tools.adb import ADBTool
from core.tools.apk_bundle import safe_extract_apks_from_zip, sort_apk_paths_for_install
from db.models import Device, DeviceStatus, OperationLog, OperationStatus, StoredApk, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/store", tags=["apk-store"])
adb_tool = ADBTool()

STORE_SUBDIR = "apk_store"


class StoredApkResponse(BaseModel):
    id: int
    display_name: str | None
    original_filename: str
    size_bytes: int
    created_at: str

    class Config:
        from_attributes = True

    @classmethod
    def from_row(cls, row: StoredApk) -> "StoredApkResponse":
        return cls(
            id=row.id,
            display_name=row.display_name,
            original_filename=row.original_filename,
            size_bytes=int(row.size_bytes or 0),
            created_at=row.created_at.isoformat() if row.created_at else "",
        )


class StoredApkCreateBody(BaseModel):
    display_name: str | None = Field(None, max_length=256)


class InstallFromStoreResponse(BaseModel):
    success: bool
    message: str
    package: str = ""


def _store_dir() -> Path:
    p = Path(settings.UPLOADS_DIR) / STORE_SUBDIR
    p.mkdir(parents=True, exist_ok=True)
    return p


async def _get_stored_or_404(apk_id: int, db: AsyncSession, user: User) -> StoredApk:
    r = await db.execute(select(StoredApk).where(StoredApk.id == apk_id))
    row = r.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="APK not found in store")
    if row.owner_id != user.id and user.role.value != "admin":
        raise HTTPException(status_code=403, detail="Access denied")
    return row


async def _get_device_or_404(device_id: int, db: AsyncSession, user: User) -> Device:
    r = await db.execute(select(Device).where(Device.id == device_id))
    d = r.scalar_one_or_none()
    if not d:
        raise HTTPException(status_code=404, detail="Device not found")
    if d.owner_id != user.id and user.role.value != "admin":
        raise HTTPException(status_code=403, detail="Access denied")
    return d


@router.get("/apks", response_model=list[StoredApkResponse])
async def list_stored_apks(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role.value == "admin":
        q = select(StoredApk).order_by(StoredApk.created_at.desc())
    else:
        q = select(StoredApk).where(StoredApk.owner_id == current_user.id).order_by(StoredApk.created_at.desc())
    r = await db.execute(q)
    return [StoredApkResponse.from_row(x) for x in r.scalars().all()]


@router.post("/apks", response_model=StoredApkResponse, status_code=201)
async def upload_to_store(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    lower = (file.filename or "").lower()
    if not lower.endswith(".apk") and not lower.endswith(".apkm"):
        raise HTTPException(status_code=400, detail="File must be an .apk or .apkm bundle")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    ext = ".apkm" if lower.endswith(".apkm") else ".apk"
    safe = f"{uuid.uuid4().hex}{ext}"
    path = _store_dir() / safe
    path.write_bytes(data)

    row = StoredApk(
        owner_id=current_user.id,
        display_name=None,
        stored_filename=safe,
        original_filename=file.filename[:250],
        size_bytes=len(data),
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return StoredApkResponse.from_row(row)


@router.patch("/apks/{apk_id}", response_model=StoredApkResponse)
async def update_stored_apk_meta(
    apk_id: int,
    body: StoredApkCreateBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = await _get_stored_or_404(apk_id, db, current_user)
    if body.display_name is not None:
        row.display_name = body.display_name[:256] if body.display_name else None
    await db.flush()
    await db.refresh(row)
    return StoredApkResponse.from_row(row)


@router.delete("/apks/{apk_id}", status_code=204)
async def delete_stored_apk(
    apk_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = await _get_stored_or_404(apk_id, db, current_user)
    path = _store_dir() / row.stored_filename
    try:
        path.unlink(missing_ok=True)
    except Exception as e:
        logger.warning("Could not delete store file %s: %s", path, e)
    await db.delete(row)
    await db.flush()


@router.post("/apks/{apk_id}/install/{device_id}", response_model=InstallFromStoreResponse)
async def install_from_store(
    apk_id: int,
    device_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = await _get_stored_or_404(apk_id, db, current_user)
    device = await _get_device_or_404(device_id, db, current_user)

    if device.status != DeviceStatus.running or not device.adb_serial:
        raise HTTPException(status_code=400, detail="Device must be running to install APK")

    path = _store_dir() / row.stored_filename
    if not path.is_file():
        raise HTTPException(status_code=410, detail="APK file missing on disk — re-upload")

    extract_dir: str | None = None
    try:
        orig_lower = (row.original_filename or "").lower()
        if orig_lower.endswith(".apkm") or path.suffix.lower() == ".apkm":
            extract_dir = tempfile.mkdtemp(prefix="apkm_store_")
            apks = safe_extract_apks_from_zip(path, Path(extract_dir))
            ordered = sort_apk_paths_for_install([str(p) for p in apks])
            output = await adb_tool.install_multiple_apks(device.adb_serial, ordered)
        else:
            output = await adb_tool.install_apk(device.adb_serial, str(path))
        success = "Success" in output or "success" in output.lower()
        message = output.strip()
        log = OperationLog(
            device_id=device_id,
            user_id=current_user.id,
            action="install_apk_from_store",
            status=OperationStatus.success if success else OperationStatus.failure,
            detail=f"store_id={apk_id} {row.original_filename}: {message[:200]}",
        )
        db.add(log)
        await db.flush()
        return InstallFromStoreResponse(success=success, message=message, package=row.original_filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("install_from_store failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Install failed: {e}")
    finally:
        if extract_dir:
            shutil.rmtree(extract_dir, ignore_errors=True)

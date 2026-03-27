"""
Firmware download management endpoints.

Routes:
-------
POST   /api/firmware/download          Start a firmware download job
GET    /api/firmware/jobs              List all active/recent jobs
GET    /api/firmware/jobs/{job_id}     Get job status + progress
DELETE /api/firmware/jobs/{job_id}     Cancel a download job
GET    /api/firmware/packages          List locally available firmware packages
GET    /api/firmware/entries           List firmware entries from database
POST   /api/firmware/entries           Create new firmware entry
PUT    /api/firmware/entries/{id}      Update firmware entry
DELETE /api/firmware/entries/{id}      Delete firmware entry
POST   /api/firmware/sync              Scan disk and import new packages to database
POST   /api/firmware/upload            Upload firmware file (auto-detect & parse)
"""

from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import select

from api.deps import get_current_user, get_db
from core.firmware.downloader import (
    DownloadJob,
    cancel_job,
    get_job,
    list_jobs,
    start_firmware_download,
)
from core.firmware.scan import iter_firmware_packages
from config import settings
from db.models import User, FirmwareEntry
from pathlib import Path
from datetime import datetime
from core.firmware.samfw import resolve_firmware_meta

router = APIRouter(prefix="/firmware", tags=["firmware"])


class FirmwareDownloadRequest(BaseModel):
    """Request body for starting a firmware download."""

    model: str
    csc: str = "XEU"
    url: Optional[str] = None  # Custom URL if auto-download fails


class FirmwareJobResponse(BaseModel):
    """Response for firmware job status."""

    job_id: str
    model: str
    csc: str
    ap_version: Optional[str]
    status: Literal[
        'pending', 'downloading', 'verifying', 'done', 'failed', 'cancelled', 'needs_url'
    ]
    progress_pct: float
    downloaded_bytes: int
    total_bytes: Optional[int]
    dest_path: Optional[str]
    error: Optional[str]
    md5_hash: Optional[str]
    sha256_hash: Optional[str]
    requires_url: bool

    class Config:
        from_attributes = True


class FirmwareEntryCreate(BaseModel):
    """Request to create a new firmware entry."""

    source: str = "manual"  # "manual", "samfw", "auto"
    device_model: str
    sales_code: str
    ap_version: Optional[str] = None
    csc_version: Optional[str] = None
    package_variant: Optional[str] = None
    country: Optional[str] = None
    language: Optional[str] = None
    filename: Optional[str] = None
    size_bytes: int = 0
    local_path: Optional[str] = None
    notes: Optional[str] = None


class FirmwareEntryUpdate(BaseModel):
    """Request to update a firmware entry."""

    ap_version: Optional[str] = None
    csc_version: Optional[str] = None
    package_variant: Optional[str] = None
    country: Optional[str] = None
    language: Optional[str] = None
    size_bytes: Optional[int] = None
    local_path: Optional[str] = None
    notes: Optional[str] = None


class FirmwareEntryResponse(BaseModel):
    """Response with firmware entry data."""

    id: int
    source: str
    device_model: str
    sales_code: str
    ap_version: Optional[str] = None
    csc_version: Optional[str] = None
    package_variant: Optional[str] = None
    country: Optional[str] = None
    language: Optional[str] = None
    filename: Optional[str] = None
    size_bytes: int
    local_path: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


@router.get("/sources")
async def get_firmware_sources(
    _user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Get list of available firmware download sources (primary + fallbacks).

    Returns:
    - sources: List of primary sources
    - fallback_sources_count: Number of user-configured fallbacks
    - description: How sources are tried
    """
    primary_sources = [
        {"name": s["name"], "description": s.get("description", "")}
        for s in settings.FIRMWARE_SOURCES
        if s.get("enabled", True)
    ]

    fallback_count = len(settings.FIRMWARE_FALLBACK_SOURCES)

    return {
        "sources": primary_sources,
        "fallback_sources_count": fallback_count,
        "description": f"Tries primary sources, then {fallback_count} user-configured fallback(s), then custom URL if provided",
        "how_to_add_fallback": "Set FIRMWARE_FALLBACK_SOURCES environment variable with semicolon-separated URLs"
    }


@router.post("/upload")
def upload_firmware_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> FirmwareEntryResponse:
    """
    Upload a firmware file manually.

    Supports: .zip, .tar, .tar.md5

    The system automatically:
    1. Parses the filename to extract model, AP version, CSC
    2. Saves the file to FIRMWARE_PACKAGES_DIR
    3. Creates/updates FirmwareEntry in database
    4. Returns detected metadata

    Example filenames:
    - SAMFW.COM_SM-G996B_EGY_G996BXXSJHZC2_fac.zip
    - AP_S721BXXS3AYB8_S721BXXS3AYB8_MQB93088282.tar.md5
    - AP_S921BXXU6GUB1_S921BOXM6GUB1_MQB93088282.tar
    """
    lower = (file.filename or "").lower()
    if not any(lower.endswith(e) for e in (".zip", ".tar.md5", ".tar")):
        raise HTTPException(400, "Unsupported format. Use .zip, .tar, or .tar.md5")

    # Read file data
    data = file.file.read()
    if not data:
        raise HTTPException(400, "Empty file")

    # Save to disk
    safe_name = Path(file.filename).name
    firmware_dir = Path(settings.FIRMWARE_PACKAGES_DIR)
    firmware_dir.mkdir(parents=True, exist_ok=True)
    dest_path = firmware_dir / safe_name
    dest_path.write_bytes(data)

    # Auto-detect metadata from filename
    meta = resolve_firmware_meta(safe_name) or {}

    # Upsert FirmwareEntry by filename
    existing = db.query(FirmwareEntry).filter(FirmwareEntry.filename == safe_name).first()

    if existing:
        existing.size_bytes = len(data)
        existing.local_path = str(dest_path)
        db.commit()
        db.refresh(existing)
        return FirmwareEntryResponse.from_orm(existing)

    # Create new entry
    entry = FirmwareEntry(
        source=meta.get("source", "manual"),
        device_model=meta.get("device_model"),
        sales_code=meta.get("sales_code"),
        ap_version=meta.get("ap_version"),
        csc_version=meta.get("csc_version"),
        package_variant=meta.get("package_variant"),
        filename=safe_name,
        size_bytes=len(data),
        local_path=str(dest_path),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)

    return FirmwareEntryResponse.from_orm(entry)


@router.post("/download")
async def start_download(
    req: FirmwareDownloadRequest, _user: User = Depends(get_current_user)
) -> FirmwareJobResponse:
    """
    Start a firmware download job.

    The download runs in the background. Poll GET /api/firmware/jobs/{job_id}
    to track progress.

    Query params:
    - model: Samsung model (e.g. "SM-S921B", "SM-A556B")
    - csc: Region code (default "XEU"). Examples: XEU, BTU, KSA, UAE, EGY, XSP
    - url: Optional direct download URL (for fallback if Samsung CDN is blocked)

    Returns immediately with job_id. Job state is pending/downloading/etc.
    """
    job = await start_firmware_download(req.model, req.csc, req.url)
    return FirmwareJobResponse(**job.__dict__)


@router.get("/jobs")
async def list_firmware_jobs(
    limit: int = 50, _user: User = Depends(get_current_user)
) -> List[FirmwareJobResponse]:
    """
    List all firmware download jobs (active + recent), most recent first.

    Query params:
    - limit: Max jobs to return (default 50)
    """
    jobs = await list_jobs(limit=limit)
    return [FirmwareJobResponse(**j.__dict__) for j in jobs]


@router.get("/jobs/{job_id}")
async def get_firmware_job(
    job_id: str, _user: User = Depends(get_current_user)
) -> FirmwareJobResponse:
    """
    Get a firmware download job's current status and progress.

    Returns:
    - status: one of pending, downloading, verifying, done, failed, cancelled, needs_url
    - progress_pct: 0-100
    - downloaded_bytes: bytes downloaded so far
    - total_bytes: total file size (if known)
    - error: error message if status == failed
    - md5_hash, sha256_hash: checksums if download completed
    """
    job = await get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id} not found")

    return FirmwareJobResponse(**job.__dict__)


@router.delete("/jobs/{job_id}")
async def cancel_firmware_job(
    job_id: str, _user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Cancel an in-progress firmware download.

    Cancels the download, removes partial file, and marks job as cancelled.
    """
    cancelled = await cancel_job(job_id)
    if not cancelled:
        raise HTTPException(
            400,
            f"Job {job_id} cannot be cancelled (already done or not found)"
        )
    return {"success": True, "job_id": job_id}


@router.get("/packages")
async def list_available_packages(
    _user: User = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """
    List locally available firmware packages (scanner results).

    This scans FIRMWARE_PACKAGES_DIR for:
    - SAMFW.COM_*.zip files (named by Samsung naming convention)
    - Directories matching AP_CSC_SALES pattern

    Returns the same format as GET /api/meta/firmware-packages.
    """
    firmware_dir = Path(settings.FIRMWARE_PACKAGES_DIR)
    return iter_firmware_packages(firmware_dir)


# ─── Firmware Entry CRUD ──────────────────────────────────────────────────────


@router.get("/entries")
def list_firmware_entries(
    model: Optional[str] = None,
    csc: Optional[str] = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> List[FirmwareEntryResponse]:
    """
    List firmware entries from database with optional filtering.

    Query params:
    - model: Filter by device_model (e.g. "SM-A556B")
    - csc: Filter by sales_code (e.g. "XEU")

    Returns all matching entries sorted by created_at descending.
    """
    try:
        query = db.query(FirmwareEntry)

        if model:
            query = query.filter(FirmwareEntry.device_model == model)
        if csc:
            query = query.filter(FirmwareEntry.sales_code == csc)

        entries = query.order_by(FirmwareEntry.created_at.desc()).all()
        return [FirmwareEntryResponse.from_orm(e) for e in entries]
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"list_firmware_entries error: {type(e).__name__}: {str(e)}", exc_info=True)
        raise HTTPException(500, f"Failed to list firmware entries: {str(e)}")


@router.post("/entries")
def create_firmware_entry(
    req: FirmwareEntryCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> FirmwareEntryResponse:
    """
    Create a new firmware entry manually.

    Used when Samsung FOTA API returns "needs_url" or for manual catalog entries.

    Request body:
    {
      "source": "manual",
      "device_model": "SM-A556B",
      "sales_code": "XEU",
      "ap_version": "A556BXXU3BXJ1",
      "csc_version": "A556BOXM3BXJ1",
      "notes": "from SamFW.com"
    }
    """
    entry = FirmwareEntry(
        source=req.source,
        device_model=req.device_model,
        sales_code=req.sales_code,
        ap_version=req.ap_version,
        csc_version=req.csc_version,
        package_variant=req.package_variant,
        country=req.country,
        language=req.language,
        filename=req.filename,
        size_bytes=req.size_bytes,
        local_path=req.local_path,
        notes=req.notes,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return FirmwareEntryResponse.from_orm(entry)


@router.put("/entries/{entry_id}")
def update_firmware_entry(
    entry_id: int,
    req: FirmwareEntryUpdate,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> FirmwareEntryResponse:
    """
    Update a firmware entry.

    Path params:
    - entry_id: ID of the entry to update

    Request body contains only fields to update (others left unchanged).
    """
    entry = db.query(FirmwareEntry).filter(FirmwareEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(404, f"Firmware entry {entry_id} not found")

    update_data = req.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(entry, key, value)

    db.commit()
    db.refresh(entry)
    return FirmwareEntryResponse.from_orm(entry)


@router.delete("/entries/{entry_id}")
def delete_firmware_entry(
    entry_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Delete a firmware entry.

    Path params:
    - entry_id: ID of the entry to delete

    Note: Does NOT delete the actual firmware file (local_path).
    """
    entry = db.query(FirmwareEntry).filter(FirmwareEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(404, f"Firmware entry {entry_id} not found")

    db.delete(entry)
    db.commit()
    return {"success": True, "entry_id": entry_id}


@router.post("/sync")
def sync_firmware_entries(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Scan firmware directory and import new packages to database.

    Scans FIRMWARE_PACKAGES_DIR for packages, checks if they already exist
    in the database (by filename or device_model + sales_code + ap_version),
    and creates new entries for any newly found packages.

    Returns count of newly imported entries.
    """
    firmware_dir = Path(settings.FIRMWARE_PACKAGES_DIR)
    packages = iter_firmware_packages(firmware_dir)

    imported = 0
    for pkg in packages:
        # Check if entry already exists by filename or by model/csc/ap combo
        existing = None
        if pkg.get("filename"):
            existing = db.query(FirmwareEntry).filter(
                FirmwareEntry.filename == pkg["filename"]
            ).first()

        if not existing:
            # Try to match by model + csc + ap_version
            existing = db.query(FirmwareEntry).filter(
                FirmwareEntry.device_model == pkg.get("device_model"),
                FirmwareEntry.sales_code == pkg.get("sales_code"),
                FirmwareEntry.ap_version == pkg.get("ap_version"),
            ).first()

        if not existing:
            # Create new entry
            entry = FirmwareEntry(
                source="auto",
                device_model=pkg.get("device_model"),
                sales_code=pkg.get("sales_code"),
                ap_version=pkg.get("ap_version"),
                csc_version=pkg.get("csc_version"),
                filename=pkg.get("filename"),
                size_bytes=pkg.get("size_bytes", 0),
            )
            db.add(entry)
            imported += 1

    db.commit()
    return {"success": True, "imported": imported}

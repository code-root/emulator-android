"""
Firmware download management endpoints.

Routes:
-------
POST   /api/firmware/download          Start a firmware download job
GET    /api/firmware/jobs              List all active/recent jobs
GET    /api/firmware/jobs/{job_id}     Get job status + progress
DELETE /api/firmware/jobs/{job_id}     Cancel a download job
GET    /api/firmware/packages          List locally available firmware packages
"""

from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import get_current_user
from core.firmware.downloader import (
    DownloadJob,
    cancel_job,
    get_job,
    list_jobs,
    start_firmware_download,
)
from core.firmware.scan import iter_firmware_packages
from config import settings
from db.models import User
from pathlib import Path

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

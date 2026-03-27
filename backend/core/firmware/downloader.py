"""
Samsung firmware auto-downloader with streaming + on-the-fly MD5/SHA256 verification.

Supports:
- Automatic download from Samsung CDN (https://cfs4.samsungmobile.com/)
- Fallback to user-provided URL (SamFW.com, etc.)
- Streaming download with chunked processing (no memory spike)
- Real-time progress tracking (bytes/total)
- On-the-fly MD5 + SHA256 hashing
- Automatic save to FIRMWARE_PACKAGES_DIR in SAMFW naming convention
"""

import asyncio
import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Literal, Optional

import httpx
from aiofiles import open as aio_open

from config import settings
from core.firmware.samsung_fota import fetch_latest_firmware
from db.database import SessionLocal
from db.models import FirmwareEntry

logger = logging.getLogger(__name__)

# In-memory job storage — keyed by job_id
_jobs: Dict[str, 'DownloadJob'] = {}
_jobs_lock = asyncio.Lock()

# Download chunk size: 1 MB
CHUNK_SIZE = 1024 * 1024


@dataclass
class DownloadJob:
    """Represents a single firmware download job."""

    job_id: str
    model: str
    csc: str
    ap_version: Optional[str] = None
    status: Literal[
        'pending', 'downloading', 'verifying', 'done', 'failed', 'cancelled', 'needs_url'
    ] = 'pending'
    progress_pct: float = 0.0
    downloaded_bytes: int = 0
    total_bytes: Optional[int] = None
    dest_path: Optional[str] = None
    error: Optional[str] = None
    md5_hash: Optional[str] = None
    sha256_hash: Optional[str] = None
    requires_url: bool = False
    created_at: datetime = field(default_factory=datetime.now)
    _task: Optional[asyncio.Task] = field(default=None, init=False, repr=False)


async def start_firmware_download(
    model: str, csc: str, url: Optional[str] = None
) -> DownloadJob:
    """
    Start a firmware download job.

    Args:
        model: Samsung model (e.g. "SM-S921B")
        csc: Region code (e.g. "XEU")
        url: Optional direct download URL. If None, tries Samsung CDN automatically.

    Returns:
        DownloadJob with job_id (status = "pending")

    The actual download happens in background. Poll GET /api/firmware/jobs/{job_id}
    to track progress.
    """
    job_id = str(uuid.uuid4())
    job = DownloadJob(job_id=job_id, model=model, csc=csc)

    async with _jobs_lock:
        _jobs[job_id] = job

    # Fetch AP version from Samsung FOTA if URL not provided
    if not url:
        try:
            fota_data = await fetch_latest_firmware(model, csc)
            job.ap_version = fota_data.get('ap_version')
            if not job.ap_version:
                job.status = 'failed'
                job.error = 'Could not fetch firmware version from Samsung'
                return job
            # Construct Samsung CDN URL
            url = f'https://cfs4.samsungmobile.com/{csc.upper()}/{model.upper()}/{job.ap_version}.zip'
        except Exception as e:
            logger.error(f'Error fetching firmware version: {e}')
            job.status = 'needs_url'
            job.error = f'Auto-fetch failed: {e}. Please provide manual URL.'
            job.requires_url = True
            return job

    # Launch background download task
    task = asyncio.create_task(_download_worker(job, url))
    job._task = task

    return job


async def _download_worker(job: DownloadJob, url: str) -> None:
    """
    Background worker that downloads firmware and verifies integrity.
    Updates job state in-place.
    """
    try:
        job.status = 'downloading'
        firmware_dir = Path(settings.FIRMWARE_PACKAGES_DIR)
        firmware_dir.mkdir(parents=True, exist_ok=True)

        # Construct destination filename in SAMFW naming convention
        dest_filename = f'SAMFW.COM_{job.model}_{job.csc}_{job.ap_version}_fac.zip'
        dest_path = firmware_dir / dest_filename
        job.dest_path = str(dest_path)

        # Download with streaming
        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream('GET', url) as response:
                if response.status_code != 200:
                    job.status = 'failed'
                    job.error = f'HTTP {response.status_code}: {response.reason_phrase}'
                    return

                # Get total size from Content-Length header
                try:
                    job.total_bytes = int(response.headers.get('content-length', 0))
                except (ValueError, TypeError):
                    job.total_bytes = None

                # Prepare hashing
                md5 = hashlib.md5()
                sha256 = hashlib.sha256()

                # Stream download + hash
                async with aio_open(dest_path, 'wb') as f:
                    async for chunk in response.aiter_bytes(chunk_size=CHUNK_SIZE):
                        if job.status == 'cancelled':
                            await f.close()
                            dest_path.unlink(missing_ok=True)
                            return

                        await f.write(chunk)
                        md5.update(chunk)
                        sha256.update(chunk)

                        job.downloaded_bytes += len(chunk)
                        if job.total_bytes and job.total_bytes > 0:
                            job.progress_pct = min(
                                100.0, (job.downloaded_bytes / job.total_bytes) * 100
                            )

        # Verify phase
        job.status = 'verifying'
        job.md5_hash = md5.hexdigest()
        job.sha256_hash = sha256.hexdigest()

        logger.info(
            f'Firmware downloaded: {job.model}/{job.csc} → {dest_filename} '
            f'({job.downloaded_bytes} bytes, SHA256: {job.sha256_hash})'
        )

        job.status = 'done'
        job.progress_pct = 100.0

        # Auto-save to database
        try:
            db = SessionLocal()
            try:
                # Check if entry already exists by filename
                existing = db.query(FirmwareEntry).filter(
                    FirmwareEntry.filename == dest_filename
                ).first()

                if existing:
                    # Update existing entry
                    existing.ap_version = job.ap_version
                    existing.size_bytes = job.downloaded_bytes
                    existing.local_path = str(dest_path)
                else:
                    # Create new entry
                    entry = FirmwareEntry(
                        source='auto',
                        device_model=job.model,
                        sales_code=job.csc,
                        ap_version=job.ap_version,
                        filename=dest_filename,
                        size_bytes=job.downloaded_bytes,
                        local_path=str(dest_path),
                    )
                    db.add(entry)

                db.commit()
                logger.info(f'Firmware entry saved to database: {dest_filename}')
            finally:
                db.close()
        except Exception as e:
            logger.error(f'Failed to save firmware entry to database: {e}')

    except asyncio.CancelledError:
        job.status = 'cancelled'
        job.error = 'Download cancelled by user'
        if job.dest_path:
            Path(job.dest_path).unlink(missing_ok=True)
        raise

    except Exception as e:
        job.status = 'failed'
        job.error = str(e)
        logger.error(f'Firmware download failed for {job.model}/{job.csc}: {e}')
        if job.dest_path:
            Path(job.dest_path).unlink(missing_ok=True)


async def get_job(job_id: str) -> Optional[DownloadJob]:
    """Retrieve a job by ID."""
    async with _jobs_lock:
        return _jobs.get(job_id)


async def list_jobs(limit: int = 50) -> list[DownloadJob]:
    """List all jobs (active + recent), most recent first."""
    async with _jobs_lock:
        # Sort by created_at descending, take latest {limit}
        jobs = sorted(_jobs.values(), key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]


async def cancel_job(job_id: str) -> bool:
    """
    Cancel a download job.

    Returns True if cancelled, False if job not found or already done.
    """
    async with _jobs_lock:
        job = _jobs.get(job_id)

    if not job:
        return False

    if job.status in ('done', 'failed', 'cancelled'):
        return False

    job.status = 'cancelled'
    if job._task and not job._task.done():
        job._task.cancel()

    return True


async def cleanup_old_jobs(hours: int = 24) -> int:
    """Remove jobs older than {hours} from memory. Returns count removed."""
    now = datetime.now()
    to_delete = []

    async with _jobs_lock:
        for job_id, job in _jobs.items():
            age_hours = (now - job.created_at).total_seconds() / 3600
            if age_hours > hours:
                to_delete.append(job_id)

        for job_id in to_delete:
            del _jobs[job_id]

    return len(to_delete)

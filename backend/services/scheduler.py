import asyncio
import logging
import os
from typing import Dict, Any, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from db.database import AsyncSessionLocal
from db.models import Device, DeviceStatus
from services.ws_manager import ws_manager

logger = logging.getLogger(__name__)


class DeviceScheduler:
    """APScheduler-based device health check and auto-start scheduler."""

    def __init__(self):
        self._scheduler = AsyncIOScheduler()
        self._health_check_jobs: Dict[int, str] = {}  # device_id -> job_id
        self._auto_start_jobs: Dict[int, str] = {}    # device_id -> job_id

    def start(self) -> None:
        """Start the scheduler."""
        if not self._scheduler.running:
            self._scheduler.start()
            logger.info("Device scheduler started")

    def stop(self) -> None:
        """Stop the scheduler."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Device scheduler stopped")

    def add_health_check(self, device_id: int, interval: int = 15) -> str:
        """Add a periodic health check job for a device."""
        job_id = f"health_check_{device_id}"

        # Remove existing job if any
        self.remove_health_check(device_id)

        job = self._scheduler.add_job(
            self._health_check_job,
            trigger=IntervalTrigger(seconds=interval),
            id=job_id,
            args=[device_id],
            replace_existing=True,
            max_instances=1,
        )
        self._health_check_jobs[device_id] = job_id
        logger.debug(f"Added health check for device {device_id} every {interval}s")
        return job_id

    def remove_health_check(self, device_id: int) -> None:
        """Remove health check job for a device."""
        job_id = self._health_check_jobs.pop(device_id, None)
        if job_id:
            try:
                self._scheduler.remove_job(job_id)
            except Exception:
                pass

    def add_auto_start(self, device_id: int, cron_expression: str) -> str:
        """Schedule auto-start for a device with a cron expression."""
        # cron_expression format: "minute hour day month day_of_week"
        # e.g., "0 9 * * 1-5" = every weekday at 9am
        job_id = f"auto_start_{device_id}"
        self.remove_auto_start(device_id)

        parts = cron_expression.split()
        if len(parts) != 5:
            raise ValueError(f"Invalid cron expression: {cron_expression}")

        minute, hour, day, month, day_of_week = parts
        trigger = CronTrigger(
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
        )
        self._scheduler.add_job(
            self._auto_start_job,
            trigger=trigger,
            id=job_id,
            args=[device_id],
            replace_existing=True,
        )
        self._auto_start_jobs[device_id] = job_id
        logger.info(f"Added auto-start for device {device_id}: {cron_expression}")
        return job_id

    def remove_auto_start(self, device_id: int) -> None:
        """Remove auto-start job for a device."""
        job_id = self._auto_start_jobs.pop(device_id, None)
        if job_id:
            try:
                self._scheduler.remove_job(job_id)
            except Exception:
                pass

    def remove_jobs(self, device_id: int) -> None:
        """Remove all scheduler jobs for a device."""
        self.remove_health_check(device_id)
        self.remove_auto_start(device_id)
        logger.info(f"Removed all jobs for device {device_id}")

    async def _health_check_job(self, device_id: int) -> None:
        """Check if device process is alive and update DB status."""
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(Device).where(Device.id == device_id))
                device = result.scalar_one_or_none()
                if not device:
                    self.remove_jobs(device_id)
                    return

                if device.status not in (DeviceStatus.running, DeviceStatus.booting):
                    return

                # Check if PID is still alive
                is_alive = False
                if device.pid:
                    try:
                        os.kill(device.pid, 0)
                        is_alive = True
                    except ProcessLookupError:
                        is_alive = False
                    except PermissionError:
                        is_alive = True  # Process exists, just no permission

                if not is_alive and device.status == DeviceStatus.running:
                    logger.warning(f"Device {device_id} process {device.pid} is dead — marking as stopped")
                    device.status = DeviceStatus.stopped
                    device.pid = None
                    await db.commit()
                    await ws_manager.broadcast(
                        device_id,
                        {
                            "type": "status",
                            "status": "stopped",
                            "device_id": device_id,
                            "reason": "process_died",
                        }
                    )
                else:
                    # Broadcast heartbeat
                    await ws_manager.broadcast(
                        device_id,
                        {
                            "type": "heartbeat",
                            "status": device.status.value,
                            "device_id": device_id,
                        }
                    )
        except Exception as e:
            logger.error(f"Health check error for device {device_id}: {e}")

    async def _auto_start_job(self, device_id: int) -> None:
        """Auto-start a device according to schedule."""
        try:
            from core.emulator.manager import EmulatorManager
            emulator_manager = EmulatorManager()

            async with AsyncSessionLocal() as db:
                result = await db.execute(select(Device).where(Device.id == device_id))
                device = result.scalar_one_or_none()
                if not device:
                    return
                if device.status == DeviceStatus.running:
                    logger.info(f"Auto-start: device {device_id} already running")
                    return

                logger.info(f"Auto-start: starting device {device_id}")
                device.status = DeviceStatus.booting
                await db.commit()
                await db.refresh(device)
                db.expunge(device)

            success, info = await emulator_manager.start(device)
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(Device).where(Device.id == device_id))
                device = result.scalar_one_or_none()
                if device:
                    if success:
                        device.status = DeviceStatus.running
                        device.pid = info.get("pid")
                        device.adb_serial = info.get("adb_serial")
                        device.adb_port = info.get("adb_port")
                    else:
                        device.status = DeviceStatus.error
                    await db.commit()

            await ws_manager.broadcast(
                device_id,
                {
                    "type": "status",
                    "status": "running" if success else "error",
                    "device_id": device_id,
                }
            )
        except Exception as e:
            logger.error(f"Auto-start job error for device {device_id}: {e}")

    def get_jobs_info(self) -> Dict[str, Any]:
        """Return information about all scheduled jobs."""
        jobs = []
        for job in self._scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run": str(job.next_run_time) if job.next_run_time else None,
            })
        return {
            "running": self._scheduler.running,
            "jobs": jobs,
            "total": len(jobs),
        }


# Global singleton
device_scheduler = DeviceScheduler()

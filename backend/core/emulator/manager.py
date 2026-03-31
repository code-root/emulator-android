import logging
from typing import Tuple, Dict, Any, Optional

from core.emulator.avd import AVDBackend
from core.emulator.physical import PhysicalDeviceBackend
from config import settings

logger = logging.getLogger(__name__)


def _device_kind(device) -> str:
    return (getattr(device, "emulator_kind", None) or "avd").strip().lower()


class EmulatorManager:
    """High-level emulator lifecycle manager."""

    def __init__(self):
        self.avd_backend = AVDBackend()
        self.physical_backend = PhysicalDeviceBackend()
        # Track running processes: device_id -> asyncio.Process
        self._processes: Dict[int, Any] = {}

    async def start(
        self,
        device,
        samsung_props: Optional[Dict[str, Any]] = None,
        system_img: Optional[str] = None,
        vendor_img: Optional[str] = None,
        wipe_data: bool = False,
    ) -> Tuple[bool, Dict[str, Any]]:
        """Start the emulator for the given device record."""
        kind = _device_kind(device)
        if kind == "physical":
            success, info = await self.physical_backend.attach(device)
        elif settings.EMULATOR_BACKEND == "avd":
            success, info = await self.avd_backend.start_avd(
                device,
                samsung_props=samsung_props,
                system_img=system_img,
                vendor_img=vendor_img,
                wipe_data=wipe_data,
            )
        else:
            logger.error("Unknown EMULATOR_BACKEND: %s", settings.EMULATOR_BACKEND)
            return False, {}

        if success and info.get("process"):
            self._processes[device.id] = info.pop("process")

        if success and info.get("adb_serial"):
            # Wait for boot in background — this function should not block too long
            serial = info["adb_serial"]
            # Wait for ADB to connect
            try:
                await self._wait_for_adb(serial, timeout=60)
                booted = await self.avd_backend.wait_for_boot(serial, timeout=180)
                if not booted:
                    logger.warning(f"Device {device.id} may not be fully booted")
            except Exception as e:
                logger.warning(f"Boot wait error: {e}")

        return success, info

    async def _wait_for_adb(self, serial: str, timeout: int = 60) -> bool:
        """Wait until the emulator serial is visible to ADB (local or TCP)."""
        from core.tools.adb import ADBTool
        adb = ADBTool()
        if ":" in serial:
            try:
                await adb.connect(serial)
            except Exception as e:
                logger.debug(f"ADB optional connect {serial}: {e}")
        ok = await adb.wait_for_device(serial, timeout=timeout)
        if ok:
            logger.info(f"ADB ready for {serial}")
        return ok

    async def stop(self, device) -> bool:
        """Stop the emulator for the given device."""
        # لا نُطفئ هاتفاً حقيقياً — فقط إيقاف محاكي AVD
        if _device_kind(device) != "physical" and device.adb_serial:
            try:
                from core.tools.adb import ADBTool
                adb = ADBTool()
                await adb.shell(device.adb_serial, "reboot -p")
            except Exception:
                pass

        # Kill process
        proc = self._processes.pop(device.id, None)
        if proc:
            try:
                proc.terminate()
                import asyncio
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    proc.kill()
            except Exception as e:
                logger.warning(f"Error terminating process: {e}")

        return await self.avd_backend.stop_avd(device)

    async def get_status(self, device) -> str:
        """Get emulator status."""
        if _device_kind(device) == "physical" and device.adb_serial:
            from core.tools.adb import ADBTool
            adb = ADBTool()
            try:
                out = await adb.shell(device.adb_serial, "getprop sys.boot_completed")
                if out.strip() == "1":
                    return "running"
            except Exception:
                pass
            return "stopped"
        proc = self._processes.get(device.id)
        if proc is not None:
            if proc.returncode is None:
                return "running"
            else:
                return "stopped"
        return await self.avd_backend.get_status(device)

    def is_process_alive(self, device_id: int) -> bool:
        proc = self._processes.get(device_id)
        if proc is None:
            return False
        return proc.returncode is None

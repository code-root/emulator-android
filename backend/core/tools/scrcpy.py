import asyncio
import logging
import shutil
from typing import Dict, Optional, Any

from config import settings

logger = logging.getLogger(__name__)


class ScrcpyManager:
    """Manage scrcpy sessions for browser-accessible device screens."""

    def __init__(self):
        self._sessions: Dict[int, asyncio.subprocess.Process] = {}
        self._scrcpy_bin = shutil.which("scrcpy") or "scrcpy"

    async def start_session(
        self,
        device_id: int,
        serial: str,
        port: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Start a scrcpy session for a device."""
        if device_id in self._sessions:
            proc = self._sessions[device_id]
            if proc.returncode is None:
                return {"active": True, "device_id": device_id, "port": port}
            del self._sessions[device_id]

        if port is None:
            port = settings.SCRCPY_PORT_START + device_id

        cmd = [
            self._scrcpy_bin,
            "--serial", serial,
            "--no-audio",
            "--turn-screen-off",
            "--stay-awake",
            "--max-size", "1080",
            "--bit-rate", "2M",
        ]

        logger.info(f"Starting scrcpy session for device {device_id}: {' '.join(cmd)}")
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._sessions[device_id] = proc
            await asyncio.sleep(1)

            if proc.returncode is not None:
                stderr = await proc.stderr.read()
                logger.error(f"Scrcpy exited immediately: {stderr.decode()[:300]}")
                return {"active": False, "error": "scrcpy exited immediately"}

            return {
                "active": True,
                "device_id": device_id,
                "port": port,
                "pid": proc.pid,
            }
        except FileNotFoundError:
            logger.warning("scrcpy binary not found — screen streaming unavailable")
            return {"active": False, "error": "scrcpy not installed"}
        except Exception as e:
            logger.error(f"Failed to start scrcpy: {e}")
            return {"active": False, "error": str(e)}

    async def stop_session(self, device_id: int) -> bool:
        """Stop a scrcpy session."""
        proc = self._sessions.pop(device_id, None)
        if proc is None:
            return True
        try:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
            logger.info(f"Stopped scrcpy session for device {device_id}")
            return True
        except Exception as e:
            logger.error(f"Error stopping scrcpy: {e}")
            return False

    def get_session_url(self, device_id: int) -> Optional[str]:
        """Return the WebSocket URL for the scrcpy session."""
        proc = self._sessions.get(device_id)
        if proc and proc.returncode is None:
            port = settings.SCRCPY_PORT_START + device_id
            return f"ws://localhost:{port}"
        return None

    def is_session_active(self, device_id: int) -> bool:
        proc = self._sessions.get(device_id)
        return proc is not None and proc.returncode is None

    async def stop_all(self):
        """Stop all active scrcpy sessions."""
        device_ids = list(self._sessions.keys())
        for device_id in device_ids:
            await self.stop_session(device_id)

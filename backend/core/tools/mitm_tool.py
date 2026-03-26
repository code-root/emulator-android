import asyncio
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Any

from config import settings
from core.tools.adb import ADBTool

logger = logging.getLogger(__name__)


class MitmManager:
    """mitmproxy process manager — one mitmproxy instance per device."""

    MITM_CERT_DIR = "/tmp/mitmproxy_certs"

    def __init__(self):
        self._processes: Dict[int, asyncio.subprocess.Process] = {}
        self._log_files: Dict[int, str] = {}
        self._log_handles: Dict[int, Any] = {}
        self._mitmdump_bin = shutil.which("mitmdump") or "mitmdump"
        self._mitmproxy_bin = shutil.which("mitmproxy") or "mitmproxy"

    async def start(
        self,
        device_id: int,
        port: int,
        upstream_proxy: Optional[str] = None,
    ) -> int:
        """Start mitmproxy on the given port. Returns PID."""
        if device_id in self._processes:
            proc = self._processes[device_id]
            if proc.returncode is None:
                return proc.pid
            del self._processes[device_id]

        log_path = f"/tmp/mitm_device_{device_id}.log"
        self._log_files[device_id] = log_path
        Path(log_path).write_bytes(b"")

        cmd = [
            self._mitmdump_bin,
            "--listen-host", "0.0.0.0",
            "--listen-port", str(port),
            "--set", f"confdir={self.MITM_CERT_DIR}",
            "--set", "ssl_insecure=true",
        ]

        if upstream_proxy:
            cmd.extend(["--mode", f"upstream:{upstream_proxy}"])

        logger.info(f"Starting mitmproxy for device {device_id} on port {port}")
        try:
            Path(self.MITM_CERT_DIR).mkdir(parents=True, exist_ok=True)

            log_handle = open(log_path, "ab", buffering=0)
            self._log_handles[device_id] = log_handle

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=log_handle,
                stderr=asyncio.subprocess.STDOUT,
            )
            self._processes[device_id] = proc
            await asyncio.sleep(1)

            if proc.returncode is not None:
                err_tail = Path(log_path).read_text(errors="replace")[-500:]
                raise RuntimeError(f"mitmproxy exited: {err_tail}")

            logger.info(f"mitmproxy started for device {device_id}: PID={proc.pid}, port={port}")
            return proc.pid
        except FileNotFoundError:
            logger.warning("mitmdump not found — install mitmproxy: pip install mitmproxy")
            raise RuntimeError("mitmdump not installed")
        except Exception as e:
            logger.error(f"Failed to start mitmproxy: {e}")
            raise

    async def stop(self, device_id: int) -> bool:
        """Stop mitmproxy for a device."""
        proc = self._processes.pop(device_id, None)
        log_handle = self._log_handles.pop(device_id, None)
        if log_handle:
            try:
                log_handle.flush()
                log_handle.close()
            except Exception:
                pass
        if not proc:
            return True
        try:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
            logger.info(f"Stopped mitmproxy for device {device_id}")
            return True
        except Exception as e:
            logger.error(f"Error stopping mitmproxy: {e}")
            return False

    async def set_device_proxy(
        self,
        adb_tool: ADBTool,
        serial: str,
        host: str,
        port: int,
    ) -> None:
        """Configure Android device to use the proxy."""
        proxy_str = f"{host}:{port}"
        await adb_tool.shell(serial, f"settings put global http_proxy {proxy_str}")
        await adb_tool.shell(serial, f"settings put global global_http_proxy_host {host}")
        await adb_tool.shell(serial, f"settings put global global_http_proxy_port {port}")
        logger.info(f"Set proxy {proxy_str} on device {serial}")

    async def clear_device_proxy(self, adb_tool: ADBTool, serial: str) -> None:
        """Remove proxy settings from Android device."""
        await adb_tool.shell(serial, "settings put global http_proxy :0")
        await adb_tool.shell(serial, "settings delete global global_http_proxy_host")
        await adb_tool.shell(serial, "settings delete global global_http_proxy_port")
        logger.info(f"Cleared proxy on device {serial}")

    async def get_traffic_log(self, device_id: int, limit: int = 100) -> List[str]:
        """Read recent traffic from mitmproxy log file."""
        log_path = self._log_files.get(device_id)
        if not log_path or not Path(log_path).exists():
            return []
        try:
            with open(log_path, "r", errors="replace") as f:
                lines = f.readlines()
            return [line.strip() for line in lines[-limit:] if line.strip()]
        except Exception as e:
            logger.error(f"Error reading traffic log: {e}")
            return []

    async def install_cert(self, adb_tool: ADBTool, serial: str) -> bool:
        """Push mitmproxy CA certificate to the Android device."""
        cert_dir = Path(self.MITM_CERT_DIR)
        cert_path = cert_dir / "mitmproxy-ca-cert.pem"

        if not cert_path.exists():
            # Generate cert by running mitmproxy briefly
            logger.warning(f"mitmproxy cert not found at {cert_path}")
            return False

        try:
            # Calculate cert hash for Android
            import hashlib
            with open(cert_path, "rb") as f:
                cert_data = f.read()

            # Push cert to device
            remote_path = f"/sdcard/mitmproxy-ca-cert.crt"
            await adb_tool.push_file(serial, str(cert_path), remote_path)

            # Install cert (requires user interaction on non-rooted devices)
            await adb_tool.shell(
                serial,
                f"am start -n com.android.certinstaller/.CertInstallerMain -a android.intent.action.VIEW "
                f"-t application/x-x509-ca-cert -d file://{remote_path}"
            )
            logger.info(f"Cert push initiated for device {serial}")
            return True
        except Exception as e:
            logger.error(f"Failed to install mitmproxy cert: {e}")
            return False

    def is_running(self, device_id: int) -> bool:
        proc = self._processes.get(device_id)
        return proc is not None and proc.returncode is None

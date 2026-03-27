import asyncio
import base64
import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import settings
from core.tools.adb import ADBTool

logger = logging.getLogger(__name__)

# Path to the structured-capture addon script (same package)
_ADDON_PATH = str(Path(__file__).parent / "mitm_addon.py")


class MitmManager:
    """mitmproxy process manager — one mitmproxy instance per device."""

    MITM_CERT_DIR = "/tmp/mitmproxy_certs"

    def __init__(self):
        self._processes: Dict[int, asyncio.subprocess.Process] = {}
        self._log_files: Dict[int, str] = {}
        self._flow_stores: Dict[int, str] = {}   # device_id → JSONL flow file path
        self._log_handles: Dict[int, Any] = {}
        self._mitmdump_bin = shutil.which("mitmdump") or "mitmdump"
        self._mitmproxy_bin = shutil.which("mitmproxy") or "mitmproxy"

    def flow_store_path(self, device_id: int) -> str:
        """Return the path of the structured JSONL flow store for a device."""
        return f"/tmp/mitm_flows_{device_id}.jsonl"

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
        flow_path = self.flow_store_path(device_id)
        self._log_files[device_id] = log_path
        self._flow_stores[device_id] = flow_path
        Path(log_path).write_bytes(b"")
        # Keep flow store across restarts (append mode in addon) — only clear on explicit flush
        Path(flow_path).touch()

        cmd = [
            self._mitmdump_bin,
            "--listen-host", "0.0.0.0",
            "--listen-port", str(port),
            "--set", f"confdir={self.MITM_CERT_DIR}",
            "--set", "ssl_insecure=true",
            "-s", _ADDON_PATH,
            "--set", f"addon_store={flow_path}",
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

    # ------------------------------------------------------------------
    # Structured flow access (network inspector)
    # ------------------------------------------------------------------

    def _read_flows(self, device_id: int, limit: int = 200) -> List[Dict[str, Any]]:
        """Read the last ``limit`` structured flow records from the JSONL store."""
        path = self.flow_store_path(device_id)
        if not Path(path).exists():
            return []
        records: List[Dict[str, Any]] = []
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            for line in lines[-limit:]:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        except Exception as exc:
            logger.warning("flow store read error: %s", exc)
        return records

    def get_connections(self, device_id: int, limit: int = 200) -> List[Dict[str, Any]]:
        """Return a summary list of captured HTTP(S) connections."""
        flows = self._read_flows(device_id, limit)
        summaries = []
        for f in flows:
            summaries.append({
                "id":           f.get("id"),
                "timestamp":    f.get("timestamp"),
                "method":       f.get("method"),
                "url":          f.get("url"),
                "host":         f.get("host"),
                "path":         f.get("path"),
                "scheme":       f.get("scheme"),
                "status_code":  f.get("status_code"),
                "content_type": f.get("content_type"),
                "error":        f.get("error"),
            })
        return summaries

    def get_flow_detail(self, device_id: int, flow_id: str) -> Optional[Dict[str, Any]]:
        """Return the full flow record (including headers, cookies, body) by ID."""
        for f in self._read_flows(device_id, limit=5000):
            if f.get("id") == flow_id:
                return f
        return None

    def get_all_cookies(self, device_id: int) -> List[Dict[str, Any]]:
        """Aggregate all Set-Cookie entries across all captured flows."""
        flows = self._read_flows(device_id, limit=5000)
        seen: Dict[str, Dict[str, Any]] = {}
        for f in flows:
            for cookie in f.get("resp_cookies") or []:
                key = f"{cookie.get('domain', '')}::{cookie.get('name', '')}"
                # Keep the most recent value
                seen[key] = {
                    **cookie,
                    "url":       f.get("url", ""),
                    "host":      f.get("host", ""),
                    "timestamp": f.get("timestamp"),
                }
        return list(seen.values())

    def get_sessions(self, device_id: int) -> List[Dict[str, Any]]:
        """
        Group request cookies by host to surface 'sessions'.
        Returns one entry per (host, session_cookie_name) pair.
        """
        flows = self._read_flows(device_id, limit=5000)
        sessions: Dict[str, Dict[str, Any]] = {}
        session_keywords = {"session", "sess", "sid", "token", "auth", "jwt", "access_token"}
        for f in flows:
            host = f.get("host", "")
            for name, value in (f.get("req_cookies") or {}).items():
                if any(kw in name.lower() for kw in session_keywords):
                    key = f"{host}::{name}"
                    sessions[key] = {
                        "host":      host,
                        "url":       f.get("url", ""),
                        "name":      name,
                        "value":     value,
                        "timestamp": f.get("timestamp"),
                    }
        return list(sessions.values())

    def flush_flows(self, device_id: int) -> bool:
        """Clear the flow store for a device."""
        path = self.flow_store_path(device_id)
        try:
            Path(path).write_text("", encoding="utf-8")
            return True
        except Exception as exc:
            logger.warning("flush_flows error: %s", exc)
            return False

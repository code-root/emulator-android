import asyncio
import logging
import shutil
import tempfile
import os
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class FridaTool:
    """Frida dynamic instrumentation tool wrapper."""

    def __init__(self):
        self._frida_bin = shutil.which("frida") or "frida"
        self._frida_ps_bin = shutil.which("frida-ps") or "frida-ps"
        self._active_sessions: Dict[int, asyncio.subprocess.Process] = {}

    async def list_processes(self, serial: str) -> List[Dict[str, Any]]:
        """List processes on device via frida-ps."""
        try:
            proc = await asyncio.create_subprocess_exec(
                self._frida_ps_bin,
                "-D", serial,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            output = stdout.decode(errors="replace")
            processes = []
            for line in output.splitlines()[1:]:  # skip header
                parts = line.split(None, 1)
                if len(parts) >= 2:
                    try:
                        processes.append({"pid": int(parts[0]), "name": parts[1].strip()})
                    except ValueError:
                        pass
            return processes
        except FileNotFoundError:
            logger.warning("frida-ps not found — install frida-tools")
            return []
        except Exception as e:
            logger.error(f"frida-ps error: {e}")
            return []

    async def attach(
        self,
        device_id: int,
        serial: str,
        process_name: str,
        script_path: str,
    ) -> Dict[str, Any]:
        """Attach frida to a process with a script."""
        cmd = [
            self._frida_bin,
            "-D", serial,
            "-n", process_name,
            "-l", script_path,
            "--no-pause",
        ]
        logger.info(f"Frida attach: {' '.join(cmd)}")
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            # Give it a moment
            await asyncio.sleep(1)
            if proc.returncode is not None:
                stderr = await proc.stderr.read()
                return {"success": False, "error": stderr.decode()[:300]}
            self._active_sessions[device_id] = proc
            return {"success": True, "pid": proc.pid, "session_id": device_id}
        except FileNotFoundError:
            return {"success": False, "error": "frida not installed"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def detach(self, device_id: int) -> bool:
        """Detach frida session for device."""
        proc = self._active_sessions.pop(device_id, None)
        if not proc:
            return True
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=5)
            return True
        except Exception:
            proc.kill()
            return True

    async def inject_script(
        self,
        serial: str,
        pid: int,
        script_code: str,
    ) -> Dict[str, Any]:
        """Inject a frida script into a running process by PID."""
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".js",
            delete=False,
            prefix="frida_script_",
        ) as f:
            f.write(script_code)
            tmp_path = f.name

        try:
            cmd = [
                self._frida_bin,
                "-D", serial,
                "-p", str(pid),
                "-l", tmp_path,
                "--no-pause",
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            output = stdout.decode(errors="replace")
            err = stderr.decode(errors="replace")
            return {
                "success": proc.returncode == 0,
                "output": output,
                "error": err if proc.returncode != 0 else None,
            }
        except FileNotFoundError:
            return {"success": False, "error": "frida not installed"}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    async def get_session_output(self, session_id: int) -> str:
        """Get stdout from a running frida session."""
        proc = self._active_sessions.get(session_id)
        if not proc:
            return ""
        try:
            # Non-blocking read
            stdout_data = b""
            try:
                stdout_data = await asyncio.wait_for(proc.stdout.read(4096), timeout=0.1)
            except asyncio.TimeoutError:
                pass
            return stdout_data.decode(errors="replace")
        except Exception:
            return ""

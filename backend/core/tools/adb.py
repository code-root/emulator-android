import asyncio
import io
import logging
import shlex
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image

logger = logging.getLogger(__name__)

# One screenshot at a time per device: WS + HTTP share the same adb serial and used to
# race on a fixed /sdcard path (pull vs rm / truncated PNG / missing file).
_screenshot_locks: dict[str, asyncio.Lock] = {}


def _screenshot_lock(serial: str) -> asyncio.Lock:
    lock = _screenshot_locks.get(serial)
    if lock is None:
        lock = asyncio.Lock()
        _screenshot_locks[serial] = lock
    return lock


def _png_loads(data: bytes) -> bool:
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.load()
        return True
    except Exception:
        return False


def _decode_screencap_png(raw: bytes, *, from_exec_out: bool) -> bytes:
    """
    Parse PNG from screencap -p.

    exec-out: adb may inject \\r\\n into the stream — try CRLF fix + trim garbage.
    pull: binary file is usually clean — do NOT globally replace \\r\\n (can break zlib).
    """
    if not raw or len(raw) < 8:
        raise ValueError("empty screencap output")

    variants: list[bytes] = [raw]
    if from_exec_out:
        fixed = raw.replace(b"\r\n", b"\n")
        if fixed != raw:
            variants.append(fixed)

    for blob in variants:
        if _png_loads(blob):
            return blob
        idx = blob.find(b"\x89PNG")
        if idx >= 0:
            tail = blob[idx:]
            if _png_loads(tail):
                return tail

    raise ValueError("invalid PNG in screencap output")


class ADBTool:
    """Async ADB wrapper."""

    def __init__(self, adb_path: Optional[str] = None):
        if adb_path:
            self._adb = adb_path
        else:
            from config import settings
            from pathlib import Path as P
            sdk = P(settings.AVD_SDK_PATH)
            candidate = sdk / "platform-tools" / "adb"
            if candidate.exists():
                self._adb = str(candidate)
            else:
                self._adb = shutil.which("adb") or "adb"

    async def connect(self, serial_or_port: str) -> str:
        """Connect to a device via TCP/IP."""
        if ":" not in serial_or_port:
            serial_or_port = f"localhost:{serial_or_port}"
        result = await self._run(["connect", serial_or_port], check=False)
        return result

    async def disconnect(self, serial: str) -> str:
        result = await self._run(["disconnect", serial], check=False)
        return result

    async def install_apk(self, serial: str, apk_path: str, args: List[str] = None) -> str:
        if args is None:
            args = ["-r", "-t"]
        cmd = ["-s", serial, "install"] + args + [apk_path]
        return await self._run(cmd, timeout=120)

    async def install_multiple_apks(self, serial: str, apk_paths: List[str], args: List[str] = None) -> str:
        """Install split APK set (same package). apk_paths order: base first when possible."""
        if not apk_paths:
            raise ValueError("no APK paths")
        if args is None:
            args = ["-r", "-t"]
        cmd = ["-s", serial, "install-multiple"] + args + apk_paths
        return await self._run(cmd, timeout=600)

    async def uninstall_pkg(self, serial: str, package: str) -> str:
        return await self._run(["-s", serial, "uninstall", package], check=False)

    async def list_packages(self, serial: str) -> List[str]:
        output = await self._run(["-s", serial, "shell", "pm", "list", "packages"])
        packages = []
        for line in output.splitlines():
            line = line.strip()
            if line.startswith("package:"):
                packages.append(line[len("package:"):].strip())
        return sorted(packages)

    async def shell(self, serial: str, cmd: str) -> str:
        try:
            parts = shlex.split(cmd, posix=True)
        except ValueError:
            parts = cmd.split()
        return await self._run(["-s", serial, "shell"] + parts, check=False)

    async def tap(self, serial: str, x: int, y: int) -> str:
        return await self._run(["-s", serial, "shell", "input", "tap", str(x), str(y)], check=False)

    async def swipe(self, serial: str, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> str:
        return await self._run(
            ["-s", serial, "shell", "input", "swipe",
             str(x1), str(y1), str(x2), str(y2), str(duration_ms)],
            check=False,
        )

    async def key_event(self, serial: str, keycode: str) -> str:
        # Accept both numeric and string keycodes
        return await self._run(["-s", serial, "shell", "input", "keyevent", str(keycode)], check=False)

    async def input_text(self, serial: str, text: str) -> str:
        # Escape special characters
        safe_text = text.replace("'", "\\'").replace(" ", "%s")
        return await self._run(["-s", serial, "shell", "input", "text", safe_text], check=False)

    async def screenshot(self, serial: str) -> bytes:
        """Take screenshot and return PNG bytes (exec-out is faster; pull is the fallback)."""
        async with _screenshot_lock(serial):
            try:
                return await self._screenshot_exec_out(serial)
            except Exception as e:
                logger.debug(f"exec-out screencap failed for {serial}, using pull: {e}")
            return await self._screenshot_via_pull(serial)

    async def _screenshot_exec_out(self, serial: str) -> bytes:
        cmd = [self._adb, "-s", serial, "exec-out", "screencap", "-p"]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=45)
        if proc.returncode != 0:
            err = (stderr or b"").decode(errors="replace").strip()
            raise RuntimeError(err or "exec-out screencap failed")
        return _decode_screencap_png(stdout or b"", from_exec_out=True)

    async def _screenshot_via_pull(self, serial: str) -> bytes:
        rid = uuid.uuid4().hex[:16]
        remote = f"/data/local/tmp/.screencap_{rid}.png"
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            tmp = f.name

        try:
            await self._run(["-s", serial, "shell", "screencap", "-p", remote])
            await self._run(["-s", serial, "pull", remote, tmp])
            with open(tmp, "rb") as f:
                raw = f.read()
            return _decode_screencap_png(raw, from_exec_out=False)
        finally:
            import os
            try:
                os.unlink(tmp)
            except Exception:
                pass
            try:
                await self._run(["-s", serial, "shell", "rm", "-f", remote], check=False)
            except Exception:
                pass

    async def pull_file(self, serial: str, remote_path: str, local_path: str) -> str:
        return await self._run(["-s", serial, "pull", remote_path, local_path])

    async def push_file(self, serial: str, local_path: str, remote_path: str) -> str:
        return await self._run(["-s", serial, "push", local_path, remote_path])

    async def get_prop(self, serial: str, prop_name: str) -> str:
        output = await self._run(["-s", serial, "shell", "getprop", prop_name], check=False)
        return output.strip()

    async def set_prop(self, serial: str, prop_name: str, value: str) -> str:
        """Set property. Only works on userdebug/rooted builds."""
        return await self._run(["-s", serial, "shell", "setprop", prop_name, value], check=False)

    async def try_set_property(self, serial: str, prop_name: str, value: str) -> bool:
        """Try setprop (shell → su 0 → su -c). Returns True if any attempt exits 0."""
        if not value:
            return False
        strategies: List[List[str]] = [
            ["shell", "setprop", prop_name, value],
            ["shell", "su", "0", "setprop", prop_name, value],
        ]
        for argv in strategies:
            try:
                proc = await asyncio.create_subprocess_exec(
                    self._adb,
                    "-s",
                    serial,
                    *argv,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await asyncio.wait_for(proc.communicate(), timeout=25)
                if proc.returncode == 0:
                    return True
            except Exception as e:
                logger.debug(f"setprop {prop_name} via {' '.join(argv)}: {e}")

        try:
            proc_sh = await asyncio.create_subprocess_exec(
                self._adb,
                "-s",
                serial,
                "shell",
                "su",
                "-c",
                f"setprop {prop_name} {shlex.quote(value)}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc_sh.communicate(), timeout=25)
            if proc_sh.returncode == 0:
                return True
        except Exception as e:
            logger.debug(f"su -c setprop {prop_name} failed: {e}")
        return False

    async def logcat(self, serial: str, num_lines: int = 100) -> str:
        try:
            output = await self._run(
                ["-s", serial, "logcat", "-t", str(num_lines), "-d"],
                check=False,
                timeout=30,
            )
            return output
        except Exception as e:
            return f"logcat error: {e}"

    async def forward_port(self, serial: str, host_port: int, device_port: int) -> str:
        return await self._run(
            ["-s", serial, "forward", f"tcp:{host_port}", f"tcp:{device_port}"],
            check=False,
        )

    async def wait_for_device(self, serial: str, timeout: int = 60) -> bool:
        try:
            await asyncio.wait_for(
                self._run(["-s", serial, "wait-for-device"], check=True),
                timeout=timeout,
            )
            return True
        except asyncio.TimeoutError:
            return False
        except Exception:
            return False

    async def root(self, serial: str) -> str:
        return await self._run(["-s", serial, "root"], check=False)

    async def remount(self, serial: str) -> str:
        return await self._run(["-s", serial, "remount"], check=False)

    async def reboot(self, serial: str) -> str:
        return await self._run(["-s", serial, "reboot"], check=False)

    async def _run(self, args: List[str], check: bool = True, timeout: int = 60) -> str:
        """Run an ADB command and return stdout as string."""
        cmd = [self._adb] + args
        logger.debug(f"ADB: {' '.join(cmd)}")
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            output = stdout.decode(errors="replace").strip()
            err = stderr.decode(errors="replace").strip()

            if check and proc.returncode != 0:
                raise RuntimeError(f"ADB command failed (rc={proc.returncode}): {err or output}")

            return output if output else err
        except asyncio.TimeoutError:
            logger.error(f"ADB command timed out: {' '.join(cmd)}")
            raise RuntimeError(f"ADB command timed out: {' '.join(args)}")
        except Exception as e:
            if "RuntimeError" in type(e).__name__:
                raise
            logger.error(f"ADB subprocess error: {e}")
            raise RuntimeError(f"ADB error: {e}")

import asyncio
import logging
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List

from config import settings

logger = logging.getLogger(__name__)


def _java_major_from_java_bin(java_bin: Path) -> Optional[int]:
    try:
        proc = subprocess.run(
            [str(java_bin), "-version"],
            capture_output=True,
            timeout=15,
        )
        text = (proc.stderr or b"").decode(errors="replace")
        if not text.strip():
            text = (proc.stdout or b"").decode(errors="replace")
        line = text.splitlines()[0] if text else ""
        m = re.search(r'version "(\d+)', line)
        if m:
            return int(m.group(1))
        m = re.search(r'version "1\.(\d)', line)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return None


def _discover_java_home_17_plus() -> Optional[str]:
    if platform.system() == "Darwin":
        for p in (
            "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home",
            "/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home",
            "/opt/homebrew/opt/openjdk@25/libexec/openjdk.jdk/Contents/Home",
            "/usr/local/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home",
            "/usr/local/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home",
        ):
            jp = Path(p)
            if (jp / "bin" / "java").is_file():
                return str(jp)
        try:
            for ver in ("17", "21", "22", "25"):
                proc = subprocess.run(
                    ["/usr/libexec/java_home", "-v", ver],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if proc.returncode == 0:
                    home = (proc.stdout or "").strip()
                    if home and Path(home, "bin", "java").is_file():
                        return home
        except Exception:
            pass
    elif platform.system() == "Linux":
        for p in (
            "/usr/lib/jvm/java-25-openjdk-amd64",
            "/usr/lib/jvm/java-21-openjdk-amd64",
            "/usr/lib/jvm/java-17-openjdk-amd64",
            "/usr/lib/jvm/java-17-openjdk",
        ):
            jp = Path(p)
            if (jp / "bin" / "java").is_file():
                return str(jp)
    return None


def effective_java_home_for_android_cli() -> Optional[str]:
    """Use JDK 17+ for avdmanager/sdkmanager; replace JAVA_HOME if it is older."""
    env_home = (os.environ.get("JAVA_HOME") or "").strip()
    if env_home:
        jb = Path(env_home) / "bin" / "java"
        if jb.is_file():
            maj = _java_major_from_java_bin(jb)
            if maj is not None and maj >= 17:
                return env_home
    found = _discover_java_home_17_plus()
    if found:
        if env_home and os.path.normpath(found) != os.path.normpath(env_home):
            logger.warning(
                "JAVA_HOME was %s (needs JDK 17+ for avdmanager); using %s instead",
                env_home,
                found,
            )
        elif not env_home:
            logger.info("JAVA_HOME for Android SDK CLI: %s", found)
        return found
    return env_home if env_home else None


def normalize_system_image_arch(arch: str) -> str:
    """Apple Silicon hosts cannot run x86_64 emulator images reliably; use ARM system images."""
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        if arch in ("x86_64", "x86", "i686"):
            return "arm64-v8a"
    return arch


class AVDBackend:
    """Android Virtual Device backend using avdmanager + emulator CLI."""

    def __init__(self):
        self._sdk_path = settings.AVD_SDK_PATH
        self._emulator_bin: Optional[str] = None
        self._avdmanager_bin: Optional[str] = None
        self._adb_bin: Optional[str] = None
        self._sdkmanager_bin: Optional[str] = None
        self._find_binaries()

    def _find_binaries(self):
        """Locate SDK binaries."""
        sdk = Path(self._sdk_path)

        # emulator binary
        candidates = [
            sdk / "emulator" / "emulator",
            sdk / "tools" / "emulator",
            Path("/usr/local/bin/emulator"),
        ]
        for c in candidates:
            if c.exists():
                self._emulator_bin = str(c)
                break
        if not self._emulator_bin:
            self._emulator_bin = shutil.which("emulator") or "emulator"

        # avdmanager
        avd_candidates = [
            sdk / "cmdline-tools" / "latest" / "bin" / "avdmanager",
            sdk / "cmdline-tools" / "bin" / "avdmanager",
            sdk / "tools" / "bin" / "avdmanager",
        ]
        for c in avd_candidates:
            if c.exists():
                self._avdmanager_bin = str(c)
                break
        if not self._avdmanager_bin:
            self._avdmanager_bin = shutil.which("avdmanager") or "avdmanager"

        # sdkmanager
        sdk_candidates = [
            sdk / "cmdline-tools" / "latest" / "bin" / "sdkmanager",
            sdk / "cmdline-tools" / "bin" / "sdkmanager",
            sdk / "tools" / "bin" / "sdkmanager",
        ]
        for c in sdk_candidates:
            if c.exists():
                self._sdkmanager_bin = str(c)
                break
        if not self._sdkmanager_bin:
            self._sdkmanager_bin = shutil.which("sdkmanager") or "sdkmanager"

        # adb
        adb_candidates = [
            sdk / "platform-tools" / "adb",
        ]
        for c in adb_candidates:
            if c.exists():
                self._adb_bin = str(c)
                break
        if not self._adb_bin:
            self._adb_bin = shutil.which("adb") or "adb"

        logger.info(f"AVD binaries: emulator={self._emulator_bin}, avdmanager={self._avdmanager_bin}")

    def _default_avd_ini_path(self, avd_name: str) -> Path:
        return Path.home() / ".android" / "avd" / f"{avd_name}.ini"

    async def ensure_avd_exists(self, device) -> bool:
        """If the AVD was never created (e.g. failed background job), create it now."""
        avd_name = device.avd_name
        if self._default_avd_ini_path(avd_name).is_file():
            return True
        arch = normalize_system_image_arch(device.arch)
        api_level = int(device.api_level or 31)
        logger.warning(
            "AVD %r missing under ~/.android/avd; creating (api=%s arch=%s)",
            avd_name,
            api_level,
            arch,
        )
        return await self.create_avd(avd_name, api_level=api_level, arch=arch)

    async def create_avd(self, device_name: str, api_level: int = 31, arch: str = "x86_64") -> bool:
        """Create a new AVD using avdmanager."""
        arch = normalize_system_image_arch(arch)
        system_image = f"system-images;android-{api_level};google_apis;{arch}"
        logger.info(f"Creating AVD {device_name} with image {system_image}")

        # Check if image is installed
        try:
            env = self._build_env()
            proc = await asyncio.create_subprocess_exec(
                self._avdmanager_bin, "list", "avd",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout, _ = await proc.communicate()
            existing_avds = stdout.decode(errors="replace")
            if device_name in existing_avds:
                logger.info(f"AVD {device_name} already exists")
                return True
        except Exception as e:
            logger.warning(f"Could not list AVDs: {e}")

        hw_profile = "pixel_8" if api_level >= 35 else "pixel_6"

        # Create AVD
        cmd = [
            self._avdmanager_bin,
            "--verbose",
            "create", "avd",
            "--name", device_name,
            "--package", system_image,
            "--device", hw_profile,
            "--force",
        ]
        try:
            env = self._build_env()
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=b"no\n"),
                timeout=120,
            )
            output = stdout.decode(errors="replace")
            err_output = stderr.decode(errors="replace")
            if proc.returncode == 0:
                logger.info(f"AVD {device_name} created successfully")
                return True
            else:
                combined = "\n".join(x for x in (output.strip(), err_output.strip()) if x)
                logger.error(
                    "AVD creation failed (rc=%s): %s",
                    proc.returncode,
                    combined or "(no output; check JAVA_HOME is JDK 17+ for avdmanager)",
                )
                return False
        except asyncio.TimeoutError:
            logger.error(f"AVD creation timed out for {device_name}")
            return False
        except Exception as e:
            logger.error(f"AVD creation exception: {e}")
            return False

    async def start_avd(self, device) -> Tuple[bool, Dict[str, Any]]:
        """Start the emulator process for a device. Returns (success, info_dict)."""
        avd_name = device.avd_name
        preferred = settings.ADB_PORT_START + max(0, (device.id or 1) - 1) * 2
        adb_port = device.adb_port or self._find_free_port_near(preferred)
        console_port = adb_port  # console is adb_port, adb is adb_port+1 for standard emulators
        # Actually emulator uses: console on adb_port, adb on adb_port+1
        adb_host_port = adb_port + 1

        instances_dir = Path(settings.INSTANCES_DIR) / str(device.id)
        instances_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            self._emulator_bin,
            "-avd", avd_name,
            "-no-audio",
            "-no-window",
            "-no-snapshot",
            "-ports", f"{console_port},{adb_host_port}",
            "-wipe-data",
            "-gpu", "swiftshader_indirect",
            "-memory", str(device.ram_mb),
            "-cores", str(device.cpu_cores),
            "-logcat-output", str(instances_dir / "logcat.txt"),
        ]

        env = self._build_env()
        # Isolate emulator runtime files; do NOT set ANDROID_AVD_HOME here — avdmanager
        # creates AVDs under the default home (~/.android/avd), and a per-instance empty
        # AVD_HOME makes -avd <name> fail instantly with no useful stderr.
        env["ANDROID_EMULATOR_HOME"] = str(instances_dir)

        if not await self.ensure_avd_exists(device):
            logger.error("Cannot start: AVD %r does not exist and creation failed", avd_name)
            return False, {}

        logger.info(f"Starting emulator: {' '.join(cmd)}")
        try:
            # The emulator prints INFO| / ERROR| lines to stdout (stderr is often empty).
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
            )
            # Give it a moment to start
            await asyncio.sleep(2)

            if proc.returncode is not None:
                out, _ = await proc.communicate()
                text = (out or b"").decode(errors="replace").strip()
                rc = proc.returncode
                log_path = instances_dir / "emulator-last-run.log"
                try:
                    log_path.write_text(text, encoding="utf-8", errors="replace")
                except OSError:
                    pass
                logger.error(
                    "Emulator exited immediately (rc=%s): %s",
                    rc,
                    text[:2000] if text else "(no output; see %s)" % log_path,
                )
                return False, {}

            async def _drain_emulator_stdout() -> None:
                try:
                    while True:
                        chunk = await proc.stdout.read(65536)
                        if not chunk:
                            break
                except Exception:
                    pass

            asyncio.create_task(_drain_emulator_stdout())

            serial = f"emulator-{adb_port}"
            info = {
                "pid": proc.pid,
                "adb_port": adb_port,
                "adb_serial": serial,
                "console_port": console_port,
                "process": proc,
            }
            logger.info(f"Emulator started: PID={proc.pid}, serial={serial}")
            return True, info
        except Exception as e:
            logger.error(f"Failed to start emulator: {e}")
            return False, {}

    async def stop_avd(self, device) -> bool:
        """Stop the emulator by PID."""
        if not device.pid:
            return True
        try:
            import signal
            os.kill(device.pid, signal.SIGTERM)
            await asyncio.sleep(1)
            try:
                os.kill(device.pid, 0)  # check if still alive
                os.kill(device.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass  # already dead
            logger.info(f"Stopped emulator PID {device.pid}")
            return True
        except ProcessLookupError:
            return True
        except Exception as e:
            logger.error(f"Error stopping emulator PID {device.pid}: {e}")
            return False

    async def get_status(self, device) -> str:
        """Check if emulator is alive."""
        if not device.pid:
            return "stopped"
        try:
            os.kill(device.pid, 0)
            return "running"
        except ProcessLookupError:
            return "stopped"
        except PermissionError:
            return "running"

    async def wait_for_boot(self, serial: str, timeout: int = 180) -> bool:
        """Poll adb shell getprop sys.boot_completed until 1 or timeout."""
        logger.info(f"Waiting for device {serial} to boot (timeout={timeout}s)...")
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            try:
                proc = await asyncio.create_subprocess_exec(
                    self._adb_bin, "-s", serial,
                    "shell", "getprop", "sys.boot_completed",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
                val = stdout.decode().strip()
                if val == "1":
                    logger.info(f"Device {serial} boot completed!")
                    return True
            except Exception:
                pass
            await asyncio.sleep(5)
        logger.warning(f"Device {serial} boot timed out after {timeout}s")
        return False

    async def list_avds(self) -> List[Dict[str, str]]:
        """List all AVDs."""
        try:
            env = self._build_env()
            proc = await asyncio.create_subprocess_exec(
                self._avdmanager_bin, "list", "avd",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            output = stdout.decode(errors="replace")
            return self._parse_avd_list(output)
        except Exception as e:
            logger.error(f"list_avds error: {e}")
            return []

    def _parse_avd_list(self, output: str) -> List[Dict[str, str]]:
        avds = []
        current: Dict[str, str] = {}
        for line in output.splitlines():
            line = line.strip()
            if line.startswith("Name:"):
                if current:
                    avds.append(current)
                current = {"name": line.split(":", 1)[1].strip()}
            elif line.startswith("Path:"):
                current["path"] = line.split(":", 1)[1].strip()
            elif line.startswith("Target:"):
                current["target"] = line.split(":", 1)[1].strip()
            elif line.startswith("ABI:"):
                current["abi"] = line.split(":", 1)[1].strip()
        if current:
            avds.append(current)
        return avds

    async def delete_avd(self, device_name: str) -> bool:
        """Delete an AVD."""
        try:
            env = self._build_env()
            proc = await asyncio.create_subprocess_exec(
                self._avdmanager_bin, "delete", "avd", "--name", device_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            if proc.returncode == 0:
                logger.info(f"AVD {device_name} deleted")
                return True
            logger.warning(f"Delete AVD {device_name} failed: {stderr.decode()}")
            return False
        except Exception as e:
            logger.error(f"delete_avd error: {e}")
            return False

    def _find_free_port(self, start: int) -> int:
        """Find a free even port starting from start (emulators use pairs)."""
        import socket
        port = start
        while port < start + 100:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(("", port))
                    return port
            except OSError:
                port += 2  # emulator ports are in pairs (console, adb)
        return start

    def _find_free_port_near(self, preferred: int, max_tries: int = 40) -> int:
        """Prefer a stable per-device port; scan forward by pairs if busy."""
        import socket
        for i in range(max_tries):
            port = preferred + i * 2
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(("", port))
                    return port
            except OSError:
                continue
        return self._find_free_port(5554)

    def _build_env(self) -> dict:
        """Build environment variables for SDK commands."""
        env = os.environ.copy()
        if self._sdk_path:
            env["ANDROID_HOME"] = self._sdk_path
            env["ANDROID_SDK_ROOT"] = self._sdk_path
        jh = effective_java_home_for_android_cli()
        if jh:
            env["JAVA_HOME"] = jh
            bin_dir = str(Path(jh) / "bin")
            path = env.get("PATH", "")
            if bin_dir not in path:
                env["PATH"] = f"{bin_dir}{os.pathsep}{path}"
        return env

    def _find_emulator_binary(self) -> str:
        """Search for emulator binary."""
        sdk = Path(self._sdk_path)
        candidates = [
            sdk / "emulator" / "emulator",
            sdk / "tools" / "emulator",
        ]
        for c in candidates:
            if c.exists():
                return str(c)
        found = shutil.which("emulator")
        return found or "emulator"

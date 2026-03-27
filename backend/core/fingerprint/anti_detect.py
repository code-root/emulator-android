"""
Comprehensive anti-emulator detection for Android AVDs.

Three-layer approach:
  Layer 1 — ADB system-property patching (survives until reboot)
  Layer 2 — Emulator console commands (battery, sensors, GPS, network)
  Layer 3 — Frida runtime script (hooks Java/JNI calls in target apps)

Emulator-detection vectors eliminated:
  • ro.kernel.qemu=1           ← most common check
  • ro.hardware=ranchu/goldfish ← hardware name
  • ro.product.device=generic*  ← generic device name
  • ro.build.characteristics=emulator
  • ro.product.cpu.abilist showing x86/x86_64
  • ro.debuggable=1 / ro.secure=0 / ro.build.tags=test-keys
  • /dev/qemu_pipe, /dev/goldfish_pipe (checked by apps via File.exists)
  • TelephonyManager returning null IMEI / empty carrier
  • SensorManager returning empty sensor list
  • Battery always 100% / always charging
  • Build class fields matching known emulator signatures
  • SystemProperties.get("ro.kernel.qemu") = "1"
"""
from __future__ import annotations

import asyncio
import logging
import os
import string
from typing import Any, Dict, List, Optional

from core.tools.adb import ADBTool

logger = logging.getLogger(__name__)

# ─── Layer 1: system-property patches ─────────────────────────────────────────
#
# These are applied via `adb shell setprop` (needs root / userdebug build).
# Properties prefixed "ro." are normally read-only but CAN be changed on
# rooted / userdebug / eng builds, which all AVDs are.

EMULATOR_PROPS_OVERRIDE: Dict[str, str] = {
    # ── core emulator flags ────────────────────────────────────────────────
    "ro.kernel.qemu":              "0",
    "ro.kernel.qemu.gles":         "0",
    "ro.kernel.qemu.opengles.version": "0",

    # ── hardware identity ──────────────────────────────────────────────────
    # Do NOT set here — hardware values come from the device profile in
    # spoofer._set_build_props().  Listed for reference only.
    # "ro.hardware":              "qcom",
    # "ro.hardware.egl":          "adreno",

    # ── build type (user = production, not eng/userdebug) ──────────────────
    "ro.build.type":               "user",
    "ro.build.tags":               "release-keys",
    "ro.build.version.codename":   "REL",
    "ro.debuggable":               "0",
    "ro.secure":                   "1",
    "ro.adb.secure":               "1",

    # ── boot/verified boot ─────────────────────────────────────────────────
    "ro.boot.verifiedbootstate":   "green",
    "ro.boot.veritymode":          "enforcing",
    "ro.boot.flash.locked":        "1",
    "ro.boot.warranty_bit":        "0",   # 0 = warranty intact

    # ── CPU ABI (ARM, not x86) ──────────────────────────────────────────────
    # Real values come from device profile.  Generic arm64 defaults:
    "ro.product.cpu.abi":          "arm64-v8a",
    "ro.product.cpu.abilist":      "arm64-v8a,armeabi-v7a,armeabi",
    "ro.product.cpu.abilist32":    "armeabi-v7a,armeabi",
    "ro.product.cpu.abilist64":    "arm64-v8a",

    # ── build characteristics (يُستبدل في apply() حسب البصمة — ليس emulator) ──
    "ro.build.characteristics":    "default",

    # ── telephony ──────────────────────────────────────────────────────────
    "ro.telephony.default_network":  "9",   # 9 = LTE preferred
    "persist.radio.multisim.config": "ssss",
    "ro.telephony.sim_slots.count":  "1",

    # ── misc emulator-specific qemu props ──────────────────────────────────
    "qemu.hw.mainkeys":            "",      # set to empty string = effectively absent
    "qemu.sf.lcd_density":         "",
    "qemu.sf.fake_camera":         "",
    "qemu.gles":                   "",
    "qemu.gles.renderer":          "",

    # ── boot / virtual device flags (فحوصات شائعة) ─────────────────────────
    "ro.boot.qemu":                "0",
    "ro.hardware.virtual_device":  "0",
    "ro.kernel.android.qemud":     "0",
}

# adb shell settings commands (no root required, user-space settings DB)
EMULATOR_SETTINGS_OVERRIDE: List[str] = [
    # device is set up / provisioned
    "settings put global device_provisioned 1",
    "settings put secure user_setup_complete 1",
    # disable USB debugging visibility hint (doesn't disable ADB)
    "settings put global adb_enabled 1",
    # pretend this is not a test device
    "settings put global development_settings_enabled 0",
    # realistic battery state (not "AC_ONLINE" forever)
    # overridden per-device in apply() using console port
]


# ─── Layer 2: emulator console commands ───────────────────────────────────────
#
# Sent via telnet to the emulator console (port = device.console_port).

def _battery_commands(level: int = 78, ac_online: bool = False) -> List[str]:
    """Return emulator-console commands that simulate real battery state."""
    ac  = "ac on" if ac_online else "ac off"
    usb = "usb off"
    return [
        f"power capacity {level}",
        f"power status not-charging",
        ac,
        usb,
    ]

def _sensor_commands() -> List[str]:
    """Simulate realistic sensor readings."""
    return [
        # accelerometer (standing still, flat on table ~9.8 m/s²)
        "sensor set acceleration 0.0:9.80665:0.0",
        # gyroscope (no rotation)
        "sensor set gyroscope 0.0:0.0:0.0",
        # magnetic field (Earth-like)
        "sensor set magnetic-field 22.5:-12.3:43.8",
        # proximity sensor (not covered)
        "sensor set proximity 7.0",
        # light sensor (indoor)
        "sensor set light 200.0",
        # pressure (sea-level ish)
        "sensor set pressure 1013.0",
        # temperature
        "sensor set temperature 25.0",
    ]


# ─── Layer 3: Frida runtime script ────────────────────────────────────────────
#
# Injected into the target app process via frida_tool.py.
# Hooks Java APIs that apps use to detect emulators at runtime.

FRIDA_ANTI_DETECT_SCRIPT = r"""
/*
 * Anti-emulator detection Frida script
 * Hooks commonly used Android APIs to present a real-device identity.
 *
 * Inject with:
 *   frida -U -f <package> --no-pause -l anti_detect.js
 *   OR attach to running process:
 *   frida -U -n <package> -l anti_detect.js
 */

var SPOOF = {
    FINGERPRINT:  "{{build_fingerprint}}",
    MODEL:        "{{device_model}}",
    MANUFACTURER: "{{manufacturer}}",
    BRAND:        "{{brand}}",
    DEVICE:       "{{device_codename}}",
    PRODUCT:      "{{product_name}}",
    HARDWARE:     "{{hardware}}",
    BOARD:        "{{board}}",
    BOOTLOADER:   "{{bootloader}}",
    DISPLAY:      "{{build_display_id}}",
    TAGS:         "release-keys",
    TYPE:         "user",
    HOST:         "{{build_host}}",
    ID:           "{{build_id}}",
    USER:         "dpi",
    SERIAL:       "{{serial_number}}",
    IMEI:         "{{imei}}",
    ANDROID_ID:   "{{android_id}}",
    MAC:          "{{mac_address}}",
    SDK_INT:      {{sdk_version}},
    RELEASE:      "{{android_version}}",
};

// Emulator-specific files that should NOT exist
var EMULATOR_FILES = [
    "/dev/qemu_pipe",
    "/dev/goldfish_pipe",
    "/dev/socket/qemud",
    "/dev/goldfish_sync",
    "/dev/vboxguest",
    "/proc/tty/drivers",      // contains "goldfish" on emulator
    "/sys/bus/platform/drivers/goldfish_battery",
    "/sys/bus/platform/drivers/goldfish_framebuffer",
    "/sys/bus/platform/drivers/goldfish_audio",
    "/sys/devices/virtual/input/input0",    // emulator input device
];

// System properties that should return spoofed values
var PROP_SPOOF = {
    "ro.kernel.qemu":          "0",
    "ro.kernel.qemu.avd_name": "",
    "ro.hardware":             SPOOF.HARDWARE,
    "ro.product.model":        SPOOF.MODEL,
    "ro.product.brand":        SPOOF.BRAND,
    "ro.product.manufacturer": SPOOF.MANUFACTURER,
    "ro.product.device":       SPOOF.DEVICE,
    "ro.build.fingerprint":    SPOOF.FINGERPRINT,
    "ro.build.type":           "user",
    "ro.build.tags":           "release-keys",
    "ro.debuggable":           "0",
    "ro.secure":               "1",
    "ro.product.cpu.abi":      "{{cpu_abi}}",
    "ro.product.cpu.abilist":  "{{cpu_abilist}}",
    "qemu.hw.mainkeys":        "",
    "qemu.sf.lcd_density":     "",
};

Java.perform(function () {

    // ── 1. android.os.Build ───────────────────────────────────────────────
    try {
        var Build = Java.use("android.os.Build");
        Build.FINGERPRINT.value  = SPOOF.FINGERPRINT;
        Build.MODEL.value        = SPOOF.MODEL;
        Build.MANUFACTURER.value = SPOOF.MANUFACTURER;
        Build.BRAND.value        = SPOOF.BRAND;
        Build.DEVICE.value       = SPOOF.DEVICE;
        Build.PRODUCT.value      = SPOOF.PRODUCT;
        Build.HARDWARE.value     = SPOOF.HARDWARE;
        Build.BOARD.value        = SPOOF.BOARD;
        Build.BOOTLOADER.value   = SPOOF.BOOTLOADER;
        Build.DISPLAY.value      = SPOOF.DISPLAY;
        Build.TAGS.value         = SPOOF.TAGS;
        Build.TYPE.value         = SPOOF.TYPE;
        Build.HOST.value         = SPOOF.HOST;
        Build.ID.value           = SPOOF.ID;
        Build.USER.value         = SPOOF.USER;
        Build.SERIAL.value       = SPOOF.SERIAL;
        console.log("[anti_detect] Build fields spoofed ✓");
    } catch (e) {
        console.warn("[anti_detect] Build spoof failed: " + e);
    }

    // ── 2. android.os.Build.VERSION ───────────────────────────────────────
    try {
        var BuildVersion = Java.use("android.os.Build$VERSION");
        BuildVersion.SDK_INT.value  = SPOOF.SDK_INT;
        BuildVersion.RELEASE.value  = SPOOF.RELEASE;
        BuildVersion.CODENAME.value = "REL";
        console.log("[anti_detect] Build.VERSION spoofed ✓");
    } catch (e) {
        console.warn("[anti_detect] Build.VERSION spoof failed: " + e);
    }

    // ── 3. android.os.SystemProperties ───────────────────────────────────
    try {
        var SysProp = Java.use("android.os.SystemProperties");

        SysProp.get.overload("java.lang.String").implementation = function (key) {
            if (PROP_SPOOF.hasOwnProperty(key)) return PROP_SPOOF[key];
            return this.get(key);
        };

        SysProp.get.overload("java.lang.String", "java.lang.String").implementation = function (key, def) {
            if (PROP_SPOOF.hasOwnProperty(key)) return PROP_SPOOF[key];
            return this.get(key, def);
        };

        SysProp.getInt.overload("java.lang.String", "int").implementation = function (key, def) {
            if (key === "ro.kernel.qemu") return 0;
            return this.getInt(key, def);
        };

        console.log("[anti_detect] SystemProperties hooked ✓");
    } catch (e) {
        console.warn("[anti_detect] SystemProperties hook failed: " + e);
    }

    // ── 4. File.exists() — hide emulator device files ──────────────────────
    try {
        var File = Java.use("java.io.File");
        File.exists.implementation = function () {
            var path = this.getAbsolutePath();
            for (var i = 0; i < EMULATOR_FILES.length; i++) {
                if (path === EMULATOR_FILES[i]) return false;
                if (path.startsWith(EMULATOR_FILES[i])) return false;
            }
            return this.exists();
        };
        console.log("[anti_detect] File.exists hooked ✓");
    } catch (e) {
        console.warn("[anti_detect] File.exists hook failed: " + e);
    }

    // ── 5. TelephonyManager ───────────────────────────────────────────────
    try {
        var TM = Java.use("android.telephony.TelephonyManager");

        // getDeviceId (pre-API 26)
        try {
            TM.getDeviceId.overload().implementation = function () { return SPOOF.IMEI; };
        } catch (_) {}

        // getImei (API 26+)
        try {
            TM.getImei.overload().implementation       = function () { return SPOOF.IMEI; };
            TM.getImei.overload("int").implementation  = function () { return SPOOF.IMEI; };
        } catch (_) {}

        // getPhoneType — 1=GSM
        try {
            TM.getPhoneType.overload().implementation = function () { return 1; };
        } catch (_) {}

        // getNetworkOperator — 310410 = AT&T
        try {
            TM.getNetworkOperator.overload().implementation       = function () { return "310410"; };
        } catch (_) {}
        try {
            TM.getNetworkOperatorName.overload().implementation   = function () { return "AT&T"; };
        } catch (_) {}
        try {
            TM.getSimOperator.overload().implementation           = function () { return "310410"; };
        } catch (_) {}
        try {
            TM.getSimOperatorName.overload().implementation       = function () { return "AT&T"; };
        } catch (_) {}

        // getDeviceSoftwareVersion (IMEISV)
        try {
            TM.getDeviceSoftwareVersion.overload().implementation = function () { return "01"; };
        } catch (_) {}

        // isNetworkRoaming
        try {
            TM.isNetworkRoaming.overload().implementation = function () { return false; };
        } catch (_) {}

        console.log("[anti_detect] TelephonyManager hooked ✓");
    } catch (e) {
        console.warn("[anti_detect] TelephonyManager hook failed: " + e);
    }

    // ── 6. Settings.Secure — Android ID ──────────────────────────────────
    try {
        var Secure = Java.use("android.provider.Settings$Secure");
        Secure.getString.overload(
            "android.content.ContentResolver",
            "java.lang.String"
        ).implementation = function (resolver, name) {
            if (name === "android_id") return SPOOF.ANDROID_ID;
            return this.getString(resolver, name);
        };
        console.log("[anti_detect] Settings.Secure.android_id hooked ✓");
    } catch (e) {
        console.warn("[anti_detect] Settings.Secure hook failed: " + e);
    }

    // ── 7. WifiManager — MAC address ─────────────────────────────────────
    try {
        var WifiInfo = Java.use("android.net.wifi.WifiInfo");
        try {
            WifiInfo.getMacAddress.overload().implementation = function () { return SPOOF.MAC; };
        } catch (_) {}
        console.log("[anti_detect] WifiInfo.getMacAddress hooked ✓");
    } catch (e) {
        console.warn("[anti_detect] WifiInfo.MAC hook failed: " + e);
    }

    // ── 8. NetworkInterface — MAC bytes ──────────────────────────────────
    try {
        var NI = Java.use("java.net.NetworkInterface");
        NI.getHardwareAddress.implementation = function () {
            var name = this.getName();
            if (name === "wlan0" || name === "eth0") {
                // parse SPOOF.MAC  "aa:bb:cc:dd:ee:ff" → byte[]
                var parts = SPOOF.MAC.split(":");
                var arr   = Java.array("byte", parts.map(function(h) {
                    var v = parseInt(h, 16);
                    return v > 127 ? v - 256 : v;  // Java signed byte
                }));
                return arr;
            }
            return this.getHardwareAddress();
        };
        console.log("[anti_detect] NetworkInterface.getHardwareAddress hooked ✓");
    } catch (e) {
        console.warn("[anti_detect] NetworkInterface hook failed: " + e);
    }

    // ── 9. SensorManager — report standard sensor list ────────────────────
    // Most advanced detection: if sensor list is empty → emulator.
    // The real sensors physically exist in the AVD firmware;
    // this hook is a last-resort for apps that call getSensorList(TYPE_ALL).
    // Android AVDs with API ≥ 28 usually have sensors enabled by default.
    // No override needed in most cases, but kept as template.

    // ── 10. PackageManager — hide emulator packages ───────────────────────
    try {
        var PM = Java.use("android.app.ApplicationPackageManager");
        var emulatorPkgs = [
            "com.android.emulator.multidisplay",
            "com.android.emulator.smoketests",
            "com.google.android.gms.testapks",
        ];
        PM.getApplicationInfo.overload(
            "java.lang.String", "int"
        ).implementation = function (pkgName, flags) {
            for (var i = 0; i < emulatorPkgs.length; i++) {
                if (pkgName === emulatorPkgs[i]) {
                    throw Java.use("android.content.pm.PackageManager$NameNotFoundException")
                        .$new(pkgName);
                }
            }
            return this.getApplicationInfo(pkgName, flags);
        };
        console.log("[anti_detect] PackageManager.getApplicationInfo hooked ✓");
    } catch (e) {
        console.warn("[anti_detect] PackageManager hook failed (non-fatal): " + e);
    }

    console.log("[anti_detect] All hooks installed.");
});
"""


def _render_frida_script(fp: Dict[str, Any]) -> str:
    """Substitute fingerprint values into the Frida script template."""
    model        = fp.get("device_model", "SM-G996B")
    manufacturer = fp.get("manufacturer", "samsung")
    brand        = fp.get("brand", "samsung")
    codename     = fp.get("device_codename", "o1s")
    board        = fp.get("board", "lahaina")
    hardware     = fp.get("hardware", "qcom")
    fingerprint  = fp.get("build_fingerprint", "samsung/o1sxeea/o1s:15/AP3A.240905.015/G996BXXSJHZC2:user/release-keys")
    serial       = fp.get("serial_number", "R5CN80XXXXX")
    imei         = fp.get("imei", "353000000000000")
    android_id   = fp.get("android_id", "0000000000000000")
    mac          = fp.get("mac_address", "aa:bb:cc:dd:ee:ff")
    sdk          = int(fp.get("sdk_version", 35))
    release      = str(fp.get("android_version", "15"))

    # derive product name & build display from fingerprint
    parts           = fingerprint.split("/")
    product_name    = parts[1] if len(parts) > 1 else codename + "xeea"
    build_display   = fp.get("ap_version") or (parts[4].split(":")[0] if len(parts) > 4 else "G996BXXSJHZC2")
    build_id_str    = fp.get("build_id", "AP3A.240905.015.A2")
    build_host_str  = "SWDD8524"
    bootloader_str  = fp.get("ap_version", "G996BXXSJHZC2")

    cpu_abi = "arm64-v8a"
    cpu_abilist = fp.get("cpu_abi_list_spoof") or "arm64-v8a,armeabi-v7a,armeabi"
    if isinstance(cpu_abilist, str) and "," in cpu_abilist:
        cpu_abi = cpu_abilist.split(",")[0].strip() or cpu_abi

    substitutions = {
        "{{build_fingerprint}}": fingerprint,
        "{{device_model}}":      model,
        "{{manufacturer}}":      manufacturer,
        "{{brand}}":             brand,
        "{{device_codename}}":   codename,
        "{{product_name}}":      product_name,
        "{{hardware}}":          hardware,
        "{{board}}":             board,
        "{{bootloader}}":        bootloader_str,
        "{{build_display_id}}":  build_display,
        "{{build_id}}":          build_id_str,
        "{{build_host}}":        build_host_str,
        "{{serial_number}}":     serial,
        "{{imei}}":              imei,
        "{{android_id}}":        android_id,
        "{{mac_address}}":       mac,
        "{{sdk_version}}":       str(sdk),
        "{{android_version}}":   release,
        "{{cpu_abi}}":           cpu_abi,
        "{{cpu_abilist}}":       str(cpu_abilist),
    }
    script = FRIDA_ANTI_DETECT_SCRIPT
    for placeholder, value in substitutions.items():
        script = script.replace(placeholder, value)
    return script


# ─── Main apply function ───────────────────────────────────────────────────────

class AntiDetect:
    """Apply all anti-emulator-detection measures to a running device."""

    async def apply(
        self,
        adb_tool: ADBTool,
        serial: str,
        fingerprint_data: Dict[str, Any],
        console_port: Optional[int] = None,
    ) -> Dict[str, List[str]]:
        """
        Apply all three layers of anti-detection.

        Returns dict with keys: applied, failed, warnings.
        """
        results: Dict[str, List[str]] = {"applied": [], "failed": [], "warnings": []}

        # ── Layer 1: system properties ────────────────────────────────────
        await self._apply_props(adb_tool, serial, fingerprint_data, results)

        # ── Layer 2: emulator-console commands ────────────────────────────
        if console_port:
            await self._apply_console(console_port, results)
        else:
            results["warnings"].append("anti_detect: no console_port — skipping Layer 2")

        # ── Layer 3: Frida script (write to /data/local/tmp) ─────────────
        await self._write_frida_script(adb_tool, serial, fingerprint_data, results)

        return results

    async def _apply_props(
        self,
        adb_tool: ADBTool,
        serial: str,
        fp: Dict[str, Any],
        results: Dict[str, List[str]],
    ) -> None:
        props = dict(EMULATOR_PROPS_OVERRIDE)

        abilist = (fp.get("cpu_abi_list_spoof") or "arm64-v8a,armeabi-v7a,armeabi").strip()
        first_abi = abilist.split(",")[0].strip() or "arm64-v8a"
        props["ro.product.cpu.abi"] = first_abi
        props["ro.product.cpu.abilist"] = abilist
        props["ro.product.cpu.abilist32"] = "armeabi-v7a,armeabi"
        props["ro.product.cpu.abilist64"] = "arm64-v8a"
        if "," in abilist:
            for part in abilist.split(","):
                p = part.strip()
                if p in ("arm64-v8a", "x86_64"):
                    props["ro.product.cpu.abilist64"] = p
                    break

        manu = (fp.get("manufacturer") or fp.get("brand") or "").lower()
        hw = (fp.get("hardware") or "").lower()
        if manu == "samsung" or hw == "qcom":
            props["ro.build.characteristics"] = "default"
        elif hw in ("ranchu", "goldfish"):
            props["ro.build.characteristics"] = "nosdcard"

        # Merge hardware values from profile
        if fp.get("hardware"):
            props["ro.hardware"]      = fp["hardware"]
            props["ro.boot.hardware"] = fp["hardware"]
        if fp.get("hardware") and fp["hardware"] not in ("ranchu", "goldfish"):
            props["ro.hardware.egl"]  = "adreno" if fp["hardware"] == "qcom" else fp["hardware"]

        for prop, value in props.items():
            if value == "":
                # set to empty but still run the command so the runtime sees it
                cmd = f"setprop {prop} ''"
            else:
                safe_val = value.replace("'", "\\'")
                cmd = f"setprop {prop} '{safe_val}'"
            try:
                await adb_tool.shell(serial, cmd)
                results["applied"].append(f"prop:{prop}")
            except Exception as exc:
                results["failed"].append(f"prop:{prop} ({exc})")

        # settings put
        for cmd in EMULATOR_SETTINGS_OVERRIDE:
            try:
                await adb_tool.shell(serial, cmd)
                results["applied"].append(f"settings:{cmd.split()[3] if len(cmd.split())>3 else cmd}")
            except Exception as exc:
                results["warnings"].append(f"settings_cmd failed: {exc}")

    async def _apply_console(
        self,
        console_port: int,
        results: Dict[str, List[str]],
    ) -> None:
        """Send battery + sensor commands to emulator console."""
        import random
        level  = random.randint(55, 93)
        cmds   = _battery_commands(level=level, ac_online=False) + _sensor_commands()

        for cmd in cmds:
            ok = await self._telnet(console_port, cmd)
            if ok:
                results["applied"].append(f"console:{cmd.split()[0]}")
            else:
                results["warnings"].append(f"console:{cmd[:40]} failed")

    async def _write_frida_script(
        self,
        adb_tool: ADBTool,
        serial: str,
        fp: Dict[str, Any],
        results: Dict[str, List[str]],
    ) -> None:
        """
        Render and push the Frida anti-detect script to /data/local/tmp/
        so the user can inject it with:
            frida -U -f <pkg> --no-pause -l /data/local/tmp/anti_detect.js
        """
        try:
            script = _render_frida_script(fp)
            import tempfile, os as _os
            with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
                f.write(script)
                tmp_path = f.name

            remote_path = "/data/local/tmp/anti_detect.js"
            try:
                await adb_tool.push_file(serial, tmp_path, remote_path)
                await adb_tool.shell(serial, f"chmod 644 {remote_path}")
                results["applied"].append("frida_script:/data/local/tmp/anti_detect.js")
            finally:
                _os.unlink(tmp_path)
        except Exception as exc:
            results["warnings"].append(f"frida_script push failed: {exc}")

    async def _telnet(self, port: int, command: str, timeout: float = 5.0) -> bool:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection("localhost", port), timeout=timeout
            )
            await asyncio.wait_for(reader.read(1024), timeout=2)
            auth_path = os.path.expanduser("~/.emulator_console_auth_token")
            if os.path.exists(auth_path):
                with open(auth_path) as fh:
                    token = fh.read().strip()
                writer.write(f"auth {token}\n".encode())
                await writer.drain()
                await asyncio.wait_for(reader.read(256), timeout=2)
            writer.write(f"{command}\n".encode())
            await writer.drain()
            await asyncio.wait_for(reader.read(256), timeout=2)
            writer.write(b"quit\n")
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            return True
        except Exception:
            return False


anti_detect = AntiDetect()

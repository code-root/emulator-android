import asyncio
import logging
import telnetlib
from typing import Any, Dict, List, Optional

from core.tools.adb import ADBTool
from core.fingerprint.samsung_enhanced import (
    build_extended_samsung_prop_map,
    is_samsung_fingerprint,
    merge_profile_defaults_for_apply,
    samsung_surface_settings_commands,
)
from core.fingerprint.anti_detect import anti_detect

logger = logging.getLogger(__name__)


class FingerprintSpoofer:
    """Apply Android device fingerprint via ADB commands."""

    async def apply(
        self,
        adb_tool: ADBTool,
        serial: str,
        fingerprint_data: Dict[str, Any],
    ) -> Dict[str, List[str]]:
        """Apply all fingerprint fields to a running device."""
        results: Dict[str, List[str]] = {"applied": [], "failed": [], "warnings": []}

        # Try to get root access first
        try:
            await adb_tool.root(serial)
            await asyncio.sleep(2)
            await adb_tool.remount(serial)
        except Exception as e:
            results["warnings"].append(f"Could not get root: {e}. Some props may not apply.")

        fp_merged = merge_profile_defaults_for_apply(fingerprint_data)
        prop_results = await self._set_build_props(adb_tool, serial, fp_merged)
        results["applied"].extend(prop_results["applied"])
        results["failed"].extend(prop_results["failed"])

        if is_samsung_fingerprint(fp_merged):
            n = await self._apply_samsung_surface_settings(adb_tool, serial, fp_merged)
            results["applied"].extend([f"settings:{x}" for x in n.get("ok", [])])
            results["warnings"].extend(n.get("warn", []))

        # Anti-emulator layers (props, optional console, Frida script push)
        try:
            ad = await anti_detect.apply(
                adb_tool,
                serial,
                fp_merged,
                console_port=fp_merged.get("console_port"),
            )
            results["applied"].extend(ad.get("applied", []))
            results["failed"].extend(ad.get("failed", []))
            results["warnings"].extend(ad.get("warnings", []))
        except Exception as e:
            results["warnings"].append(f"anti_detect: {e}")

        # Apply Android ID (works without root via settings)
        if fp_merged.get("android_id"):
            ok = await self._set_android_id(adb_tool, serial, fp_merged)
            if ok:
                results["applied"].append("android_id")
            else:
                results["failed"].append("android_id")

        # Apply GPS location
        if fp_merged.get("latitude") is not None and fp_merged.get("longitude") is not None:
            console_port = fp_merged.get("console_port")
            if console_port:
                ok = await self._set_gps(adb_tool, serial, fp_merged, console_port)
                if ok:
                    results["applied"].append("gps")
                else:
                    results["warnings"].append("GPS: telnet console not available")
            else:
                results["warnings"].append("GPS: no console port configured")

        # Apply MAC address (requires root)
        if fp_merged.get("mac_address"):
            ok = await self._set_mac(adb_tool, serial, fp_merged["mac_address"])
            if ok:
                results["applied"].append("mac_address")
            else:
                results["warnings"].append("MAC: requires root/kernel support")

        # Apply timezone
        if fp_merged.get("timezone"):
            ok = await self._set_timezone(adb_tool, serial, fp_merged["timezone"])
            if ok:
                results["applied"].append("timezone")

        # Apply language/locale
        if fp_merged.get("language") and fp_merged.get("country"):
            ok = await self._set_locale(adb_tool, serial, fp_merged["language"], fp_merged["country"])
            if ok:
                results["applied"].append("locale")

        # Apply network type via emulator console
        if fp_merged.get("network_type") and fp_merged.get("console_port"):
            ok = await self._set_network_type(
                adb_tool, serial, fp_merged["network_type"], fp_merged["console_port"]
            )
            if ok:
                results["applied"].append("network_type")

        bl = fp_merged.get("battery_level")
        if bl is not None and fp_merged.get("console_port"):
            try:
                lvl = max(0, min(100, int(bl)))
                ok = await self._set_battery(adb_tool, serial, lvl, fp_merged["console_port"])
                if ok:
                    results["applied"].append(f"battery_console:{lvl}")
            except (TypeError, ValueError):
                results["warnings"].append("battery_level invalid")

        logger.info(
            f"Fingerprint applied to {serial}: "
            f"{len(results['applied'])} ok, {len(results['failed'])} failed"
        )
        return results

    async def _set_build_props(
        self,
        adb: ADBTool,
        serial: str,
        fp: Dict[str, Any],
    ) -> Dict[str, List[str]]:
        """Set build/product props — مسار Samsung موسّع + مسار عام."""
        if is_samsung_fingerprint(fp):
            props = build_extended_samsung_prop_map(fp)
        else:
            props = {}
            if fp.get("device_model"):
                props["ro.product.model"] = fp["device_model"]
            if fp.get("manufacturer"):
                props["ro.product.manufacturer"] = fp["manufacturer"]
            if fp.get("brand"):
                props["ro.product.brand"] = fp["brand"]
            if fp.get("device_codename"):
                props["ro.product.device"] = fp["device_codename"]
                props["ro.product.name"] = fp["device_codename"]
            if fp.get("board"):
                props["ro.product.board"] = fp["board"]
            if fp.get("build_fingerprint"):
                props["ro.build.fingerprint"] = fp["build_fingerprint"]
                props["ro.bootimage.build.fingerprint"] = fp["build_fingerprint"]
            if fp.get("hardware"):
                props["ro.hardware"] = fp["hardware"]
            if fp.get("serial_number"):
                props["ro.serialno"] = fp["serial_number"]
            if fp.get("android_version"):
                props["ro.build.version.release"] = fp["android_version"]
            if fp.get("sdk_version"):
                props["ro.build.version.sdk"] = str(fp["sdk_version"])
            if fp.get("security_patch"):
                props["ro.build.version.security_patch"] = str(fp["security_patch"])
            if fp.get("build_id"):
                props["ro.build.id"] = str(fp["build_id"])
            if fp.get("product_name"):
                props["ro.product.name"] = str(fp["product_name"])
            if fp.get("bootloader_override"):
                props["ro.bootloader"] = str(fp["bootloader_override"])
            ap = fp.get("ap_version")
            csc = fp.get("csc_version")
            if ap:
                props["ro.build.display.id"] = ap
                props["ro.build.version.incremental"] = ap
                props["ro.bootloader"] = ap
                props["ro.build.PDA"] = ap
            if csc:
                props["ro.csc.version"] = csc
                props["ro.omc.version"] = csc
                if not ap:
                    props["ro.build.changelist"] = csc

        applied: List[str] = []
        failed: List[str] = []
        for prop, value in props.items():
            ok = await adb.try_set_property(serial, prop, value)
            if ok:
                applied.append(prop)
            else:
                failed.append(prop)

        return {"applied": applied, "failed": failed}

    async def _apply_samsung_surface_settings(
        self,
        adb: ADBTool,
        serial: str,
        fp: Dict[str, Any],
    ) -> Dict[str, List[str]]:
        ok: List[str] = []
        warn: List[str] = []
        for cmd in samsung_surface_settings_commands(fp):
            try:
                await adb.shell(serial, cmd)
                ok.append(cmd.split()[2] if len(cmd.split()) > 2 else cmd)
            except Exception as e:
                warn.append(f"settings cmd failed: {cmd[:48]}… ({e})")
        return {"ok": ok, "warn": warn}

    async def _set_android_id(
        self,
        adb: ADBTool,
        serial: str,
        fp: Dict[str, Any],
    ) -> bool:
        """Set Android ID via settings provider."""
        android_id = fp.get("android_id", "")
        if not android_id:
            return False
        try:
            await adb.shell(serial, f"settings put secure android_id {android_id}")
            return True
        except Exception as e:
            logger.warning(f"Failed to set android_id: {e}")
            return False

    async def _set_gps(
        self,
        adb: ADBTool,
        serial: str,
        fp: Dict[str, Any],
        console_port: int,
    ) -> bool:
        """Set GPS coordinates via emulator console (telnet)."""
        lat = fp.get("latitude")
        lng = fp.get("longitude")
        alt = fp.get("altitude", 0)
        if lat is None or lng is None:
            return False
        try:
            return await self._telnet_command(
                console_port,
                f"geo fix {lng} {lat} {alt}",
            )
        except Exception as e:
            logger.warning(f"GPS set via telnet failed: {e}")
            # Fallback: use adb shell
            try:
                # Enable mock locations
                await adb.shell(serial, "settings put secure mock_location 1")
                return True
            except Exception:
                return False

    async def _set_mac(
        self,
        adb: ADBTool,
        serial: str,
        mac: str,
    ) -> bool:
        """Set MAC address via ip link (requires root)."""
        try:
            output = await adb.shell(serial, f"ip link set wlan0 address {mac}")
            return True
        except Exception as e:
            logger.debug(f"MAC set failed (expected on most devices): {e}")
            return False

    async def _set_network_type(
        self,
        adb: ADBTool,
        serial: str,
        network_type: str,
        console_port: int,
    ) -> bool:
        """Set network type via emulator console."""
        type_map = {
            "WIFI": "full",
            "LTE": "lte",
            "5G": "5g",
            "3G": "umts",
            "2G": "gprs",
        }
        speed = type_map.get(network_type, "full")
        try:
            return await self._telnet_command(console_port, f"network speed {speed}")
        except Exception as e:
            logger.debug(f"Network type set failed: {e}")
            return False

    async def _set_battery(
        self,
        adb: ADBTool,
        serial: str,
        level: int,
        console_port: int,
    ) -> bool:
        """Set battery level via emulator console."""
        try:
            return await self._telnet_command(console_port, f"power capacity {level}")
        except Exception as e:
            logger.debug(f"Battery set failed: {e}")
            return False

    async def _set_timezone(self, adb: ADBTool, serial: str, timezone: str) -> bool:
        try:
            await adb.shell(serial, f"setprop persist.sys.timezone {timezone}")
            await adb.shell(serial, f"settings put global time_zone {timezone}")
            return True
        except Exception as e:
            logger.debug(f"Timezone set failed: {e}")
            return False

    async def _set_locale(self, adb: ADBTool, serial: str, language: str, country: str) -> bool:
        try:
            locale = f"{language}-{country}"
            await adb.shell(serial, f"setprop persist.sys.locale {locale}")
            await adb.shell(serial, f"setprop persist.sys.language {language}")
            await adb.shell(serial, f"setprop persist.sys.country {country}")
            return True
        except Exception as e:
            logger.debug(f"Locale set failed: {e}")
            return False

    async def _telnet_command(self, port: int, command: str, timeout: float = 5.0) -> bool:
        """Send a command to the emulator via telnet console."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection("localhost", port),
                timeout=timeout,
            )
            # Wait for OK prompt
            await asyncio.wait_for(reader.read(1024), timeout=2)

            # Send auth token if required
            import os
            auth_token_path = os.path.expanduser("~/.emulator_console_auth_token")
            if os.path.exists(auth_token_path):
                with open(auth_token_path) as f:
                    token = f.read().strip()
                writer.write(f"auth {token}\n".encode())
                await writer.drain()
                await asyncio.wait_for(reader.read(256), timeout=2)

            # Send command
            writer.write(f"{command}\n".encode())
            await writer.drain()
            await asyncio.wait_for(reader.read(256), timeout=2)

            writer.write(b"quit\n")
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            return True
        except Exception as e:
            logger.debug(f"Telnet command '{command}' on port {port} failed: {e}")
            return False

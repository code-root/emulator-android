"""
ربط جهاز Android حقيقي عبر ADB (USB أو adb connect) — روم سامسونغ / One UI فعلي.

لا يُشغّل محاكياً؛ يتحقق من ظهور التسلسل في adb ويستخدمه كما هو.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Tuple

from core.tools.adb import ADBTool

logger = logging.getLogger(__name__)


class PhysicalDeviceBackend:
    """إرفاق جهاز مضيف واحد لكل سجل Device (تسلسل ADB ثابت)."""

    async def attach(self, device) -> Tuple[bool, Dict[str, Any]]:
        serial = (getattr(device, "host_adb_serial", None) or "").strip()
        if not serial:
            logger.error("physical device: empty host_adb_serial for device id=%s", getattr(device, "id", "?"))
            return False, {}

        adb = ADBTool()
        if ":" in serial:
            try:
                await adb.connect(serial)
            except Exception as e:
                logger.debug("adb connect %s: %s", serial, e)

        ok = await adb.wait_for_device(serial, timeout=45)
        if not ok:
            logger.error("physical device: adb did not see serial %r (usb debugging on? cable?)", serial)
            return False, {}

        try:
            out = await adb.shell(serial, "getprop sys.boot_completed")
            if out.strip() != "1":
                logger.warning("physical device %s: boot_completed=%r (continuing anyway)", serial, out[:80])
        except Exception as e:
            logger.warning("physical device %s: boot check: %s", serial, e)

        logger.info("physical device attached: %s", serial)
        return True, {
            "pid": None,
            "adb_port": None,
            "adb_serial": serial,
            "console_port": None,
            "process": None,
        }

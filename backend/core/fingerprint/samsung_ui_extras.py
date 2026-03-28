"""
واجهة تشبه سامسونغ على محاكي Google AVD: لا يوجد One UI حقيقي بدون روم سامسونغ.

بعد تطبيق البصمة، إن وُجدت ملفات ‎.apk في ‎SAMSUNG_UI_EXTRAS_DIR تُثبَّت بالترتيب،
ثم يُعاد تعيين المشغّل الافتراضي اختيارياً عبر samsung_ui.json.

المستخدم يضع APKs بنفسه (مثلاً مستخرجة من جهازه) — لا نوزّع سوفتوير سامسونغ مع المشروع.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from config import settings
from core.fingerprint.samsung_enhanced import is_samsung_fingerprint
from core.tools.adb import ADBTool

logger = logging.getLogger(__name__)

CONFIG_NAME = "samsung_ui.json"


async def apply_samsung_ui_extras(adb_tool: ADBTool, serial: str, fp: Dict[str, Any]) -> Dict[str, Any]:
    """
    يثبّت ‎*.apk من مجلد الإضافات ويضبط المشغّل الافتراضي إن وُجدت الإعدادات.

    يعيد: installed (أسماء ملفات), home_set (نص أو None), warnings (قائمة).
    """
    out: Dict[str, Any] = {"installed": [], "home_set": None, "warnings": []}
    if not is_samsung_fingerprint(fp):
        return out

    root = Path(settings.SAMSUNG_UI_EXTRAS_DIR)
    if not root.is_dir():
        return out

    apks = sorted(root.glob("*.apk"), key=lambda p: p.name.lower())
    if not apks:
        return out

    for apk in apks:
        try:
            text = await adb_tool.install_apk(serial, str(apk), args=["-r", "-t", "-g"])
            out["installed"].append(apk.name)
            if "Failure" in text or "INSTALL_FAILED" in text:
                out["warnings"].append(f"{apk.name}: {text.strip()[-400:]}")
            logger.info("samsung_ui_extras: installed %s", apk.name)
        except Exception as e:
            out["warnings"].append(f"{apk.name}: {e}")

    cfg = root / CONFIG_NAME
    home: str = ""
    if cfg.is_file():
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            home = str(data.get("default_home") or data.get("home_activity") or "").strip()
        except Exception as e:
            out["warnings"].append(f"samsung_ui.json: {e}")

    if home:
        try:
            await adb_tool.shell(serial, f"cmd package set-home-activity {home}")
            out["home_set"] = home
        except Exception as e:
            out["warnings"].append(f"set-home-activity {home}: {e}")

    try:
        await adb_tool.shell(
            serial,
            "am start -a android.intent.action.MAIN -c android.intent.category.HOME",
        )
    except Exception as e:
        out["warnings"].append(f"launch HOME: {e}")

    return out

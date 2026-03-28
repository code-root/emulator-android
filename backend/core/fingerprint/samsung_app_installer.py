"""
Samsung app installer for Android emulator.

Automatically installs Samsung system apps and configures defaults.
تثبيت تطبيقات Samsung تلقائياً وتعيينها كافتراضية.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.tools.adb import ADBTool

logger = logging.getLogger(__name__)

# Samsung app catalog with package names and relative paths
SAMSUNG_APPS = {
    "launcher": {
        "package": "com.sec.android.app.launcher",
        "apk_name": "launcher.apk",
        "apk_paths": [
            "firmware/samsung_apps/com.sec.android.app.launcher/base.apk",
            "firmware/samsung_apps/launcher/base.apk",
            "firmware/samsung_apps/com.sec.android.app.launcher.apk",
            "firmware/samsung_apps/launcher.apk",
        ],
        "component": "com.sec.android.app.launcher/.Launcher",
        "priority": 1,
        "description": "Samsung One UI Home Launcher",
    },
    "internet": {
        "package": "com.sec.android.app.sbrowser",
        "apk_name": "internet.apk",
        "apk_paths": [
            "firmware/samsung_apps/com.sec.android.app.sbrowser/base.apk",
            "firmware/samsung_apps/internet/base.apk",
            "firmware/samsung_apps/com.sec.android.app.sbrowser.apk",
            "firmware/samsung_apps/internet.apk",
        ],
        "component": "com.sec.android.app.sbrowser/.SBrowserMainActivity",
        "priority": 1,
        "description": "Samsung Internet Browser",
    },
    "keyboard": {
        "package": "com.samsung.android.inputmethod",
        "apk_name": "keyboard.apk",
        "apk_paths": [
            "firmware/samsung_apps/com.samsung.android.inputmethod/base.apk",
            "firmware/samsung_apps/keyboard/base.apk",
            "firmware/samsung_apps/com.samsung.android.inputmethod.apk",
            "firmware/samsung_apps/keyboard.apk",
        ],
        "component": "com.samsung.android.inputmethod/.SamsungKeyboard",
        "priority": 1,
        "description": "Samsung Keyboard",
    },
    "notes": {
        "package": "com.sec.android.app.notes",
        "apk_name": "notes.apk",
        "apk_paths": [
            "firmware/samsung_apps/com.sec.android.app.notes/base.apk",
            "firmware/samsung_apps/notes/base.apk",
            "firmware/samsung_apps/com.sec.android.app.notes.apk",
            "firmware/samsung_apps/notes.apk",
        ],
        "component": "com.sec.android.app.notes/.NotesMainActivity",
        "priority": 2,
        "description": "Samsung Notes",
    },
    "health": {
        "package": "com.sec.android.app.shealth",
        "apk_name": "health.apk",
        "apk_paths": [
            "firmware/samsung_apps/com.sec.android.app.shealth/base.apk",
            "firmware/samsung_apps/health/base.apk",
            "firmware/samsung_apps/com.sec.android.app.shealth.apk",
            "firmware/samsung_apps/health.apk",
        ],
        "component": "com.sec.android.app.shealth/.MainActivity",
        "priority": 2,
        "description": "Samsung Health",
    },
    "secure_folder": {
        "package": "com.samsung.knox.securefolder",
        "apk_name": "secure_folder.apk",
        "apk_paths": [
            "firmware/samsung_apps/com.samsung.knox.securefolder/base.apk",
            "firmware/samsung_apps/secure_folder/base.apk",
            "firmware/samsung_apps/com.samsung.knox.securefolder.apk",
            "firmware/samsung_apps/secure_folder.apk",
        ],
        "component": "com.samsung.knox.securefolder/.MainActivityForSF",
        "priority": 2,
        "description": "Samsung Secure Folder",
    },
    "theme": {
        "package": "com.samsung.android.themestore",
        "apk_name": "theme.apk",
        "apk_paths": [
            "firmware/samsung_apps/com.samsung.android.themestore/base.apk",
            "firmware/samsung_apps/theme/base.apk",
            "firmware/samsung_apps/com.samsung.android.themestore.apk",
            "firmware/samsung_apps/theme.apk",
        ],
        "component": "com.samsung.android.themestore/.MainActivity",
        "priority": 2,
        "description": "Samsung Theme Store",
    },
    "galaxy_store": {
        "package": "com.sec.android.app.samsungapps",
        "apk_name": "galaxy_store.apk",
        "apk_paths": [
            "firmware/samsung_apps/com.sec.android.app.samsungapps/base.apk",
            "firmware/samsung_apps/galaxy_store/base.apk",
            "firmware/samsung_apps/com.sec.android.app.samsungapps.apk",
            "firmware/samsung_apps/galaxy_store.apk",
        ],
        "component": "com.sec.android.app.samsungapps/.SamsungAppsMainActivity",
        "priority": 3,
        "description": "Galaxy Store",
    },
    "pass": {
        "package": "com.samsung.android.smartlock",
        "apk_name": "pass.apk",
        "apk_paths": [
            "firmware/samsung_apps/com.samsung.android.smartlock/base.apk",
            "firmware/samsung_apps/pass/base.apk",
            "firmware/samsung_apps/com.samsung.android.smartlock.apk",
            "firmware/samsung_apps/pass.apk",
        ],
        "component": "com.samsung.android.smartlock/.MainActivity",
        "priority": 3,
        "description": "Samsung Pass",
    },
    "quick_share": {
        "package": "com.samsung.android.app.sharelive",
        "apk_name": "quick_share.apk",
        "apk_paths": [
            "firmware/samsung_apps/com.samsung.android.app.sharelive/base.apk",
            "firmware/samsung_apps/quick_share/base.apk",
            "firmware/samsung_apps/com.samsung.android.app.sharelive.apk",
            "firmware/samsung_apps/quick_share.apk",
        ],
        "component": "com.samsung.android.app.sharelive/.MainActivity",
        "priority": 3,
        "description": "Samsung Quick Share",
    },
}


def find_apk_file(firmware_dir: Path, app_key: str) -> Optional[Path]:
    """
    Find APK file for a Samsung app by checking multiple possible locations.

    Args:
        firmware_dir: Directory where Samsung APKs are stored
        app_key: Key in SAMSUNG_APPS dict (e.g., 'launcher', 'internet')

    Returns:
        Path to APK file if found, None otherwise
    """
    if app_key not in SAMSUNG_APPS:
        return None

    app_info = SAMSUNG_APPS[app_key]

    # Try each possible path
    for apk_path in app_info["apk_paths"]:
        full_path = firmware_dir / apk_path
        if full_path.exists() and full_path.is_file():
            return full_path

    return None


async def install_samsung_app(
    adb_tool: ADBTool,
    serial: str,
    app_key: str,
    apk_path: Path,
) -> bool:
    """
    Install a single Samsung app via ADB.

    Args:
        adb_tool: ADB tool instance
        serial: Device serial
        app_key: App key from SAMSUNG_APPS
        apk_path: Path to APK file

    Returns:
        True if successful, False otherwise
    """
    if not apk_path.exists():
        logger.warning(f"APK not found: {apk_path}")
        return False

    app_info = SAMSUNG_APPS[app_key]

    try:
        await adb_tool.install(serial, str(apk_path))
        logger.info(f"✓ Installed {app_info['description']} ({app_key})")
        return True
    except Exception as e:
        logger.warning(f"✗ Failed to install {app_key}: {str(e)[:100]}")
        return False


async def install_samsung_apps(
    adb_tool: ADBTool,
    serial: str,
    firmware_dir: Path,
    apps_to_install: Optional[List[str]] = None,
    skip_missing: bool = True,
) -> Dict[str, Any]:
    """
    Install Samsung apps on device.

    تثبيت تطبيقات Samsung على الجهاز

    Args:
        adb_tool: ADB tool instance
        serial: Device serial number
        firmware_dir: Path to firmware directory with APKs
        apps_to_install: List of app keys to install (None = priority 1 only)
        skip_missing: If True, skip apps with missing APKs (default: True)

    Returns:
        Dict with 'installed', 'failed', 'skipped' lists
    """
    if not firmware_dir.exists():
        logger.warning(f"Firmware directory not found: {firmware_dir}")
        return {"installed": [], "failed": [], "skipped": []}

    # Default: install only priority 1 apps (launcher, internet, keyboard)
    if apps_to_install is None:
        apps_to_install = [
            k for k, v in SAMSUNG_APPS.items()
            if v.get("priority", 3) <= 1
        ]

    installed = []
    failed = []
    skipped = []

    for app_key in apps_to_install:
        if app_key not in SAMSUNG_APPS:
            logger.warning(f"Unknown app key: {app_key}")
            continue

        apk_path = find_apk_file(firmware_dir, app_key)

        if not apk_path:
            msg = f"{app_key}: APK not found"
            if skip_missing:
                skipped.append(msg)
                logger.info(f"⊘ Skipped {msg}")
            else:
                failed.append(msg)
                logger.warning(f"✗ {msg}")
            continue

        if await install_samsung_app(adb_tool, serial, app_key, apk_path):
            installed.append(app_key)
        else:
            failed.append(app_key)

    return {
        "installed": installed,
        "failed": failed,
        "skipped": skipped,
    }


async def set_samsung_defaults(
    adb_tool: ADBTool,
    serial: str,
) -> Dict[str, Any]:
    """
    Set Samsung apps as system defaults.

    تعيين تطبيقات Samsung كافتراضية

    Args:
        adb_tool: ADB tool instance
        serial: Device serial

    Returns:
        Dict with 'set', 'failed' lists
    """
    defaults = {
        "launcher": "com.sec.android.app.launcher/.Launcher",
        "keyboard": "com.samsung.android.inputmethod/.SamsungKeyboard",
        "internet": "com.sec.android.app.sbrowser/.SBrowserMainActivity",
    }

    set_defaults = []
    failed = []

    for role, component in defaults.items():
        try:
            await adb_tool.shell(
                serial,
                f"cmd package set-home-activity {component}",
            )
            set_defaults.append(role)
            logger.info(f"✓ Set {role} default: {component}")
        except Exception as e:
            failed.append(f"{role}: {str(e)[:80]}")
            logger.warning(f"✗ Failed to set {role} default: {e}")

    return {
        "set": set_defaults,
        "failed": failed,
    }


async def configure_knox_security(
    adb_tool: ADBTool,
    serial: str,
) -> Dict[str, Any]:
    """
    Configure enhanced Knox security settings.

    تعزيز إعدادات Knox Security

    Args:
        adb_tool: ADB tool instance
        serial: Device serial

    Returns:
        Dict with 'configured', 'failed' lists
    """
    knox_props = {
        "ro.config.knox": "1",
        "ro.config.tima": "1",
        "ro.boot.warranty_bit": "1",
        "ro.boot.flash.locked": "1",
        "ro.securestorage.support": "true",
        "knox.supported": "1",
    }

    configured = []
    failed = []

    for prop, value in knox_props.items():
        try:
            await adb_tool.try_set_property(serial, prop, value)
            configured.append(f"{prop}={value}")
            logger.info(f"✓ Configured {prop} = {value}")
        except Exception as e:
            failed.append(f"{prop}: {str(e)[:80]}")
            logger.warning(f"✗ Failed to configure {prop}: {e}")

    return {
        "configured": configured,
        "failed": failed,
    }


async def setup_galaxy_account(
    adb_tool: ADBTool,
    serial: str,
) -> Dict[str, Any]:
    """
    Setup Galaxy Account integration.

    إعداد حساب Galaxy

    Args:
        adb_tool: ADB tool instance
        serial: Device serial

    Returns:
        Dict with status
    """
    try:
        # Enable Galaxy Account service
        await adb_tool.shell(
            serial,
            "am start com.sec.android.app.samsungapps/com.samsung.android.SettingsSearch.SettingsSearchActivity",
        )
        logger.info("✓ Galaxy Account integration setup initiated")
        return {"status": "success"}
    except Exception as e:
        logger.warning(f"✗ Galaxy Account setup failed: {e}")
        return {"status": "failed", "error": str(e)[:100]}


async def setup_secure_folder(
    adb_tool: ADBTool,
    serial: str,
) -> Dict[str, Any]:
    """
    Configure Secure Folder settings.

    إعداد مجلد آمن

    Args:
        adb_tool: ADB tool instance
        serial: Device serial

    Returns:
        Dict with status
    """
    try:
        # Start Secure Folder service
        await adb_tool.shell(
            serial,
            "am start com.samsung.knox.securefolder/.MainActivityForSF",
        )
        logger.info("✓ Secure Folder initialized")
        return {"status": "success"}
    except Exception as e:
        logger.warning(f"✗ Secure Folder setup failed: {e}")
        return {"status": "failed", "error": str(e)[:100]}


async def apply_samsung_ui_theme(
    adb_tool: ADBTool,
    serial: str,
) -> Dict[str, Any]:
    """
    Apply Samsung UI theme settings.

    تطبيق موضوع One UI

    Args:
        adb_tool: ADB tool instance
        serial: Device serial

    Returns:
        Dict with status
    """
    theme_settings = {
        # Color mode: Natural (default for One UI)
        "ro.config.theme_mode": "0",
        # One UI features
        "ro.build.fingerprint_oneui": "true",
    }

    configured = []
    failed = []

    for key, value in theme_settings.items():
        try:
            await adb_tool.try_set_property(serial, key, value)
            configured.append(f"{key}={value}")
            logger.info(f"✓ Theme setting: {key} = {value}")
        except Exception:
            failed.append(key)

    return {
        "configured": configured,
        "failed": failed,
    }


async def full_samsung_setup(
    adb_tool: ADBTool,
    serial: str,
    firmware_dir: Path,
) -> Dict[str, Any]:
    """
    Full Samsung environment setup.

    إعداد بيئة Samsung كاملة

    Args:
        adb_tool: ADB tool instance
        serial: Device serial
        firmware_dir: Path to firmware directory

    Returns:
        Dict with all setup results
    """
    logger.info("═" * 80)
    logger.info("Starting Full Samsung Setup...")
    logger.info("═" * 80)

    results = {}

    # Phase 1: Install apps
    logger.info("\n📱 Phase 1: Installing Samsung Apps...")
    results["apps"] = await install_samsung_apps(
        adb_tool,
        serial,
        firmware_dir,
        skip_missing=True,
    )

    # Phase 2: Set defaults
    logger.info("\n⚙️  Phase 2: Setting Samsung Defaults...")
    results["defaults"] = await set_samsung_defaults(adb_tool, serial)

    # Phase 3: Knox Security
    logger.info("\n🔒 Phase 3: Configuring Knox Security...")
    results["knox"] = await configure_knox_security(adb_tool, serial)

    # Phase 4: Theme
    logger.info("\n🎨 Phase 4: Applying Samsung UI Theme...")
    results["theme"] = await apply_samsung_ui_theme(adb_tool, serial)

    # Phase 5: Secure Folder
    logger.info("\n📁 Phase 5: Setting Up Secure Folder...")
    results["secure_folder"] = await setup_secure_folder(adb_tool, serial)

    # Phase 6: Galaxy Account
    logger.info("\n👤 Phase 6: Setting Up Galaxy Account...")
    results["galaxy_account"] = await setup_galaxy_account(adb_tool, serial)

    logger.info("\n" + "═" * 80)
    logger.info("✅ Full Samsung Setup Complete!")
    logger.info("═" * 80)

    return results

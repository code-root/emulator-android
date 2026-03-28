#!/usr/bin/env python3
"""
Basic functional tests for Samsung app installer
اختبارات وظيفية أساسية لمثبت تطبيقات Samsung
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from core.fingerprint.samsung_app_installer import (
    find_apk_file,
    SAMSUNG_APPS,
)


def test_samsung_apps_registry():
    """Test that Samsung apps registry is properly configured"""
    print("\n🔍 Test 1: Samsung Apps Registry")
    print("=" * 60)

    # Check required apps exist
    required_apps = ["launcher", "internet", "keyboard"]
    for app in required_apps:
        assert app in SAMSUNG_APPS, f"Missing app: {app}"
        print(f"  ✓ {app} registered")

    # Check app structure
    for app_key, app_info in SAMSUNG_APPS.items():
        required_fields = {"package", "apk_paths", "component", "priority"}
        for field in required_fields:
            assert field in app_info, f"Missing field '{field}' in {app_key}"
        print(f"  ✓ {app_key} has all required fields")

    # Check priority values
    for app_key, app_info in SAMSUNG_APPS.items():
        priority = app_info.get("priority")
        assert priority in [1, 2, 3], f"Invalid priority for {app_key}: {priority}"
    print(f"  ✓ All apps have valid priority values (1-3)")

    print("\n✅ Registry Test PASSED\n")


def test_apk_file_discovery():
    """Test APK file discovery mechanism"""
    print("\n🔍 Test 2: APK File Discovery")
    print("=" * 60)

    # Create temporary directory structure
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        fw_dir = Path(tmpdir)

        # Test 1: No APKs found
        result = find_apk_file(fw_dir, "launcher")
        assert result is None, "Should return None when APK not found"
        print(f"  ✓ Correctly returns None when APK missing")

        # Test 2: APK in standard location
        # Note: find_apk_file constructs path as firmware_dir / apk_path from registry
        # The apk_path in registry starts with "firmware/samsung_apps/..."
        # So we need to create: tmpdir/firmware/samsung_apps/...
        launcher_dir = fw_dir / "firmware" / "samsung_apps" / "com.sec.android.app.launcher"
        launcher_dir.mkdir(parents=True)
        apk_file = launcher_dir / "base.apk"
        apk_file.write_text("dummy")

        result = find_apk_file(fw_dir, "launcher")
        assert result is not None, "Should find APK in standard location"
        assert result.exists(), "Found APK should exist"
        print(f"  ✓ Finds APK in standard path")

        # Test 3: APK in alternative location
        internet_dir = fw_dir / "firmware" / "samsung_apps" / "internet"
        internet_dir.mkdir(parents=True)
        internet_apk = internet_dir / "base.apk"  # Must be base.apk, not internet.apk
        internet_apk.write_text("dummy")

        result = find_apk_file(fw_dir, "internet")
        assert result is not None, "Should find APK in alternative path"
        print(f"  ✓ Finds APK in alternative paths")

        # Test 4: Invalid app
        result = find_apk_file(fw_dir, "nonexistent_app")
        assert result is None, "Should return None for invalid app"
        print(f"  ✓ Returns None for invalid app")

    print("\n✅ APK Discovery Test PASSED\n")


async def test_async_functions():
    """Test async functions (basic structure check)"""
    print("\n🔍 Test 3: Async Functions Availability")
    print("=" * 60)

    from core.fingerprint.samsung_app_installer import (
        install_samsung_app,
        install_samsung_apps,
        set_samsung_defaults,
        configure_knox_security,
        apply_samsung_ui_theme,
        setup_secure_folder,
        setup_galaxy_account,
    )

    functions = [
        ("install_samsung_app", install_samsung_app),
        ("install_samsung_apps", install_samsung_apps),
        ("set_samsung_defaults", set_samsung_defaults),
        ("configure_knox_security", configure_knox_security),
        ("apply_samsung_ui_theme", apply_samsung_ui_theme),
        ("setup_secure_folder", setup_secure_folder),
        ("setup_galaxy_account", setup_galaxy_account),
    ]

    for name, func in functions:
        assert asyncio.iscoroutinefunction(func), f"{name} is not async"
        print(f"  ✓ {name} is async function")

    print("\n✅ Async Functions Test PASSED\n")


def test_app_packages():
    """Test that app package names are correct"""
    print("\n🔍 Test 4: App Package Names")
    print("=" * 60)

    expected_packages = {
        "launcher": "com.sec.android.app.launcher",
        "internet": "com.sec.android.app.sbrowser",
        "keyboard": "com.samsung.android.inputmethod",
        "notes": "com.sec.android.app.notes",
        "health": "com.sec.android.app.shealth",
        "secure_folder": "com.samsung.knox.securefolder",
        "theme": "com.samsung.android.themestore",
        "galaxy_store": "com.sec.android.app.samsungapps",
        "pass": "com.samsung.android.smartlock",
    }

    for app_key, expected_package in expected_packages.items():
        actual_package = SAMSUNG_APPS[app_key]["package"]
        assert (
            actual_package == expected_package
        ), f"Wrong package for {app_key}: {actual_package} vs {expected_package}"
        print(f"  ✓ {app_key}: {actual_package}")

    print("\n✅ Package Names Test PASSED\n")


def test_apk_paths():
    """Test that apps have valid APK paths"""
    print("\n🔍 Test 5: APK Path Configuration")
    print("=" * 60)

    for app_key, app_info in SAMSUNG_APPS.items():
        apk_paths = app_info.get("apk_paths")
        assert apk_paths is not None, f"Missing apk_paths for {app_key}"
        assert isinstance(apk_paths, list), f"apk_paths should be list for {app_key}"
        assert len(apk_paths) > 0, f"apk_paths is empty for {app_key}"
        print(f"  ✓ {app_key}: {len(apk_paths)} search paths configured")

    print("\n✅ APK Paths Test PASSED\n")


def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("  Samsung App Installer - Basic Tests")
    print("=" * 60)

    try:
        # Synchronous tests
        test_samsung_apps_registry()
        test_apk_file_discovery()
        test_app_packages()
        test_apk_paths()

        # Async tests
        asyncio.run(test_async_functions())

        # Summary
        print("\n" + "=" * 60)
        print("  ✅ ALL TESTS PASSED!")
        print("=" * 60)
        print("\n  مجموع الاختبارات: 5 اختبارات")
        print("  النتيجة: نجح كل شيء ✅\n")

        return 0

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}\n")
        return 1
    except Exception as e:
        print(f"\n❌ ERROR: {e}\n")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

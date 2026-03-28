"""
Tests for Samsung app installer module.

اختبارات وحدة لمثبت تطبيقات Samsung
"""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from core.fingerprint.samsung_app_installer import (
    find_apk_file,
    install_samsung_app,
    install_samsung_apps,
    set_samsung_defaults,
    configure_knox_security,
    SAMSUNG_APPS,
)


@pytest.fixture
def mock_adb_tool():
    """Create mock ADB tool."""
    return AsyncMock()


@pytest.fixture
def firmware_dir(tmp_path):
    """Create temporary firmware directory with test APKs."""
    samsung_apps = tmp_path / "samsung_apps"

    # Create app directories
    for app_key in ["launcher", "internet", "keyboard"]:
        app_dir = samsung_apps / f"com.sec.android.app.{app_key}" if app_key != "internet" else samsung_apps / "com.sec.android.app.sbrowser"
        app_dir.mkdir(parents=True, exist_ok=True)

        # Create dummy APK
        apk_file = app_dir / "base.apk"
        apk_file.write_text(f"dummy apk for {app_key}")

    return tmp_path


class TestFindApkFile:
    """Test APK file discovery."""

    def test_find_existing_apk(self, firmware_dir):
        """Test finding existing APK file."""
        result = find_apk_file(firmware_dir, "launcher")
        assert result is not None
        assert result.exists()
        assert "launcher" in str(result)

    def test_find_nonexistent_app(self, firmware_dir):
        """Test finding APK for non-existent app."""
        result = find_apk_file(firmware_dir, "nonexistent_app")
        assert result is None

    def test_find_internet_apk(self, firmware_dir):
        """Test finding Samsung Internet APK."""
        result = find_apk_file(firmware_dir, "internet")
        assert result is not None
        assert "sbrowser" in str(result)

    def test_multiple_paths_fallback(self, firmware_dir):
        """Test that function checks multiple paths."""
        # Create APK in alternative path
        alt_dir = firmware_dir / "samsung_apps" / "launcher"
        alt_dir.mkdir(parents=True, exist_ok=True)
        alt_apk = alt_dir / "launcher.apk"
        alt_apk.write_text("alternative apk")

        result = find_apk_file(firmware_dir, "launcher")
        assert result is not None


class TestInstallSamsungApp:
    """Test single app installation."""

    @pytest.mark.asyncio
    async def test_install_existing_app(self, mock_adb_tool, firmware_dir):
        """Test installing existing app."""
        apk_path = find_apk_file(firmware_dir, "launcher")

        result = await install_samsung_app(
            mock_adb_tool,
            "emulator-5554",
            "launcher",
            apk_path,
        )

        assert result is True
        mock_adb_tool.install.assert_called_once()

    @pytest.mark.asyncio
    async def test_install_nonexistent_apk(self, mock_adb_tool):
        """Test installing non-existent APK."""
        result = await install_samsung_app(
            mock_adb_tool,
            "emulator-5554",
            "launcher",
            Path("/nonexistent/path/to/apk.apk"),
        )

        assert result is False
        mock_adb_tool.install.assert_not_called()

    @pytest.mark.asyncio
    async def test_install_failure(self, mock_adb_tool, firmware_dir):
        """Test handling installation failure."""
        mock_adb_tool.install.side_effect = Exception("Installation failed")
        apk_path = find_apk_file(firmware_dir, "launcher")

        result = await install_samsung_app(
            mock_adb_tool,
            "emulator-5554",
            "launcher",
            apk_path,
        )

        assert result is False


class TestInstallSamsungApps:
    """Test bulk app installation."""

    @pytest.mark.asyncio
    async def test_install_all_available_apps(self, mock_adb_tool, firmware_dir):
        """Test installing all available apps."""
        result = await install_samsung_apps(
            mock_adb_tool,
            "emulator-5554",
            firmware_dir,
            skip_missing=True,
        )

        assert "installed" in result
        assert "failed" in result
        assert "skipped" in result
        # Should have installed some apps
        assert len(result["installed"]) > 0

    @pytest.mark.asyncio
    async def test_install_specific_apps(self, mock_adb_tool, firmware_dir):
        """Test installing specific apps."""
        result = await install_samsung_apps(
            mock_adb_tool,
            "emulator-5554",
            firmware_dir,
            apps_to_install=["launcher", "internet"],
            skip_missing=True,
        )

        assert "launcher" in result["installed"] or "launcher" in result["skipped"]
        assert "internet" in result["installed"] or "internet" in result["skipped"]

    @pytest.mark.asyncio
    async def test_install_missing_directory(self, mock_adb_tool):
        """Test installation when firmware directory doesn't exist."""
        result = await install_samsung_apps(
            mock_adb_tool,
            "emulator-5554",
            Path("/nonexistent/firmware"),
            skip_missing=True,
        )

        assert result["installed"] == []
        mock_adb_tool.install.assert_not_called()

    @pytest.mark.asyncio
    async def test_skip_missing_apps(self, mock_adb_tool, firmware_dir):
        """Test skipping missing apps."""
        result = await install_samsung_apps(
            mock_adb_tool,
            "emulator-5554",
            firmware_dir,
            apps_to_install=["launcher", "nonexistent"],
            skip_missing=True,
        )

        assert len(result["skipped"]) > 0

    @pytest.mark.asyncio
    async def test_fail_missing_apps(self, mock_adb_tool, firmware_dir):
        """Test failing on missing apps."""
        result = await install_samsung_apps(
            mock_adb_tool,
            "emulator-5554",
            firmware_dir,
            apps_to_install=["launcher", "nonexistent"],
            skip_missing=False,
        )

        assert len(result["failed"]) > 0


class TestSetSamsungDefaults:
    """Test setting Samsung app defaults."""

    @pytest.mark.asyncio
    async def test_set_defaults_success(self, mock_adb_tool):
        """Test successfully setting defaults."""
        result = await set_samsung_defaults(mock_adb_tool, "emulator-5554")

        assert "set" in result
        assert "failed" in result
        # Should attempt to set at least one default
        assert mock_adb_tool.shell.call_count > 0

    @pytest.mark.asyncio
    async def test_set_launcher_default(self, mock_adb_tool):
        """Test setting launcher as default."""
        await set_samsung_defaults(mock_adb_tool, "emulator-5554")

        # Check that cmd package set-home-activity was called
        calls = [str(call) for call in mock_adb_tool.shell.call_args_list]
        assert any("set-home-activity" in str(call) for call in calls)

    @pytest.mark.asyncio
    async def test_set_defaults_failure(self, mock_adb_tool):
        """Test handling failures when setting defaults."""
        mock_adb_tool.shell.side_effect = Exception("Shell error")

        result = await set_samsung_defaults(mock_adb_tool, "emulator-5554")

        assert len(result["failed"]) > 0


class TestConfigureKnoxSecurity:
    """Test Knox security configuration."""

    @pytest.mark.asyncio
    async def test_configure_knox_success(self, mock_adb_tool):
        """Test successfully configuring Knox."""
        result = await configure_knox_security(mock_adb_tool, "emulator-5554")

        assert "configured" in result
        assert "failed" in result
        # Should configure at least one Knox property
        assert len(result["configured"]) > 0

    @pytest.mark.asyncio
    async def test_configure_knox_properties(self, mock_adb_tool):
        """Test that Knox properties are set."""
        await configure_knox_security(mock_adb_tool, "emulator-5554")

        # Check that try_set_property was called
        assert mock_adb_tool.try_set_property.call_count > 0

    @pytest.mark.asyncio
    async def test_configure_knox_failure(self, mock_adb_tool):
        """Test handling failures in Knox configuration."""
        mock_adb_tool.try_set_property.side_effect = Exception("Property error")

        result = await configure_knox_security(mock_adb_tool, "emulator-5554")

        # Should still complete even with failures
        assert "configured" in result
        assert "failed" in result


class TestSamsungAppsRegistry:
    """Test Samsung apps registry."""

    def test_launcher_in_registry(self):
        """Test that launcher is registered."""
        assert "launcher" in SAMSUNG_APPS
        app = SAMSUNG_APPS["launcher"]
        assert "package" in app
        assert "apk_paths" in app
        assert app["priority"] == 1

    def test_internet_in_registry(self):
        """Test that internet is registered."""
        assert "internet" in SAMSUNG_APPS
        app = SAMSUNG_APPS["internet"]
        assert app["priority"] == 1

    def test_all_apps_have_required_fields(self):
        """Test that all apps have required fields."""
        required_fields = {"package", "apk_name", "apk_paths", "component", "priority"}

        for app_key, app_info in SAMSUNG_APPS.items():
            for field in required_fields:
                assert field in app_info, f"Missing '{field}' in {app_key}"

    def test_priority_values(self):
        """Test that priority values are valid."""
        for app_key, app_info in SAMSUNG_APPS.items():
            priority = app_info.get("priority")
            assert priority in [1, 2, 3], f"Invalid priority for {app_key}"


class TestIntegration:
    """Integration tests."""

    @pytest.mark.asyncio
    async def test_full_workflow(self, mock_adb_tool, firmware_dir):
        """Test full installation workflow."""
        # Install apps
        app_result = await install_samsung_apps(
            mock_adb_tool,
            "emulator-5554",
            firmware_dir,
            skip_missing=True,
        )
        assert len(app_result["installed"]) > 0

        # Set defaults
        default_result = await set_samsung_defaults(mock_adb_tool, "emulator-5554")
        assert len(default_result["set"]) > 0

        # Configure Knox
        knox_result = await configure_knox_security(mock_adb_tool, "emulator-5554")
        assert len(knox_result["configured"]) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

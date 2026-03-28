"""Tests for optional Samsung UI APK install hook (no ADB)."""

import pytest

from core.fingerprint.samsung_ui_extras import apply_samsung_ui_extras
from core.tools.adb import ADBTool


@pytest.mark.asyncio
async def test_samsung_ui_extras_skips_non_samsung():
    adb = ADBTool(adb_path="/nonexistent/adb")
    r = await apply_samsung_ui_extras(adb, "fake", {"manufacturer": "Google", "brand": "google"})
    assert r["installed"] == []
    assert r["home_set"] is None
    assert r["warnings"] == []

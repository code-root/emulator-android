"""
Test firmware upload auto-detection and parsing.

Tests:
- SAMFW ZIP format detection
- Samsung TAR format detection
- Samsung TAR.MD5 format detection
- Filename parsing and metadata extraction
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parent.parent
_REPO = _BACKEND.parent
# Remove repo root from path to avoid conflicts
sys.path[:] = [p for p in sys.path if p and os.path.normpath(p) != os.path.normpath(str(_REPO))]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))
elif sys.path.index(str(_BACKEND)) != 0:
    sys.path.remove(str(_BACKEND))
    sys.path.insert(0, str(_BACKEND))

from core.firmware.samfw import resolve_firmware_meta  # noqa: E402


def test_parse_samfw_zip():
    """Test SAMFW ZIP format parsing."""
    filename = "SAMFW.COM_SM-G996B_EGY_G996BXXSJHZC2_fac.zip"
    meta = resolve_firmware_meta(filename)

    assert meta is not None
    assert meta["device_model"] == "SM-G996B"
    assert meta["sales_code"] == "EGY"
    assert meta["ap_version"] == "G996BXXSJHZC2"
    assert meta["source"] == "samfw"
    assert meta["package_variant"] == "fac"


def test_parse_samsung_tar_md5():
    """Test Samsung TAR.MD5 format parsing."""
    filename = "AP_S721BXXS3AYB8_S721BXXS3AYB8_MQB93088282_REV00_user_low_ship_MULTI_CERT_meta_OS14.tar.md5"
    meta = resolve_firmware_meta(filename)

    assert meta is not None
    assert meta["device_model"] == "SM-S721B"
    assert meta["ap_version"] == "S721BXXS3AYB8"
    assert meta["csc_version"] == "S721BXXS3AYB8"
    assert meta["source"] == "samsung_tar"
    assert meta["package_variant"] == "ap_tar.md5"


def test_parse_samsung_tar():
    """Test Samsung TAR format parsing."""
    filename = "AP_S921BXXU6GUB1_S921BOXM6GUB1_MQB93088282_REV00_user_low_ship.tar"
    meta = resolve_firmware_meta(filename)

    assert meta is not None
    assert meta["device_model"] == "SM-S921B"
    assert meta["ap_version"] == "S921BXXU6GUB1"
    assert meta["source"] == "samsung_tar"
    assert meta["package_variant"] == "ap_tar"


def test_parse_samsung_bundle_dir():
    """Test Samsung bundle directory format parsing."""
    dirname = "G996BXXSJHZA6_G996BOXMJHZA6_XSG"
    meta = resolve_firmware_meta(dirname)

    assert meta is not None
    assert meta["device_model"] == "SM-G996B"
    assert meta["ap_version"] == "G996BXXSJHZA6"
    assert meta["source"] == "samsung_bundle_dir"
    assert meta["sales_code"] == "XSG"


def test_parse_unsupported_format():
    """Test that unsupported formats return None."""
    filename = "random_firmware_file.bin"
    meta = resolve_firmware_meta(filename)
    assert meta is None


def test_parse_invalid_tar_format():
    """Test that invalid TAR filenames return None."""
    filename = "INVALID_AP_VERSION_TAR.tar"
    meta = resolve_firmware_meta(filename)
    # Should fall through to bundle dir check which will also fail
    assert meta is None

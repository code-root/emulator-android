"""اختبارات مواءمة فريموير Odin/SAMFW — مجلد G996BXXSJHZA6_G996BOXMJHZA6_XSG ودمج البصمة."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parent.parent
_REPO = _BACKEND.parent
# إزالة جذر المستودع من المقدمة إن وُجد — يمنع التعارض مع حزمة core أخرى
sys.path[:] = [p for p in sys.path if p and os.path.normpath(p) != os.path.normpath(str(_REPO))]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))
elif sys.path.index(str(_BACKEND)) != 0:
    sys.path.remove(str(_BACKEND))
    sys.path.insert(0, str(_BACKEND))

from core.firmware.samfw import (  # noqa: E402
    merge_firmware_into_fingerprint,
    parse_samsung_bundle_dirname,
    resolve_firmware_meta,
)
from core.fingerprint.generator import DEVICE_PROFILES  # noqa: E402

XSG_DIR = "G996BXXSJHZA6_G996BOXMJHZA6_XSG"

_G996B_PROFILE = next(p for p in DEVICE_PROFILES if p.get("device_model") == "SM-G996B")


def test_parse_xsg_bundle_dirname():
    m = parse_samsung_bundle_dirname(XSG_DIR)
    assert m is not None
    assert m["device_model"] == "SM-G996B"
    assert m["ap_version"] == "G996BXXSJHZA6"
    assert m["csc_version"] == "G996BOXMJHZA6"
    assert m["sales_code"] == "XSG"
    assert m["country"] == "SG"
    assert m["language"] == "en"


def test_resolve_firmware_meta_xsg():
    assert resolve_firmware_meta(XSG_DIR) is not None


def test_merge_xsg_updates_ap_csc_product_and_pda():
    fp = dict(_G996B_PROFILE)
    fp["imei"] = "359162051234567"
    fp["android_id"] = "deadbeefcafebabe"
    fp["mac_address"] = "02:00:00:00:00:01"
    meta = parse_samsung_bundle_dirname(XSG_DIR)
    assert meta is not None
    out = merge_firmware_into_fingerprint(fp, meta)
    assert out["ap_version"] == "G996BXXSJHZA6"
    assert out["csc_version"] == "G996BOXMJHZA6"
    assert out["country"] == "SG"
    assert out["language"] == "en"
    bf = out["build_fingerprint"]
    assert "o1sxxx" in bf
    assert "o1sxeea" not in bf
    assert bf.endswith("G996BXXSJHZA6:user/release-keys")


def test_merge_without_sales_product_mapping_only_patches_pda():
    """ZIP SAMFW لمنطقة أخرى: لا يوجد مفتاح منتج خاص — يبقى مقطع المنتج كما في القالب إن وُجد."""
    from core.firmware.samfw import parse_samfw_filename

    name = "SAMFW.COM_SM-G996B_EGY_G996BXXSJHZC2_fac.zip"
    meta = parse_samfw_filename(name)
    assert meta is not None
    fp = dict(_G996B_PROFILE)
    out = merge_firmware_into_fingerprint(fp, meta)
    assert out["ap_version"] == "G996BXXSJHZC2"
    assert "o1sxeea" in (out["build_fingerprint"] or "")

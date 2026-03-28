"""Tests for AP tar build.prop scanning (no real firmware required)."""

from pathlib import Path

from core.firmware.ap_buildprop import (
    _props_from_binary,
    find_ap_tar_path,
    merge_ap_tar_build_props_into_fp_data,
)


def test_props_from_binary_finds_fingerprint():
    blob = b"padding\x00" * 100 + (
        b"ro.build.fingerprint=samsung/o1sxxx/o1s:15/AP3A.999/TEST:user/release-keys\n"
        b"ro.build.version.release=15\x00"
    )
    p = _props_from_binary(blob)
    assert "ro.build.fingerprint" in p
    assert "samsung/" in p["ro.build.fingerprint"]
    assert p.get("ro.build.version.release") == "15"


def test_find_ap_tar_in_tmpdir(tmp_path: Path):
    d = tmp_path / "G996BXXSJHZA6_G996BOXMJHZA6_XSG"
    d.mkdir()
    ap = d / "AP_G996BXXSJHZA6_G996BXXSJHZA6_MQB1_user_low_ship_META_OS15.tar.md5"
    ap.write_bytes(b"not a real tar")
    found = find_ap_tar_path(d)
    assert found == ap


def test_find_ap_tar_file_path(tmp_path: Path):
    ap = tmp_path / "AP_G996BXXSJHZA6_G996BXXSJHZA6_MQB1_user_low_ship_META_OS15.tar.md5"
    ap.write_bytes(b"x")
    assert find_ap_tar_path(ap) == ap


def test_merge_ap_updates_fp_data_minimal(tmp_path: Path, monkeypatch):
    """If scan returns empty, fp_data unchanged."""
    ap = tmp_path / "AP_G996BXXSJHZA6_G996BXXSJHZA6_MQB1_x.tar.md5"
    ap.write_bytes(b"bad")
    fp = {"device_model": "SM-G996B", "extended": {}}
    warns = merge_ap_tar_build_props_into_fp_data(fp, ap)
    assert isinstance(warns, list)
    assert fp["device_model"] == "SM-G996B"

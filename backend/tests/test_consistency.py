"""Unit tests for core/fingerprint/consistency.py"""
import pytest

from core.fingerprint.consistency import (
    _luhn_ok,
    check_build_fingerprint_format,
    check_carrier_mcc_consistency,
    check_sensor_completeness,
    run_consistency_checks,
    validate_mcc_mnc,
)


# ---------------------------------------------------------------------------
# Luhn
# ---------------------------------------------------------------------------

class TestLuhn:
    def test_valid_imei(self):
        # Known valid IMEI (Luhn-correct)
        assert _luhn_ok("490154203237518") is True

    def test_invalid_imei(self):
        assert _luhn_ok("490154203237519") is False

    def test_wrong_length(self):
        assert _luhn_ok("12345") is False

    def test_non_digits(self):
        assert _luhn_ok("4901542032375AB") is False

    def test_empty(self):
        assert _luhn_ok("") is False


# ---------------------------------------------------------------------------
# Build fingerprint format
# ---------------------------------------------------------------------------

class TestBuildFingerprintFormat:
    def test_valid_samsung(self):
        ok, msg = check_build_fingerprint_format(
            "samsung/o1sxeea/o1s:15/AP3A.240905.015.A2/G996BXXSJHZC2:user/release-keys"
        )
        assert ok is True

    def test_valid_pixel(self):
        ok, msg = check_build_fingerprint_format(
            "google/oriole/oriole:12/SP2A.220505.002/8353555:user/release-keys"
        )
        assert ok is True

    def test_empty(self):
        ok, msg = check_build_fingerprint_format("")
        assert ok is False
        assert "empty" in msg

    def test_malformed(self):
        ok, msg = check_build_fingerprint_format("not/a/fingerprint")
        assert ok is False


# ---------------------------------------------------------------------------
# MCC/MNC validation
# ---------------------------------------------------------------------------

class TestMccMnc:
    def test_both_none(self):
        ok, msg = validate_mcc_mnc(None, None)
        assert ok is True
        assert msg == "skip"

    def test_valid(self):
        ok, _ = validate_mcc_mnc(310, 260)
        assert ok is True

    def test_mcc_too_low(self):
        ok, msg = validate_mcc_mnc(99, 1)
        assert ok is False
        assert "MCC" in msg

    def test_mnc_out_of_range(self):
        ok, msg = validate_mcc_mnc(310, 1000)
        assert ok is False

    def test_non_integer(self):
        ok, msg = validate_mcc_mnc("abc", "xyz")
        assert ok is False


# ---------------------------------------------------------------------------
# Carrier / MCC consistency
# ---------------------------------------------------------------------------

class TestCarrierMcc:
    def test_skip_when_no_carrier(self):
        ok, msg = check_carrier_mcc_consistency(None, "310")
        assert ok is True
        assert msg == "skip"

    def test_skip_when_no_mcc(self):
        ok, msg = check_carrier_mcc_consistency("Verizon", None)
        assert ok is True
        assert msg == "skip"

    def test_matching_carrier_mcc(self):
        ok, msg = check_carrier_mcc_consistency("Verizon", "310")
        assert ok is True

    def test_mismatched_carrier_mcc(self):
        # STC is Saudi (SA=420) but MCC 310 is US
        ok, msg = check_carrier_mcc_consistency("STC", "310")
        assert ok is False
        assert "SA" in msg or "US" in msg

    def test_multinational_carrier_skipped(self):
        # Vodafone is multinational — should not warn
        ok, msg = check_carrier_mcc_consistency("Vodafone", "234")
        assert ok is True

    def test_unknown_mcc_skipped(self):
        ok, msg = check_carrier_mcc_consistency("STC", "999")
        assert ok is True
        assert msg == "skip"


# ---------------------------------------------------------------------------
# Sensor completeness
# ---------------------------------------------------------------------------

class TestSensorCompleteness:
    def test_samsung_with_full_sensors(self):
        extended = {
            "sensors": {
                "accelerometer": {"noise_rms": 0.02},
                "gyroscope": {"noise_rms": 0.01},
                "magnetometer": {"noise_rms": 0.5},
                "light": {"lux_ambient": 100},
            }
        }
        ok, msg = check_sensor_completeness("samsung", "SM-G996B", extended)
        assert ok is True

    def test_samsung_missing_gyroscope(self):
        extended = {
            "sensors": {
                "accelerometer": {"noise_rms": 0.02},
                "magnetometer": {"noise_rms": 0.5},
            }
        }
        ok, msg = check_sensor_completeness("samsung", "SM-G996B", extended)
        assert ok is False
        assert "gyroscope" in msg

    def test_non_samsung_skipped(self):
        ok, msg = check_sensor_completeness("Google", "Pixel 6", {})
        assert ok is True
        assert msg == "skip"

    def test_no_extended(self):
        ok, msg = check_sensor_completeness("samsung", "SM-S918B", None)
        assert ok is False  # no sensors at all

    def test_skip_when_no_manufacturer(self):
        ok, msg = check_sensor_completeness(None, None, {})
        assert ok is True
        assert msg == "skip"


# ---------------------------------------------------------------------------
# run_consistency_checks integration
# ---------------------------------------------------------------------------

class TestRunConsistencyChecks:
    def test_clean_data_passes(self):
        result = run_consistency_checks({
            "imei": "490154203237518",
            "build_fingerprint": "samsung/o1sxeea/o1s:15/AP3A.240905.015.A2/G996BXXSJHZC2:user/release-keys",
            "mcc": 310,
            "mnc": 260,
            "device_model": "SM-G996B",
            "manufacturer": "samsung",
            "extended": {
                "sensors": {
                    "accelerometer": {},
                    "gyroscope": {},
                    "magnetometer": {},
                },
                "network": {"carrier_name": "Verizon", "mcc": "310", "mnc": "260"},
            },
        })
        assert result["ok"] is True
        assert result["errors"] == []

    def test_bad_imei_is_error(self):
        result = run_consistency_checks({"imei": "490154203237519"})
        assert result["ok"] is False
        assert any("imei" in e for e in result["errors"])

    def test_bad_mcc_is_error(self):
        result = run_consistency_checks({"mcc": 99, "mnc": 1})
        assert result["ok"] is False

    def test_carrier_mismatch_is_warning_not_error(self):
        result = run_consistency_checks({
            "manufacturer": "samsung",
            "device_model": "SM-G996B",
            "extended": {
                "network": {"carrier_name": "STC", "mcc": "310"},
                "sensors": {"accelerometer": {}, "gyroscope": {}, "magnetometer": {}},
            },
        })
        # carrier mismatch is a warning, not a hard error
        assert result["ok"] is True
        assert any("carrier" in w or "mismatch" in w for w in result["warnings"])

    def test_missing_sensors_is_warning(self):
        result = run_consistency_checks({
            "manufacturer": "samsung",
            "device_model": "SM-G996B",
            "extended": {"sensors": {}},
        })
        assert result["ok"] is True
        assert any("sensor" in w for w in result["warnings"])

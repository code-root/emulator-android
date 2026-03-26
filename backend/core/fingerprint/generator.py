import random
import string
from typing import Dict, Any, Optional

# Preset عند إنشاء جهاز: يضبط api_level + البصمة (مثل Samsung حقيقي)
DEVICE_CREATION_PRESETS: Dict[str, Dict[str, Any]] = {
    "samsung_sm_g996b_android15": {
        "label": "Samsung Galaxy S21+ 5G (SM-G996B) · Android 15 · AP/CSC كما طلبت",
        "device_model": "SM-G996B",
        "api_level": 35,
        "arch": "x86_64",
        "ram_mb": 4096,
        "cpu_cores": 4,
    },
    "samsung_sm_g996b_android15_arm64": {
        "label": "SM-G996B Android 15 (Apple Silicon / ARM64 host)",
        "device_model": "SM-G996B",
        "api_level": 35,
        "arch": "arm64-v8a",
        "ram_mb": 4096,
        "cpu_cores": 4,
    },
}

DEVICE_PROFILES = [
    {
        "device_model": "SM-G996B",
        "manufacturer": "samsung",
        "brand": "samsung",
        "device_codename": "o1s",
        "board": "lahaina",
        "hardware": "qcom",
        "build_fingerprint": "samsung/o1sxeea/o1s:15/AP3A.240905.015.A2/G996BXXSJHZC2:user/release-keys",
        "sdk_version": 35,
        "android_version": "15",
        "ap_version": "G996BXXSJHZC2",
        "csc_version": "G996BOXMJHZC2",
        "security_patch": "2025-01-01",
        "first_api_level": 30,
        "soc_model": "SM8350",
        "soc_manufacturer": "QTI",
        "cpu_abi_list_spoof": "arm64-v8a,armeabi-v7a,armeabi",
        "build_version_codename": "REL",
    },
    {
        "device_model": "Pixel 6",
        "manufacturer": "Google",
        "brand": "google",
        "device_codename": "oriole",
        "board": "oriole",
        "hardware": "oriole",
        "build_fingerprint": "google/oriole/oriole:12/SP2A.220505.002/8353555:user/release-keys",
        "sdk_version": 31,
        "android_version": "12",
    },
    {
        "device_model": "Pixel 6 Pro",
        "manufacturer": "Google",
        "brand": "google",
        "device_codename": "raven",
        "board": "raven",
        "hardware": "raven",
        "build_fingerprint": "google/raven/raven:12/SP2A.220505.002/8353555:user/release-keys",
        "sdk_version": 31,
        "android_version": "12",
    },
    {
        "device_model": "Pixel 7",
        "manufacturer": "Google",
        "brand": "google",
        "device_codename": "panther",
        "board": "panther",
        "hardware": "panther",
        "build_fingerprint": "google/panther/panther:13/TQ3A.230805.001/10316531:user/release-keys",
        "sdk_version": 33,
        "android_version": "13",
    },
    {
        "device_model": "Pixel 7 Pro",
        "manufacturer": "Google",
        "brand": "google",
        "device_codename": "cheetah",
        "board": "cheetah",
        "hardware": "cheetah",
        "build_fingerprint": "google/cheetah/cheetah:13/TQ3A.230805.001/10316531:user/release-keys",
        "sdk_version": 33,
        "android_version": "13",
    },
    {
        "device_model": "Pixel 8",
        "manufacturer": "Google",
        "brand": "google",
        "device_codename": "shiba",
        "board": "shiba",
        "hardware": "shiba",
        "build_fingerprint": "google/shiba/shiba:14/UP1A.231005.007/10754064:user/release-keys",
        "sdk_version": 34,
        "android_version": "14",
    },
    {
        "device_model": "SM-S901B",  # Samsung Galaxy S22
        "manufacturer": "Samsung",
        "brand": "samsung",
        "device_codename": "r0q",
        "board": "r0q",
        "hardware": "qcom",
        "build_fingerprint": "samsung/r0qxxx/r0q:12/SP1A.210812.016/S901BXXU4BVJ2:user/release-keys",
        "sdk_version": 31,
        "android_version": "12",
    },
    {
        "device_model": "SM-S908B",  # Samsung Galaxy S22 Ultra
        "manufacturer": "Samsung",
        "brand": "samsung",
        "device_codename": "b0q",
        "board": "b0q",
        "hardware": "qcom",
        "build_fingerprint": "samsung/b0qxxx/b0q:12/SP1A.210812.016/S908BXXU4BVJ2:user/release-keys",
        "sdk_version": 31,
        "android_version": "12",
    },
    {
        "device_model": "SM-S918B",  # Samsung Galaxy S23 Ultra
        "manufacturer": "Samsung",
        "brand": "samsung",
        "device_codename": "e3q",
        "board": "e3q",
        "hardware": "qcom",
        "build_fingerprint": "samsung/e3qxxx/e3q:13/TP1A.220624.014/S918BXXU4BVK1:user/release-keys",
        "sdk_version": 33,
        "android_version": "13",
    },
    {
        "device_model": "SM-A536B",  # Samsung Galaxy A53
        "manufacturer": "Samsung",
        "brand": "samsung",
        "device_codename": "a53x",
        "board": "a53x",
        "hardware": "exynos",
        "build_fingerprint": "samsung/a53xeea/a53x:12/SP1A.210812.016/A536BXXU5CWA1:user/release-keys",
        "sdk_version": 31,
        "android_version": "12",
    },
    {
        "device_model": "OnePlus 10 Pro",
        "manufacturer": "OnePlus",
        "brand": "OnePlus",
        "device_codename": "OP8859L1",
        "board": "waipio",
        "hardware": "qcom",
        "build_fingerprint": "OnePlus/OP8859L1/OP8859L1:12/SKQ1.211006.001/R.202205031454:user/release-keys",
        "sdk_version": 31,
        "android_version": "12",
    },
    {
        "device_model": "IN2023",  # OnePlus 9
        "manufacturer": "OnePlus",
        "brand": "OnePlus",
        "device_codename": "OnePlus9",
        "board": "lahaina",
        "hardware": "qcom",
        "build_fingerprint": "OnePlus/OnePlus9/OnePlus9:11/RKQ1.201217.002/2105072121:user/release-keys",
        "sdk_version": 30,
        "android_version": "11",
    },
    {
        "device_model": "Mi 11",
        "manufacturer": "Xiaomi",
        "brand": "Xiaomi",
        "device_codename": "venus",
        "board": "msmnile",
        "hardware": "qcom",
        "build_fingerprint": "Xiaomi/venus/venus:11/RKQ1.200826.002/venus-user 11:V12.5.3.0.RKBMIXM:user/release-keys",
        "sdk_version": 30,
        "android_version": "11",
    },
    {
        "device_model": "2201123G",  # Xiaomi 12
        "manufacturer": "Xiaomi",
        "brand": "Xiaomi",
        "device_codename": "cupid",
        "board": "taro",
        "hardware": "qcom",
        "build_fingerprint": "Xiaomi/cupid/cupid:12/SKQ1.211006.001/V13.0.2.0.SLCMIXM:user/release-keys",
        "sdk_version": 31,
        "android_version": "12",
    },
    {
        "device_model": "CPH2449",  # OPPO Find X5
        "manufacturer": "OPPO",
        "brand": "OPPO",
        "device_codename": "PFEM10",
        "board": "taro",
        "hardware": "qcom",
        "build_fingerprint": "OPPO/CPH2449/OP4F3FL1:12/SKQ1.211006.001/R.202206111027:user/release-keys",
        "sdk_version": 31,
        "android_version": "12",
    },
    {
        "device_model": "vivo X80 Pro",
        "manufacturer": "vivo",
        "brand": "vivo",
        "device_codename": "V2185A",
        "board": "taro",
        "hardware": "qcom",
        "build_fingerprint": "vivo/V2185A/V2185A:12/SKQ1.211006.001/compiler05161528:user/release-keys",
        "sdk_version": 31,
        "android_version": "12",
    },
    {
        "device_model": "Nokia G21",
        "manufacturer": "HMD Global",
        "brand": "Nokia",
        "device_codename": "GN18L",
        "board": "ums9230",
        "hardware": "ums9230",
        "build_fingerprint": "Nokia/Nokia_G21/GN18L:11/RP1A.201005.001/00WW_3_370:user/release-keys",
        "sdk_version": 30,
        "android_version": "11",
    },
    {
        "device_model": "Moto G Power (2022)",
        "manufacturer": "Motorola",
        "brand": "motorola",
        "device_codename": "hawaii",
        "board": "bengal",
        "hardware": "qcom",
        "build_fingerprint": "motorola/hawaii/hawaii:12/S3RE32.20-42-10/4a0d15:user/release-keys",
        "sdk_version": 31,
        "android_version": "12",
    },
    {
        "device_model": "LM-Q720",  # LG Stylo 6
        "manufacturer": "LGE",
        "brand": "lge",
        "device_codename": "stylo6",
        "board": "stylo6",
        "hardware": "qcom",
        "build_fingerprint": "lge/stylo6/stylo6:10/QKQ1.200628.002/200628:user/release-keys",
        "sdk_version": 29,
        "android_version": "10",
    },
    {
        "device_model": "CPH2339",  # Realme GT 2 Pro
        "manufacturer": "realme",
        "brand": "realme",
        "device_codename": "RE54E4L1",
        "board": "lahaina",
        "hardware": "qcom",
        "build_fingerprint": "realme/RMX3300/RE54E4L1:12/SKQ1.211006.001/R.202205161027:user/release-keys",
        "sdk_version": 31,
        "android_version": "12",
    },
    {
        "device_model": "M2101K6G",  # Redmi Note 10 Pro
        "manufacturer": "Xiaomi",
        "brand": "Redmi",
        "device_codename": "sweet",
        "board": "sm6150",
        "hardware": "qcom",
        "build_fingerprint": "Redmi/sweet_ru/sweet:11/RKQ1.200826.002/V12.5.6.0.RKOMIXM:user/release-keys",
        "sdk_version": 30,
        "android_version": "11",
    },
]

REGIONS = {
    "us": [
        (40.7128, -74.0060),   # New York
        (34.0522, -118.2437),  # Los Angeles
        (41.8781, -87.6298),   # Chicago
        (29.7604, -95.3698),   # Houston
        (33.4484, -112.0740),  # Phoenix
        (47.6062, -122.3321),  # Seattle
        (37.7749, -122.4194),  # San Francisco
        (25.7617, -80.1918),   # Miami
    ],
    "eu": [
        (51.5074, -0.1278),    # London
        (48.8566, 2.3522),     # Paris
        (52.5200, 13.4050),    # Berlin
        (41.9028, 12.4964),    # Rome
        (40.4168, -3.7038),    # Madrid
        (52.3702, 4.8952),     # Amsterdam
        (48.2082, 16.3738),    # Vienna
    ],
    "asia": [
        (35.6762, 139.6503),   # Tokyo
        (31.2304, 121.4737),   # Shanghai
        (22.3193, 114.1694),   # Hong Kong
        (1.3521, 103.8198),    # Singapore
        (37.5665, 126.9780),   # Seoul
        (13.7563, 100.5018),   # Bangkok
        (19.0760, 72.8777),    # Mumbai
    ],
    "global": None,
}

TIMEZONES_BY_REGION = {
    "us": ["America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles", "America/Phoenix"],
    "eu": ["Europe/London", "Europe/Paris", "Europe/Berlin", "Europe/Rome", "Europe/Madrid", "Europe/Amsterdam"],
    "asia": ["Asia/Tokyo", "Asia/Shanghai", "Asia/Hong_Kong", "Asia/Singapore", "Asia/Seoul", "Asia/Bangkok"],
    "global": ["America/New_York", "Europe/London", "Asia/Tokyo", "Asia/Shanghai", "Europe/Paris"],
}


class FingerprintGenerator:
    """Generate realistic Android device fingerprints."""

    def generate(self, device_model: Optional[str] = None) -> Dict[str, Any]:
        """Generate a complete fingerprint for a device."""
        if device_model:
            profile = next(
                (p for p in DEVICE_PROFILES if p["device_model"] == device_model),
                None,
            )
        else:
            profile = None

        if not profile:
            profile = random.choice(DEVICE_PROFILES)

        region = random.choice(["us", "eu", "asia"])
        lat, lng = self._random_location(region)
        network = self._random_network_type()
        lang, country = self._random_locale(region)

        tac_imei = "35916205" if profile.get("manufacturer", "").lower() == "samsung" else None
        out: Dict[str, Any] = {
            "imei": self._random_imei(tac_prefix=tac_imei),
            "android_id": self._random_android_id(),
            "mac_address": self._random_mac(),
            "device_model": profile["device_model"],
            "manufacturer": profile["manufacturer"],
            "brand": profile["brand"],
            "device_codename": profile["device_codename"],
            "build_fingerprint": profile["build_fingerprint"],
            "sdk_version": profile["sdk_version"],
            "android_version": profile["android_version"],
            "board": profile["board"],
            "hardware": profile["hardware"],
            "serial_number": self._random_serial(),
            "latitude": lat,
            "longitude": lng,
            "altitude": round(random.uniform(0, 500), 1),
            "network_type": network,
            "ip_address": self._random_private_ip(),
            "timezone": random.choice(TIMEZONES_BY_REGION.get(region, TIMEZONES_BY_REGION["global"])),
            "language": lang,
            "country": country,
            "ap_version": profile.get("ap_version"),
            "csc_version": profile.get("csc_version"),
        }
        for _k in (
            "security_patch",
            "first_api_level",
            "soc_model",
            "soc_manufacturer",
            "cpu_abi_list_spoof",
            "build_version_codename",
        ):
            if profile.get(_k) is not None:
                out[_k] = profile[_k]
        return out

    def _random_imei(self, tac_prefix: Optional[str] = None) -> str:
        """Generate a valid IMEI using Luhn algorithm."""
        tac_prefixes = [
            "35906305",  # Google
            "35916205",  # Samsung
            "86493702",  # Xiaomi
            "35299310",  # Apple (for mixing)
            "35407208",  # OnePlus
            "86769003",  # OPPO
        ]
        prefix = tac_prefix if tac_prefix else random.choice(tac_prefixes)
        # Generate remaining 6 digits (serial within TAC)
        partial = prefix + "".join([str(random.randint(0, 9)) for _ in range(6)])
        # Calculate Luhn check digit
        digits = [int(d) for d in partial]
        total = 0
        for i, d in enumerate(reversed(digits)):
            if i % 2 == 0:
                d *= 2
                if d > 9:
                    d -= 9
            total += d
        check = (10 - (total % 10)) % 10
        return partial + str(check)

    def _random_android_id(self) -> str:
        """Generate a random 16-character hex Android ID."""
        return "".join(random.choices("0123456789abcdef", k=16))

    def _random_mac(self) -> str:
        """Generate a locally administered unicast MAC address."""
        # Set bit 1 (locally administered) and clear bit 0 (unicast) of first byte
        first = random.randint(0, 63) * 4 + 2  # locally administered, unicast
        rest = [random.randint(0, 255) for _ in range(5)]
        mac_bytes = [first] + rest
        return ":".join(f"{b:02x}" for b in mac_bytes)

    def _random_serial(self) -> str:
        """Generate a random device serial number."""
        return "".join(random.choices(string.ascii_uppercase + string.digits, k=10))

    def _random_location(self, region: str = "global"):
        """Return realistic GPS coordinates for a region."""
        locations = REGIONS.get(region)
        if not locations:
            region = random.choice(["us", "eu", "asia"])
            locations = REGIONS[region]
        base_lat, base_lng = random.choice(locations)
        # Add small random offset (within ~10km)
        lat = base_lat + random.uniform(-0.05, 0.05)
        lng = base_lng + random.uniform(-0.05, 0.05)
        return round(lat, 6), round(lng, 6)

    def _random_network_type(self) -> str:
        """Return a random network type with weighted distribution."""
        return random.choices(
            ["WIFI", "LTE", "5G", "3G"],
            weights=[45, 35, 15, 5],
            k=1,
        )[0]

    def _random_private_ip(self) -> str:
        """Generate a random private IP address."""
        prefix = random.choice([
            f"192.168.{random.randint(0, 255)}",
            f"10.{random.randint(0, 255)}.{random.randint(0, 255)}",
            f"172.{random.randint(16, 31)}.{random.randint(0, 255)}",
        ])
        return f"{prefix}.{random.randint(2, 254)}"

    def _random_locale(self, region: str) -> tuple:
        """Return (language, country) pair for a region."""
        locales = {
            "us": [("en", "US")],
            "eu": [("en", "GB"), ("de", "DE"), ("fr", "FR"), ("es", "ES"), ("it", "IT"), ("nl", "NL")],
            "asia": [("ja", "JP"), ("zh", "CN"), ("zh", "HK"), ("en", "SG"), ("ko", "KR"), ("th", "TH")],
        }
        choices = locales.get(region, [("en", "US")])
        return random.choice(choices)

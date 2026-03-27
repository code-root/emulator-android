"""
Geographic database for fingerprint generation.

Provides:
  - Country list with major cities (lat/lng/alt)
  - Realistic mobile carrier info per country (MCC/MNC/carrier_name)
  - Plausible mobile IP ranges per carrier (CGNAT / private + realistic public prefix)
  - Samsung TAC codes per model (first 8 digits of IMEI)
  - Real Samsung MAC OUI prefixes

Usage:
    from core.fingerprint.geo_database import (
        pick_random_location,
        get_carrier_for_country,
        generate_realistic_ip,
        get_samsung_tac,
        random_samsung_mac,
        list_countries,
        COUNTRY_DB,
    )
"""
from __future__ import annotations

import random
import re
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Country → cities (lat, lng, altitude_m)
# ---------------------------------------------------------------------------

COUNTRY_DB: Dict[str, Dict[str, Any]] = {
    "SA": {
        "name": "Saudi Arabia",
        "cities": [
            ("Riyadh",    24.7136,  46.6753,  612),
            ("Jeddah",    21.3891,  39.8579,   17),
            ("Mecca",     21.3891,  39.8579,  277),
            ("Medina",    24.5247,  39.5692,  608),
            ("Dammam",    26.4207,  50.0888,    7),
            ("Khobar",    26.2172,  50.1972,    7),
            ("Abha",      18.2164,  42.5053, 2270),
        ],
        "carriers": [
            {"name": "STC",     "mcc": "420", "mnc": "01", "apn": "jawalnet.com.sa"},
            {"name": "Mobily",  "mcc": "420", "mnc": "03", "apn": "internet"},
            {"name": "Zain SA", "mcc": "420", "mnc": "04", "apn": "internet.sa"},
        ],
        "ip_prefixes": ["5.1.", "5.21.", "37.36.", "37.244.", "82.148.", "95.177."],
        "timezone": "Asia/Riyadh",
        "language": "ar",
        "country_iso": "sa",
    },
    "AE": {
        "name": "UAE",
        "cities": [
            ("Dubai",       25.2048, 55.2708,   10),
            ("Abu Dhabi",   24.4539, 54.3773,   27),
            ("Sharjah",     25.3462, 55.4209,   17),
            ("Ajman",       25.4052, 55.5136,   10),
        ],
        "carriers": [
            {"name": "Etisalat (e&)", "mcc": "424", "mnc": "02", "apn": "internet"},
            {"name": "du",            "mcc": "430", "mnc": "02", "apn": "internet"},
        ],
        "ip_prefixes": ["82.148.", "89.42.", "94.200.", "185.3.", "91.74."],
        "timezone": "Asia/Dubai",
        "language": "ar",
        "country_iso": "ae",
    },
    "EG": {
        "name": "Egypt",
        "cities": [
            ("Cairo",       30.0444, 31.2357,   23),
            ("Alexandria",  31.2001, 29.9187,   32),
            ("Giza",        30.0131, 31.2089,   23),
            ("Sharm El-Sheikh", 27.9158, 34.3300, 12),
        ],
        "carriers": [
            {"name": "Vodafone EG",  "mcc": "602", "mnc": "02", "apn": "internet.vodafone.net"},
            {"name": "Orange Egypt", "mcc": "602", "mnc": "01", "apn": "internet"},
            {"name": "Etisalat EG",  "mcc": "602", "mnc": "03", "apn": "internet"},
            {"name": "WE",           "mcc": "602", "mnc": "04", "apn": "internet.we.eg"},
        ],
        "ip_prefixes": ["41.67.", "41.128.", "41.196.", "197.33.", "197.37."],
        "timezone": "Africa/Cairo",
        "language": "ar",
        "country_iso": "eg",
    },
    "TR": {
        "name": "Turkey",
        "cities": [
            ("Istanbul",  41.0082, 28.9784,  40),
            ("Ankara",    39.9334, 32.8597, 938),
            ("Izmir",     38.4237, 27.1428,   4),
            ("Antalya",   36.8969, 30.7133,  56),
        ],
        "carriers": [
            {"name": "Turkcell",    "mcc": "286", "mnc": "01", "apn": "internet"},
            {"name": "Vodafone TR", "mcc": "286", "mnc": "02", "apn": "internet"},
            {"name": "TurkTelekom", "mcc": "286", "mnc": "04", "apn": "internet"},
        ],
        "ip_prefixes": ["37.130.", "78.162.", "85.111.", "88.255.", "176.42."],
        "timezone": "Europe/Istanbul",
        "language": "tr",
        "country_iso": "tr",
    },
    "DE": {
        "name": "Germany",
        "cities": [
            ("Berlin",    52.5200, 13.4050,  34),
            ("Munich",    48.1351, 11.5820, 519),
            ("Hamburg",   53.5753,  9.9925,  17),
            ("Frankfurt", 50.1109,  8.6821, 112),
        ],
        "carriers": [
            {"name": "Telekom DE",   "mcc": "262", "mnc": "01", "apn": "internet.t-mobile"},
            {"name": "Vodafone DE",  "mcc": "262", "mnc": "02", "apn": "web.vodafone.de"},
            {"name": "O2 Germany",   "mcc": "262", "mnc": "07", "apn": "internet"},
        ],
        "ip_prefixes": ["77.186.", "80.187.", "87.123.", "91.52.", "194.138."],
        "timezone": "Europe/Berlin",
        "language": "de",
        "country_iso": "de",
    },
    "FR": {
        "name": "France",
        "cities": [
            ("Paris",     48.8566,  2.3522,  35),
            ("Lyon",      45.7640,  4.8357, 173),
            ("Marseille", 43.2965,  5.3698,  28),
            ("Nice",      43.7102,  7.2620,  18),
        ],
        "carriers": [
            {"name": "Orange FR",   "mcc": "208", "mnc": "01", "apn": "orange.fr"},
            {"name": "SFR",         "mcc": "208", "mnc": "10", "apn": "sfr"},
            {"name": "Bouygues",    "mcc": "208", "mnc": "20", "apn": "mmsbouygtel.com"},
            {"name": "Free Mobile", "mcc": "208", "mnc": "15", "apn": "free"},
        ],
        "ip_prefixes": ["2.9.", "90.62.", "90.63.", "176.149.", "195.186."],
        "timezone": "Europe/Paris",
        "language": "fr",
        "country_iso": "fr",
    },
    "GB": {
        "name": "United Kingdom",
        "cities": [
            ("London",     51.5074,  -0.1278,   8),
            ("Manchester", 53.4808,  -2.2426,  38),
            ("Birmingham", 52.4862,  -1.8904, 141),
            ("Leeds",      53.8008,  -1.5491,  57),
        ],
        "carriers": [
            {"name": "EE",          "mcc": "234", "mnc": "30", "apn": "everywhere"},
            {"name": "O2 UK",       "mcc": "234", "mnc": "10", "apn": "mobile.o2.co.uk"},
            {"name": "Vodafone UK", "mcc": "234", "mnc": "15", "apn": "wap.vodafone.co.uk"},
            {"name": "Three UK",    "mcc": "234", "mnc": "20", "apn": "three.co.uk"},
        ],
        "ip_prefixes": ["82.71.", "86.164.", "92.40.", "109.152.", "212.22."],
        "timezone": "Europe/London",
        "language": "en",
        "country_iso": "gb",
    },
    "US": {
        "name": "United States",
        "cities": [
            ("New York",    40.7128,  -74.0060,  10),
            ("Los Angeles", 34.0522, -118.2437,  89),
            ("Chicago",     41.8781,  -87.6298, 182),
            ("Houston",     29.7604,  -95.3698,  15),
            ("Miami",       25.7617,  -80.1918,   4),
            ("Dallas",      32.7767,  -96.7970, 139),
        ],
        "carriers": [
            {"name": "Verizon",  "mcc": "311", "mnc": "480", "apn": "vzwinternet"},
            {"name": "AT&T",     "mcc": "310", "mnc": "410", "apn": "phone"},
            {"name": "T-Mobile", "mcc": "310", "mnc": "260", "apn": "fast.t-mobile.com"},
        ],
        "ip_prefixes": ["73.162.", "75.130.", "98.207.", "108.82.", "174.192."],
        "timezone": "America/New_York",
        "language": "en",
        "country_iso": "us",
    },
    "IN": {
        "name": "India",
        "cities": [
            ("Mumbai",    19.0760, 72.8777,  14),
            ("Delhi",     28.7041, 77.1025, 216),
            ("Bengaluru", 12.9716, 77.5946, 920),
            ("Hyderabad", 17.3850, 78.4867, 542),
            ("Chennai",   13.0827, 80.2707,   9),
        ],
        "carriers": [
            {"name": "Jio",          "mcc": "405", "mnc": "840", "apn": "jionet"},
            {"name": "Airtel",       "mcc": "404", "mnc": "10",  "apn": "airtelgprs.com"},
            {"name": "Vi (Vodafone)", "mcc": "404", "mnc": "20", "apn": "www"},
        ],
        "ip_prefixes": ["14.139.", "59.144.", "103.36.", "106.76.", "117.221."],
        "timezone": "Asia/Kolkata",
        "language": "hi",
        "country_iso": "in",
    },
    "SG": {
        "name": "Singapore",
        "cities": [
            ("Singapore",  1.3521, 103.8198, 15),
            ("Jurong West", 1.3404, 103.7090, 10),
        ],
        "carriers": [
            {"name": "Singtel",  "mcc": "525", "mnc": "05", "apn": "internet"},
            {"name": "StarHub",  "mcc": "525", "mnc": "05", "apn": "shwapint"},
            {"name": "M1",       "mcc": "525", "mnc": "03", "apn": "sunsurf"},
        ],
        "ip_prefixes": ["1.179.", "116.88.", "122.11.", "175.136.", "203.116."],
        "timezone": "Asia/Singapore",
        "language": "en",
        "country_iso": "sg",
    },
    "JP": {
        "name": "Japan",
        "cities": [
            ("Tokyo",    35.6762, 139.6503, 40),
            ("Osaka",    34.6937, 135.5023, 15),
            ("Nagoya",   35.1815, 136.9066, 52),
            ("Sapporo",  43.0642, 141.3469, 17),
        ],
        "carriers": [
            {"name": "NTT Docomo", "mcc": "440", "mnc": "10", "apn": "spmode.ne.jp"},
            {"name": "SoftBank",   "mcc": "440", "mnc": "20", "apn": "plus.4g"},
            {"name": "au (KDDI)",  "mcc": "440", "mnc": "50", "apn": "uno.au-net.ne.jp"},
        ],
        "ip_prefixes": ["1.33.", "49.96.", "103.77.", "111.87.", "153.242."],
        "timezone": "Asia/Tokyo",
        "language": "ja",
        "country_iso": "jp",
    },
    "KR": {
        "name": "South Korea",
        "cities": [
            ("Seoul",    37.5665, 126.9780, 38),
            ("Busan",    35.1796, 129.0756, 69),
            ("Incheon",  37.4563, 126.7052, 32),
        ],
        "carriers": [
            {"name": "SK Telecom",  "mcc": "450", "mnc": "05", "apn": "internet"},
            {"name": "KT",          "mcc": "450", "mnc": "08", "apn": "lte.ktfwing.com"},
            {"name": "LG Uplus",    "mcc": "450", "mnc": "06", "apn": "internet"},
        ],
        "ip_prefixes": ["1.209.", "14.52.", "61.43.", "106.101.", "175.223."],
        "timezone": "Asia/Seoul",
        "language": "ko",
        "country_iso": "kr",
    },
    "RU": {
        "name": "Russia",
        "cities": [
            ("Moscow",          55.7558,  37.6173, 156),
            ("Saint Petersburg", 59.9311,  30.3609,   6),
            ("Novosibirsk",     54.9885,  82.9207, 168),
            ("Yekaterinburg",   56.8389,  60.6057, 281),
        ],
        "carriers": [
            {"name": "MTS",     "mcc": "250", "mnc": "01", "apn": "internet.mts.ru"},
            {"name": "Beeline", "mcc": "250", "mnc": "99", "apn": "internet.beeline.ru"},
            {"name": "MegaFon", "mcc": "250", "mnc": "02", "apn": "internet"},
        ],
        "ip_prefixes": ["5.18.", "31.173.", "46.29.", "77.108.", "195.14."],
        "timezone": "Europe/Moscow",
        "language": "ru",
        "country_iso": "ru",
    },
    "BR": {
        "name": "Brazil",
        "cities": [
            ("São Paulo",   -23.5505, -46.6333,  760),
            ("Rio de Janeiro", -22.9068, -43.1729, 10),
            ("Brasília",    -15.7942, -47.8822, 1071),
            ("Salvador",    -12.9777, -38.5016,   20),
        ],
        "carriers": [
            {"name": "Vivo",  "mcc": "724", "mnc": "06", "apn": "zap.vivo.com.br"},
            {"name": "TIM",   "mcc": "724", "mnc": "02", "apn": "tim.br"},
            {"name": "Claro", "mcc": "724", "mnc": "05", "apn": "claro.com.br"},
        ],
        "ip_prefixes": ["177.8.", "177.71.", "177.136.", "189.0.", "189.100."],
        "timezone": "America/Sao_Paulo",
        "language": "pt",
        "country_iso": "br",
    },
    "CN": {
        "name": "China",
        "cities": [
            ("Beijing",   39.9042, 116.4074,   44),
            ("Shanghai",  31.2304, 121.4737,    5),
            ("Guangzhou", 23.1291, 113.2644,   21),
            ("Shenzhen",  22.5431, 114.0579,    3),
            ("Chengdu",   30.5728, 104.0668,  506),
        ],
        "carriers": [
            {"name": "China Mobile",  "mcc": "460", "mnc": "00", "apn": "cmnet"},
            {"name": "China Unicom",  "mcc": "460", "mnc": "01", "apn": "3gnet"},
            {"name": "China Telecom", "mcc": "460", "mnc": "03", "apn": "ctnet"},
        ],
        "ip_prefixes": ["36.152.", "42.120.", "61.135.", "110.242.", "182.61."],
        "timezone": "Asia/Shanghai",
        "language": "zh",
        "country_iso": "cn",
    },
    "AU": {
        "name": "Australia",
        "cities": [
            ("Sydney",     -33.8688, 151.2093,  58),
            ("Melbourne",  -37.8136, 144.9631,  25),
            ("Brisbane",   -27.4698, 153.0251,  27),
            ("Perth",      -31.9505, 115.8605,  25),
        ],
        "carriers": [
            {"name": "Telstra",   "mcc": "505", "mnc": "01", "apn": "telstra.internet"},
            {"name": "Optus",     "mcc": "505", "mnc": "02", "apn": "yesinternet"},
            {"name": "Vodafone AU","mcc": "505", "mnc": "03", "apn": "internet"},
        ],
        "ip_prefixes": ["1.128.", "49.176.", "101.160.", "122.107.", "175.32."],
        "timezone": "Australia/Sydney",
        "language": "en",
        "country_iso": "au",
    },
    "PK": {
        "name": "Pakistan",
        "cities": [
            ("Karachi",   24.8607, 67.0011,   8),
            ("Lahore",    31.5204, 74.3587, 217),
            ("Islamabad", 33.7294, 73.0931, 508),
        ],
        "carriers": [
            {"name": "Jazz",     "mcc": "410", "mnc": "01", "apn": "jazz"},
            {"name": "Telenor PK", "mcc": "410", "mnc": "06", "apn": "internet"},
            {"name": "Ufone",    "mcc": "410", "mnc": "03", "apn": "ufone.internet"},
            {"name": "Zong",     "mcc": "410", "mnc": "08", "apn": "zong"},
        ],
        "ip_prefixes": ["39.32.", "39.37.", "103.14.", "119.155.", "182.182."],
        "timezone": "Asia/Karachi",
        "language": "ur",
        "country_iso": "pk",
    },
    "NG": {
        "name": "Nigeria",
        "cities": [
            ("Lagos",    6.5244, 3.3792, 41),
            ("Abuja",    9.0765, 7.3986, 472),
            ("Kano",    12.0022, 8.5920, 474),
        ],
        "carriers": [
            {"name": "MTN Nigeria",   "mcc": "621", "mnc": "30", "apn": "internet"},
            {"name": "Airtel Nigeria", "mcc": "621", "mnc": "20", "apn": "internet"},
            {"name": "Glo Nigeria",   "mcc": "621", "mnc": "50", "apn": "glosecure"},
        ],
        "ip_prefixes": ["41.184.", "41.203.", "154.68.", "196.3.", "197.210."],
        "timezone": "Africa/Lagos",
        "language": "en",
        "country_iso": "ng",
    },
    "MA": {
        "name": "Morocco",
        "cities": [
            ("Casablanca", 33.5731, -7.5898,  50),
            ("Rabat",      34.0209, -6.8416, 100),
            ("Marrakesh",  31.6295, -7.9811, 466),
        ],
        "carriers": [
            {"name": "Maroc Telecom", "mcc": "604", "mnc": "01", "apn": "internet.iam.ma"},
            {"name": "Orange MA",     "mcc": "604", "mnc": "00", "apn": "internet"},
            {"name": "Inwi",          "mcc": "604", "mnc": "05", "apn": "internet.inwi.ma"},
        ],
        "ip_prefixes": ["41.92.", "105.158.", "196.200.", "212.100."],
        "timezone": "Africa/Casablanca",
        "language": "ar",
        "country_iso": "ma",
    },
    "ID": {
        "name": "Indonesia",
        "cities": [
            ("Jakarta",   -6.2088, 106.8456,   8),
            ("Surabaya",  -7.2575, 112.7521,   7),
            ("Bandung",   -6.9175, 107.6191, 768),
        ],
        "carriers": [
            {"name": "Telkomsel",    "mcc": "510", "mnc": "10", "apn": "internet"},
            {"name": "XL Axiata",    "mcc": "510", "mnc": "11", "apn": "internet"},
            {"name": "Indosat",      "mcc": "510", "mnc": "01", "apn": "indosatgprs"},
        ],
        "ip_prefixes": ["36.66.", "36.82.", "103.53.", "125.160.", "182.0."],
        "timezone": "Asia/Jakarta",
        "language": "id",
        "country_iso": "id",
    },
}


# ---------------------------------------------------------------------------
# Samsung TAC codes (IMEI Type Allocation Code — first 8 digits)
# Source: public GSMA TAC database entries for Samsung flagship models
# ---------------------------------------------------------------------------

SAMSUNG_TAC_DB: Dict[str, List[str]] = {
    "SM-G996B": [
        "35272111", "35272112", "35272113", "35272114",
        "35272115", "35272116", "35272117", "35272118",
    ],
    "SM-G996U": [
        "35272121", "35272122", "35272123", "35272124",
    ],
    "SM-S918B": [
        "35657616", "35657617", "35657618", "35657619",
        "35657620", "35657621",
    ],
    "SM-S918U": [
        "35657625", "35657626", "35657627",
    ],
    "SM-A536B": [
        "35254024", "35254025", "35254026", "35254027",
    ],
    "SM-A525F": [
        "35259923", "35259924", "35259925",
    ],
    "SM-G991B": [
        "35272008", "35272009", "35272010", "35272011",
    ],
    "SM-N986B": [
        "35093511", "35093512", "35093513",
    ],
    # Generic Samsung fallback
    "_default": [
        "35272111", "35272112", "35272113", "35272114",
        "35093511", "35093512", "35093513",
        "35657616", "35657617",
    ],
}

# Samsung OUI prefixes (Organizationally Unique Identifier for MAC)
# These are real Samsung OUIs (first 3 bytes = 6 hex chars)
SAMSUNG_OUI = [
    "00:00:F0", "00:02:78", "00:07:AB", "00:09:18", "00:0D:E5",
    "00:12:47", "00:12:FB", "00:15:99", "00:15:B9", "00:16:32",
    "00:17:C9", "00:17:D5", "00:18:AF", "00:1A:8A", "00:1B:98",
    "00:1C:43", "00:1D:25", "00:1D:F6", "00:1E:E1", "00:1E:E2",
    "00:21:19", "00:23:39", "00:24:54", "00:24:91", "00:26:37",
    "00:26:5F", "08:08:C2", "08:37:3D", "0C:14:20", "0C:71:5D",
    "10:1D:C0", "18:3D:A2", "18:89:5B", "1C:5A:3E", "20:13:E0",
    "24:4B:03", "28:27:BF", "2C:AE:2B", "30:96:FB", "34:14:5F",
    "38:2D:D1", "3C:8B:FE", "40:0E:85", "44:78:3E", "48:44:F7",
    "4C:3C:16", "50:01:BB", "50:32:75", "54:92:BE", "58:CB:52",
    "5C:2E:59", "60:6B:BD", "64:77:91", "68:9A:87", "6C:2F:2C",
    "70:F9:27", "74:45:8A", "78:1F:DB", "7C:1C:4E", "80:65:6D",
    "84:38:38", "84:A4:66", "88:32:9B", "8C:C8:4B", "90:18:7C",
    "94:76:B7", "98:39:8E", "9C:02:98", "A0:07:98", "A4:EB:D3",
    "A8:9C:ED", "AC:36:13", "B0:72:BF", "B4:62:93", "B8:BC:1B",
    "BC:72:B1", "C0:BD:D1", "C4:57:6E", "C8:A8:23", "CC:07:AB",
    "D0:22:BE", "D0:DF:C7", "D4:87:D8", "D8:C4:6A", "DC:71:96",
    "E0:CB:4E", "E4:40:E2", "E4:92:FB", "E8:50:8B", "EC:9B:F3",
    "F0:25:B7", "F4:42:8F", "F8:04:2E", "FC:A1:3E",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_countries() -> List[Dict[str, str]]:
    """Return sorted list of {code, name} for UI dropdowns."""
    return sorted(
        [{"code": k, "name": v["name"]} for k, v in COUNTRY_DB.items()],
        key=lambda x: x["name"],
    )


def pick_random_location(country_code: Optional[str] = None) -> Dict[str, Any]:
    """
    Return a random city from the given country (or any country if None).

    Returns dict with: country_code, country_name, city, latitude, longitude,
    altitude, timezone, language, country_iso.
    """
    if country_code and country_code.upper() in COUNTRY_DB:
        code = country_code.upper()
    else:
        code = random.choice(list(COUNTRY_DB.keys()))

    entry = COUNTRY_DB[code]
    city_row = random.choice(entry["cities"])
    city_name, lat, lng, alt = city_row

    # Add small random offset so two devices in the same city have different coords
    lat += random.uniform(-0.05, 0.05)
    lng += random.uniform(-0.05, 0.05)
    lat = round(lat, 6)
    lng = round(lng, 6)

    return {
        "country_code":  code,
        "country_name":  entry["name"],
        "city":          city_name,
        "latitude":      lat,
        "longitude":     lng,
        "altitude":      float(alt + random.randint(-10, 10)),
        "timezone":      entry["timezone"],
        "language":      entry["language"],
        "country_iso":   entry["country_iso"],
    }


def get_carrier_for_country(country_code: Optional[str] = None) -> Dict[str, Any]:
    """Return a random carrier dict for the given country."""
    if country_code and country_code.upper() in COUNTRY_DB:
        code = country_code.upper()
    else:
        code = random.choice(list(COUNTRY_DB.keys()))
    entry = COUNTRY_DB[code]
    return {**random.choice(entry["carriers"]), "country_code": code}


def generate_realistic_ip(country_code: Optional[str] = None) -> str:
    """
    Generate a plausible mobile ISP IP for a given country.
    Uses real IP prefixes observed for mobile carriers in that country.
    """
    if country_code and country_code.upper() in COUNTRY_DB:
        code = country_code.upper()
    else:
        code = random.choice(list(COUNTRY_DB.keys()))
    prefixes = COUNTRY_DB[code]["ip_prefixes"]
    prefix = random.choice(prefixes)
    # Generate remaining octets avoiding .0 and .255
    parts = prefix.rstrip(".").split(".")
    while len(parts) < 4:
        parts.append(str(random.randint(1, 254)))
    return ".".join(parts[:4])


def _luhn_complete(partial: str) -> str:
    """Given the first 14 digits of an IMEI, compute and append the check digit."""
    total = 0
    for i, c in enumerate(reversed(partial)):
        n = int(c)
        if i % 2 == 0:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    check = (10 - (total % 10)) % 10
    return partial + str(check)


def generate_imei(device_model: Optional[str] = None) -> str:
    """
    Generate a valid IMEI using a real Samsung TAC for the given model.
    Returns a 15-digit Luhn-valid IMEI string.
    """
    model_key = (device_model or "").upper().replace(" ", "-")
    tac_list = SAMSUNG_TAC_DB.get(model_key) or SAMSUNG_TAC_DB.get("_default", [])
    tac = random.choice(tac_list)
    # Fill remaining 6 digits (serial number within TAC)
    serial_6 = "".join([str(random.randint(0, 9)) for _ in range(6)])
    partial_14 = tac + serial_6
    return _luhn_complete(partial_14)


def random_samsung_mac() -> str:
    """Generate a random MAC address using a real Samsung OUI."""
    oui = random.choice(SAMSUNG_OUI)
    last_3 = ":".join(f"{random.randint(0, 255):02X}" for _ in range(3))
    return f"{oui}:{last_3}"


def random_samsung_serial(device_model: Optional[str] = None) -> str:
    """
    Generate a realistic Samsung serial number.

    Samsung serial format: R[region_code][2 digits][model_suffix][4 alphanumeric]
    Examples: RF1D23ABCDEF, R38MA012345X
    """
    regions = ["F1", "28", "38", "3C", "X9", "W7", "58"]
    alphanum = "ABCDEFGHJKLMNPQRSTUVWXYZ0123456789"
    region = random.choice(regions)
    digits = "".join([str(random.randint(0, 9)) for _ in range(2)])
    suffix = "".join(random.choices(alphanum, k=6))
    return f"R{region}{digits}{suffix}"


def generate_android_id() -> str:
    """Generate a realistic Android ID (16 hex chars, lower-case)."""
    return "".join(f"{random.randint(0, 255):02x}" for _ in range(8))


def build_fingerprint_for_model(
    device_model: str,
    ap_version: str,
    android_version: str,
    build_id: str,
) -> str:
    """
    Build a realistic Samsung build fingerprint string.
    Format: brand/product/device:version/build_id/incremental:type/tags
    """
    model_segments = {
        "SM-G996B": ("samsung", "o1sxeea",  "o1s"),
        "SM-G991B": ("samsung", "o1sxeea",  "o1s"),
        "SM-S918B": ("samsung", "dm3qxeea", "dm3q"),
        "SM-A536B": ("samsung", "a53xeea",  "a53x"),
        "SM-A525F": ("samsung", "a52xeea",  "a52x"),
        "SM-N986B": ("samsung", "c2q",       "c2q"),
    }
    brand, product, device = model_segments.get(
        device_model.upper(), ("samsung", "o1sxeea", "o1s")
    )
    return (
        f"{brand}/{product}/{device}:{android_version}/{build_id}"
        f"/{ap_version}:user/release-keys"
    )

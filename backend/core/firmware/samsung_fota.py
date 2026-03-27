"""
Samsung FOTA firmware version fetcher.

Public Samsung FOTA server API for fetching latest firmware versions:
https://fota-cloud-dn.ospserver.net/firmware/{csc}/{model}/version.xml

Response format:
<versioninfo>
  <firmware>
    <version>
      <latest>AP_VERSION/CSC_VERSION/CP_VERSION/PDA_VERSION</latest>
    </version>
  </firmware>
</versioninfo>

Example: S921BXXU3CXJ1/S921BOXM3CXJ1/S921BXXU3CXJ1/S921BXXU3CXJ1
Index:   [0]AP          [1]CSC          [2]CP           [3]PDA
"""

import httpx
import xml.etree.ElementTree as ET
from functools import lru_cache
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

FOTA_URL = "https://fota-cloud-dn.ospserver.net/firmware/{csc}/{model}/version.xml"
HTTP_TIMEOUT = 10.0


@lru_cache(maxsize=128)
def _fetch_cached(model: str, csc: str) -> Optional[str]:
    """Cached HTTP fetch from Samsung FOTA server."""
    url = FOTA_URL.format(csc=csc.upper(), model=model.upper())
    try:
        response = httpx.get(url, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        return response.text
    except Exception as e:
        logger.warning(f"Samsung FOTA fetch failed for {model}/{csc}: {e}")
        return None


async def fetch_latest_firmware(model: str, csc: str) -> Dict[str, Any]:
    """
    Fetch latest Samsung firmware versions for a device + region.

    Args:
        model: Samsung model code (e.g. "SM-S921B")
        csc: Customer Service Center code / region (e.g. "XEU", "KSA", "UAE")

    Returns:
        {
            "model": "SM-S921B",
            "csc": "XEU",
            "ap_version": "S921BXXU3CXJ1",
            "csc_version": "S921BXEF3CXJ1",
            "full_version": "S921BXXU3CXJ1/S921BXEF3CXJ1/S921BXXU3CXJ1/S921BXXU3CXJ1"
        }

    Raises:
        ValueError: If firmware not found or parsing fails
        httpx.HTTPError: If Samsung server returns error
    """
    xml_text = _fetch_cached(model, csc)
    if not xml_text:
        raise ValueError(f"No firmware found for {model}/{csc}")

    try:
        root = ET.fromstring(xml_text)
        latest_elem = root.find(".//latest")
        if latest_elem is None or not latest_elem.text:
            raise ValueError(f"No <latest> tag found in response")

        latest = latest_elem.text.strip()
        parts = latest.split("/")

        ap_version = parts[0] if len(parts) > 0 else None
        csc_version = parts[1] if len(parts) > 1 else None

        return {
            "model": model.upper(),
            "csc": csc.upper(),
            "ap_version": ap_version,
            "csc_version": csc_version,
            "full_version": latest,
        }
    except ET.ParseError as e:
        logger.error(f"Failed to parse Samsung FOTA XML for {model}/{csc}: {e}")
        raise ValueError(f"Invalid XML response from Samsung FOTA server: {e}")


def clear_cache():
    """Clear the firmware fetch cache (useful for testing)."""
    _fetch_cached.cache_clear()

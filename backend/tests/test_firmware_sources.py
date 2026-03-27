"""
Test firmware download sources connectivity and availability.

Tests:
- DNS resolution for each source
- HTTP connectivity
- URL template formatting
- Response codes
"""

import asyncio
import httpx
import logging
from pathlib import Path
import sys

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s'
)
logger = logging.getLogger(__name__)


async def test_dns_resolution(domain: str) -> bool:
    """Test if domain can be resolved."""
    try:
        async with httpx.AsyncClient() as client:
            # Try to connect with a HEAD request to test DNS only
            await client.head(f"https://{domain}", timeout=5)
            return True
    except httpx.ConnectError as e:
        logger.warning(f"  ❌ DNS/Connection failed: {e}")
        return False
    except httpx.TimeoutException:
        logger.warning(f"  ❌ Timeout")
        return False
    except Exception as e:
        logger.warning(f"  ❌ Error: {e}")
        return False


async def test_source_connectivity(source_dict: dict) -> dict:
    """Test a single firmware source."""
    source_name = source_dict["name"]
    url_template = source_dict["url_template"]
    manual_only = source_dict.get("manual_only", False)
    description = source_dict.get("description", "")

    logger.info(f"\n🔍 Testing: {source_name}")
    logger.info(f"   Description: {description}")
    logger.info(f"   URL Template: {url_template[:70]}...")

    if manual_only:
        logger.info(f"   ℹ️  Manual only (user must provide URL)")
        return {
            "name": source_name,
            "status": "MANUAL_ONLY",
            "description": description,
            "manual_only": True
        }

    # Extract domain from URL
    domain = url_template.split("://")[1].split("/")[0]
    logger.info(f"   Domain: {domain}")

    # Test DNS resolution
    logger.info("   → Testing DNS resolution...")
    dns_ok = await test_dns_resolution(domain)

    if not dns_ok:
        logger.error(f"   ⚠️  DNS failed for {domain}")
        return {
            "name": source_name,
            "status": "DNS_FAILED",
            "domain": domain,
            "dns_working": False,
            "http_working": False
        }

    logger.info(f"   ✅ DNS resolved successfully")

    # Test HTTP connectivity with sample URL
    logger.info("   → Testing HTTP connectivity...")
    try:
        # Create a sample URL
        sample_url = url_template.format(
            csc="XEU",
            model="SM-G996B",
            ap_version="G996BXXU6GUB1"
        )
        logger.info(f"   Sample URL: {sample_url[:70]}...")

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.head(sample_url, allow_redirects=True)

            logger.info(f"   HTTP Status: {response.status_code}")

            if response.status_code in (200, 206):
                logger.info(f"   ✅ HTTP connectivity OK")
                return {
                    "name": source_name,
                    "status": "OK",
                    "domain": domain,
                    "dns_working": True,
                    "http_working": True,
                    "status_code": response.status_code
                }
            elif response.status_code in (403, 404, 405):
                # These are expected - means server is reachable
                logger.info(f"   ✅ Server reachable (status {response.status_code})")
                return {
                    "name": source_name,
                    "status": "REACHABLE",
                    "domain": domain,
                    "dns_working": True,
                    "http_working": True,
                    "status_code": response.status_code,
                    "note": f"Server returned {response.status_code} - may need actual firmware file"
                }
            else:
                logger.warning(f"   ⚠️  Unexpected status: {response.status_code}")
                return {
                    "name": source_name,
                    "status": "UNEXPECTED_STATUS",
                    "domain": domain,
                    "dns_working": True,
                    "http_working": False,
                    "status_code": response.status_code
                }

    except httpx.TimeoutException:
        logger.warning(f"   ⚠️  Request timeout")
        return {
            "name": source_name,
            "status": "TIMEOUT",
            "domain": domain,
            "dns_working": True,
            "http_working": False,
            "note": "Server not responding (may be blocked in your region)"
        }
    except httpx.ConnectError as e:
        logger.warning(f"   ⚠️  Connection error: {e}")
        return {
            "name": source_name,
            "status": "CONNECT_FAILED",
            "domain": domain,
            "dns_working": True,
            "http_working": False
        }
    except Exception as e:
        logger.error(f"   ❌ Error: {e}")
        return {
            "name": source_name,
            "status": "ERROR",
            "domain": domain,
            "dns_working": True,
            "http_working": False,
            "error": str(e)
        }


async def test_all_sources():
    """Test all firmware sources."""
    logger.info("=" * 70)
    logger.info("FIRMWARE SOURCE CONNECTIVITY TEST")
    logger.info("=" * 70)

    results = []

    for source in settings.FIRMWARE_SOURCES:
        result = await test_source_connectivity(source)
        results.append(result)

    # Summary
    logger.info("\n" + "=" * 70)
    logger.info("TEST SUMMARY")
    logger.info("=" * 70)

    working_sources = [r for r in results if r.get("http_working")]
    manual_sources = [r for r in results if r.get("manual_only")]
    failed_sources = [r for r in results if not r.get("http_working") and not r.get("manual_only")]

    logger.info(f"\n✅ Auto-Download Sources (working): {len(working_sources)}/{len([r for r in results if not r.get('manual_only')])}")
    for r in working_sources:
        logger.info(f"   • {r['name']} ({r.get('domain', 'N/A')})")

    if manual_sources:
        logger.info(f"\n📝 Manual Sources (user-provided URLs): {len(manual_sources)}")
        for r in manual_sources:
            logger.info(f"   • {r['name']}")
            if r.get('description'):
                logger.info(f"     {r['description']}")

    if failed_sources:
        logger.info(f"\n⚠️  Failed/Unreachable Sources: {len(failed_sources)}")
        for r in failed_sources:
            status = r.get("status", "UNKNOWN")
            note = r.get("note", "")
            logger.info(f"   • {r['name']} ({r.get('domain', 'N/A')}) - {status}")
            if note:
                logger.info(f"     Note: {note}")

    # Detailed report
    logger.info("\n" + "-" * 70)
    logger.info("DETAILED RESULTS")
    logger.info("-" * 70)

    for r in results:
        logger.info(f"\n📦 {r['name']}")
        if r.get("manual_only"):
            logger.info(f"   Type: Manual (user provides URL)")
            if r.get("description"):
                logger.info(f"   Description: {r['description']}")
        else:
            logger.info(f"   Domain: {r.get('domain', 'N/A')}")
            logger.info(f"   DNS: {'✅ OK' if r.get('dns_working') else '❌ FAILED'}")
            logger.info(f"   HTTP: {'✅ OK' if r.get('http_working') else '❌ FAILED'}")
            if r.get("status_code"):
                logger.info(f"   Status Code: {r['status_code']}")
            if r.get("note"):
                logger.info(f"   Note: {r['note']}")
            if r.get("error"):
                logger.info(f"   Error: {r['error']}")

    # Recommendations
    logger.info("\n" + "=" * 70)
    logger.info("RECOMMENDATIONS")
    logger.info("=" * 70)

    if not working_sources:
        logger.error("\n❌ NO WORKING SOURCES FOUND!")
        logger.info("\nPossible causes:")
        logger.info("  1. Your network is blocking firmware downloads")
        logger.info("  2. VPN/Proxy required for your region")
        logger.info("  3. All mirror sites are currently down")
        logger.info("\nNext steps:")
        logger.info("  1. Check your internet connection")
        logger.info("  2. Try with VPN enabled")
        logger.info("  3. Use Custom URL option to provide manual download link")
    else:
        logger.info(f"\n✅ {len(working_sources)} source(s) are available!")
        logger.info("The firmware downloader will automatically use these sources.")
        logger.info("If one fails, it will try the next one automatically.")

    return {
        "total": len(results),
        "working": len(working_sources),
        "failed": len(failed_sources),
        "results": results
    }


if __name__ == "__main__":
    result = asyncio.run(test_all_sources())

    # Exit code based on results
    exit_code = 0 if result["working"] > 0 else 1
    sys.exit(exit_code)

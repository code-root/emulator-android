# Firmware Download Sources Configuration

## Overview

The firmware downloader uses a **multi-source fallback strategy** to download Samsung firmware reliably, even when primary servers are blocked or unavailable.

## Download Priority

1. **Primary Source**: Samsung CDN (`cfs4.samsungmobile.com`)
2. **User Fallbacks**: Any sources you configure (optional)
3. **Custom URL**: Manual URL you provide in the UI

## Configuring Fallback Sources

### Method 1: Environment Variable (Recommended)

Set `FIRMWARE_FALLBACK_SOURCES` with semicolon-separated URLs:

```bash
export FIRMWARE_FALLBACK_SOURCES="https://samfw.com/firmware/{model}/{csc}/{ap_version};https://your-server.local/firmware/{model}/{csc}/{ap_version}.zip"
```

Or in `.env.local`:

```env
FIRMWARE_FALLBACK_SOURCES=https://samfw.com/firmware/{model}/{csc}/{ap_version};https://your-server.local/{model}_{csc}_{ap_version}.zip
```

### URL Template Variables

Replace these placeholders in your URLs:

- `{model}` — Device model (e.g., `SM-G996B`)
- `{csc}` — Region code (e.g., `XEU` for Europe)
- `{ap_version}` — Firmware version (e.g., `G996BXXU6GUB1`)

### Examples

**SamFW.com:**
```
https://www.samfw.com/firmware/{model}/{csc}/{ap_version}
```

**Your Private Server:**
```
https://firmware.company.local/samsung/{model}-{csc}-{ap_version}.zip
```

**S3 Bucket:**
```
https://s3.amazonaws.com/firmware-backups/{model}/{csc}/{ap_version}.zip
```

**HTTP Archive:**
```
http://archive.local:8080/samsung-fw/{model}_{csc}_{ap_version}.zip
```

## Testing Sources

Run the connectivity test:

```bash
cd backend
source .venv/bin/activate
python tests/test_firmware_sources.py
```

This will:
- ✅ Check DNS resolution for each source
- ✅ Test HTTP connectivity
- ✅ Report which sources are reachable
- ✅ Provide troubleshooting recommendations

## How the Downloader Behaves

```
User starts download (SM-G996B / XEU)
  ↓
Fetch metadata from Samsung FOTA
  ↓ (get ap_version = "G996BXXU6GUB1")
Try Samsung CDN: https://cfs4.samsungmobile.com/XEU/SM-G996B/G996BXXU6GUB1.zip
  ├─ ✅ Success? → Download, verify hashes, save to DB
  ├─ ❌ HTTP error? → Try next source
  ├─ ❌ Timeout? → Try next source
  └─ ❌ DNS failed? → Try next source
      ↓
Try Fallback 1: https://samfw.com/firmware/SM-G996B/XEU/G996BXXU6GUB1
  ├─ ✅ Success? → Download, verify, save
  └─ ❌ Fail? → Try next
      ↓
Try Fallback 2, 3, etc...
      ↓
User Custom URL (if provided): https://custom-server.com/...
  ├─ ✅ Success? → Download, verify, save
  └─ ❌ Fail? → Mark as failed
```

**Result stored in database:**
```
FirmwareEntry {
  device_model: "SM-G996B"
  sales_code: "XEU"
  ap_version: "G996BXXU6GUB1"
  source: "auto"  (successfully downloaded)
  local_path: "/path/to/firmware/SAMFW.COM_SM-G996B_XEU_G996BXXU6GUB1_fac.zip"
  sha256_hash: "abc123..."
  created_at: 2026-03-27 22:10:00
}
```

## Network Issues?

### Issue: DNS Failed
**Error:** `[Errno 8] nodename nor servname provided, or not known`

**Solutions:**
1. Check internet connection: `ping 8.8.8.8`
2. Try with VPN enabled
3. Add private firmware server via `FIRMWARE_FALLBACK_SOURCES`
4. Use "Custom URL" in UI with direct link

### Issue: All Sources Blocked
**Cause:** ISP/network blocking all firmware downloads

**Solutions:**
1. Run your own firmware mirror on private server
2. Set up proxy/VPN tunnel
3. Use "Custom URL" with allowed server

### Issue: Slow Downloads
**Solution:** Add faster mirror to `FIRMWARE_FALLBACK_SOURCES`:
```
FIRMWARE_FALLBACK_SOURCES=https://fast-mirror.local/firmware/{model}/{csc}/{ap_version}
```

## API Endpoints

### Get Available Sources
```bash
GET /api/firmware/sources
```

Response:
```json
{
  "sources": [
    {"name": "Samsung CDN", "description": "Official Samsung FOTA server"}
  ],
  "fallback_sources_count": 2,
  "description": "Tries primary sources, then 2 user-configured fallback(s), then custom URL if provided",
  "how_to_add_fallback": "Set FIRMWARE_FALLBACK_SOURCES environment variable with semicolon-separated URLs"
}
```

### Start Download with Custom URL
```bash
POST /api/firmware/download
{
  "model": "SM-G996B",
  "csc": "XEU",
  "url": "https://samfw.com/firmware/SM-G996B/XEU/G996BXXU6GUB1"
}
```

## Database Persistence

All successfully downloaded firmware is **automatically saved to database**:

```sql
SELECT device_model, sales_code, ap_version, source, size_bytes, created_at
FROM firmware_entries
WHERE source = 'auto';
```

This means:
- ✅ Survives application restart
- ✅ Browsable in "Firmware Catalog"
- ✅ Can be deleted/managed via UI
- ✅ Can be manually added via "Add Firmware Entry" form

## Best Practices

1. **Always verify hashes**: MD5 + SHA256 are checked on-the-fly
2. **Use HTTPS**: Prefer encrypted sources over HTTP
3. **Test before deploying**: Run `test_firmware_sources.py`
4. **Monitor logs**: Check which source succeeded
5. **Cache successfully downloaded**: Use database entries

## Troubleshooting Checklist

- [ ] Run: `python tests/test_firmware_sources.py`
- [ ] Check logs for which source succeeded
- [ ] Verify Samsung FOTA returns metadata: `curl https://fota-cloud-dn.ospserver.net/firmware/XEU/SM-G996B/version.xml`
- [ ] Test primary CDN: `curl -I https://cfs4.samsungmobile.com/XEU/SM-G996B/G996BXXU6GUB1.zip`
- [ ] Add fallback if primary blocked: `export FIRMWARE_FALLBACK_SOURCES=...`
- [ ] Use Custom URL as last resort in UI

## Examples

### Simple Setup (Samsung CDN only)
```bash
# Default configuration, no changes needed
python -m uvicorn main:app
```

### Private Firmware Server
```bash
export FIRMWARE_FALLBACK_SOURCES="https://firmware.company.local/samsung/{model}/{csc}/{ap_version}.zip"
python -m uvicorn main:app
```

### Multiple Mirrors (Redundancy)
```bash
export FIRMWARE_FALLBACK_SOURCES="https://mirror1.local/{model}/{csc}/{ap_version}.zip;https://mirror2.local/{model}-{csc}-{ap_version}.zip;https://s3.company.com/firmware/{model}/{csc}/{ap_version}"
python -m uvicorn main:app
```

### Testing in Blocked Region
```bash
# Test which sources work
python tests/test_firmware_sources.py

# Add working fallback
export FIRMWARE_FALLBACK_SOURCES="https://working-mirror.com/firmware/{model}/{csc}/{ap_version}"
python -m uvicorn main:app
```

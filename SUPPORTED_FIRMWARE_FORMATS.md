# Supported Firmware Formats

## Overview

The firmware system now supports **multiple Samsung firmware formats** used across Odin, SamFW, and direct downloads.

## Supported Formats

### 1. SAMFW ZIP Format ✅

**Pattern:** `SAMFW.COM_{Model}_{CSC}_{APVersion}_{Variant}.zip`

**Example:**
```
SAMFW.COM_SM-G996B_EGY_G996BXXSJHZC2_fac.zip
SAMFW.COM_SM-S921B_XEU_S921BXXU6GUB1_fac.zip
```

**Extracted:**
- Model: `SM-G996B`
- CSC (Region): `EGY`
- AP Version: `G996BXXSJHZC2`
- Variant: `fac` (factory)

### 2. Samsung TAR Format ✅ (NEW)

**Pattern:** `{COMPONENT}_{APVersion}_{CSCVersion}_{Metadata}.{tar|tar.md5}`

**Example:**
```
AP_S721BXXS3AYB8_S721BXXS3AYB8_MQB93088282_REV00_user_low_ship_MULTI_CERT_meta_OS14.tar.md5
AP_S921BXXU6GUB1_S921BOXM6GUB1_MQB93088282_REV00_user_low_ship_MULTI_CERT_meta_OS14.tar
BL_R900XXU1AUGA_R900OYM1AUGA_MQB12345678_REV00.tar.md5
CSC_S721BXXS3AYB8_S721BXXS3AYB8_MQB93088282_REV00.tar.md5
```

**Components:**
- `AP` - Application Processor (main firmware)
- `BL` - Bootloader
- `CSC` - Country/region specific configuration
- `MODEM` - Modem firmware

**Extracted:**
- Component: `AP`, `BL`, `CSC`, or `MODEM`
- AP Version: `S721BXXS3AYB8`
- CSC Version: `S721BXXS3AYB8`
- Device Model (auto): `SM-S721B` (from S721B prefix)

### 3. Samsung Bundle Directory Format ✅

**Pattern:** `{APVersion}_{CSCVersion}_{SALES}`

**Example:**
```
G996BXXSJHZA6_G996BOXMJHZA6_XSG/
S921BXXU6GUB1_S921BOXM6GUB1_XEU/
```

**Note:** Directories are automatically detected and indexed.

## Mixed Format Support

You can have **all formats in the same directory**:

```
firmware/
├── SAMFW.COM_SM-G996B_EGY_G996BXXSJHZC2_fac.zip
├── AP_S721BXXS3AYB8_S721BXXS3AYB8_MQB93088282_REV00_user_low_ship_MULTI_CERT_meta_OS14.tar.md5
├── AP_S921BXXU6GUB1_S921BOXM6GUB1_MQB93088282_REV00_user_low_ship.tar
└── G996BXXSJHZA6_G996BOXMJHZA6_XSG/
```

The system will **automatically detect and index all formats**.

## Database Integration

All formats are stored in the same database:

```sql
SELECT device_model, ap_version, source, package_variant, filename
FROM firmware_entries;
```

| device_model | ap_version  | source       | package_variant | filename |
|--|--|--|--|--|
| SM-G996B | G996BXXSJHZC2 | samfw | fac | SAMFW.COM_SM-G996B_EGY_G996BXXSJHZC2_fac.zip |
| SM-S721B | S721BXXS3AYB8 | samsung_tar | ap_tar.md5 | AP_S721BXXS3AYB8_... |
| SM-S921B | S921BXXU6GUB1 | samsung_tar | ap_tar | AP_S921BXXU6GUB1_... |

## UI Handling

### Firmware List
All formats displayed together in "Available Firmware" section:
- Shows model, AP version, CSC version
- Shows source (SAMFW, Samsung TAR, etc.)
- Shows file type (ZIP, TAR, TAR.MD5)

### Manual Entry
Can manually add firmware via "Add Firmware Entry" form:
- Specify model, CSC, AP version
- Any source type supported
- Notes field for reference

### Sync
"Sync Disk" button scans all formats and imports new ones to database.

## Format Detection Algorithm

1. **Check SAMFW ZIP**: `SAMFW.COM_*.zip` pattern
2. **Check Samsung TAR**: `{AP|BL|CSC|MODEM}_*.(tar|tar.md5)` pattern
3. **Check Bundle DIR**: `*_*_{SALES}` directory pattern
4. **Fallback**: Manual entry required

## Example: Using TAR Format

### Download TAR Firmware
1. Place file: `firmware/AP_S721BXXS3AYB8_S721BXXS3AYB8_MQB93088282.tar.md5`
2. Click "Sync Disk" in UI
3. Entry auto-indexed in database
4. Available in "Firmware Catalog"

### Extract Model from Filename
```
AP_S721BXXS3AYB8_...
   ↓
   S721B (pattern: {Letter}{Digits}{Letter})
   ↓
   SM-S721B ✅
```

### Create Fingerprint Entry
If you want to use this firmware for a device:

1. Create device (e.g., SM-S721B)
2. Go to Fingerprint tab
3. Select "SM-S721B" from model dropdown
4. System will find matching firmware entries
5. Select or manually enter AP version
6. Apply fingerprint

## Troubleshooting

### Format Not Recognized
**Error:** File not showing in "Available Firmware"

**Solution:**
1. Check filename pattern matches examples above
2. Use underscores (not spaces) in filename
3. Use uppercase for model/CSC/version
4. Try manual entry in "Add Firmware Entry" form

### Model Not Detected
**Error:** `device_model` is `null` in database

**For TAR formats:** AP version must start with model prefix
- `S721BXXS3AYB8` → `S721B` → `SM-S721B` ✅
- `ABC123XYZ` → Cannot extract model ❌

**Solution:** Manually enter model in "Add Firmware Entry"

### CSC Version Mismatch
Both AP and CSC versions are extracted from TAR filename. If they don't match, that's valid (e.g., different regional CSC).

## Best Practices

1. **Keep original filenames**: Don't rename firmware files
2. **Use consistent format**: Pick ZIP or TAR, don't mix per device
3. **Verify checksums**: TAR.MD5 includes checksum in filename
4. **Organize by model**: Create subdirectories like `firmware/S721/`, `firmware/S921/`
5. **Document source**: Use notes field when adding entries manually

## Adding New Format Support

To add support for a new firmware format:

1. Add regex pattern to `samfw.py`
2. Implement `parse_{format}_filename()` function
3. Add to `resolve_firmware_meta()` fallback chain
4. Update `iter_firmware_packages()` glob patterns
5. Test with `python tests/test_firmware_sources.py`

Example:
```python
# samfw.py
_MY_FORMAT = re.compile(r"^pattern_here$")

def parse_my_format_filename(filename):
    # Extract and return dict
    return {...}

# samfw.py - resolve_firmware_meta()
return (
    parse_samfw_filename(basename)
    or parse_samsung_tar_filename(basename)
    or parse_my_format_filename(basename)  # Add here
    or parse_samsung_bundle_dirname(basename)
)

# scan.py - iter_firmware_packages()
for pattern in ["*.custom", "*.ext"]:  # Add here
    for p in sorted(scan_root.glob(pattern)):
        meta = parse_my_format_filename(p.name)
        # ... same processing
```

"""
أقصى ما يمكن محاكاته على AOSP/Google APIs عبر setprop / settings:
تقليد طبقات product / vendor / system / csc / samsung كما على أجهزة حقيقية قدر الإمكان.
لا يضيف نواة Samsung أو One UI — فقط ما يقبله النظام بعد adb root عادة.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


def is_samsung_fingerprint(fp: Dict[str, Any]) -> bool:
    m = (fp.get("manufacturer") or "").lower()
    b = (fp.get("brand") or "").lower()
    return m == "samsung" or b == "samsung"


def infer_sales_code_from_csc(csc_version: Optional[str]) -> str:
    """
    من سلسلة مثل G996BOXMJHZC2 يُستخرج غالباً كود CSC ثلاثي (مثل OXM).
    """
    if not csc_version or len(csc_version) < 8:
        return "OXM"
    # بعد بادئة G996B (5 أحرف) غالباً يأتي CSC
    if re.match(r"^G996B", csc_version, re.I):
        return csc_version[5:8].upper()
    return "OXM"


def merge_profile_defaults_for_apply(fp: Dict[str, Any]) -> Dict[str, Any]:
    """يملأ حقولاً تقنية تُستخدم فقط عند التطبيق (ليست كلها في جدول DB)."""
    out = dict(fp)
    model = (out.get("device_model") or "").upper()
    if model != "SM-G996B":
        return out
    defaults: Dict[str, Any] = {
        "security_patch": "2025-01-01",
        "first_api_level": 30,
        "soc_model": "SM8350",
        "soc_manufacturer": "QTI",
        "cpu_abi_list_spoof": "arm64-v8a,armeabi-v7a,armeabi",
        "build_version_codename": "REL",
    }
    for k, v in defaults.items():
        if out.get(k) is None:
            out[k] = v
    return out


def build_extended_samsung_prop_map(fp: Dict[str, Any]) -> Dict[str, str]:
    """
    خريطة موسّعة لخصائص Samsung / تقسيمات AOSP الحديثة.
    القيم تُستمد من fp؛ أي مفتاح فارغ يُتخطّى لاحقاً.
    """
    if not is_samsung_fingerprint(fp):
        return {}

    model = fp.get("device_model") or ""
    manu = (fp.get("manufacturer") or "samsung").lower()
    brand = (fp.get("brand") or "samsung").lower()
    codename = fp.get("device_codename") or "o1s"
    # يطابق شكل البصمة samsung/o1sxeea/o1s على أجهزة S21+ EEA
    product_name = "o1sxeea" if codename == "o1s" else f"{codename}xeea"
    board = fp.get("board") or "lahaina"
    hw = fp.get("hardware") or "qcom"
    fingerprint = fp.get("build_fingerprint") or ""
    release = str(fp.get("android_version") or "15")
    sdk = str(fp.get("sdk_version") or "35")
    ap = fp.get("ap_version") or ""
    csc = fp.get("csc_version") or ""
    serial = fp.get("serial_number") or ""
    patch = str(fp.get("security_patch") or "2025-01-01")
    first_api = str(fp.get("first_api_level") or "30")
    soc = fp.get("soc_model") or "SM8350"
    soc_m = fp.get("soc_manufacturer") or "QTI"
    sales = infer_sales_code_from_csc(csc)
    codename_rel = fp.get("build_version_codename") or "REL"

    # بلد من fp إن وُجد
    country = (fp.get("country") or "DE").upper()
    country_iso2 = country if len(country) == 2 else "DE"

    props: Dict[str, str] = {}

    def add(k: str, v: Any):
        if v is not None and str(v).strip() != "":
            props[k] = str(v)

    # ——— product (متعدد الأقسام كما على أجهزة حقيقية) ———
    add("ro.product.model", model)
    add("ro.product.brand", brand)
    add("ro.product.manufacturer", manu)
    add("ro.product.device", codename)
    add("ro.product.name", product_name)
    add("ro.product.board", board)

    for partition in ("system", "system_ext", "vendor", "odm", "product"):
        add(f"ro.product.{partition}.model", model)
        add(f"ro.product.{partition}.brand", brand)
        add(f"ro.product.{partition}.manufacturer", manu)
        add(f"ro.product.{partition}.device", codename)
        add(f"ro.product.{partition}.name", product_name)

    add("ro.product.cpu.abi", "arm64-v8a")
    abilist = fp.get("cpu_abi_list_spoof")
    if abilist:
        add("ro.product.cpu.abilist", abilist)
        add("ro.product.cpu.abilist32", "armeabi-v7a,armeabi")
        add("ro.product.cpu.abilist64", "arm64-v8a")
        add("ro.vendor.product.cpu.abilist", abilist)

    add("ro.hardware", hw)
    add("ro.soc.model", soc)
    add("ro.soc.manufacturer", soc_m)
    add("ro.boot.hardware", hw)
    add("ro.boot.hardware.platform", "lahaina")

    # ——— build / إصدارات ———
    add("ro.build.version.release", release)
    add("ro.build.version.sdk", sdk)
    add("ro.build.version.release_or_codename", release)
    add("ro.build.version.codename", codename_rel)
    add("ro.build.version.security_patch", patch)
    add("ro.build.version.base_os", "")
    add("ro.product.first_api_level", first_api)
    add("ro.board.first_api_level", first_api)
    add("ro.build.characteristics", "default")
    add("ro.treble.enabled", "true")

    if fingerprint:
        for key in (
            "ro.build.fingerprint",
            "ro.bootimage.build.fingerprint",
            "ro.system.build.fingerprint",
            "ro.system_ext.build.fingerprint",
            "ro.vendor.build.fingerprint",
            "ro.odm.build.fingerprint",
            "ro.product.build.fingerprint",
        ):
            add(key, fingerprint)

    add("ro.vendor.build.security_patch", patch)
    add("ro.system.build.security_patch", patch)

    if ap:
        add("ro.build.display.id", ap)
        add("ro.build.version.incremental", ap)
        add("ro.bootloader", ap)
        add("ro.build.PDA", ap)
        add("ro.build.changelist", ap)
        add("gsm.version.baseband", ap)

    if csc:
        add("ro.csc.version", csc)
        add("ro.csc.version_string", csc)
        add("ro.omc.version", csc)
        if not ap:
            add("ro.build.changelist", csc)

    if serial:
        add("ro.serialno", serial)
        add("ro.boot.serialno", serial)

    # ——— CSC / OMC ———
    add("ro.csc.sales_code", sales)
    add("ro.csc.country_code", country_iso2)
    add("ro.csc.countryiso_code", country_iso2)
    add("ro.omc.enable", "true")
    add("ro.omc.multi_csc", "OXM,EUX,EUY,BTU")
    add("ro.config.ringtone", "Galaxy_Bells.ogg")
    add("ro.config.notification_sound", "Spaceline.ogg")

    # ——— مساحة اسم samsung (تُقرأ من تطبيقات Samsung أحياناً) ———
    add("ro.samsung.model", model)
    add("ro.samsung.device", codename)
    add("ro.samsung.build.version", release)

    # Knox / أمان ظاهري (قيم شائعة على أجهزة مبيعات)
    add("ro.boot.warranty_bit", "1")
    add("ro.boot.flash.locked", "1")
    add("ro.securestorage.support", "true")
    add("ro.config.tima", "1")
    add("ro.config.knox", "1")

    # محاولة تقليد Adreno (قد تفشل على x86 AVD — لا ضرر إن رُفضت)
    add("ro.hardware.egl", "adreno")
    add("ro.opengles.version", "196610")

    return props


def samsung_surface_settings_commands(fp: Dict[str, Any]) -> List[str]:
    """
    أوامر shell لـ settings put — آمنة نسبياً لتحسين «مظهر» الجهاز بعد الإعداد.
    """
    if not is_samsung_fingerprint(fp):
        return []
    model = fp.get("device_model") or "Samsung device"
    return [
        "settings put global device_provisioned 1",
        "settings put secure user_setup_complete 1",
        f"settings put secure bluetooth_name {model}",
        "settings put global stay_on_while_plugged_in 3",
    ]

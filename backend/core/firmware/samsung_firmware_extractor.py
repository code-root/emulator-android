"""
Samsung Firmware Extractor

استخراج ROM الحقيقي من firmware Samsung .tar.md5 files
يستند على Scamsung methodology
"""

import tarfile
import hashlib
from pathlib import Path
from typing import Optional, Dict, List
from dataclasses import dataclass


@dataclass
class FirmwareComponent:
    """مكون firmware Samsung"""
    name: str
    file_path: Path
    size_bytes: int
    md5_hash: str


class SamsungFirmwareExtractor:
    """استخراج ROM و firmware من Samsung"""

    # الملفات المدعومة في firmware
    SUPPORTED_COMPONENTS = {
        "AP": "Application Processor (system.img)",
        "BL": "BootLoader (kernel)",
        "CSC": "Consumer Software Customization (vendor.img)",
        "MODEM": "Cellular Modem Firmware",
        "PARAM": "Parameter block",
        "BOOT": "Boot image",
        "HIDDEN": "Hidden files",
    }

    def __init__(self, firmware_dir: Path):
        """
        تهيئة المستخرج

        Args:
            firmware_dir: مجلد firmware Samsung
        """
        self.firmware_dir = Path(firmware_dir)
        self.extracted_files: Dict[str, FirmwareComponent] = {}

    async def extract_all(self) -> Dict[str, FirmwareComponent]:
        """استخراج جميع مكونات firmware"""
        if not self.firmware_dir.exists():
            return {}

        # ابحث عن ملفات .tar.md5
        tar_files = list(self.firmware_dir.glob("*.tar.md5"))

        for tar_file in tar_files:
            await self._extract_tar(tar_file)

        return self.extracted_files

    async def _extract_tar(self, tar_path: Path) -> bool:
        """استخراج ملف tar.md5"""
        try:
            with tarfile.open(tar_path, "r:*") as tar:
                # اقرأ قائمة الملفات
                members = tar.getmembers()

                print(f"\n📦 Extracting: {tar_path.name}")
                print(f"   Files in archive: {len(members)}")

                for member in members:
                    # استخرج الملفات المهمة فقط
                    if member.isfile():
                        component_type = self._identify_component(member.name)

                        if component_type:
                            # احفظ معلومات المكون
                            extracted_path = self.firmware_dir / member.name

                            # استخرج الملف
                            tar.extract(member, self.firmware_dir)

                            # احسب MD5
                            md5 = self._calculate_md5(extracted_path)

                            component = FirmwareComponent(
                                name=component_type,
                                file_path=extracted_path,
                                size_bytes=member.size,
                                md5_hash=md5
                            )

                            self.extracted_files[component_type] = component

                            print(f"   ✓ {component_type:10} {member.size / (1024 ** 3):.2f} GB")

                return True

        except Exception as e:
            print(f"❌ Error extracting {tar_path.name}: {e}")
            return False

    def _identify_component(self, filename: str) -> Optional[str]:
        """تحديد نوع المكون من الاسم"""
        filename_upper = filename.upper()

        # ملفات AP (system)
        if filename_upper.startswith("AP_"):
            return "AP"

        # ملفات BL (bootloader)
        elif filename_upper.startswith("BL_"):
            return "BL"

        # ملفات CSC (vendor/firmware)
        elif filename_upper.startswith("CSC_") or "CSC" in filename_upper:
            return "CSC"

        # ملفات MODEM
        elif filename_upper.startswith("MODEM_"):
            return "MODEM"

        return None

    def _calculate_md5(self, file_path: Path) -> str:
        """حساب MD5 للملف"""
        md5_hash = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                md5_hash.update(chunk)
        return md5_hash.hexdigest()

    async def extract_build_prop(self, ap_component: Optional[FirmwareComponent] = None):
        """استخراج build.prop من AP"""
        ap = ap_component or self.extracted_files.get("AP")

        if not ap:
            print("❌ AP component not found")
            return None

        try:
            # AP عادة يحتوي على system.tar أو system.img
            ap_path = ap.file_path

            # حاول فتح كـ tar
            if ap_path.suffix in [".tar", ".md5"]:
                with tarfile.open(ap_path, "r:*") as tar:
                    # ابحث عن build.prop
                    for member in tar.getmembers():
                        if member.name.endswith("build.prop"):
                            # استخرج build.prop
                            extracted = tar.extractfile(member)
                            if extracted:
                                build_prop_content = extracted.read().decode("utf-8", errors="ignore")
                                return self._parse_build_prop(build_prop_content)

        except Exception as e:
            print(f"❌ Error extracting build.prop: {e}")

        return None

    def _parse_build_prop(self, content: str) -> Dict[str, str]:
        """تحليل build.prop"""
        props = {}
        for line in content.splitlines():
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                key, _, value = line.partition("=")
                props[key.strip()] = value.strip()
        return props

    async def extract_one_ui_config(self) -> Dict:
        """استخراج إعدادات One UI من vendor"""
        csc = self.extracted_files.get("CSC")

        if not csc:
            return {}

        one_ui_config = {
            "version": None,
            "theme": None,
            "features": [],
            "services": []
        }

        try:
            # OneUI version من vendor properties
            build_prop = await self.extract_build_prop()
            if build_prop:
                oneui_version = build_prop.get("ro.build.version.oneui")
                if oneui_version:
                    # تحويل صيغة numeric (مثل 70000) إلى اسم (مثل 7.0)
                    version_int = int(oneui_version)
                    major = version_int // 10000
                    minor = (version_int % 10000) // 1000
                    one_ui_config["version"] = f"{major}.{minor}"

            # اقتراح الخدمات المتاحة
            one_ui_config["services"] = [
                "Samsung Cloud",
                "Samsung Account",
                "Samsung Members",
                "SmartThings",
                "Galaxy Store",
                "Secure Folder",
                "Knox Security"
            ]

            one_ui_config["theme"] = "Samsung One UI"
            one_ui_config["features"] = [
                "Always On Display",
                "One Handed Operation",
                "Samsung DeX",
                "Bluetooth Low Energy",
                "Wireless PowerShare"
            ]

        except Exception as e:
            print(f"Warning extracting One UI config: {e}")

        return one_ui_config

    def get_summary(self) -> Dict:
        """الحصول على ملخص المستخرج"""
        return {
            "firmware_dir": str(self.firmware_dir),
            "components_extracted": len(self.extracted_files),
            "components": {
                name: {
                    "size_gb": component.size_bytes / (1024 ** 3),
                    "md5": component.md5_hash,
                    "path": str(component.file_path)
                }
                for name, component in self.extracted_files.items()
            }
        }


# مثال على الاستخدام
if __name__ == "__main__":
    import asyncio

    async def test():
        firmware_dir = Path("firmware")

        extractor = SamsungFirmwareExtractor(firmware_dir)

        print("="*80)
        print("Samsung Firmware Extractor - Test")
        print("="*80)

        # استخرج جميع المكونات
        components = await extractor.extract_all()

        print("\n" + "="*80)
        print("Summary")
        print("="*80)

        summary = extractor.get_summary()
        print(f"Components found: {summary['components_extracted']}")

        for comp_name, comp_info in summary["components"].items():
            print(f"\n{comp_name}:")
            print(f"  Size: {comp_info['size_gb']:.2f} GB")
            print(f"  MD5: {comp_info['md5']}")

        # استخرج build.prop
        print("\n" + "="*80)
        print("Extracted build.prop")
        print("="*80)

        build_prop = await extractor.extract_build_prop()
        if build_prop:
            for key in list(build_prop.keys())[:5]:
                print(f"  {key}: {build_prop[key]}")
            if len(build_prop) > 5:
                print(f"  ... and {len(build_prop) - 5} more properties")

        # استخرج One UI config
        print("\n" + "="*80)
        print("One UI Configuration")
        print("="*80)

        one_ui = await extractor.extract_one_ui_config()
        for key, value in one_ui.items():
            print(f"  {key}: {value}")

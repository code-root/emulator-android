import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, List


def detect_android_sdk() -> str:
    for env_var in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        val = os.environ.get(env_var)
        if val and Path(val).exists():
            return val
    common_paths = [
        Path.home() / "Android" / "Sdk",
        Path.home() / "Library" / "Android" / "sdk",
        Path("/opt/android-sdk"),
        Path("/usr/local/lib/android/sdk"),
    ]
    for p in common_paths:
        if p.exists():
            return str(p)
    return os.environ.get("ANDROID_HOME", "/opt/android-sdk")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database (محلياً للاختبار: sqlite+aiosqlite — انظر scripts/run_dev_local.sh)
    DATABASE_URL: str = "postgresql+asyncpg://emulator:emulator@localhost:5432/emulatordb"

    # بذرة تلقائية عند قاعدة فارغة (ضعها في run_dev_local أو .env.local — لا تستخدم في الإنتاج)
    DEV_SEED_ADMIN_USERNAME: str = ""
    DEV_SEED_ADMIN_PASSWORD: str = ""
    DEV_SEED_ADMIN_EMAIL: str = ""

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT
    SECRET_KEY: str = "changeme-super-secret-key-for-jwt-tokens-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    # محاكي افتراضي: avd. أجهزة سامسونغ الحقيقية تُضبط لكل جهاز عبر emulator_kind=physical في API وليس هنا.
    EMULATOR_BACKEND: str = "avd"  # avd (qemu غير مفعّل)

    # Android SDK
    AVD_SDK_PATH: str = ""

    # Directories
    INSTANCES_DIR: str = "/tmp/emulator-instances"
    IMAGES_DIR: str = "/tmp/emulator-images"
    # Docker يضبطه إلى /app/uploads عبر المتغير؛ محلياً يُشتق من جذر المشروع
    UPLOADS_DIR: str = ""
    # حزم سوفتوير (ZIP) مثل SAMFW — للمسح ومواءمة البصمة فقط؛ لا تُستخدم كـ system.img لـ AVD
    FIRMWARE_PACKAGES_DIR: str = ""
    # APKs اختيارية (مشغّل سامسونغ وغيره) — تُثبَّت بعد تطبيق البصمة إن كان الموديل Samsung
    SAMSUNG_UI_EXTRAS_DIR: str = ""

    # Limits
    MAX_INSTANCES: int = 10

    # Ports
    MITMPROXY_BASE_PORT: int = 8080
    SCRCPY_PORT_START: int = 27183
    ADB_PORT_START: int = 5554
    EMULATOR_CONSOLE_PORT_START: int = 5554

    # App
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    DEBUG: bool = False

    # GitHub OAuth (تسجيل دخول + ربط الحساب — أنشئ تطبيقاً من GitHub → Settings → Developer settings → OAuth Apps)
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""
    # عنوان الاستدعاء الخلفي الذي تضعه في إعدادات OAuth App على GitHub (يجب أن يطابق حرفياً)
    GITHUB_OAUTH_REDIRECT_URI: str = ""
    # الواجهة التي نُعيد التوجيه إليها بعد النجاح (يحمل ?token=)
    FRONTEND_URL: str = "http://localhost:5173"

    # Firmware download sources — tried in order if primary fails
    FIRMWARE_SOURCES: list[dict] = [
        {
            "name": "Samsung CDN",
            "url_template": "https://cfs4.samsungmobile.com/{csc}/{model}/{ap_version}.zip",
            "description": "Official Samsung FOTA server",
            "enabled": True
        },
    ]

    # User-provided fallback sources (add your own here or via environment)
    # Example format:
    # FIRMWARE_FALLBACK_SOURCES = [
    #     "https://samfw.com/firmware/{model}/{csc}/{ap_version}",
    #     "https://firmware-server.local/samsung/{model}_{csc}_{ap_version}.zip",
    # ]
    FIRMWARE_FALLBACK_SOURCES: list[str] = os.environ.get("FIRMWARE_FALLBACK_SOURCES", "").split(";") if os.environ.get("FIRMWARE_FALLBACK_SOURCES") else []

    # CORS
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:80",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:80",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://nginx",
    ]

    def model_post_init(self, __context):
        if not self.AVD_SDK_PATH:
            self.AVD_SDK_PATH = detect_android_sdk()
        if not self.GITHUB_OAUTH_REDIRECT_URI:
            self.GITHUB_OAUTH_REDIRECT_URI = f"http://127.0.0.1:{self.APP_PORT}/api/auth/github/callback"
        root = Path(__file__).resolve().parent.parent
        if not self.UPLOADS_DIR:
            self.UPLOADS_DIR = str(root / "uploads")
        if not self.FIRMWARE_PACKAGES_DIR:
            self.FIRMWARE_PACKAGES_DIR = str(root / "firmware")
        if not self.SAMSUNG_UI_EXTRAS_DIR:
            self.SAMSUNG_UI_EXTRAS_DIR = str(Path(self.FIRMWARE_PACKAGES_DIR) / "samsung_extras")
        # Ensure directories exist
        for d in [
            self.INSTANCES_DIR,
            self.IMAGES_DIR,
            self.UPLOADS_DIR,
            self.FIRMWARE_PACKAGES_DIR,
            self.SAMSUNG_UI_EXTRAS_DIR,
        ]:
            Path(d).mkdir(parents=True, exist_ok=True)


settings = Settings()

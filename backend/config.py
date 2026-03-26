import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


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

    # Emulator backend
    EMULATOR_BACKEND: str = "avd"  # avd or qemu

    # Android SDK
    AVD_SDK_PATH: str = ""

    # Directories
    INSTANCES_DIR: str = "/tmp/emulator-instances"
    IMAGES_DIR: str = "/tmp/emulator-images"
    # Docker يضبطه إلى /app/uploads عبر المتغير؛ محلياً يُشتق من جذر المشروع
    UPLOADS_DIR: str = ""
    # حزم سوفتوير (ZIP) مثل SAMFW — للمسح ومواءمة البصمة فقط؛ لا تُستخدم كـ system.img لـ AVD
    FIRMWARE_PACKAGES_DIR: str = ""

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
        # Ensure directories exist
        for d in [self.INSTANCES_DIR, self.IMAGES_DIR, self.UPLOADS_DIR, self.FIRMWARE_PACKAGES_DIR]:
            Path(d).mkdir(parents=True, exist_ok=True)


settings = Settings()

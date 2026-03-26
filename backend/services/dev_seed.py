"""بذرة مستخدم admin للتطوير المحلي فقط — عند تعيين DEV_SEED_* وقاعدة بلا مستخدمين."""
import logging
from sqlalchemy import func, select
from passlib.context import CryptContext

from config import settings
from db.database import AsyncSessionLocal
from db.models import User, UserRole

logger = logging.getLogger(__name__)
_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def seed_dev_admin_if_configured() -> None:
    user = (settings.DEV_SEED_ADMIN_USERNAME or "").strip()
    password = settings.DEV_SEED_ADMIN_PASSWORD or ""
    if not user or not password:
        return

    async with AsyncSessionLocal() as db:
        count_result = await db.execute(select(func.count()).select_from(User))
        if (count_result.scalar() or 0) > 0:
            return

        email = (settings.DEV_SEED_ADMIN_EMAIL or "").strip() or f"{user}@localhost.dev"
        hashed = _pwd.hash(password)
        db.add(
            User(
                username=user,
                email=email,
                hashed_password=hashed,
                role=UserRole.admin,
                is_active=True,
            )
        )
        await db.commit()
    logger.info("DEV_SEED: created admin user %r (local dev only)", user)

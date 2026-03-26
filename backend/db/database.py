from typing import Any, AsyncGenerator, Dict
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool
from config import settings
from db.models import Base
import logging

logger = logging.getLogger(__name__)


def _async_engine_kwargs(database_url: str) -> Dict[str, Any]:
    """SQLite محلياً بدون Postgres — استخدم DATABASE_URL=sqlite+aiosqlite:///..."""
    base: Dict[str, Any] = {
        "echo": settings.DEBUG,
        "future": True,
    }
    if database_url.startswith("sqlite"):
        base["poolclass"] = NullPool
        base["connect_args"] = {"check_same_thread": False}
        return base
    base["poolclass"] = NullPool
    return base


engine = create_async_engine(
    settings.DATABASE_URL,
    **_async_engine_kwargs(settings.DATABASE_URL),
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def create_all_tables() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created successfully")


async def drop_all_tables() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    logger.info("Database tables dropped")

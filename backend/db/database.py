from typing import Any, AsyncGenerator, Dict
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy import text
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


async def _sqlite_add_column_if_missing(conn, table: str, column: str, ddl: str) -> None:
    try:
        res = await conn.execute(text(f"PRAGMA table_info({table})"))
        rows = res.fetchall()
        names = {r[1] for r in rows}
        if column not in names:
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))
            logger.info("SQLite migration: added %s.%s", table, column)
    except Exception as e:
        logger.warning("SQLite migration skip %s.%s: %s", table, column, e)


async def ensure_legacy_fingerprint_columns() -> None:
    """إضافة أعمدة/جداول جديدة دون Alembic (SQLite)."""
    url = settings.DATABASE_URL
    if not url.startswith("sqlite"):
        return
    async with engine.begin() as conn:
        await _sqlite_add_column_if_missing(
            conn, "device_fingerprints", "extended_json", "extended_json TEXT"
        )


async def create_all_tables() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await ensure_legacy_fingerprint_columns()
    logger.info("Database tables created successfully")


async def drop_all_tables() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    logger.info("Database tables dropped")

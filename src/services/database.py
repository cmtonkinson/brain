"""Database session management and action logging."""

import logging
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncGenerator
from pathlib import Path

from sqlalchemy import text, create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from alembic import command
from alembic.config import Config

from config import settings
from models import ActionLog

logger = logging.getLogger(__name__)

# Convert sync URL to async URL
_db_url = settings.database_url
if _db_url and _db_url.startswith("postgresql://"):
    _db_url = _db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

# Create async engine
engine = create_async_engine(
    _db_url or "postgresql+asyncpg://brain:brain@localhost:5432/brain",
    echo=False,
    pool_pre_ping=True,
)

# Session factory
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

_sync_engine = None
_sync_session_factory: sessionmaker | None = None


def _get_sync_db_url() -> str:
    url = _db_url or "postgresql+asyncpg://brain:brain@localhost:5432/brain"
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return url


def get_sync_engine():
    global _sync_engine
    if _sync_engine is None:
        _sync_engine = create_engine(
            _get_sync_db_url(),
            pool_pre_ping=True,
        )
    return _sync_engine


def get_sync_session() -> Session:
    global _sync_session_factory
    if _sync_session_factory is None:
        _sync_session_factory = sessionmaker(bind=get_sync_engine())
    return _sync_session_factory()


def _run_migrations() -> None:
    alembic_ini = Path(__file__).resolve().parents[2] / "alembic.ini"
    alembic_cfg = Config(str(alembic_ini))
    alembic_cfg.set_main_option("sqlalchemy.url", _get_sync_db_url())
    command.upgrade(alembic_cfg, "head")


async def init_db() -> None:
    """Initialize database tables."""
    await asyncio.to_thread(_run_migrations)
    logger.info("Database migrations applied")


def run_migrations_sync() -> None:
    """Run database migrations synchronously."""
    _run_migrations()


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get an async database session.

    Usage:
        async with get_session() as session:
            # use session
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def log_action(
    session: AsyncSession,
    action_type: str,
    description: str,
    result: str | None = None,
) -> ActionLog:
    """Log an action to the database.

    Args:
        session: Database session
        action_type: Type of action (e.g., "search", "create_note", "send_message")
        description: Human-readable description of the action
        result: Optional result or response from the action

    Returns:
        The created ActionLog record
    """
    action = ActionLog(
        action_type=action_type,
        description=description,
        result=result,
        timestamp=datetime.utcnow(),
    )
    session.add(action)
    await session.flush()
    logger.debug(f"Logged action: {action_type} - {description}")
    return action


async def check_connection() -> bool:
    """Check if database connection is working."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error(f"Database connection check failed: {e}")
        return False

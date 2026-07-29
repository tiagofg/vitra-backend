from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import config

engine: AsyncEngine = create_async_engine(
    config.url_efetiva,
    echo=config.db_echo,
    pool_size=config.db_pool_size,
    max_overflow=config.db_max_overflow,
    pool_pre_ping=True,
)

SessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Uma transação por request: commit no fim, rollback em qualquer exceção."""
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            await session.commit()

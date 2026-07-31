from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import config
from app.core.tenancy import registrar_eventos

# Antes de qualquer sessão existir: é este registro que faz o `SET LOCAL` sair sozinho no
# início de toda transação. Sem ele o RLS não deixa de valer — a aplicação é que passa a
# enxergar zero linhas em tudo.
registrar_eventos()

engine: AsyncEngine = create_async_engine(
    config.database_url,
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

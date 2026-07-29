from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, MetaData, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

# Nomes determinísticos para índices e constraints — sem isso o autogenerate do Alembic
# produz migrações que não conseguem derrubar o que criaram.
CONVENCAO_NOMES = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=CONVENCAO_NOMES)


class ModeloBase(Base):
    """Toda tabela do VITRA: id UUID, criado_em, atualizado_em, criado_por_id."""

    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    @declared_attr
    @classmethod
    def criado_por_id(cls) -> Mapped[uuid.UUID | None]:
        # Nulável: seeds e o primeiro usuário do sistema não têm autor.
        return mapped_column(
            Uuid,
            ForeignKey("usuario.id", ondelete="SET NULL", use_alter=True),
            nullable=True,
        )

    def __repr__(self) -> str:
        return f"<{type(self).__name__} id={self.id}>"

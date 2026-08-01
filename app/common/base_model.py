from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, MetaData, PrimaryKeyConstraint, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from app.common.mixins import TenantScopedMixin

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


class _AuditoriaMixin:
    """`criado_em` / `atualizado_em` / `criado_por_id`, comuns a toda tabela do VITRA."""

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
            ForeignKey("employees.id", ondelete="SET NULL", use_alter=True),
            nullable=True,
        )


class _ModeloComId(Base, _AuditoriaMixin):
    """Ponto comum de tipagem entre `ModeloBase` e `ModeloTenant`: ambos têm `id` e
    auditoria, mas nenhum é subtipo do outro (a PK é composta num e não no outro). É esta
    classe, e não `ModeloBase`, que `app/common/base_service.py` usa como bound do
    `TypeVar` genérico — serviço não deveria saber se o recurso é global ou por empresa.
    """

    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)


class ModeloBase(_ModeloComId):
    """Tabela global do VITRA: PK `id` simples + auditoria."""

    __abstract__ = True

    # Redeclara `id` só para acrescentar `primary_key=True` — tabela global não passa
    # pelo `PrimaryKeyConstraint` explícito que `ModeloTenant` exige.
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} id={self.id}>"


class ModeloTenant(_ModeloComId, TenantScopedMixin):
    """Tabela por empresa: `id` + `tenant_id` (via `TenantScopedMixin`) + auditoria.

    Não declara a PK — herança de mixin não garante a ordem das colunas (ver o docstring
    de `TenantScopedMixin`), então cada modelo concreto declara o próprio
    `PrimaryKeyConstraint("tenant_id", "id")` em `__table_args__`. Use `pk_tenant()` para
    não repetir o nome da constraint em cada modelo.
    """

    __abstract__ = True

    def __repr__(self) -> str:
        return f"<{type(self).__name__} tenant_id={self.tenant_id} id={self.id}>"


def pk_tenant(tabela: str) -> PrimaryKeyConstraint:
    """`PrimaryKeyConstraint("tenant_id", "id")` com o nome que a convenção de `pk` exige."""
    return PrimaryKeyConstraint("tenant_id", "id", name=f"pk_{tabela}")

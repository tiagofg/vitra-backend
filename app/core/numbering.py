from __future__ import annotations

import enum
import uuid

from sqlalchemy import BigInteger, Enum, String, UniqueConstraint, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import ModeloTenant, pk_tenant


class TipoDocumento(enum.StrEnum):
    orcamento = "orcamento"
    pedido_venda = "pedido_venda"
    pedido_compra = "pedido_compra"
    ordem_compra = "ordem_compra"


def enum_col(tipo: type[enum.Enum], nome: str) -> Enum:
    """Grava o *valor* do enum (minúsculo), não o nome do membro."""
    return Enum(tipo, name=nome, values_callable=lambda e: [m.value for m in e])


class ContadorDocumento(ModeloTenant):
    """Sequência por (empresa, tipo, série).

    Não é `SEQUENCE` do Postgres de propósito: a numeração precisa ser por empresa+série e
    sem buracos — e SEQUENCE não faz rollback do valor consumido. Por empresa é agora PK
    composta `(tenant_id, id)`, como toda tabela por empresa sob RLS.
    """

    __tablename__ = "contador_documento"
    __table_args__ = (
        pk_tenant("contador_documento"),
        UniqueConstraint("tenant_id", "tipo", "serie", name="uq_contador_tenant_tipo_serie"),
    )

    tipo: Mapped[TipoDocumento] = mapped_column(
        enum_col(TipoDocumento, "tipo_documento"), nullable=False
    )
    serie: Mapped[str] = mapped_column(String(10), nullable=False, default="1")
    ultimo_numero: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


async def proximo_numero(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    tipo: TipoDocumento,
    serie: str = "1",
) -> int:
    """Reserva o próximo número dentro da transação corrente.

    O `FOR UPDATE` serializa concorrentes na linha do contador: dois documentos criados em
    paralelo na mesma série não podem receber o mesmo número. O número é atribuído na
    CRIAÇÃO — no legado a numeração não é cronológica, a emissão vem depois.
    """
    # Garante a linha existir sem estourar em corrida de dois primeiros documentos.
    await session.execute(
        pg_insert(ContadorDocumento)
        .values(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            tipo=tipo.value,
            serie=serie,
            ultimo_numero=0,
        )
        .on_conflict_do_nothing(constraint="uq_contador_tenant_tipo_serie")
    )

    contador = (
        await session.execute(
            select(ContadorDocumento)
            .where(
                ContadorDocumento.tenant_id == tenant_id,
                ContadorDocumento.tipo == tipo,
                ContadorDocumento.serie == serie,
            )
            .with_for_update()
        )
    ).scalar_one()

    contador.ultimo_numero += 1
    await session.flush()
    return contador.ultimo_numero

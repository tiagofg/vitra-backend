"""Auditoria append-only, na mesma transação da escrita.

O contrato do VITRA exige isso desde a primeira tabela — não é uma fase de endurecimento
posterior (ver "Retrabalho na S0 já entregue" no plano). `audit_log` é por empresa, como o
que ela audita: cada linha aponta para `tenant_id`, e a política de RLS a recorta como
qualquer outra tabela por empresa — exceto que o papel de runtime só recebe `SELECT` e
`INSERT` (ver o `GRANT` em `alembic/versions/b1c2d3e4f5a6_rls_multiempresa.py`, que trata
`audit_log` à parte do laço genérico). Sem `UPDATE`/`DELETE` concedidos, "append-only" é
uma garantia do banco, não uma promessa do código: nem um bug na aplicação nem uma conexão
comprometida com as credenciais de runtime consegue apagar ou alterar rastro.

**O que este módulo entrega agora:** o schema da tabela e `registrar_evento()`, para o
serviço chamar explicitamente onde uma mutação importa (documentos, estoque — a partir de
S3/S4). **O que fica para quando houver um consumidor de verdade:** interceptar
automaticamente via `before_flush`. Instrumentar isso sem nenhum serviço para validar
contra é código morto com risco de esconder um bug de serialização (linhas com PK
composta, `Decimal`, `datetime`) até o primeiro uso real — melhor esperar a S3/S4, que são
as primeiras tabelas que este plano audita de fato (estoque, documentos).
"""

from __future__ import annotations

import enum
import uuid
from typing import Any

from sqlalchemy import Index, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import ModeloTenant, pk_tenant
from app.core.numbering import enum_col


class AcaoAuditoria(enum.StrEnum):
    criar = "criar"
    atualizar = "atualizar"
    desativar = "desativar"
    reativar = "reativar"
    cancelar = "cancelar"


class RegistroAuditoria(ModeloTenant):
    __tablename__ = "audit_log"
    __table_args__ = (
        pk_tenant("audit_log"),
        Index("ix_audit_log_tenant_tabela_linha", "tenant_id", "tabela", "linha_id"),
    )

    tabela: Mapped[str] = mapped_column(String(63), nullable=False)
    linha_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    acao: Mapped[AcaoAuditoria] = mapped_column(
        enum_col(AcaoAuditoria, "acao_auditoria"), nullable=False
    )
    antes: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    depois: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


async def registrar_evento(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    tabela: str,
    linha_id: uuid.UUID,
    acao: AcaoAuditoria,
    antes: dict[str, Any] | None = None,
    depois: dict[str, Any] | None = None,
    usuario_id: uuid.UUID | None = None,
) -> None:
    """Grava o evento **na mesma transação** da escrita que o originou.

    Não há `commit()` aqui de propósito: quem chama já está dentro da transação da
    mutação, e um `flush()` isolado bastaria para não perder a ordem — o `commit` do
    request é quem torna tudo durável junto.
    """
    session.add(
        RegistroAuditoria(
            tenant_id=tenant_id,
            tabela=tabela,
            linha_id=linha_id,
            acao=acao,
            antes=antes,
            depois=depois,
            criado_por_id=usuario_id,
        )
    )
    await session.flush()

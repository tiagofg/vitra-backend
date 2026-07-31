from __future__ import annotations

import enum
import uuid
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Numeric,
    String,
    Table,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.base_model import Base, ModeloBase
from app.common.mixins import AtivoMixin, EmpresaOpcionalMixin
from app.core.numbering import TipoDocumento, enum_col

usuario_grupo = Table(
    "usuario_grupo",
    Base.metadata,
    Column("usuario_id", Uuid, ForeignKey("usuario.id", ondelete="CASCADE"), primary_key=True),
    Column("grupo_id", Uuid, ForeignKey("grupo.id", ondelete="CASCADE"), primary_key=True),
)

grupo_permissao = Table(
    "grupo_permissao",
    Base.metadata,
    Column("grupo_id", Uuid, ForeignKey("grupo.id", ondelete="CASCADE"), primary_key=True),
    Column("permissao_id", Uuid, ForeignKey("permissao.id", ondelete="CASCADE"), primary_key=True),
)


class Permissao(ModeloBase):
    """Par recurso+ação. O catálogo canônico vive em `app/core/permissions.py`."""

    __tablename__ = "permissao"
    __table_args__ = (UniqueConstraint("recurso", "acao", name="uq_permissao_recurso_acao"),)

    recurso: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    acao: Mapped[str] = mapped_column(String(30), nullable=False)
    descricao: Mapped[str | None] = mapped_column(String(200))

    @property
    def chave(self) -> str:
        return f"{self.recurso}:{self.acao}"


class Grupo(ModeloBase, AtivoMixin):
    __tablename__ = "grupo"

    nome: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    descricao: Mapped[str | None] = mapped_column(String(200))

    permissoes: Mapped[list[Permissao]] = relationship(secondary=grupo_permissao, lazy="selectin")


class Usuario(ModeloBase, AtivoMixin, EmpresaOpcionalMixin):
    __tablename__ = "usuario"

    login: Mapped[str] = mapped_column(String(60), nullable=False, unique=True, index=True)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str | None] = mapped_column(String(160))
    senha_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    superusuario: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # `Alterar Limites` do orçamento: acima disto o desconto exige autorização (S4).
    limite_desconto_pct: Mapped[Decimal] = mapped_column(
        Numeric(9, 4), default=Decimal("0.0000"), nullable=False
    )

    grupos: Mapped[list[Grupo]] = relationship(secondary=usuario_grupo, lazy="selectin")

    def permissoes_efetivas(self) -> set[str]:
        return {p.chave for grupo in self.grupos if grupo.ativo for p in grupo.permissoes}

    def pode(self, recurso: str, acao: str) -> bool:
        return self.superusuario or f"{recurso}:{acao}" in self.permissoes_efetivas()


class TipoAutorizacao(enum.StrEnum):
    desconto_acima_do_limite = "desconto_acima_do_limite"
    alteracao_de_preco = "alteracao_de_preco"
    liberacao_de_credito = "liberacao_de_credito"


class StatusAutorizacao(enum.StrEnum):
    pendente = "pendente"
    aprovada = "aprovada"
    rejeitada = "rejeitada"


class AutorizacaoDocumento(ModeloBase):
    """O botão `Permissões` do orçamento: autorização pontual, por documento.

    Modelo criado em S0 junto com o RBAC porque a migração inicial já o comporta;
    o serviço que o consome entra em S4 (desconto acima do limite do usuário).
    """

    __tablename__ = "autorizacao_documento"

    documento_tipo: Mapped[TipoDocumento] = mapped_column(
        enum_col(TipoDocumento, "tipo_documento"), nullable=False
    )
    documento_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    tipo: Mapped[TipoAutorizacao] = mapped_column(
        enum_col(TipoAutorizacao, "tipo_autorizacao"), nullable=False
    )
    solicitante_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("usuario.id", ondelete="RESTRICT"), nullable=False
    )
    autorizador_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("usuario.id", ondelete="RESTRICT")
    )
    valor_solicitado: Mapped[Decimal | None] = mapped_column(Numeric(15, 4))
    status: Mapped[StatusAutorizacao] = mapped_column(
        enum_col(StatusAutorizacao, "status_autorizacao"),
        default=StatusAutorizacao.pendente,
        nullable=False,
    )
    motivo: Mapped[str | None] = mapped_column(String(500))

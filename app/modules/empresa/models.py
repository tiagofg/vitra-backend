from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKeyConstraint, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import ModeloBase, ModeloTenant, pk_tenant
from app.common.mixins import (
    AtivoMixin,
    ComunicadoresMixin,
    ContatosMixin,
    EnderecoMixin,
    ObservacaoMixin,
    RedesSociaisMixin,
)


class Empresa(
    ModeloBase,
    AtivoMixin,
    EnderecoMixin,
    ContatosMixin,
    RedesSociaisMixin,
    ComunicadoresMixin,
    ObservacaoMixin,
):
    """Raiz do recorte multiempresa. Vertz e Via HF são duas linhas aqui.

    Tabela física `tenants`: é a mesma raiz que o bake-off criou (`id`, `cnpj`, `active`),
    agora com as colunas próprias da S0 por cima. Ela mesma não é recortada por RLS — é o
    que o RLS recorta a partir dela.
    """

    __tablename__ = "tenants"

    codigo: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    razao_social: Mapped[str] = mapped_column(String(160), nullable=False)
    nome_fantasia: Mapped[str | None] = mapped_column(String(160))
    cnpj: Mapped[str | None] = mapped_column(String(14), unique=True)
    inscricao_estadual: Mapped[str | None] = mapped_column(String(30))
    inscricao_municipal: Mapped[str | None] = mapped_column(String(30))


class Filial(ModeloTenant, AtivoMixin, EnderecoMixin, ContatosMixin):
    __tablename__ = "filial"
    __table_args__ = (
        pk_tenant("filial"),
        UniqueConstraint("tenant_id", "codigo", name="uq_filial_tenant_codigo"),
    )

    codigo: Mapped[str] = mapped_column(String(20), nullable=False)
    nome: Mapped[str] = mapped_column(String(160), nullable=False)
    cnpj: Mapped[str | None] = mapped_column(String(14))
    matriz: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class CentroCusto(ModeloTenant, AtivoMixin):
    __tablename__ = "centro_custo"
    __table_args__ = (
        pk_tenant("centro_custo"),
        UniqueConstraint("tenant_id", "codigo", name="uq_centro_custo_tenant_codigo"),
        # FK composta: um centro de custo só pode ser pai de outro **da mesma empresa**.
        ForeignKeyConstraint(
            ["tenant_id", "pai_id"],
            ["centro_custo.tenant_id", "centro_custo.id"],
            name="fk_centro_custo_pai_id",
            ondelete="RESTRICT",
        ),
    )

    codigo: Mapped[str] = mapped_column(String(20), nullable=False)
    nome: Mapped[str] = mapped_column(String(160), nullable=False)
    pai_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)

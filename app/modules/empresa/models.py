from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import ModeloBase
from app.common.mixins import (
    AtivoMixin,
    ComunicadoresMixin,
    ContatosMixin,
    EmpresaScopedMixin,
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
    """Raiz do recorte multiempresa. Vertz e Via HF são duas linhas aqui."""

    __tablename__ = "empresa"

    codigo: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    razao_social: Mapped[str] = mapped_column(String(160), nullable=False)
    nome_fantasia: Mapped[str | None] = mapped_column(String(160))
    cnpj: Mapped[str | None] = mapped_column(String(18), unique=True)
    inscricao_estadual: Mapped[str | None] = mapped_column(String(30))
    inscricao_municipal: Mapped[str | None] = mapped_column(String(30))


class Filial(ModeloBase, AtivoMixin, EmpresaScopedMixin, EnderecoMixin, ContatosMixin):
    __tablename__ = "filial"
    __table_args__ = (UniqueConstraint("empresa_id", "codigo", name="uq_filial_empresa_codigo"),)

    codigo: Mapped[str] = mapped_column(String(20), nullable=False)
    nome: Mapped[str] = mapped_column(String(160), nullable=False)
    cnpj: Mapped[str | None] = mapped_column(String(18))
    matriz: Mapped[bool] = mapped_column(default=False, nullable=False)


class CentroCusto(ModeloBase, AtivoMixin, EmpresaScopedMixin):
    __tablename__ = "centro_custo"
    __table_args__ = (
        UniqueConstraint("empresa_id", "codigo", name="uq_centro_custo_empresa_codigo"),
    )

    codigo: Mapped[str] = mapped_column(String(20), nullable=False)
    nome: Mapped[str] = mapped_column(String(160), nullable=False)
    pai_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("centro_custo.id", ondelete="RESTRICT")
    )

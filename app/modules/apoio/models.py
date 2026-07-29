from __future__ import annotations

import enum
import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.base_model import ModeloBase
from app.common.mixins import AtivoMixin, EmpresaOpcionalMixin
from app.core.numbering import enum_col


class DominioApoio(enum.StrEnum):
    """Os 19 `[combo +...]` das telas do legado. Um domínio por combo, uma tabela só."""

    setor = "setor"
    grau_instrucao = "grau_instrucao"
    profissao = "profissao"
    raca_cor = "raca_cor"
    estado_civil = "estado_civil"
    nacionalidade = "nacionalidade"
    cargo = "cargo"
    vinculo = "vinculo"
    categoria = "categoria"
    tipo_produto = "tipo_produto"
    tipo_peca = "tipo_peca"
    tipo_linha = "tipo_linha"
    classificacao = "classificacao"
    designer_modelo = "designer_modelo"
    fabrica = "fabrica"
    marca = "marca"
    material = "material"
    unidade = "unidade"
    acabamento = "acabamento"
    tamanho = "tamanho"


class TabelaApoio(ModeloBase, AtivoMixin, EmpresaOpcionalMixin):
    """Uma tabela para os 19 combos, discriminada por `dominio`.

    `empresa_id` nulo = valor global (compartilhado entre Vertz e Via HF).
    """

    __tablename__ = "tabela_apoio"
    __table_args__ = (
        UniqueConstraint("dominio", "codigo", "empresa_id", name="uq_apoio_dominio_codigo_emp"),
        Index("ix_apoio_dominio_descricao", "dominio", "descricao"),
    )

    dominio: Mapped[DominioApoio] = mapped_column(
        enum_col(DominioApoio, "dominio_apoio"), nullable=False, index=True
    )
    codigo: Mapped[str] = mapped_column(String(30), nullable=False)
    descricao: Mapped[str] = mapped_column(String(160), nullable=False)
    ordem: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Uf(ModeloBase):
    __tablename__ = "uf"

    sigla: Mapped[str] = mapped_column(String(2), nullable=False, unique=True)
    nome: Mapped[str] = mapped_column(String(60), nullable=False)
    codigo_ibge: Mapped[str] = mapped_column(String(2), nullable=False, unique=True)


class Cidade(ModeloBase):
    """Fora da tabela de apoio de propósito: tem campos próprios (UF, IBGE) e é
    `[busca +...]`, não `[combo +...]`."""

    __tablename__ = "cidade"
    __table_args__ = (UniqueConstraint("uf_id", "nome", name="uq_cidade_uf_nome"),)

    uf_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("uf.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    nome: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    codigo_ibge: Mapped[str | None] = mapped_column(String(7), unique=True)

    uf: Mapped[Uf] = relationship(lazy="joined")

    @property
    def uf_sigla(self) -> str:
        return self.uf.sigla


class Banco(ModeloBase, AtivoMixin):
    __tablename__ = "banco"

    codigo: Mapped[str] = mapped_column(String(5), nullable=False, unique=True)
    nome: Mapped[str] = mapped_column(String(120), nullable=False, index=True)

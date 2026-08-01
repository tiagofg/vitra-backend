from __future__ import annotations

import enum
import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.base_model import ModeloBase
from app.common.mixins import AtivoMixin
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


class TabelaApoio(ModeloBase, AtivoMixin):
    """Uma tabela para os 19 combos, discriminada por `dominio`.

    Tabela física `catalog_lookups` — o schema que o bake-off já trazia (`id`, `kind`,
    `name`, `active`) e que o plano confirmou como o desenho certo: os 19 combos são
    vocabulário do grupo inteiro, não de cada empresa. `empresa_id` não existe mais aqui;
    era o desenho pré-RLS, mantido durante a coexistência dos dois módulos.

    Sem RLS, e é o desenho: mas isso quer dizer que `apoio:editar`/`apoio:excluir`
    concedido a alguém vale para o vocabulário inteiro do grupo, mesmo depois do RBAC por
    empresa da S2 (`VinculoEmpresa.grupo_id`, `app/core/permissions.py::RECURSOS_POR_EMPRESA`)
    — `apoio` é global de propósito, não entra nesse conjunto, então o grupo do vínculo
    nunca decide sobre ele sozinho. Editar "Dourado" na ABACAXI muda o combo que a tela da
    UVA também usa, porque é a mesma linha; recorte por empresa não existe para dado global.
    """

    __tablename__ = "catalog_lookups"
    __table_args__ = (
        # `UniqueConstraint`/`Index` referenciam o nome **físico** da coluna (o argumento
        # posicional de `mapped_column`), não o atributo Python.
        UniqueConstraint("kind", "code", name="uq_catalog_lookups_kind_code"),
        Index("ix_catalog_lookups_kind_name", "kind", "name"),
    )

    dominio: Mapped[DominioApoio] = mapped_column(
        "kind", enum_col(DominioApoio, "dominio_apoio"), nullable=False, index=True
    )
    codigo: Mapped[str] = mapped_column("code", String(30), nullable=False)
    descricao: Mapped[str] = mapped_column("name", String(160), nullable=False)
    ordem: Mapped[int] = mapped_column("sort_order", Integer, default=0, nullable=False)


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

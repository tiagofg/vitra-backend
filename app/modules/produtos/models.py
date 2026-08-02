"""Produto, variante, preço/estoque, fornecedor do produto e grupos relacionados.

Origem: `Produto`/`Variante`/`ProdutoEmpresa` viviam em `app/modules/bakeoff/`, mapeadas
sobre `Base` puro (sem auditoria) porque o schema do banco compartilhado do Neon era fixo e
não tinha essas colunas. Com o bake-off encerrado (S0.5) o módulo passa a ser dono do
próprio schema, e os três modelos ganharam `ModeloTenant` — PK composta e auditoria, como
qualquer tabela nova por empresa. A S2 acrescenta o resto: as ~20 colunas de catálogo do
plano, `produto_fornecedor`, `grupo_relacionado`/`item_relacionado`, e troca `finish`/`size`
(texto livre do bake-off) por FK para `catalog_lookups` — acabamento e tamanho são
`[combo +...]`, não campo livre.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.base_model import ModeloTenant, pk_tenant
from app.common.mixins import AtivoMixin


class Produto(ModeloTenant, AtivoMixin):
    __tablename__ = "products"
    __table_args__ = (
        pk_tenant("products"),
        # Nome físico da coluna, não o atributo Python: `codigo`→`code`, `descricao`→`description`.
        UniqueConstraint("tenant_id", "code", name="uq_products_tenant_code"),
        Index("ix_products_tenant_description", "tenant_id", "description"),
    )

    codigo: Mapped[str] = mapped_column("code", String(40), nullable=False)
    descricao: Mapped[str] = mapped_column("description", String(300), nullable=False)

    codigo_especial: Mapped[str | None] = mapped_column(String(40))
    codigo_reduzido: Mapped[str | None] = mapped_column(String(20))
    descricao_complementar: Mapped[str | None] = mapped_column(String(500))
    dt_vigencia: Mapped[date | None] = mapped_column(Date)

    # Os `[combo +...]` da aba 1. FK simples: `catalog_lookups` é global, sem `tenant_id`,
    # então não há chave composta a carregar aqui — mesma convenção de `pessoas`.
    tipo_produto_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("catalog_lookups.id", ondelete="RESTRICT")
    )
    tipo_peca_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("catalog_lookups.id", ondelete="RESTRICT")
    )
    tipo_linha_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("catalog_lookups.id", ondelete="RESTRICT")
    )
    classificacao_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("catalog_lookups.id", ondelete="RESTRICT")
    )
    designer_modelo_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("catalog_lookups.id", ondelete="RESTRICT")
    )
    fabrica_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("catalog_lookups.id", ondelete="RESTRICT")
    )
    marca_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("catalog_lookups.id", ondelete="RESTRICT")
    )
    unidade_entrada_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("catalog_lookups.id", ondelete="RESTRICT")
    )
    unidade_saida_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("catalog_lookups.id", ondelete="RESTRICT")
    )
    qtd_entrada: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, default=1)
    qtd_saida: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, default=1)

    # `tenants` é global — FK simples, sem chave composta. É vínculo de *negócio* (qual
    # empresa do grupo normalmente compra este produto), não recorte de acesso: RLS não
    # entra aqui, é `products.tenant_id` quem já faz esse papel.
    empresa_compradora_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="RESTRICT")
    )

    fora_de_linha: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    consultar_valor: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sobre_medida: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    publicar_no_site: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Fiscal: guardados para quando a emissão (Focus NFe) precisar, sem motor de regra
    # NCM×Operação×CFOP×UF construído aqui — decisão nº 3 do plano.
    ncm: Mapped[str | None] = mapped_column(String(8))
    cest: Mapped[str | None] = mapped_column(String(7))
    origem: Mapped[str | None] = mapped_column(String(1))

    # Aba 2 (`Outros Dados`): ~25 campos luminotécnicos que são especificação de catálogo,
    # não regra de negócio. Validado na borda por `EspecificacaoLuminaria`
    # (`app/modules/produtos/schemas.py`) — se virassem coluna, cada atributo novo seria
    # migração.
    especificacao: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    # `lazy="selectin"` nas três, não o padrão preguiçoso: `BaseService.obter()` (usado
    # por dentro de `atualizar()`, para o replace-set das grades) faz um `select()` puro,
    # sem passar pelas opções de carregamento de `ProdutoService._stmt_base()` — sem
    # `selectin` aqui, `obj.variantes` dentro de `_resolver_relacoes` dispararia lazy load
    # síncrono num contexto async (`MissingGreenlet`). `selectin` e não `joined`: é uma
    # segunda consulta com `IN (...)`, então não duplica linha do produto nem interfere na
    # paginação de `listar()` — mesma razão que já valia para `variantes` no bake-off.
    variantes: Mapped[list[Variante]] = relationship(
        back_populates="produto", cascade="all, delete-orphan", lazy="selectin"
    )
    fornecedores: Mapped[list[ProdutoFornecedor]] = relationship(
        back_populates="produto", cascade="all, delete-orphan", lazy="selectin"
    )
    grupos_relacionados: Mapped[list[GrupoRelacionado]] = relationship(
        back_populates="produto", cascade="all, delete-orphan", lazy="selectin"
    )


class Variante(ModeloTenant, AtivoMixin):
    """`Acabamento × Tamanho`. Preço e estoque não moram aqui — moram abaixo, em
    `product_tenant`.

    `acabamento_id`/`tamanho_id` são FK para `catalog_lookups`, não texto livre — os dois são
    `[combo +...]` do legado (domínios `acabamento`/`tamanho`), a mesma razão de
    `Cliente.profissao_id` ser FK e não `String`.
    """

    __tablename__ = "product_variants"
    __table_args__ = (
        pk_tenant("product_variants"),
        # A FK leva o `tenant_id` junto. É o que impede a variante de uma empresa apontar
        # para o produto de outra: sem a coluna na FK, o banco aceitaria.
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_product_variants_product",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id",
            "product_id",
            "acabamento_id",
            "tamanho_id",
            name="uq_product_variants_produto",
        ),
    )

    produto_id: Mapped[uuid.UUID] = mapped_column("product_id", Uuid, nullable=False)
    acabamento_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("catalog_lookups.id", ondelete="RESTRICT"), nullable=False
    )
    tamanho_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("catalog_lookups.id", ondelete="RESTRICT"), nullable=False
    )

    produto: Mapped[Produto] = relationship(back_populates="variantes")
    # `lazy="joined"` — um-para-um, mesmo padrão de `VinculoEmpresa.colaborador`/`grupo`:
    # sempre um `JOIN` a mais na consulta, nunca uma segunda viagem ao banco, e não
    # duplica linha porque a cardinalidade do outro lado é no máximo 1.
    preco: Mapped[ProdutoEmpresa | None] = relationship(
        back_populates="variante", cascade="all, delete-orphan", uselist=False, lazy="joined"
    )


class ProdutoEmpresa(ModeloTenant):
    """Preço e estoque da variante naquela empresa.

    Repare no que a FK composta compra: esta linha só consegue apontar para uma variante
    **da mesma empresa**. Não é convenção nem validação de serviço — o `INSERT` falha.
    """

    __tablename__ = "product_tenant"
    __table_args__ = (
        pk_tenant("product_tenant"),
        ForeignKeyConstraint(
            ["tenant_id", "variant_id"],
            ["product_variants.tenant_id", "product_variants.id"],
            name="fk_product_tenant_variant",
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "variant_id", name="uq_product_tenant_variant"),
        CheckConstraint("price_cents >= 0", name="price_cents_nao_negativo"),
        CheckConstraint("stock_qty >= 0", name="stock_qty_nao_negativo"),
    )

    variante_id: Mapped[uuid.UUID] = mapped_column("variant_id", Uuid, nullable=False)
    # Dinheiro é inteiro em centavos. R$ 12,34 é 1234. Nunca float, nunca Numeric —
    # converter para reais é responsabilidade do schema de saída, não do banco.
    preco_cents: Mapped[int] = mapped_column("price_cents", BigInteger, nullable=False, default=0)
    estoque: Mapped[Decimal] = mapped_column("stock_qty", Numeric(14, 3), nullable=False, default=0)
    estoque_minimo: Mapped[Decimal] = mapped_column(
        "min_stock", Numeric(14, 3), nullable=False, default=0
    )
    # Legado sem detalhe capturado além do nome do campo — `indice` e `tipo_valor` entram
    # como colunas soltas, sem validação nem uso em regra de negócio ainda; nenhuma tela ou
    # cálculo de S2-S5 os consome. Confirmar semântica exata quando houver captura da tela
    # de preço que os usa.
    indice: Mapped[Decimal | None] = mapped_column(Numeric(9, 4))
    tipo_valor: Mapped[str | None] = mapped_column(String(20))

    variante: Mapped[Variante] = relationship(back_populates="preco")


class ProdutoFornecedor(ModeloTenant):
    """Um fornecedor do produto, com o código e a descrição que ele usa no catálogo dele —
    snapshot, não só FK: o que foi cadastrado não muda se o fornecedor renomear o produto
    no catálogo dele depois."""

    __tablename__ = "produto_fornecedor"
    __table_args__ = (
        pk_tenant("produto_fornecedor"),
        ForeignKeyConstraint(
            ["tenant_id", "produto_id"],
            ["products.tenant_id", "products.id"],
            name="fk_produto_fornecedor_produto",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "fornecedor_id"],
            ["fornecedor.tenant_id", "fornecedor.id"],
            name="fk_produto_fornecedor_fornecedor",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "tenant_id", "produto_id", "fornecedor_id", name="uq_produto_fornecedor_par"
        ),
        # Só um fornecedor padrão por produto — a tela mostra um fornecedor "principal" em
        # destaque, e a UNIQUE parcial é o que impede dois ao mesmo tempo, sem checagem de
        # serviço para manter a invariante sob concorrência.
        Index(
            "uq_produto_fornecedor_padrao",
            "tenant_id",
            "produto_id",
            unique=True,
            postgresql_where=text("padrao"),
        ),
    )

    produto_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    fornecedor_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    codigo_fornecedor: Mapped[str | None] = mapped_column(String(60))
    descricao_fornecedor: Mapped[str | None] = mapped_column(String(300))
    padrao: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    produto: Mapped[Produto] = relationship(back_populates="fornecedores")


class GrupoRelacionado(ModeloTenant, AtivoMixin):
    """Grupo de produtos relacionados a um produto — kit (quando os itens têm quantidade)
    ou sugestão de venda cruzada (quando não têm). Ver `ItemRelacionado`."""

    __tablename__ = "grupo_relacionado"
    __table_args__ = (
        pk_tenant("grupo_relacionado"),
        ForeignKeyConstraint(
            ["tenant_id", "produto_id"],
            ["products.tenant_id", "products.id"],
            name="fk_grupo_relacionado_produto",
            ondelete="CASCADE",
        ),
    )

    produto_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    padrao: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    produto: Mapped[Produto] = relationship(back_populates="grupos_relacionados")
    # Sem relacionamento `itens` aqui de propósito: `ItemRelacionadoService` consulta
    # `ItemRelacionado` direto por `grupo_id`, nunca por navegação de objeto — declarar a
    # coleção só para nunca ser lida seria carregar dado à toa (ou arriscar lazy load
    # síncrono em outro caminho, como já aconteceu com `variantes`/`fornecedores` acima). A
    # limpeza em cascata na remoção continua garantida pelo `ON DELETE CASCADE` da FK.


class ItemRelacionado(ModeloTenant):
    """Um item dentro de um `GrupoRelacionado`.

    `quantidade` preenchida = **kit** (o produto do grupo entra automaticamente com aquela
    quantidade quando o item principal é vendido); `quantidade` nula = **sugestão** de venda
    cruzada (aparece como "compre também", sem entrar sozinho no pedido). Semântica da
    transcrição do legado, não invenção deste módulo.
    """

    __tablename__ = "item_relacionado"
    __table_args__ = (
        pk_tenant("item_relacionado"),
        ForeignKeyConstraint(
            ["tenant_id", "grupo_id"],
            ["grupo_relacionado.tenant_id", "grupo_relacionado.id"],
            name="fk_item_relacionado_grupo",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "produto_id"],
            ["products.tenant_id", "products.id"],
            name="fk_item_relacionado_produto",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "variante_id"],
            ["product_variants.tenant_id", "product_variants.id"],
            name="fk_item_relacionado_variante",
            ondelete="RESTRICT",
        ),
        # `NULL` é o valor com significado ("sugestão", não "kit de zero unidades") — só
        # proíbe o zero/negativo explícito, não a ausência.
        CheckConstraint("quantidade IS NULL OR quantidade > 0", name="quantidade_positiva_ou_nula"),
    )

    grupo_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    produto_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    variante_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    quantidade: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    padrao: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

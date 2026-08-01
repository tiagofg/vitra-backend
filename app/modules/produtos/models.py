"""Produto, variante e o preço/estoque por empresa — herdado do bake-off.

Origem: as três tabelas viviam em `app/modules/bakeoff/`, mapeadas sobre `Base` puro (sem
auditoria) porque o schema do banco compartilhado do Neon era fixo e não tinha essas
colunas. Com o bake-off encerrado (S0.5) o módulo passa a ser o dono do próprio schema, e
os três modelos ganham `ModeloTenant` — PK composta e auditoria, como qualquer tabela nova
por empresa.

Ainda um esqueleto: a S2 acrescenta as ~20 colunas de catálogo do plano (fornecedor,
classificação, especificação JSONB) e as grades. Aqui só o que o bake-off provou: preço e
estoque não vivem no produto nem na variante, vivem numa terceira tabela.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
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

    variantes: Mapped[list[Variante]] = relationship(
        back_populates="produto", cascade="all, delete-orphan"
    )


class Variante(ModeloTenant, AtivoMixin):
    """`Acabamento × Tamanho`. Preço e estoque não moram aqui — moram abaixo, em
    `product_tenant`."""

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
            "tenant_id", "product_id", "finish", "size", name="uq_product_variants_produto"
        ),
    )

    produto_id: Mapped[uuid.UUID] = mapped_column("product_id", Uuid, nullable=False)
    acabamento: Mapped[str] = mapped_column("finish", String(80), nullable=False)
    tamanho: Mapped[str] = mapped_column("size", String(80), nullable=False)

    produto: Mapped[Produto] = relationship(back_populates="variantes")
    preco: Mapped[ProdutoEmpresa | None] = relationship(
        back_populates="variante", cascade="all, delete-orphan", uselist=False
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

    variante: Mapped[Variante] = relationship(back_populates="preco")

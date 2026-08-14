"""Orçamento, ambiente e item — a tela central do legado.

O diagrama `cabinet-minimo` traz as três (`quotes`, `quote_environments`, `quote_items`) e
elas não existiam no código. O que este módulo acrescenta ao que o diagrama desenha:

* **`profissional_id`, `vendedor_id`, `filial_id`, `centro_custo_id`** — o arquiteto que
  indicou a obra é metade do negócio nesse ramo (é a razão de `profissional_externo`
  existir), e o rateio precisa da filial e do centro de custo.
* **`origem_id`** — dois orçamentos do mesmo cliente no mesmo dia (21638/21639) são caso
  real do legado: é revisão, não duplicata. Sem a coluna, o encadeamento se perde.
* **`produto_id` no item, além de `variant_id`** — o *pré-produto* do legado: item que
  ainda não existe no catálogo, orçado pela descrição. Com só `variant_id` (como no
  diagrama) ele seria irrepresentável, e é caso corrente na tela.

**Todo texto de item é snapshot.** `descricao`, `acabamento`, `tamanho`, `unidade`,
`fornecedor_nome`, `grupo_produto` e `tipo_peca` são copiados do catálogo no instante em
que o item entra, e nunca mais mudam. Renomear o produto amanhã não pode reescrever o
orçamento que o cliente assinou ontem — é a mesma razão de `produto_fornecedor` guardar o
código e a descrição do fornecedor em vez de só a FK.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.base_model import ModeloTenant, pk_tenant
from app.common.mixins import ObservacaoMixin
from app.core.numbering import enum_col


class StatusOrcamento(enum.StrEnum):
    """`quotes.status`. Enum nativo, não o VARCHAR livre do diagrama.

    `cancelado` não é exclusão: a tela do legado troca `Excluir` por `Cancelar` justamente
    porque documento fiscalizável não some — ele muda de estado e continua na listagem.
    """

    rascunho = "rascunho"
    aberto = "aberto"
    fechado = "fechado"
    cancelado = "cancelado"


class ModoDesconto(enum.StrEnum):
    """`quotes.discount_mode`. Percentual sobre o total, ou valor absoluto em centavos."""

    percentual = "percentual"
    valor = "valor"


class Orcamento(ModeloTenant, ObservacaoMixin):
    __tablename__ = "quotes"
    __table_args__ = (
        pk_tenant("quotes"),
        # Numeração por empresa **e série**, sem buracos — quem gera é
        # `app.core.numbering.proximo_numero`. A UNIQUE é o que impede dois orçamentos
        # criados em paralelo na mesma série repetirem número; sem ela a garantia dependeria
        # da aplicação nunca ter uma corrida.
        UniqueConstraint("tenant_id", "series", "number", name="uq_quotes_tenant_serie_numero"),
        ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["partners.tenant_id", "partners.id"],
            name="fk_quotes_customer",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "site_id"],
            ["obra.tenant_id", "obra.id"],
            name="fk_quotes_site",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "professional_id"],
            ["partners.tenant_id", "partners.id"],
            name="fk_quotes_professional",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "filial_id"],
            ["filial.tenant_id", "filial.id"],
            name="fk_quotes_filial",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "centro_custo_id"],
            ["centro_custo.tenant_id", "centro_custo.id"],
            name="fk_quotes_centro_custo",
            ondelete="RESTRICT",
        ),
        # Auto-referência: a revisão aponta para o orçamento que a originou.
        ForeignKeyConstraint(
            ["tenant_id", "origem_id"],
            ["quotes.tenant_id", "quotes.id"],
            name="fk_quotes_origem",
            ondelete="RESTRICT",
        ),
        CheckConstraint("total_cents >= 0", name="quotes_total_nao_negativo"),
        CheckConstraint("discount_value >= 0", name="quotes_desconto_nao_negativo"),
        Index("ix_quotes_tenant_status", "tenant_id", "status"),
    )

    numero: Mapped[int] = mapped_column("number", BigInteger, nullable=False)
    serie: Mapped[str] = mapped_column("series", String(3), nullable=False, default="1")
    status: Mapped[StatusOrcamento] = mapped_column(
        enum_col(StatusOrcamento, "status_orcamento"),
        nullable=False,
        default=StatusOrcamento.rascunho,
    )
    emitido_em: Mapped[date | None] = mapped_column("issued_at", Date)
    expira_em: Mapped[date | None] = mapped_column("expires_at", Date)
    fechado_em: Mapped[date | None] = mapped_column("closed_at", Date)

    cliente_id: Mapped[uuid.UUID] = mapped_column("customer_id", Uuid, nullable=False)
    obra_id: Mapped[uuid.UUID | None] = mapped_column("site_id", Uuid)
    # O arquiteto/decorador que indicou. `partners` com `e_profissional=true` — é a mesma
    # tabela do cliente, discriminada pela bandeira.
    profissional_id: Mapped[uuid.UUID | None] = mapped_column("professional_id", Uuid)
    # FK simples: `employees` é global, sem `tenant_id` a carregar.
    vendedor_id: Mapped[uuid.UUID | None] = mapped_column(
        "seller_id", Uuid, ForeignKey("employees.id", ondelete="RESTRICT")
    )
    filial_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    centro_custo_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    origem_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)

    nome_projeto: Mapped[str | None] = mapped_column("project_name", String(160))
    numero_pasta: Mapped[str | None] = mapped_column("folder_number", String(30))
    categoria_id: Mapped[uuid.UUID | None] = mapped_column(
        "category_id", Uuid, ForeignKey("catalog_lookups.id", ondelete="RESTRICT")
    )

    modo_desconto: Mapped[ModoDesconto] = mapped_column(
        "discount_mode",
        enum_col(ModoDesconto, "modo_desconto"),
        nullable=False,
        default=ModoDesconto.percentual,
    )
    # Percentual com 4 casas: o total do legado mostra `Desconto 0,0010 %`. Quando
    # `modo_desconto=valor`, o mesmo campo guarda centavos — daí `Numeric` e não `BigInteger`.
    desconto_valor: Mapped[Decimal] = mapped_column(
        "discount_value", Numeric(14, 4), nullable=False, default=0
    )
    total_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    ambientes: Mapped[list[OrcamentoAmbiente]] = relationship(
        back_populates="orcamento", cascade="all, delete-orphan", lazy="selectin"
    )
    itens: Mapped[list[OrcamentoItem]] = relationship(
        back_populates="orcamento", cascade="all, delete-orphan", lazy="selectin"
    )


class OrcamentoAmbiente(ModeloTenant):
    """`Ambiente F5` da tela: cozinha, sala, dormitório. Agrupa itens dentro do orçamento —
    não é cadastro da obra, é recorte deste documento."""

    __tablename__ = "quote_environments"
    __table_args__ = (
        pk_tenant("quote_environments"),
        ForeignKeyConstraint(
            ["tenant_id", "quote_id"],
            ["quotes.tenant_id", "quotes.id"],
            name="fk_quote_environments_quote",
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "quote_id", "code", name="uq_quote_environments_codigo"),
    )

    orcamento_id: Mapped[uuid.UUID] = mapped_column("quote_id", Uuid, nullable=False)
    # VARCHAR, não o UUID que o diagrama mostra: é o código curto que o usuário digita
    # ("COZ", "SALA"), ao lado de `name` e `sort`. UUID ali é quase certamente erro de
    # geração do diagrama — um identificador opaco não conviveria com `sort` manual.
    codigo: Mapped[str] = mapped_column("code", String(20), nullable=False)
    nome: Mapped[str] = mapped_column("name", String(120), nullable=False)
    ordem: Mapped[int] = mapped_column("sort", Integer, nullable=False, default=0)

    orcamento: Mapped[Orcamento] = relationship(back_populates="ambientes")


class OrcamentoItem(ModeloTenant):
    __tablename__ = "quote_items"
    __table_args__ = (
        pk_tenant("quote_items"),
        ForeignKeyConstraint(
            ["tenant_id", "quote_id"],
            ["quotes.tenant_id", "quotes.id"],
            name="fk_quote_items_quote",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "environment_id"],
            ["quote_environments.tenant_id", "quote_environments.id"],
            name="fk_quote_items_environment",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "variant_id"],
            ["product_variants.tenant_id", "product_variants.id"],
            name="fk_quote_items_variant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_quote_items_product",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "supplier_id"],
            ["partners.tenant_id", "partners.id"],
            name="fk_quote_items_supplier",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "quote_id", "line_number", name="uq_quote_items_linha"),
        CheckConstraint("quantity > 0", name="quote_items_quantidade_positiva"),
        CheckConstraint("unit_price_cents >= 0", name="quote_items_preco_nao_negativo"),
        CheckConstraint("total_cents >= 0", name="quote_items_total_nao_negativo"),
        # O pré-produto: item sem catálogo. `descricao` é `NOT NULL`, então sempre há o que
        # mostrar na tela — mas variante e produto podem faltar os dois ao mesmo tempo.
        CheckConstraint(
            "variant_id IS NULL OR product_id IS NOT NULL",
            name="quote_items_variante_exige_produto",
        ),
    )

    orcamento_id: Mapped[uuid.UUID] = mapped_column("quote_id", Uuid, nullable=False)
    linha: Mapped[int] = mapped_column("line_number", Integer, nullable=False)
    ambiente_id: Mapped[uuid.UUID | None] = mapped_column("environment_id", Uuid)

    # Os dois nulos = pré-produto (orçado só pela descrição, ainda sem cadastro).
    produto_id: Mapped[uuid.UUID | None] = mapped_column("product_id", Uuid)
    variante_id: Mapped[uuid.UUID | None] = mapped_column("variant_id", Uuid)

    # --- snapshot: copiado do catálogo na entrada, nunca reescrito depois ---
    descricao: Mapped[str] = mapped_column("description", Text, nullable=False)
    acabamento: Mapped[str | None] = mapped_column("finish", String(60))
    tamanho: Mapped[str | None] = mapped_column("size", String(60))
    unidade: Mapped[str | None] = mapped_column("unit", String(20))
    fornecedor_nome: Mapped[str | None] = mapped_column("supplier_name", String(160))
    fornecedor_codigo: Mapped[str | None] = mapped_column("supplier_code", String(60))
    grupo_produto: Mapped[str | None] = mapped_column("product_group", String(60))
    tipo_peca: Mapped[str | None] = mapped_column("piece_type", String(60))

    fornecedor_id: Mapped[uuid.UUID | None] = mapped_column("supplier_id", Uuid)

    quantidade: Mapped[Decimal] = mapped_column("quantity", Numeric(14, 3), nullable=False)
    preco_unitario_cents: Mapped[int] = mapped_column(
        "unit_price_cents", BigInteger, nullable=False, default=0
    )
    desconto_pct: Mapped[Decimal] = mapped_column(
        "discount_pct", Numeric(7, 4), nullable=False, default=0
    )
    total_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    orcamento: Mapped[Orcamento] = relationship(back_populates="itens")

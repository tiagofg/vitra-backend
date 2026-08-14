"""Local, saldo e movimento de estoque.

O diagrama `cabinet-minimo` troca a coluna `stock_qty` que vivia em `product_tenant` por
três tabelas, e a troca compra duas coisas que a coluna não dava:

* **Saldo por local.** Uma empresa com depósito e loja precisa saber onde as 12 unidades
  estão, não só que existem 12. `stock_balances` é por `(variante, local)`.
* **História.** `stock_movements` é o extrato: quem mexeu, quando, por quê, e qual era o
  saldo depois. Uma coluna solta responde "quanto tem"; ela nunca responde "por que mudou".

`saldo_apos` é redundante com a soma dos `delta` **de propósito** — é o extrato do legado,
que mostra o saldo em cada linha. Recalcular a soma a cada leitura seria varrer o histórico
inteiro; gravar o valor no momento do movimento é o que torna a listagem barata. Quem
garante que os dois não divergem é `EstoqueService.movimentar`, que só escreve os dois
juntos, sob o mesmo `SELECT ... FOR UPDATE` do saldo.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.base_model import ModeloTenant, pk_tenant
from app.common.mixins import AtivoMixin
from app.core.numbering import enum_col


class TipoLocalEstoque(enum.StrEnum):
    """`stock_locations.kind`. Enum nativo, não o VARCHAR livre do diagrama: os quatro
    valores são fechados, e um typo em texto livre viraria um local fantasma que nenhuma
    consulta acha."""

    deposito = "deposito"
    loja = "loja"
    obra = "obra"
    transito = "transito"


class MotivoMovimento(enum.StrEnum):
    """`stock_movements.reason`. O `delta` diz quanto; o motivo diz por quê — e é por ele
    que o extrato é filtrado na tela."""

    entrada_compra = "entrada_compra"
    saida_venda = "saida_venda"
    devolucao = "devolucao"
    transferencia = "transferencia"
    ajuste = "ajuste"
    inventario = "inventario"


class OrigemMovimento(enum.StrEnum):
    """`stock_movements.source_kind`. O diagrama deixa `source_kind`/`source_id` como
    referência polimórfica sem destino declarado; este enum é o destino, explícito. Sem FK
    de verdade — é o preço de uma referência polimórfica, e por isso `origem_id` **não** é
    conferido pelo banco. Quem grava é responsável por apontar para algo que existe."""

    orcamento = "orcamento"
    pedido_venda = "pedido_venda"
    pedido_compra = "pedido_compra"
    ajuste_manual = "ajuste_manual"
    inventario = "inventario"


class LocalEstoque(ModeloTenant, AtivoMixin):
    __tablename__ = "stock_locations"
    __table_args__ = (
        pk_tenant("stock_locations"),
        UniqueConstraint("tenant_id", "code", name="uq_stock_locations_tenant_code"),
    )

    codigo: Mapped[str] = mapped_column("code", String(20), nullable=False)
    nome: Mapped[str] = mapped_column("name", String(120), nullable=False, index=True)
    tipo: Mapped[TipoLocalEstoque] = mapped_column(
        "kind",
        enum_col(TipoLocalEstoque, "tipo_local_estoque"),
        nullable=False,
        default=TipoLocalEstoque.deposito,
    )


class SaldoEstoque(ModeloTenant):
    """Quanto tem de uma variante num local. Uma linha por par — é a `UNIQUE` que garante
    isso, e sem ela o saldo duplicaria em silêncio (o diagrama não declara nenhuma).

    Sem `AtivoMixin`: saldo não é cadastro, não se "desativa". Zera.
    """

    __tablename__ = "stock_balances"
    __table_args__ = (
        pk_tenant("stock_balances"),
        ForeignKeyConstraint(
            ["tenant_id", "variant_id"],
            ["product_variants.tenant_id", "product_variants.id"],
            name="fk_stock_balances_variant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["stock_locations.tenant_id", "stock_locations.id"],
            name="fk_stock_balances_location",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "tenant_id", "variant_id", "location_id", name="uq_stock_balances_variante_local"
        ),
        # Estoque negativo é erro de operação, não estado válido. `EstoqueService.movimentar`
        # recusa antes de chegar aqui com uma mensagem de negócio; este CHECK é a rede que
        # pega quem escrever pela lateral.
        CheckConstraint("qty >= 0", name="qty_nao_negativo"),
    )

    variante_id: Mapped[uuid.UUID] = mapped_column("variant_id", Uuid, nullable=False)
    local_id: Mapped[uuid.UUID] = mapped_column("location_id", Uuid, nullable=False)
    quantidade: Mapped[Decimal] = mapped_column("qty", Numeric(14, 3), nullable=False, default=0)


class MovimentoEstoque(ModeloTenant):
    """Uma linha do extrato. Nunca é editada nem apagada — corrigir um movimento errado é
    lançar o movimento inverso, como em qualquer razão contábil. O serviço não expõe
    `atualizar`/`desativar` por isso."""

    __tablename__ = "stock_movements"
    __table_args__ = (
        pk_tenant("stock_movements"),
        ForeignKeyConstraint(
            ["tenant_id", "variant_id"],
            ["product_variants.tenant_id", "product_variants.id"],
            name="fk_stock_movements_variant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["stock_locations.tenant_id", "stock_locations.id"],
            name="fk_stock_movements_location",
            ondelete="RESTRICT",
        ),
        # `delta` zero não é movimento — é ruído no extrato.
        CheckConstraint("delta <> 0", name="delta_nao_zero"),
        # O extrato é sempre lido por variante+local, do mais recente para o mais antigo.
        Index(
            "ix_stock_movements_extrato",
            "tenant_id",
            "variant_id",
            "location_id",
            "occurred_at",
        ),
    )

    variante_id: Mapped[uuid.UUID] = mapped_column("variant_id", Uuid, nullable=False)
    local_id: Mapped[uuid.UUID] = mapped_column("location_id", Uuid, nullable=False)
    # Assinado: entrada é positivo, saída é negativo. Um par (quantidade, sentido) exigiria
    # que todo somatório soubesse interpretar o sentido; `delta` só precisa de `SUM()`.
    delta: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    motivo: Mapped[MotivoMovimento] = mapped_column(
        "reason", enum_col(MotivoMovimento, "motivo_movimento"), nullable=False
    )
    origem_tipo: Mapped[OrigemMovimento | None] = mapped_column(
        "source_kind", enum_col(OrigemMovimento, "origem_movimento")
    )
    origem_id: Mapped[uuid.UUID | None] = mapped_column("source_id", Uuid)
    saldo_apos: Mapped[Decimal] = mapped_column("balance_after", Numeric(14, 3), nullable=False)
    ocorrido_em: Mapped[datetime] = mapped_column(
        "occurred_at", DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # FK simples: `employees` é global, sem `tenant_id` — não há chave composta a carregar.
    # Nulável porque movimento de seed/importação não tem autor.
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="SET NULL")
    )

    local: Mapped[LocalEstoque] = relationship(
        lazy="joined",
        primaryjoin=(
            "and_(MovimentoEstoque.tenant_id == LocalEstoque.tenant_id, "
            "MovimentoEstoque.local_id == LocalEstoque.id)"
        ),
        viewonly=True,
    )

"""As 7 tabelas do bake-off.

O schema é **fixo**: as três stacks em disputa apontam para o mesmo banco `vitra_bakeoff`
no Neon, e ninguém cria, altera ou apaga tabela lá. Estes modelos existem para (a) mapear
esse schema e (b) permitir que a migração o recrie, idêntico, num Postgres descartável —
que é onde o RLS se testa.

**Idioma.** Tabela e coluna em inglês porque o schema compartilhado é assim e não se mexe
nele. Classe, serviço, rota e mensagem de erro em português, que é a língua do domínio e
da equipe. O mapeamento explícito do SQLAlchemy absorve a diferença.

Sem `criado_em` / `atualizado_em` / `criado_por_id`: o schema do bake-off não os tem, e
inventá-los aqui faria a migração local divergir do banco compartilhado — exatamente o que
ela existe para evitar. As colunas de auditoria voltam no VITRA real.
"""

from __future__ import annotations

import enum
import uuid
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.base_model import Base
from app.common.mixins import TenantScopedMixin


class PapelEmpresa(enum.StrEnum):
    """Os 5 papéis de `employee_company`.

    Papel **fixo** por empresa, não o RBAC recurso+ação do plano. Para o bake-off basta;
    para o VITRA real o papel vira o *grupo* a que a pessoa pertence naquela empresa, e as
    permissões seguem penduradas no grupo. A ponte está aberta no plano.

    Gravado como texto, não como tipo `ENUM` do Postgres: o schema compartilhado é fixo e
    não dá para conferir se lá existe o tipo. Texto é o palpite que não quebra a escrita.
    """

    owner = "owner"
    admin = "admin"
    operator_full = "operator-full"
    operator_sales = "operator-sales"
    viewer = "viewer"


# --- globais: sem tenant_id, sem RLS ------------------------------------------


class Empresa(Base):
    """Um CNPJ = uma linha. É a raiz do recorte, e por isso ela própria não é recortada."""

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    # varchar(14), caixa alta, sem máscara — já pronto para o CNPJ alfanumérico, que passa
    # a valer em 31/07/2026. Máscara no banco tornaria a virada uma migração de dados.
    cnpj: Mapped[str | None] = mapped_column(String(14), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Colaborador(Base):
    """Identidade única no grupo. O papel é por empresa e mora em `employee_company`."""

    __tablename__ = "employees"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ValorApoio(Base):
    """A tabela de apoio genérica dos 19 `[combo +...]`, discriminada por `kind`.

    O schema do bake-off resolveu uma dúvida que o plano deixava em aberto: ela é
    **global**. Os 19 combos são vocabulário do grupo, não de cada loja.
    """

    __tablename__ = "catalog_lookups"
    __table_args__ = (
        # A unique constraint já cria o índice `(kind, name)` que a busca por domínio usa.
        # Um `Index` com as mesmas colunas seria uma segunda cópia da mesma estrutura.
        UniqueConstraint("kind", "name", name="uq_catalog_lookups_kind_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


# --- por empresa: PK composta, RLS FORCE --------------------------------------


class Produto(Base, TenantScopedMixin):
    __tablename__ = "products"
    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "id", name="pk_products"),
        UniqueConstraint("tenant_id", "code", name="uq_products_tenant_code"),
        Index("ix_products_tenant_description", "tenant_id", "description"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    variantes: Mapped[list[Variante]] = relationship(
        back_populates="produto", cascade="all, delete-orphan"
    )


class Variante(Base, TenantScopedMixin):
    """`Acabamento × Tamanho`. Preço e estoque não moram aqui — moram abaixo, em
    `product_tenant`."""

    __tablename__ = "product_variants"
    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "id", name="pk_product_variants"),
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

    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    finish: Mapped[str] = mapped_column(String(80), nullable=False)
    size: Mapped[str] = mapped_column(String(80), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    produto: Mapped[Produto] = relationship(back_populates="variantes")
    preco: Mapped[ProdutoEmpresa | None] = relationship(
        back_populates="variante", cascade="all, delete-orphan", uselist=False
    )


class ProdutoEmpresa(Base, TenantScopedMixin):
    """Preço e estoque da variante naquela empresa.

    Repare no que a FK composta compra: esta linha só consegue apontar para uma variante
    **da mesma empresa**. Não é convenção nem validação de serviço — o `INSERT` falha.
    """

    __tablename__ = "product_tenant"
    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "id", name="pk_product_tenant"),
        ForeignKeyConstraint(
            ["tenant_id", "variant_id"],
            ["product_variants.tenant_id", "product_variants.id"],
            name="fk_product_tenant_variant",
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "variant_id", name="uq_product_tenant_variant"),
        # A convenção de nomes já prefixa `ck_<tabela>_`; repetir aqui sairia duplicado.
        CheckConstraint("stock_qty >= 0", name="stock_qty_nao_negativo"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    variant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    # Dinheiro é inteiro em centavos. R$ 12,34 é 1234. Nunca float, nunca Numeric —
    # converter para reais é responsabilidade do schema de saída, não do banco.
    price_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    stock_qty: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, default=0)
    min_stock: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, default=0)

    variante: Mapped[Variante] = relationship(back_populates="preco")


class ColaboradorEmpresa(Base, TenantScopedMixin):
    """Papel da pessoa naquela empresa. Uma pessoa, N papéis — um por empresa.

    ANA SILVA é `admin` na ABACAXI e `operator-sales` na UVA. Mesma identidade global,
    autorização diferente de cada lado: é o caso que prova por que o papel não pode ser
    coluna de `employees`.
    """

    __tablename__ = "employee_company"
    __table_args__ = (PrimaryKeyConstraint("tenant_id", "employee_id", name="pk_employee_company"),)

    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)

    colaborador: Mapped[Colaborador] = relationship(lazy="joined")


# Tabelas que o RLS protege.
#
# A migração **não** lê daqui, de propósito: migração é foto do schema num instante do
# tempo, e se ela lesse o modelo, mudar o modelo amanhã reescreveria o passado. Ela repete
# a lista. Quem cruza as duas é `test_toda_tabela_com_tenant_id_tem_rls_forcado`, que
# descobre no catálogo do Postgres quem tem `tenant_id` e cobra que o conjunto bata com
# esta constante — então divergir entre modelo e migração reprova, em vez de passar calado.
TABELAS_POR_EMPRESA: tuple[str, ...] = (
    Produto.__tablename__,
    Variante.__tablename__,
    ProdutoEmpresa.__tablename__,
    ColaboradorEmpresa.__tablename__,
)

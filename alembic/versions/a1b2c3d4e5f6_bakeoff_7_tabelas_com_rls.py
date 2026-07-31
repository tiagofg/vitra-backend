"""bake-off: as 7 tabelas, chave composta e RLS

Recria localmente, num Postgres descartável, o schema fixo do banco compartilhado
`vitra_bakeoff`. Nunca rode isto contra o Neon: lá a estrutura é fixa e as outras duas
stacks do bake-off estão apontando para as mesmas tabelas.

O RLS vai em SQL cru de propósito. O Alembic não modela política de segurança, e deixá-la
fora da migração seria pior que não tê-la: o banco de um dev teria a trava, o do outro não,
e nenhum teste reclamaria.

Revision ID: a1b2c3d4e5f6
Revises: 0402c7bf6bee
Create Date: 2026-07-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "0402c7bf6bee"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Repetida aqui, e não importada de `app.modules.bakeoff.models`: migração é foto do
# schema num instante do tempo. Se ela lesse o modelo, mudar o modelo amanhã reescreveria
# o passado — e o `upgrade` deixaria de reproduzir o que produziu na primeira vez.
TABELAS_POR_EMPRESA = ("products", "product_variants", "product_tenant", "employee_company")

# Papel de runtime da aplicação. Ele **não** é dono das tabelas e **não** tem BYPASSRLS —
# sem essas duas coisas o RLS é decorativo, porque o dono ignora a política por padrão e o
# superusuário a ignora sempre. Criado sem LOGIN: é um papel de grupo, e quem loga (dev,
# teste, produção) é um usuário concedido a ele, com senha que nunca entra no repositório.
PAPEL_RUNTIME = "vitra_app"

# O predicado das quatro políticas. O `NULLIF` não é zelo: sem ele, uma conexão de pool que
# ainda não recebeu `SET LOCAL` tentaria converter string vazia para uuid e **estouraria**,
# em vez de simplesmente não casar. Com ele o predicado dá NULL, nada casa, e a consulta
# volta vazia — que é a propriedade que se está comprando.
PREDICADO = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("cnpj", sa.String(length=14), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_tenants"),
        sa.UniqueConstraint("cnpj", name="uq_tenants_cnpj"),
    )

    op.create_table(
        "employees",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("email", sa.String(length=160), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_employees"),
        sa.UniqueConstraint("email", name="uq_employees_email"),
    )

    op.create_table(
        "catalog_lookups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_catalog_lookups"),
        sa.UniqueConstraint("kind", "name", name="uq_catalog_lookups_kind_name"),
    )

    op.create_table(
        "products",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_products_tenant_id", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name="pk_products"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_products_tenant_code"),
    )
    # Único índice além dos que PK e unique já criam: a listagem ordena e busca por
    # `description` dentro de uma empresa. Índice sobre `tenant_id` sozinho seria
    # redundante — a PK composta já o tem como coluna líder.
    op.create_index("ix_products_tenant_description", "products", ["tenant_id", "description"])

    op.create_table(
        "product_variants",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("finish", sa.String(length=80), nullable=False),
        sa.Column("size", sa.String(length=80), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        # A FK leva o `tenant_id` junto — é o que torna *fisicamente impossível* ligar a
        # variante de uma empresa ao produto de outra.
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_product_variants_product",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_product_variants_tenant_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name="pk_product_variants"),
        sa.UniqueConstraint(
            "tenant_id", "product_id", "finish", "size", name="uq_product_variants_produto"
        ),
    )

    op.create_table(
        "product_tenant",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("variant_id", sa.Uuid(), nullable=False),
        # Dinheiro é inteiro em centavos. R$ 12,34 é 1234.
        sa.Column("price_cents", sa.BigInteger(), nullable=False),
        sa.Column("stock_qty", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("min_stock", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.CheckConstraint("stock_qty >= 0", name="ck_product_tenant_stock_qty_nao_negativo"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "variant_id"],
            ["product_variants.tenant_id", "product_variants.id"],
            name="fk_product_tenant_variant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_product_tenant_tenant_id", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name="pk_product_tenant"),
        sa.UniqueConstraint("tenant_id", "variant_id", name="uq_product_tenant_variant"),
    )

    op.create_table(
        "employee_company",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employees.id"],
            name="fk_employee_company_employee_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_employee_company_tenant_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "employee_id", name="pk_employee_company"),
    )

    _criar_papel_runtime()
    for tabela in TABELAS_POR_EMPRESA:
        _ligar_rls(tabela)


def downgrade() -> None:
    # Sem desligar RLS antes: política é objeto dependente da tabela, e o `DROP TABLE`
    # leva as quatro junto. Desligar primeiro era trabalho morto — e trabalho morto numa
    # migração é pior que inútil, porque parece necessário para quem lê depois.
    op.drop_table("employee_company")
    op.drop_table("product_tenant")
    op.drop_table("product_variants")
    op.drop_table("products")
    op.drop_table("catalog_lookups")
    op.drop_table("employees")
    op.drop_table("tenants")

    # Nada a revogar, e nenhum `DROP ROLE`.
    #
    # Os `GRANT` por tabela morreram com o `DROP TABLE` acima — privilégio é dependente do
    # objeto. Sobra o `USAGE ON SCHEMA public`, que fica de propósito: o papel pode ter
    # privilégio em outras tabelas do banco, e tirar o `USAGE` derrubaria o acesso a elas
    # tão bem quanto um `DROP ROLE` derrubaria. A versão anterior deste arquivo fazia
    # `REVOKE ALL ON SCHEMA public` logo abaixo de um comentário explicando por que não
    # se devia quebrar esse acesso.


def _criar_papel_runtime() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{PAPEL_RUNTIME}') THEN
                CREATE ROLE {PAPEL_RUNTIME} NOLOGIN NOBYPASSRLS;
            END IF;
        END
        $$
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {PAPEL_RUNTIME}")
    # Só DML. Nada de OWNER, nada de DDL: um papel que pudesse `ALTER TABLE` poderia
    # desligar a própria política — e o teste de isolamento nº 4 existe para provar isso.
    for tabela in TABELAS_POR_EMPRESA + ("tenants", "employees", "catalog_lookups"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {tabela} TO {PAPEL_RUNTIME}")


def _ligar_rls(tabela: str) -> None:
    # ENABLE sozinho não basta: o dono da tabela ignora RLS por padrão. FORCE é o que faz a
    # política valer também para ele. Superusuário continua passando por cima — daí a
    # aplicação nunca conectar como superusuário nem como dono.
    op.execute(f"ALTER TABLE {tabela} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {tabela} FORCE ROW LEVEL SECURITY")

    # Quatro políticas, uma por comando, todas sobre o mesmo predicado. Uma política única
    # com FOR ALL seria mais curta e esconderia a assimetria que importa: SELECT/DELETE
    # filtram o que já existe (USING), INSERT valida o que está entrando (WITH CHECK), e
    # UPDATE precisa dos dois — senão dá para mover uma linha para outra empresa.
    op.execute(f'CREATE POLICY "{tabela}_sel" ON {tabela} FOR SELECT USING ({PREDICADO})')
    op.execute(f'CREATE POLICY "{tabela}_ins" ON {tabela} FOR INSERT WITH CHECK ({PREDICADO})')
    op.execute(
        f'CREATE POLICY "{tabela}_upd" ON {tabela} FOR UPDATE '
        f"USING ({PREDICADO}) WITH CHECK ({PREDICADO})"
    )
    op.execute(f'CREATE POLICY "{tabela}_del" ON {tabela} FOR DELETE USING ({PREDICADO})')

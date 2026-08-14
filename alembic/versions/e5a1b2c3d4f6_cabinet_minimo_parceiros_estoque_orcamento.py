"""cabinet-minimo: parceiros unificados, estoque e orçamento

Converge o schema com o diagrama `cabinet-minimo`. Três movimentos, nesta ordem — e a ordem
importa, porque `quotes` referencia `partners`, e `stock_balances` recebe o saldo que sai de
`product_tenant`:

1. **`partners` + `partner_tenant_links`.** `cliente`, `fornecedor` e `profissional_externo`
   viram uma tabela só, discriminada por três bandeiras. Os dados são migrados preservando
   o `id` de cada linha — é o que faz `obra.cliente_id` e `fornecedor_empresa.fornecedor_id`
   continuarem apontando para a pessoa certa depois do `ALTER ... RENAME`, sem mapa de
   de-para. As três tabelas antigas só caem depois disso.

2. **Estoque.** `stock_locations`/`stock_balances`/`stock_movements` nascem, e a coluna
   `product_tenant.stock_qty` é convertida em saldo de um local `PADRAO` criado por empresa
   que tenha estoque. A tabela é renomeada para `variant_tenant_settings` e `price_cents`
   para `sale_price_cents`.

3. **Orçamento.** `quotes`/`quote_environments`/`quote_items`, mais os enums que elas usam.

Todas as tabelas novas nascem sob RLS, na mesma forma de `af281e86c3d5`/`b1c2d3e4f5a6`:
`FORCE ROW LEVEL SECURITY` + as quatro políticas + `GRANT` de DML para `vitra_app`.

**Colisão de código.** `uq_partners_tenant_codigo` é por `(tenant_id, codigo)`, e nada
impedia `CLI001` existir em `cliente` e em `fornecedor` da mesma empresa. Em vez de
renomear em silêncio (dado de negócio fabricado pela migração) ou estourar um
`UniqueViolation` que não explica nada, `_exigir_codigos_sem_colisao()` consulta antes e
falha com a lista exata do que precisa ser resolvido à mão. Mesma escolha de
`_exigir_tabela_vazia()` na migração `d2cf768cdc65`.

Revision ID: e5a1b2c3d4f6
Revises: d2cf768cdc65
Create Date: 2026-08-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e5a1b2c3d4f6"
down_revision: str | None = "d2cf768cdc65"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PAPEL_RUNTIME = "vitra_app"
PREDICADO = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"

TABELAS_NOVAS = (
    "partners",
    "partner_tenant_links",
    "stock_locations",
    "stock_balances",
    "stock_movements",
    "quotes",
    "quote_environments",
    "quote_items",
)

TABELAS_REMOVIDAS = ("cliente", "fornecedor", "profissional_externo")


def _ligar_rls(tabela: str) -> None:
    op.execute(f"ALTER TABLE {tabela} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {tabela} FORCE ROW LEVEL SECURITY")
    op.execute(f'CREATE POLICY "{tabela}_sel" ON {tabela} FOR SELECT USING ({PREDICADO})')
    op.execute(f'CREATE POLICY "{tabela}_ins" ON {tabela} FOR INSERT WITH CHECK ({PREDICADO})')
    op.execute(
        f'CREATE POLICY "{tabela}_upd" ON {tabela} FOR UPDATE '
        f"USING ({PREDICADO}) WITH CHECK ({PREDICADO})"
    )
    op.execute(f'CREATE POLICY "{tabela}_del" ON {tabela} FOR DELETE USING ({PREDICADO})')
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {tabela} TO {PAPEL_RUNTIME}")


def _desligar_rls(tabela: str) -> None:
    op.execute(f"ALTER TABLE {tabela} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {tabela} DISABLE ROW LEVEL SECURITY")
    for sufixo in ("sel", "ins", "upd", "del"):
        op.execute(f'DROP POLICY IF EXISTS "{tabela}_{sufixo}" ON {tabela}')
    op.execute(f"REVOKE ALL ON {tabela} FROM {PAPEL_RUNTIME}")


def _exigir_codigos_sem_colisao() -> None:
    """`cliente`, `fornecedor` e `profissional_externo` viram uma tabela com UNIQUE por
    `(tenant_id, codigo)`. Se o mesmo código existir em duas delas na mesma empresa, a
    migração não tem como decidir qual mantém — e renomear sozinha seria inventar dado."""
    conexao = op.get_bind()
    colisoes = conexao.execute(
        sa.text(
            """
            SELECT tenant_id, codigo, count(*) AS quantas
            FROM (
                SELECT tenant_id, codigo FROM cliente
                UNION ALL SELECT tenant_id, codigo FROM fornecedor
                UNION ALL SELECT tenant_id, codigo FROM profissional_externo
            ) AS todos
            GROUP BY tenant_id, codigo
            HAVING count(*) > 1
            ORDER BY tenant_id, codigo
            """
        )
    ).all()
    if colisoes:
        detalhe = ", ".join(
            f"{linha.tenant_id}/{linha.codigo} (x{linha.quantas})" for linha in colisoes
        )
        raise RuntimeError(
            "Código repetido entre cliente/fornecedor/profissional_externo na mesma empresa: "
            f"{detalhe}. Renomeie um dos lados antes de rodar esta migração — `partners` "
            "exige código único por empresa."
        )


def upgrade() -> None:
    # --- 1. partners ------------------------------------------------------------
    _exigir_codigos_sem_colisao()

    op.create_table(
        "partners",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("codigo", sa.String(length=20), nullable=False),
        sa.Column("legal_name", sa.String(length=160), nullable=False),
        sa.Column("trade_name", sa.String(length=160), nullable=True),
        sa.Column(
            "tipo_pessoa",
            postgresql.ENUM(name="tipo_pessoa", create_type=False),
            nullable=False,
        ),
        sa.Column("document", sa.String(length=14), nullable=True),
        sa.Column("rg_ie", sa.String(length=20), nullable=True),
        sa.Column("dt_nascimento", sa.Date(), nullable=True),
        sa.Column("is_customer", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_supplier", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_professional", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("registration", sa.String(length=30), nullable=True),
        sa.Column("payout_bank_details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("profissao_id", sa.Uuid(), nullable=True),
        sa.Column("estado_civil_id", sa.Uuid(), nullable=True),
        sa.Column("raca_cor_id", sa.Uuid(), nullable=True),
        sa.Column("nacionalidade_id", sa.Uuid(), nullable=True),
        sa.Column("categoria_id", sa.Uuid(), nullable=True),
        sa.Column("transportadora_padrao_id", sa.Uuid(), nullable=True),
        sa.Column("endereco_cep", sa.String(length=9), nullable=True),
        sa.Column("endereco_logradouro", sa.String(length=160), nullable=True),
        sa.Column("endereco_numero", sa.String(length=20), nullable=True),
        sa.Column("endereco_complemento", sa.String(length=80), nullable=True),
        sa.Column("endereco_bairro", sa.String(length=80), nullable=True),
        sa.Column("endereco_ponto_referencia", sa.String(length=160), nullable=True),
        sa.Column("endereco_cidade_id", sa.Uuid(), nullable=True),
        sa.Column("telefone", sa.String(length=20), nullable=True),
        sa.Column("telefone_secundario", sa.String(length=20), nullable=True),
        sa.Column("celular", sa.String(length=20), nullable=True),
        sa.Column("fax", sa.String(length=20), nullable=True),
        sa.Column("email", sa.String(length=160), nullable=True),
        sa.Column("email_secundario", sa.String(length=160), nullable=True),
        sa.Column("site", sa.String(length=160), nullable=True),
        sa.Column("observacao", sa.String(length=2000), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "atualizado_em",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("criado_por_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("tenant_id", "id", name="pk_partners"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_partners_tenant_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["endereco_cidade_id"],
            ["cidade.id"],
            name="fk_partners_endereco_cidade_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["profissao_id"],
            ["catalog_lookups.id"],
            name="fk_partners_profissao_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["estado_civil_id"],
            ["catalog_lookups.id"],
            name="fk_partners_estado_civil_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["raca_cor_id"],
            ["catalog_lookups.id"],
            name="fk_partners_raca_cor_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["nacionalidade_id"],
            ["catalog_lookups.id"],
            name="fk_partners_nacionalidade_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["categoria_id"],
            ["catalog_lookups.id"],
            name="fk_partners_categoria_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "transportadora_padrao_id"],
            ["transportadora.tenant_id", "transportadora.id"],
            name="fk_partners_transportadora_padrao",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "codigo", name="uq_partners_tenant_codigo"),
        sa.CheckConstraint(
            "is_customer OR is_supplier OR is_professional",
            name="partners_ao_menos_um_papel",
        ),
    )
    op.create_index("ix_partners_tenant_legal_name", "partners", ["tenant_id", "legal_name"])
    op.create_index("ix_partners_active", "partners", ["active"])
    op.create_foreign_key(
        "fk_partners_criado_por_id",
        "partners",
        "employees",
        ["criado_por_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Preserva o `id`: é o que faz `obra` e `fornecedor_empresa` continuarem válidas.
    op.execute(
        """
        INSERT INTO partners (
            tenant_id, id, codigo, legal_name, trade_name, tipo_pessoa, document, rg_ie,
            dt_nascimento, is_customer, is_supplier, is_professional,
            profissao_id, estado_civil_id, raca_cor_id, nacionalidade_id, categoria_id,
            endereco_cep, endereco_logradouro, endereco_numero, endereco_complemento,
            endereco_bairro, endereco_ponto_referencia, endereco_cidade_id,
            telefone, telefone_secundario, celular, fax, email, email_secundario, site,
            observacao, active, criado_em, atualizado_em, criado_por_id
        )
        SELECT
            tenant_id, id, codigo, nome, NULL, tipo_pessoa, cpf_cnpj, rg_ie,
            dt_nascimento, true, false, false,
            profissao_id, estado_civil_id, raca_cor_id, nacionalidade_id, categoria_id,
            endereco_cep, endereco_logradouro, endereco_numero, endereco_complemento,
            endereco_bairro, endereco_ponto_referencia, endereco_cidade_id,
            telefone, telefone_secundario, celular, fax, email, email_secundario, site,
            observacao, active, criado_em, atualizado_em, criado_por_id
        FROM cliente
        """
    )
    op.execute(
        """
        INSERT INTO partners (
            tenant_id, id, codigo, legal_name, trade_name, tipo_pessoa, document,
            is_customer, is_supplier, is_professional, transportadora_padrao_id,
            endereco_cep, endereco_logradouro, endereco_numero, endereco_complemento,
            endereco_bairro, endereco_ponto_referencia, endereco_cidade_id,
            telefone, telefone_secundario, celular, fax, email, email_secundario, site,
            active, criado_em, atualizado_em, criado_por_id
        )
        SELECT
            tenant_id, id, codigo, razao_social, nome_fantasia, 'juridica'::tipo_pessoa, cnpj,
            false, true, false, transportadora_padrao_id,
            endereco_cep, endereco_logradouro, endereco_numero, endereco_complemento,
            endereco_bairro, endereco_ponto_referencia, endereco_cidade_id,
            telefone, telefone_secundario, celular, fax, email, email_secundario, site,
            active, criado_em, atualizado_em, criado_por_id
        FROM fornecedor
        """
    )
    op.execute(
        """
        INSERT INTO partners (
            tenant_id, id, codigo, legal_name, tipo_pessoa, document,
            is_customer, is_supplier, is_professional, registration, profissao_id,
            endereco_cep, endereco_logradouro, endereco_numero, endereco_complemento,
            endereco_bairro, endereco_ponto_referencia, endereco_cidade_id,
            telefone, telefone_secundario, celular, fax, email, email_secundario, site,
            active, criado_em, atualizado_em, criado_por_id
        )
        SELECT
            tenant_id, id, codigo, nome, tipo_pessoa, cpf_cnpj,
            false, false, true, crea_cau, profissao_id,
            endereco_cep, endereco_logradouro, endereco_numero, endereco_complemento,
            endereco_bairro, endereco_ponto_referencia, endereco_cidade_id,
            telefone, telefone_secundario, celular, fax, email, email_secundario, site,
            active, criado_em, atualizado_em, criado_por_id
        FROM profissional_externo
        """
    )

    op.create_table(
        "partner_tenant_links",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("partner_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=True),
        sa.Column("payment_terms", sa.String(length=60), nullable=True),
        sa.Column("credit_limit_cents", sa.BigInteger(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "atualizado_em",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("criado_por_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("tenant_id", "id", name="pk_partner_tenant_links"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_partner_tenant_links_tenant_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "partner_id"],
            ["partners.tenant_id", "partners.id"],
            name="fk_partner_tenant_links_partner",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("tenant_id", "partner_id", name="uq_partner_tenant_links_partner"),
        sa.CheckConstraint(
            "credit_limit_cents IS NULL OR credit_limit_cents >= 0",
            name="credit_limit_nao_negativo",
        ),
    )
    op.create_index("ix_partner_tenant_links_active", "partner_tenant_links", ["active"])
    op.create_foreign_key(
        "fk_partner_tenant_links_criado_por_id",
        "partner_tenant_links",
        "employees",
        ["criado_por_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # `obra` e `fornecedor_empresa` passam a apontar para `partners`.
    op.drop_constraint("fk_obra_cliente", "obra", type_="foreignkey")
    op.alter_column("obra", "cliente_id", new_column_name="parceiro_id")
    op.create_foreign_key(
        "fk_obra_parceiro",
        "obra",
        "partners",
        ["tenant_id", "parceiro_id"],
        ["tenant_id", "id"],
        ondelete="CASCADE",
    )

    op.drop_index("uq_fornecedor_empresa_vigente", table_name="fornecedor_empresa")
    op.drop_constraint("fk_fornecedor_empresa_fornecedor", "fornecedor_empresa", type_="foreignkey")
    op.alter_column("fornecedor_empresa", "fornecedor_id", new_column_name="parceiro_id")
    op.create_foreign_key(
        "fk_fornecedor_empresa_parceiro",
        "fornecedor_empresa",
        "partners",
        ["tenant_id", "parceiro_id"],
        ["tenant_id", "id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "uq_fornecedor_empresa_vigente",
        "fornecedor_empresa",
        ["tenant_id", "parceiro_id"],
        unique=True,
        postgresql_where=sa.text("vigencia_fim IS NULL"),
    )

    # `produto_fornecedor.fornecedor_id` também apontava para `fornecedor`. A coluna não
    # muda de nome — é o papel que importa ali —, só o destino da FK.
    op.drop_constraint("fk_produto_fornecedor_fornecedor", "produto_fornecedor", type_="foreignkey")
    op.create_foreign_key(
        "fk_produto_fornecedor_fornecedor",
        "produto_fornecedor",
        "partners",
        ["tenant_id", "fornecedor_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )

    for tabela in TABELAS_REMOVIDAS:
        _desligar_rls(tabela)
        op.drop_table(tabela)

    # --- 2. estoque -------------------------------------------------------------
    tipo_local = postgresql.ENUM("deposito", "loja", "obra", "transito", name="tipo_local_estoque")
    tipo_local.create(op.get_bind())
    motivo_movimento = postgresql.ENUM(
        "entrada_compra",
        "saida_venda",
        "devolucao",
        "transferencia",
        "ajuste",
        "inventario",
        name="motivo_movimento",
    )
    motivo_movimento.create(op.get_bind())
    origem_movimento = postgresql.ENUM(
        "orcamento",
        "pedido_venda",
        "pedido_compra",
        "ajuste_manual",
        "inventario",
        name="origem_movimento",
    )
    origem_movimento.create(op.get_bind())

    op.create_table(
        "stock_locations",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "kind", postgresql.ENUM(name="tipo_local_estoque", create_type=False), nullable=False
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "atualizado_em",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("criado_por_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("tenant_id", "id", name="pk_stock_locations"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_stock_locations_tenant_id", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("tenant_id", "code", name="uq_stock_locations_tenant_code"),
    )
    op.create_index("ix_stock_locations_name", "stock_locations", ["name"])
    op.create_index("ix_stock_locations_active", "stock_locations", ["active"])
    op.create_foreign_key(
        "fk_stock_locations_criado_por_id",
        "stock_locations",
        "employees",
        ["criado_por_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "stock_balances",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("variant_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column(
            "qty", sa.Numeric(precision=14, scale=3), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "atualizado_em",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("criado_por_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("tenant_id", "id", name="pk_stock_balances"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_stock_balances_tenant_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "variant_id"],
            ["product_variants.tenant_id", "product_variants.id"],
            name="fk_stock_balances_variant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["stock_locations.tenant_id", "stock_locations.id"],
            name="fk_stock_balances_location",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id", "variant_id", "location_id", name="uq_stock_balances_variante_local"
        ),
        sa.CheckConstraint("qty >= 0", name="qty_nao_negativo"),
    )
    op.create_foreign_key(
        "fk_stock_balances_criado_por_id",
        "stock_balances",
        "employees",
        ["criado_por_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "stock_movements",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("variant_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("delta", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column(
            "reason", postgresql.ENUM(name="motivo_movimento", create_type=False), nullable=False
        ),
        sa.Column(
            "source_kind",
            postgresql.ENUM(name="origem_movimento", create_type=False),
            nullable=True,
        ),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("balance_after", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("employee_id", sa.Uuid(), nullable=True),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "atualizado_em",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("criado_por_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("tenant_id", "id", name="pk_stock_movements"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_stock_movements_tenant_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "variant_id"],
            ["product_variants.tenant_id", "product_variants.id"],
            name="fk_stock_movements_variant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["stock_locations.tenant_id", "stock_locations.id"],
            name="fk_stock_movements_location",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employees.id"],
            name="fk_stock_movements_employee_id",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint("delta <> 0", name="delta_nao_zero"),
    )
    op.create_index(
        "ix_stock_movements_extrato",
        "stock_movements",
        ["tenant_id", "variant_id", "location_id", "occurred_at"],
    )
    op.create_foreign_key(
        "fk_stock_movements_criado_por_id",
        "stock_movements",
        "employees",
        ["criado_por_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # O saldo que estava em `product_tenant.stock_qty` vira saldo de um local `PADRAO`, um
    # por empresa que de fato tenha estoque — criar local para empresa sem estoque seria
    # cadastro inventado pela migração.
    op.execute(
        """
        INSERT INTO stock_locations (tenant_id, id, code, name, kind, active, criado_em, atualizado_em)
        SELECT t.tenant_id, gen_random_uuid(), 'PADRAO', 'Depósito padrão',
               'deposito'::tipo_local_estoque, true, now(), now()
        -- O DISTINCT vai na subconsulta, não na projeção: `gen_random_uuid()` e `now()` são
        -- voláteis, então `SELECT DISTINCT` sobre a linha inteira torna toda linha única e
        -- insere um local por variante, em vez de um por empresa.
        FROM (SELECT DISTINCT tenant_id FROM product_tenant WHERE stock_qty > 0) AS t
        """
    )
    op.execute(
        """
        INSERT INTO stock_balances (tenant_id, id, variant_id, location_id, qty, criado_em, atualizado_em)
        SELECT pt.tenant_id, gen_random_uuid(), pt.variant_id, sl.id, pt.stock_qty, now(), now()
        FROM product_tenant pt
        JOIN stock_locations sl ON sl.tenant_id = pt.tenant_id AND sl.code = 'PADRAO'
        WHERE pt.stock_qty > 0
        """
    )
    # Movimento de abertura: sem ele o saldo existiria sem nenhuma linha que o explique, que
    # é exatamente o problema que `stock_movements` veio resolver.
    op.execute(
        """
        INSERT INTO stock_movements (
            tenant_id, id, variant_id, location_id, delta, reason, source_kind,
            balance_after, occurred_at, criado_em, atualizado_em
        )
        SELECT sb.tenant_id, gen_random_uuid(), sb.variant_id, sb.location_id, sb.qty,
               'inventario'::motivo_movimento, 'inventario'::origem_movimento,
               sb.qty, now(), now(), now()
        FROM stock_balances sb
        """
    )

    # `product_tenant` vira `variant_tenant_settings` — só configuração, sem saldo.
    op.drop_constraint("stock_qty_nao_negativo", "product_tenant", type_="check")
    op.drop_column("product_tenant", "stock_qty")
    op.drop_constraint("price_cents_nao_negativo", "product_tenant", type_="check")
    op.alter_column("product_tenant", "price_cents", new_column_name="sale_price_cents")
    op.add_column(
        "product_tenant",
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )

    op.drop_constraint("fk_product_tenant_variant", "product_tenant", type_="foreignkey")
    op.drop_constraint("uq_product_tenant_variant", "product_tenant", type_="unique")
    op.drop_constraint("pk_product_tenant", "product_tenant", type_="primary")
    op.rename_table("product_tenant", "variant_tenant_settings")
    op.create_primary_key(
        "pk_variant_tenant_settings", "variant_tenant_settings", ["tenant_id", "id"]
    )
    op.create_unique_constraint(
        "uq_variant_tenant_settings_variant", "variant_tenant_settings", ["tenant_id", "variant_id"]
    )
    op.create_foreign_key(
        "fk_variant_tenant_settings_variant",
        "variant_tenant_settings",
        "product_variants",
        ["tenant_id", "variant_id"],
        ["tenant_id", "id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        "sale_price_cents_nao_negativo",
        "variant_tenant_settings",
        "sale_price_cents >= 0",
    )
    op.create_check_constraint(
        "min_stock_nao_negativo",
        "variant_tenant_settings",
        "min_stock >= 0",
    )
    op.create_index("ix_variant_tenant_settings_active", "variant_tenant_settings", ["active"])
    # As políticas foram criadas com o nome antigo — `RENAME TABLE` não as renomeia.
    for sufixo in ("sel", "ins", "upd", "del"):
        op.execute(
            f'ALTER POLICY "product_tenant_{sufixo}" ON variant_tenant_settings '
            f'RENAME TO "variant_tenant_settings_{sufixo}"'
        )

    # --- 3. orçamento -----------------------------------------------------------
    status_orcamento = postgresql.ENUM(
        "rascunho", "aberto", "fechado", "cancelado", name="status_orcamento"
    )
    status_orcamento.create(op.get_bind())
    modo_desconto = postgresql.ENUM("percentual", "valor", name="modo_desconto")
    modo_desconto.create(op.get_bind())

    op.create_table(
        "quotes",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.BigInteger(), nullable=False),
        sa.Column("series", sa.String(length=3), nullable=False),
        sa.Column(
            "status", postgresql.ENUM(name="status_orcamento", create_type=False), nullable=False
        ),
        sa.Column("issued_at", sa.Date(), nullable=True),
        sa.Column("expires_at", sa.Date(), nullable=True),
        sa.Column("closed_at", sa.Date(), nullable=True),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=True),
        sa.Column("professional_id", sa.Uuid(), nullable=True),
        sa.Column("seller_id", sa.Uuid(), nullable=True),
        sa.Column("filial_id", sa.Uuid(), nullable=True),
        sa.Column("centro_custo_id", sa.Uuid(), nullable=True),
        sa.Column("origem_id", sa.Uuid(), nullable=True),
        sa.Column("project_name", sa.String(length=160), nullable=True),
        sa.Column("folder_number", sa.String(length=30), nullable=True),
        sa.Column("category_id", sa.Uuid(), nullable=True),
        sa.Column(
            "discount_mode",
            postgresql.ENUM(name="modo_desconto", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "discount_value",
            sa.Numeric(precision=14, scale=4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("total_cents", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("observacao", sa.String(length=2000), nullable=True),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "atualizado_em",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("criado_por_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("tenant_id", "id", name="pk_quotes"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_quotes_tenant_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["partners.tenant_id", "partners.id"],
            name="fk_quotes_customer",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "site_id"],
            ["obra.tenant_id", "obra.id"],
            name="fk_quotes_site",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "professional_id"],
            ["partners.tenant_id", "partners.id"],
            name="fk_quotes_professional",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "filial_id"],
            ["filial.tenant_id", "filial.id"],
            name="fk_quotes_filial",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "centro_custo_id"],
            ["centro_custo.tenant_id", "centro_custo.id"],
            name="fk_quotes_centro_custo",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "origem_id"],
            ["quotes.tenant_id", "quotes.id"],
            name="fk_quotes_origem",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["seller_id"], ["employees.id"], name="fk_quotes_seller_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["catalog_lookups.id"],
            name="fk_quotes_category_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "series", "number", name="uq_quotes_tenant_serie_numero"),
        sa.CheckConstraint("total_cents >= 0", name="quotes_total_nao_negativo"),
        sa.CheckConstraint("discount_value >= 0", name="quotes_desconto_nao_negativo"),
    )
    op.create_index("ix_quotes_tenant_status", "quotes", ["tenant_id", "status"])
    op.create_foreign_key(
        "fk_quotes_criado_por_id",
        "quotes",
        "employees",
        ["criado_por_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "quote_environments",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("quote_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("sort", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "atualizado_em",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("criado_por_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("tenant_id", "id", name="pk_quote_environments"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_quote_environments_tenant_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "quote_id"],
            ["quotes.tenant_id", "quotes.id"],
            name="fk_quote_environments_quote",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("tenant_id", "quote_id", "code", name="uq_quote_environments_codigo"),
    )
    op.create_foreign_key(
        "fk_quote_environments_criado_por_id",
        "quote_environments",
        "employees",
        ["criado_por_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "quote_items",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("quote_id", sa.Uuid(), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("environment_id", sa.Uuid(), nullable=True),
        sa.Column("product_id", sa.Uuid(), nullable=True),
        sa.Column("variant_id", sa.Uuid(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("finish", sa.String(length=60), nullable=True),
        sa.Column("size", sa.String(length=60), nullable=True),
        sa.Column("unit", sa.String(length=20), nullable=True),
        sa.Column("supplier_id", sa.Uuid(), nullable=True),
        sa.Column("supplier_name", sa.String(length=160), nullable=True),
        sa.Column("supplier_code", sa.String(length=60), nullable=True),
        sa.Column("product_group", sa.String(length=60), nullable=True),
        sa.Column("piece_type", sa.String(length=60), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("unit_price_cents", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "discount_pct",
            sa.Numeric(precision=7, scale=4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("total_cents", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "atualizado_em",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("criado_por_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("tenant_id", "id", name="pk_quote_items"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_quote_items_tenant_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "quote_id"],
            ["quotes.tenant_id", "quotes.id"],
            name="fk_quote_items_quote",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "environment_id"],
            ["quote_environments.tenant_id", "quote_environments.id"],
            name="fk_quote_items_environment",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "variant_id"],
            ["product_variants.tenant_id", "product_variants.id"],
            name="fk_quote_items_variant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_quote_items_product",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supplier_id"],
            ["partners.tenant_id", "partners.id"],
            name="fk_quote_items_supplier",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "quote_id", "line_number", name="uq_quote_items_linha"),
        sa.CheckConstraint("quantity > 0", name="quote_items_quantidade_positiva"),
        sa.CheckConstraint("unit_price_cents >= 0", name="quote_items_preco_nao_negativo"),
        sa.CheckConstraint("total_cents >= 0", name="quote_items_total_nao_negativo"),
        sa.CheckConstraint(
            "variant_id IS NULL OR product_id IS NOT NULL",
            name="quote_items_variante_exige_produto",
        ),
    )
    op.create_foreign_key(
        "fk_quote_items_criado_por_id",
        "quote_items",
        "employees",
        ["criado_por_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # --- 4. colunas soltas do diagrama ------------------------------------------
    op.add_column("products", sa.Column("group_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_products_group_id",
        "products",
        "catalog_lookups",
        ["group_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.add_column(
        "employees",
        sa.Column(
            "must_change_password", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.add_column(
        "employee_company",
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.create_index("ix_employee_company_active", "employee_company", ["active"])

    # `server_default` só existiu para o `ADD COLUMN` não quebrar contra tabela cheia — o
    # modelo Python não o declara, e deixá-lo seria ruído no próximo autogenerate.
    for tabela, coluna in (
        ("employees", "must_change_password"),
        ("employee_company", "active"),
        ("variant_tenant_settings", "active"),
    ):
        op.alter_column(tabela, coluna, server_default=None)

    for tabela in TABELAS_NOVAS:
        _ligar_rls(tabela)


def downgrade() -> None:
    # Levanta **antes** de qualquer DDL, não no fim: desfazer estoque e orçamento é
    # mecânico, mas desfazer `partners` não é — um parceiro que hoje é cliente **e**
    # fornecedor não tem para qual das três tabelas originais voltar. Um downgrade que
    # reverte dois terços e para no último seria pior que um que não começa.
    raise RuntimeError(
        "Downgrade não suportado: a unificação em `partners` não é reversível "
        "automaticamente (um parceiro com mais de um papel não tem tabela de destino "
        "única). Restaure de backup se precisar desfazer esta migração."
    )

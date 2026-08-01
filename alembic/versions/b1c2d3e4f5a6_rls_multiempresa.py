"""RLS: multiempresa imposta pelo banco

Toda tabela por empresa ganha chave primária composta `(tenant_id, id)` — já declarada na
migração `fundacao` — e aqui a política que a faz valer: `FORCE ROW LEVEL SECURITY` mais
quatro políticas por tabela, todas sobre o mesmo predicado. O papel de runtime nasce aqui
também, sem ser dono e sem `BYPASSRLS` — sem essas duas coisas o RLS é decorativo.

Vai em SQL cru de propósito: o Alembic não modela política de segurança, e deixá-la fora da
migração seria pior que não tê-la — o banco de um dev teria a trava, o do outro não, e
nenhum teste reclamaria.

Revision ID: b1c2d3e4f5a6
Revises: c2d3e4f5a6b7
Create Date: 2026-07-31
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: str | None = "c2d3e4f5a6b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Repetida aqui, e não importada de `app.models`: migração é foto do schema num instante do
# tempo. Se ela lesse o modelo, mudar o modelo amanhã reescreveria o passado — e o
# `upgrade` deixaria de reproduzir o que produziu na primeira vez. Quem cruza as duas é
# `test_toda_tabela_com_tenant_id_tem_rls_forcado`.
TABELAS_POR_EMPRESA = (
    "filial",
    "centro_custo",
    "contador_documento",
    "employee_company",
    "products",
    "product_variants",
    "product_tenant",
    "audit_log",
)

# Tabelas globais: sem `tenant_id`, sem RLS. Precisam do `GRANT` de DML como qualquer
# outra — só não recebem política, porque não há o que recortar.
TABELAS_GLOBAIS = (
    "tenants",
    "employees",
    "catalog_lookups",
    "grupo",
    "permissao",
    "uf",
    "cidade",
    "banco",
    "autorizacao_documento",
    "grupo_permissao",
    "usuario_grupo",
)

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
    _criar_papel_runtime()
    for tabela in TABELAS_POR_EMPRESA:
        _ligar_rls(tabela)


def downgrade() -> None:
    for tabela in TABELAS_POR_EMPRESA:
        op.execute(f"ALTER TABLE {tabela} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {tabela} DISABLE ROW LEVEL SECURITY")
        for sufixo in ("sel", "ins", "upd", "del"):
            op.execute(f'DROP POLICY IF EXISTS "{tabela}_{sufixo}" ON {tabela}')

    for tabela in TABELAS_POR_EMPRESA + TABELAS_GLOBAIS:
        op.execute(f"REVOKE ALL ON {tabela} FROM {PAPEL_RUNTIME}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {PAPEL_RUNTIME}")
    # `DROP ROLE` leva junto a associação `GRANT {PAPEL_RUNTIME} TO vitra_runtime` — mas
    # essa associação foi criada **fora** do Alembic, por `scripts/conceder_runtime.sql`
    # (`make runtime`), rodado uma vez por banco. O próximo `upgrade()` recria o papel
    # vazio, sem `vitra_runtime` dentro dele, e a aplicação sobe sem privilégio nenhuma nas
    # tabelas até alguém rodar `make runtime` de novo. Assimetria deliberada — como o
    # `downgrade` de resto deste arquivo não faz `DROP ROLE` no caminho normal (só aqui,
    # que é o de desfazer a própria migração que o criou) — mas vale o registro.
    op.execute(f"DROP ROLE IF EXISTS {PAPEL_RUNTIME}")


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
    for tabela in TABELAS_POR_EMPRESA + TABELAS_GLOBAIS:
        if tabela == "audit_log":
            continue
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {tabela} TO {PAPEL_RUNTIME}")

    # `audit_log` é o caso à parte: SELECT e INSERT, nunca UPDATE nem DELETE. É o que faz
    # "append-only" ser uma garantia do banco — nem um bug na aplicação, nem uma conexão
    # comprometida com as credenciais de runtime conseguem apagar ou alterar o rastro.
    op.execute(f"GRANT SELECT, INSERT ON audit_log TO {PAPEL_RUNTIME}")


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

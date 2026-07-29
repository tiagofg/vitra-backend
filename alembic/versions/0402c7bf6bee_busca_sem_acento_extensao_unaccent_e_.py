"""busca sem acento: extensao unaccent e wrapper imutavel

Revision ID: 0402c7bf6bee
Revises: 1f0577e25b9d
Create Date: 2026-07-28 23:15:30.478967
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = '0402c7bf6bee'
down_revision: str | None = '1f0577e25b9d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # `unaccent` é extensão confiável desde o PG 13: o dono do banco cria sem ser superusuário.
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")

    # A função unaccent() padrão é STABLE, não IMMUTABLE — ela lê um dicionário que pode ser
    # recarregado em runtime, e por isso não pode entrar em índice funcional. O wrapper fixa o
    # dicionário como argumento e declara IMMUTABLE, que é a receita usual para tornar a busca
    # sem acento indexável quando o volume justificar (hoje as tabelas são pequenas).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION vitra_unaccent(texto text)
        RETURNS text
        LANGUAGE sql
        IMMUTABLE
        PARALLEL SAFE
        STRICT
        AS $$ SELECT public.unaccent('public.unaccent'::regdictionary, texto) $$
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS vitra_unaccent(text)")
    # A extensão fica de propósito: derrubá-la é mais destrutivo do que esta revisão precisa.

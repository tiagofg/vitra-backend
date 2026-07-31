"""cnpj: varchar(18) com máscara -> varchar(14) caixa alta sem máscara

A S0 gravou `varchar(18)` com máscara (`12.345.678/0001-90`). Está errado por duas razões,
e a segunda tem prazo: **o CNPJ alfanumérico passa a valer em 31/07/2026**, e um campo
mascarado obriga a decidir onde ficam as letras dentro da máscara. Sem máscara o problema
não existe. Caixa alta pelo mesmo motivo — `a1b2` e `A1B2` são o mesmo CNPJ e não podem
ocupar duas linhas sob a restrição de unicidade.

A conversão é barata agora e cara depois: não há nada em produção.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ALVOS = (("empresa", "cnpj"), ("filial", "cnpj"))

# Tudo que não é dígito nem letra sai. `regexp_replace` com a flag 'g' para pegar todas as
# ocorrências, não só a primeira — sem o 'g' a máscara só perderia o primeiro ponto.
LIMPEZA = "upper(regexp_replace({coluna}, '[^0-9A-Za-z]', '', 'g'))"


def upgrade() -> None:
    for tabela, coluna in ALVOS:
        op.execute(f"UPDATE {tabela} SET {coluna} = {LIMPEZA.format(coluna=coluna)}")
        op.alter_column(
            tabela,
            coluna,
            type_=sa.String(length=14),
            existing_type=sa.String(length=18),
            existing_nullable=True,
        )


def downgrade() -> None:
    # Só devolve o tamanho. A máscara **não** volta: reconstruí-la exigiria saber se o valor
    # é CNPJ ou CPF, e um downgrade que adivinha é pior que um downgrade que não desfaz.
    for tabela, coluna in ALVOS:
        op.alter_column(
            tabela,
            coluna,
            type_=sa.String(length=18),
            existing_type=sa.String(length=14),
            existing_nullable=True,
        )

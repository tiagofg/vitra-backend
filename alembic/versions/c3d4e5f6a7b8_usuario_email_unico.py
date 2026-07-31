"""usuario.email passa a ser único

O e-mail deixou de ser só um campo de contato: desde a fase SB ele é a **ponte** que liga
quem loga (`usuario`) a quem trabalha (`employees`), e é por ela que a autorização por
empresa decide (ver `app/modules/bakeoff/deps.py`).

Sem `UNIQUE`, duas linhas com o mesmo e-mail recebem o mesmo acesso à mesma empresa e nada
no banco impede que existam — quem pudesse criar usuário atravessaria o recorte da S0
escrevendo o e-mail certo no cadastro. A ausência da restrição é o que tornaria isso
silencioso.

Barato agora e caro depois, pelo mesmo argumento que valeu para o CNPJ: não há nada em
produção.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-31
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Normaliza antes de restringir: `a@x.dev` e `A@X.dev` são o mesmo e-mail para a ponte
    # (que compara em minúsculas), então deixá-los passar criaria duplicata efetiva sob uma
    # restrição que diz não haver nenhuma.
    op.execute("UPDATE usuario SET email = lower(email) WHERE email IS NOT NULL")
    op.create_unique_constraint("uq_usuario_email", "usuario", ["email"])


def downgrade() -> None:
    op.drop_constraint("uq_usuario_email", "usuario", type_="unique")

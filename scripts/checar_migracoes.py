"""Confere que a árvore de migrações tem **uma cabeça só**.

    python scripts/checar_migracoes.py

Duas cabeças acontecem quando dois branches criam migração em paralelo. O modo de falha é
traiçoeiro: o `alembic upgrade head` de quem criou cada uma funciona perfeitamente, e o
erro só aparece no banco de quem faz o merge — normalmente em CI, normalmente no pior dia.

Não toca no banco: lê só os arquivos de `alembic/versions/`.
"""

from __future__ import annotations

import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

RAIZ = Path(__file__).resolve().parents[1]


def main() -> int:
    cfg = Config(str(RAIZ / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ / "alembic"))
    cabecas = ScriptDirectory.from_config(cfg).get_heads()

    if len(cabecas) == 1:
        return 0

    if not cabecas:
        print("Nenhuma migração encontrada em alembic/versions/.", file=sys.stderr)
        return 1

    print(f"A árvore de migrações tem {len(cabecas)} cabeças:", file=sys.stderr)
    for cabeca in cabecas:
        print(f"  - {cabeca}", file=sys.stderr)
    print(
        "\nResolva antes de seguir — provavelmente dois branches criaram migração em\n"
        "paralelo. O caminho normal é reapontar o `down_revision` da mais nova para a\n"
        "outra cabeça; `alembic merge` só quando as duas já estiverem aplicadas em algum\n"
        "banco de verdade.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

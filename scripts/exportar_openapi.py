"""Escreve o contrato OpenAPI em `openapi.json`.

    python scripts/exportar_openapi.py

Entregável nº 6 do bake-off, e não é detalhe de documentação: um servidor Python **não**
pode usar tRPC, que é o mecanismo de contrato tipado do front do VITRA hoje. O OpenAPI
publicado é o substituto — é por ele que o front Next.js gera o cliente.

Não sobe o banco: `criar_app()` só monta rotas e schemas.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.main import criar_app  # noqa: E402


def main() -> None:
    destino = RAIZ / "openapi.json"
    contrato = criar_app().openapi()
    destino.write_text(json.dumps(contrato, indent=2, ensure_ascii=False) + "\n", "utf-8")
    print(f"{destino.relative_to(RAIZ)}: {len(contrato['paths'])} rotas")


if __name__ == "__main__":
    main()

"""Serviço de produtos.

Herdado do bake-off: o que vale reparar não é o que tem, é **o que não tem** em `listar` —
nenhum filtro por empresa. Não é esquecimento — é a política de RLS que recorta sozinha.
Esqueceu a empresa? Lista vazia, nunca dado da empresa errada — ver `SessaoEmpresa`.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import selectinload

from app.common.base_service import BaseService
from app.core.listing import ListingSpec
from app.modules.produtos.models import Produto, Variante
from app.modules.produtos.schemas import ProdutoCriar

SPEC_PRODUTO = ListingSpec(
    model=Produto,
    campos_busca=("codigo", "descricao"),
    campo_codigo="codigo",
    campos_ordenacao=("codigo", "descricao", "criado_em"),
    ordenacao_padrao="codigo",
)


class ProdutoService(BaseService[Produto, ProdutoCriar, Any]):
    nome_recurso = "Produto"
    spec = SPEC_PRODUTO
    colecoes_novas = ("variantes",)

    def _stmt_base(self) -> Select[Any]:
        # `selectinload` e não `joinedload`: o carregamento sai numa segunda consulta, com
        # `IN (...)`, então o `LIMIT` da paginação continua contando **produtos**. Com
        # `joinedload` o limite passaria a cortar linhas do join.
        #
        # Isso importa porque `app.core.listing.paginar()` conta com
        # `select(func.count()).select_from(stmt.order_by(None).subquery())` — correto
        # enquanto o carregamento sai numa consulta separada. Trocar para `joinedload` faria
        # o `COUNT` contar linhas do join, e o total divergiria de `len(itens)` (que já
        # precisa de `.unique()` por causa do join duplicando linhas).
        return select(Produto).options(selectinload(Produto.variantes).selectinload(Variante.preco))

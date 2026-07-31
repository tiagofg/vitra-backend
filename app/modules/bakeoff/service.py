"""Serviço de produtos do bake-off.

O que vale reparar não é o que tem, é **o que não tem**: nenhum filtro por empresa. Não é
esquecimento nem atalho de protótipo — é a coisa toda que o bake-off está medindo. O
`SELECT` sai sem `WHERE tenant_id = ...` e ainda assim volta só o que é da empresa da
transação, porque quem recorta é a política do Postgres.

A consequência incômoda é a outra face da mesma moeda: se a empresa não foi declarada, isto
devolve **lista vazia, sem erro**. Quando algo "sumir do nada" em desenvolvimento, a
primeira hipótese é sempre a mesma — faltou o `SET LOCAL`.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.listing import ListingSpec, ListParams, Pagina, aplicar_listagem, paginar
from app.modules.bakeoff.models import Produto, Variante
from app.modules.bakeoff.schemas import ProdutoCriar, ProdutoSaida

SPEC_PRODUTO = ListingSpec(
    model=Produto,
    campos_busca=("code", "description"),
    campo_codigo="code",
    campos_ordenacao=("code", "description"),
    # Sem `criado_em`: o schema compartilhado é fixo e não tem colunas de auditoria.
    ordenacao_padrao="code",
    campo_ativo="active",
    # False de propósito. Ver o docstring do módulo.
    tem_empresa=False,
)


class ProdutoService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _stmt_base(self) -> Select[Any]:
        # `selectinload` e não `joinedload`: o carregamento sai numa segunda consulta, com
        # `IN (...)`, então o `LIMIT` da paginação continua contando **produtos**. Com
        # `joinedload` o limite passaria a cortar linhas do join — 50 produtos virariam 17.
        return select(Produto).options(selectinload(Produto.variantes).selectinload(Variante.preco))

    async def listar(self, params: ListParams) -> Pagina[ProdutoSaida]:
        stmt = aplicar_listagem(self._stmt_base(), params, SPEC_PRODUTO)
        return await paginar(self.session, stmt, params, ProdutoSaida.model_validate)

    async def criar(self, dados: ProdutoCriar, empresa_id: uuid.UUID) -> Produto:
        """`tenant_id` vem do argumento, não do corpo do pedido.

        E ele precisa bater com a empresa da transação: a política de INSERT tem
        `WITH CHECK`, então gravar em nome de outra empresa é recusado pelo banco mesmo se
        alguém conseguisse passar o valor por aqui.
        """
        produto = Produto(
            tenant_id=empresa_id,
            code=dados.codigo,
            description=dados.descricao,
            active=dados.ativo,
        )
        produto.variantes = []
        self.session.add(produto)
        await self.session.flush()
        return produto

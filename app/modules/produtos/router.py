from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.core.errors import CONFLITO, pode_falhar
from app.core.listing import ListParams, Pagina
from app.core.permissions import Acao, require
from app.modules.auth.deps import EmpresaDoPedido, SessaoEmpresa
from app.modules.auth.models import Usuario
from app.modules.produtos.schemas import ProdutoCriar, ProdutoSaida
from app.modules.produtos.service import ProdutoService

router_produtos = APIRouter(prefix="/produtos", tags=["produtos"])


@router_produtos.get("", response_model=Pagina[ProdutoSaida])
async def listar_produtos(
    session: SessaoEmpresa,
    params: Annotated[ListParams, Depends()],
    _: Annotated[Usuario, Depends(require("produto", Acao.ler))],
) -> Pagina[ProdutoSaida]:
    """Listagem server-side: busca sem acento, ordenação e paginação, tudo no servidor.

    `tenant_id` não é parâmetro: a empresa vem do token (ou de `X-Empresa-Id`) e entra na
    transação, nunca da query string.
    """
    return await ProdutoService(session).listar(params, ProdutoSaida.model_validate)


@router_produtos.post("", response_model=ProdutoSaida, status_code=status.HTTP_201_CREATED)
@pode_falhar(CONFLITO)
async def criar_produto(
    dados: ProdutoCriar,
    session: SessaoEmpresa,
    empresa_id: EmpresaDoPedido,
    _: Annotated[Usuario, Depends(require("produto", Acao.criar))],
) -> ProdutoSaida:
    produto = await ProdutoService(session, tenant_id=empresa_id).criar(dados)
    return ProdutoSaida.model_validate(produto)


routers = [router_produtos]

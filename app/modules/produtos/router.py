from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.core.errors import CONFLITO, pode_falhar
from app.core.listing import ListParams, Pagina
from app.modules.auth.deps import EmpresaDoPedido, SessaoEmpresa
from app.modules.produtos.schemas import ProdutoCriar, ProdutoSaida
from app.modules.produtos.service import ProdutoService

router_produtos = APIRouter(prefix="/produtos", tags=["produtos"])

# Sem `Depends(require(...))` de propósito, como no módulo herdado do bake-off: o RBAC
# recurso+ação para o catálogo de produtos é trabalho da S2, que enriquece este módulo.
# `SessaoEmpresa` já exige token válido **e** vínculo provado com a empresa pedida — a
# autorização por recurso é uma segunda camada que entra quando o cadastro de verdade
# existir, não antes.


@router_produtos.get("", response_model=Pagina[ProdutoSaida])
async def listar_produtos(
    session: SessaoEmpresa,
    params: Annotated[ListParams, Depends()],
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
) -> ProdutoSaida:
    produto = await ProdutoService(session, tenant_id=empresa_id).criar(dados)
    return ProdutoSaida.model_validate(produto)


routers = [router_produtos]

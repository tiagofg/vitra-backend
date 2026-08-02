from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.common.crud_router import crud_router
from app.core.errors import NAO_ENCONTRADO, REGRA_DE_NEGOCIO, pode_falhar
from app.core.permissions import Acao, require
from app.modules.auth.deps import EmpresaDoPedido, SessaoEmpresa
from app.modules.auth.models import Usuario
from app.modules.produtos.schemas import (
    ItemRelacionadoCriar,
    ItemRelacionadoSaida,
    ProdutoAtualizar,
    ProdutoCriar,
    ProdutoSaida,
)
from app.modules.produtos.service import ItemRelacionadoService, ProdutoService

router_produtos = crud_router(
    prefixo="/produtos",
    tag="produtos",
    recurso="produto",
    service=ProdutoService,
    criar=ProdutoCriar,
    atualizar=ProdutoAtualizar,
    saida=ProdutoSaida,
    # `ConfereDominiosMixin` levanta `dominio_invalido`/`referencia_invalida` nas nove FKs
    # para `catalog_lookups` — sem isto o contrato só publicaria o `422 validacao` genérico.
    falhas_extra=(REGRA_DE_NEGOCIO,),
)


# --- itens de um grupo relacionado: fora do padrão da fábrica ---------------------
#
# `grupo_relacionado` em si não tem rota própria — é uma das três grades do
# `PUT /produtos/{id}` (`ProdutoService._resolver_relacoes`). Só os itens dentro de um
# grupo têm rota: a tela adiciona/remove um de cada vez, não substitui o conjunto inteiro.

router_itens_relacionados = APIRouter(
    prefix="/produtos/{produto_id}/grupos-relacionados/{grupo_id}/itens", tags=["produtos"]
)


@router_itens_relacionados.get("", response_model=list[ItemRelacionadoSaida])
@pode_falhar(NAO_ENCONTRADO)
async def listar_itens_relacionados(
    produto_id: uuid.UUID,
    grupo_id: uuid.UUID,
    _: Annotated[Usuario, Depends(require("produto", Acao.ler))],
    session: SessaoEmpresa,
) -> list[ItemRelacionadoSaida]:
    itens = await ItemRelacionadoService(session, produto_id, grupo_id).listar()
    return [ItemRelacionadoSaida.model_validate(item) for item in itens]


@router_itens_relacionados.post(
    "", response_model=ItemRelacionadoSaida, status_code=status.HTTP_201_CREATED
)
@pode_falhar(NAO_ENCONTRADO, REGRA_DE_NEGOCIO)
async def criar_item_relacionado(
    produto_id: uuid.UUID,
    grupo_id: uuid.UUID,
    dados: ItemRelacionadoCriar,
    usuario: Annotated[Usuario, Depends(require("produto", Acao.editar))],
    session: SessaoEmpresa,
    empresa_id: EmpresaDoPedido,
) -> ItemRelacionadoSaida:
    service = ItemRelacionadoService(session, produto_id, grupo_id, usuario.id, empresa_id)
    return ItemRelacionadoSaida.model_validate(await service.criar(dados))


@router_itens_relacionados.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
@pode_falhar(NAO_ENCONTRADO)
async def remover_item_relacionado(
    produto_id: uuid.UUID,
    grupo_id: uuid.UUID,
    item_id: uuid.UUID,
    usuario: Annotated[Usuario, Depends(require("produto", Acao.editar))],
    session: SessaoEmpresa,
    empresa_id: EmpresaDoPedido,
) -> None:
    await ItemRelacionadoService(session, produto_id, grupo_id, usuario.id, empresa_id).remover(
        item_id
    )


routers = [router_produtos, router_itens_relacionados]

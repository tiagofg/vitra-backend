from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.common.crud_router import crud_router
from app.core.errors import NAO_ENCONTRADO, REGRA_DE_NEGOCIO, pode_falhar
from app.core.listing import ListParams, Pagina
from app.core.permissions import Acao, require
from app.modules.auth.deps import EmpresaDoPedido, SessaoEmpresa
from app.modules.auth.models import Usuario
from app.modules.estoque.schemas import (
    LocalEstoqueAtualizar,
    LocalEstoqueCriar,
    LocalEstoqueSaida,
    MovimentoCriar,
    MovimentoSaida,
    SaldoEstoqueSaida,
    TransferenciaCriar,
    TransferenciaSaida,
)
from app.modules.estoque.service import EstoqueService, LocalEstoqueService

router_locais = crud_router(
    prefixo="/estoque/locais",
    tag="estoque",
    recurso="local_estoque",
    service=LocalEstoqueService,
    criar=LocalEstoqueCriar,
    atualizar=LocalEstoqueAtualizar,
    saida=LocalEstoqueSaida,
    # `local_com_saldo` na desativação — o único código que a fábrica não adivinha.
    falhas_extra=(REGRA_DE_NEGOCIO,),
)

# --- saldo e extrato: fora do padrão da fábrica ----------------------------------
#
# Movimento não é CRUD. Não há `PUT` nem `DELETE`: o extrato é append-only, e corrigir um
# lançamento errado é lançar o inverso. Por isso este router é escrito à mão em vez de
# passar por `crud_router()`.

router_estoque = APIRouter(prefix="/estoque", tags=["estoque"])


@router_estoque.get("/saldos", response_model=Pagina[SaldoEstoqueSaida])
async def listar_saldos(
    _: Annotated[Usuario, Depends(require("estoque", Acao.ler))],
    session: SessaoEmpresa,
    params: Annotated[ListParams, Depends()],
) -> Pagina[SaldoEstoqueSaida]:
    return await EstoqueService(session).saldos(params, SaldoEstoqueSaida.model_validate)


@router_estoque.get("/saldos/{variante_id}", response_model=list[SaldoEstoqueSaida])
@pode_falhar(NAO_ENCONTRADO)
async def saldos_da_variante(
    variante_id: uuid.UUID,
    _: Annotated[Usuario, Depends(require("estoque", Acao.ler))],
    session: SessaoEmpresa,
) -> list[SaldoEstoqueSaida]:
    """O saldo da variante em cada local. Lista, não número único: é justamente o que a
    coluna `stock_qty` de `product_tenant` não conseguia responder."""
    saldos = await EstoqueService(session).saldos_da_variante(variante_id)
    return [SaldoEstoqueSaida.model_validate(s) for s in saldos]


@router_estoque.get("/movimentos", response_model=Pagina[MovimentoSaida])
async def listar_movimentos(
    _: Annotated[Usuario, Depends(require("estoque", Acao.ler))],
    session: SessaoEmpresa,
    params: Annotated[ListParams, Depends()],
    variante_id: uuid.UUID | None = Query(None),
    local_id: uuid.UUID | None = Query(None),
) -> Pagina[MovimentoSaida]:
    return await EstoqueService(session).extrato(
        params,
        MovimentoSaida.model_validate,
        variante_id=variante_id,
        local_id=local_id,
    )


@router_estoque.post(
    "/movimentos", response_model=MovimentoSaida, status_code=status.HTTP_201_CREATED
)
@pode_falhar(NAO_ENCONTRADO, REGRA_DE_NEGOCIO)
async def movimentar(
    dados: MovimentoCriar,
    usuario: Annotated[Usuario, Depends(require("estoque", Acao.criar))],
    session: SessaoEmpresa,
    empresa_id: EmpresaDoPedido,
) -> MovimentoSaida:
    """Entrada (`delta` positivo) ou saída (`delta` negativo). Saldo e extrato são escritos
    juntos, sob o mesmo lock — ver `EstoqueService.movimentar`."""
    service = EstoqueService(session, usuario.id, empresa_id)
    return MovimentoSaida.model_validate(await service.movimentar(dados))


@router_estoque.post(
    "/transferencias", response_model=TransferenciaSaida, status_code=status.HTTP_201_CREATED
)
@pode_falhar(NAO_ENCONTRADO, REGRA_DE_NEGOCIO)
async def transferir(
    dados: TransferenciaCriar,
    usuario: Annotated[Usuario, Depends(require("estoque", Acao.criar))],
    session: SessaoEmpresa,
    empresa_id: EmpresaDoPedido,
) -> TransferenciaSaida:
    """Move quantidade de um local para outro. Devolve as **duas** linhas do extrato."""
    service = EstoqueService(session, usuario.id, empresa_id)
    saida, entrada = await service.transferir(dados)
    return TransferenciaSaida(
        saida=MovimentoSaida.model_validate(saida),
        entrada=MovimentoSaida.model_validate(entrada),
    )


routers = [router_locais, router_estoque]

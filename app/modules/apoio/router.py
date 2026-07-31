from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.deps import Sessao, UsuarioAtual
from app.core.errors import CONFLITO, NAO_ENCONTRADO, pode_falhar
from app.core.listing import ListParams, LookupItem, Pagina
from app.core.permissions import Acao, require
from app.modules.apoio.models import DominioApoio
from app.modules.apoio.schemas import (
    ApoioAtualizar,
    ApoioCriar,
    ApoioSaida,
    BancoAtualizar,
    BancoCriar,
    BancoSaida,
    CidadeAtualizar,
    CidadeCriar,
    CidadeSaida,
    DominioSaida,
    UfSaida,
)
from app.modules.apoio.service import ApoioService, BancoService, CidadeService, UfService
from app.modules.auth.models import Usuario

router_apoio = APIRouter(prefix="/apoio", tags=["apoio"])
router_cidades = APIRouter(prefix="/cidades", tags=["apoio"])
router_bancos = APIRouter(prefix="/bancos", tags=["apoio"])
router_ufs = APIRouter(prefix="/ufs", tags=["apoio"])


@router_apoio.get("/dominios", response_model=list[DominioSaida])
async def listar_dominios(_: UsuarioAtual) -> list[DominioSaida]:
    """Os 19 combos das telas, um por domínio."""
    return [
        DominioSaida(dominio=d, rotulo=d.value.replace("_", " ").capitalize()) for d in DominioApoio
    ]


@router_apoio.get("/{dominio}", response_model=Pagina[ApoioSaida])
async def listar_apoio(
    dominio: DominioApoio,
    session: Sessao,
    params: Annotated[ListParams, Depends()],
    _: Annotated[Usuario, Depends(require("apoio", Acao.ler))],
) -> Pagina[ApoioSaida]:
    return await ApoioService(session, dominio).listar(params, ApoioSaida.model_validate)


@router_apoio.get("/{dominio}/lookup", response_model=list[LookupItem])
async def lookup_apoio(
    dominio: DominioApoio,
    session: Sessao,
    _: Annotated[Usuario, Depends(require("apoio", Acao.ler))],
    q: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    empresa_id: uuid.UUID | None = Query(None),
) -> list[LookupItem]:
    return await ApoioService(session, dominio).lookup(q, limit, empresa_id)


@router_apoio.post("/{dominio}", response_model=ApoioSaida, status_code=status.HTTP_201_CREATED)
@pode_falhar(CONFLITO)
async def criar_apoio(
    dominio: DominioApoio,
    dados: ApoioCriar,
    session: Sessao,
    usuario: Annotated[Usuario, Depends(require("apoio", Acao.criar))],
) -> ApoioSaida:
    """É o botão `...` ao lado do combo: cria o valor sem sair da tela."""
    service = ApoioService(session, dominio, usuario.id)
    return ApoioSaida.model_validate(await service.criar(dados))


@router_apoio.get("/{dominio}/{item_id}", response_model=ApoioSaida)
@pode_falhar(NAO_ENCONTRADO)
async def obter_apoio(
    dominio: DominioApoio,
    item_id: uuid.UUID,
    session: Sessao,
    _: Annotated[Usuario, Depends(require("apoio", Acao.ler))],
) -> ApoioSaida:
    return ApoioSaida.model_validate(await ApoioService(session, dominio).obter(item_id))


@router_apoio.put("/{dominio}/{item_id}", response_model=ApoioSaida)
@pode_falhar(NAO_ENCONTRADO, CONFLITO)
async def atualizar_apoio(
    dominio: DominioApoio,
    item_id: uuid.UUID,
    dados: ApoioAtualizar,
    session: Sessao,
    usuario: Annotated[Usuario, Depends(require("apoio", Acao.editar))],
) -> ApoioSaida:
    service = ApoioService(session, dominio, usuario.id)
    return ApoioSaida.model_validate(await service.atualizar(item_id, dados))


@router_apoio.delete("/{dominio}/{item_id}", response_model=ApoioSaida)
@pode_falhar(NAO_ENCONTRADO)
async def desativar_apoio(
    dominio: DominioApoio,
    item_id: uuid.UUID,
    session: Sessao,
    usuario: Annotated[Usuario, Depends(require("apoio", Acao.excluir))],
) -> ApoioSaida:
    service = ApoioService(session, dominio, usuario.id)
    return ApoioSaida.model_validate(await service.desativar(item_id))


# --- cidades / bancos / ufs ---------------------------------------------------


@router_cidades.get("", response_model=Pagina[CidadeSaida])
async def listar_cidades(
    session: Sessao,
    params: Annotated[ListParams, Depends()],
    _: Annotated[Usuario, Depends(require("cidade", Acao.ler))],
) -> Pagina[CidadeSaida]:
    return await CidadeService(session).listar(params, CidadeSaida.model_validate)


@router_cidades.get("/lookup", response_model=list[LookupItem])
async def lookup_cidades(
    session: Sessao,
    _: Annotated[Usuario, Depends(require("cidade", Acao.ler))],
    q: str | None = Query(None),
    uf: str | None = Query(None, min_length=2, max_length=2),
    limit: int = Query(20, ge=1, le=100),
) -> list[LookupItem]:
    return await CidadeService(session).lookup(q, limit, uf)


@router_cidades.post("", response_model=CidadeSaida, status_code=status.HTTP_201_CREATED)
@pode_falhar(CONFLITO)
async def criar_cidade(
    dados: CidadeCriar,
    session: Sessao,
    usuario: Annotated[Usuario, Depends(require("cidade", Acao.criar))],
) -> CidadeSaida:
    cidade = await CidadeService(session, usuario.id).criar(dados)
    await session.refresh(cidade, ["uf"])
    return CidadeSaida.model_validate(cidade)


@router_cidades.put("/{cidade_id}", response_model=CidadeSaida)
@pode_falhar(NAO_ENCONTRADO, CONFLITO)
async def atualizar_cidade(
    cidade_id: uuid.UUID,
    dados: CidadeAtualizar,
    session: Sessao,
    usuario: Annotated[Usuario, Depends(require("cidade", Acao.editar))],
) -> CidadeSaida:
    service = CidadeService(session, usuario.id)
    return CidadeSaida.model_validate(await service.atualizar(cidade_id, dados))


@router_bancos.get("", response_model=Pagina[BancoSaida])
async def listar_bancos(
    session: Sessao,
    params: Annotated[ListParams, Depends()],
    _: Annotated[Usuario, Depends(require("banco", Acao.ler))],
) -> Pagina[BancoSaida]:
    return await BancoService(session).listar(params, BancoSaida.model_validate)


@router_bancos.get("/lookup", response_model=list[LookupItem])
async def lookup_bancos(
    session: Sessao,
    _: Annotated[Usuario, Depends(require("banco", Acao.ler))],
    q: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
) -> list[LookupItem]:
    return await BancoService(session).lookup(q, limit)


@router_bancos.post("", response_model=BancoSaida, status_code=status.HTTP_201_CREATED)
@pode_falhar(CONFLITO)
async def criar_banco(
    dados: BancoCriar,
    session: Sessao,
    usuario: Annotated[Usuario, Depends(require("banco", Acao.criar))],
) -> BancoSaida:
    return BancoSaida.model_validate(await BancoService(session, usuario.id).criar(dados))


@router_bancos.put("/{banco_id}", response_model=BancoSaida)
@pode_falhar(NAO_ENCONTRADO, CONFLITO)
async def atualizar_banco(
    banco_id: uuid.UUID,
    dados: BancoAtualizar,
    session: Sessao,
    usuario: Annotated[Usuario, Depends(require("banco", Acao.editar))],
) -> BancoSaida:
    service = BancoService(session, usuario.id)
    return BancoSaida.model_validate(await service.atualizar(banco_id, dados))


@router_ufs.get("", response_model=Pagina[UfSaida])
async def listar_ufs(
    session: Sessao,
    params: Annotated[ListParams, Depends()],
    _: Annotated[Usuario, Depends(require("uf", Acao.ler))],
) -> Pagina[UfSaida]:
    return await UfService(session).listar(params, UfSaida.model_validate)


routers = [router_apoio, router_cidades, router_bancos, router_ufs]

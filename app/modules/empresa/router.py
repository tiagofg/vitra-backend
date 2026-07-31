from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.deps import Sessao
from app.core.listing import ListParams, LookupItem, Pagina
from app.core.permissions import Acao, require
from app.modules.auth.models import Usuario
from app.modules.empresa.schemas import (
    CentroCustoAtualizar,
    CentroCustoCriar,
    CentroCustoSaida,
    EmpresaAtualizar,
    EmpresaCriar,
    EmpresaSaida,
    FilialAtualizar,
    FilialCriar,
    FilialSaida,
)
from app.modules.empresa.service import CentroCustoService, EmpresaService, FilialService

router_empresas = APIRouter(prefix="/empresas", tags=["empresa"])
router_filiais = APIRouter(prefix="/filiais", tags=["empresa"])
router_centros_custo = APIRouter(prefix="/centros-custo", tags=["empresa"])


@router_empresas.get("", response_model=Pagina[EmpresaSaida])
async def listar_empresas(
    session: Sessao,
    params: Annotated[ListParams, Depends()],
    _: Annotated[Usuario, Depends(require("empresa", Acao.ler))],
) -> Pagina[EmpresaSaida]:
    return await EmpresaService(session).listar(params, EmpresaSaida.model_validate)


@router_empresas.get("/lookup", response_model=list[LookupItem])
async def lookup_empresas(
    session: Sessao,
    _: Annotated[Usuario, Depends(require("empresa", Acao.ler))],
    q: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
) -> list[LookupItem]:
    return await EmpresaService(session).lookup(q, limit)


@router_empresas.post("", response_model=EmpresaSaida, status_code=status.HTTP_201_CREATED)
async def criar_empresa(
    dados: EmpresaCriar,
    session: Sessao,
    usuario: Annotated[Usuario, Depends(require("empresa", Acao.criar))],
) -> EmpresaSaida:
    return EmpresaSaida.model_validate(await EmpresaService(session, usuario.id).criar(dados))


@router_empresas.get("/{empresa_id}", response_model=EmpresaSaida)
async def obter_empresa(
    empresa_id: uuid.UUID,
    session: Sessao,
    _: Annotated[Usuario, Depends(require("empresa", Acao.ler))],
) -> EmpresaSaida:
    return EmpresaSaida.model_validate(await EmpresaService(session).obter(empresa_id))


@router_empresas.put("/{empresa_id}", response_model=EmpresaSaida)
async def atualizar_empresa(
    empresa_id: uuid.UUID,
    dados: EmpresaAtualizar,
    session: Sessao,
    usuario: Annotated[Usuario, Depends(require("empresa", Acao.editar))],
) -> EmpresaSaida:
    service = EmpresaService(session, usuario.id)
    return EmpresaSaida.model_validate(await service.atualizar(empresa_id, dados))


@router_empresas.delete("/{empresa_id}", response_model=EmpresaSaida)
async def desativar_empresa(
    empresa_id: uuid.UUID,
    session: Sessao,
    usuario: Annotated[Usuario, Depends(require("empresa", Acao.excluir))],
) -> EmpresaSaida:
    service = EmpresaService(session, usuario.id)
    return EmpresaSaida.model_validate(await service.desativar(empresa_id))


@router_filiais.get("", response_model=Pagina[FilialSaida])
async def listar_filiais(
    session: Sessao,
    params: Annotated[ListParams, Depends()],
    _: Annotated[Usuario, Depends(require("filial", Acao.ler))],
) -> Pagina[FilialSaida]:
    return await FilialService(session).listar(params, FilialSaida.model_validate)


@router_filiais.post("", response_model=FilialSaida, status_code=status.HTTP_201_CREATED)
async def criar_filial(
    dados: FilialCriar,
    session: Sessao,
    usuario: Annotated[Usuario, Depends(require("filial", Acao.criar))],
) -> FilialSaida:
    return FilialSaida.model_validate(await FilialService(session, usuario.id).criar(dados))


@router_filiais.get("/{filial_id}", response_model=FilialSaida)
async def obter_filial(
    filial_id: uuid.UUID,
    session: Sessao,
    _: Annotated[Usuario, Depends(require("filial", Acao.ler))],
) -> FilialSaida:
    return FilialSaida.model_validate(await FilialService(session).obter(filial_id))


@router_filiais.put("/{filial_id}", response_model=FilialSaida)
async def atualizar_filial(
    filial_id: uuid.UUID,
    dados: FilialAtualizar,
    session: Sessao,
    usuario: Annotated[Usuario, Depends(require("filial", Acao.editar))],
) -> FilialSaida:
    service = FilialService(session, usuario.id)
    return FilialSaida.model_validate(await service.atualizar(filial_id, dados))


@router_filiais.delete("/{filial_id}", response_model=FilialSaida)
async def desativar_filial(
    filial_id: uuid.UUID,
    session: Sessao,
    usuario: Annotated[Usuario, Depends(require("filial", Acao.excluir))],
) -> FilialSaida:
    service = FilialService(session, usuario.id)
    return FilialSaida.model_validate(await service.desativar(filial_id))


@router_centros_custo.get("", response_model=Pagina[CentroCustoSaida])
async def listar_centros_custo(
    session: Sessao,
    params: Annotated[ListParams, Depends()],
    _: Annotated[Usuario, Depends(require("centro_custo", Acao.ler))],
) -> Pagina[CentroCustoSaida]:
    return await CentroCustoService(session).listar(params, CentroCustoSaida.model_validate)


@router_centros_custo.post("", response_model=CentroCustoSaida, status_code=status.HTTP_201_CREATED)
async def criar_centro_custo(
    dados: CentroCustoCriar,
    session: Sessao,
    usuario: Annotated[Usuario, Depends(require("centro_custo", Acao.criar))],
) -> CentroCustoSaida:
    service = CentroCustoService(session, usuario.id)
    return CentroCustoSaida.model_validate(await service.criar(dados))


@router_centros_custo.get("/{centro_id}", response_model=CentroCustoSaida)
async def obter_centro_custo(
    centro_id: uuid.UUID,
    session: Sessao,
    _: Annotated[Usuario, Depends(require("centro_custo", Acao.ler))],
) -> CentroCustoSaida:
    return CentroCustoSaida.model_validate(await CentroCustoService(session).obter(centro_id))


@router_centros_custo.put("/{centro_id}", response_model=CentroCustoSaida)
async def atualizar_centro_custo(
    centro_id: uuid.UUID,
    dados: CentroCustoAtualizar,
    session: Sessao,
    usuario: Annotated[Usuario, Depends(require("centro_custo", Acao.editar))],
) -> CentroCustoSaida:
    service = CentroCustoService(session, usuario.id)
    return CentroCustoSaida.model_validate(await service.atualizar(centro_id, dados))


@router_centros_custo.delete("/{centro_id}", response_model=CentroCustoSaida)
async def desativar_centro_custo(
    centro_id: uuid.UUID,
    session: Sessao,
    usuario: Annotated[Usuario, Depends(require("centro_custo", Acao.excluir))],
) -> CentroCustoSaida:
    service = CentroCustoService(session, usuario.id)
    return CentroCustoSaida.model_validate(await service.desativar(centro_id))


routers = [router_empresas, router_filiais, router_centros_custo]

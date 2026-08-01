from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.common.crud_router import crud_router
from app.core.errors import CONFLITO, NAO_ENCONTRADO, REGRA_DE_NEGOCIO, pode_falhar
from app.core.listing import ListParams, Pagina
from app.core.permissions import Acao, require
from app.modules.auth.deps import EmpresaDoPedido, SessaoEmpresa
from app.modules.auth.models import Usuario
from app.modules.pessoas.schemas import (
    ClienteAtualizar,
    ClienteCriar,
    ClienteSaida,
    ColaboradorAtualizar,
    ColaboradorCriar,
    ColaboradorSaida,
    FornecedorAtualizar,
    FornecedorCriar,
    FornecedorEmpresaAbrir,
    FornecedorEmpresaSaida,
    FornecedorSaida,
    ObraAtualizar,
    ObraCriar,
    ObraSaida,
    ProfissionalExternoAtualizar,
    ProfissionalExternoCriar,
    ProfissionalExternoSaida,
    TransportadoraAtualizar,
    TransportadoraCriar,
    TransportadoraSaida,
)
from app.modules.pessoas.service import (
    ClienteService,
    ColaboradorService,
    FornecedorEmpresaService,
    FornecedorService,
    ObraService,
    ProfissionalExternoService,
    TransportadoraService,
)

router_clientes = crud_router(
    prefixo="/clientes",
    tag="pessoas",
    recurso="cliente",
    service=ClienteService,
    criar=ClienteCriar,
    atualizar=ClienteAtualizar,
    saida=ClienteSaida,
)

router_fornecedores = crud_router(
    prefixo="/fornecedores",
    tag="pessoas",
    recurso="fornecedor",
    service=FornecedorService,
    criar=FornecedorCriar,
    atualizar=FornecedorAtualizar,
    saida=FornecedorSaida,
)

router_colaboradores = crud_router(
    prefixo="/colaboradores",
    tag="pessoas",
    recurso="colaborador",
    service=ColaboradorService,
    criar=ColaboradorCriar,
    atualizar=ColaboradorAtualizar,
    saida=ColaboradorSaida,
)

router_profissionais_externos = crud_router(
    prefixo="/profissionais-externos",
    tag="pessoas",
    recurso="profissional_externo",
    service=ProfissionalExternoService,
    criar=ProfissionalExternoCriar,
    atualizar=ProfissionalExternoAtualizar,
    saida=ProfissionalExternoSaida,
)

router_transportadoras = crud_router(
    prefixo="/transportadoras",
    tag="pessoas",
    recurso="transportadora",
    service=TransportadoraService,
    criar=TransportadoraCriar,
    atualizar=TransportadoraAtualizar,
    saida=TransportadoraSaida,
)


# --- obras: subrecurso de cliente, fora do padrão da fábrica ---------------------

router_obras = APIRouter(prefix="/clientes/{cliente_id}/obras", tags=["pessoas"])


@router_obras.get("", response_model=Pagina[ObraSaida])
@pode_falhar(NAO_ENCONTRADO)
async def listar_obras(
    cliente_id: uuid.UUID,
    _: Annotated[Usuario, Depends(require("obra", Acao.ler))],
    session: SessaoEmpresa,
    params: Annotated[ListParams, Depends()],
) -> Pagina[ObraSaida]:
    # `cliente_id` é UUID no caminho — o contrato exige 404 quando não existe, não uma
    # página vazia que faria o chamador não saber se o cliente sumiu ou só não tem obras.
    await ClienteService(session).obter(cliente_id)
    return await ObraService(session, cliente_id).listar(params, ObraSaida.model_validate)


@router_obras.post("", response_model=ObraSaida, status_code=status.HTTP_201_CREATED)
@pode_falhar(CONFLITO, NAO_ENCONTRADO)
async def criar_obra(
    cliente_id: uuid.UUID,
    dados: ObraCriar,
    usuario: Annotated[Usuario, Depends(require("obra", Acao.criar))],
    session: SessaoEmpresa,
    empresa_id: EmpresaDoPedido,
) -> ObraSaida:
    """Confere que o cliente existe (e é desta empresa — RLS) antes de pendurar a obra nele.
    `ClienteService.obter` é quem levanta o 404; `ObraService` não sabe validar `Cliente`,
    que é outro recurso."""
    await ClienteService(session).obter(cliente_id)
    obra = await ObraService(session, cliente_id, usuario.id, empresa_id).criar(dados)
    return ObraSaida.model_validate(obra)


@router_obras.get("/{obra_id}", response_model=ObraSaida)
@pode_falhar(NAO_ENCONTRADO)
async def obter_obra(
    cliente_id: uuid.UUID,
    obra_id: uuid.UUID,
    _: Annotated[Usuario, Depends(require("obra", Acao.ler))],
    session: SessaoEmpresa,
) -> ObraSaida:
    return ObraSaida.model_validate(await ObraService(session, cliente_id).obter(obra_id))


@router_obras.put("/{obra_id}", response_model=ObraSaida)
@pode_falhar(NAO_ENCONTRADO)
async def atualizar_obra(
    cliente_id: uuid.UUID,
    obra_id: uuid.UUID,
    dados: ObraAtualizar,
    usuario: Annotated[Usuario, Depends(require("obra", Acao.editar))],
    session: SessaoEmpresa,
) -> ObraSaida:
    service = ObraService(session, cliente_id, usuario.id)
    return ObraSaida.model_validate(await service.atualizar(obra_id, dados))


@router_obras.delete("/{obra_id}", response_model=ObraSaida)
@pode_falhar(NAO_ENCONTRADO)
async def desativar_obra(
    cliente_id: uuid.UUID,
    obra_id: uuid.UUID,
    usuario: Annotated[Usuario, Depends(require("obra", Acao.excluir))],
    session: SessaoEmpresa,
) -> ObraSaida:
    service = ObraService(session, cliente_id, usuario.id)
    return ObraSaida.model_validate(await service.desativar(obra_id))


# --- fornecedor_empresa: histórico, fora do padrão da fábrica ---------------------

router_fornecedor_empresa = APIRouter(
    prefix="/fornecedores/{fornecedor_id}/empresas-compradoras", tags=["pessoas"]
)


@router_fornecedor_empresa.get("", response_model=list[FornecedorEmpresaSaida])
@pode_falhar(NAO_ENCONTRADO)
async def listar_historico_empresa_compradora(
    fornecedor_id: uuid.UUID,
    _: Annotated[Usuario, Depends(require("fornecedor", Acao.ler))],
    session: SessaoEmpresa,
) -> list[FornecedorEmpresaSaida]:
    historico = await FornecedorEmpresaService(session, fornecedor_id).historico()
    return [FornecedorEmpresaSaida.model_validate(item) for item in historico]


@router_fornecedor_empresa.post(
    "", response_model=FornecedorEmpresaSaida, status_code=status.HTTP_201_CREATED
)
@pode_falhar(NAO_ENCONTRADO, REGRA_DE_NEGOCIO)
async def abrir_empresa_compradora(
    fornecedor_id: uuid.UUID,
    dados: FornecedorEmpresaAbrir,
    usuario: Annotated[Usuario, Depends(require("fornecedor", Acao.editar))],
    session: SessaoEmpresa,
    empresa_id: EmpresaDoPedido,
) -> FornecedorEmpresaSaida:
    service = FornecedorEmpresaService(session, fornecedor_id, usuario.id, empresa_id)
    return FornecedorEmpresaSaida.model_validate(await service.abrir_vigencia(dados))


routers = [
    router_clientes,
    router_obras,
    router_fornecedores,
    router_fornecedor_empresa,
    router_colaboradores,
    router_profissionais_externos,
    router_transportadoras,
]

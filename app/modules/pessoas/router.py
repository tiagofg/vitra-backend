from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Path, status

from app.common.crud_router import crud_router
from app.core.errors import (
    CONFLITO,
    NAO_ENCONTRADO,
    REGRA_DE_NEGOCIO,
    NaoEncontrado,
    pode_falhar,
)
from app.core.listing import ListParams, Pagina
from app.core.permissions import Acao, require
from app.modules.auth.deps import EmpresaDoPedido, SessaoEmpresa
from app.modules.auth.models import Usuario
from app.modules.pessoas.schemas import (
    ColaboradorAtualizar,
    ColaboradorCriar,
    ColaboradorSaida,
    FornecedorEmpresaAbrir,
    FornecedorEmpresaSaida,
    ObraAtualizar,
    ObraCriar,
    ObraSaida,
    ParceiroAtualizar,
    ParceiroCriar,
    ParceiroEmpresaGravar,
    ParceiroEmpresaSaida,
    ParceiroSaida,
    TransportadoraAtualizar,
    TransportadoraCriar,
    TransportadoraSaida,
)
from app.modules.pessoas.service import (
    PAPEIS,
    ColaboradorService,
    FornecedorEmpresaService,
    ObraService,
    ParceiroEmpresaService,
    ParceiroService,
    TransportadoraService,
)

router_parceiros = crud_router(
    prefixo="/parceiros",
    tag="pessoas",
    recurso="parceiro",
    service=ParceiroService,
    criar=ParceiroCriar,
    atualizar=ParceiroAtualizar,
    saida=ParceiroSaida,
    # `ConfereDominiosMixin` levanta `dominio_invalido`/`referencia_invalida` — sem isto o
    # contrato só publicaria o `422 validacao` genérico do FastAPI.
    falhas_extra=(REGRA_DE_NEGOCIO,),
)

router_colaboradores = crud_router(
    prefixo="/colaboradores",
    tag="pessoas",
    recurso="colaborador",
    service=ColaboradorService,
    criar=ColaboradorCriar,
    atualizar=ColaboradorAtualizar,
    saida=ColaboradorSaida,
    # `dominio_invalido` (herdado do mixin) + `colaborador_sem_vinculo` +
    # `empresa_nao_declarada_para_colaborador`, os três levantados por `ColaboradorService`.
    falhas_extra=(REGRA_DE_NEGOCIO,),
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


# --- listagem por papel ----------------------------------------------------------
#
# `/parceiros/clientes`, `/parceiros/fornecedores`, `/parceiros/profissionais`. As três
# telas do legado continuam existindo — o que sumiu foram as três *tabelas*. Uma rota só,
# com o papel no caminho, em vez de três `crud_router` idênticos: o `POST` continua sendo
# `/parceiros`, porque criar já diz qual é o papel pelas bandeiras do corpo.

router_papeis = APIRouter(prefix="/parceiros", tags=["pessoas"])


@router_papeis.get("/{papel}", response_model=Pagina[ParceiroSaida])
@pode_falhar(NAO_ENCONTRADO)
async def listar_por_papel(
    _: Annotated[Usuario, Depends(require("parceiro", Acao.ler))],
    session: SessaoEmpresa,
    params: Annotated[ListParams, Depends()],
    papel: Annotated[str, Path(description="clientes, fornecedores ou profissionais")],
) -> Pagina[ParceiroSaida]:
    """Declarado **depois** de `router_parceiros` no `routers` abaixo — se viesse antes,
    `/parceiros/{papel}` capturaria `/parceiros/{item_id}` e todo `GET` de um parceiro por
    id cairia aqui. Como `papel` é `str` e `item_id` é `uuid.UUID`, a ordem é o que decide.
    """
    if papel not in PAPEIS:
        # 404, não 422: para quem chama, `/parceiros/<uuid>` e `/parceiros/clientes` são a
        # mesma rota — um papel inválido é um caminho que não existe.
        raise NaoEncontrado("Papel de parceiro", papel)
    return await ParceiroService(session, papel=papel).listar(params, ParceiroSaida.model_validate)


# --- condição comercial: subrecurso de parceiro ----------------------------------

router_parceiro_empresa = APIRouter(
    prefix="/parceiros/{parceiro_id}/condicao-comercial", tags=["pessoas"]
)


@router_parceiro_empresa.get("", response_model=ParceiroEmpresaSaida)
@pode_falhar(NAO_ENCONTRADO)
async def obter_condicao_comercial(
    parceiro_id: uuid.UUID,
    _: Annotated[Usuario, Depends(require("parceiro", Acao.ler))],
    session: SessaoEmpresa,
) -> ParceiroEmpresaSaida:
    service = ParceiroEmpresaService(session, parceiro_id)
    return ParceiroEmpresaSaida.model_validate(await service.obter())


@router_parceiro_empresa.put("", response_model=ParceiroEmpresaSaida)
@pode_falhar(NAO_ENCONTRADO)
async def gravar_condicao_comercial(
    parceiro_id: uuid.UUID,
    dados: ParceiroEmpresaGravar,
    usuario: Annotated[Usuario, Depends(require("parceiro", Acao.editar))],
    session: SessaoEmpresa,
    empresa_id: EmpresaDoPedido,
) -> ParceiroEmpresaSaida:
    """Idempotente: cria se não existir, atualiza se existir. É no máximo uma linha por
    parceiro nesta empresa, então não há `POST` separado."""
    service = ParceiroEmpresaService(session, parceiro_id, usuario.id, empresa_id)
    return ParceiroEmpresaSaida.model_validate(await service.gravar(dados))


# --- obras: subrecurso de parceiro ------------------------------------------------

router_obras = APIRouter(prefix="/parceiros/{parceiro_id}/obras", tags=["pessoas"])


@router_obras.get("", response_model=Pagina[ObraSaida])
@pode_falhar(NAO_ENCONTRADO)
async def listar_obras(
    parceiro_id: uuid.UUID,
    _: Annotated[Usuario, Depends(require("obra", Acao.ler))],
    session: SessaoEmpresa,
    params: Annotated[ListParams, Depends()],
) -> Pagina[ObraSaida]:
    # `parceiro_id` é UUID no caminho — o contrato exige 404 quando não existe, não uma
    # página vazia que faria o chamador não saber se o parceiro sumiu ou só não tem obras.
    await ParceiroService(session).obter(parceiro_id)
    return await ObraService(session, parceiro_id).listar(params, ObraSaida.model_validate)


@router_obras.post("", response_model=ObraSaida, status_code=status.HTTP_201_CREATED)
@pode_falhar(CONFLITO, NAO_ENCONTRADO)
async def criar_obra(
    parceiro_id: uuid.UUID,
    dados: ObraCriar,
    usuario: Annotated[Usuario, Depends(require("obra", Acao.criar))],
    session: SessaoEmpresa,
    empresa_id: EmpresaDoPedido,
) -> ObraSaida:
    """Confere que o parceiro existe (e é desta empresa — RLS) antes de pendurar a obra
    nele. `ParceiroService.obter` é quem levanta o 404; `ObraService` não sabe validar
    `Parceiro`, que é outro recurso."""
    await ParceiroService(session).obter(parceiro_id)
    obra = await ObraService(session, parceiro_id, usuario.id, empresa_id).criar(dados)
    return ObraSaida.model_validate(obra)


@router_obras.get("/{obra_id}", response_model=ObraSaida)
@pode_falhar(NAO_ENCONTRADO)
async def obter_obra(
    parceiro_id: uuid.UUID,
    obra_id: uuid.UUID,
    _: Annotated[Usuario, Depends(require("obra", Acao.ler))],
    session: SessaoEmpresa,
) -> ObraSaida:
    return ObraSaida.model_validate(await ObraService(session, parceiro_id).obter(obra_id))


@router_obras.put("/{obra_id}", response_model=ObraSaida)
@pode_falhar(NAO_ENCONTRADO)
async def atualizar_obra(
    parceiro_id: uuid.UUID,
    obra_id: uuid.UUID,
    dados: ObraAtualizar,
    usuario: Annotated[Usuario, Depends(require("obra", Acao.editar))],
    session: SessaoEmpresa,
) -> ObraSaida:
    service = ObraService(session, parceiro_id, usuario.id)
    return ObraSaida.model_validate(await service.atualizar(obra_id, dados))


@router_obras.delete("/{obra_id}", response_model=ObraSaida)
@pode_falhar(NAO_ENCONTRADO)
async def desativar_obra(
    parceiro_id: uuid.UUID,
    obra_id: uuid.UUID,
    usuario: Annotated[Usuario, Depends(require("obra", Acao.excluir))],
    session: SessaoEmpresa,
) -> ObraSaida:
    service = ObraService(session, parceiro_id, usuario.id)
    return ObraSaida.model_validate(await service.desativar(obra_id))


# --- histórico de empresa compradora: fora do padrão da fábrica -------------------

router_fornecedor_empresa = APIRouter(
    prefix="/parceiros/{parceiro_id}/empresas-compradoras", tags=["pessoas"]
)


@router_fornecedor_empresa.get("", response_model=list[FornecedorEmpresaSaida])
@pode_falhar(NAO_ENCONTRADO)
async def listar_historico_empresa_compradora(
    parceiro_id: uuid.UUID,
    _: Annotated[Usuario, Depends(require("parceiro", Acao.ler))],
    session: SessaoEmpresa,
) -> list[FornecedorEmpresaSaida]:
    historico = await FornecedorEmpresaService(session, parceiro_id).historico()
    return [FornecedorEmpresaSaida.model_validate(item) for item in historico]


@router_fornecedor_empresa.post(
    "", response_model=FornecedorEmpresaSaida, status_code=status.HTTP_201_CREATED
)
@pode_falhar(NAO_ENCONTRADO, REGRA_DE_NEGOCIO)
async def abrir_empresa_compradora(
    parceiro_id: uuid.UUID,
    dados: FornecedorEmpresaAbrir,
    usuario: Annotated[Usuario, Depends(require("parceiro", Acao.editar))],
    session: SessaoEmpresa,
    empresa_id: EmpresaDoPedido,
) -> FornecedorEmpresaSaida:
    service = FornecedorEmpresaService(session, parceiro_id, usuario.id, empresa_id)
    return FornecedorEmpresaSaida.model_validate(await service.abrir_vigencia(dados))


# `router_parceiros` (com `/{item_id}` UUID) antes de `router_papeis` (com `/{papel}` str):
# o FastAPI casa na ordem de registro, e invertê-las faria todo `GET /parceiros/<uuid>` cair
# na listagem por papel.
routers = [
    router_parceiros,
    router_papeis,
    router_parceiro_empresa,
    router_obras,
    router_fornecedor_empresa,
    router_colaboradores,
    router_transportadoras,
]

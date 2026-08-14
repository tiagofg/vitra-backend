from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.common.crud_router import ROTA_LOOKUP, TODAS_AS_ROTAS, crud_router
from app.core.errors import NAO_ENCONTRADO, REGRA_DE_NEGOCIO, pode_falhar
from app.core.permissions import Acao, require
from app.modules.auth.deps import EmpresaDoPedido, SessaoEmpresa
from app.modules.auth.models import Usuario
from app.modules.vendas.schemas import (
    CancelarOrcamento,
    OrcamentoAtualizar,
    OrcamentoCriar,
    OrcamentoSaida,
)
from app.modules.vendas.service import OrcamentoService

# Sem `lookup`: orçamento não é `[busca +...]` de outra tela — ninguém escolhe um orçamento
# num combo. As outras cinco rotas do padrão valem.
router_orcamentos = crud_router(
    prefixo="/orcamentos",
    tag="vendas",
    recurso="orcamento",
    service=OrcamentoService,
    criar=OrcamentoCriar,
    atualizar=OrcamentoAtualizar,
    saida=OrcamentoSaida,
    rotas=TODAS_AS_ROTAS - {ROTA_LOOKUP},
    # `orcamento_nao_editavel`, `parceiro_nao_e_cliente`, `parceiro_nao_e_profissional`,
    # `desconto_maior_que_total`, `empresa_nao_declarada_para_orcamento`.
    falhas_extra=(REGRA_DE_NEGOCIO,),
)

# --- transições de estado: fora do padrão da fábrica ------------------------------
#
# `DELETE /orcamentos/{id}` (da fábrica) é desativação lógica, como em todo cadastro. O
# **cancelamento** é outra coisa: muda o status para `cancelado` e exige motivo — é o que a
# tela do legado chama de `Excluir`, e por isso tem rota própria com corpo.

router_acoes = APIRouter(prefix="/orcamentos", tags=["vendas"])


@router_acoes.post("/{item_id}/abrir", response_model=OrcamentoSaida)
@pode_falhar(NAO_ENCONTRADO, REGRA_DE_NEGOCIO)
async def abrir_orcamento(
    item_id: uuid.UUID,
    usuario: Annotated[Usuario, Depends(require("orcamento", Acao.editar))],
    session: SessaoEmpresa,
    empresa_id: EmpresaDoPedido,
) -> OrcamentoSaida:
    """Rascunho → aberto. Recusa orçamento sem itens."""
    service = OrcamentoService(session, usuario.id, empresa_id)
    return OrcamentoSaida.model_validate(await service.abrir(item_id))


@router_acoes.post("/{item_id}/fechar", response_model=OrcamentoSaida)
@pode_falhar(NAO_ENCONTRADO, REGRA_DE_NEGOCIO)
async def fechar_orcamento(
    item_id: uuid.UUID,
    usuario: Annotated[Usuario, Depends(require("orcamento", Acao.fechar))],
    session: SessaoEmpresa,
    empresa_id: EmpresaDoPedido,
) -> OrcamentoSaida:
    """Aberto → fechado. A partir daqui o documento não aceita mais edição."""
    service = OrcamentoService(session, usuario.id, empresa_id)
    return OrcamentoSaida.model_validate(await service.fechar(item_id))


@router_acoes.post("/{item_id}/cancelar", response_model=OrcamentoSaida)
@pode_falhar(NAO_ENCONTRADO, REGRA_DE_NEGOCIO)
async def cancelar_orcamento(
    item_id: uuid.UUID,
    dados: CancelarOrcamento,
    usuario: Annotated[Usuario, Depends(require("orcamento", Acao.cancelar))],
    session: SessaoEmpresa,
    empresa_id: EmpresaDoPedido,
) -> OrcamentoSaida:
    """Não apaga: muda o status e registra o motivo. O documento continua na listagem."""
    service = OrcamentoService(session, usuario.id, empresa_id)
    return OrcamentoSaida.model_validate(await service.cancelar(item_id, dados))


@router_acoes.post("/{item_id}/revisar", response_model=OrcamentoSaida)
@pode_falhar(NAO_ENCONTRADO, REGRA_DE_NEGOCIO)
async def revisar_orcamento(
    item_id: uuid.UUID,
    usuario: Annotated[Usuario, Depends(require("orcamento", Acao.criar))],
    session: SessaoEmpresa,
    empresa_id: EmpresaDoPedido,
) -> OrcamentoSaida:
    """Cria um rascunho novo, cópia deste, encadeado por `origem_id`."""
    service = OrcamentoService(session, usuario.id, empresa_id)
    return OrcamentoSaida.model_validate(await service.revisar(item_id))


routers = [router_orcamentos, router_acoes]

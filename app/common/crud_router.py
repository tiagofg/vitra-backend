"""Fábrica de router CRUD.

`app/modules/empresa/router.py` e `app/modules/apoio/router.py` escrevem à mão seis rotas
quase idênticas por recurso: listar, lookup, criar, obter, atualizar, desativar. A S1 sozinha
acrescenta seis recursos novos — repetir à mão de novo custaria ~1200 linhas que não dizem
nada além do que o `BaseService`/`ListingSpec` já sabem. `crud_router()` monta as seis a
partir do service e dos schemas do recurso; o que foge do padrão (subrecurso, ação além do
CRUD) continua escrito à mão, como sempre foi.

Duas propriedades do código já escrito à mão **não podem regredir** aqui:

* **`require(...)` resolvido antes de `SessaoEmpresa`.** É a ordem que faz "sem permissão e
  sem empresa" responder `403 sem_permissao` antes de `400 empresa_nao_declarada` — coberta
  por `test_sem_permissao_prevalece_sobre_empresa_nao_declarada`
  (`tests/test_autorizacao_por_empresa.py`). `app/modules/produtos/router.py` já segue essa
  ordem; é a que esta fábrica reproduz para todo recurso por empresa.
* **Nenhuma rota escreve `responses=`.** Cada dependência já declara a própria falha via
  `pode_falhar`, e `app/core/openapi.py` monta o contrato a partir do grafo de dependências
  — a fábrica não precisa (e não deve) repetir isso.

**Por que este arquivo não usa `from __future__ import annotations`.** As rotas são
funções construídas em tempo de execução, com a anotação do corpo (`dados: criar`) e do
retorno (`response_model=saida`) vindas de parâmetros de `crud_router()` — classes reais,
capturadas por clausura. O FastAPI lê `__annotations__` para decidir se um parâmetro é
corpo, query ou path; com `from __future__ import annotations` ativo, toda anotação vira
*string* na definição da função, e o FastAPI tentaria resolver `"criar"` como nome no
módulo (`__globals__`), não como a classe capturada na clausura — `NameError` em tempo de
requisição. Sem o import, o Python resolve a anotação para o objeto de verdade no instante
em que o `def` roda, que é exatamente o que se quer.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel

from app.common.base_service import BaseService
from app.common.schemas import SaidaBase
from app.core.deps import Sessao
from app.core.errors import CONFLITO, NAO_ENCONTRADO, Falha, pode_falhar
from app.core.listing import ListParams, LookupItem, Pagina

ROTA_LISTAR = "listar"
ROTA_LOOKUP = "lookup"
ROTA_CRIAR = "criar"
ROTA_OBTER = "obter"
ROTA_ATUALIZAR = "atualizar"
ROTA_DESATIVAR = "desativar"

TODAS_AS_ROTAS = frozenset(
    {ROTA_LISTAR, ROTA_LOOKUP, ROTA_CRIAR, ROTA_OBTER, ROTA_ATUALIZAR, ROTA_DESATIVAR}
)


def crud_router(
    *,
    prefixo: str,
    tag: str,
    recurso: str,
    service: type[BaseService[Any, Any, Any]],
    criar: type[BaseModel],
    atualizar: type[BaseModel],
    saida: type[SaidaBase],
    por_empresa: bool = True,
    rotas: frozenset[str] = TODAS_AS_ROTAS,
    falhas_extra: tuple[Falha, ...] = (),
) -> APIRouter:
    """Monta o CRUD comum de um recurso.

    `recurso` é a chave RBAC (`app/core/permissions.py::CATALOGO`) — precisa ter CRUD
    completo lá, senão `require()` estoura na importação, como qualquer outra rota.

    `por_empresa=True` (padrão): as rotas usam `SessaoEmpresa`/`EmpresaDoPedido`, e `criar()`
    recebe o `tenant_id` da transação — nunca do corpo do pedido. `por_empresa=False` é para
    recurso global (`apoio`, `cidade`, `banco`), que usa `Sessao` puro.

    `falhas_extra` documenta, em `criar`/`atualizar`, falha que só o `service` do recurso
    conhece (`RegraDeNegocio` com código específico — domínio errado de uma FK,
    referência inválida) e que a fábrica não tem como adivinhar sozinha. Sem isto o
    contrato publica só o `422 validacao` genérico do FastAPI, e o código real (ex.:
    `dominio_invalido`) fica documentado em lugar nenhum — mesmo problema que
    `test_toda_rota_com_id_no_caminho_declara_404` existe para pegar do lado do 404.

    Import de `app.modules.auth.deps` fica dentro da função, não no topo do arquivo: é a
    única peça que este módulo comum precisa de um módulo de domínio, e adiar o import evita
    que toda a árvore de `app.common` passe a depender de `app.modules.auth` na importação —
    só quem de fato monta um router `por_empresa=True` paga o custo.
    """
    from app.core.permissions import Acao, require
    from app.modules.auth.deps import EmpresaDoPedido, SessaoEmpresa
    from app.modules.auth.models import Usuario

    router = APIRouter(prefix=prefixo, tags=[tag])

    ler = require(recurso, Acao.ler)
    pode_criar = require(recurso, Acao.criar)
    pode_editar = require(recurso, Acao.editar)
    pode_excluir = require(recurso, Acao.excluir)

    if ROTA_LISTAR in rotas:
        if por_empresa:

            async def listar(
                _: Annotated[Usuario, Depends(ler)],
                session: SessaoEmpresa,
                params: Annotated[ListParams, Depends()],
            ) -> Pagina[Any]:
                return await service(session).listar(params, saida.model_validate)
        else:

            async def listar(
                _: Annotated[Usuario, Depends(ler)],
                session: Sessao,
                params: Annotated[ListParams, Depends()],
            ) -> Pagina[Any]:
                return await service(session).listar(params, saida.model_validate)

        router.add_api_route(
            "",
            listar,
            methods=["GET"],
            response_model=Pagina[saida],  # type: ignore[valid-type]
            name=f"listar_{recurso}",
            operation_id=f"listar_{recurso}",
        )

    if ROTA_LOOKUP in rotas:
        if por_empresa:

            async def lookup(
                _: Annotated[Usuario, Depends(ler)],
                session: SessaoEmpresa,
                q: str | None = Query(None),
                limit: int = Query(20, ge=1, le=100),
            ) -> list[LookupItem]:
                return await service(session).lookup(q, limit)
        else:

            async def lookup(
                _: Annotated[Usuario, Depends(ler)],
                session: Sessao,
                q: str | None = Query(None),
                limit: int = Query(20, ge=1, le=100),
            ) -> list[LookupItem]:
                return await service(session).lookup(q, limit)

        router.add_api_route(
            "/lookup",
            lookup,
            methods=["GET"],
            response_model=list[LookupItem],
            name=f"lookup_{recurso}",
            operation_id=f"lookup_{recurso}",
        )

    if ROTA_CRIAR in rotas:
        # As duas variantes têm aridade diferente (`empresa_id` só existe na de empresa) —
        # nomes distintos por ramo, cada uma com o próprio `add_api_route`, porque o mypy
        # trata `def` do mesmo nome em ramos de um `if`/`else` como redefinição do símbolo
        # e reprova quando as assinaturas não são estruturalmente iguais.
        if por_empresa:

            @pode_falhar(CONFLITO, *falhas_extra)
            async def criar_item_por_empresa(
                dados: criar,  # type: ignore[valid-type]
                usuario: Annotated[Usuario, Depends(pode_criar)],
                session: SessaoEmpresa,
                empresa_id: EmpresaDoPedido,
            ) -> Any:
                obj = await service(session, usuario.id, empresa_id).criar(dados)
                return saida.model_validate(obj)

            router.add_api_route(
                "",
                criar_item_por_empresa,
                methods=["POST"],
                response_model=saida,
                status_code=status.HTTP_201_CREATED,
                name=f"criar_{recurso}",
                operation_id=f"criar_{recurso}",
            )
        else:

            @pode_falhar(CONFLITO, *falhas_extra)
            async def criar_item_global(
                dados: criar,  # type: ignore[valid-type]
                usuario: Annotated[Usuario, Depends(pode_criar)],
                session: Sessao,
            ) -> Any:
                obj = await service(session, usuario.id).criar(dados)
                return saida.model_validate(obj)

            router.add_api_route(
                "",
                criar_item_global,
                methods=["POST"],
                response_model=saida,
                status_code=status.HTTP_201_CREATED,
                name=f"criar_{recurso}",
                operation_id=f"criar_{recurso}",
            )

    if ROTA_OBTER in rotas:
        session_dep = SessaoEmpresa if por_empresa else Sessao

        @pode_falhar(NAO_ENCONTRADO)
        async def obter(
            item_id: uuid.UUID,
            _: Annotated[Usuario, Depends(ler)],
            session: session_dep,  # type: ignore[valid-type]
        ) -> Any:
            return saida.model_validate(await service(session).obter(item_id))

        router.add_api_route(
            "/{item_id}",
            obter,
            methods=["GET"],
            response_model=saida,
            name=f"obter_{recurso}",
            operation_id=f"obter_{recurso}",
        )

    if ROTA_ATUALIZAR in rotas:
        # Mesma razão da bifurcação de `criar`: por_empresa acrescenta `empresa_id` (aridade
        # diferente), e o mypy trata `def` do mesmo nome em ramos de `if`/`else` como
        # redefinição do símbolo quando as assinaturas não batem.
        if por_empresa:

            @pode_falhar(NAO_ENCONTRADO, CONFLITO, *falhas_extra)
            async def atualizar_item_por_empresa(
                item_id: uuid.UUID,
                dados: atualizar,  # type: ignore[valid-type]
                usuario: Annotated[Usuario, Depends(pode_editar)],
                session: SessaoEmpresa,
                empresa_id: EmpresaDoPedido,
            ) -> Any:
                # `tenant_id` aqui não muda o recorte — RLS e `obter()` já garantem que só a
                # linha da empresa ativa é alcançada — mas mantém `self.tenant_id`
                # preenchido para qualquer gancho (`_antes_de_atualizar`) que precise dele,
                # como `ColaboradorService` já precisa.
                obj = await service(session, usuario.id, empresa_id).atualizar(item_id, dados)
                return saida.model_validate(obj)

            router.add_api_route(
                "/{item_id}",
                atualizar_item_por_empresa,
                methods=["PUT"],
                response_model=saida,
                name=f"atualizar_{recurso}",
                operation_id=f"atualizar_{recurso}",
            )
        else:

            @pode_falhar(NAO_ENCONTRADO, CONFLITO, *falhas_extra)
            async def atualizar_item_global(
                item_id: uuid.UUID,
                dados: atualizar,  # type: ignore[valid-type]
                usuario: Annotated[Usuario, Depends(pode_editar)],
                session: Sessao,
            ) -> Any:
                obj = await service(session, usuario.id).atualizar(item_id, dados)
                return saida.model_validate(obj)

            router.add_api_route(
                "/{item_id}",
                atualizar_item_global,
                methods=["PUT"],
                response_model=saida,
                name=f"atualizar_{recurso}",
                operation_id=f"atualizar_{recurso}",
            )

    if ROTA_DESATIVAR in rotas:
        if por_empresa:

            @pode_falhar(NAO_ENCONTRADO)
            async def desativar_item_por_empresa(
                item_id: uuid.UUID,
                usuario: Annotated[Usuario, Depends(pode_excluir)],
                session: SessaoEmpresa,
                empresa_id: EmpresaDoPedido,
            ) -> Any:
                obj = await service(session, usuario.id, empresa_id).desativar(item_id)
                return saida.model_validate(obj)

            router.add_api_route(
                "/{item_id}",
                desativar_item_por_empresa,
                methods=["DELETE"],
                response_model=saida,
                name=f"desativar_{recurso}",
                operation_id=f"desativar_{recurso}",
            )
        else:

            @pode_falhar(NAO_ENCONTRADO)
            async def desativar_item_global(
                item_id: uuid.UUID,
                usuario: Annotated[Usuario, Depends(pode_excluir)],
                session: Sessao,
            ) -> Any:
                obj = await service(session, usuario.id).desativar(item_id)
                return saida.model_validate(obj)

            router.add_api_route(
                "/{item_id}",
                desativar_item_global,
                methods=["DELETE"],
                response_model=saida,
                name=f"desativar_{recurso}",
                operation_id=f"desativar_{recurso}",
            )

    return router

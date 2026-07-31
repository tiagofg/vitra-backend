"""O contrato também declara o que dá errado.

Um servidor Python não pode usar tRPC, então `openapi.json` é o contrato tipado do front —
e um contrato que descreve só o caminho feliz obriga o outro lado a descobrir a falha por
tentativa e erro contra o servidor rodando. Aqui as respostas de erro entram no documento.

Duas decisões explicam o formato:

* **Falha se declara uma vez, onde ela nasce.** A dependência que exige o token declara o
  401; a que resolve a empresa declara o 400 e o 403; `require(...)` declara o seu 403 já
  com o par recurso+ação daquela rota. A rota herda tudo pelo grafo de dependências do
  FastAPI. Sem isso seriam 55 listas de `responses` escritas à mão, e duas listas parecidas
  divergem — a primeira rota nova sairia com o contrato errado.
* **Pós-processamento do documento, não `responses=` por rota.** `route.responses` só vira
  schema se o campo correspondente for construído no `__init__` da rota; mexer nele depois
  publicaria um `$ref` pendurado. O documento gerado é a superfície pública e estável.

O 422 do FastAPI é reescrito em vez de acrescentado: ele já existe em toda rota com
parâmetro, mas descreve `HTTPValidationError` — corpo que a API **não** devolve, porque
`registrar_handlers` troca o do FastAPI pelo envelope. Contrato errado é pior que contrato
ausente: o cliente gerado compila e quebra em produção.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any

from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, RouteContext, iter_route_contexts

from app.core.errors import ATRIBUTO_FALHAS, VALIDACAO, EnvelopeErro, Falha, NaoAutenticado

PREFIXO_COMPONENTES = "#/components/schemas/"
NOME_ENVELOPE = EnvelopeErro.__name__
REF_ENVELOPE = f"{PREFIXO_COMPONENTES}{NOME_ENVELOPE}"

# Schemas que o FastAPI cria só para o 422 padrão. Depois da reescrita ninguém aponta para
# eles, e schema órfão vira tipo morto no cliente gerado.
SCHEMAS_DO_422_PADRAO = ("HTTPValidationError", "ValidationError")


def documentar_erros(app: FastAPI) -> None:
    """Faz `app.openapi()` publicar também as respostas de erro.

    Envolve o gerador em vez de substituí-lo: tudo que o FastAPI monta continua igual, e o
    cache de `openapi_schema` segue valendo — o trabalho acontece uma vez por processo.
    """
    gerar = app.openapi

    def openapi() -> dict[str, Any]:
        esquema = app.openapi_schema
        if esquema is None:
            esquema = gerar()
            _injetar_erros(app, esquema)
            app.openapi_schema = esquema
        return esquema

    app.openapi = openapi  # type: ignore[method-assign]


def rotas_da_api(app: FastAPI) -> Iterator[RouteContext]:
    """As mesmas rotas que o gerador do OpenAPI enxerga, na mesma ordem.

    Desde a 0.141 o FastAPI não achata mais as rotas de um `include_router`: elas ficam
    penduradas num roteador intermediário, e `app.routes` só mostra o topo. Reusar o
    `iter_route_contexts` do próprio FastAPI é o que garante que este módulo e o
    `get_openapi` percorram exatamente o mesmo conjunto — um caminho paralelo de travessia
    documentaria rota que não existe, ou pularia rota que existe.
    """
    for contexto in iter_route_contexts(app.routes):
        if isinstance(contexto.original_route, APIRoute):
            yield contexto


def falhas_da_rota(rota: RouteContext) -> list[Falha]:
    """As falhas da rota: as do próprio endpoint mais as de todas as suas dependências.

    Ordenado por status e código para o documento sair estável — `openapi.json` é
    versionado, e diff de ordem aleatória esconde a mudança de verdade.
    """
    unicas: dict[tuple[int, str], Falha] = {}
    for alvo in (rota.endpoint, *_dependencias(rota.dependant)):
        for falha in getattr(alvo, ATRIBUTO_FALHAS, ()):
            unicas.setdefault((falha.status, falha.codigo), falha)
    return sorted(unicas.values(), key=lambda f: (f.status, f.codigo))


def _dependencias(dependant: Dependant) -> Iterator[Callable[..., Any]]:
    """Todo callable do grafo, em profundidade.

    Recursivo porque a declaração pode estar a dois níveis: `SessaoEmpresa` depende de
    `empresa_do_pedido`, que é quem levanta o 400 e o 403, e que por sua vez depende de
    `usuario_atual`, dono do 401.
    """
    for sub in dependant.dependencies:
        if sub.call is not None:
            yield sub.call
        yield from _dependencias(sub)


def _injetar_erros(app: FastAPI, esquema: dict[str, Any]) -> None:
    componentes = esquema.setdefault("components", {}).setdefault("schemas", {})
    componentes.update(_schemas_do_envelope())

    for rota in rotas_da_api(app):
        operacoes = esquema["paths"].get(rota.path_format, {})
        falhas = falhas_da_rota(rota)
        # `or ()` só por causa da assinatura: rota de API sempre tem método.
        for metodo in rota.methods or ():
            operacao = operacoes.get(metodo.lower())
            if operacao is not None:
                _escrever_respostas(operacao, falhas)

    _remover_schemas_orfaos(esquema)


def _escrever_respostas(operacao: dict[str, Any], falhas: list[Falha]) -> None:
    respostas: dict[str, Any] = operacao.setdefault("responses", {})

    # Só onde o FastAPI já declarou 422: rota sem parâmetro nenhum não valida nada, e
    # anunciar uma falha impossível é o mesmo defeito na direção oposta.
    if str(VALIDACAO.status) in respostas:
        falhas = sorted([*falhas, VALIDACAO], key=lambda f: (f.status, f.codigo))

    por_status: dict[int, list[Falha]] = {}
    for falha in falhas:
        por_status.setdefault(falha.status, []).append(falha)

    for status, grupo in por_status.items():
        respostas[str(status)] = _resposta(status, grupo)

    operacao["responses"] = dict(sorted(respostas.items()))


def _resposta(status: int, falhas: list[Falha]) -> dict[str, Any]:
    """Uma resposta por status, com um exemplo nomeado por código.

    Vários códigos caem no mesmo status — `empresa_nao_declarada` e `ordenacao_invalida`
    são os dois 400 de `GET /produtos`. O OpenAPI só admite uma resposta por status, então
    o que distingue os casos é o mapa de `examples`, que é onde o código aparece literal.
    """
    resposta: dict[str, Any] = {
        "description": " ".join(f.descricao for f in falhas),
        "content": {
            "application/json": {
                "schema": {"$ref": REF_ENVELOPE},
                "examples": {
                    f.codigo: {"summary": f.descricao, "value": f.exemplo} for f in falhas
                },
            }
        },
    }
    if status == NaoAutenticado.http_status:
        resposta["headers"] = {
            "WWW-Authenticate": {
                "description": "Sempre `Bearer`.",
                "schema": {"type": "string"},
            }
        }
    return resposta


def _schemas_do_envelope() -> dict[str, Any]:
    """`EnvelopeErro` e o que ele aninha, já com os `$ref` no formato do OpenAPI."""
    esquema = EnvelopeErro.model_json_schema(ref_template=f"{PREFIXO_COMPONENTES}{{model}}")
    aninhados: dict[str, Any] = esquema.pop("$defs", {})
    return {**aninhados, NOME_ENVELOPE: esquema}


def _remover_schemas_orfaos(esquema: dict[str, Any]) -> None:
    componentes: dict[str, Any] = esquema.get("components", {}).get("schemas", {})
    candidatos = [nome for nome in SCHEMAS_DO_422_PADRAO if nome in componentes]
    if not candidatos:
        return

    # Confere referência de verdade antes de remover: se alguma rota ainda apontar para o
    # schema, tirá-lo do documento quebraria o contrato em vez de limpá-lo.
    for nome in candidatos:
        reservado = componentes.pop(nome)
        if f'"{PREFIXO_COMPONENTES}{nome}"' in json.dumps(esquema):
            componentes[nome] = reservado

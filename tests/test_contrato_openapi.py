"""O contrato promete os erros que a API entrega de verdade.

Duas metades, e as duas são necessárias:

* **Cobertura** — nenhuma operação sai do documento escondendo um caminho de erro. Os
  testes daqui derivam a expectativa do próprio contrato (`security`, parâmetro de caminho
  em UUID), nunca do `app/core/openapi.py`; código que se confere sozinho não confere nada.
* **Fidelidade** — o exemplo publicado é o que o servidor responde. Contrato que descreve
  um corpo diferente do real é pior que contrato ausente: o cliente gerado compila e
  quebra em produção, e ninguém desconfia do arquivo.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

from httpx import AsyncClient

from app.core.errors import EnvelopeErro
from app.main import criar_app
from tests.cenario import Cenario

# Montar o app não abre conexão — `criar_app()` só monta rotas e schemas.
CONTRATO: dict[str, Any] = criar_app().openapi()

REF_ENVELOPE = f"#/components/schemas/{EnvelopeErro.__name__}"


def operacoes() -> Iterator[tuple[str, str, dict[str, Any]]]:
    for caminho, metodos in CONTRATO["paths"].items():
        for metodo, operacao in metodos.items():
            yield caminho, metodo, operacao


def erros_declarados(caminho: str, metodo: str, status: int) -> dict[str, Any]:
    """Os exemplos publicados para aquele status, por código."""
    resposta = CONTRATO["paths"][caminho][metodo]["responses"].get(str(status), {})
    conteudo = resposta.get("content", {}).get("application/json", {})
    return {nome: exemplo["value"] for nome, exemplo in conteudo.get("examples", {}).items()}


def conferir(caminho: str, metodo: str, status: int, corpo: dict[str, Any], codigo: str) -> None:
    """O corpo real bate com o exemplo daquele código — mesmo formato, mesma chave."""
    exemplos = erros_declarados(caminho, metodo, status)
    assert codigo in exemplos, f"{metodo.upper()} {caminho} não declara '{codigo}' em {status}"
    assert corpo["erro"]["codigo"] == codigo
    assert corpo.keys() == exemplos[codigo].keys()
    assert corpo["erro"].keys() == exemplos[codigo]["erro"].keys()


# --- cobertura ---------------------------------------------------------------


def test_toda_resposta_de_erro_usa_o_envelope() -> None:
    """Um único formato de erro no contrato inteiro, do 400 ao 422."""
    for caminho, metodo, operacao in operacoes():
        for status, resposta in operacao["responses"].items():
            if int(status) < 400:
                continue
            schema = resposta["content"]["application/json"]["schema"]
            assert schema == {"$ref": REF_ENVELOPE}, f"{metodo.upper()} {caminho} → {status}"


def test_o_422_padrao_do_fastapi_nao_sobrou() -> None:
    """`registrar_handlers` troca o corpo do FastAPI pelo envelope — o contrato acompanha.

    Enquanto `HTTPValidationError` estava publicado, o cliente gerado esperava
    `{detail: [...]}` num 422 que sempre chegou como `{erro: {...}}`.
    """
    assert "HTTPValidationError" not in CONTRATO["components"]["schemas"]
    assert "HTTPValidationError" not in str(CONTRATO)


def test_toda_rota_que_exige_token_declara_401() -> None:
    """`security` no contrato é o próprio FastAPI dizendo que a rota depende do Bearer."""
    for caminho, metodo, operacao in operacoes():
        if not operacao.get("security"):
            continue
        assert "nao_autenticado" in erros_declarados(caminho, metodo, 401), (
            f"{metodo.upper()} {caminho} exige token e não declara 401"
        )


def test_toda_rota_com_id_no_caminho_declara_404() -> None:
    """Guarda contra o `pode_falhar` esquecido.

    Todo UUID no caminho identifica um registro que o serviço busca com `obter()`, e
    `obter()` levanta `NaoEncontrado`. É a regra que uma rota nova quebra sem perceber —
    daí o teste, e não um comentário.
    """
    for caminho, metodo, operacao in operacoes():
        tem_uuid = any(
            p.get("in") == "path" and p.get("schema", {}).get("format") == "uuid"
            for p in operacao.get("parameters", [])
        )
        if not tem_uuid:
            continue
        assert "nao_encontrado" in erros_declarados(caminho, metodo, 404), (
            f"{metodo.upper()} {caminho} recebe um id e não declara 404"
        )


# --- fidelidade: o corpo real bate com o exemplo -----------------------------


async def test_401_sem_token(cliente: AsyncClient) -> None:
    resposta = await cliente.get("/api/v1/grupos")
    assert resposta.status_code == 401
    assert resposta.headers["www-authenticate"] == "Bearer"
    conferir("/api/v1/grupos", "get", 401, resposta.json(), "nao_autenticado")


async def test_403_sem_permissao(cliente: AsyncClient, cabecalho_consultor: dict[str, str]) -> None:
    """O consultor só lê apoio. O exemplo do contrato traz o par recurso+ação da rota."""
    resposta = await cliente.get("/api/v1/grupos", headers=cabecalho_consultor)
    assert resposta.status_code == 403
    conferir("/api/v1/grupos", "get", 403, resposta.json(), "sem_permissao")
    assert resposta.json()["erro"]["campos"] == {"recurso": "grupo", "acao": "ler"}


async def test_400_ordenacao_fora_da_whitelist(
    cliente: AsyncClient, cabecalho_admin: dict[str, str]
) -> None:
    resposta = await cliente.get(
        "/api/v1/usuarios", params={"ordenar_por": "senha_hash"}, headers=cabecalho_admin
    )
    assert resposta.status_code == 400
    conferir("/api/v1/usuarios", "get", 400, resposta.json(), "ordenacao_invalida")


async def test_404_id_inexistente(cliente: AsyncClient, cabecalho_admin: dict[str, str]) -> None:
    resposta = await cliente.get(f"/api/v1/empresas/{uuid.uuid4()}", headers=cabecalho_admin)
    assert resposta.status_code == 404
    conferir("/api/v1/empresas/{empresa_id}", "get", 404, resposta.json(), "nao_encontrado")


async def test_409_codigo_repetido(cliente: AsyncClient, cabecalho_admin: dict[str, str]) -> None:
    corpo = {"codigo": "DUPLA", "razao_social": "Empresa Dupla Ltda"}
    assert (await cliente.post("/api/v1/empresas", json=corpo, headers=cabecalho_admin)).is_success
    resposta = await cliente.post("/api/v1/empresas", json=corpo, headers=cabecalho_admin)
    assert resposta.status_code == 409
    conferir("/api/v1/empresas", "post", 409, resposta.json(), "conflito")


async def test_422_validacao(cliente: AsyncClient, cabecalho_admin: dict[str, str]) -> None:
    """O 422 é o do FastAPI reescrito: status dele, corpo nosso."""
    resposta = await cliente.post("/api/v1/empresas", json={}, headers=cabecalho_admin)
    assert resposta.status_code == 422
    conferir("/api/v1/empresas", "post", 422, resposta.json(), "validacao")


async def test_400_sem_cabecalho_de_empresa(autenticado: AsyncClient, cenario: Cenario) -> None:
    resposta = await autenticado.get("/api/v1/produtos")
    assert resposta.status_code == 400
    conferir("/api/v1/produtos", "get", 400, resposta.json(), "empresa_nao_declarada")


async def test_403_empresa_de_outro(so_abacaxi: AsyncClient, cenario: Cenario) -> None:
    resposta = await so_abacaxi.get("/api/v1/produtos", headers={"X-Empresa-Id": str(cenario.uva)})
    assert resposta.status_code == 403
    conferir("/api/v1/produtos", "get", 403, resposta.json(), "sem_vinculo_com_empresa")

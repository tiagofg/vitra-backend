"""`[busca +...]` de produtos por código próprio **e** por código do fornecedor."""

from __future__ import annotations

from httpx import AsyncClient

from app.modules.empresa.models import Empresa
from tests.cenario import parceiro_json


def _cabecalho(cabecalho_admin: dict[str, str], empresa: Empresa) -> dict[str, str]:
    return {**cabecalho_admin, "X-Empresa-Id": str(empresa.id)}


async def _criar_produto_comparceiro_json(
    cliente: AsyncClient,
    cabecalho: dict[str, str],
    *,
    codigo: str,
    descricao: str,
    codigo_fornecedor: str,
) -> str:
    fornecedor_id = (
        await cliente.post(
            "/api/v1/parceiros",
            json=parceiro_json(f"FOR-{codigo}", f"Fornecedor de {codigo}"),
            headers=cabecalho,
        )
    ).json()["id"]
    produto = await cliente.post(
        "/api/v1/produtos", json={"codigo": codigo, "descricao": descricao}, headers=cabecalho
    )
    produto_id = produto.json()["id"]
    await cliente.put(
        f"/api/v1/produtos/{produto_id}",
        json={
            "fornecedores": [
                {"fornecedor_id": fornecedor_id, "codigo_fornecedor": codigo_fornecedor}
            ]
        },
        headers=cabecalho,
    )
    return produto_id


async def test_lookup_por_codigo_proprio(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    cabecalho = _cabecalho(cabecalho_admin, empresa)
    await cliente.post(
        "/api/v1/produtos",
        json={"codigo": "PEND001", "descricao": "Pendente São Paulo"},
        headers=cabecalho,
    )

    resposta = await cliente.get(
        "/api/v1/produtos/lookup", params={"q": "pend001"}, headers=cabecalho
    )
    assert resposta.status_code == 200
    itens = resposta.json()
    assert len(itens) == 1
    assert itens[0]["codigo"] == "PEND001"
    assert itens[0]["extras"] == {}


async def test_lookup_por_descricao_ignora_acento(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    cabecalho = _cabecalho(cabecalho_admin, empresa)
    await cliente.post(
        "/api/v1/produtos",
        json={"codigo": "PEND001", "descricao": "Pendente São Paulo"},
        headers=cabecalho,
    )

    resposta = await cliente.get(
        "/api/v1/produtos/lookup", params={"q": "sao paulo"}, headers=cabecalho
    )
    assert len(resposta.json()) == 1


async def test_lookup_por_codigo_doparceiro_json(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    """A tela de orçamento precisa achar o item digitando o código que o fornecedor usa,
    não só o código próprio."""
    cabecalho = _cabecalho(cabecalho_admin, empresa)
    produto_id = await _criar_produto_comparceiro_json(
        cliente,
        cabecalho,
        codigo="PEND001",
        descricao="Pendente Aurora",
        codigo_fornecedor="XYZ-999",
    )

    por_codigo_proprio = await cliente.get(
        "/api/v1/produtos/lookup", params={"q": "PEND001"}, headers=cabecalho
    )
    assert {i["id"] for i in por_codigo_proprio.json()} == {produto_id}

    por_codigo_fornecedor = await cliente.get(
        "/api/v1/produtos/lookup", params={"q": "xyz-999"}, headers=cabecalho
    )
    itens = por_codigo_fornecedor.json()
    assert {i["id"] for i in itens} == {produto_id}
    # O `extras` diz que o casamento veio do fornecedor, não do código próprio.
    assert itens[0]["extras"]["codigo_fornecedor"] == "XYZ-999"


async def test_lookup_com_dois_fornecedores_nao_duplica_produto(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    """`EXISTS` correlacionado, não `JOIN` — um produto com dois fornecedores não pode
    aparecer duas vezes no resultado."""
    cabecalho = _cabecalho(cabecalho_admin, empresa)
    produto_id = (
        await cliente.post(
            "/api/v1/produtos", json={"codigo": "PROD001", "descricao": "Teste"}, headers=cabecalho
        )
    ).json()["id"]
    fornecedor_a = (
        await cliente.post(
            "/api/v1/parceiros",
            json=parceiro_json("FORA", "Fornecedor A"),
            headers=cabecalho,
        )
    ).json()["id"]
    fornecedor_b = (
        await cliente.post(
            "/api/v1/parceiros",
            json=parceiro_json("FORB", "Fornecedor B"),
            headers=cabecalho,
        )
    ).json()["id"]
    await cliente.put(
        f"/api/v1/produtos/{produto_id}",
        json={
            "fornecedores": [
                {"fornecedor_id": fornecedor_a, "codigo_fornecedor": "COD-COMUM"},
                {"fornecedor_id": fornecedor_b, "codigo_fornecedor": "COD-COMUM"},
            ]
        },
        headers=cabecalho,
    )

    resposta = await cliente.get(
        "/api/v1/produtos/lookup", params={"q": "COD-COMUM"}, headers=cabecalho
    )
    itens = resposta.json()
    assert len(itens) == 1
    assert itens[0]["id"] == produto_id

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.apoio.models import Cidade, Uf
from app.modules.empresa.models import Empresa


@pytest.fixture
async def sao_paulo(sessao: AsyncSession) -> Cidade:
    uf = Uf(sigla="SP", nome="São Paulo", codigo_ibge="35")
    sessao.add(uf)
    await sessao.flush()
    cidade = Cidade(uf_id=uf.id, nome="São Paulo", codigo_ibge="3550308")
    sessao.add(cidade)
    await sessao.flush()
    return cidade


@pytest.mark.parametrize("consulta", ["sao", "SAO", "são", "São Paulo", "paulo"])
async def test_lookup_de_cidade_encontra_com_e_sem_acento(
    cliente: AsyncClient,
    cabecalho_admin: dict[str, str],
    sao_paulo: Cidade,
    consulta: str,
) -> None:
    """Ninguém digita acento num campo de busca."""
    resposta = await cliente.get(
        "/api/v1/cidades/lookup", params={"q": consulta}, headers=cabecalho_admin
    )
    assert resposta.status_code == 200
    assert [item["label"] for item in resposta.json()] == ["São Paulo - SP"]


async def test_lookup_sem_acento_nao_deixa_de_filtrar(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], sao_paulo: Cidade
) -> None:
    resposta = await cliente.get(
        "/api/v1/cidades/lookup", params={"q": "curitiba"}, headers=cabecalho_admin
    )
    assert resposta.json() == []


@pytest.mark.parametrize("consulta", ["ilumina", "iluminacao", "ILUMINAÇÃO"])
async def test_busca_de_listagem_ignora_acento(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], consulta: str
) -> None:
    await cliente.post(
        "/api/v1/apoio/marca",
        json={"descricao": "Bella Iluminação"},
        headers=cabecalho_admin,
    )
    resposta = await cliente.get(
        "/api/v1/apoio/marca", params={"busca": consulta}, headers=cabecalho_admin
    )
    assert resposta.json()["total"] == 1


async def test_lookup_de_apoio_ignora_acento(
    cliente: AsyncClient, cabecalho_admin: dict[str, str]
) -> None:
    await cliente.post(
        "/api/v1/apoio/acabamento",
        json={"descricao": "Alumínio Escovado"},
        headers=cabecalho_admin,
    )
    resposta = await cliente.get(
        "/api/v1/apoio/acabamento/lookup", params={"q": "aluminio"}, headers=cabecalho_admin
    )
    assert [item["label"] for item in resposta.json()] == ["Alumínio Escovado"]


async def test_lookup_de_empresa_ignora_acento(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    await cliente.post(
        "/api/v1/empresas",
        json={"codigo": "VIAHF", "razao_social": "Via HF Iluminação Ltda"},
        headers=cabecalho_admin,
    )
    resposta = await cliente.get(
        "/api/v1/empresas/lookup", params={"q": "iluminacao"}, headers=cabecalho_admin
    )
    # As duas empresas do grupo têm "Iluminação" na razão social.
    assert sorted(item["codigo"] for item in resposta.json()) == ["VERTZ", "VIAHF"]

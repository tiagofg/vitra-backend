from __future__ import annotations

from httpx import AsyncClient


async def _semear_marcas(cliente: AsyncClient, cabecalho: dict[str, str], quantas: int) -> None:
    for i in range(quantas):
        await cliente.post(
            "/api/v1/apoio/marca",
            json={"descricao": f"Marca {i:02d}", "ordem": i},
            headers=cabecalho,
        )


async def test_paginacao_reporta_total_e_paginas(
    cliente: AsyncClient, cabecalho_admin: dict[str, str]
) -> None:
    await _semear_marcas(cliente, cabecalho_admin, 7)

    resposta = await cliente.get(
        "/api/v1/apoio/marca", params={"pagina": 1, "tamanho": 3}, headers=cabecalho_admin
    )
    pagina = resposta.json()
    assert pagina["total"] == 7
    assert pagina["paginas"] == 3
    assert len(pagina["itens"]) == 3

    ultima = await cliente.get(
        "/api/v1/apoio/marca", params={"pagina": 3, "tamanho": 3}, headers=cabecalho_admin
    )
    assert len(ultima.json()["itens"]) == 1


async def test_paginas_nao_repetem_nem_pulam_itens(
    cliente: AsyncClient, cabecalho_admin: dict[str, str]
) -> None:
    await _semear_marcas(cliente, cabecalho_admin, 10)

    vistos: list[str] = []
    for pagina in (1, 2, 3, 4):
        resposta = await cliente.get(
            "/api/v1/apoio/marca",
            params={"pagina": pagina, "tamanho": 3, "ordenar_por": "ordem"},
            headers=cabecalho_admin,
        )
        vistos += [item["id"] for item in resposta.json()["itens"]]

    assert len(vistos) == 10
    assert len(set(vistos)) == 10


async def test_ordenacao_ascendente_e_descendente(
    cliente: AsyncClient, cabecalho_admin: dict[str, str]
) -> None:
    await _semear_marcas(cliente, cabecalho_admin, 3)

    asc = await cliente.get(
        "/api/v1/apoio/marca",
        params={"ordenar_por": "descricao", "ordem": "asc"},
        headers=cabecalho_admin,
    )
    desc = await cliente.get(
        "/api/v1/apoio/marca",
        params={"ordenar_por": "descricao", "ordem": "desc"},
        headers=cabecalho_admin,
    )
    nomes_asc = [i["descricao"] for i in asc.json()["itens"]]
    nomes_desc = [i["descricao"] for i in desc.json()["itens"]]
    assert nomes_asc == sorted(nomes_asc)
    assert nomes_desc == list(reversed(nomes_asc))


async def test_ordenar_por_campo_fora_da_whitelist_e_recusado(
    cliente: AsyncClient, cabecalho_admin: dict[str, str]
) -> None:
    """`ordenar_por` vem do cliente — só pode citar coluna declarada no ListingSpec."""
    resposta = await cliente.get(
        "/api/v1/apoio/marca",
        params={"ordenar_por": "senha_hash"},
        headers=cabecalho_admin,
    )
    assert resposta.status_code == 400
    assert resposta.json()["erro"]["codigo"] == "ordenacao_invalida"


async def test_busca_textual_filtra(cliente: AsyncClient, cabecalho_admin: dict[str, str]) -> None:
    await cliente.post("/api/v1/apoio/marca", json={"descricao": "Lumini"}, headers=cabecalho_admin)
    await cliente.post(
        "/api/v1/apoio/marca", json={"descricao": "Bella Luce"}, headers=cabecalho_admin
    )

    resposta = await cliente.get(
        "/api/v1/apoio/marca", params={"busca": "bella"}, headers=cabecalho_admin
    )
    assert resposta.json()["total"] == 1


async def test_busca_por_codigo_e_exata(
    cliente: AsyncClient, cabecalho_admin: dict[str, str]
) -> None:
    await cliente.post(
        "/api/v1/apoio/marca",
        json={"descricao": "Lumini", "codigo": "lum"},
        headers=cabecalho_admin,
    )
    await cliente.post(
        "/api/v1/apoio/marca",
        json={"descricao": "Luminária X", "codigo": "lum_x"},
        headers=cabecalho_admin,
    )

    resposta = await cliente.get(
        "/api/v1/apoio/marca", params={"busca_codigo": "lum"}, headers=cabecalho_admin
    )
    assert resposta.json()["total"] == 1
    assert resposta.json()["itens"][0]["codigo"] == "lum"


async def test_filtro_por_ativo(cliente: AsyncClient, cabecalho_admin: dict[str, str]) -> None:
    primeiro = await cliente.post(
        "/api/v1/apoio/marca", json={"descricao": "Lumini"}, headers=cabecalho_admin
    )
    await cliente.post(
        "/api/v1/apoio/marca", json={"descricao": "Bella Luce"}, headers=cabecalho_admin
    )
    await cliente.delete(f"/api/v1/apoio/marca/{primeiro.json()['id']}", headers=cabecalho_admin)

    ativos = await cliente.get(
        "/api/v1/apoio/marca", params={"ativo": True}, headers=cabecalho_admin
    )
    inativos = await cliente.get(
        "/api/v1/apoio/marca", params={"ativo": False}, headers=cabecalho_admin
    )
    todos = await cliente.get("/api/v1/apoio/marca", headers=cabecalho_admin)

    assert ativos.json()["total"] == 1
    assert inativos.json()["total"] == 1
    assert todos.json()["total"] == 2


async def test_tamanho_de_pagina_tem_teto(
    cliente: AsyncClient, cabecalho_admin: dict[str, str]
) -> None:
    resposta = await cliente.get(
        "/api/v1/apoio/marca", params={"tamanho": 10_000}, headers=cabecalho_admin
    )
    assert resposta.status_code == 422

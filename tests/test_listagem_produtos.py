"""Listagem de produtos server-side — entregável nº 5 do bake-off.

Busca textual, ordenação e paginação **no servidor**, devolvendo `{itens, total, pagina,
tamanho, paginas}` — o contrato que o TanStack Table server-side do front espera.

Os casos de borda testados aqui estão nos dados de propósito: preço `0` e
registros `active = false`. São os três que um `or` distraído colapsa — `0 or None` dá
`None`, e "sem preço" vira "custa zero" sem ninguém perceber.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.tenancy import declarar_empresa
from app.modules.apoio.models import DominioApoio
from app.modules.produtos.models import Produto, Variante, VarianteEmpresa
from tests.cenario import Cenario, apoio_id


@pytest.fixture
async def catalogo_de_borda(motor_runtime: AsyncEngine, cenario: Cenario) -> dict[str, str]:
    """Três produtos que exercitam o que costuma quebrar."""
    itens = {
        "grafite": f"BRD-GRAFITE-{cenario.sufixo}",
        "inativo": f"BRD-INATIVO-{cenario.sufixo}",
        "sem_preco": f"BRD-SEMPRECO-{cenario.sufixo}",
    }
    async with AsyncSession(motor_runtime, expire_on_commit=False) as sessao:
        await declarar_empresa(sessao, cenario.abacaxi)

        # Preço zero — não é "sem preço", é preço zero.
        zerado = Produto(
            tenant_id=cenario.abacaxi,
            codigo=itens["grafite"],
            descricao="Trilho Órion — grafite acetinado",
            ativo=True,
        )
        # `ativo = false` continua na base e só aparece quando pedido.
        inativo = Produto(
            tenant_id=cenario.abacaxi,
            codigo=itens["inativo"],
            descricao="Spot Íris — descontinuado",
            ativo=False,
        )
        # Variante sem linha em `product_tenant`: preço ausente, que é diferente de zero.
        sem_preco = Produto(
            tenant_id=cenario.abacaxi,
            codigo=itens["sem_preco"],
            descricao="Luminária Ácis — a definir",
            ativo=True,
        )
        sessao.add_all([zerado, inativo, sem_preco])
        await sessao.flush()

        grafite_id = await apoio_id(sessao, DominioApoio.acabamento, "grafite", "Grafite")
        cru_id = await apoio_id(sessao, DominioApoio.acabamento, "cru", "Cru")
        unico_id = await apoio_id(sessao, DominioApoio.tamanho, "u", "Único")

        variante_zerada = Variante(
            tenant_id=cenario.abacaxi,
            produto_id=zerado.id,
            acabamento_id=grafite_id,
            tamanho_id=unico_id,
            ativo=True,
        )
        variante_muda = Variante(
            tenant_id=cenario.abacaxi,
            produto_id=sem_preco.id,
            acabamento_id=cru_id,
            tamanho_id=unico_id,
            ativo=True,
        )
        sessao.add_all([variante_zerada, variante_muda])
        await sessao.flush()

        sessao.add(
            VarianteEmpresa(
                tenant_id=cenario.abacaxi,
                variante_id=variante_zerada.id,
                preco_cents=0,
                estoque_minimo=Decimal("0.000"),
            )
        )
        await sessao.commit()
    return itens


def _cabecalho(empresa: uuid.UUID) -> dict[str, str]:
    return {"X-Empresa-Id": str(empresa)}


async def test_pagina_tem_o_formato_que_o_tanstack_table_espera(
    autenticado: AsyncClient, cenario: Cenario
) -> None:
    resposta = await autenticado.get("/api/v1/produtos", headers=_cabecalho(cenario.abacaxi))

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert set(corpo) == {"itens", "total", "pagina", "tamanho", "paginas"}
    assert corpo["total"] >= 1


async def test_busca_textual_ignora_acento_e_caixa(
    autenticado: AsyncClient, cenario: Cenario, catalogo_de_borda: dict[str, str]
) -> None:
    """Quem digita num campo de busca não põe acento. `orion` tem que achar `Órion`."""
    for termo in ("orion", "ÓRION", "Órion"):
        resposta = await autenticado.get(
            "/api/v1/produtos",
            params={"busca": termo},
            headers=_cabecalho(cenario.abacaxi),
        )
        codigos = {item["codigo"] for item in resposta.json()["itens"]}
        assert catalogo_de_borda["grafite"] in codigos, f"busca por {termo!r} não achou"


async def test_preco_zero_e_diferente_de_sem_preco(
    autenticado: AsyncClient, cenario: Cenario, catalogo_de_borda: dict[str, str]
) -> None:
    """`0` e `None` não podem colapsar. É o caso de borda mais fácil de errar em silêncio."""
    resposta = await autenticado.get(
        "/api/v1/produtos", params={"tamanho": 200}, headers=_cabecalho(cenario.abacaxi)
    )
    por_codigo = {item["codigo"]: item for item in resposta.json()["itens"]}

    zerado = por_codigo[catalogo_de_borda["grafite"]]
    assert zerado["preco_minimo_cents"] == 0
    assert zerado["variantes"][0]["preco"]["preco_cents"] == 0
    # Saldo não sai mais aqui: virou `stock_balances`, por variante **e** local
    # (`GET /estoque/saldos/{variante_id}`). O que continua valendo neste teste é a
    # distinção que ele existe para provar: preço `0` é diferente de preço ausente.
    assert "estoque" not in zerado["variantes"][0]["preco"]

    mudo = por_codigo[catalogo_de_borda["sem_preco"]]
    assert mudo["preco_minimo_cents"] is None
    assert mudo["variantes"][0]["preco"] is None


async def test_filtro_ativo_separa_os_tres_estados(
    autenticado: AsyncClient, cenario: Cenario, catalogo_de_borda: dict[str, str]
) -> None:
    """`ativo` ausente = todos; `true` = só ativos; `false` = só inativos."""

    async def codigos(**params: object) -> set[str]:
        resposta = await autenticado.get(
            "/api/v1/produtos",
            params={"tamanho": 200, **params},
            headers=_cabecalho(cenario.abacaxi),
        )
        return {item["codigo"] for item in resposta.json()["itens"]}

    todos = await codigos()
    assert catalogo_de_borda["inativo"] in todos
    assert catalogo_de_borda["grafite"] in todos

    assert catalogo_de_borda["inativo"] not in await codigos(ativo="true")
    assert await codigos(ativo="false") >= {catalogo_de_borda["inativo"]}


async def test_ordenacao_e_paginacao_saem_do_servidor(
    autenticado: AsyncClient, cenario: Cenario, catalogo_de_borda: dict[str, str]
) -> None:
    crescente = await autenticado.get(
        "/api/v1/produtos",
        params={"ordenar_por": "codigo", "ordem": "asc", "tamanho": 200},
        headers=_cabecalho(cenario.abacaxi),
    )
    codigos = [item["codigo"] for item in crescente.json()["itens"]]
    assert codigos == sorted(codigos)

    primeira = await autenticado.get(
        "/api/v1/produtos",
        params={"ordenar_por": "codigo", "pagina": 1, "tamanho": 2},
        headers=_cabecalho(cenario.abacaxi),
    )
    segunda = await autenticado.get(
        "/api/v1/produtos",
        params={"ordenar_por": "codigo", "pagina": 2, "tamanho": 2},
        headers=_cabecalho(cenario.abacaxi),
    )
    corpo = primeira.json()
    assert len(corpo["itens"]) == 2
    assert corpo["total"] > 2, "o total é o do conjunto inteiro, não o da página"
    # Sem desempate estável, a página 2 poderia repetir uma linha da página 1.
    assert not {i["codigo"] for i in corpo["itens"]} & {
        i["codigo"] for i in segunda.json()["itens"]
    }


async def test_ordenar_por_campo_fora_da_whitelist_e_recusado(
    autenticado: AsyncClient, cenario: Cenario
) -> None:
    """`ordenar_por` vem do cliente e nunca pode virar SQL arbitrário."""
    resposta = await autenticado.get(
        "/api/v1/produtos",
        params={"ordenar_por": "tenant_id"},
        headers=_cabecalho(cenario.abacaxi),
    )

    assert resposta.status_code == 400
    assert resposta.json()["erro"]["codigo"] == "ordenacao_invalida"


async def test_empresa_id_na_query_string_nao_muda_o_recorte(
    autenticado: AsyncClient, cenario: Cenario
) -> None:
    """`empresa_id` saiu do contrato (S0.5): `ListParams` não o declara mais em nenhuma
    listagem. Um valor extra na query string é apenas ignorado pelo FastAPI — o que este
    teste garante é que ele não tem *nenhum* efeito sobre o recorte, que continua vindo só
    do `X-Empresa-Id`/claim declarado na transação.
    """
    resposta = await autenticado.get(
        "/api/v1/produtos",
        params={"empresa_id": str(cenario.uva), "tamanho": 200},
        headers=_cabecalho(cenario.abacaxi),
    )

    codigos = {item["codigo"] for item in resposta.json()["itens"]}
    assert cenario.codigo_abacaxi in codigos
    assert cenario.codigo_uva not in codigos

"""Listagem de produtos server-side — entregável nº 5 do bake-off.

Busca textual, ordenação e paginação **no servidor**, devolvendo `{itens, total, pagina,
tamanho, paginas}` — o contrato que o TanStack Table server-side do front espera.

Os casos de borda testados aqui estão nos dados de propósito: preço `0`, estoque `0` e
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
from app.modules.bakeoff.models import Produto, ProdutoEmpresa, Variante
from tests.bakeoff import Cenario


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

        # Preço zero e estoque zero — não é "sem preço", é preço zero.
        zerado = Produto(
            tenant_id=cenario.abacaxi,
            code=itens["grafite"],
            description="Trilho Órion — grafite acetinado",
            active=True,
        )
        # `active = false` continua na base e só aparece quando pedido.
        inativo = Produto(
            tenant_id=cenario.abacaxi,
            code=itens["inativo"],
            description="Spot Íris — descontinuado",
            active=False,
        )
        # Variante sem linha em `product_tenant`: preço ausente, que é diferente de zero.
        sem_preco = Produto(
            tenant_id=cenario.abacaxi,
            code=itens["sem_preco"],
            description="Luminária Ácis — a definir",
            active=True,
        )
        sessao.add_all([zerado, inativo, sem_preco])
        await sessao.flush()

        variante_zerada = Variante(
            tenant_id=cenario.abacaxi,
            product_id=zerado.id,
            finish="grafite",
            size="U",
            active=True,
        )
        variante_muda = Variante(
            tenant_id=cenario.abacaxi,
            product_id=sem_preco.id,
            finish="cru",
            size="U",
            active=True,
        )
        sessao.add_all([variante_zerada, variante_muda])
        await sessao.flush()

        sessao.add(
            ProdutoEmpresa(
                tenant_id=cenario.abacaxi,
                variant_id=variante_zerada.id,
                price_cents=0,
                stock_qty=Decimal("0.000"),
                min_stock=Decimal("0.000"),
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
    assert Decimal(zerado["variantes"][0]["preco"]["estoque"]) == 0

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
        params={"ordenar_por": "code", "ordem": "asc", "tamanho": 200},
        headers=_cabecalho(cenario.abacaxi),
    )
    codigos = [item["codigo"] for item in crescente.json()["itens"]]
    assert codigos == sorted(codigos)

    primeira = await autenticado.get(
        "/api/v1/produtos",
        params={"ordenar_por": "code", "pagina": 1, "tamanho": 2},
        headers=_cabecalho(cenario.abacaxi),
    )
    segunda = await autenticado.get(
        "/api/v1/produtos",
        params={"ordenar_por": "code", "pagina": 2, "tamanho": 2},
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
    """`empresa_id` saiu do contrato. Se sobrasse, reabriria por fora a porta do RLS.

    O parâmetro ainda existe em `ListParams` por causa das tabelas da S0 que não migraram;
    o que este teste garante é que ele **não tem efeito** sobre uma tabela sob RLS.
    """
    resposta = await autenticado.get(
        "/api/v1/produtos",
        params={"empresa_id": str(cenario.uva), "tamanho": 200},
        headers=_cabecalho(cenario.abacaxi),
    )

    codigos = {item["codigo"] for item in resposta.json()["itens"]}
    assert cenario.codigo_abacaxi in codigos
    assert cenario.codigo_uva not in codigos

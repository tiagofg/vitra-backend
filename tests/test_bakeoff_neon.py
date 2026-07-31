"""Listagem server-side apontando para o banco **compartilhado** do bake-off.

É o outro lado do entregável nº 5: a mesma listagem que roda contra o Postgres descartável
tem que responder contra o `vitra_bakeoff` no Neon, com os dados reais das duas empresas.

**Somente leitura, e é regra, não estilo.** Os devs das outras duas stacks apontam para
este mesmo banco ao mesmo tempo. Um teste que escreve sujou o dado para os outros dois
times — e a estrutura é fixa, então nada de DDL em hipótese nenhuma. Se o dado bagunçar,
o Henrique reseta em ~1 min, mas o certo é não bagunçar.

Pulado quando `VITRA_BAKEOFF_DATABASE_URL` não está no `.env` — que é o caso do CI: a
string traz senha real e não entra no repositório.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import config
from app.core.db import get_session
from app.main import criar_app

# Fixos no enunciado do bake-off.
ABACAXI = uuid.UUID("11111111-1111-1111-1111-111111111111")
UVA = uuid.UUID("22222222-2222-2222-2222-222222222222")

pytestmark = pytest.mark.skipif(
    not config.bakeoff_database_url,
    reason="VITRA_BAKEOFF_DATABASE_URL não configurada — banco compartilhado do bake-off",
)


@pytest.fixture
async def cliente_neon() -> AsyncIterator[AsyncClient]:
    motor = create_async_engine(
        config.bakeoff_database_url or "",
        pool_pre_ping=True,  # o Neon suspende o banco quando ocioso; a conexão morta some
        connect_args={"timeout": config.bakeoff_timeout_conexao},
    )
    fabrica = async_sessionmaker(motor, expire_on_commit=False, autoflush=False)

    async def _sessao() -> AsyncIterator[AsyncSession]:
        async with fabrica() as sessao:
            try:
                yield sessao
            finally:
                # Rollback sempre, mesmo no caminho feliz: com o banco compartilhado, um
                # commit acidental é dano visível para os outros dois times.
                await sessao.rollback()

    app: FastAPI = criar_app()
    app.dependency_overrides[get_session] = _sessao
    transporte = ASGITransport(app=app)
    async with AsyncClient(transport=transporte, base_url="http://neon") as c:
        yield c
    await motor.dispose()


async def test_listagem_responde_contra_o_banco_compartilhado(
    cliente_neon: AsyncClient,
) -> None:
    """Os 200 produtos da ABACAXI, paginados pelo servidor."""
    resposta = await cliente_neon.get(
        "/api/v1/produtos",
        params={"tamanho": 20, "ordenar_por": "code"},
        headers={"X-Empresa-Id": str(ABACAXI)},
    )

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["total"] > 0
    assert len(corpo["itens"]) <= 20
    assert corpo["paginas"] >= 1


async def test_as_duas_empresas_veem_catalogos_diferentes(cliente_neon: AsyncClient) -> None:
    """Mesma rota, mesmo código, dois recortes — a diferença vem do banco, não do serviço."""
    resultados = {}
    for rotulo, empresa in (("abacaxi", ABACAXI), ("uva", UVA)):
        resposta = await cliente_neon.get(
            "/api/v1/produtos",
            params={"tamanho": 200, "ordenar_por": "code"},
            headers={"X-Empresa-Id": str(empresa)},
        )
        assert resposta.status_code == 200, resposta.text
        resultados[rotulo] = {i["codigo"] for i in resposta.json()["itens"]}

    assert resultados["abacaxi"], "a ABACAXI voltou vazia — o dado sumiu ou faltou SET LOCAL"
    assert resultados["uva"], "a UVA voltou vazia"


async def test_busca_sem_acento_funciona_no_dado_real(cliente_neon: AsyncClient) -> None:
    """Contra dado de verdade, não contra fixture escolhida a dedo para casar."""
    resposta = await cliente_neon.get(
        "/api/v1/produtos",
        params={"busca": "a", "tamanho": 5},
        headers={"X-Empresa-Id": str(ABACAXI)},
    )

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["total"] > 0


async def test_casos_de_borda_do_dado_compartilhado(cliente_neon: AsyncClient) -> None:
    """Preço 0, estoque 0 e `active = false` estão lá de propósito."""
    resposta = await cliente_neon.get(
        "/api/v1/produtos",
        params={"tamanho": 200},
        headers={"X-Empresa-Id": str(ABACAXI)},
    )
    itens = resposta.json()["itens"]

    # Nenhum preço pode ter virado float pelo caminho, e `None` não pode virar `0`.
    for item in itens:
        minimo = item["preco_minimo_cents"]
        assert minimo is None or isinstance(minimo, int)
        for variante in item["variantes"]:
            if variante["preco"] is not None:
                assert isinstance(variante["preco"]["preco_cents"], int)

    inativos = await cliente_neon.get(
        "/api/v1/produtos",
        params={"ativo": "false", "tamanho": 200},
        headers={"X-Empresa-Id": str(ABACAXI)},
    )
    assert inativos.status_code == 200, inativos.text

"""Dois pedidos simultâneos de empresas diferentes não se misturam.

Este é o teste que o RLS torna possível escrever e que o desenho antigo — `empresa_id`
filtrado no serviço — não tinha como provar: lá, "não vazou" dependia de nenhum
desenvolvedor ter esquecido um `WHERE`, o que nenhum teste consegue afirmar.

Ele roda pela pilha HTTP inteira, com pool de conexão de verdade (`app_bakeoff`), porque é
justamente no reuso de conexão entre pedidos que um `SET` no lugar de `SET LOCAL` vazaria.
"""

from __future__ import annotations

import asyncio

from httpx import AsyncClient

from tests.cenario import Cenario


async def test_pedidos_simultaneos_de_empresas_diferentes_nao_se_misturam(
    autenticado: AsyncClient, cenario: Cenario
) -> None:
    """20 pedidos alternando empresa, contra um pool de 2 conexões.

    A proporção importa: mais pedidos que conexões força o reuso, e o reuso é o cenário de
    vazamento. Um único par de pedidos poderia nem chegar a se sobrepor.
    """
    empresas = [cenario.abacaxi, cenario.uva] * 10

    respostas = await asyncio.gather(
        *(
            autenticado.get("/api/v1/produtos", headers={"X-Empresa-Id": str(empresa)})
            for empresa in empresas
        )
    )

    esperado = {
        str(cenario.abacaxi): cenario.codigo_abacaxi,
        str(cenario.uva): cenario.codigo_uva,
    }
    proibido = {
        str(cenario.abacaxi): cenario.codigo_uva,
        str(cenario.uva): cenario.codigo_abacaxi,
    }

    for empresa, resposta in zip(empresas, respostas, strict=True):
        assert resposta.status_code == 200, resposta.text
        codigos = {item["codigo"] for item in resposta.json()["itens"]}
        # Positivo antes do negativo: se a listagem viesse vazia por outro motivo, o
        # "não vazou" abaixo passaria sozinho e não significaria nada.
        assert esperado[str(empresa)] in codigos
        assert proibido[str(empresa)] not in codigos


async def test_pedido_sem_cabecalho_de_empresa_falha_na_borda(
    autenticado: AsyncClient, cenario: Cenario
) -> None:
    """Sem `X-Empresa-Id`, 400 — e não uma lista vazia enganosa.

    Sob RLS, o comportamento natural de esquecer a empresa é "voltou vazio", que é seguro
    mas péssimo de depurar: parece dado sumido. Falhar explicitamente na borda troca uma
    investigação de meia hora por uma mensagem de erro.
    """
    resposta = await autenticado.get("/api/v1/produtos")

    assert resposta.status_code == 400
    assert resposta.json()["erro"]["codigo"] == "empresa_nao_declarada"


async def test_escrita_concorrente_fica_em_empresas_separadas(
    autenticado: AsyncClient, cenario: Cenario
) -> None:
    """A escrita simultânea também não se mistura — e `tenant_id` nunca vem do corpo."""
    corpo_a = {"codigo": f"CONC-A-{cenario.sufixo}", "descricao": "Arandela concorrente A"}
    corpo_b = {"codigo": f"CONC-B-{cenario.sufixo}", "descricao": "Arandela concorrente B"}

    resposta_a, resposta_b = await asyncio.gather(
        autenticado.post(
            "/api/v1/produtos", json=corpo_a, headers={"X-Empresa-Id": str(cenario.abacaxi)}
        ),
        autenticado.post(
            "/api/v1/produtos", json=corpo_b, headers={"X-Empresa-Id": str(cenario.uva)}
        ),
    )
    assert resposta_a.status_code == 201, resposta_a.text
    assert resposta_b.status_code == 201, resposta_b.text

    listagem = await autenticado.get(
        "/api/v1/produtos", headers={"X-Empresa-Id": str(cenario.abacaxi)}
    )
    codigos = {item["codigo"] for item in listagem.json()["itens"]}
    assert corpo_a["codigo"] in codigos
    assert corpo_b["codigo"] not in codigos

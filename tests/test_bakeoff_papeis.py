"""Identidade é global; papel é por empresa.

O enunciado do bake-off traz ANA SILVA (`ana@grupo.dev`) como `admin` na ABACAXI **e**
`operator-sales` na UVA. Não é detalhe de fixture: é o caso que prova por que o papel não
pode ser coluna de `employees`, e por que `employee_company` tem `tenant_id` na chave.
"""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.tenancy import declarar_empresa
from app.modules.bakeoff.models import Colaborador, ColaboradorEmpresa
from tests.bakeoff import Cenario, criar_colaborador_nos_dois


async def test_mesma_pessoa_tem_papel_diferente_em_cada_empresa(
    motor_runtime: AsyncEngine, cenario: Cenario
) -> None:
    pessoa_id = await criar_colaborador_nos_dois(motor_runtime, cenario)

    papeis = {}
    for rotulo, empresa_id in (("abacaxi", cenario.abacaxi), ("uva", cenario.uva)):
        async with AsyncSession(motor_runtime) as sessao:
            await declarar_empresa(sessao, empresa_id)
            vinculos = (await sessao.execute(select(ColaboradorEmpresa))).scalars().all()
            # O RLS recorta `employee_company` também: cada empresa vê só o vínculo dela.
            assert all(v.tenant_id == empresa_id for v in vinculos)
            papeis[rotulo] = {v.role for v in vinculos if v.employee_id == pessoa_id}

    assert papeis["abacaxi"] == {"admin"}
    assert papeis["uva"] == {"operator-sales"}


async def test_identidade_do_colaborador_e_unica_no_grupo(
    motor_runtime: AsyncEngine, cenario: Cenario
) -> None:
    """`employees` é global e não tem RLS — a pessoa é a mesma linha nas duas empresas."""
    pessoa_id = await criar_colaborador_nos_dois(motor_runtime, cenario)

    async with AsyncSession(motor_runtime) as sessao:
        # Sem empresa declarada e mesmo assim a pessoa aparece: tabela global não é
        # recortada. Se este teste passasse a devolver vazio, seria sinal de que alguém
        # ligou RLS numa tabela que não devia.
        pessoa = await sessao.get(Colaborador, pessoa_id)

    assert pessoa is not None
    assert pessoa.name == "ANA SILVA"


async def test_rota_de_papeis_so_mostra_a_empresa_ativa(
    autenticado: AsyncClient, motor_runtime: AsyncEngine, cenario: Cenario
) -> None:
    pessoa_id = await criar_colaborador_nos_dois(motor_runtime, cenario)

    resposta = await autenticado.get(
        "/api/v1/bakeoff/empresas/papeis",
        headers={"X-Empresa-Id": str(cenario.uva)},
    )

    assert resposta.status_code == 200
    dela = [p for p in resposta.json() if p["colaborador_id"] == str(pessoa_id)]
    assert [p["papel"] for p in dela] == ["operator-sales"]
    assert all(p["empresa_id"] == str(cenario.uva) for p in resposta.json())

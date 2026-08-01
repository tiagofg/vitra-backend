from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.tenancy import declarar_empresa
from app.modules.empresa.models import Empresa, Filial
from tests.cenario import Cenario


async def test_crud_de_empresa(cliente: AsyncClient, cabecalho_admin: dict[str, str]) -> None:
    criado = await cliente.post(
        "/api/v1/empresas",
        json={
            "codigo": "VIAHF",
            "razao_social": "Via HF Iluminação Ltda",
            "nome_fantasia": "Via HF",
            "endereco_cep": "01310-100",
            "endereco_logradouro": "Av. Paulista",
            "endereco_numero": "1000",
            "telefone": "1130000000",
            "instagram": "@viahf",
        },
        headers=cabecalho_admin,
    )
    assert criado.status_code == 201
    corpo = criado.json()
    assert corpo["endereco_logradouro"] == "Av. Paulista"
    assert corpo["instagram"] == "@viahf"
    assert corpo["ativo"] is True

    empresa_id = corpo["id"]
    atualizado = await cliente.put(
        f"/api/v1/empresas/{empresa_id}",
        json={"nome_fantasia": "Via HF Iluminação"},
        headers=cabecalho_admin,
    )
    assert atualizado.status_code == 200
    assert atualizado.json()["nome_fantasia"] == "Via HF Iluminação"
    # PUT parcial não apaga o que não veio no corpo.
    assert atualizado.json()["endereco_logradouro"] == "Av. Paulista"

    desativado = await cliente.delete(f"/api/v1/empresas/{empresa_id}", headers=cabecalho_admin)
    assert desativado.status_code == 200
    assert desativado.json()["ativo"] is False


async def test_codigo_de_empresa_e_unico(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    resposta = await cliente.post(
        "/api/v1/empresas",
        json={"codigo": empresa.codigo, "razao_social": "Outra"},
        headers=cabecalho_admin,
    )
    assert resposta.status_code == 409
    assert resposta.json()["erro"]["campos"] == {"codigo": "já utilizado"}


async def test_empresa_inexistente_da_404(
    cliente: AsyncClient, cabecalho_admin: dict[str, str]
) -> None:
    resposta = await cliente.get(
        "/api/v1/empresas/00000000-0000-0000-0000-000000000000", headers=cabecalho_admin
    )
    assert resposta.status_code == 404
    assert resposta.json()["erro"]["codigo"] == "nao_encontrado"


async def test_filial_e_centro_de_custo_ficam_sob_a_empresa(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    """`filial`/`centro_custo` estão sob RLS: a empresa vem de `X-Empresa-Id`, não do
    corpo — o admin da fixture já tem vínculo com `empresa` (ver `conftest.py`)."""
    cabecalho = {**cabecalho_admin, "X-Empresa-Id": str(empresa.id)}

    filial = await cliente.post(
        "/api/v1/filiais",
        json={"codigo": "001", "nome": "Matriz", "matriz": True},
        headers=cabecalho,
    )
    assert filial.status_code == 201, filial.text
    assert filial.json()["tenant_id"] == str(empresa.id)

    centro = await cliente.post(
        "/api/v1/centros-custo",
        json={"codigo": "CC01", "nome": "Showroom"},
        headers=cabecalho,
    )
    assert centro.status_code == 201, centro.text

    listagem = await cliente.get("/api/v1/filiais", headers=cabecalho)
    assert listagem.json()["total"] == 1


async def test_filial_de_outra_empresa_nao_aparece_no_recorte(
    motor_runtime: AsyncEngine, cenario: Cenario
) -> None:
    """`filial` está sob RLS como qualquer tabela por empresa (S0.5).

    `cliente`/`sessao` conectam como **dono** do banco de teste — que aqui é o superusuário
    do Testcontainers — e por isso ignoram RLS por definição; provar recorte entre
    empresas exige o papel de runtime, o mesmo usado por `test_rls_isolamento.py`. O 403
    de quem não tem vínculo já está coberto para o mecanismo compartilhado
    (`empresa_do_pedido`) em `test_bakeoff_autorizacao.py`, via `/produtos` — não precisa
    ser reprovado tabela por tabela.
    """
    async with AsyncSession(motor_runtime, expire_on_commit=False) as sessao:
        await declarar_empresa(sessao, cenario.abacaxi)
        sessao.add(Filial(tenant_id=cenario.abacaxi, codigo="001", nome="Matriz"))
        await sessao.commit()

    async with AsyncSession(motor_runtime, expire_on_commit=False) as sessao:
        await declarar_empresa(sessao, cenario.uva)
        sessao.add(Filial(tenant_id=cenario.uva, codigo="002", nome="Matriz"))
        await sessao.commit()

    async with AsyncSession(motor_runtime) as sessao:
        await declarar_empresa(sessao, cenario.uva)
        filiais = (await sessao.execute(select(Filial))).scalars().all()

    assert [f.codigo for f in filiais] == ["002"]


async def test_lookup_de_empresa(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    resposta = await cliente.get(
        "/api/v1/empresas/lookup", params={"q": "vertz"}, headers=cabecalho_admin
    )
    assert resposta.status_code == 200
    itens = resposta.json()
    assert len(itens) == 1
    assert itens[0]["codigo"] == "VERTZ"
    assert itens[0]["label"] == "Vertz"

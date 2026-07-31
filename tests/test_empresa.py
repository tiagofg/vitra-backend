from __future__ import annotations

from httpx import AsyncClient

from app.modules.empresa.models import Empresa


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
    filial = await cliente.post(
        "/api/v1/filiais",
        json={
            "empresa_id": str(empresa.id),
            "codigo": "001",
            "nome": "Matriz",
            "matriz": True,
        },
        headers=cabecalho_admin,
    )
    assert filial.status_code == 201

    centro = await cliente.post(
        "/api/v1/centros-custo",
        json={"empresa_id": str(empresa.id), "codigo": "CC01", "nome": "Showroom"},
        headers=cabecalho_admin,
    )
    assert centro.status_code == 201

    listagem = await cliente.get(
        "/api/v1/filiais",
        params={"empresa_id": str(empresa.id)},
        headers=cabecalho_admin,
    )
    assert listagem.json()["total"] == 1


async def test_filial_de_outra_empresa_nao_aparece_no_recorte(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    outra = await cliente.post(
        "/api/v1/empresas",
        json={"codigo": "VIAHF", "razao_social": "Via HF"},
        headers=cabecalho_admin,
    )
    outra_id = outra.json()["id"]

    for empresa_id, codigo in ((str(empresa.id), "001"), (outra_id, "002")):
        await cliente.post(
            "/api/v1/filiais",
            json={"empresa_id": empresa_id, "codigo": codigo, "nome": "Matriz"},
            headers=cabecalho_admin,
        )

    listagem = await cliente.get(
        "/api/v1/filiais", params={"empresa_id": outra_id}, headers=cabecalho_admin
    )
    assert listagem.json()["total"] == 1
    assert listagem.json()["itens"][0]["codigo"] == "002"


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

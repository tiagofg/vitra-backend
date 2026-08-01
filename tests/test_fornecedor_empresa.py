from __future__ import annotations

from datetime import date, timedelta

from httpx import AsyncClient

from app.modules.empresa.models import Empresa


def _cabecalho(cabecalho_admin: dict[str, str], empresa: Empresa) -> dict[str, str]:
    return {**cabecalho_admin, "X-Empresa-Id": str(empresa.id)}


async def _criar_fornecedor(
    cliente: AsyncClient, cabecalho: dict[str, str], codigo: str = "FOR001"
) -> str:
    resposta = await cliente.post(
        "/api/v1/fornecedores",
        json={"codigo": codigo, "razao_social": "Lumini Distribuidora"},
        headers=cabecalho,
    )
    assert resposta.status_code == 201, resposta.text
    return str(resposta.json()["id"])


async def test_abrir_vigencia_sem_historico_anterior(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    cabecalho = _cabecalho(cabecalho_admin, empresa)
    fornecedor_id = await _criar_fornecedor(cliente, cabecalho)

    aberta = await cliente.post(
        f"/api/v1/fornecedores/{fornecedor_id}/empresas-compradoras",
        json={
            "empresa_compradora_id": str(empresa.id),
            "vigencia_inicio": "2026-01-01",
            "motivo": "Cadastro inicial",
        },
        headers=cabecalho,
    )
    assert aberta.status_code == 201, aberta.text
    corpo = aberta.json()
    assert corpo["vigencia_fim"] is None
    assert corpo["empresa_compradora_id"] == str(empresa.id)

    historico = await cliente.get(
        f"/api/v1/fornecedores/{fornecedor_id}/empresas-compradoras", headers=cabecalho
    )
    assert historico.status_code == 200
    assert len(historico.json()) == 1


async def test_abrir_nova_vigencia_fecha_a_anterior(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    """O caso real da aba `Histórico Emp. Comp.`: a vigência muda no tempo, nunca duas
    abertas ao mesmo tempo."""
    cabecalho = _cabecalho(cabecalho_admin, empresa)
    fornecedor_id = await _criar_fornecedor(cliente, cabecalho)

    primeira = await cliente.post(
        f"/api/v1/fornecedores/{fornecedor_id}/empresas-compradoras",
        json={"empresa_compradora_id": str(empresa.id), "vigencia_inicio": "2026-01-01"},
        headers=cabecalho,
    )
    assert primeira.status_code == 201, primeira.text

    segunda = await cliente.post(
        f"/api/v1/fornecedores/{fornecedor_id}/empresas-compradoras",
        json={"empresa_compradora_id": str(empresa.id), "vigencia_inicio": "2026-06-01"},
        headers=cabecalho,
    )
    assert segunda.status_code == 201, segunda.text
    assert segunda.json()["vigencia_fim"] is None

    historico = (
        await cliente.get(
            f"/api/v1/fornecedores/{fornecedor_id}/empresas-compradoras", headers=cabecalho
        )
    ).json()
    assert len(historico) == 2
    fechada = next(item for item in historico if item["id"] == primeira.json()["id"])
    assert fechada["vigencia_fim"] == "2026-05-31"


async def test_nova_vigencia_nao_pode_comecar_antes_da_aberta(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    cabecalho = _cabecalho(cabecalho_admin, empresa)
    fornecedor_id = await _criar_fornecedor(cliente, cabecalho)

    await cliente.post(
        f"/api/v1/fornecedores/{fornecedor_id}/empresas-compradoras",
        json={"empresa_compradora_id": str(empresa.id), "vigencia_inicio": "2026-06-01"},
        headers=cabecalho,
    )

    invalida = await cliente.post(
        f"/api/v1/fornecedores/{fornecedor_id}/empresas-compradoras",
        json={"empresa_compradora_id": str(empresa.id), "vigencia_inicio": "2026-01-01"},
        headers=cabecalho,
    )
    assert invalida.status_code == 422
    assert invalida.json()["erro"]["codigo"] == "vigencia_invalida"


async def test_vigencia_no_futuro_e_rejeitada(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    cabecalho = _cabecalho(cabecalho_admin, empresa)
    fornecedor_id = await _criar_fornecedor(cliente, cabecalho)

    amanha = (date.today() + timedelta(days=1)).isoformat()
    resposta = await cliente.post(
        f"/api/v1/fornecedores/{fornecedor_id}/empresas-compradoras",
        json={"empresa_compradora_id": str(empresa.id), "vigencia_inicio": amanha},
        headers=cabecalho,
    )
    assert resposta.status_code == 422


async def test_fornecedor_inexistente_da_404(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], empresa: Empresa
) -> None:
    cabecalho = _cabecalho(cabecalho_admin, empresa)
    bogus = "00000000-0000-0000-0000-000000000000"

    resposta = await cliente.post(
        f"/api/v1/fornecedores/{bogus}/empresas-compradoras",
        json={"empresa_compradora_id": str(empresa.id), "vigencia_inicio": "2026-01-01"},
        headers=cabecalho,
    )
    assert resposta.status_code == 404

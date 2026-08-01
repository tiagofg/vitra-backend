from __future__ import annotations

from datetime import date, timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.tenancy import declarar_empresa
from app.modules.empresa.models import Empresa
from app.modules.pessoas.models import Fornecedor, FornecedorEmpresa
from app.modules.pessoas.service import FornecedorEmpresaService
from tests.cenario import Cenario


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


async def test_abrir_vigencia_recusa_empresa_compradora_sem_vinculo(
    cliente: AsyncClient,
    cabecalho_admin: dict[str, str],
    empresa: Empresa,
    sessao: AsyncSession,
) -> None:
    """`empresa_compradora_id` é FK simples para `tenants` — tabela **global**, sem RLS.
    Sem checar vínculo, o usuário registraria como compradora qualquer empresa da
    instalação, com ou sem relação nenhuma com ela."""
    rival = Empresa(codigo="RIVAL", razao_social="Rival Iluminação Ltda")
    sessao.add(rival)
    await sessao.flush()

    cabecalho = _cabecalho(cabecalho_admin, empresa)
    fornecedor_id = await _criar_fornecedor(cliente, cabecalho)

    resposta = await cliente.post(
        f"/api/v1/fornecedores/{fornecedor_id}/empresas-compradoras",
        json={"empresa_compradora_id": str(rival.id), "vigencia_inicio": "2026-01-01"},
        headers=cabecalho,
    )
    assert resposta.status_code == 422, resposta.text
    assert resposta.json()["erro"]["codigo"] == "sem_vinculo_com_empresa_compradora"


async def test_fornecedor_empresa_de_outra_empresa_nao_aparece_no_recorte(
    motor_runtime: AsyncEngine, cenario: Cenario
) -> None:
    async with AsyncSession(motor_runtime, expire_on_commit=False) as sessao:
        await declarar_empresa(sessao, cenario.abacaxi)
        fornecedor_abacaxi = Fornecedor(
            tenant_id=cenario.abacaxi,
            codigo=f"FOR-A-{cenario.sufixo}",
            razao_social="Da Abacaxi",
        )
        sessao.add(fornecedor_abacaxi)
        await sessao.flush()
        sessao.add(
            FornecedorEmpresa(
                tenant_id=cenario.abacaxi,
                fornecedor_id=fornecedor_abacaxi.id,
                empresa_compradora_id=cenario.abacaxi,
                vigencia_inicio=date(2026, 1, 1),
            )
        )
        await sessao.commit()

    async with AsyncSession(motor_runtime, expire_on_commit=False) as sessao:
        await declarar_empresa(sessao, cenario.uva)
        fornecedor_uva = Fornecedor(
            tenant_id=cenario.uva, codigo=f"FOR-U-{cenario.sufixo}", razao_social="Da Uva"
        )
        sessao.add(fornecedor_uva)
        await sessao.flush()
        sessao.add(
            FornecedorEmpresa(
                tenant_id=cenario.uva,
                fornecedor_id=fornecedor_uva.id,
                empresa_compradora_id=cenario.uva,
                vigencia_inicio=date(2026, 1, 1),
            )
        )
        await sessao.commit()

    async with AsyncSession(motor_runtime) as sessao:
        await declarar_empresa(sessao, cenario.uva)
        historico = (await sessao.execute(select(FornecedorEmpresa))).scalars().all()

    assert len(historico) == 1
    assert historico[0].tenant_id == cenario.uva


async def test_empresa_compradora_em_resolve_a_vigencia_certa(
    sessao: AsyncSession, empresa: Empresa
) -> None:
    """`empresa_compradora_em` ainda não tem chamador em produção (a S5/compras é quem vai
    usar), mas é a regra de negócio que a aba `Histórico Emp. Comp.` do legado documenta —
    coberta aqui para não ficar código morto sem prova."""
    fornecedor = Fornecedor(tenant_id=empresa.id, codigo="FOR001", razao_social="X")
    sessao.add(fornecedor)
    await sessao.flush()

    sessao.add_all(
        [
            FornecedorEmpresa(
                tenant_id=empresa.id,
                fornecedor_id=fornecedor.id,
                empresa_compradora_id=empresa.id,
                vigencia_inicio=date(2026, 1, 1),
                vigencia_fim=date(2026, 5, 31),
            ),
            FornecedorEmpresa(
                tenant_id=empresa.id,
                fornecedor_id=fornecedor.id,
                empresa_compradora_id=empresa.id,
                vigencia_inicio=date(2026, 6, 1),
                vigencia_fim=None,
            ),
        ]
    )
    await sessao.flush()

    service = FornecedorEmpresaService(sessao, fornecedor.id)
    assert await service.empresa_compradora_em(date(2026, 3, 1)) == empresa.id
    assert await service.empresa_compradora_em(date(2026, 12, 1)) == empresa.id
    assert await service.empresa_compradora_em(date(2025, 12, 31)) is None

"""RBAC que muda conforme a empresa ativa — o que a S0.5 deixava em aberto e a S2 fecha.

Todos os testes aqui passam por `app_bakeoff`/`motor_runtime` (papel de runtime, RLS de
verdade), não pela conexão de dono (`cliente`/`sessao`). É a lição da revisão do PR #7
(rodada 2): uma checagem que consulta tabela sob RLS pode passar pela suíte por acidente
quando testada só pela conexão que ignora a política — e o próprio objetivo destes testes é
provar que "grupo do vínculo, quando existe, decide sozinho" funciona sob a política de
verdade, não só sob uma simulação que a contorna.
"""

from __future__ import annotations

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.tenancy import declarar_empresa
from app.modules.auth.models import Grupo, Permissao, VinculoEmpresa
from tests.cenario import Cenario, criar_usuario_vinculado


async def _permissao(sessao: AsyncSession, recurso: str, acao: str) -> Permissao:
    existente = (
        await sessao.execute(
            select(Permissao).where(Permissao.recurso == recurso, Permissao.acao == acao)
        )
    ).scalar_one_or_none()
    if existente is not None:
        return existente
    nova = Permissao(recurso=recurso, acao=acao, descricao=f"{acao} {recurso}")
    sessao.add(nova)
    await sessao.flush()
    return nova


async def _definir_grupo_do_vinculo(
    motor: AsyncEngine, tenant_id: object, employee_id: object, grupo_id: object
) -> None:
    async with AsyncSession(motor, expire_on_commit=False) as sessao:
        await declarar_empresa(sessao, tenant_id)  # type: ignore[arg-type]
        await sessao.execute(
            update(VinculoEmpresa)
            .where(VinculoEmpresa.tenant_id == tenant_id, VinculoEmpresa.employee_id == employee_id)
            .values(grupo_id=grupo_id)
        )
        await sessao.commit()


async def test_grupo_do_vinculo_decide_sozinho_nao_e_uniao_com_o_global(
    app_bakeoff: FastAPI, motor_runtime: AsyncEngine, cenario: Cenario
) -> None:
    """A mesma pessoa, vinculada às duas empresas, sem grupo global nenhum: um grupo
    específico no vínculo da ABACAXI concede `produto:criar` lá — e **não** vaza para a
    UVA, onde o vínculo não tem grupo (e cai no global, vazio aqui). É a propriedade que
    `VinculoEmpresa.grupo_id` existe para garantir: "admin na ABACAXI" não virar "admin em
    toda parte".
    """
    usuario = await criar_usuario_vinculado(
        motor_runtime,
        cenario,
        empresas=(cenario.abacaxi, cenario.uva),
        sufixo_login="-rbac-uniao",
        com_permissao_produtos=False,
    )

    async with AsyncSession(motor_runtime, expire_on_commit=False) as sessao:
        criar = await _permissao(sessao, "produto", "criar")
        grupo_abacaxi = Grupo(nome=f"RBAC-ABA-{cenario.sufixo}", permissoes=[criar])
        sessao.add(grupo_abacaxi)
        await sessao.flush()
        grupo_id = grupo_abacaxi.id
        await sessao.commit()

    await _definir_grupo_do_vinculo(motor_runtime, cenario.abacaxi, usuario.id, grupo_id)

    transporte = ASGITransport(app=app_bakeoff)
    headers_base = {"Authorization": f"Bearer {usuario.token}"}
    async with AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        criado = await cliente.post(
            "/api/v1/produtos",
            json={"codigo": f"RBAC-A-{cenario.sufixo}", "descricao": "Produto Abacaxi"},
            headers={**headers_base, "X-Empresa-Id": str(cenario.abacaxi)},
        )
        assert criado.status_code == 201, criado.text

        negado = await cliente.post(
            "/api/v1/produtos",
            json={"codigo": f"RBAC-U-{cenario.sufixo}", "descricao": "Produto Uva"},
            headers={**headers_base, "X-Empresa-Id": str(cenario.uva)},
        )

    assert negado.status_code == 403, negado.text
    assert negado.json()["erro"]["codigo"] == "sem_permissao"


async def test_vinculo_sem_grupo_especifico_cai_no_grupo_global(
    app_bakeoff: FastAPI, motor_runtime: AsyncEngine, cenario: Cenario
) -> None:
    """`grupo_id` nulo no vínculo (o padrão, sempre foi assim antes da S2) continua caindo
    nos grupos globais — não pode ser regressão do comportamento que já existia."""
    usuario = await criar_usuario_vinculado(
        motor_runtime,
        cenario,
        empresas=(cenario.abacaxi,),
        sufixo_login="-rbac-fallback",
        com_permissao_produtos=True,
    )

    transporte = ASGITransport(app=app_bakeoff)
    headers = {"Authorization": f"Bearer {usuario.token}", "X-Empresa-Id": str(cenario.abacaxi)}
    async with AsyncClient(
        transport=transporte, base_url="http://teste", headers=headers
    ) as cliente:
        resposta = await cliente.get("/api/v1/produtos")

    assert resposta.status_code == 200, resposta.text


async def test_grupo_do_vinculo_nao_decide_sobre_recurso_global(
    app_bakeoff: FastAPI, motor_runtime: AsyncEngine, cenario: Cenario
) -> None:
    """`usuario` não tem `tenant_id` — é da instalação inteira, não de uma empresa. Um
    grupo de vínculo concedendo `usuario:criar` na ABACAXI não pode virar permissão para
    criar conta na instalação inteira: seria escalada de privilégio, achado de revisão
    (o próprio furo que este PR se propôs a fechar, reaberto na metade global do
    catálogo). `RECURSOS_POR_EMPRESA` existe para `require()` nunca deixar o grupo do
    vínculo decidir sobre `usuario` — só `Usuario.pode()` (grupos globais) pode.
    """
    usuario = await criar_usuario_vinculado(
        motor_runtime,
        cenario,
        empresas=(cenario.abacaxi,),
        sufixo_login="-rbac-global",
        com_permissao_produtos=False,
    )

    async with AsyncSession(motor_runtime, expire_on_commit=False) as sessao:
        criar_usuario_permissao = await _permissao(sessao, "usuario", "criar")
        grupo = Grupo(nome=f"RBAC-GLOBAL-{cenario.sufixo}", permissoes=[criar_usuario_permissao])
        sessao.add(grupo)
        await sessao.flush()
        grupo_id = grupo.id
        await sessao.commit()

    await _definir_grupo_do_vinculo(motor_runtime, cenario.abacaxi, usuario.id, grupo_id)

    transporte = ASGITransport(app=app_bakeoff)
    headers = {"Authorization": f"Bearer {usuario.token}", "X-Empresa-Id": str(cenario.abacaxi)}
    async with AsyncClient(
        transport=transporte, base_url="http://teste", headers=headers
    ) as cliente:
        resposta = await cliente.post(
            "/api/v1/usuarios",
            json={
                "login": f"invasor-{cenario.sufixo}",
                "nome": "Invasor",
                "senha": "senha-bem-forte-123",
                "email": f"invasor-{cenario.sufixo}@grupo.dev",
            },
        )

    assert resposta.status_code == 403, resposta.text
    assert resposta.json()["erro"]["codigo"] == "sem_permissao"


async def test_grupo_do_vinculo_desativado_cai_no_grupo_global(
    app_bakeoff: FastAPI, motor_runtime: AsyncEngine, cenario: Cenario
) -> None:
    """Grupo do vínculo desativado não bloqueia nem concede sozinho — o mesmo efeito de não
    ter grupo específico, espelhando `test_grupo_desativado_nao_concede_permissao` para o
    caso global."""
    usuario = await criar_usuario_vinculado(
        motor_runtime,
        cenario,
        empresas=(cenario.abacaxi,),
        sufixo_login="-rbac-grupo-desativado",
        com_permissao_produtos=True,
    )

    async with AsyncSession(motor_runtime, expire_on_commit=False) as sessao:
        grupo_desativado = Grupo(nome=f"RBAC-DES-{cenario.sufixo}", ativo=False)
        sessao.add(grupo_desativado)
        await sessao.flush()
        grupo_id = grupo_desativado.id
        await sessao.commit()

    await _definir_grupo_do_vinculo(motor_runtime, cenario.abacaxi, usuario.id, grupo_id)

    transporte = ASGITransport(app=app_bakeoff)
    headers = {"Authorization": f"Bearer {usuario.token}", "X-Empresa-Id": str(cenario.abacaxi)}
    async with AsyncClient(
        transport=transporte, base_url="http://teste", headers=headers
    ) as cliente:
        resposta = await cliente.get("/api/v1/produtos")

    # Cai no global (`com_permissao_produtos=True` concedeu `produto:ler`), não no grupo
    # desativado do vínculo — que não tem `permissoes` nenhuma e, se valesse, negaria.
    assert resposta.status_code == 200, resposta.text

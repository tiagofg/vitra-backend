"""`usuario:criar`/`editar`/`excluir` são permissões de cadastro rotineiras — não deviam
bastar para fabricar, promover, rebaixar, redefinir a senha de, desativar ou reativar um
superusuário. As quatro travas (`UsuarioService._antes_de_criar/_antes_de_atualizar/
_antes_de_desativar`, `definir_senha`) saíram sem nenhum teste de regressão na primeira
revisão — e foi exatamente por isso que a de `desativar` ficou de fora sem ninguém notar.
Este arquivo cobre as quatro, mais o caso positivo (superusuário pode).
"""

from __future__ import annotations

from httpx import AsyncClient

from app.modules.auth.models import Permissao, Usuario
from tests.conftest import SENHA_PADRAO, autenticar


async def _cabecalho_comprador(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], permissoes: list[Permissao]
) -> dict[str, str]:
    """Usuário comum com `usuario:criar/editar/excluir` — permissão de cadastro, não de
    superusuário. É contra este perfil que as travas de escalada precisam segurar."""
    grupo = await cliente.post("/api/v1/grupos", json={"nome": "RH"}, headers=cabecalho_admin)
    alvo = [str(p.id) for p in permissoes if p.recurso == "usuario"]
    await cliente.put(
        f"/api/v1/grupos/{grupo.json()['id']}/permissoes",
        json={"permissao_ids": alvo},
        headers=cabecalho_admin,
    )
    await cliente.post(
        "/api/v1/usuarios",
        json={
            "login": "rh",
            "nome": "RH",
            "email": "rh@vertz.teste",
            "senha": SENHA_PADRAO,
            "grupo_ids": [grupo.json()["id"]],
        },
        headers=cabecalho_admin,
    )
    return await autenticar(cliente, "rh")


async def test_comprador_nao_pode_criar_superusuario(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], permissoes: list[Permissao]
) -> None:
    cabecalho_rh = await _cabecalho_comprador(cliente, cabecalho_admin, permissoes)

    resposta = await cliente.post(
        "/api/v1/usuarios",
        json={
            "login": "invasor",
            "nome": "Invasor",
            "email": "invasor@vertz.teste",
            "senha": SENHA_PADRAO,
            "superusuario": True,
        },
        headers=cabecalho_rh,
    )
    assert resposta.status_code == 422, resposta.text
    assert resposta.json()["erro"]["codigo"] == "escalada_de_privilegio"


async def test_comprador_nao_pode_se_autopromover(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], permissoes: list[Permissao]
) -> None:
    cabecalho_rh = await _cabecalho_comprador(cliente, cabecalho_admin, permissoes)
    eu = await cliente.get("/api/v1/auth/eu", headers=cabecalho_rh)
    meu_id = eu.json()["id"]

    resposta = await cliente.put(
        f"/api/v1/usuarios/{meu_id}",
        json={"superusuario": True},
        headers=cabecalho_rh,
    )
    assert resposta.status_code == 422, resposta.text
    assert resposta.json()["erro"]["codigo"] == "escalada_de_privilegio"


async def test_comprador_nao_pode_editar_um_superusuario(
    cliente: AsyncClient,
    cabecalho_admin: dict[str, str],
    admin: Usuario,
    permissoes: list[Permissao],
) -> None:
    cabecalho_rh = await _cabecalho_comprador(cliente, cabecalho_admin, permissoes)

    resposta = await cliente.put(
        f"/api/v1/usuarios/{admin.id}",
        json={"nome": "Nome Trocado"},
        headers=cabecalho_rh,
    )
    assert resposta.status_code == 422, resposta.text
    assert resposta.json()["erro"]["codigo"] == "escalada_de_privilegio"


async def test_comprador_nao_pode_redefinir_senha_de_superusuario(
    cliente: AsyncClient,
    cabecalho_admin: dict[str, str],
    admin: Usuario,
    permissoes: list[Permissao],
) -> None:
    cabecalho_rh = await _cabecalho_comprador(cliente, cabecalho_admin, permissoes)

    resposta = await cliente.post(
        f"/api/v1/usuarios/{admin.id}/senha",
        json={"senha_nova": "senha-forjada-123"},
        headers=cabecalho_rh,
    )
    assert resposta.status_code == 422, resposta.text
    assert resposta.json()["erro"]["codigo"] == "escalada_de_privilegio"


async def test_comprador_nao_pode_desativar_superusuario(
    cliente: AsyncClient,
    cabecalho_admin: dict[str, str],
    admin: Usuario,
    permissoes: list[Permissao],
) -> None:
    """A trava que faltava na revisão anterior: `DELETE` fazia a mesma coisa que `PUT
    {"ativo": false}`, mas só o segundo estava protegido."""
    # Lido antes: a requisição que falha faz rollback na sessão de teste e expira os
    # objetos ORM das fixtures (mesmo padrão de `test_alterar_senha_troca_as_credenciais`).
    login, admin_id = admin.login, admin.id
    cabecalho_rh = await _cabecalho_comprador(cliente, cabecalho_admin, permissoes)

    resposta = await cliente.delete(f"/api/v1/usuarios/{admin_id}", headers=cabecalho_rh)
    assert resposta.status_code == 422, resposta.text
    assert resposta.json()["erro"]["codigo"] == "escalada_de_privilegio"

    # E não desativou de fato: o superusuário continua logando.
    ainda_ativo = await cliente.post(
        "/api/v1/auth/login", json={"login": login, "senha": SENHA_PADRAO}
    )
    assert ainda_ativo.status_code == 200


async def test_comprador_nao_pode_desativar_a_si_mesmo_via_put(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], permissoes: list[Permissao]
) -> None:
    """Espelho do `DELETE` já coberto em `test_usuario_nao_desativa_a_si_mesmo`
    (`test_acesso.py`): `PUT {"ativo": false}` é a mesma transição por outra rota."""
    cabecalho_rh = await _cabecalho_comprador(cliente, cabecalho_admin, permissoes)
    eu = await cliente.get("/api/v1/auth/eu", headers=cabecalho_rh)
    meu_id = eu.json()["id"]

    resposta = await cliente.put(
        f"/api/v1/usuarios/{meu_id}", json={"ativo": False}, headers=cabecalho_rh
    )
    assert resposta.status_code == 422, resposta.text
    assert resposta.json()["erro"]["codigo"] == "regra_de_negocio"


async def test_superusuario_pode_desativar_e_reativar_outro_superusuario(
    cliente: AsyncClient, cabecalho_admin: dict[str, str]
) -> None:
    """Caso positivo: a trava é contra `usuario:excluir` sozinho, não contra
    superusuário nenhum poder mexer em superusuário."""
    outro = await cliente.post(
        "/api/v1/usuarios",
        json={
            "login": "outro-admin",
            "nome": "Outro Admin",
            "email": "outro-admin@vertz.teste",
            "senha": SENHA_PADRAO,
            "superusuario": True,
        },
        headers=cabecalho_admin,
    )
    assert outro.status_code == 201, outro.text
    outro_id = outro.json()["id"]

    desativado = await cliente.delete(f"/api/v1/usuarios/{outro_id}", headers=cabecalho_admin)
    assert desativado.status_code == 200
    assert desativado.json()["ativo"] is False

    reativado = await cliente.post(f"/api/v1/usuarios/{outro_id}/reativar", headers=cabecalho_admin)
    assert reativado.status_code == 200
    assert reativado.json()["ativo"] is True

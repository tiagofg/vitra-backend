from __future__ import annotations

from httpx import AsyncClient

from app.modules.auth.models import Permissao, Usuario
from app.modules.empresa.models import Empresa
from tests.conftest import autenticar


async def test_criar_grupo_e_conceder_permissoes(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], permissoes: list[Permissao]
) -> None:
    grupo = await cliente.post(
        "/api/v1/grupos",
        json={"nome": "Compradores", "descricao": "Setor de compras"},
        headers=cabecalho_admin,
    )
    assert grupo.status_code == 201
    grupo_id = grupo.json()["id"]
    assert grupo.json()["permissoes"] == []

    alvo = [str(p.id) for p in permissoes if p.recurso == "banco"]
    concedido = await cliente.put(
        f"/api/v1/grupos/{grupo_id}/permissoes",
        json={"permissao_ids": alvo},
        headers=cabecalho_admin,
    )
    assert concedido.status_code == 200
    assert {p["recurso"] for p in concedido.json()["permissoes"]} == {"banco"}

    listado = await cliente.get(f"/api/v1/grupos/{grupo_id}/permissoes", headers=cabecalho_admin)
    assert len(listado.json()) == len(alvo)


async def test_put_de_permissoes_substitui_o_conjunto(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], permissoes: list[Permissao]
) -> None:
    grupo = await cliente.post(
        "/api/v1/grupos", json={"nome": "Compradores"}, headers=cabecalho_admin
    )
    grupo_id = grupo.json()["id"]
    bancos = [str(p.id) for p in permissoes if p.recurso == "banco"]
    apoio_ler = [str(p.id) for p in permissoes if p.recurso == "apoio" and p.acao == "ler"]

    await cliente.put(
        f"/api/v1/grupos/{grupo_id}/permissoes",
        json={"permissao_ids": bancos},
        headers=cabecalho_admin,
    )
    final = await cliente.put(
        f"/api/v1/grupos/{grupo_id}/permissoes",
        json={"permissao_ids": apoio_ler},
        headers=cabecalho_admin,
    )
    chaves = {f"{p['recurso']}:{p['acao']}" for p in final.json()["permissoes"]}
    assert chaves == {"apoio:ler"}


async def test_permissao_inexistente_no_grupo_da_404(
    cliente: AsyncClient, cabecalho_admin: dict[str, str]
) -> None:
    grupo = await cliente.post(
        "/api/v1/grupos", json={"nome": "Compradores"}, headers=cabecalho_admin
    )
    resposta = await cliente.put(
        f"/api/v1/grupos/{grupo.json()['id']}/permissoes",
        json={"permissao_ids": ["00000000-0000-0000-0000-000000000000"]},
        headers=cabecalho_admin,
    )
    assert resposta.status_code == 404


async def test_nome_de_grupo_e_unico(cliente: AsyncClient, cabecalho_admin: dict[str, str]) -> None:
    await cliente.post("/api/v1/grupos", json={"nome": "Compras"}, headers=cabecalho_admin)
    repetido = await cliente.post(
        "/api/v1/grupos", json={"nome": "Compras"}, headers=cabecalho_admin
    )
    assert repetido.status_code == 409


async def test_usuario_criado_pela_api_consegue_logar(
    cliente: AsyncClient,
    cabecalho_admin: dict[str, str],
    empresa: Empresa,
    permissoes: list[Permissao],
) -> None:
    grupo = await cliente.post(
        "/api/v1/grupos", json={"nome": "Compradores"}, headers=cabecalho_admin
    )
    await cliente.put(
        f"/api/v1/grupos/{grupo.json()['id']}/permissoes",
        json={"permissao_ids": [str(p.id) for p in permissoes if p.recurso == "banco"]},
        headers=cabecalho_admin,
    )

    criado = await cliente.post(
        "/api/v1/usuarios",
        json={
            "login": "comprador",
            "nome": "Comprador",
            "email": "comprador@vertz.teste",
            "senha": "senha-do-comprador-1",
            "grupo_ids": [grupo.json()["id"]],
        },
        headers=cabecalho_admin,
    )
    assert criado.status_code == 201
    # Chave JSON exata, não a substring solta: campos legítimos do contrato contêm
    # "senha" no nome (`deve_trocar_senha`), e `"senha" not in texto` reprovaria por causa
    # deles sem que nenhum segredo tenha vazado.
    assert '"senha"' not in criado.text
    assert "senha_hash" not in criado.text

    cabecalho = await autenticar(cliente, "comprador", "senha-do-comprador-1")
    eu = await cliente.get("/api/v1/auth/eu", headers=cabecalho)
    assert eu.json()["permissoes"] == [
        "banco:criar",
        "banco:editar",
        "banco:excluir",
        "banco:ler",
    ]

    permitido = await cliente.get("/api/v1/bancos", headers=cabecalho)
    negado = await cliente.get("/api/v1/usuarios", headers=cabecalho)
    assert permitido.status_code == 200
    assert negado.status_code == 403


async def test_login_duplicado_e_conflito(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], admin: Usuario
) -> None:
    resposta = await cliente.post(
        "/api/v1/usuarios",
        json={
            "login": admin.login,
            "nome": "Outro",
            "email": "outro@vertz.teste",
            "senha": "uma-senha-qualquer-1",
        },
        headers=cabecalho_admin,
    )
    assert resposta.status_code == 409


async def test_admin_redefine_senha_de_outro_usuario(
    cliente: AsyncClient, cabecalho_admin: dict[str, str]
) -> None:
    criado = await cliente.post(
        "/api/v1/usuarios",
        json={
            "login": "comprador",
            "nome": "Comprador",
            "email": "comprador@vertz.teste",
            "senha": "senha-antiga-123",
        },
        headers=cabecalho_admin,
    )
    usuario_id = criado.json()["id"]

    resposta = await cliente.post(
        f"/api/v1/usuarios/{usuario_id}/senha",
        json={"senha_nova": "senha-nova-4567"},
        headers=cabecalho_admin,
    )
    assert resposta.status_code == 204

    await autenticar(cliente, "comprador", "senha-nova-4567")


async def test_usuario_nao_desativa_a_si_mesmo(
    cliente: AsyncClient, cabecalho_admin: dict[str, str], admin: Usuario
) -> None:
    resposta = await cliente.delete(f"/api/v1/usuarios/{admin.id}", headers=cabecalho_admin)
    assert resposta.status_code == 422
    assert resposta.json()["erro"]["codigo"] == "regra_de_negocio"


async def test_usuario_desativado_perde_o_acesso(
    cliente: AsyncClient, cabecalho_admin: dict[str, str]
) -> None:
    criado = await cliente.post(
        "/api/v1/usuarios",
        json={
            "login": "comprador",
            "nome": "Comprador",
            "email": "comprador@vertz.teste",
            "senha": "senha-do-comprador-1",
        },
        headers=cabecalho_admin,
    )
    cabecalho = await autenticar(cliente, "comprador", "senha-do-comprador-1")

    await cliente.delete(f"/api/v1/usuarios/{criado.json()['id']}", headers=cabecalho_admin)

    resposta = await cliente.get("/api/v1/auth/eu", headers=cabecalho)
    assert resposta.status_code == 401

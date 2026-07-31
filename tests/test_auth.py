from __future__ import annotations

from httpx import AsyncClient

from app.modules.auth.models import Usuario
from tests.conftest import SENHA_PADRAO


async def test_saude_responde_sem_autenticacao(cliente: AsyncClient) -> None:
    resposta = await cliente.get("/saude")
    assert resposta.status_code == 200
    assert resposta.json()["status"] == "ok"


async def test_login_devolve_par_de_tokens(cliente: AsyncClient, admin: Usuario) -> None:
    resposta = await cliente.post(
        "/api/v1/auth/login", json={"login": admin.login, "senha": SENHA_PADRAO}
    )
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["token_type"] == "bearer"
    assert corpo["access_token"] and corpo["refresh_token"]
    assert corpo["access_token"] != corpo["refresh_token"]


async def test_login_com_senha_errada_nao_revela_o_motivo(
    cliente: AsyncClient, admin: Usuario
) -> None:
    errada = await cliente.post(
        "/api/v1/auth/login", json={"login": admin.login, "senha": "nao-e-essa"}
    )
    inexistente = await cliente.post(
        "/api/v1/auth/login", json={"login": "ninguem", "senha": SENHA_PADRAO}
    )
    assert errada.status_code == inexistente.status_code == 401
    assert errada.json() == inexistente.json()
    assert errada.json()["erro"]["codigo"] == "nao_autenticado"


async def test_login_de_usuario_desativado_falha(
    cliente: AsyncClient, admin: Usuario, sessao
) -> None:
    admin.ativo = False
    await sessao.flush()
    resposta = await cliente.post(
        "/api/v1/auth/login", json={"login": admin.login, "senha": SENHA_PADRAO}
    )
    assert resposta.status_code == 401
    assert "desativado" in resposta.json()["erro"]["mensagem"]


async def test_eu_descreve_o_usuario_e_suas_permissoes(
    cliente: AsyncClient, consultor: Usuario, cabecalho_consultor: dict[str, str]
) -> None:
    resposta = await cliente.get("/api/v1/auth/eu", headers=cabecalho_consultor)
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["login"] == "consultor"
    assert corpo["grupos"] == ["Consultor"]
    assert corpo["permissoes"] == ["apoio:ler"]


async def test_eu_sem_token_devolve_401_no_envelope(cliente: AsyncClient) -> None:
    resposta = await cliente.get("/api/v1/auth/eu")
    assert resposta.status_code == 401
    assert set(resposta.json()["erro"]) == {"codigo", "mensagem", "campos"}


async def test_token_invalido_e_recusado(cliente: AsyncClient) -> None:
    resposta = await cliente.get(
        "/api/v1/auth/eu", headers={"Authorization": "Bearer nao.e.um.jwt"}
    )
    assert resposta.status_code == 401
    assert resposta.json()["erro"]["mensagem"] == "Token inválido."


async def test_refresh_troca_por_novo_access(cliente: AsyncClient, admin: Usuario) -> None:
    login = await cliente.post(
        "/api/v1/auth/login", json={"login": admin.login, "senha": SENHA_PADRAO}
    )
    refresh = login.json()["refresh_token"]

    resposta = await cliente.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert resposta.status_code == 200

    novo = resposta.json()["access_token"]
    conferencia = await cliente.get("/api/v1/auth/eu", headers={"Authorization": f"Bearer {novo}"})
    assert conferencia.status_code == 200


async def test_access_token_nao_serve_de_refresh(cliente: AsyncClient, admin: Usuario) -> None:
    login = await cliente.post(
        "/api/v1/auth/login", json={"login": admin.login, "senha": SENHA_PADRAO}
    )
    resposta = await cliente.post(
        "/api/v1/auth/refresh", json={"refresh_token": login.json()["access_token"]}
    )
    assert resposta.status_code == 401


async def test_alterar_senha_troca_as_credenciais(
    cliente: AsyncClient, admin: Usuario, cabecalho_admin: dict[str, str]
) -> None:
    # O login é lido antes: a requisição que falha faz rollback na sessão de teste e
    # expira os objetos ORM das fixtures.
    login = admin.login
    nova = "outra-senha-forte-1"
    resposta = await cliente.post(
        "/api/v1/auth/alterar-senha",
        json={"senha_atual": SENHA_PADRAO, "senha_nova": nova},
        headers=cabecalho_admin,
    )
    assert resposta.status_code == 204

    antiga = await cliente.post("/api/v1/auth/login", json={"login": login, "senha": SENHA_PADRAO})
    atual = await cliente.post("/api/v1/auth/login", json={"login": login, "senha": nova})
    assert antiga.status_code == 401
    assert atual.status_code == 200


async def test_alterar_senha_exige_a_senha_atual_correta(
    cliente: AsyncClient, cabecalho_admin: dict[str, str]
) -> None:
    resposta = await cliente.post(
        "/api/v1/auth/alterar-senha",
        json={"senha_atual": "chute", "senha_nova": "outra-senha-forte-1"},
        headers=cabecalho_admin,
    )
    assert resposta.status_code == 401


async def test_senha_nova_precisa_ter_tamanho_minimo(
    cliente: AsyncClient, cabecalho_admin: dict[str, str]
) -> None:
    resposta = await cliente.post(
        "/api/v1/auth/alterar-senha",
        json={"senha_atual": SENHA_PADRAO, "senha_nova": "curta"},
        headers=cabecalho_admin,
    )
    assert resposta.status_code == 422
    assert resposta.json()["erro"]["codigo"] == "validacao"

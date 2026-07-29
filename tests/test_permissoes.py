from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Acao, pares_do_catalogo, require
from app.modules.auth.models import Grupo, Permissao, Usuario


async def test_permissao_bloqueia_rota_mutante(
    cliente: AsyncClient, cabecalho_consultor: dict[str, str]
) -> None:
    """O consultor tem `apoio:ler` e mais nada — criar tem que dar 403."""
    resposta = await cliente.post(
        "/api/v1/apoio/marca", json={"descricao": "Lumini"}, headers=cabecalho_consultor
    )
    assert resposta.status_code == 403
    erro = resposta.json()["erro"]
    assert erro["codigo"] == "sem_permissao"
    assert erro["campos"] == {"recurso": "apoio", "acao": "criar"}


async def test_permissao_de_leitura_concedida_passa(
    cliente: AsyncClient, cabecalho_consultor: dict[str, str]
) -> None:
    resposta = await cliente.get("/api/v1/apoio/marca", headers=cabecalho_consultor)
    assert resposta.status_code == 200


async def test_recurso_fora_do_grupo_e_bloqueado(
    cliente: AsyncClient, cabecalho_consultor: dict[str, str]
) -> None:
    resposta = await cliente.get("/api/v1/usuarios", headers=cabecalho_consultor)
    assert resposta.status_code == 403
    assert resposta.json()["erro"]["campos"]["recurso"] == "usuario"


async def test_superusuario_atravessa_tudo(
    cliente: AsyncClient, cabecalho_admin: dict[str, str]
) -> None:
    for caminho in ("/api/v1/usuarios", "/api/v1/grupos", "/api/v1/empresas"):
        resposta = await cliente.get(caminho, headers=cabecalho_admin)
        assert resposta.status_code == 200, caminho


async def test_permissao_concedida_em_tempo_de_execucao_libera(
    cliente: AsyncClient,
    sessao: AsyncSession,
    consultor: Usuario,
    permissoes: list[Permissao],
    cabecalho_consultor: dict[str, str],
) -> None:
    grupo = consultor.grupos[0]
    criar = next(p for p in permissoes if p.recurso == "apoio" and p.acao == "criar")
    grupo.permissoes = [*grupo.permissoes, criar]
    await sessao.flush()

    resposta = await cliente.post(
        "/api/v1/apoio/marca", json={"descricao": "Lumini"}, headers=cabecalho_consultor
    )
    assert resposta.status_code == 201


async def test_grupo_desativado_nao_concede_permissao(
    cliente: AsyncClient,
    sessao: AsyncSession,
    consultor: Usuario,
    cabecalho_consultor: dict[str, str],
) -> None:
    consultor.grupos[0].ativo = False
    await sessao.flush()

    resposta = await cliente.get("/api/v1/apoio/marca", headers=cabecalho_consultor)
    assert resposta.status_code == 403


async def test_require_recusa_permissao_fora_do_catalogo() -> None:
    """Erro de digitação em `require(...)` estoura na importação, não em produção."""
    with pytest.raises(KeyError):
        require("recurso_que_nao_existe", Acao.ler)


async def test_catalogo_nao_tem_duplicatas() -> None:
    pares = pares_do_catalogo()
    assert len(pares) == len(set(pares))


async def test_permissoes_efetivas_somam_grupos(
    sessao: AsyncSession, consultor: Usuario, permissoes: list[Permissao]
) -> None:
    outro = Grupo(nome="Compradores")
    outro.permissoes = [p for p in permissoes if p.recurso == "banco"]
    sessao.add(outro)
    consultor.grupos = [*consultor.grupos, outro]
    await sessao.flush()

    efetivas = consultor.permissoes_efetivas()
    assert "apoio:ler" in efetivas
    assert "banco:criar" in efetivas
    assert consultor.pode("banco", "editar")
    assert not consultor.pode("usuario", "editar")
